"""分列的连线（lanes.build 的 links）按（种类, 通道, 起列, 终列）合成组：links 命令列组、explain 讲一组，用的是这同一份。
组的写法 `l:种类|通道|起列|终列`（segments 的交接组用同样的写法，从录到的交接直接数）；页面上画的一条（两头落在两个节点上）
再加 `|起节点|终节点`（页面的选中、时间顺序编号的稳定写法）；explain 认 `…#k` 挑这一组 / 这一条里的第 k 种两头。

一组里两头的（函数, 行）可能有几种（同一个线程往同一个队列里放，1861 行放音频、1863 行放统计），合起来按次数排；
那一头的放 / 取发生在仓库外的代码里时，函数是那一刻这条线程栈底的仓库函数（lanes.build 认的），outside 为真。
"""
from __future__ import annotations

from .errors import CodestrataError


def group_id(kind: str, via: str, fa: str, ta: str, nodes: tuple | None = None) -> str:
    """组的写法；给了 nodes（起节点, 终节点）是页面上画的那一条（两头落在哪两个节点上）"""
    return f"l:{kind}|{via}|{fa}|{ta}" + (f"|{nodes[0] or ''}|{nodes[1] or ''}" if nodes else "")


def parse(item: str) -> tuple[str, str, str, str, tuple | None, int | None]:
    """'l:种类|通道|起列|终列[|起节点|终节点][#k]' → (种类, 通道, 起列, 终列, (起节点, 终节点) 或 None, k)。
    带两个节点的是页面上画的那一条（页面的选中、时间顺序的编号都这么写），不带的是整组"""
    body, sep, k = item.rpartition("#") if "#" in item.rpartition("|")[2] else (item, "", "")
    parts = body.split("|")
    if len(parts) not in (4, 6) or not parts[0].startswith("l:"):
        raise CodestrataError("usage", f"连线写成 'l:种类|通道|起列|终列'，页面上的一条再加 '|起节点|终节点'（都可以加 #k 挑第 k 种两头）：{item!r}")
    if sep and not k.isdigit():
        raise CodestrataError("usage", f"'#' 后面是第几种两头（数字）：{item!r}")
    return parts[0][2:], parts[1], parts[2], parts[3], (parts[4], parts[5]) if len(parts) == 6 else None, int(k) if sep else None


def find(built: dict, aliases: dict, item: str) -> tuple[dict | None, int | None, list[str]]:
    """一个连线的写法 → (组（带节点的写法只含那一条）、k、同种类的组的写法：找不到时当候选)"""
    kind, via, fa, ta, nodes, k = parse(item)
    links = built["links"]
    if nodes is not None:
        links = [lk for lk in links if ((lk["from"].get("node") or ""), (lk["to"].get("node") or "")) == nodes]
    gs = groups({"links": links}, aliases, "all")
    hit = next((g for g in gs if (g["kind"], g["via"], g["from"], g["to"]) == (kind, via, fa, ta)), None)
    if hit is not None and nodes is not None:
        hit["id"] = group_id(kind, via, fa, ta, nodes)
    return hit, k, [g["id"] for g in groups(built, aliases, "all") if g["kind"] == kind]


def _end(fn: str | None, line: int, outside: bool, d: dict | None) -> dict:
    """一头：{fn, file, line, outside}"""
    return {"fn": fn, "file": (d or {}).get("f") or (fn or "").partition("#")[0] or None, "line": line or None, "outside": bool(outside)}


def groups(built: dict, aliases: dict, kind: str = "handoff", want: set | None = None) -> list[dict]:
    """[{id, kind, via, from, to, n, first_us, last_us, cross, pairs: [{from, to, n, first_us, h}], n_pairs, members}]，按首次的先后。
    kind 是 all 时不分种类；want：只要一头在这些列 id 里的；整条都在段外（out）的不算"""
    gs: dict[tuple, dict] = {}
    for lk in built["links"]:
        if kind != "all" and lk["kind"] != kind or lk.get("out"):
            continue
        if want is not None and lk["from"]["lane"] not in want and lk["to"]["lane"] not in want:
            continue
        fa, ta = aliases.get(lk["from"]["lane"], lk["from"]["lane"]), aliases.get(lk["to"]["lane"], lk["to"]["lane"])
        g = gs.setdefault((lk["kind"], lk["via"], fa, ta), {
            "id": group_id(lk["kind"], lk["via"], fa, ta), "kind": lk["kind"], "via": lk["via"], "from": fa, "to": ta,
            "n": 0, "first_us": lk["first"], "last_us": lk["last"],
            "cross": lk["from"]["lane"].partition(":")[0] != lk["to"]["lane"].partition(":")[0], "members": []})
        g["n"] += lk["n"]
        if lk["first"] is not None:
            g["first_us"] = lk["first"] if g["first_us"] is None else min(g["first_us"], lk["first"])
        if lk["last"] is not None:
            g["last_us"] = lk["last"] if g["last_us"] is None else max(g["last_us"], lk["last"])
        g["members"].append(lk)
    for g in gs.values():
        g["pairs"], g["n_pairs"] = merged_pairs(g["members"])
    return sorted(gs.values(), key=lambda g: (g["first_us"] is None, g["first_us"] or 0))


def merged_pairs(members: list[dict]) -> tuple[list[dict], int]:
    """几条连线的两头（函数, 行）合起来按次数排：([{from, to, n, first_us, h}], 一共几种——每条连线只带了前 8 种)"""
    acc: dict[tuple, dict] = {}
    for lk in members:
        for pr in lk.get("pairs") or []:
            k = (pr["a"], pr["la"], pr["b"], pr["lb"], pr["xa"], pr["xb"])
            x = acc.get(k)
            if x is None:
                acc[k] = x = {"from": _end(pr["a"], pr["la"], pr["xa"], pr.get("da")), "to": _end(pr["b"], pr["lb"], pr["xb"], pr.get("db")),
                              "n": 0, "first_us": pr.get("first"), "h": pr.get("h")}
            x["n"] += pr["n"]
            f = pr.get("first")
            if f is not None and (x["first_us"] is None or f < x["first_us"]):
                x["first_us"], x["h"] = f, pr.get("h")
    out = sorted(acc.values(), key=lambda x: (-x["n"], x["first_us"] if x["first_us"] is not None else 0))
    return out, sum(lk.get("n_pairs") or len(lk.get("pairs") or []) for lk in members)
