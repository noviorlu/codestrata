"""find：按名字找函数 / 类 / 文件 / 目录，再看它在一段时间里被调了几次、在哪几列跑过。给 agent 把「功能」落到具体代码上的抓手。

名字表来自 scan 的索引（和搜索栏同一份数据，打分另写：搜索栏的在冻结的 web/search.js 里，这里多了 `*` 和按种类过滤，
同一个词两边排出来可以不一样——用户 10-10 定的）。匹配不分大小写，顺序：完全一样 > 前缀 > 子串；带 `*` 的按通配。
次数按时序事件现算（每列分开）；没录时序事件的 run 从 counts.json.gz 取总数，不分列。
"""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

KINDS = ("fn", "class", "file", "dir")


def _rank(text: str, names: list[str]) -> int | None:
    """0 完全一样、1 前缀、2 子串、3 通配；对不上是 None。names 是这个东西的几种叫法（短名、限定名、路径），都已小写"""
    if "*" in text:
        return 3 if any(fnmatch.fnmatchcase(n, text) for n in names) else None
    if text in names:
        return 0
    if any(n.startswith(text) for n in names):
        return 1
    if any(text in n for n in names):
        return 2
    return None


def match(idx: dict, text: str, kind: str | None = None, under: str | None = None) -> list[dict]:
    """[{kind, key（函数 / 类是 路径#限定名，文件 / 目录是路径）, name, file, line, rank}]，按 rank、名字长短排"""
    t = (text or "").strip().lower()
    under = (under or "").strip("/")
    out: list[dict] = []

    def ok(path: str) -> bool:
        return not under or path == under or path.startswith(under + "/")

    if kind in (None, "fn", "class"):
        for key, s in (idx.get("symbols") or {}).items():
            k = "class" if s.get("k") == "class" else "fn"
            if kind and k != kind or not ok(s["f"]):
                continue
            r = _rank(t, [s["n"].rsplit(".", 1)[-1].lower(), s["n"].lower()])
            if r is not None:
                out.append({"kind": k, "key": key, "name": s["n"], "file": s["f"], "line": s.get("l"), "rank": r})
    if kind in (None, "file"):
        for f in idx.get("files") or {}:
            if not ok(f):
                continue
            r = _rank(t, [PurePosixPath(f).name.lower(), f.lower()])
            if r is not None:
                out.append({"kind": "file", "key": f, "name": f, "file": f, "line": None, "rank": r})
    if kind in (None, "dir"):
        for d in idx.get("dirs") or {}:
            if not ok(d):
                continue
            r = _rank(t, [PurePosixPath(d).name.lower(), d.lower()])
            if r is not None:
                out.append({"kind": "dir", "key": d + "/", "name": d + "/", "file": None, "line": None, "rank": r})
    out.sort(key=lambda x: (x["rank"], len(x["name"]), x["name"]))
    return out


def node_counts(calls: dict, keys: list[str], threads: dict, label, lane_of) -> dict[str, dict]:
    """seq.phase_calls 的 calls → {函数节点: {列别名: [次数, 首, 末]}}（GPU 的行不算）。lane_of(pid, 线程名) → 列别名"""
    out: dict[str, dict] = {}
    for (pid, tid, _, b), e in calls.items():
        node = label(keys[b]) if 0 <= b < len(keys) else None
        if not node:
            continue
        tname = (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
        x = out.setdefault(node, {}).setdefault(lane_of(pid, tname), [0, e[0], e[1]])
        x[0] += e[2]
        x[1], x[2] = min(x[1], e[0]), max(x[2], e[1])
    return out


def hits_of(item: dict, per_node: dict[str, dict]) -> dict[str, list]:
    """一个东西（函数 / 类 / 文件 / 目录）在这段时间里各列的 [次数, 首, 末]：类合它的方法，文件 / 目录合里面的函数"""
    k = item["kind"]
    if k == "fn":
        nodes = [item["key"]] if item["key"] in per_node else []
    elif k == "class":
        pre = item["key"] + "."
        nodes = [n for n in per_node if n == item["key"] or n.startswith(pre)]
    elif k == "file":
        nodes = [n for n in per_node if n.partition("#")[0] == item["key"]]
    else:
        nodes = [n for n in per_node if n.startswith(item["key"])]
    out: dict[str, list] = {}
    for n in nodes:
        for lane, (c, a, b) in per_node[n].items():
            x = out.setdefault(lane, [0, a, b])
            x[0] += c
            x[1], x[2] = min(x[1], a), max(x[2], b)
    return out
