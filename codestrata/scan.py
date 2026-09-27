"""静态扫描：用 ast 遍历一个 Python 仓库，产出总图需要的一切。

只用标准库。产出两个文件：

  index.json（画总图要的，小）
    packages   聚合单位（默认二级包，如 vllm_omni.engine），含「架构高度」
    edges      包之间的 import 边，权重 = import 语句条数
  symbols.json（按需加载，大）
    symbols    每个类/函数的 file:line、结束行、基类、所属包
    files      文件 → 包的映射，给 runtime tracer 反查用
    aux        包目录里的 C/C++/CUDA 文件 → 包
    edge_sites 每条边背后的 import 语句
    edge_uses  每条边上实际引用了对方的哪些符号、在哪一行
    edge_dead  导入了但从没引用的名字，以及原因
    docs       作者写的文档 → 包（包内 README、frontmatter 声明了代码路径的设计文档）

「架构高度」= (出边 − 入边) / (出边 + 入边)，范围 [-1, +1]：

    +1  谁都不依赖它，它依赖一切  → 入口层（CLI、API server）
     0  双向都多                  → 中间层（引擎、调度）
    -1  只被依赖，自己不依赖别人  → 叶子工具（协议定义、metrics）

为什么不用拓扑排序或 SCC 缩点：Python 仓库普遍存在循环 import。在 vllm-omni 上
30 个二级包有 20 个塌进同一个强连通分量，缩点之后分层信息全部丢失；而最长路径
分层会退化成一条 19 层、每层一个包的链。出入度比值反而稳定且符合架构直觉。
"""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", ".tox", ".venv", "venv", "env",
    "node_modules", "build", "dist", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".eggs", "site-packages",
}

# 包目录里的 C/C++/CUDA 源文件：挂在所在的包下供浏览，不参与 import 图
AUX_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".cu", ".cuh"}

# 这些顶层目录默认不进总图。它们 import 一切、却几乎无人 import，
# 算进去会把「架构高度」彻底冲掉：在 vllm-omni 上，把 tests/ 算进来会让
# entrypoints 从 +0.85 掉到 -0.33（因为测试大量 import 它，入度暴涨）。
# 注意 examples/ 仍然是 hot 图的 case 来源，只是不参与静态图与高度计算。
NON_LIB_DIRS = {
    "tests", "test", "testing", "examples", "example", "samples",
    "benchmarks", "benchmark", "bench", "docs", "doc", "scripts",
    "tools", "ci", "buildkite",
}


# 带语句体的节点：只有这些内部才可能出现 def / class。
# 用 getattr 兜住不同 Python 版本的差异（TryStar 是 3.11+，Match 是 3.10+）。
_STMT_CONTAINERS = tuple(t for t in (
    ast.Module, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
    ast.Try, getattr(ast, "TryStar", None), getattr(ast, "Match", None),
    getattr(ast, "match_case", None), ast.ExceptHandler,
) if t is not None)


@dataclass
class Symbol:
    """一个类或函数的定义点。"""
    name: str            # 限定名，如 DuplexOmni 或 OmniBase._create_engine
    kind: str            # "class" | "func"
    file: str            # 相对仓库根
    line: int            # def/class 所在行
    dline: int           # 第一个装饰器所在行（无装饰器时等于 line）
    module: str          # 点分模块名
    pkg: str             # 聚合用的包名
    bases: list[str] = field(default_factory=list)
    end: int = 0         # 最后一行；runtime 里的闭包 / lambda 靠它归到外层符号

    def key(self) -> str:
        return f"{self.module}:{self.name}"

    def as_json(self) -> dict:
        d = {"n": self.name, "k": self.kind, "f": self.file, "l": self.line,
             "m": self.module, "p": self.pkg}
        if self.dline != self.line:
            d["dl"] = self.dline
        if self.bases:
            d["b"] = self.bases
        if self.end:
            d["e"] = self.end
        return d


def _use(store: dict, a: str, b: str, sym: str, f: str, line: int) -> None:
    """记一次跨包使用。同一行重复出现（a.x.y 链）只记一次。"""
    if not b or a == b:
        return
    lst = store.setdefault((a, b), {}).setdefault(sym, [])
    if not lst or lst[-1] != [f, line]:
        lst.append([f, line])


def iter_py_files(root: Path) -> Iterable[Path]:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fn:
            if f.endswith(".py"):
                yield Path(dp) / f


def detect_roots(root: Path) -> list[str]:
    """猜仓库里哪些顶层目录是 Python 包。

    优先取带 __init__.py 的顶层目录；没有就退化为「含 .py 最多的顶层目录」，
    这样 src-layout 和扁平 layout 都能覆盖。
    """
    pkgs = [p.name for p in root.iterdir()
            if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")
            and (p / "__init__.py").exists()]
    lib = [n for n in pkgs if n not in NON_LIB_DIRS]
    if lib:
        return sorted(lib)          # 只要有真正的库包，就忽略 tests/examples
    if pkgs:
        return sorted(pkgs)
    # src-layout: root/src/<pkg>/__init__.py
    src = root / "src"
    if src.is_dir():
        inner = [p.name for p in src.iterdir()
                 if p.is_dir() and (p / "__init__.py").exists()]
        if inner:
            return sorted(f"src/{n}" for n in inner)
    counts: dict[str, int] = {}
    for f in iter_py_files(root):
        rel = f.relative_to(root).parts
        if len(rel) > 1:
            counts[rel[0]] = counts.get(rel[0], 0) + 1
    return [max(counts, key=counts.get)] if counts else []


# 设计文档在 frontmatter 里声明自己管哪些代码（vllm-omni 的 docs/design 就是这样），
# 这几个键下面的列表项是仓库内路径（文件、目录或 dir/**）
DOC_PATH_KEYS = {"primary_code_paths": "primary", "code_paths": "primary",
                 "related_code_paths": "related"}


def collect_docs(root: Path, files: dict[str, str]) -> dict[str, list]:
    """把作者写的文档挂到包上：包目录里的 README，和 frontmatter 声明了代码路径的设计文档。

    解读层最缺的是「为什么」，而作者往往在文档里写过。输入包和详情面板会列出它们，
    让写解读的人或 agent 先读作者自己的说法，而不是从命名去猜。
    """
    dir_pkg: dict[str, str] = {}
    for rel, pkg in files.items():
        dir_pkg.setdefault(os.path.dirname(rel), pkg)
    out: dict[str, dict] = {}

    rank = {"readme": 0, "primary": 1, "related": 2, "mentions": 3}

    def paths_to_pkgs(path: str) -> set[str]:
        path = path.removesuffix("/**").removesuffix("/*").rstrip("/")
        if path in files:
            return {files[path]}
        return {pkg for fr, pkg in files.items()
                if fr.startswith(path + "/") or fr.startswith(path + ".")}

    def add(pkg: str, rel: str, kind: str, title: str) -> None:
        cur = out.setdefault(pkg, {}).get(rel)
        if cur is None or rank[kind] < rank[cur["kind"]]:
            out[pkg][rel] = {"f": rel, "kind": kind, "title": title}

    n = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fn:
            if not f.lower().endswith(".md"):
                continue
            n += 1
            if n > 5000:
                break
            p = Path(dp, f)
            rel = str(p.relative_to(root))
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), f)
            if f.lower().startswith("readme"):
                pkg = dir_pkg.get(os.path.dirname(rel))
                if pkg:
                    add(pkg, rel, "readme", title)
            if not text.startswith("---"):
                # 没有 frontmatter 的设计文档常在开头一段写「本文负责 `pkg/sub/**`」：
                # 开头 40 行里用反引号写出的仓库路径算「提到」（最弱的一档）
                head = "\n".join(text.splitlines()[:40])
                for m in re.finditer(r"`([\w./*-]+/[\w./*-]+)`", head):
                    for pkg in paths_to_pkgs(m.group(1)):
                        add(pkg, rel, "mentions", title)
                continue
            end = text.find("\n---", 3)
            if end < 0:
                continue
            kind = None
            for line in text[3:end].splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if not line.startswith((" ", "\t", "-")):          # 新的顶层键
                    k = s.split(":", 1)[0].strip()
                    kind = DOC_PATH_KEYS.get(k)
                    if k == "title":
                        title = s.split(":", 1)[1].strip().strip('"') or title
                    continue
                if kind and s.startswith("- "):
                    for pkg in paths_to_pkgs(s[2:].strip().strip('"').strip("'")):
                        add(pkg, rel, kind, title)
    return {pkg: sorted(v.values(), key=lambda d: (rank[d["kind"]], d["f"]))
            for pkg, v in out.items()}


def module_of(rel: Path) -> str:
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        parts.pop()
    elif parts:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def scan(root: Path, depth: int = 2, roots: list[str] | None = None,
         include_non_lib: bool = False, expand: list[str] | None = None) -> dict:
    """扫描仓库，返回 index 字典。

    depth 是聚合粒度：2 表示把 a.b.c.d 归到 a.b。包太多时调大，太笼统时调小。

    expand 是「只把这几个包往下拆一层」：大仓库里往往只有一两个包大到看不清
    （vllm-omni 的 model_executor.models 是 45 个模型族挤在一个框里），整体加深
    depth 又会让其余部分碎成几百个节点。被展开的包，**子目录**各自成为节点，
    直接放在它下面的散文件仍归它自己——否则会炸出一堆文件级的小节点。
    """
    root = root.resolve()
    roots = roots or detect_roots(root)
    if not include_non_lib:
        roots = [r for r in roots if r.split("/")[-1] not in NON_LIB_DIRS] or roots
    if not roots:
        raise SystemExit(f"在 {root} 下没找到 Python 包；用 --roots 手动指定")
    # 顶层包名集合，用来判断一条 import 是不是「内部依赖」
    top = {r.split("/")[-1] for r in roots}

    symbols: dict[str, Symbol] = {}
    files: dict[str, str] = {}
    pkg_files: dict[str, int] = {}
    pkg_loc: dict[str, int] = {}
    pkg_cls: dict[str, int] = {}
    pkg_fn: dict[str, int] = {}
    edges: dict[tuple[str, str], int] = {}
    edge_sites: dict[tuple[str, str], list] = {}
    edge_uses: dict[tuple[str, str], dict] = {}
    edge_dead: dict[tuple[str, str], list] = {}
    n_files = n_err = 0

    expand = sorted(expand or [], key=lambda p: -p.count("."))    # 最具体的前缀优先
    # 哪些点分名是「目录包」（有 __init__.py）：展开时只有它们能成为节点
    pkg_dirs: set[str] = set()
    if expand:
        for r in roots:
            base = root / r
            if base.exists():
                for p in iter_py_files(base):
                    if p.name == "__init__.py":
                        pkg_dirs.add(module_of(p.relative_to(base.parent)))

    def pkg_of(module: str) -> str:
        for pre in expand:
            if module == pre or module.startswith(pre + "."):
                n = pre.count(".") + 1
                parts = module.split(".")
                if len(parts) > n + 1 or (len(parts) == n + 1 and module in pkg_dirs):
                    return ".".join(parts[:n + 1])
                return pre
        return ".".join(module.split(".")[:depth])

    for r in roots:
        base = root / r
        if not base.exists():
            continue
        # 模块名相对于包根的**父目录**算，文件路径仍相对仓库根。
        # src-layout（src/mypkg/...）下若相对仓库根算，模块名会变成 src.mypkg.x，
        # 而代码里写的是 import mypkg.x——所有边都指向不存在的包，图上一条边都画不出来。
        mod_base = base.parent
        for path in iter_py_files(base):
            rel = path.relative_to(root)
            n_files += 1
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except (SyntaxError, ValueError, OSError):
                n_err += 1
                continue
            module = module_of(path.relative_to(mod_base))
            pkg = pkg_of(module)
            files[str(rel)] = pkg
            pkg_files[pkg] = pkg_files.get(pkg, 0) + 1
            pkg_loc[pkg] = pkg_loc.get(pkg, 0) + src.count("\n") + 1

            # 符号：类与顶层/类内函数，带限定名
            def walk(node: ast.AST, prefix: str = "") -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.ClassDef):
                        qn = f"{prefix}{child.name}"
                        bases = []
                        for b in child.bases:
                            try:
                                bases.append(ast.unparse(b))
                            except Exception:
                                pass
                        dl = min([d.lineno for d in child.decorator_list] + [child.lineno])
                        s = Symbol(qn, "class", str(rel), child.lineno, dl, module, pkg, bases,
                                   child.end_lineno or 0)
                        symbols[s.key()] = s
                        pkg_cls[pkg] = pkg_cls.get(pkg, 0) + 1
                        walk(child, qn + ".")
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qn = f"{prefix}{child.name}"
                        dl = min([d.lineno for d in child.decorator_list] + [child.lineno])
                        s = Symbol(qn, "func", str(rel), child.lineno, dl, module, pkg,
                                   end=child.end_lineno or 0)
                        symbols[s.key()] = s
                        pkg_fn[pkg] = pkg_fn.get(pkg, 0) + 1
                        walk(child, qn + ".")
                    elif isinstance(child, _STMT_CONTAINERS):
                        # def/class 只能出现在语句位置，所以只需下潜进「带语句体的节点」。
                        # 早先只白名单了 If/Try/With，for 循环体里的嵌套函数全漏了
                        # （codestrata 自扫描时这一个漏洞吃掉 86 次调用）；
                        # 但换成无条件递归又会退化成遍历整棵 AST（含表达式子树），
                        # 在 vllm-omni 上慢一个量级。白名单语句容器兼顾两者。
                        walk(child, prefix)

            walk(tree)

            # 包级 import 边（只算内部依赖）
            bound: dict[str, dict] = {}
            # `if TYPE_CHECKING:` 里的 import 只服务于类型标注，而且常写成字符串标注，
            # AST 里看不到 Name 引用——不能因此判成死 import
            typeonly: set[int] = set()
            for n2 in ast.walk(tree):
                if isinstance(n2, ast.If):
                    t = n2.test
                    if (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or \
                       (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"):
                        for n3 in n2.body:
                            for n4 in ast.walk(n3):
                                if isinstance(n4, (ast.Import, ast.ImportFrom)):
                                    typeonly.add(id(n4))
            is_init = rel.name == "__init__.py"
            chains: dict[str, dict] = {}
            src_lines = src.split("\n")
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        # 相对 import。先算出“点号指向的那个包”
                        up = module.split(".")
                        up = up[: max(0, len(up) - node.level)]
                        base = ".".join(up)
                        if node.module:
                            # from .layout import x  →  <base>.layout
                            targets.append(f"{base}.{node.module}" if base else node.module)
                        else:
                            # from . import layout, render  →  <base>.layout, <base>.render
                            # 这里必须看 names：早先版本只取 base，于是所有
                            # `from . import X` 都塌成指向包自己的边，模块间依赖全丢。
                            for a in node.names:
                                targets.append(f"{base}.{a.name}" if base else a.name)
                    elif node.module and node.module.split(".")[0] in top:
                        targets.append(node.module)
                        # from pkg.mod import Thing —— Thing 也可能是子模块，
                        # 但无法静态区分，按模块算即可（粒度聚合后无差别）
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] in top:
                            targets.append(a.name)
                if not targets:
                    continue
                names = [a.name for a in node.names]
                try:
                    stmt = ast.unparse(node)
                except Exception:
                    stmt = ""
                for target in targets:
                    if not target:
                        continue
                    dst = pkg_of(target)
                    if dst and dst != pkg and dst.split(".")[0] in top:
                        edges[(pkg, dst)] = edges.get((pkg, dst), 0) + 1
                        # 点开一条边时要看到「具体用了对方的哪些东西、在哪一行」
                        edge_sites.setdefault((pkg, dst), []).append({
                            "f": str(rel), "l": node.lineno, "s": stmt[:200],
                            "m": target, "n": names[:12]})
                        # 记下这条 import 在本文件里引入的本地名字，第二遍用来找「实际用到了什么」
                        why = ("type" if id(node) in typeonly
                               else "reexport" if is_init else None)
                        if isinstance(node, ast.ImportFrom):
                            for a in node.names:
                                if a.name == "*":
                                    continue            # 通配导入无法追踪
                                local = a.asname or a.name
                                if node.module is None:
                                    # from . import payload as _payload → _payload 是模块别名
                                    bound[local] = {"kind": "mod", "sym": target, "dst": dst,
                                                    "line": node.lineno, "orig": a.name, "why": why}
                                else:
                                    # from x.y import Name → Name 可能是符号，也可能是子模块
                                    bound[local] = {"kind": "name", "sym": f"{target}:{a.name}",
                                                    "dst": dst, "line": node.lineno,
                                                    "orig": a.name, "why": why}
                        else:
                            for a in node.names:
                                if a.asname:
                                    bound[a.asname] = {"kind": "mod", "sym": a.name, "dst": dst,
                                                       "line": node.lineno, "orig": a.name, "why": why}
                                elif "." in a.name:
                                    # import a.b.c：绑定的是根名 a，使用形如 a.b.c.X。
                                    # 没有任何这样的使用时，几乎总是为了副作用（注册、打补丁）。
                                    chains[a.name] = {"kind": "chain", "sym": a.name, "dst": dst,
                                                      "line": node.lineno, "orig": a.name,
                                                      "why": why or "sideeffect"}

            # 第二遍：本地名字的实际使用点。`_payload.graph_payload(...)` → 用了 graph_payload；
            # `Orchestrator(...)` → 用了 Orchestrator。这才回答得了「具体用了对方哪些函数」。
            if bound or chains:
                used: set[str] = set()
                for node in ast.walk(tree):
                    if chains and isinstance(node, ast.Attribute):
                        # 还原 a.b.c.X 这条链，前缀命中某个 import a.b.c 就算用了 X
                        parts, cur = [], node
                        while isinstance(cur, ast.Attribute):
                            parts.append(cur.attr)
                            cur = cur.value
                        if isinstance(cur, ast.Name):
                            parts.append(cur.id)
                            parts.reverse()
                            for cut in range(len(parts) - 1, 0, -1):
                                mod = ".".join(parts[:cut])
                                c = chains.get(mod)
                                if c:
                                    used.add(mod)
                                    _use(edge_uses, pkg, c["dst"], f"{mod}:{parts[cut]}",
                                         str(rel), node.lineno)
                                    break
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        b = bound.get(node.value.id)
                        if b and b["kind"] == "mod":
                            used.add(node.value.id)
                            _use(edge_uses, pkg, b["dst"], f"{b['sym']}:{node.attr}",
                                 str(rel), node.lineno)
                    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        b = bound.get(node.id)
                        if b:
                            used.add(node.id)
                            if b["kind"] == "name":
                                _use(edge_uses, pkg, b["dst"], b["sym"], str(rel), node.lineno)
                # 导入了但本文件从没引用过
                for local, b in list(bound.items()) + list(chains.items()):
                    if local in used:
                        continue
                    why = b["why"]
                    if not why:
                        ln = src_lines[b["line"] - 1] if 0 < b["line"] <= len(src_lines) else ""
                        # 作者用 noqa: F401 明确说了「这个没用的 import 是故意的」
                        why = "intentional" if ("noqa" in ln and "F401" in ln) else "unused"
                    edge_dead.setdefault((pkg, b["dst"]), []).append({
                        "f": str(rel), "l": b["line"], "n": b["orig"],
                        "sym": b["sym"], "why": why})

    # 架构高度
    out: dict[str, int] = {}
    inn: dict[str, int] = {}
    for (a, b), w in edges.items():
        out[a] = out.get(a, 0) + w
        inn[b] = inn.get(b, 0) + w
    packages = {}
    for p in sorted(pkg_files):
        o, i = out.get(p, 0), inn.get(p, 0)
        packages[p] = {
            "files": pkg_files[p], "loc": pkg_loc.get(p, 0),
            "classes": pkg_cls.get(p, 0), "funcs": pkg_fn.get(p, 0),
            "out": o, "in": i,
            "alt": round((o - i) / (o + i), 4) if (o + i) else 0.0,
        }

    # 包目录里的 C++ / CUDA 源文件：挂到所在的包下，供浏览和高亮。
    # 它们不进 import 图——C++ 与 Python 之间的绑定边（pybind、torch.ops）
    # 需要真正的 C++ 解析（tree-sitter），是另一件事。
    aux: dict[str, str] = {}
    for r in roots:
        base = root / r
        if not base.exists():
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
            for f in fn:
                if os.path.splitext(f)[1].lower() in AUX_EXTS:
                    p = Path(dp, f)
                    mod = ".".join(p.relative_to(base.parent).parent.parts)
                    aux[str(p.relative_to(root))] = pkg_of(mod) if mod else ""

    docs = collect_docs(root, files)
    return {
        "docs": docs,
        "repo": {"root": str(root), "name": root.name, "roots": roots,
                 "depth": depth, "expand": expand, "n_files": n_files, "n_parse_errors": n_err,
                 "n_aux": len(aux)},
        "aux": aux,
        "edge_sites": {f"{a}|{b}": v for (a, b), v in edge_sites.items()},
        # 用到的对方符号：{"a|b": {"模块:名字": [[文件, 行], ...]}}
        "edge_uses": {f"{a}|{b}": v for (a, b), v in edge_uses.items()},
        # 导入了但没引用。why：unused 真的没用 / type 只在 TYPE_CHECKING 里 /
        # reexport __init__ 里的再导出 / sideeffect import a.b.c 为了注册或打补丁 /
        # intentional 行上带 noqa: F401，作者说了是故意的
        "edge_dead": {f"{a}|{b}": v for (a, b), v in edge_dead.items()},
        "packages": packages,
        "edges": [[a, b, w] for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1])],
        "symbols": {k: s.as_json() for k, s in symbols.items()},
        "files": files,
    }


def write_index(root: Path, index: dict, outdir: Path | None = None) -> Path:
    """写盘。符号表单独存 symbols.json——它比图数据大一两个数量级，
    渲染总图时不需要全量加载。"""
    outdir = outdir or (root / ".codestrata")
    outdir.mkdir(parents=True, exist_ok=True)
    symbols = index.pop("symbols", {})
    files = index.pop("files", {})
    aux = index.pop("aux", {})
    sites = index.pop("edge_sites", {})
    uses = index.pop("edge_uses", {})
    dead = index.pop("edge_dead", {})
    docs = index.pop("docs", {})
    (outdir / "symbols.json").write_text(
        json.dumps({"symbols": symbols, "files": files, "aux": aux, "docs": docs,
                    "edge_sites": sites, "edge_uses": uses, "edge_dead": dead},
                   ensure_ascii=False),
        encoding="utf-8")
    index["n_symbols"] = len(symbols)
    p = outdir / "index.json"
    p.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    index["symbols"], index["files"], index["aux"] = symbols, files, aux   # 调用方还要用
    index["edge_sites"], index["edge_uses"], index["edge_dead"] = sites, uses, dead
    index["docs"] = docs
    return p
