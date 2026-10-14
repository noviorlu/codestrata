"""分列的连线（lanes.build 的 links）按（种类, 通道, 起列, 终列）合成组：links 命令列组用它。
组的写法 `l:种类|通道|起列|终列`；页面上画的一条（两头落在两个节点上）再加 `|起节点|终节点`（页面的选中、时间顺序编号的稳定写法）。

一组里两头的（函数, 行）可能有几种（同一个线程往同一个队列里放，1861 行放音频、1863 行放统计），合起来按次数排；
那一头的放 / 取发生在仓库外的代码里时，函数是那一刻这条线程栈底的仓库函数（lanes.build 认的），outside 为真。
"""
from __future__ import annotations


def group_id(kind: str, via: str, fa: str, ta: str, nodes: tuple | None = None) -> str:
    """组的写法；给了 nodes（起节点, 终节点）是页面上画的那一条（两头落在哪两个节点上）"""
    return f"l:{kind}|{via}|{fa}|{ta}" + (f"|{nodes[0] or ''}|{nodes[1] or ''}" if nodes else "")


VERB = {"queue": ("放", "取"), "asyncio": ("放", "取"), "janus": ("放", "取"), "zmq": ("发", "收"), "shm": ("写", "读"),
        "thread": ("起", "线程入口"), "exec": ("起", "子进程"), "fork": ("fork", "子进程"),
        "join": ("被等的", "等到"), "wait": ("被等的", "等到")}


def verbs(via: str) -> tuple[str, str]:
    return VERB.get(via, ("从", "到"))


def end(fn: str | None, line: int, outside: bool, d: dict | None) -> dict:
    """一头：{fn, file, line, outside}（d 是定义 {f, l, k}，没有就按节点的文件）"""
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
                acc[k] = x = {"from": end(pr["a"], pr["la"], pr["xa"], pr.get("da")), "to": end(pr["b"], pr["lb"], pr["xb"], pr.get("db")),
                              "n": 0, "first_us": pr.get("first"), "h": pr.get("h")}
            x["n"] += pr["n"]
            f = pr.get("first")
            if f is not None and (x["first_us"] is None or f < x["first_us"]):
                x["first_us"], x["h"] = f, pr.get("h")
    out = sorted(acc.values(), key=lambda x: (-x["n"], x["first_us"] if x["first_us"] is not None else 0))
    return out, sum(lk.get("n_pairs") or len(lk.get("pairs") or []) for lk in members)
