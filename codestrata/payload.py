"""组装前端要的数据。serve（live）和 export（单文件）共用这一份，免得两边漂移。"""
from __future__ import annotations

import json
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


def _hot_on_cut(hot: dict, node_of: dict) -> tuple[dict, dict]:
    """一个 run 的 hot（单元粒度）按切面汇总：(节点 → 次数, "a|b" 节点间的边 → 次数)。"""
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
    return hp, he


def _meta_brief(m: dict | None) -> dict | None:
    """对比 / 导出里别的 run 只带这些：够横幅和下拉用"""
    if not m:
        return None
    # 横幅和帮助里要读的都带上（都不大）：换到导出里别的 run 时，安装包映射、命令、进程这些说明不能没了
    return {k: m.get(k) for k in ("run_id", "case", "phase", "phases", "status", "problems", "created",
                                    "tags", "note", "git", "n_procs", "stale_files", "unmatched", "events",
                                    "mapped_from", "n_mapped", "mapped_mismatch", "unmapped", "cmd", "procs",
                                    "script", "file_state")}


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, open_=None, lanes="auto", min_files: int = 1,
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
    syn = {"repo": idx["repo"], "packages": v["nodes"], "edges": v["edges"], "frames": frames}
    g = _layout.build(syn, lanes=lanes, min_files=min_files, width=width)
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
    uses, dead = idx.get("edge_uses") or {}, idx.get("edge_dead") or {}
    kinds: dict[str, dict] = {}
    syms_used: dict[str, set] = {}
    for a, b, w in idx.get("edges") or []:
        na, nb = node_of[a], node_of[b]
        if na == nb:
            continue
        k = f"{na}|{nb}"
        d = kinds.setdefault(k, {"uses": 0, "dead": 0, "sites": 0})
        syms_used.setdefault(k, set()).update(uses.get(f"{a}|{b}", {}))
        d["dead"] += len(dead.get(f"{a}|{b}", []))
        d["sites"] += w
    for k, ss in syms_used.items():
        kinds[k]["uses"] = len(ss)
    # hot 叠加也按切面汇总；只在 runtime 出现、静态 import 图里根本没有的节点间调用——插件、
    # importlib、注册表——是静态分析的盲区，必须单独画出来，否则图会说谎。
    # 对比（hot_b，另一个 run）：两边各自按切面汇总，节点和边上都带 [A, B] 两个次数；
    # 只在 runtime 出现的边、「只看跑到的」都取两边的并集
    hot_view, rt_only, cmp = None, [], None
    if hot:
        hp, he = _hot_on_cut(hot, node_of)
        hot_view = {**hot, "packages": hp, "edges": he}
        hpb, heb = _hot_on_cut(hot_b, node_of) if hot_b else ({}, {})
        if hot_b:
            ref_b = (hot_meta_b or {}).get("run_id", "?") + (f"@{hot_meta_b['phase']}" if (hot_meta_b or {}).get("phase") else "")
            cmp = {"ref_b": ref_b, "meta_b": _meta_brief(hot_meta_b),
                   "nodes": {n: [hp.get(n, 0), hpb.get(n, 0)] for n in set(hp) | set(hpb) if hp.get(n) or hpb.get(n)},
                   "edges": {k: [he.get(k, 0), heb.get(k, 0)] for k in set(he) | set(heb) if he.get(k) or heb.get(k)}}
        shown = {n["id"] for n in g["nodes"]}
        for k in sorted(set(he) | set(heb)):
            a, _, b = k.partition("|")
            if k not in kinds and a in shown and b in shown:
                rt_only.append([a, b, max(he.get(k, 0), heb.get(k, 0))])
    # hot 视图单独排版：只放跑到的节点（对比时两边任一跑到的），泳道数沿用总图，纵坐标含义不变、横向更紧凑
    g_hot = (_layout.build(syn, lanes=g["lanes"], min_files=min_files, width=width,
                           only={p for p, n in hot_view["packages"].items() if n} | set((cmp or {}).get("nodes") or {}))
             if hot_view else None)
    for nd in (g["nodes"] + (g_hot["nodes"] if g_hot else [])):   # 前端要知道哪些节点能展开、收起到哪里
        x = v["nodes"][nd["id"]]
        nd.update(kind=x["kind"], expandable=x["expandable"], parent=x["parent"],
                  collapsible=x["collapsible"], fanout=x["fanout"], units=x["units"])
    return {"repo": repo_info, "graph": g, "graphHot": g_hot, "pkgs": v["nodes"],
            "pkgSyms": pkg_syms, "pkgFiles": pkg_files, "pkgDocs": pkg_docs,
            "fileLoc": idx.get("file_loc") or {},
            "edgeKinds": kinds, "runtimeOnlyEdges": rt_only,
            "hot": hot_view, "hotMeta": hot_meta, "cmp": cmp,
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
        return {"f": d["f"], "l": d["l"], "k": d["k"]} if d else None

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
        return _pair_detail(repo, idx, a, b, hot)
    Bs = set(B)
    hot_edges = (hot or {}).get("edges") or {}
    pairs = sorted({(x, y) for x, y, _ in idx.get("edges") or [] if y in Bs and x in set(A)}
                   | {tuple(k.split("|")) for k in hot_edges
                      if k.split("|")[1] in Bs and k.split("|")[0] in set(A)})
    parts = [_pair_detail(repo, idx, x, y, hot) for x, y in pairs]
    out = {"a": a, "b": b, "has_runtime": bool(hot), "import_exec": 0, "static_edge": False,
           "sites": [], "n_sites": 0, "items": [], "import_only": [], "n_pairs": len(parts),
           "counts": {"confirmed": 0, "static": 0, "dynamic": 0, "import_only": 0, "calls": 0}}
    items: dict[str, dict] = {}
    for p in parts:
        out["import_exec"] += p.get("import_exec", 0)
        out["static_edge"] = out["static_edge"] or p["static_edge"]
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


def _stale(repo: Path, X: dict, rel: str) -> bool:
    """这个文件在 scan 之后改过没有（大小或修改时间变了）。改过的文件，xref 里的行列号
    已经对不上了：链接会落在别的字上、跳到不相干的定义——宁可不给 Ctrl+点击。"""
    fp = (X["x"].get("fp") or {}).get(rel)
    if fp is None:
        return False                      # 老的 xref.json 没记指纹：没法判断，照旧
    try:
        st = (repo / rel).stat()
    except OSError:
        return True
    return [st.st_size, st.st_mtime_ns] != list(fp)


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


def export_payload(repo: Path, idx: dict, *, hot=None, hot_meta=None,
                   per_pkg: int = 10, lines: int = 30,
                   total_budget: int = 14_000_000, others: list | None = None, compare: bool = False) -> dict:
    """单文件导出要的全部数据：图 + 已有解读 + 待办输入包 + 代表符号的源码 + 尽量多的全文。

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
        for h, m in others:
            hp, he = _hot_on_cut(h, v["node_of"])
            ref = m["run_id"] + (f"@{m['phase']}" if m.get("phase") else "")
            rt = [[k.split("|")[0], k.split("|")[1], n] for k, n in sorted(he.items())
                  if k not in p["edgeKinds"] and k.split("|")[0] in shown and k.split("|")[1] in shown]
            hot_by[ref] = {"packages": hp, "edges": he, "unmapped": h.get("unmapped"),
                           "runtimeOnlyEdges": rt, "meta": _meta_brief(m)}
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
    for pkg, syms in p["pkgSyms"].items():
        for s in syms[:per_pkg]:
            src = symbol_source(repo, idx, s["key"], lines)
            if src:
                share(src.get("xref"))
                sources[s["key"]] = src
    edges = {}
    for a, b, _ in p["graph"]["edges"]:
        edges[f"{a}|{b}"] = edge_compare(repo, idx, a, b, hot, hb)
    for a, b, _ in p["runtimeOnlyEdges"]:
        edges[f"{a}|{b}"] = edge_compare(repo, idx, a, b, hot, hb)
    p.update({"notes": nts, "tasks": todo, "packs": packs, "sources": sources, "edges": edges,
              "search": search_index(idx), "xrefTargets": xtargets, "hotBy": hot_by})

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
