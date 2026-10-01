"""点开一条边：它承载了哪些引用和调用（给 /api/edge）。两边怎么对上由 align 定。"""
from __future__ import annotations

from pathlib import Path

from .. import align as _align
from .. import cut as _cut
from . import source as _source


def _name_def(repo: Path, syms: dict, symkey: str) -> dict | None:
    """符号表里没有的「<路径>#<名字>」——模块级变量（`LIMIT: int = 30`）、__init__ 再导出的类 / 函数——的定义：
    scan 时 xref 按 `from 模块 import 名字` 追到的（xref.json 的 names，和 Ctrl+点击同一套解析）。
    老的 xref.json 没有 names、或者没追到：None（面板照旧说没找到定义）。"""
    X = _source.load_xref(repo)
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
