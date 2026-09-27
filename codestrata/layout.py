"""把包 + 架构高度变成可画的坐标。

纵轴是架构高度（scan.py 算出来的 `alt`）：把 [+1, -1] 切成若干泳道，
+1 那条在最上面。横轴用重心迭代排序减少连线交叉——Sugiyama 分层画图法里
那一步的简化版，对几十个节点足够，而且不引入任何依赖。

节点面积编码规模（文件数），所以「哪个包大」和「哪个包在底层」可以同时读出来。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Node:
    id: str
    label: str
    lane: int
    x: float = 0.0          # 0..1，框中心
    cy: float = 0.0         # 像素，纵向中心（由泳道几何算出）
    w: float = 0.0          # 像素
    h: float = 0.0
    alt: float = 0.0
    files: int = 0
    loc: int = 0
    classes: int = 0
    funcs: int = 0
    out: int = 0
    inn: int = 0
    order: float = 0.0      # 泳道内排序键
    meta: dict = field(default_factory=dict)


def _label(pkg: str, root_prefix: str) -> str:
    """去掉共同前缀，vllm_omni.engine → engine。"""
    if root_prefix and pkg.startswith(root_prefix + "."):
        return pkg[len(root_prefix) + 1:]
    return pkg


def build(index: dict, *, lanes: int | str = "auto", min_files: int = 1,
          top: int | None = None, width: float = 1180.0) -> dict:
    """返回 {"nodes": [...], "edges": [...], "lanes": n, "width": w, "height": h}"""
    pkgs = index["packages"]
    # 过滤：小包和 top-N。同时丢掉「既无符号又无连边」的空包——
    # 典型是只有一个空 __init__.py 的目录，画出来纯是噪声。
    items = [(p, v) for p, v in pkgs.items()
             if v["files"] >= min_files
             and not (v["out"] == 0 and v["in"] == 0
                      and v["classes"] == 0 and v["funcs"] == 0)]
    if top:
        items.sort(key=lambda kv: -kv[1]["files"])
        items = items[:top]
    keep = {p for p, _ in items}

    roots = index["repo"].get("roots") or []
    root_prefix = roots[0].split("/")[-1] if len(roots) == 1 else ""

    # 高度 → 泳道。+1 在 lane 0（最上），-1 在最后一条。
    def lane_at(alt: float, k: int) -> int:
        t = (1.0 - alt) / 2.0                     # +1→0, -1→1
        return max(0, min(k - 1, int(t * k)))

    if lanes == "auto":
        # 泳道太多会出现大片空带（6 个模块摊到 9 条泳道时有 6 条是空的），
        # 太少又把不同高度压在一起。所以取「占用率最高」的泳道数，
        # 占用率相同时偏向更多泳道（保留更多高度分辨率）。
        # 早先取的是「满足 ≥60% 的最大 k」，于是 6 个模块也会摊到 6 条、空 2 条。
        alts = [v["alt"] for _, v in items]
        lanes = max(range(3, 10),
                    key=lambda k: (len({lane_at(a, k) for a in alts}) / k, k))
    lanes = int(lanes)

    def lane_of(alt: float) -> int:
        return lane_at(alt, lanes)

    nodes: dict[str, Node] = {}
    for p, v in items:
        nodes[p] = Node(
            id=p, label=_label(p, root_prefix), lane=lane_of(v["alt"]),
            alt=v["alt"], files=v["files"], loc=v["loc"],
            classes=v["classes"], funcs=v["funcs"], out=v["out"], inn=v["in"],
        )

    edges = [(a, b, w) for a, b, w in index["edges"] if a in keep and b in keep]

    # 节点宽度：标签长度为底，文件数给一点加成（面积编码规模）
    for n in nodes.values():
        base = max(len(n.label) * 7.1 + 24, 78)
        bonus = min(56.0, 10.0 * math.log1p(n.files))
        n.w = base + bonus
        n.h = 30.0 + min(14.0, 3.2 * math.log1p(n.files))

    # ---- 重心迭代排序：让有连边的节点在横向靠近 ----
    by_lane: dict[int, list[Node]] = {}
    for n in nodes.values():
        by_lane.setdefault(n.lane, []).append(n)
    for lane in by_lane:
        by_lane[lane].sort(key=lambda n: -n.files)      # 初始序：大包在中间偏左
        for i, n in enumerate(by_lane[lane]):
            n.order = float(i)

    adj: dict[str, list[tuple[str, int]]] = {}
    for a, b, w in edges:
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))

    for _ in range(12):
        for lane, group in by_lane.items():
            if len(group) < 2:
                continue
            for n in group:
                num = den = 0.0
                for m_id, w in adj.get(n.id, ()):
                    m = nodes.get(m_id)
                    if m is None or m.lane == lane:
                        continue
                    num += m.order * w
                    den += w
                if den:
                    n.order = num / den
            group.sort(key=lambda n: n.order)
            for i, n in enumerate(group):
                n.order = float(i)

    # ---- 落到像素：每条泳道内按顺序等分，宽的节点占更多份 ----
    MARGIN = 74.0
    usable = width - MARGIN * 2
    for lane, group in by_lane.items():
        group.sort(key=lambda n: n.order)
        total = sum(n.w for n in group) + 26.0 * max(0, len(group) - 1)
        if total <= usable:
            x = MARGIN + (usable - total) / 2.0
            for n in group:
                n.x = (x + n.w / 2.0) / width
                x += n.w + 26.0
        else:
            # 挤不下：宽度和间距按同一个比例缩，缩完正好填满 usable。
            # （早先版本只缩宽度、位置仍按均分步长推进，比步长宽的节点会压到邻居。）
            scale = usable / total
            gap = 26.0 * scale
            x = MARGIN
            for n in group:
                n.w *= scale
                n.x = (x + n.w / 2.0) / width
                x += n.w + gap

    # 泳道几何。空泳道压成细条并标出它跳过的高度区间——既不占画布，
    # 又保留「这里有一段高度差」这个信息（把空泳道直接删掉会让纵轴说谎）。
    FULL_H, EMPTY_H, TOP = 118.0, 34.0, 30.0
    occupied = {n.lane for n in nodes.values()}
    rows = []
    y = TOP
    for i in range(lanes):
        hi = 1.0 - 2.0 * i / lanes
        lo = 1.0 - 2.0 * (i + 1) / lanes
        h = FULL_H if i in occupied else EMPTY_H
        rows.append({"i": i, "y": y, "h": h, "empty": i not in occupied,
                     "hi": round(hi, 2), "lo": round(lo, 2), "name": ""})
        y += h
    # 标签：入口 / 叶子给最上、最下**有内容**的泳道；中间只给最接近 0 的那一条。
    # （早先用 abs(mid) < 0.18 判断，lanes=6 时会有两条同时命中，图上出现两个「中间」。）
    occ = sorted(occupied)
    if occ:
        rows[occ[0]]["name"] = "入口"
        if len(occ) > 1:
            rows[occ[-1]]["name"] = "叶子"
        if len(occ) > 2:
            mid = min(occ[1:-1], key=lambda i: abs((rows[i]["hi"] + rows[i]["lo"]) / 2))
            rows[mid]["name"] = "中间"
    height = y + 26.0

    for n in nodes.values():
        r = rows[n.lane]
        n.cy = r["y"] + r["h"] / 2.0

    return {
        "width": width, "height": height, "lanes": lanes,
        "lane_rows": rows, "top": TOP,
        "nodes": [vars(n) for n in sorted(nodes.values(), key=lambda n: (n.lane, n.order))],
        "edges": [[a, b, w] for a, b, w in edges],
        "root_prefix": root_prefix,
    }

