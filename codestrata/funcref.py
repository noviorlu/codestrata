"""命令行里写的函数 → trace 的键（steps 的 --with / --head、explain 也用；没录到的函数 resolve_symbol 退到 scan 的索引）。

写法：`仓库相对路径#限定名`（graph 的节点）、限定名（`OmniARScheduler.schedule`）、唯一的方法名或函数名（`schedule`）。
同一个函数在 run 里可能有几个键（录制之后挪了行）：按节点合在一起。对不上报 item_not_found，对上好几个报 ambiguous_item，
候选是节点（全路径写法）和这段时间里各调了几次。
"""
from __future__ import annotations

import re
from collections import Counter

from .errors import CodestrataError


def resolve(text: str, keys: list[str], label, calls: Counter | None = None) -> tuple[str, set[int]]:
    """(节点, 它的键下标)。label：键 → 节点（align.node_labeler）；calls：{键下标: 这段时间里调了几次}——同名的先挑这段时间里调过的"""
    text = (text or "").strip()
    if not text:
        raise CodestrataError("usage", "没给函数")
    nodes: dict[str, set[int]] = {}
    for i, k in enumerate(keys):
        if k == "?" or k.endswith(":0"):
            continue
        node = label(k)
        if node and _match(text, node):
            nodes.setdefault(node, set()).add(i)
    n = Counter({node: sum((calls or {}).get(i, 0) for i in ks) for node, ks in nodes.items()})
    if len(nodes) > 1 and calls is not None:
        ran = {node: ks for node, ks in nodes.items() if n[node]}
        if ran:
            nodes = ran
    if len(nodes) == 1:
        return next(iter(nodes.items()))
    if not nodes:
        t = re.sub(r"\.py$", "", text.split("#")[-1].rsplit("/", 1)[-1])     # 写的是文件路径时按文件名（不带 .py）找近的
        low = t.lower().rsplit(".", 1)[-1]
        near = sorted({lab for k in keys if k != "?" and (lab := label(k)) and low in lab.partition("#")[2].lower()})[:12]
        raise CodestrataError("item_not_found", f"没有叫 {text!r} 的函数（写全路径#限定名、限定名，或唯一的名字）", candidates=near)
    order = sorted(nodes, key=lambda x: -n[x])
    counts = "，".join(f"{x.partition('#')[2]} ×{n[x]}" for x in order[:5]) if calls is not None else ""
    raise CodestrataError("ambiguous_item", f"{text!r} 对上了 {len(nodes)} 个函数，写全路径#限定名"
                          + (f"（这段时间里：{counts}）" if counts else ""), candidates=order[:20])


def _match(text: str, node: str) -> bool:
    if "#" in text:
        return node == text
    q = node.partition("#")[2]
    return q == text or q.endswith("." + text)


def resolve_symbol(text: str, symbols: dict, kinds: tuple[str, ...] | None = None) -> str | None:
    """在 scan 的索引里找（没录到的也找得到）：全路径#限定名、限定名、唯一的短名 → 节点；kinds 只认这几种（class、func、method…）。
    对不上或对上好几个是 None"""
    text = (text or "").strip()
    if not text:
        return None
    ok = (lambda s: s.get("k") in kinds) if kinds else (lambda s: True)
    if "#" in text:
        s = symbols.get(text)
        return text if s and ok(s) else None
    hits = [k for k, s in symbols.items() if ok(s) and (s.get("n") == text or s.get("n", "").endswith("." + text))]
    return hits[0] if len(hits) == 1 else None
