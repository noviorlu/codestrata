"""分列里时间顺序的编号（页面上的 1、2、3… 号牌）：页面和命令行（explain 24）用同一份。

编号的是：每列里的边（两头的节点都在这一列里）和交接连线，第一次发生在这段时间里的；按 (第一次, 最后一次, 稳定写法) 排——
同一时刻的几条按稳定写法比先后，不按列表下标（换个切面，同一时刻的几条不会互换）。编号和视图无关：收起的进程、只看几列时
看不见的号空着，不重排。
"""
from __future__ import annotations


def rank(L: dict, aliases: dict[str, str]) -> dict:
    """{"keys": {页面上的 key（e:列 id|a|b、l:下标）: 名次（从 0 数）}, "ids": [按名次的稳定写法], "n"}"""
    lo, hi = (L.get("window") or [0, 0])[:2]
    items = []
    for ln in L["lanes"]:
        al = aliases.get(ln["id"], ln["id"])
        for e in ln.get("edges") or []:
            if e["a"] not in ln["nodes"] or e["b"] not in ln["nodes"]:
                continue
            if e.get("first") is not None and lo <= e["first"] <= hi:
                items.append((e["first"], e.get("last") or 0, f"e:{al}|{e['a']}|{e['b']}", f"e:{ln['id']}|{e['a']}|{e['b']}"))
    for i, k in enumerate(L.get("links") or []):
        if k["kind"] != "handoff" or k.get("inferred") or k.get("first") is None or not lo <= k["first"] <= hi:
            continue
        fa, ta = aliases.get(k["from"]["lane"], k["from"]["lane"]), aliases.get(k["to"]["lane"], k["to"]["lane"])
        stable = f"l:handoff|{k['via']}|{fa}|{ta}|{k['from'].get('node') or ''}|{k['to'].get('node') or ''}"
        items.append((k["first"], k.get("last") or 0, stable, f"l:{i}"))
    items.sort()
    return {"keys": {x[3]: r for r, x in enumerate(items)}, "ids": [x[2] for x in items], "n": len(items)}
