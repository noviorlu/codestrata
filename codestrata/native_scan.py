"""C / C++ / CUDA 的扫描端：tree-sitter 认语法，名字按文本对（近似档）。

一份「分片」交给 scan 装进同一个 index：
  units    文件 → {loc, classes, funcs, lang}：每个原生源文件一个单元（id 是相对仓库根的路径，不给 label，按路径显示）
  symbols  符号键 <路径>#<限定名> → 符号（k 是 class / func / kernel；kernel 是 CUDA 的 __global__；n 用 :: 分段）
  includes [[从, 到]]：#include "…" 解析到仓库里的文件（只当排版的权重，和 Python 的 import 一样）
  calls    {调用方: [[被调方, 行, 末行, 种类]]}：按名字对上、只有一个候选的调用；种类 0 调用、7 启动 kernel（k<<<…>>>(…)）
  sites    {调用方: [[名字, 行, 末行, 种类]]}：对不上的（0 有好几个候选——宁可不连也不连错；6 仓库里没有这个名字）
  file_sha 内容哈希（和 runs.sha16 同一种）

名字怎么对：被调的名字取最后一段（`qmk::decode_kernel` → decode_kernel、`gemm_task<true>` → gemm_task、
`obj.f` / `p->f` → f），在仓库的原生符号里找同名的函数 / kernel；写了限定（a::b）就要求符号的限定名以它结尾。
还剩好几个时，依次只留同一个文件的、本文件 #include 得到的（传递）文件里的；仍然不止一个就不连。
同一个文件里同名的几个定义（重载）共用一个符号键，另几个记在 `a` 里（和 Python 的同名 def 一样）。

不认：宏展开出来的定义和调用、模板实例化、虚函数分派、函数指针。tree-sitter 认不了的写法（`__align__(n)`、
`#pragma`）先换成等长的空白再解析，行号和字节位置不变。
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

CALL, EXT, LAUNCH = 0, 6, 7            # 和 graph.py 的种类同一套编号
LANG = {".c": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".h": "cpp", ".hh": "cpp", ".hpp": "cpp",
        ".hxx": "cpp", ".inl": "cpp", ".cu": "cuda", ".cuh": "cuda"}
# tree-sitter 认不了、对我们又没有信息的写法，换成等长的空白：`__align__(n)`；`#pragma unroll` 夹在
# `for (…)` 和不带花括号的循环体中间（CUDA 里很常见）会让整个语句解析失败
_BLANK = re.compile(rb"__align__\s*\([^()]*\)|^[ \t]*#[ \t]*pragma[^\n]*", re.M)
_SCOPES = ("namespace_definition", "class_specifier", "struct_specifier", "union_specifier")


def available() -> str | None:
    """装没装 tree-sitter 和 CUDA 语法；没装时返回说明，装了是 None"""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_cuda  # noqa: F401
    except ImportError:
        return "没装 tree-sitter / tree-sitter-cuda（pip install 'codestrata[native]'），C / C++ / CUDA 文件不进图"
    return None


def _parser():
    import tree_sitter as ts
    import tree_sitter_cuda as tc
    return ts.Parser(ts.Language(tc.language()))


def is_native(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in LANG


def scan_files(root: Path, rels: list[str]) -> dict:
    """rels：要扫的原生文件（相对仓库根）。返回分片（见模块说明）；没装 tree-sitter 时抛 RuntimeError"""
    why = available()
    if why:
        raise RuntimeError(why)
    parser = _parser()
    parsed: dict[str, tuple] = {}
    out = {"units": {}, "symbols": {}, "includes": [], "calls": {}, "sites": {}, "file_sha": {}, "errors": {}}
    for rel in sorted(rels):
        try:
            raw = (root / rel).read_bytes()
        except OSError as e:
            out["errors"][rel] = str(e)
            continue
        out["file_sha"][rel] = hashlib.sha256(raw).hexdigest()[:16]
        src = _BLANK.sub(lambda m: b" " * len(m.group(0)), raw)
        tree = parser.parse(src)
        f = _File(rel, src)
        f.walk(tree.root_node, [])
        parsed[rel] = (f, tree)
        out["units"][rel] = {"loc": raw.count(b"\n") + 1, "lang": LANG[os.path.splitext(rel)[1].lower()],
                             "classes": sum(1 for s in f.symbols if s["k"] == "class"),
                             "funcs": sum(1 for s in f.symbols if s["k"] != "class")}
        if tree.root_node.has_error:
            out["errors"][rel] = "有 tree-sitter 认不了的地方（多半是宏），那几处的定义 / 调用可能缺"
        for s in f.symbols:
            key = f"{rel}#{s['n']}"
            if key in out["symbols"]:                  # 同一个文件里同名的另一个定义（重载）
                out["symbols"][key].setdefault("a", []).append([s["l"], s.get("dl", s["l"]), s["e"]])
            else:
                out["symbols"][key] = s
    files = set(parsed)
    inc = {rel: [t for t in (_resolve_include(root, rel, name, files) for name in f.includes) if t]
           for rel, (f, _) in parsed.items()}
    out["includes"] = sorted({(a, b) for a, bs in inc.items() for b in bs if a != b})
    names = _NameTable(out["symbols"], inc)
    for rel, (f, _) in parsed.items():
        for caller, name, qual, l, e, kind in f.calls:
            target = names.resolve(rel, name, qual)
            if target:
                out["calls"].setdefault(caller, []).append([target, l, e, kind])
            else:
                why = CALL if names.known(name) else EXT
                out["sites"].setdefault(caller, []).append([qual or name, l, e, kind if kind == LAUNCH else why])
    return out


class _File:
    """走一个文件的语法树：定义（带命名空间 / 类的限定名、起止行）、调用和启动、#include"""

    def __init__(self, rel: str, src: bytes):
        self.rel, self.src = rel, src
        self.symbols: list[dict] = []
        self.calls: list[tuple] = []       # (调用方键, 名字, 写的限定名, 行, 末行, 种类)
        self.includes: list[str] = []

    def text(self, n) -> str:
        return self.src[n.start_byte:n.end_byte].decode("utf-8", "replace")

    def walk(self, n, scope: list[str]) -> None:
        t = n.type
        if t == "preproc_include":
            p = n.child_by_field_name("path")
            if p is not None and p.type == "string_literal":
                self.includes.append(self.text(p).strip('"'))
            return
        if t == "function_definition":
            self._function(n, scope)
            return
        if t in _SCOPES:
            name = n.child_by_field_name("name")
            body = n.child_by_field_name("body")
            if body is not None:
                inner = scope + ([self.text(name)] if name is not None else [])
                if name is not None and t != "namespace_definition":
                    self.symbols.append(self._sym("::".join(inner), "class", n))
                for c in body.children:
                    self.walk(c, inner)
                return
        for c in n.children:
            self.walk(c, scope)

    def _sym(self, qname: str, kind: str, n, dl: int | None = None) -> dict:
        l = n.start_point[0] + 1
        d = {"n": qname, "s": qname.rsplit("::", 1)[-1], "k": kind, "f": self.rel, "l": l,
             "e": n.end_point[0] + 1, "p": self.rel, "lang": LANG[os.path.splitext(self.rel)[1].lower()]}
        if dl and dl != l:
            d["dl"] = dl
        return d

    def _function(self, n, scope: list[str]) -> None:
        decl = _declarator_name(n.child_by_field_name("declarator"))
        if decl is None:                   # struct __align__(…) X {…} 这类被认成函数的、函数指针：不是函数
            return
        name = self.text(decl)
        name = re.sub(r"<.*>$", "", name)                      # 模板特化 f<int>：按 f 算
        qname = "::".join(scope + [name]) if not name.startswith("::") else name[2:]
        kernel = any(c.type == "__global__" for c in n.children)
        tpl = n.parent if n.parent is not None and n.parent.type == "template_declaration" else None
        sym = self._sym(qname, "kernel" if kernel else "func", n, dl=(tpl.start_point[0] + 1) if tpl else None)
        self.symbols.append(sym)
        key = f"{self.rel}#{qname}"
        body = n.child_by_field_name("body")
        if body is not None:
            self._calls(body, key)

    def _calls(self, n, caller: str) -> None:
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            name, qual = _callee_name(self, fn)
            if name:
                launch = any(c.type == "kernel_call_syntax" for c in n.children)
                self.calls.append((caller, name, qual, n.start_point[0] + 1, n.end_point[0] + 1,
                                   LAUNCH if launch else CALL))
        for c in n.children:
            self._calls(c, caller)


def _declarator_name(d):
    """function_definition 的 declarator 一路剥到函数名那个节点（identifier / qualified_identifier / …）"""
    while d is not None:
        if d.type == "function_declarator":
            inner = d.child_by_field_name("declarator")
            if inner is not None and inner.type in ("identifier", "qualified_identifier", "field_identifier",
                                                    "destructor_name", "operator_name", "template_function"):
                return inner
            return None
        d = d.child_by_field_name("declarator")
    return None


_CASTS = {"static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "sizeof", "alignof", "decltype"}


def _callee_name(f: _File, fn) -> tuple[str | None, str | None]:
    """调用的被调名字：(最后一段, 写出来的限定名或 None)。转型、调用的结果再调用、下标调用等没有名字"""
    if fn is None:
        return None, None
    if fn.type == "template_function":
        fn = fn.child_by_field_name("name") or fn
    if fn.type == "identifier":
        name = f.text(fn)
        return (None, None) if name in _CASTS else (name, None)
    if fn.type == "qualified_identifier":
        full = re.sub(r"<[^<>]*>", "", f.text(fn)).replace(" ", "")
        return full.rsplit("::", 1)[-1], full.lstrip(":")
    if fn.type == "field_expression":
        fld = fn.child_by_field_name("field")
        if fld is not None:
            return re.sub(r"<.*>$", "", f.text(fld)), None
    return None, None


def _resolve_include(root: Path, rel: str, name: str, files: set[str]) -> str | None:
    """#include "x.h"：先找包含它的文件所在目录，再找扫描到的文件里路径以它结尾的唯一一个"""
    here = os.path.normpath(os.path.join(os.path.dirname(rel), name))
    if here in files:
        return here
    hits = [p for p in files if p == name or p.endswith("/" + name)]
    return hits[0] if len(hits) == 1 else None


class _NameTable:
    """按名字找被调的原生函数 / kernel（近似）"""

    def __init__(self, symbols: dict, includes: dict[str, list[str]]):
        self.by_name: dict[str, list[str]] = {}
        for key, s in symbols.items():
            if s["k"] in ("func", "kernel"):
                self.by_name.setdefault(s["s"], []).append(key)
        self.symbols = symbols
        self.reach = {f: _closure(f, includes) for f in includes}

    def known(self, name: str) -> bool:
        return name in self.by_name

    def resolve(self, rel: str, name: str, qual: str | None) -> str | None:
        cands = self.by_name.get(name) or []
        if qual and "::" in qual:
            cands = [k for k in cands if self.symbols[k]["n"] == qual or self.symbols[k]["n"].endswith("::" + qual)]
        if len(cands) > 1:
            same = [k for k in cands if self.symbols[k]["f"] == rel]
            seen = self.reach.get(rel, set())
            cands = same or [k for k in cands if self.symbols[k]["f"] in seen] or cands
        return cands[0] if len(cands) == 1 else None


def _closure(start: str, includes: dict[str, list[str]]) -> set[str]:
    out, todo = set(), [start]
    while todo:
        f = todo.pop()
        for g in includes.get(f, ()):
            if g not in out:
                out.add(g)
                todo.append(g)
    return out
