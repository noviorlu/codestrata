"""组装 serve 的前端要的数据。"""
from __future__ import annotations

import json
import sys
import threading
from functools import lru_cache
from pathlib import Path

from . import align as _align
from . import cut as _cut
from . import highlight as _hl
from . import layout as _layout
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
            "n_parse_errors": r.get("n_parse_errors"), "roots": r.get("roots") or [],
            "outdated": idx.get("format") != _cut.INDEX_FORMAT}


def load_index(repo: Path) -> dict:
    d = repo / ".codestrata"
    p = d / "index.json"
    if not p.exists():
        raise SystemExit(f"没有 {p}；先跑 codestrata scan {repo}")
    idx = json.loads(p.read_text(encoding="utf-8"))
    if idx.get("format") != _cut.INDEX_FORMAT:
        raise SystemExit(f"{p} 是旧版本的格式；重新跑一次 codestrata scan {repo}")
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


def norm_open(idx: dict, open_) -> set:
    return set(idx.get("default_open") or []) if open_ is None else {o for o in open_ if _cut.is_node(idx, o)}


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, open_=None, min_files: int = 1,
                  width: float = 1180.0) -> dict:
    """一个切面上的全部前端数据。open_ 是展开着的目录（不给就用 scan 算出的默认切面）；
    图、边的种类、hot 叠加、每个节点的文件 / 符号 / 文档，都按这个切面汇总。
    width：页面上图框有多宽——按它排版，宽屏上图铺满、少折行，而不是把 1180 宽的图放大"""
    open_ = norm_open(idx, open_)
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
            segs, sep = _cut.label(idx, f)
            frames[f] = {"parent": p if p != top else None, "kind": _cut.kind(idx, f), "n": 0,
                         "label": sep.join(segs), "sep": sep}
            f = frames[f]["parent"]
    for n in _cut.visible(v):              # 每个框里一共有几个画得出来的节点（hot 视图只画一部分）
        f = v["nodes"][n]["frame"]
        while f:
            frames[f]["n"] += 1
            f = frames[f]["parent"]
    # 同一个切面上短名撞了的（flask.app 和 flask.sansio.app 都叫 app）：补上父目录段，图上和面板里一样
    alias = _cut.disambiguate(idx, set(_cut.visible(v)) | set(frames))
    syn = {"repo": idx["repo"], "packages": v["nodes"], "edges": v["edges"], "frames": frames, "alias": alias,
           "root_label": _cut.root_label(idx)}
    # 分层（纵轴）：叠了 run 就按这次实际发生的调用排，调用方在上；
    # 静态 import 只作次要依据——基类回调子类、注册表、回调这些调用和 import 的方向是反的
    rt_calls = _align.hot_on_cut(hot, v["node_of"])[1] if hot else {}
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
    syms_used = _align.edge_uses_on_cut(idx, node_of)
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
    hot_view, rt_only, dyn_only = None, [], []
    shown = {n["id"] for n in g["nodes"]}
    type_only = [[*k.split("|"), w] for k, w in sorted(type_w.items()) if set(k.split("|")) <= shown]
    if hot:
        hp, he, hd = _align.hot_on_cut(hot, node_of, syms_used)
        hot_view = {**hot, "packages": hp, "edges": he, "dyn": hd}
        dyn_only = _align.dyn_only(kinds, he, hd)
        for k in sorted(he):
            a, _, b = k.partition("|")
            if k not in kinds and a in shown and b in shown:
                rt_only.append([a, b, he[k]])
    # hot 视图单独排版：只放跑到的节点，每个节点的层沿用总图，纵坐标含义不变、横向更紧凑
    # 「跑到的」节点：这一段里有函数被调用进去的，加上这一段里任何一条 runtime 边（动态分派的也算）的两端。
    # 调用方不一定有「被调用」的次数：一直在跑的外层函数（case 脚本的 main 在上一个阶段就进去了）、
    # import 时执行的模块顶层（定义，不算调用）——少了它们，边就没有起点
    ran = ({p for p, n in hot_view["packages"].items() if n}
           | {x for k in hot_view["edges"] for x in k.split("|")}) if hot_view else set()
    g_hot = (_layout.build(syn, lane_of={n["id"]: n["lane"] for n in g["nodes"]},
                           lane_labels={r["i"]: r["label"] for r in g["lane_rows"]}, min_files=min_files, width=width,
                           only=ran)
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
    # 面板、搜索栏写的短名（不带框的相对部分）：撞了名的用补过父目录段的，其余是显示名的最后一段
    # labels 是完整的显示名（标题用：vllm_omni.engine.core）
    names, labels = {}, {}
    for n in set(v["nodes"]) | set(frames):
        own = _cut.residual_base(n) if _cut.is_residual(n) else n
        names[n] = alias.get(own) or _cut.short(idx, own)
        segs, sep = _cut.label(idx, own)
        labels[n] = sep.join(segs)
    return {"repo": repo_info, "graph": g, "graphHot": g_hot, "pkgs": v["nodes"], "names": names, "labels": labels,
            "rootLabel": _cut.sep_join(idx, _cut.root_label(idx)),
            "pkgSyms": pkg_syms, "pkgFiles": pkg_files, "pkgDocs": pkg_docs,
            "fileLoc": idx.get("file_loc") or {},
            "alias": alias, "edgeKinds": kinds, "runtimeOnlyEdges": rt_only, "dynOnlyEdges": dyn_only, "typeOnlyEdges": type_only,
            "hot": hot_view, "hotMeta": hot_meta, "phaseMarks": phase_marks,
            "open": sorted(open_), "defaultOpen": idx.get("default_open") or [],
            "autoSplit": idx["repo"].get("auto_split") or []}


def _name_def(repo: Path, syms: dict, symkey: str) -> dict | None:
    """符号表里没有的「<路径>#<名字>」——模块级变量（`LIMIT: int = 30`）、__init__ 再导出的类 / 函数——的定义：
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

    def runtime(callee: str, info: dict) -> dict:
        return {"sym": callee, "def": {"f": info["f"], "l": info["l"]}, "n": info["n"],
                "callers": sorted(({"sym": c, "def": {"f": v["f"], "l": v["l"]}, "n": v["n"]}
                                   for c, v in info["callers"].items()), key=lambda x: -x["n"])[:8]}

    items = []
    for sym, locs, rts, status in _align.pair_items(uses, calls):
        rt = [runtime(c, info) for c, info in rts]
        items.append({"sym": sym, "name": sym.partition("#")[2], "def": where(sym), "status": status,
                      "uses": [{"f": f, "l": l} for f, l in locs[:20]], "n_uses": len(locs),
                      "runtime": sorted(rt, key=lambda x: -x["n"]),
                      "calls": sum(x["n"] for x in rt)})
    order = {"confirmed": 0, "dynamic": 1, "static": 2}
    items.sort(key=lambda x: (order[x["status"]], -x["calls"], -x["n_uses"], x["name"]))

    ran = set((hot or {}).get("module_exec") or [])
    imp_only = []
    for x in dead:
        f = x["sym"].partition("#")[0]                # 导入的是模块（它的路径）或模块里的名字（<路径>#<名字>）
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


def edge_detail(repo: Path, idx: dict, a: str, b: str, hot: dict | None = None) -> dict:
    """点开一条边：a、b 可以是目录、本层文件或单个文件节点。把两端底下每一对有依赖
    （静态的或 runtime 的）单元的明细合起来；同一个被引用的符号只列一次。"""
    A, B = _cut.units_of(idx, a), _cut.units_of(idx, b)
    if A == [a] and B == [b]:
        d = _pair_detail(repo, idx, a, b, hot)
        _align.hints(repo, idx, d["items"])
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
        it["status"] = _align.merged_status(it["uses"], it["runtime"])
    order = {"confirmed": 0, "dynamic": 1, "static": 2}
    out["items"] = sorted(items.values(), key=lambda x: (order[x["status"]], -x["calls"], -x["n_uses"], x["name"]))
    for it in out["items"]:
        it["uses"] = it["uses"][:20]
        out["counts"][it["status"]] += 1
        out["counts"]["calls"] += it["calls"]
    out["counts"]["import_only"] = len(out["import_only"])
    out["sites"] = out["sites"][:80]
    _align.hints(repo, idx, out["items"])
    return out


def known_file(idx: dict, rel: str) -> str | None:
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
    pkg = known_file(idx, rel)
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
    pkg = known_file(idx, rel)
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
    """右边搜索栏要的全部名字，前端自己搜：
      mods   [[id, 种类 dir / unit, 文件数, 显示名, 分隔符], ...]   目录树上的每个目录和每个单元
      files  [路径, ...]                               单元的文件和包里的 C++ / CUDA 文件
      units  [所属单元, ...]                           和 files 对齐（C++ 文件是空串）
      syms   [[限定名, 种类首字母 c / f, 文件下标, 行], ...]   类、函数、方法
    符号不存完整的键（路径重复两万多遍）：键 = files[文件下标] + "#" + 限定名。"""
    tree = idx.get("dirs") or {}

    def mod(x: str, kind: str, n: int) -> list:
        segs, sep = _cut.label(idx, x)
        return [x, kind, n, sep.join(segs), sep]
    mods = [mod(d, "dir", len(_cut.units_of(idx, d))) for d in sorted(tree)]
    mods += [mod(u, "unit", v["files"]) for u, v in sorted((idx.get("packages") or {}).items())]
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
    return sorted(_cut.open_for(idx, norm_open(idx, open_), node))


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


def xref_inverted(X: dict) -> dict:
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
    for f, l, c, k in xref_inverted(X).get(i, []):
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
    qual = key.partition("#")[2]
    if kind in ("s", "v") and "." in qual:           # 类的成员：方法、嵌套类、类属性、实例属性
        name = qual.rsplit(".", 1)[1]
        same = sum(1 for t in X["x"]["targets"]
                   if t[0] in "sv" and "." in t.partition("#")[2]
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
