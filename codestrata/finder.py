"""一个东西（函数 / 类 / 文件 / 目录）这段时间里在哪几列跑过、各几次：页面的标记（/api/marklanes）和 view --focus / --expand 用。"""
from __future__ import annotations


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


def item_kind(idx: dict, item: str) -> str:
    """标记 / 展开 / 选中用的写法（规范的：目录带结尾的 /、文件路径、路径#限定名）→ 种类 dir / file / class / fn"""
    if item.endswith("/"):
        return "dir"
    if item in (idx.get("files") or {}):
        return "file"
    s = (idx.get("symbols") or {}).get(item)
    return "class" if s and s.get("k") == "class" else "fn"


def ran_per_node(rd, run: dict, phase: str | None, label, lane_of) -> dict[str, dict]:
    """这段时间里每个函数节点在各列的 [次数, 首, 末]（node_counts 的结果；lane_of(pid, 线程名) → 列的写法）"""
    from . import seq as _seq
    pc = _seq.phase_calls(rd, run, phase)
    return node_counts(pc["calls"], pc["keys"], pc["threads"], label, lane_of)


def ran_lanes(idx: dict, per_node: dict[str, dict], items: list[str]) -> dict[str, dict]:
    """这些东西这段时间里在哪几列跑过：{东西: {列: [次数, 首, 末]}}（只留跑过的列）——页面的标记只描这些列（用户 10-10 定）"""
    out = {}
    for it in items:
        hits = hits_of({"kind": item_kind(idx, it), "key": it}, per_node)
        out[it] = {ln: x for ln, x in hits.items() if x[0]}
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
