"""组装前端要的数据。serve（live）和 export（单文件）共用这一份，免得两边漂移。"""
from __future__ import annotations

import json
from pathlib import Path

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
    return idx


def load_hot(repo: Path, idx: dict, case: str | None) -> tuple[dict | None, dict | None]:
    if not case:
        return None, None
    tp = repo / ".codestrata" / f"trace-{case}.json"
    if not tp.exists():
        raise SystemExit(f"没有 {tp}；先跑 codestrata trace {repo} --case {case} -- <命令>")
    tr = json.loads(tp.read_text(encoding="utf-8"))
    hot = _trace.to_package_graph(tr, idx)
    meta = {"case": tr.get("case"), "cmd": tr.get("cmd"),
            "n_procs": tr.get("n_procs"), "unmapped": hot.get("unmapped"),
            # 老 trace 没存哈希时拿不到这个信息，就不报（而不是误报全部过期）
            "stale_files": _trace.stale_files(repo, tr) if tr.get("file_shas") else []}
    return hot, meta


def _pkg_syms(idx: dict) -> dict:
    out: dict[str, list] = {}
    for key, s in (idx.get("symbols") or {}).items():
        if "." in s["n"]:                  # 只列顶层类/函数，方法太多
            continue
        out.setdefault(s["p"], []).append(
            {"key": key, "n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"],
             "b": s.get("b", [])})
    for v in out.values():
        v.sort(key=lambda d: (d["k"] != "class", d["f"], d["l"]))
    return out


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, lanes="auto", min_files: int = 1) -> dict:
    g = _layout.build(idx, lanes=lanes, min_files=min_files)
    repo_info = dict(idx["repo"])
    repo_info["n_symbols"] = len(idx.get("symbols") or {})
    pkg_files: dict[str, list] = {}
    for rel, pkg in list((idx.get("files") or {}).items()) + list((idx.get("aux") or {}).items()):
        if pkg:
            pkg_files.setdefault(pkg, []).append(rel)
    for v in pkg_files.values():
        v.sort()
    # 每条静态边的「实质」：用到了对方几个符号、有几个只 import 没用的绑定。
    # 一个符号都没用到的边（纯 import）在图上画成虚线——它不承载任何调用。
    uses, dead = idx.get("edge_uses") or {}, idx.get("edge_dead") or {}
    kinds = {}
    for a, b, w in g["edges"]:
        k = f"{a}|{b}"
        kinds[k] = {"uses": len(uses.get(k, {})), "dead": len(dead.get(k, [])), "sites": w}
    # 只在 runtime 出现、静态 import 图里根本没有的包间调用——插件、importlib、注册表。
    # 这是静态分析的盲区，必须单独画出来，否则图会说谎。
    rt_only = []
    if hot:
        static = {f"{a}|{b}" for a, b, _ in g["edges"]}
        shown = {n["id"] for n in g["nodes"]}
        for k, n in hot.get("edges", {}).items():
            a, _, b = k.partition("|")
            if k not in static and a in shown and b in shown:
                rt_only.append([a, b, n])
    return {"repo": repo_info, "graph": g, "pkgs": idx["packages"],
            "pkgSyms": _pkg_syms(idx), "pkgFiles": pkg_files,
            "edgeKinds": kinds, "runtimeOnlyEdges": rt_only,
            "hot": hot, "hotMeta": hot_meta}


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


def edge_detail(repo: Path, idx: dict, a: str, b: str, hot: dict | None = None) -> dict:
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


def _known(idx: dict, rel: str) -> str | None:
    """只允许打开扫描过的文件（Python 或包内的 C++/CUDA），返回所属包。"""
    if rel in (idx.get("files") or {}):
        return idx["files"][rel]
    if rel in (idx.get("aux") or {}):
        return idx["aux"][rel] or "(无所属包)"
    return None


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
                   file_budget: int = 8_000_000) -> dict:
    """单文件导出要的全部数据：图 + 已有解读 + 待办输入包 + 代表符号的源码。"""
    p = graph_payload(repo, idx, hot=hot, hot_meta=hot_meta)
    nts = {name: _notes.load(repo, idx, name) for name in list(idx["packages"]) + [_notes.OVERVIEW]}
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
    # 整文件内嵌有上限：小仓库全带上；大仓库（vllm-omni 57 万行）只能带一部分，
    # 超出的文件在导出版里退化成只看符号片段，要看全文就用 serve。
    files, used = {}, 0
    every = sorted(set(idx.get("files") or {}) | set(idx.get("aux") or {}))
    for rel in every:
        fv = file_view(repo, idx, rel)
        if not fv:
            continue
        sz = sum(len(x) for x in fv["lines"])        # 高亮后的 HTML 才是真实体积
        if used + sz > file_budget:
            continue
        files[rel] = fv
        used += sz
    edges = {}
    for a, b, _ in p["graph"]["edges"]:
        edges[f"{a}|{b}"] = edge_detail(repo, idx, a, b, hot)
    for a, b, _ in p["runtimeOnlyEdges"]:
        edges[f"{a}|{b}"] = edge_detail(repo, idx, a, b, hot)
    p.update({"notes": nts, "tasks": todo, "packs": packs, "sources": sources,
              "files": files, "filesTruncated": len(files) < len(every), "edges": edges})
    return p
