"""组装前端要的数据。serve（live）和 export（单文件）共用这一份，免得两边漂移。"""
from __future__ import annotations

import ast
import json
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path

from . import cut as _cut
from . import highlight as _hl
from . import layout as _layout
from . import notes as _notes
from . import runs as _runs
from . import xref as _xref


def index_summary(repo: Path) -> dict | None:
    """只读 index.json（不读大得多的 symbols.json）：没 scan 过是 None。
    {scanned_at, n_files, n_symbols, n_parse_errors, roots}——主菜单的项目卡片、trace 的默认 roots 用"""
    p = repo / ".codestrata" / "index.json"
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
        at = p.stat().st_mtime
    except (OSError, ValueError):
        return None
    r = idx.get("repo") or {}
    return {"scanned_at": at, "n_files": r.get("n_files"), "n_symbols": idx.get("n_symbols"),
            "n_parse_errors": r.get("n_parse_errors"), "roots": r.get("roots") or []}


def load_index(repo: Path) -> dict:
    d = repo / ".codestrata"
    p = d / "index.json"
    if not p.exists():
        raise SystemExit(f"没有 {p}；先跑 codestrata scan {repo}")
    idx = json.loads(p.read_text(encoding="utf-8"))
    sp = d / "symbols.json"
    if sp.exists():
        extra = json.loads(sp.read_text(encoding="utf-8"))
        idx["symbols"] = extra.get("symbols", {})
        idx["files"] = extra.get("files", {})
        idx["aux"] = extra.get("aux", {})
        idx["edge_sites"] = extra.get("edge_sites", {})
        idx["edge_uses"] = extra.get("edge_uses", {})
        idx["edge_dead"] = extra.get("edge_dead", {})
        idx["name_refs"] = extra.get("name_refs")    # 老的 symbols.json 没有：None（不显示接线点）
        idx["docs"] = extra.get("docs", {})
        idx["file_loc"] = extra.get("file_loc", {})
        idx["file_sha"] = extra.get("file_sha")      # 老的 symbols.json 没有：None
    return idx


def load_hot(repo: Path, idx: dict, ref: str | None) -> tuple[dict | None, dict | None]:
    """ref 是一个 run：完整的 run id，或 case 名（取它最新一次录完的），后面可以加 @阶段，
    只叠加那个阶段的调用（见 trace 的 PHASE 约定）。run 的存储和解析见 runs.py。"""
    if not ref:
        return None, None
    hot, meta = _runs.load(repo, idx, ref)
    print(f"[codestrata] hot 图用的 run：{meta['run_id']}" + (f" @{meta['phase']}" if meta["phase"] else ""),
          file=sys.stderr)
    return hot, meta


def _unit_syms(idx: dict) -> dict:
    """顶层类 / 函数按单元分组（方法太多，只在文件树展开时按需取）。"""
    if "_unit_syms" not in idx:
        out: dict[str, list] = {}
        for key, s in (idx.get("symbols") or {}).items():
            if "." in s["n"]:
                continue
            out.setdefault(s["p"], []).append(
                {"key": key, "n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"], "b": s.get("b", [])})
        idx["_unit_syms"] = out
    return idx["_unit_syms"]


def _norm_open(idx: dict, open_) -> set:
    return set(idx.get("default_open") or []) if open_ is None else {o for o in open_ if _cut.is_node(idx, o)}


def _hot_on_cut(hot: dict, node_of: dict, used: dict | None = None) -> tuple[dict, dict, dict]:
    """一个 run 的 hot（单元粒度）按切面汇总：(节点 → 次数, "a|b" 节点间的边 → 次数,
    "a|b" → 其中动态分派的次数)。

    动态分派和边详情（edge_detail）同一个口径：被调的符号（方法归到类）不在这条切面边的静态引用
    （used，边 → 引用到的符号）里。这个数要按切面算、不能按单元对算完再加：同一个符号可能一对单元里
    静态引用、另一对里 runtime 调到，合成一条边之后算「确认」。"""
    hp: dict[str, int] = {}
    for u, n in hot["packages"].items():
        if u in node_of:
            hp[node_of[u]] = hp.get(node_of[u], 0) + n
    he: dict[str, int] = {}
    for k, n in hot["edges"].items():
        a, _, b = k.partition("|")
        if a in node_of and b in node_of and node_of[a] != node_of[b]:
            kk = f"{node_of[a]}|{node_of[b]}"
            he[kk] = he.get(kk, 0) + n
    hd: dict[str, int] = {}
    for k, calls in (hot.get("edge_calls") or {}).items():
        a, _, b = k.partition("|")
        if a in node_of and b in node_of and node_of[a] != node_of[b]:
            kk = f"{node_of[a]}|{node_of[b]}"
            refs = (used or {}).get(kk, ())
            n = sum(x["n"] for c, x in calls.items() if _top(c) not in refs)
            if n:
                hd[kk] = hd.get(kk, 0) + n
    return hp, he, hd


def _edge_uses_on_cut(idx: dict, node_of: dict) -> dict[str, set]:
    """切面边 "a|b" → 两端底下各对单元之间静态引用到的符号（合起来）"""
    uses = idx.get("edge_uses") or {}
    out: dict[str, set] = {}
    for a, b, _ in idx.get("edges") or []:
        na, nb = node_of[a], node_of[b]
        if na != nb:
            out.setdefault(f"{na}|{nb}", set()).update(uses.get(f"{a}|{b}", {}))
    return out


def _dyn_only(kinds: dict, runs: list[tuple[dict, dict]]) -> list[str]:
    """有静态边、但这次跑到的调用全是动态分派的切面边（对比时两个 run 都是这样）。
    这种边不能画成「引用 + runtime」的实线：import 的是一回事（比如一个常量），跑到的是另一回事
    （经由 self.model、注册表调到的类），展开之后实线就变成了没跑到的灰边加一条动态分派的虚线"""
    out = []
    for k in kinds:
        if any(he.get(k) for he, _ in runs) and all(hd.get(k, 0) >= he.get(k, 0) for he, hd in runs):
            out.append(k)
    return sorted(out)


def _meta_brief(m: dict | None) -> dict | None:
    """对比 / 导出里别的 run 只带这些：够横幅和下拉用"""
    if not m:
        return None
    # 横幅和帮助里要读的都带上（都不大）：换到导出里别的 run 时，安装包映射、命令、进程这些说明不能没了
    return {k: m.get(k) for k in ("run_id", "case", "phase", "phases", "status", "problems", "created",
                                    "tags", "note", "git", "n_procs", "stale_files", "unmatched", "events",
                                    "mapped_from", "n_mapped", "mapped_mismatch", "unmapped", "defs", "cmd", "procs",
                                    "script", "file_state", "rerun", "rerun_exact", "rerun_redacted", "rerun_env", "env_inherited",
                                    "phase_at", "phase_log")}


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, open_=None, min_files: int = 1,
                  width: float = 1180.0, hot_b: dict | None = None, hot_meta_b: dict | None = None) -> dict:
    """一个切面上的全部前端数据。open_ 是展开着的目录（不给就用 scan 算出的默认切面）；
    图、边的种类、hot 叠加、每个节点的文件 / 符号 / 文档，都按这个切面汇总。
    width：页面上图框有多宽——按它排版，宽屏上图铺满、少折行，而不是把 1180 宽的图放大"""
    open_ = _norm_open(idx, open_)
    v = _cut.view(idx, open_)
    # 框：每个节点被哪个展开着的目录（或展开着的本层文件）直接套着，一路往上。
    # 只有一个根时不画根的框——它就是整张图
    roots = _cut.roots_of(idx)
    top = roots[0] if len(roots) == 1 else None
    frames: dict[str, dict] = {}
    for n, x in v["nodes"].items():
        f = x["parent"] if x["parent"] != top else None
        x["frame"] = f
        x["collapsible"] = f is not None
        while f and f not in frames:
            p = _cut.parent_of(idx, f)
            frames[f] = {"parent": p if p != top else None, "kind": _cut.kind(idx, f), "n": 0}
            f = frames[f]["parent"]
    for n in _cut.visible(v):              # 每个框里一共有几个画得出来的节点（hot 视图只画一部分）
        f = v["nodes"][n]["frame"]
        while f:
            frames[f]["n"] += 1
            f = frames[f]["parent"]
    # 同一个切面上短名撞了的（flask.app 和 flask.sansio.app 都叫 app）：补上父目录段，图上和面板里一样
    alias = _cut.disambiguate(idx, set(_cut.visible(v)) | set(frames))
    syn = {"repo": idx["repo"], "packages": v["nodes"], "edges": v["edges"], "frames": frames, "alias": alias}
    # 分层（纵轴）：叠了 run 就按这次实际发生的调用排（对比时两个 run 合起来），调用方在上；
    # 静态 import 只作次要依据——基类回调子类、注册表、回调这些调用和 import 的方向是反的
    rt_calls: dict[str, int] = {}
    for h in (hot, hot_b):
        for k, n in (_hot_on_cut(h, v["node_of"])[1] if h else {}).items():
            rt_calls[k] = rt_calls.get(k, 0) + n
    g = _layout.build(syn, min_files=min_files, width=width,
                      runtime_edges=[(*k.split("|"), n) for k, n in sorted(rt_calls.items())])
    mem, node_of = v["members"], v["node_of"]
    repo_info = dict(idx["repo"])
    repo_info["n_symbols"] = len(idx.get("symbols") or {})
    repo_info["n_units"] = len(idx["packages"])
    usyms = _unit_syms(idx)
    pkg_files: dict[str, list] = {}
    pkg_syms: dict[str, list] = {}
    for rel, u in (idx.get("files") or {}).items():
        pkg_files.setdefault(node_of[u], []).append(rel)
    for rel, d in (idx.get("aux") or {}).items():
        n = _cut.dir_node(idx, open_, d)
        if n:
            pkg_files.setdefault(n, []).append(rel)
    for n, us in mem.items():
        syms = [x for u in us for x in usyms.get(u, [])]
        syms.sort(key=lambda d: (d["k"] != "class", d["f"], d["l"]))
        pkg_syms[n] = syms
    for fs in pkg_files.values():
        fs.sort()
    pkg_docs: dict[str, list] = {}
    for key, ds in (idx.get("docs") or {}).items():
        n = node_of.get(key) or _cut.dir_node(idx, open_, key)
        if n:
            have = {d["f"] for d in pkg_docs.get(n, [])}
            pkg_docs.setdefault(n, []).extend(d for d in ds if d["f"] not in have)
    # 每条边的「实质」：用到了对方几个符号、有几个只 import 没用的绑定。
    # 一个符号都没用到的边（纯 import）在图上画成虚线——它不承载任何调用。
    dead = idx.get("edge_dead") or {}
    kinds: dict[str, dict] = {}
    syms_used = _edge_uses_on_cut(idx, node_of)
    for a, b, w in idx.get("edges") or []:
        na, nb = node_of[a], node_of[b]
        if na == nb:
            continue
        k = f"{na}|{nb}"
        d = kinds.setdefault(k, {"uses": 0, "dead": 0, "sites": 0})
        d["dead"] += len(dead.get(f"{a}|{b}", []))
        d["sites"] += w
    for k, ss in syms_used.items():
        kinds[k]["uses"] = len(ss)
    # 只在 TYPE_CHECKING 里 import 的（运行时不存在）：不是依赖，不进排版和高度。切面上两端之间
    # 没有运行时 import 的才单独给出来，前端画成「仅类型」（默认不显示）；有的，它的 import 在那条边的详情里
    type_w: dict[str, int] = {}
    for a, b, w in idx.get("type_edges") or []:
        na, nb = node_of[a], node_of[b]
        if na != nb and f"{na}|{nb}" not in kinds:
            type_w[f"{na}|{nb}"] = type_w.get(f"{na}|{nb}", 0) + w
    # hot 叠加也按切面汇总；只在 runtime 出现、静态 import 图里根本没有的节点间调用——插件、
    # importlib、注册表——是静态分析的盲区，必须单独画出来，否则图会说谎。
    # 对比（hot_b，另一个 run）：两边各自按切面汇总，节点和边上都带 [A, B] 两个次数；
    # 只在 runtime 出现的边、「只看跑到的」都取两边的并集
    hot_view, rt_only, cmp, dyn_only = None, [], None, []
    shown = {n["id"] for n in g["nodes"]}
    type_only = [[*k.split("|"), w] for k, w in sorted(type_w.items()) if set(k.split("|")) <= shown]
    if hot:
        hp, he, hd = _hot_on_cut(hot, node_of, syms_used)
        hot_view = {**hot, "packages": hp, "edges": he, "dyn": hd}
        hpb, heb, hdb = _hot_on_cut(hot_b, node_of, syms_used) if hot_b else ({}, {}, {})
        if hot_b:
            ref_b = (hot_meta_b or {}).get("run_id", "?") + (f"@{hot_meta_b['phase']}" if (hot_meta_b or {}).get("phase") else "")
            cmp = {"ref_b": ref_b, "meta_b": _meta_brief(hot_meta_b),
                   "nodes": {n: [hp.get(n, 0), hpb.get(n, 0)] for n in set(hp) | set(hpb) if hp.get(n) or hpb.get(n)},
                   "edges": {k: [he.get(k, 0), heb.get(k, 0)] for k in set(he) | set(heb) if he.get(k) or heb.get(k)},
                   "dyn": {k: [hd.get(k, 0), hdb.get(k, 0)] for k in set(hd) | set(hdb)}}
        dyn_only = _dyn_only(kinds, [(he, hd)] + ([(heb, hdb)] if hot_b else []))
        for k in sorted(set(he) | set(heb)):
            a, _, b = k.partition("|")
            if k not in kinds and a in shown and b in shown:
                rt_only.append([a, b, max(he.get(k, 0), heb.get(k, 0))])
    # hot 视图单独排版：只放跑到的节点（对比时两边任一跑到的），每个节点的层沿用总图，纵坐标含义不变、横向更紧凑
    g_hot = (_layout.build(syn, lane_of={n["id"]: n["lane"] for n in g["nodes"]}, min_files=min_files, width=width,
                           only={p for p, n in hot_view["packages"].items() if n} | set((cmp or {}).get("nodes") or {}))
             if hot_view else None)
    for nd in (g["nodes"] + (g_hot["nodes"] if g_hot else [])):   # 前端要知道哪些节点能展开、收起到哪里
        x = v["nodes"][nd["id"]]
        nd.update(kind=x["kind"], expandable=x["expandable"], parent=x["parent"],
                  collapsible=x["collapsible"], fanout=x["fanout"], units=x["units"])
    # 阶段从哪个函数开始（trace --phase）：落在这个切面的哪个节点上，前端据此标出阶段的起点 / 终点
    files = idx.get("files") or {}
    phase_marks = [{**{k: t.get(k) for k in ("name", "func", "qualname", "file", "line")},
                    "node": v["node_of"].get(files.get(t.get("file")))}
                   for t in (hot_meta or {}).get("phase_at") or []]
    return {"repo": repo_info, "graph": g, "graphHot": g_hot, "pkgs": v["nodes"],
            "pkgSyms": pkg_syms, "pkgFiles": pkg_files, "pkgDocs": pkg_docs,
            "fileLoc": idx.get("file_loc") or {},
            "alias": alias, "edgeKinds": kinds, "runtimeOnlyEdges": rt_only, "dynOnlyEdges": dyn_only, "typeOnlyEdges": type_only,
            "hot": hot_view, "hotMeta": hot_meta, "cmp": cmp, "phaseMarks": phase_marks,
            "open": sorted(open_), "defaultOpen": idx.get("default_open") or [],
            "autoSplit": idx["repo"].get("auto_split") or []}


def _top(symkey: str) -> str:
    """模块:Cls.method → 模块:Cls。runtime 调到的是方法，静态引用的往往是类。"""
    m, _, q = symkey.partition(":")
    return f"{m}:{q.split('.')[0]}" if q else symkey


def _module_files(idx: dict) -> dict:
    """点分模块名 → 文件。src-layout 的 src/ 前缀不属于模块名，要去掉（同 scan）。"""
    prefixes = [r.rsplit("/", 1)[0] + "/" for r in idx["repo"].get("roots") or [] if "/" in r]
    out = {}
    for orig in idx.get("files") or {}:
        rel = orig
        for pre in prefixes:
            if rel.startswith(pre):
                rel = rel[len(pre):]
                break
        parts = rel[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[".".join(parts)] = orig
    return out


@lru_cache(maxsize=256)
def _file_lines(path: str, mtime_ns: int) -> tuple[str, ...]:
    return tuple(Path(path).read_text(encoding="utf-8", errors="replace").splitlines())


_TRUTH = ("__bool__", "__len__")
_BIN = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.MatMult: "matmul", ast.Div: "truediv",
        ast.FloorDiv: "floordiv", ast.Mod: "mod", ast.Pow: "pow", ast.LShift: "lshift", ast.RShift: "rshift",
        ast.BitAnd: "and", ast.BitOr: "or", ast.BitXor: "xor"}
_CMP = {ast.Eq: ("__eq__",), ast.NotEq: ("__ne__", "__eq__"), ast.Lt: ("__lt__", "__gt__"),
        ast.LtE: ("__le__", "__ge__"), ast.Gt: ("__gt__", "__lt__"), ast.GtE: ("__ge__", "__le__"),
        ast.In: ("__contains__", "__iter__", "__eq__", "__hash__"),
        ast.NotIn: ("__contains__", "__iter__", "__eq__", "__hash__")}
_UNARY = {ast.USub: ("__neg__",), ast.UAdd: ("__pos__",), ast.Invert: ("__invert__",)}
_ITERATES = ("__iter__", "__next__")
# 内置函数调的特殊方法：len(x) 调 x.__len__
_BUILTIN = {"len": ("__len__",), "iter": _ITERATES, "next": ("__next__",), "str": ("__str__",), "print": ("__str__",),
            "repr": ("__repr__",), "hash": ("__hash__",), "bool": _TRUTH, "abs": ("__abs__",),
            "format": ("__format__",), "reversed": ("__reversed__", "__len__", "__getitem__"),
            "int": ("__int__", "__index__"), "float": ("__float__",), "round": ("__round__",),
            **{k: _ITERATES for k in ("list", "tuple", "set", "frozenset", "dict", "sorted", "sum", "min", "max",
                                      "any", "all", "enumerate", "zip", "map", "filter")}}
_NOT_CODE = ("annotation", "returns", "type_comment", "type_params")   # 标注里的 list[int]、a | b 不是运算


def _code_nodes(node: ast.AST):
    """ast.walk，但不进类型标注（参数、返回值、AnnAssign 的标注）：那里的 [] 和 | 不会在运行时触发特殊方法"""
    todo = [node]
    while todo:
        n = todo.pop()
        yield n
        for field, v in ast.iter_fields(n):
            if field in _NOT_CODE:
                continue
            if isinstance(v, ast.AST):
                todo.append(v)
            elif isinstance(v, list):
                todo.extend(x for x in v if isinstance(x, ast.AST))


def _end(n: ast.AST) -> int:
    return getattr(n, "end_lineno", None) or n.lineno


@lru_cache(maxsize=64)
def _code_facts(path: str, mtime_ns: int) -> tuple[frozenset, frozenset, dict]:
    """一个文件的三样事实（按语法树，不按文本），找调用处用：
      - docstring 占的行：文档里写的「for all … in」「a + b」不是代码
      - 函数 / 类签名占的行（def 行到函数体第一句之前，多行签名的续行）：参数默认值、标注不是调用处
      - {行号: 这一行上由语法触发的特殊方法}：下标、运算符、比较和 in、with、for 和推导式、await、
        f-string、真值判断（if / while / and / or / not）、字典和集合的键、解包赋值、len() 这类内置函数。
        类型标注里的不算（_code_nodes）
    解析不了的文件三样都是空的。行号从 1 起"""
    try:
        tree = ast.parse(Path(path).read_bytes())
    except (SyntaxError, ValueError, OSError):
        return frozenset(), frozenset(), {}
    prose, sig, syn = set(), set(), {}

    def mark(line: int, names) -> None:
        syn.setdefault(line, set()).update(names)

    def truth(e: ast.AST) -> None:
        """e 被当真假用（if e、while e、e and …、not e）：调的是 e 的 __bool__ / __len__——除非 e 本身是比较、
        and / or、常量（那判断的是它们算出来的 bool，不是某个对象）。not x 看的是 x"""
        if type(e) is ast.UnaryOp and type(e.op) is ast.Not:
            truth(e.operand)
        elif type(e) not in (ast.Compare, ast.BoolOp, ast.Constant):
            mark(e.lineno, _TRUTH)

    for n in _code_nodes(tree):
        t = type(n)
        if t is ast.Expr and type(n.value) is ast.Constant and type(n.value.value) is str:
            prose.update(range(n.lineno, _end(n) + 1))
        elif t in (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef) and n.body:
            first = n.body[0]                    # 函数体第一句；被装饰的定义从第一个装饰器算起
            sig.update(range(n.lineno, min([first.lineno] + [x.lineno for x in getattr(first, "decorator_list", ())])))
        elif t is ast.Subscript:
            mark(_end(n.value), {ast.Load: ("__getitem__", "__class_getitem__"), ast.Store: ("__setitem__",),
                                 ast.Del: ("__delitem__",)}[type(n.ctx)])
        elif t is ast.BinOp and type(n.op) in _BIN:
            op = _BIN[type(n.op)]
            mark(_end(n.left), (f"__{op}__", f"__r{op}__"))
        elif t is ast.AugAssign and type(n.op) in _BIN:
            op = _BIN[type(n.op)]
            mark(n.lineno, (f"__i{op}__", f"__{op}__", f"__r{op}__"))
        elif t is ast.UnaryOp and type(n.op) in _UNARY:
            mark(n.lineno, _UNARY[type(n.op)])
        elif t is ast.UnaryOp and type(n.op) is ast.Not:
            truth(n.operand)
        elif t is ast.Compare:
            for o in n.ops:
                names = _CMP.get(type(o), ())
                # x in 容器：容器的 __contains__（没有就 __iter__），字典 / 集合还要 x 的 __hash__、__eq__——
                # x 是常量（3 in b）时那是 int 的，不会是仓库里的方法
                if type(o) in (ast.In, ast.NotIn) and type(n.left) is ast.Constant:
                    names = ("__contains__", "__iter__")
                mark(_end(n.left), names)
        elif t in (ast.With, ast.AsyncWith):
            names = ("__enter__", "__exit__") if t is ast.With else ("__aenter__", "__aexit__")
            for item in n.items:
                mark(item.context_expr.lineno, names)
        elif t in (ast.For, ast.AsyncFor):
            mark(n.iter.lineno, _ITERATES if t is ast.For else ("__aiter__", "__anext__"))
        elif t is ast.comprehension:
            mark(n.iter.lineno, ("__aiter__", "__anext__") if n.is_async else _ITERATES)
            for c in n.ifs:
                truth(c)
        elif t is ast.Await:
            mark(n.lineno, ("__await__",))
        elif t is ast.YieldFrom:
            mark(n.lineno, ("__iter__",))
        elif t is ast.FormattedValue:
            mark(n.value.lineno, ("__repr__",) if n.conversion in (114, 97) else ("__format__", "__str__"))
        elif t in (ast.If, ast.While, ast.IfExp, ast.Assert):
            truth(n.test)
        elif t is ast.BoolOp:
            for v in n.values:
                truth(v)
        elif t in (ast.Dict, ast.Set):
            for k in (n.keys if t is ast.Dict else n.elts):
                if k is not None:
                    mark(k.lineno, ("__hash__", "__eq__"))
        elif t is ast.Assign and any(type(x) in (ast.Tuple, ast.List, ast.Starred) for x in n.targets):
            mark(n.value.lineno, _ITERATES)
        elif t is ast.Call and type(n.func) is ast.Name and n.func.id in _BUILTIN:
            mark(n.lineno, _BUILTIN[n.func.id])
    return frozenset(prose), frozenset(sig), {k: frozenset(v) for k, v in syn.items()}


_DEF_LINE = re.compile(r"\s*(?:async\s+)?(?:def|class)\s")

# 被调的是特殊方法时，调用方那一行上多半不写它的名字，写的是触发它的语法：页面上怎么说这种写法。
# 按语法找（_code_facts）的：下面这些；写法里没有能认的记号的（对象(…) 调 __call__、取个不存在的
# 属性调 __getattr__）在 _IMPLICIT 里，只找显式写了名字的。没列的特殊方法照普通方法按名字找
_ARITH = {"add": "+", "sub": "-", "mul": "*", "matmul": "@", "truediv": "/", "floordiv": "//", "mod": "%",
          "pow": "**", "lshift": "<<", "rshift": ">>", "and": "&", "or": "|", "xor": "^"}
_BY_SYNTAX: dict[str, str] = {
    **{f"__{p}{op}__": f"… {s}{'=' if p == 'i' else ''} …" for op, s in _ARITH.items() for p in ("", "r", "i")},
    "__eq__": "… == …", "__ne__": "… != …", "__le__": "… <= …", "__ge__": "… >= …", "__lt__": "… < …",
    "__gt__": "… > …", "__enter__": "with …", "__exit__": "with …", "__aenter__": "async with …",
    "__aexit__": "async with …", "__iter__": "for … in …", "__next__": "for … in …", "__aiter__": "async for …",
    "__anext__": "async for …", "__await__": "await …", "__getitem__": "…[…]", "__class_getitem__": "…[…]",
    "__setitem__": "…[…] = …", "__delitem__": "del …[…]", "__contains__": "… in …", "__len__": "len(…) / if 对象",
    "__bool__": "if 对象", "__hash__": "hash(…) / 字典的键", "__str__": "str(…)", "__repr__": "repr(…)",
    "__format__": "f\"{…}\"", "__neg__": "-…", "__pos__": "+…", "__invert__": "~…", "__abs__": "abs(…)",
    "__reversed__": "reversed(…)", "__int__": "int(…)", "__index__": "int(…)", "__float__": "float(…)",
    "__round__": "round(…)",
}
_IMPLICIT = {"__call__": "对象(…)", "__getattr__": "对象.属性（它没有这个属性时）", "__getattribute__": "对象.属性",
             "__setattr__": "对象.属性 = …", "__delattr__": "del 对象.属性", "__get__": "对象.属性（描述符）",
             "__set__": "对象.属性 = …（描述符）", "__delete__": "del 对象.属性（描述符）"}
_ACCESSORS = ("setter", "getter", "deleter")


def _call_form(q: str, d: dict | None):
    """被调函数（限定名 q，符号表条目 d）在调用方那一行上长什么样：(按名字找的 re, 按语法找的特殊方法名或 None,
    {callee, how, form})。how 是怎么找的——call：按名字（`名字(`、getattr 的 `'名字'`、装饰器 `@名字`）；
    attr：property（scan 记下的装饰器），取属性就是调用（`.名字`）；syntax：由语法触发的特殊方法（with、for、[]、
    运算符……，按 _code_facts）；implicit：写法里认不出的特殊方法（对象(…) 调 __call__），只找显式写了名字的。
    form 是页面上说的写法。闭包、模块顶层没有名字可找：None"""
    parts = q.split(".")
    name = parts[-1]
    if not name or name.startswith("<"):
        return None
    # 构造：调用方写的是 类名(…)（__post_init__ 由 dataclass 生成的 __init__ 调，那个 __init__ 不在仓库里）
    names = [parts[-2], name] if name in ("__init__", "__new__", "__post_init__") and len(parts) > 1 else [name]
    alt = "|".join(map(re.escape, names))
    quoted = rf"['\"](?:{alt})['\"]"
    info = {"callee": names[0], "how": "call", "form": f"{names[0]}(…)"}
    if any(x.endswith("property") or x in _ACCESSORS for x in (d or {}).get("d") or ()):
        return re.compile(rf"\.(?:{alt})\b|{quoted}"), None, {**info, "how": "attr", "form": f".{name}"}
    by_name = re.compile(rf"(?<![\w])(?:{alt})\s*\(|{quoted}|^\s*@(?:[\w.]*\.)?(?:{alt})\b")
    if name in _BY_SYNTAX:
        return by_name, name, {**info, "how": "syntax", "form": _BY_SYNTAX[name]}
    if name in _IMPLICIT:
        return by_name, None, {**info, "how": "implicit", "form": _IMPLICIT[name]}
    return by_name, None, info


def _add_call_sites(repo: Path, idx: dict, items: list) -> None:
    """点开一条边时要给看的代码：每个调到的函数 from（调用方里调它的那一行）和 to（它自己的签名）。

    - caller["sites"]：在调用方的函数体里找调用那一行，最多 3 处。按被调函数的写法找（_call_form）：
      普通函数按名字（`名字(`、`'名字'`、`@名字`），property 按 `.名字`，特殊方法按触发它的语法（with、
      for、[]、运算符）；caller["how"]、caller["form"] 记着是怎么找的、页面上怎么说那种写法。
      找过但没找到是 []——中间隔了 __call__、回调或仓库外的代码，这时 caller["sig"] 是调用方自己的签名，
      页面上拿它当 from。动态分派多半就写在这一行上：self.model.compute_logits(…)。
    - runtime 条目的 r["sig"]：被调函数的签名（def 那一行到冒号为止，最多 6 行）
    - 没跑到的静态引用：item["sig"] 是被引用符号的签名，item["use_s"] 是第一处引用那一行
    只在仓库里扫描过的文件里找；只看写法，不做类型推断。"""
    syms, files = idx.get("symbols") or {}, idx.get("files") or {}

    def body(sym: str) -> list[int]:
        """调用方函数体的行下标（从 def 行起：它自己的装饰器是外层执行的）；同名的另几个 def
        （property 的 setter）也算"""
        while sym not in syms and ".<L" in sym:          # 闭包：用包住它的那个函数的范围
            sym = sym.rsplit(".<L", 1)[0]
        d = syms.get(sym)
        if not d or not d.get("e"):
            return []
        return sorted({i for a, e in [(d["l"], d["e"])] + [(x[0], x[2]) for x in d.get("a") or ()]
                       for i in range(a - 1, e)})

    def cached(f: str, reader):
        """扫描过的文件 f 经 reader（按 mtime 缓存的 _file_lines / _code_facts）读出来的东西；不是扫描过的、
        读不了的是 None"""
        if f not in files:
            return None
        try:
            st = (repo / f).stat()
            return reader(str(repo / f), st.st_mtime_ns)
        except OSError:
            return None

    def lines(f: str):
        return cached(f, _file_lines)

    def sites(c: dict, pat, dunder: str | None) -> list | None:
        """调用方 c 的函数体里调被调函数的那几行（最多 3 处）：按名字 pat 找到的，或者（特殊方法）这一行上的语法
        会触发 dunder（_code_facts）。跳过签名、docstring、注释"""
        f = (c.get("def") or {}).get("f")
        rows, ls = body(c["sym"]), lines(f) if f else None
        if not rows or ls is None:
            return None
        prose, sig, syn = cached(f, _code_facts) or (frozenset(), frozenset(), {})

        def hit(i: int) -> bool:
            if i + 1 in prose or i + 1 in sig or _DEF_LINE.match(ls[i]) or ls[i].lstrip().startswith("#"):
                return False
            return bool(pat.search(ls[i])) or (dunder is not None and dunder in syn.get(i + 1, ()))
        return [{"f": f, "l": i + 1, "s": ls[i].strip()[:200]} for i in rows if i < len(ls) and hit(i)][:3]

    def sig(d: dict | None) -> list[str] | None:
        ls = lines(d["f"]) if d else None
        if not ls or not 0 < d["l"] <= len(ls):
            return None
        if d.get("k") == "var":                          # 模块级变量：赋值那一行
            return [ls[d["l"] - 1].strip()[:200]]
        out = []
        for t in ls[d["l"] - 1:d["l"] + 5]:
            out.append(t.rstrip())
            if t.split("#", 1)[0].rstrip().endswith(":"):
                break
        if len(out) == 1:
            return [out[0].strip()[:200]]
        # 多行签名压成一行（面板窄）：def forward(self, input_ids: …, positions: …) -> …:
        one = re.sub(r"\(\s+", "(", re.sub(r",?\s*\)", ")", " ".join(t.strip() for t in out)))
        closed = out[-1].split("#", 1)[0].rstrip().endswith(":")
        return [one[:200] + ("" if closed else " …")]

    for it in items:
        if not it["runtime"]:
            if it.get("def"):
                it["sig"] = sig(it["def"])
            if it.get("uses"):
                ls = lines(it["uses"][0]["f"])
                l = it["uses"][0]["l"]
                it["use_s"] = ls[l - 1].strip()[:200] if ls and 0 < l <= len(ls) else None
            continue
        for r in it["runtime"]:
            r["sig"] = sig(r.get("def"))
            form = _call_form(r["sym"].partition(":")[2], syms.get(r["sym"]))
            if not form:
                continue                                 # 闭包、模块顶层：没有名字可找
            pat, dunder, info = form
            for c in r["callers"]:
                found = sites(c, pat, dunder)
                if found is None:
                    continue
                c["sites"] = found
                c.update(info)
                if not c["sites"]:
                    c["sig"] = sig(c["def"])


def _add_wiring(repo: Path, idx: dict, items: list) -> None:
    """动态分派调到的类：仓库里哪些字符串按名字提到了它（scan 的 name_refs）——注册表
    {"Arch": ("pkg", "mod", "Cls")}、getattr(mod, "Cls")、插件表里的 "pkg.mod.Cls"。调用方和它之间
    没有 import，接线多半就在这几行。记在 item["wiring"] = {refs: [{f, l, s, exact}], n, same_name}：
    带模块的类路径只认模块对得上的（exact）；只有类名的，同一个文件里挨着的几行（注册表的键和元组里的
    类名）只留第一行，same_name > 1 时仓库里有同名类、这些字符串不一定指它。老的 index 没有 name_refs：不加。"""
    refs_by = idx.get("name_refs")
    if refs_by is None:
        return
    syms = idx.get("symbols") or {}
    n_same: dict[str, int] = {}
    for it in items:
        d = it.get("def")
        if it["status"] != "dynamic" or not d or d.get("k") != "class":
            continue
        name, mod = it["name"].rsplit(".", 1)[-1], it["sym"].split(":", 1)[0]
        if name not in n_same:
            n_same[name] = sum(1 for x in syms.values() if x["k"] == "class" and x["n"].rsplit(".", 1)[-1] == name)
        kept: list[dict] = []
        for ref in sorted(refs_by.get(name) or [], key=lambda r: (r[0], r[1])):   # scan 按 ast.walk 的顺序收的
            f, l, exact = ref[0], ref[1], len(ref) > 2
            if exact and ref[2] != mod:
                continue                                 # 别的模块里的同名类
            if kept and kept[-1]["f"] == f and 0 <= l - kept[-1]["l"] <= 3:
                if exact and not kept[-1]["exact"]:     # 同一处登记：留带模块的那一行
                    kept[-1] = {"f": f, "l": l, "s": "", "exact": True}
                continue
            kept.append({"f": f, "l": l, "s": "", "exact": exact})
        if not kept:
            continue
        kept.sort(key=lambda r: not r["exact"])          # 带模块的（没有歧义）排前面
        for r in kept[:6]:
            try:
                ls = _file_lines(str(repo / r["f"]), (repo / r["f"]).stat().st_mtime_ns)
                r["s"] = ls[r["l"] - 1].strip()[:200] if 0 < r["l"] <= len(ls) else ""
            except OSError:
                pass
        it["wiring"] = {"refs": kept[:6], "n": len(kept), "same_name": n_same[name]}


def _dyn_hints(repo: Path, idx: dict, items: list) -> None:
    """动态分派的两条线索：调用方那一行（_add_call_sites）、按名字接线的地方（_add_wiring）"""
    _add_call_sites(repo, idx, items)
    _add_wiring(repo, idx, items)


def _name_def(repo: Path, syms: dict, symkey: str) -> dict | None:
    """符号表里没有的「模块:名字」——模块级变量（`LIMIT: int = 30`）、__init__ 再导出的类 / 函数——的定义：
    scan 时 xref 按 `from 模块 import 名字` 追到的（xref.json 的 names，和 Ctrl+点击同一套解析）。
    老的 xref.json 没有 names、或者没追到：None（面板照旧说没找到定义）。"""
    X = load_xref(repo)
    i = (X["x"].get("names") or {}).get(symkey) if X else None
    if i is None:
        return None
    (f, l), (kind, _, key) = X["x"]["where"][i], X["x"]["targets"][i].partition(":")
    return {"f": f, "l": l, "k": (syms.get(key) or {}).get("k") if kind == "s" else "var"}


def _pair_detail(repo: Path, idx: dict, a: str, b: str, hot: dict | None = None) -> dict:
    """点开一条边：它到底承载了什么。

    静态引用 × runtime 调用 两个维度交叉，归成五类：
      confirmed  代码里引用了，这次 case 也真的调到了
      static     代码里引用了，这次没走到（或没有 runtime 数据）
      dynamic    runtime 调到了，但代码里没有静态引用——插件 / getattr / 注册表
      import_only 导入了但本文件从没引用（原因再细分：unused / reexport / type / sideeffect / intentional）
    """
    key = f"{a}|{b}"
    syms = idx.get("symbols") or {}
    uses = (idx.get("edge_uses") or {}).get(key, {})
    dead = (idx.get("edge_dead") or {}).get(key, [])
    sites = (idx.get("edge_sites") or {}).get(key, [])
    calls = ((hot or {}).get("edge_calls") or {}).get(key, {})

    def where(symkey: str) -> dict | None:
        d = syms.get(symkey)
        return {"f": d["f"], "l": d["l"], "k": d["k"]} if d else _name_def(repo, syms, symkey)

    rt_by_top: dict[str, list] = {}
    for callee, info in calls.items():
        rt_by_top.setdefault(_top(callee), []).append({
            "sym": callee, "def": {"f": info["f"], "l": info["l"]}, "n": info["n"],
            "callers": sorted(({"sym": c, "def": {"f": v["f"], "l": v["l"]}, "n": v["n"]}
                               for c, v in info["callers"].items()), key=lambda x: -x["n"])[:8]})

    items = []
    for sym, locs in uses.items():
        rt = rt_by_top.pop(sym, [])
        items.append({"sym": sym, "name": sym.split(":", 1)[1], "def": where(sym),
                      "status": "confirmed" if rt else "static",
                      "uses": [{"f": f, "l": l} for f, l in locs[:20]], "n_uses": len(locs),
                      "runtime": sorted(rt, key=lambda x: -x["n"]),
                      "calls": sum(x["n"] for x in rt)})
    for t, rts in rt_by_top.items():
        items.append({"sym": t, "name": t.split(":", 1)[1], "def": where(t), "status": "dynamic",
                      "uses": [], "n_uses": 0, "runtime": sorted(rts, key=lambda x: -x["n"]),
                      "calls": sum(x["n"] for x in rts)})
    order = {"confirmed": 0, "dynamic": 1, "static": 2}
    items.sort(key=lambda x: (order[x["status"]], -x["calls"], -x["n_uses"], x["name"]))

    mod_file = _module_files(idx)
    ran = set((hot or {}).get("module_exec") or [])
    imp_only = []
    for x in dead:
        f = mod_file.get(x["sym"].split(":")[0]) or mod_file.get(x["sym"])
        imp_only.append({**x, "status": "import_only",
                         "module_ran": bool(hot) and bool(f) and f in ran})

    cnt = {"confirmed": 0, "static": 0, "dynamic": 0}
    for x in items:
        cnt[x["status"]] += 1
    return {"a": a, "b": b, "has_runtime": bool(hot),
            "import_exec": ((hot or {}).get("edge_import_exec") or {}).get(key, 0),
            "static_edge": any(e[0] == a and e[1] == b for e in (idx.get("edges") or [])),
            # 只在 if TYPE_CHECKING: 里 import 了对方（static_edge 为假时，这条「边」运行时不存在）
            "type_edge": any(e[0] == a and e[1] == b for e in (idx.get("type_edges") or [])),
            "sites": sites[:60], "n_sites": len(sites),
            "items": items, "import_only": imp_only,
            "counts": {**cnt, "import_only": len(imp_only),
                       "calls": sum(x["calls"] for x in items)}}


def edge_compare(repo: Path, idx: dict, a: str, b: str, hot: dict | None, hot_b: dict | None) -> dict:
    """对比时的边详情：A 的明细，每一项再带上 B 调了几次（calls_b）；只有 B 调到的符号补在后面
    （calls 为 0）。两个 run 各算一遍 edge_detail 再按符号合，静态的部分两边一样。"""
    d = edge_detail(repo, idx, a, b, hot)
    if not hot_b:
        return d
    db = edge_detail(repo, idx, a, b, hot_b)
    by = {it["sym"]: it for it in db["items"]}
    for it in d["items"]:
        itb = by.pop(it["sym"], None)
        it["calls_b"] = itb["calls"] if itb else 0
        it["runtime_b"] = itb["runtime"] if itb else []
    # 只有 B 调到的：单独一组（only_b），计数也单独记——放进 A 的「动态分派」会说成「这次调到了」
    for sym, itb in by.items():
        if itb["calls"]:
            d["items"].append({**itb, "status": "only_b", "calls": 0, "calls_b": itb["calls"], "runtime": [],
                               "runtime_b": itb["runtime"]})
    d["counts"]["calls_b"] = db["counts"]["calls"]
    d["counts"]["only_b"] = sum(1 for it in d["items"] if it["status"] == "only_b")
    d["has_runtime_b"] = True
    return d


def edge_detail(repo: Path, idx: dict, a: str, b: str, hot: dict | None = None) -> dict:
    """点开一条边：a、b 可以是目录、本层文件或单个文件节点。把两端底下每一对有依赖
    （静态的或 runtime 的）单元的明细合起来；同一个被引用的符号只列一次。"""
    A, B = _cut.units_of(idx, a), _cut.units_of(idx, b)
    if A == [a] and B == [b]:
        d = _pair_detail(repo, idx, a, b, hot)
        _dyn_hints(repo, idx, d["items"])
        return d
    Bs = set(B)
    hot_edges = (hot or {}).get("edges") or {}
    pairs = sorted({(x, y) for x, y, _ in (idx.get("edges") or []) + (idx.get("type_edges") or [])
                    if y in Bs and x in set(A)}
                   | {tuple(k.split("|")) for k in hot_edges
                      if k.split("|")[1] in Bs and k.split("|")[0] in set(A)})
    parts = [_pair_detail(repo, idx, x, y, hot) for x, y in pairs]
    out = {"a": a, "b": b, "has_runtime": bool(hot), "import_exec": 0, "static_edge": False, "type_edge": False,
           "sites": [], "n_sites": 0, "items": [], "import_only": [], "n_pairs": len(parts),
           "counts": {"confirmed": 0, "static": 0, "dynamic": 0, "import_only": 0, "calls": 0}}
    items: dict[str, dict] = {}
    for p in parts:
        out["import_exec"] += p.get("import_exec", 0)
        out["static_edge"] = out["static_edge"] or p["static_edge"]
        out["type_edge"] = out["type_edge"] or p["type_edge"]
        out["sites"] += p["sites"]
        out["n_sites"] += p["n_sites"]
        out["import_only"] += p["import_only"]
        for it in p["items"]:
            cur = items.get(it["sym"])
            if cur is None:
                items[it["sym"]] = {**it, "uses": list(it["uses"]), "runtime": list(it["runtime"])}
                continue
            cur["uses"] += it["uses"]
            cur["n_uses"] += it["n_uses"]
            cur["runtime"] += it["runtime"]
            cur["calls"] += it["calls"]
    for it in items.values():               # 合并完再定状态：同一个符号可能一对里静态引用、另一对里 runtime 调到
        it["status"] = ("confirmed" if it["runtime"] and it["uses"] else
                        "dynamic" if it["runtime"] else "static")
    order = {"confirmed": 0, "dynamic": 1, "static": 2}
    out["items"] = sorted(items.values(), key=lambda x: (order[x["status"]], -x["calls"], -x["n_uses"], x["name"]))
    for it in out["items"]:
        it["uses"] = it["uses"][:20]
        out["counts"][it["status"]] += 1
        out["counts"]["calls"] += it["calls"]
    out["counts"]["import_only"] = len(out["import_only"])
    out["sites"] = out["sites"][:80]
    _dyn_hints(repo, idx, out["items"])
    return out


def _known(idx: dict, rel: str) -> str | None:
    """只允许打开扫描过的文件（Python 或包内的 C++/CUDA），返回所属单元（C++ 是所在目录）。"""
    if rel in (idx.get("files") or {}):
        return idx["files"][rel]
    if rel in (idx.get("aux") or {}):
        return idx["aux"][rel] or "(无所属包)"
    for pkg, ds in (idx.get("docs") or {}).items():         # 挂在目录 / 单元上的文档也能打开
        if any(d["f"] == rel for d in ds):
            return pkg
    return None


def file_outline(repo: Path, idx: dict, rel: str) -> dict | None:
    """一个文件的完整符号大纲（含方法），给详情面板的文件树按需展开。
    Python 直接取扫描时的符号表，不用读文件；C++ / CUDA 用词法大纲（要高亮一遍，有缓存）。"""
    pkg = _known(idx, rel)
    if pkg is None:
        return None
    syms = [{"key": k, "n": x["n"], "k": x["k"], "l": x["l"]}
            for k, x in (idx.get("symbols") or {}).items() if x["f"] == rel]
    if syms or rel.endswith((".py", ".pyi")):
        return {"file": rel, "symbols": sorted(syms, key=lambda d: d["l"]), "outline_kind": "ast"}
    fv = file_view(repo, idx, rel)
    return {"file": rel, "symbols": fv["symbols"] if fv else [], "outline_kind": "lexer"}


def file_view(repo: Path, idx: dict, rel: str) -> dict | None:
    """整个文件（逐行高亮）+ 符号大纲。Python 的大纲来自 ast（精确），
    C++/CUDA 的来自词法 token（启发式）。"""
    pkg = _known(idx, rel)
    if pkg is None:
        return None
    try:
        h = _hl.highlight_file(repo, rel)
    except OSError:
        return None
    if h["lang"] in ("python", "triton"):
        syms = [{"key": k, "n": x["n"], "k": x["k"], "l": x["l"]}
                for k, x in (idx.get("symbols") or {}).items() if x["f"] == rel]
        syms.sort(key=lambda d: d["l"])
        kind = "ast"
    else:
        syms = [{"key": "", "n": o["n"], "k": o["k"], "l": o["l"]} for o in h["outline"]]
        kind = "lexer"
    return {"file": rel, "pkg": pkg, "lang": h["lang"], "lang_label": h["label"],
            "n_lines": len(h["lines"]), "lines": h["lines"],
            "symbols": syms, "outline_kind": kind, "xref": xref_for(repo, rel)}


def symbol_source(repo: Path, idx: dict, key: str, lines: int = 40) -> dict | None:
    s = (idx.get("symbols") or {}).get(key)
    if not s:
        return None
    try:
        h = _hl.highlight_file(repo, s["f"])      # 整文件高亮后再切：从中间切会让跨行字符串着色出错
    except OSError:
        return None
    a = max(0, s["l"] - 1)
    return {"key": key, "name": s["n"], "file": s["f"], "line": s["l"],
            "bases": s.get("b", []), "lang": h["lang"], "lang_label": h["label"],
            "lines": h["lines"][a:a + lines], "xref": xref_for(repo, s["f"], a + 1, a + lines)}


# ---------------------------------------------------------------- 搜索栏

def search_index(idx: dict) -> dict:
    """右边搜索栏要的全部名字，前端自己搜（导出版也能用）：
      mods   [[模块名, 种类 dir / unit, 文件数], ...]   目录树上的每个目录和每个文件级模块
      files  [路径, ...]                               Python 文件和包里的 C++ / CUDA 文件
      units  [所属单元, ...]                           和 files 对齐（C++ 文件是空串）
      syms   [[限定名, 种类首字母 c / f, 文件下标, 行], ...]   类、函数、方法
    符号不存完整的键（模块名重复两万多遍）：键 = 文件所属单元去掉 .__init__ + ":" + 限定名。"""
    tree = idx.get("dirs") or {}
    mods = [[d, "dir", len(_cut.units_of(idx, d))] for d in sorted(tree)]
    mods += [[u, "unit", v["files"]] for u, v in sorted((idx.get("packages") or {}).items())]
    unit_of = idx.get("files") or {}
    files = sorted(set(unit_of) | set(idx.get("aux") or {}))
    at = {f: i for i, f in enumerate(files)}
    syms = [[s["n"], s["k"][0], at[s["f"]], s["l"]] for _, s in sorted((idx.get("symbols") or {}).items())
            if s["f"] in at]
    return {"mods": mods, "files": files, "units": [unit_of.get(f, "") for f in files], "syms": syms}


def reveal(idx: dict, node: str, open_) -> list[str] | None:
    """让一个模块在图上露出来要展开哪些目录（在当前切面的基础上）。"""
    if not _cut.is_node(idx, node):
        return None
    return sorted(_cut.open_for(idx, _norm_open(idx, open_), node))


# ---------------------------------------------------------------- 交叉引用（Ctrl+点击）

_XREF: dict = {"key": None, "x": None}
_XREF_LOCK = threading.Lock()


def load_xref(repo: Path) -> dict | None:
    """scan 写下的 xref.json（按修改时间缓存；重新 scan 之后下一次请求自动换成新的）。
    没有就返回 None：前端不给 Ctrl+点击。serve 是多线程的：新的一份整个建好了再一次性
    换上去，读的人拿到的要么是旧的、要么是新的，不会拿到一半。"""
    global _XREF
    p = repo / ".codestrata" / "xref.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    cur = _XREF
    if cur["key"] == (str(p), mt):
        return cur
    with _XREF_LOCK:
        if _XREF["key"] != (str(p), mt):
            x = json.loads(p.read_text(encoding="utf-8"))
            _XREF = {"key": (str(p), mt), "x": x, "inv": None, "inv_lock": threading.Lock(),
                     "tid": {t: i for i, t in enumerate(x["targets"])}}
        return _XREF


@lru_cache(maxsize=32)
def _xref_fp(path: str, mtime: float) -> dict:
    """xref.json 里每个文件 scan 时的 (大小, mtime)。自己一份小缓存，不走 load_xref 那个单槽的：
    主菜单一次要看好几个仓库，走单槽会互相挤掉、每次都重新解析整个 xref.json"""
    return json.loads(Path(path).read_text(encoding="utf-8")).get("fp") or {}


def _changed(repo: Path, rel: str, fp) -> bool:
    """这个文件和 scan 时记下的 (大小, mtime) 还一样吗；不在了也算改过"""
    try:
        st = (repo / rel).stat()
    except OSError:
        return True
    return [st.st_size, st.st_mtime_ns] != list(fp)


def index_lag(repo: Path) -> int:
    """scan 之后改过（或删掉）了几个文件。index 落后了，图和搜索还是 scan 时的样子
    （Ctrl+点击的交叉引用逐个文件核对，不受影响）。只是提示：算不出来（没 scan、老格式、文件坏了）就当 0"""
    p = repo / ".codestrata" / "xref.json"
    try:
        return sum(_changed(repo, rel, fp) for rel, fp in _xref_fp(str(p), p.stat().st_mtime).items())
    except Exception:                         # noqa: BLE001
        return 0


def _stale(repo: Path, X: dict, rel: str) -> bool:
    """这个文件在 scan 之后改过没有（大小或修改时间变了）。改过的文件，xref 里的行列号
    已经对不上了：链接会落在别的字上、跳到不相干的定义——宁可不给 Ctrl+点击。"""
    fp = (X["x"].get("fp") or {}).get(rel)
    return fp is not None and _changed(repo, rel, fp)   # 老的 xref.json 没记指纹：没法判断，照旧


def xref_for(repo: Path, rel: str, lo: int | None = None, hi: int | None = None) -> dict | None:
    """一个文件（或其中 lo..hi 行）里能解析的名字：[[行, 起, 止, 目标号, 种类], ...]（列是 UTF-16
    下标，和 JS 一致），以及用到的目标 {目标号: [目标, [定义文件, 行] | None]}。
    文件在 scan 之后改过时只回 {"stale": true}。"""
    X = load_xref(repo)
    if not X:
        return None
    if _stale(repo, X, rel):
        return {"stale": True, "toks": [], "targets": {}}
    toks = X["x"]["files"].get(rel) or []
    if lo is not None:
        toks = [t for t in toks if lo <= t[0] <= hi]
    tg, wh = X["x"]["targets"], X["x"]["where"]
    return {"toks": toks, "targets": {i: [tg[i], wh[i]] for i in sorted({t[3] for t in toks})}}


@lru_cache(maxsize=256)
def _lines_of(path: str, mtime_ns: int) -> tuple:
    try:
        return tuple(Path(path).read_text(encoding="utf-8", errors="replace").split("\n"))
    except OSError:
        return ()


def _line_text(repo: Path, rel: str, line: int) -> str:
    try:
        ls = _lines_of(str(repo / rel), (repo / rel).stat().st_mtime_ns)   # 按修改时间失效
    except OSError:
        return ""
    return ls[line - 1] if 0 < line <= len(ls) else ""


def _inverted(X: dict) -> dict:
    if X["inv"] is None:
        with X["inv_lock"]:
            if X["inv"] is None:
                X["inv"] = _xref.invert(X["x"])
    return X["inv"]


def refs(repo: Path, target: str, hot: dict | None = None, limit: int = 500) -> dict | None:
    """一个定义被哪些地方引用：调用在前，其次是普通引用、import。同一行的几处合成一条（×N）。
    每条带上那一行的原文；文件在 scan 之后改过的标 stale（行号可能已经不对）。

    方法、类属性还另给一组「同名的 .xxx」：通过别的对象调用（engine.generate()）时，
    静态分析不知道那个对象是什么类型，确认不了是不是它——按名字列出来，标明没确认，
    并说仓库里一共有几个同名的成员（只有它一个时，基本就是它）。"""
    X = load_xref(repo)
    if not X or target not in X["tid"]:
        return None
    i = X["tid"][target]
    rank = {_xref.CALL: 0, _xref.REF: 1, _xref.IMPORT: 2}
    names = {_xref.CALL: "call", _xref.REF: "ref", _xref.IMPORT: "import"}
    counts: dict[str, int] = {}
    merged: dict[tuple, dict] = {}
    for f, l, c, k in _inverted(X).get(i, []):
        counts[names[k]] = counts.get(names[k], 0) + 1
        m = merged.get((f, l))
        if m is None or rank[k] < rank[m["k"]]:
            merged[(f, l)] = {"f": f, "l": l, "c": c, "k": k, "n": (m["n"] + 1) if m else 1}
        else:
            m["n"] += 1
    rows = sorted(merged.values(), key=lambda r: (rank[r["k"]], r["f"], r["l"]))
    stale_cache: dict[str, bool] = {}

    def stale(f):
        if f not in stale_cache:
            stale_cache[f] = _stale(repo, X, f)
        return stale_cache[f]

    out = []
    for r in rows[:limit]:
        r["text"] = _line_text(repo, r["f"], r["l"]).strip()[:200]
        if stale(r["f"]):
            r["stale"] = True
        out.append(r)
    kind, _, key = target.partition(":")
    wh = X["x"]["where"][i]
    res = {"target": target, "where": wh, "total": sum(counts.values()), "lines": len(rows),
           "counts": counts, "refs": out,
           # 定义本身也放进列表（最上面一条）：跳到某个引用之后，点它就回到定义
           "def": ({"f": wh[0], "l": wh[1], "text": _line_text(repo, wh[0], wh[1]).strip()[:200],
                    **({"stale": True} if stale(wh[0]) else {})} if wh else None),
           "calls": ((hot or {}).get("symbols") or {}).get(key, 0) if kind == "s" else 0}
    qual = key.partition(":")[2]
    if kind in ("s", "v") and "." in qual:           # 类的成员：方法、嵌套类、类属性、实例属性
        name = qual.rsplit(".", 1)[1]
        same = sum(1 for t in X["x"]["targets"]
                   if t[0] in "sv" and "." in t.partition(":")[2].partition(":")[2]
                   and t.rsplit(".", 1)[-1] == name)
        maybe = (X["x"].get("attrs") or {}).get(name) or []
        mrows = {}
        for f, l, c, e, k in maybe:
            m = mrows.get((f, l))
            if m is None:
                mrows[(f, l)] = {"f": f, "l": l, "c": c, "k": k, "n": 1}
            else:
                m["n"] += 1
        mrows = sorted(mrows.values(), key=lambda r: (-r["k"], r["f"], r["l"]))
        for r in mrows[:limit]:
            r["text"] = _line_text(repo, r["f"], r["l"]).strip()[:200]
            if stale(r["f"]):
                r["stale"] = True
        res["maybe"] = {"name": name, "same": same, "total": len(maybe), "lines": len(mrows),
                        "refs": mrows[:limit]}
    return res


_PATHLIST = ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH")


def publicize(pl: dict, home: str, keep: list[str]) -> dict:
    """公开导出（graph --public）：要发到公网上的页面里不带本机的个人信息。
      - 所有字符串（路径、命令、argv、解读正文、源码都算）里的主目录写成 ~；源码行里换了的，这一行上
        Ctrl+点击的列号跟着挪（xref.toks 是按原文算的列）；
      - run 元数据里的命令（rerun / rerun_env / cmd / 各进程 argv）和 env_inherited 中 PATH / LD_LIBRARY_PATH /
        PYTHONPATH 这种目录列表，不在 keep（仓库、各 run 录制时所在的目录；主目录本身、它的上级、/ 不算）
        下面的连续几段合成一个 …——剩下的只是本机装了哪些工具。命令先按 shell 规则切成参数再收、再重新
        加引号，带空格被引号包起来的 PATH 也收得到；case 脚本原文、备注这些内容不动。
    复刻命令因此不能原样执行了：pl["public"] 为真，页面上会说明，原样的在录制的机器上 runs show 里。"""
    import copy
    import html as _html
    from .runs import _q
    home = home.rstrip("/")
    # 后面跟着 .字母 的是另一个名字（/home/yc.bak），句末的 . 不是
    home_re = re.compile(re.escape(home) + r"(?![\w-]|\.[\w-])") if home and home != "/" else None
    keep_abs = []
    for k in keep:
        k = (k or "").rstrip("/")
        if not k or (home and (k == home or home.startswith(k + "/"))):
            continue                                 # 空、/、主目录本身和它的上级：会把整条 PATH 都留下
        keep_abs.append(k)

    def plist(v: str) -> str:
        out: list[str] = []
        for part in v.split(":"):
            if part and any(part == k or part.startswith(k + "/") for k in keep_abs):
                out.append(part)
            elif not out or out[-1] != "…":
                out.append("…")
        return ":".join(out)

    def tok(t: str) -> str:                          # 一个参数：PATH=… / --env=PATH=…
        pre = "--env=" if t.startswith("--env=") else ""
        k, sep, v = t[len(pre):].partition("=")
        return pre + k + "=" + plist(v) if sep and k in _PATHLIST and v else t

    def cmd_str(c: str) -> str:                      # rerun_command 拼出来的一整条 shell 命令
        if not any(n + "=" in c for n in _PATHLIST):
            return c
        import shlex
        try:
            parts = shlex.split(c)
        except ValueError:
            return re.sub(r"\b(" + "|".join(_PATHLIST) + r")=\S+", r"\1=…", c)   # 切不开：整个值都不要
        return " ".join(t if t == "&&" else _q(tok(t)) for t in parts)

    def meta_fix(m):
        if not isinstance(m, dict):
            return m
        m = dict(m)
        for k in ("rerun", "rerun_env"):
            if isinstance(m.get(k), str):
                m[k] = cmd_str(m[k])
        if isinstance(m.get("cmd"), list):
            m["cmd"] = [tok(t) if isinstance(t, str) else t for t in m["cmd"]]
        if isinstance(m.get("procs"), list):
            m["procs"] = [{**p, "argv": [tok(t) if isinstance(t, str) else t for t in p.get("argv") or []]}
                          if isinstance(p, dict) else p for p in m["procs"]]
        if isinstance(m.get("env_inherited"), dict):
            m["env_inherited"] = {k: plist(v) if k in _PATHLIST and isinstance(v, str) else v
                                  for k, v in m["env_inherited"].items()}
        return m

    out = copy.copy(pl)
    if "hotMeta" in out:
        out["hotMeta"] = meta_fix(out["hotMeta"])
    if isinstance(out.get("hotBy"), dict):
        out["hotBy"] = {r: {**v, "meta": meta_fix(v.get("meta"))} if isinstance(v, dict) else v
                        for r, v in out["hotBy"].items()}
    if isinstance(out.get("cmp"), dict) and "meta_b" in out["cmp"]:
        out["cmp"] = {**out["cmp"], "meta_b": meta_fix(out["cmp"]["meta_b"])}

    def u16(x: str) -> int:
        return len(x.encode("utf-16-le")) // 2

    def code(e: dict) -> dict:                       # 一份高亮过的源码（files / sources 的条目）
        lines, base = e.get("lines") or [], e.get("line") or 1
        toks = ((e.get("xref") or {}).get("toks") or [])
        shift: dict[int, list] = {}
        new_lines = []
        for i, ln in enumerate(lines):
            if not isinstance(ln, str) or not home_re.search(ln):
                new_lines.append(ln)
                continue
            text = _html.unescape(re.sub(r"<[^>]+>", "", ln))
            shift[base + i] = [(u16(text[:m.start()]), u16(m.group())) for m in home_re.finditer(text)]
            new_lines.append(home_re.sub("~", ln))
        if not shift:
            return {k: fix(v) for k, v in e.items()}
        nt = []
        for t in toks:
            occ = shift.get(t[0])
            if occ:
                if any(t[1] < p + n and t[2] > p for p, n in occ):
                    continue                         # 名字跨着主目录：不再能点
                d = sum(n - 1 for p, n in occ if p + n <= t[1])
                t = [t[0], t[1] - d, t[2] - d, *t[3:]]
            nt.append(t)
        e2 = {k: fix(v) for k, v in e.items() if k not in ("lines", "xref")}
        e2["lines"] = new_lines
        if "xref" in e:
            e2["xref"] = {**{k: fix(v) for k, v in e["xref"].items()}, "toks": nt}
        return e2

    def fix(x):
        if isinstance(x, str):
            return home_re.sub("~", x) if home_re and "/" in x else x
        if isinstance(x, list):
            return [fix(v) for v in x]
        if isinstance(x, dict):
            if home_re and isinstance(x.get("lines"), list) and "xref" in x:
                return code(x)
            return {fix(k): fix(v) for k, v in x.items()}
        return x
    out = fix(out)
    out["public"] = True
    if home_re:                                      # 最后兜一道：还有主目录就不写出公开页
        left = home_re.search(json.dumps(out, ensure_ascii=False))
        if left:
            raise SystemExit(f"--public：导出里还有主目录 {home}（…{left.string[max(0, left.start() - 60):left.end() + 20]}…），不写出")
    return out


def export_payload(repo: Path, idx: dict, *, hot=None, hot_meta=None,
                   per_pkg: int = 10, lines: int = 30,
                   total_budget: int = 14_000_000, others: list | None = None, compare: bool = False,
                   code: bool = True) -> dict:
    """单文件导出要的全部数据：图 + 已有解读 + 待办输入包 + 代表符号的源码 + 尽量多的全文。
    code=False（site.export_site，源码从 GitHub 取）：不带符号片段、全文和共用的跳转目标表。

    整个 HTML 要装得进一个单文件（artifact 之类的宿主上限 16 MB），所以先算好其余部分，
    剩下的额度才留给全文；这次 case 实际跑到的文件优先。

    others：别的 run [(hot, meta), …]——只带它们在导出切面上的节点、边次数和简要的 meta
    （EMB.hotBy），页面上能在它们之间切换，但边详情里的调用明细只有主 run 的。
    compare：主 run 和 others 的第一个做对比（EMB.cmp，边详情带 calls_b）。"""
    # 同一个 run 给了两遍、或者和主 run 一样：只留一份（主 run 的那份是全的）
    main_ref = (hot_meta or {}).get("run_id", "") + (f"@{hot_meta['phase']}" if (hot_meta or {}).get("phase") else "")
    seen, uniq = {main_ref}, []
    for h, m in others or []:
        ref = m["run_id"] + (f"@{m['phase']}" if m.get("phase") else "")
        if h is not None and ref not in seen:
            seen.add(ref)
            uniq.append((h, m))
    others = uniq
    hb, mb = (others[0] if (compare and others) else (None, None))
    p = graph_payload(repo, idx, hot=hot, hot_meta=hot_meta, hot_b=hb, hot_meta_b=mb)
    hot_by = {}
    if others:
        v = _cut.view(idx, _norm_open(idx, None))
        shown = {n["id"] for n in p["graph"]["nodes"]}
        used = _edge_uses_on_cut(idx, v["node_of"])
        for h, m in others:
            hp, he, hd = _hot_on_cut(h, v["node_of"], used)
            ref = m["run_id"] + (f"@{m['phase']}" if m.get("phase") else "")
            rt = [[k.split("|")[0], k.split("|")[1], n] for k, n in sorted(he.items())
                  if k not in p["edgeKinds"] and k.split("|")[0] in shown and k.split("|")[1] in shown]
            hot_by[ref] = {"packages": hp, "edges": he, "dyn": hd, "unmapped": h.get("anon"),
                           "runtimeOnlyEdges": rt, "dynOnlyEdges": _dyn_only(p["edgeKinds"], [(he, hd)]),
                           "meta": _meta_brief(m)}
    nts = {n["id"]: _notes.load(repo, idx, n["id"]) for n in p["graph"]["nodes"]}
    nts[_notes.OVERVIEW] = _notes.load(repo, idx, _notes.OVERVIEW)
    for name, nt in nts.items():
        nt["problems"] = _notes.verify(repo, idx, name)
    todo = _notes.tasks(repo, idx)
    packs = {t["target"]: _notes.prompt_pack(repo, idx, t["target"], hot=hot) for t in todo}
    # Ctrl+点击的目标（目标串 + 定义位置）全文件共用一张表，每个文件 / 片段只带 token：
    # 早先每个文件各带一份，同一个目标重复几百遍，占掉的额度够再内嵌一两百个文件
    xtargets: dict = {}

    def share(x) -> int:
        """把 x 的目标挪进共用表，返回新增了多少字节"""
        if not x or not x.get("targets"):
            return 0
        new = {k: v for k, v in x.pop("targets").items() if k not in xtargets}
        xtargets.update(new)
        return len(json.dumps(new, ensure_ascii=False)) if new else 0

    sources = {}
    for pkg, syms in (p["pkgSyms"].items() if code else ()):
        for s in syms[:per_pkg]:
            src = symbol_source(repo, idx, s["key"], lines)
            if src:
                share(src.get("xref"))
                sources[s["key"]] = src
    edges = {}
    for a, b, _ in p["graph"]["edges"]:
        edges[f"{a}|{b}"] = edge_compare(repo, idx, a, b, hot, hb)
    for a, b, _ in p["runtimeOnlyEdges"] + p["typeOnlyEdges"]:
        edges[f"{a}|{b}"] = edge_compare(repo, idx, a, b, hot, hb)
    p.update({"notes": nts, "tasks": todo, "packs": packs, "sources": sources, "edges": edges,
              "search": search_index(idx), "xrefTargets": xtargets, "hotBy": hot_by})
    if not code:
        for k in ("sources", "xrefTargets"):
            p.pop(k)
        return p

    # 全文：用剩下的额度。跑到过的文件优先，其次按体积从小到大（同样额度能带上更多文件）。
    # 先用原始字节数估算（高亮 + JSON 转义后约 3 倍），明显放不下的不去高亮，省掉大部分时间。
    remaining = total_budget - len(json.dumps(p, ensure_ascii=False))
    ran = {k.rpartition(":")[0] for k in ((hot or {}).get("symbols") or {})}
    ran |= {s["f"] for k, s in (idx.get("symbols") or {}).items() if k in ((hot or {}).get("symbols") or {})}
    # 解读里引用过的文件也优先：读者最常从解读点进去看的就是它们
    for name, nt in nts.items():
        for m in _notes._REF_RE.finditer(nt.get("md") or ""):
            fp, _ = _notes._resolve_ref(repo, idx, m.group(1), name)
            if fp:
                ran.add(str(fp.relative_to(repo)))
    every = sorted(set(idx.get("files") or {}) | set(idx.get("aux") or {})
                   | {d["f"] for ds in (idx.get("docs") or {}).values() for d in ds})
    def size(rel):
        try:
            return (repo / rel).stat().st_size
        except OSError:
            return 1 << 30
    order = sorted(every, key=lambda r: (r not in ran, size(r)))
    files = {}
    for rel in order:
        if size(rel) * 3 > remaining:
            continue
        fv = file_view(repo, idx, rel)
        if not fv:
            continue
        x = fv.get("xref")
        new = {k: v for k, v in ((x or {}).get("targets") or {}).items() if k not in xtargets}
        if x:
            x.pop("targets", None)
        sz = len(json.dumps(fv, ensure_ascii=False)) + (len(json.dumps(new, ensure_ascii=False)) if new else 0)
        if sz > remaining:
            continue
        xtargets.update(new)
        files[rel] = fv
        remaining -= sz
    p.update({"files": files, "filesTruncated": len(files) < len(every)})
    return p
