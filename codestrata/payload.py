"""组装前端要的数据。serve（live）和 export（单文件）共用这一份，免得两边漂移。"""
from __future__ import annotations

import json
from pathlib import Path

from . import cut as _cut
from . import highlight as _hl
from . import layout as _layout
from . import notes as _notes
from . import trace as _trace


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
    return idx


def load_hot(repo: Path, idx: dict, case: str | None) -> tuple[dict | None, dict | None]:
    """case 可以写成 名字@阶段，只叠加那个阶段的调用（见 trace 的 PHASE 约定）。"""
    if not case:
        return None, None
    case, _, phase = case.partition("@")
    tp = repo / ".codestrata" / f"trace-{case}.json"
    if not tp.exists():
        raise SystemExit(f"没有 {tp}；先跑 codestrata trace {repo} --case {case} -- <命令>")
    tr = json.loads(tp.read_text(encoding="utf-8"))
    phases = tr.get("phases") or {}
    if phase:
        if phase not in phases:
            raise SystemExit(f"trace {case} 里没有阶段 {phase!r}；有的是：{', '.join(phases) or '（没分阶段）'}")
        tr = {**tr, "funcs": phases[phase]["funcs"], "func_edges": phases[phase]["func_edges"]}
    hot = _trace.to_package_graph(tr, idx)
    meta = {"case": tr.get("case"), "cmd": tr.get("cmd"), "phase": phase or None,
            "phases": {k: len(v["funcs"]) for k, v in phases.items()},
            "n_procs": tr.get("n_procs"), "unmapped": hot.get("unmapped"),
            # 老 trace 没存哈希时拿不到这个信息，就不报（而不是误报全部过期）
            "stale_files": _trace.stale_files(repo, tr) if tr.get("file_shas") else [],
            # 跑的是安装包时：从哪映射来的、有没有和仓库对不上的文件
            "mapped_from": tr.get("mapped_from"), "n_mapped": len(tr.get("mapped") or {}),
            "mapped_mismatch": tr.get("mapped_mismatch") or []}
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


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, open_=None, lanes="auto", min_files: int = 1) -> dict:
    """一个切面上的全部前端数据。open_ 是展开着的目录（不给就用 scan 算出的默认切面）；
    图、边的种类、hot 叠加、每个节点的文件 / 符号 / 文档，都按这个切面汇总。"""
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
    g = _layout.build(syn, lanes=lanes, min_files=min_files)
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
    hot_view, rt_only = None, []
    if hot:
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
        hot_view = {**hot, "packages": hp, "edges": he}
        shown = {n["id"] for n in g["nodes"]}
        for k, n in he.items():
            a, _, b = k.partition("|")
            if k not in kinds and a in shown and b in shown:
                rt_only.append([a, b, n])
    # hot 视图单独排版：只放跑到的节点，泳道数沿用总图，纵坐标含义不变、横向更紧凑
    g_hot = (_layout.build(syn, lanes=g["lanes"], min_files=min_files,
                           only={p for p, n in hot_view["packages"].items() if n})
             if hot_view else None)
    for nd in (g["nodes"] + (g_hot["nodes"] if g_hot else [])):   # 前端要知道哪些节点能展开、收起到哪里
        x = v["nodes"][nd["id"]]
        nd.update(kind=x["kind"], expandable=x["expandable"], parent=x["parent"],
                  collapsible=x["collapsible"], fanout=x["fanout"], units=x["units"])
    return {"repo": repo_info, "graph": g, "graphHot": g_hot, "pkgs": v["nodes"],
            "pkgSyms": pkg_syms, "pkgFiles": pkg_files, "pkgDocs": pkg_docs,
            "fileLoc": idx.get("file_loc") or {},
            "edgeKinds": kinds, "runtimeOnlyEdges": rt_only,
            "hot": hot_view, "hotMeta": hot_meta,
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
            "symbols": syms, "outline_kind": kind}


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
            "lines": h["lines"][a:a + lines]}


def export_payload(repo: Path, idx: dict, *, hot=None, hot_meta=None,
                   per_pkg: int = 10, lines: int = 30,
                   total_budget: int = 14_000_000) -> dict:
    """单文件导出要的全部数据：图 + 已有解读 + 待办输入包 + 代表符号的源码 + 尽量多的全文。

    整个 HTML 要装得进一个单文件（artifact 之类的宿主上限 16 MB），所以先算好其余部分，
    剩下的额度才留给全文；这次 case 实际跑到的文件优先。"""
    p = graph_payload(repo, idx, hot=hot, hot_meta=hot_meta)
    nts = {n["id"]: _notes.load(repo, idx, n["id"]) for n in p["graph"]["nodes"]}
    nts[_notes.OVERVIEW] = _notes.load(repo, idx, _notes.OVERVIEW)
    for name, nt in nts.items():
        nt["problems"] = _notes.verify(repo, idx, name)
    todo = _notes.tasks(repo, idx)
    packs = {t["target"]: _notes.prompt_pack(repo, idx, t["target"], hot=hot) for t in todo}
    sources = {}
    for pkg, syms in p["pkgSyms"].items():
        for s in syms[:per_pkg]:
            src = symbol_source(repo, idx, s["key"], lines)
            if src:
                sources[s["key"]] = src
    edges = {}
    for a, b, _ in p["graph"]["edges"]:
        edges[f"{a}|{b}"] = edge_detail(repo, idx, a, b, hot)
    for a, b, _ in p["runtimeOnlyEdges"]:
        edges[f"{a}|{b}"] = edge_detail(repo, idx, a, b, hot)
    p.update({"notes": nts, "tasks": todo, "packs": packs, "sources": sources, "edges": edges})

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
        sz = len(json.dumps(fv, ensure_ascii=False))
        if sz > remaining:
            continue
        files[rel] = fv
        remaining -= sz
    p.update({"files": files, "filesTruncated": len(files) < len(every)})
    return p
