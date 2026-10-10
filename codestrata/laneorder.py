"""分列里时间顺序的编号（页面上的 1、2、3… 号牌）：按视图算，页面和命令行（explain 24）用同一份。

一个视图里编号的是：画着的列（没收起的进程里、只看列时选中的列）里画着的边（两头的节点都在这一列里，开关没藏掉它）
和画着的交接连线（两头落在同一个收起的窄列里的不画），第一次发生在这段时间里的；按 (第一次, 最后一次, 稳定写法) 排——同一时刻的几条按稳定写法比先后，
不按列表下标（换个切面、收起个进程，同一时刻的几条不会互换）。
"""
from __future__ import annotations


def edge_hidden(e: dict, hide: set[str]) -> bool:
    """这条边被开关藏起来没有：hide 里有 hot（「这次跑了」关了）就藏全部；有 dyn（「其中代码里看不出」关了）只藏全是看不出的"""
    dashed = e.get("n", 0) > 0 and e.get("only", 0) >= e["n"]
    return "hot" in hide or (dashed and "dyn" in hide)


def rank(L: dict, aliases: dict[str, str], fold: set[int] | None = None, hide: set[str] | None = None,
         lanes: set[str] | None = None) -> dict:
    """{"keys": {页面上的 key（e:列 id|a|b、l:下标）: 名次（从 0 数）}, "ids": [按名次的稳定写法], "n"}。
    fold：收起的进程；hide：藏起的边（hot / dyn）；lanes：只看的列 id（None 是全部）"""
    fold, hide = fold or set(), hide or set()
    lo, hi = (L.get("window") or [0, 0])[:2]
    items = []
    for ln in L["lanes"]:
        if ln["pid"] in fold or (lanes is not None and ln["id"] not in lanes):
            continue
        al = aliases.get(ln["id"], ln["id"])
        for e in ln.get("edges") or []:
            if e["a"] not in ln["nodes"] or e["b"] not in ln["nodes"] or edge_hidden(e, hide):
                continue
            if e.get("first") is not None and lo <= e["first"] <= hi:
                items.append((e["first"], e.get("last") or 0, f"e:{al}|{e['a']}|{e['b']}", f"e:{ln['id']}|{e['a']}|{e['b']}"))
    pid_of = {ln["id"]: ln["pid"] for ln in L["lanes"]}

    def col(lid: str) -> str:
        """这一列画在哪：自己一列；收起的进程、只看列时没选的列，每个进程合成一窄列"""
        pid = pid_of.get(lid)
        return f"fold:{pid}" if pid in fold or (lanes is not None and lid not in lanes) else lid
    for i, k in enumerate(L.get("links") or []):
        if k["kind"] != "handoff" or k.get("first") is None or not lo <= k["first"] <= hi:
            continue
        ca, cb = col(k["from"]["lane"]), col(k["to"]["lane"])
        if ca == cb and ca.startswith("fold:"):          # 两头在同一个收起的窄列里：页面上不画
            continue
        fa, ta = aliases.get(k["from"]["lane"], k["from"]["lane"]), aliases.get(k["to"]["lane"], k["to"]["lane"])
        stable = f"l:handoff|{k['via']}|{fa}|{ta}|{k['from'].get('node') or ''}|{k['to'].get('node') or ''}"
        items.append((k["first"], k.get("last") or 0, stable, f"l:{i}"))
    items.sort()
    return {"keys": {x[3]: r for r, x in enumerate(items)}, "ids": [x[2] for x in items], "n": len(items)}
