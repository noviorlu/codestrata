"""把包 + 架构高度变成可画的坐标。

纵轴是架构高度（scan.py 算出来的 `alt`）：把 [+1, -1] 切成若干泳道，
+1 那条在最上面。横轴用重心迭代排序减少连线交叉——Sugiyama 分层画图法里
那一步的简化版，对几十个节点足够，而且不引入任何依赖。

节点面积编码规模（文件数），所以「哪个包大」和「哪个包在底层」可以同时读出来。

展开着的目录画成一个框，把它底下的节点框在一起（index["frames"] 和每个节点的 "frame"
给出嵌套关系，由 payload 按切面算好）。框只能在横向上成立：每个展开的目录占一段专属的列，
框从它最高的子模块画到最低的子模块——纵轴的含义不变。
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
    row: int = 0            # 泳道放不下时折行：第几行
    frame: str | None = None  # 直接套着它的框（展开着的目录）；None 是不在任何框里
    meta: dict = field(default_factory=dict)


def _text_w(s: str) -> float:
    """等宽字体下一段文字大约多宽（像素）。中文字是西文的两倍宽——早先一律按西文算，
    「本层文件」这种名字的框和框头都装不下。"""
    return sum(12.4 if ord(c) >= 0x2E80 else 7.25 for c in s)


def _label(pkg: str, root_prefix: str) -> str:
    """去掉共同前缀，vllm_omni.engine → engine。展开出来的深层包只留最后两段
    （model_executor.models.minicpmo_4_5 → models.minicpmo_4_5），否则框宽得装不下。"""
    if root_prefix and pkg.startswith(root_prefix + "."):
        pkg = pkg[len(root_prefix) + 1:]
    parts = pkg.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else pkg


def _display(pkg: str, kind: str | None, root_prefix: str) -> str:
    """图上的名字：收起的目录带 /，「本层文件」节点写成 目录/ 本层，单个文件原样。"""
    if kind == "residual":
        return _label(pkg[:-2], root_prefix) + "/ 本层"
    return _label(pkg, root_prefix) + ("/" if kind == "dir" else "")


def build(index: dict, *, lanes: int | str = "auto", min_files: int = 1,
          top: int | None = None, width: float = 1180.0,
          only: set[str] | None = None) -> dict:
    """返回 {"nodes": [...], "edges": [...], "frames": [...], "lanes": n, "width": w, "height": h}

    only：只给这些包排版（hot 视图用）。泳道数应当由调用方传入总图的值，
    这样两张图的纵坐标含义一致，只是横向更紧凑。
    """
    pkgs = index["packages"]
    # 过滤：小包和 top-N。同时丢掉「既无符号又无连边」的空包——
    # 典型是只有一个空 __init__.py 的目录，画出来纯是噪声。
    items = [(p, v) for p, v in pkgs.items()
             if v["files"] >= min_files
             and not (v["out"] == 0 and v["in"] == 0
                      and v["classes"] == 0 and v["funcs"] == 0)]
    if only is not None:
        items = [(p, v) for p, v in items if p in only]
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

    # 框：展开着的目录把它底下的节点框在一起。fparent 是框的嵌套，home 是每个节点直接所在的框
    fr_in = index.get("frames") or {}
    fparent = {f: (v.get("parent") if v.get("parent") in fr_in else None) for f, v in fr_in.items()}
    kinds = {p: v.get("kind") for p, v in pkgs.items()}
    kinds.update({f: v.get("kind") for f, v in fr_in.items()})

    def name_in(p: str, f: str | None) -> str:
        """框里的节点只写相对于框的名字：框头已经写了 diffusion/，
        里面的 diffusion.executor/ 写成 executor/，框就窄得多。"""
        kind = kinds.get(p)
        if f is None:
            return _display(p, kind, root_prefix)
        base = f[:-2] if f.endswith(".*") else f
        own = p[:-2] if kind == "residual" else p
        if own == base:
            return "本层文件"
        if not own.startswith(base + "."):
            return _display(p, kind, root_prefix)
        return own[len(base) + 1:] + ("/ 本层" if kind == "residual" else "/" if kind == "dir" else "")

    nodes: dict[str, Node] = {}
    for p, v in items:
        f = v.get("frame") if v.get("frame") in fr_in else None
        nodes[p] = Node(
            id=p, label=name_in(p, f), lane=lane_of(v["alt"]), frame=f,
            alt=v["alt"], files=v["files"], loc=v["loc"],
            classes=v["classes"], funcs=v["funcs"], out=v["out"], inn=v["in"],
        )

    edges = [(a, b, w) for a, b, w in index["edges"] if a in keep and b in keep]

    # 节点宽度：标签长度为底，文件数给一点加成（面积编码规模）
    for n in nodes.values():
        base = max(_text_w(n.label) + 24, 78)
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

    # ---- 框：展开着的目录把它底下的节点框在一起 ----
    # 纵轴仍然是架构高度，所以一个目录的子模块会分散在好几条泳道里。框不能在纵向上
    # 把它们挪到一起（那样纵轴就说谎了），只能在横向上给每个展开的目录一段列：
    # 图按目录树切成嵌套的列，框画在这段列上、从它最高的子模块到最低的子模块。
    home = {n.id: n.frame for n in nodes.values()}
    used: set[str] = set()
    for f in home.values():
        while f and f not in used:
            used.add(f)
            f = fparent[f]
    kids: dict = {}                       # 区域（None 是整张图）→ 直接包含的子框
    for f in sorted(used):
        kids.setdefault(fparent[f], []).append(f)
    leaves: dict = {}                     # 区域 → 直接放在里面的节点
    below: dict = {}                      # 框 → 它底下所有的节点
    span: dict[str, tuple[int, int]] = {}  # 框 → 泳道跨度
    for n in nodes.values():
        leaves.setdefault(home[n.id], []).append(n)
        f = home[n.id]
        while f:
            below.setdefault(f, []).append(n)
            lo, hi = span.get(f, (n.lane, n.lane))
            span[f] = (min(lo, n.lane), max(hi, n.lane))
            f = fparent[f]
    flabel = {f: name_in(f, fparent[f]) for f in used}

    MARGIN, GAP = 74.0, 26.0
    FPAD, PGAP = 12.0, 18.0     # 框内左右留白；同一层相邻两块之间的空隙
    ROW_H = 70.0                # 泳道里多一行多这么高

    def wrap(group, room):
        """一条泳道里的一组节点（已按顺序）在 room 宽里怎么折行。不压窄框：框永远装得下标签。"""
        rows: list[list[Node]] = [[]]
        used_w = 0.0
        for n in group:
            w_need = n.w + (GAP if rows[-1] else 0.0)
            if rows[-1] and used_w + w_need > room:
                rows.append([])
                used_w, w_need = 0.0, n.w
            rows[-1].append(n)
            used_w += w_need
        if len(rows) > 1:
            # 贪心会让最后一行很短；按行数均分再排一次，放得下就用均分的
            per = -(-len(group) // len(rows))
            even = [group[i:i + per] for i in range(0, len(group), per)]
            if all(sum(n.w for n in r) + GAP * (len(r) - 1) <= room for r in even):
                rows = even
        return rows

    lane_groups: dict = {}              # 一组节点按泳道分好、排好序（缓存：规划时要反复算）

    def by_lane_of(key, ns):
        if key not in lane_groups:
            g: dict[int, list[Node]] = {}
            for n in sorted(ns, key=lambda n: n.order):
                g.setdefault(n.lane, []).append(n)
            lane_groups[key] = g
        return lane_groups[key]

    def leaf_need(ns):
        """一组节点不折行要多宽、最窄能压到多宽（一行只放一个）。"""
        by: dict[int, list[float]] = {}
        for n in ns:
            by.setdefault(n.lane, []).append(n.w)
        nat = max((sum(ws) + GAP * (len(ws) - 1) for ws in by.values()), default=0.0)
        return nat, max((n.w for n in ns), default=0.0)

    # 一个区域（整张图或一个框）里：子框各占一列（「轨道」），直接放在区域里的散节点
    # 每条泳道各自往右排，用掉那条泳道里没被框占住的宽度。框只挡它跨过的泳道——只跨一两条
    # 泳道的小框不该让别的泳道也空出一整列。所以跨的泳道多的框放左边、小框放右边，
    # 散节点在每条泳道里从「最后一个跨过这条泳道的框」的右边开始排。
    # 泳道跨度不重叠的框还可以上下叠在同一条轨道里，展开很多个小目录时能省下大量宽度。
    # 顺序只取决于框本身（跨度、名字），展开一个无关的目录不会让别的框换位置。
    track_cache: dict = {}

    def tracks_of(a):
        """[(框列表, 这条轨道跨过的泳道集合)]"""
        if a not in track_cache:
            fs = sorted(kids.get(a, []), key=lambda c: (span[c][0] - span[c][1], c))
            tracks: list[tuple[list, set]] = []
            for c in fs:
                lanes_c = set(range(span[c][0], span[c][1] + 1))
                for t in tracks:
                    if not (t[1] & lanes_c):
                        t[0].append(c)
                        t[1].update(lanes_c)
                        break
                else:
                    tracks.append(([c], set(lanes_c)))
            track_cache[a] = tracks
        return track_cache[a]

    def lane_ends(tracks, ws):
        """每条泳道里，最后一个跨过它的轨道右边到哪（相对区域内侧左边）；没有轨道跨过就是 0。"""
        ends, x = {}, 0.0
        for (fs, lanes_t), w in zip(tracks, ws):
            x += w
            for lane in lanes_t:
                ends[lane] = x
            x += PGAP
        return ends

    def leaf_room(room, ends, lane):
        e = ends.get(lane, 0.0)
        return room - e - (PGAP if e else 0.0)

    need: dict = {}

    def head_text(f):
        """框头上的数：这张图里框着几个；hot 视图里只画了一部分，写成「画出来的 / 一共」。
        （早先写「19 个」，小字号下「个」看着像个向上的箭头）"""
        n, total = len(below[f]), fr_in[f].get("n") or len(below[f])
        return f"· {n}" if n == total else f"· {n}/{total}"

    def track_need(t):
        return max(need[c][0] for c in t[0]), max(need[c][1] for c in t[0])

    def measure(a):
        for c in kids.get(a, []):
            measure(c)
        tracks = tracks_of(a)
        groups = by_lane_of(a, leaves.get(a, []))
        res = []
        for sel in (0, 1):                  # 0：不折行要多宽；1：最窄能压到多宽
            ws = [track_need(t)[sel] for t in tracks]
            ends = lane_ends(tracks, ws)
            w_all = sum(ws) + PGAP * max(0, len(ws) - 1)
            for lane, g in groups.items():
                lw = (sum(n.w for n in g) + GAP * (len(g) - 1)) if sel == 0 else max(n.w for n in g)
                e = ends.get(lane, 0.0)
                w_all = max(w_all, e + (PGAP if e else 0.0) + lw)
            res.append(w_all)
        nat, mn = res
        if a is not None:
            # 框头：收起按钮 + 名字 + 节点数，框至少要装得下它
            head = 28 + _text_w(flabel[a]) + 8 + _text_w(head_text(a)) * 11 / 12 + 12
            nat, mn = max(nat + 2 * FPAD, head), max(mn + 2 * FPAD, head)
        need[a] = (nat, mn)

    measure(None)

    def distribute(total, parts):
        """起点：按「不折行要多宽」的比例分，每块不低于它的下限。"""
        nat = sum(p[0] for p in parts)
        if nat <= total:
            return [p[0] + (total - nat) * (p[0] / nat if nat else 1.0 / len(parts)) for p in parts]
        if sum(p[1] for p in parts) >= total:
            return [p[1] for p in parts]
        lo_s, hi_s = 0.0, 1.0
        for _ in range(40):
            s_ = (lo_s + hi_s) / 2
            if sum(max(p[1], p[0] * s_) for p in parts) > total:
                hi_s = s_
            else:
                lo_s = s_
        ws = [max(p[1], p[0] * lo_s) for p in parts]
        free = [i for i, p in enumerate(parts) if p[0] * lo_s > p[1]]
        rest = total - sum(ws)                    # 二分剩下的零头补给没压到下限的块
        for i in free:
            ws[i] += rest / len(free)
        return ws

    plans: dict = {}
    INF = (float("inf"), float("inf"))

    def plan(a, width_a):
        """区域 a 给 width_a 宽（含框的左右留白）时，每条泳道要折几行、每条轨道分多宽。

        分法以「总行数最少」为目标：泳道的高度由这条泳道里最挤的那一块决定，按比例分常常
        让一块只能一行放一个、旁边一块却空着一大半。从按比例分出发，反复把一段宽度从一条
        轨道挪给另一条（有散节点时也可以挪给 / 挪自散节点），只要行数变少就接受。"""
        key = (a, int(width_a // 4))
        if key in plans:
            return plans[key]
        pad = FPAD if a is not None else 0.0
        tracks = tracks_of(a)
        groups = by_lane_of(a, leaves.get(a, []))
        room = width_a - 2 * pad
        gaps = PGAP * max(0, len(tracks) - 1)
        needs = [track_need(t) for t in tracks]
        mins = [nd[1] for nd in needs]

        def rows_of(ws):
            out: dict[int, int] = {}
            own = 0                       # 各块自己的行数之和：总行数打平时用来分胜负
            for (fs, _), w in zip(tracks, ws):
                for c in fs:
                    r = plan(c, w)[0]
                    own += sum(r.values())
                    for lane, x in r.items():
                        out[lane] = max(out.get(lane, 0), x)
            ends = lane_ends(tracks, ws)
            for lane, g in groups.items():
                lr = leaf_room(room, ends, lane)
                if lr < max(n.w for n in g) - 0.5:
                    return None           # 这条泳道里散节点放不下了
                x = len(wrap(g, lr))
                own += x
                out[lane] = max(out.get(lane, 0), x)
            return out, own

        def cost(ws):
            # 先比总行数（图的高度）；打平时比各块自己的行数之和。两块在同一条泳道里都要两行时，
            # 单独加宽哪一块总行数都不变——只看总行数，搜索就停在这里；有了第二个指标，
            # 先把其中一块压成一行，下一步再压另一块，总行数才降得下来
            r = rows_of(ws)
            return INF if r is None else (sum(r[0].values()), r[1])

        if not tracks:
            ws = []
        elif groups:
            lv = leaf_need(leaves[a])
            ws = distribute(room - gaps - PGAP, needs + [lv])[:-1]
            if cost(ws) == INF:
                ws = list(mins)
        else:
            ws = distribute(room - gaps, needs)
        best = cost(ws)
        step = room / 4
        while tracks and step >= 8:
            improved = True
            while improved:
                improved = False
                moves = [(i, j) for i in range(len(ws)) for j in range(len(ws)) if i != j]
                if groups:                # 和散节点之间挪：-1 表示散节点那一侧
                    moves += [(i, -1) for i in range(len(ws))] + [(-1, j) for j in range(len(ws))]
                for i, j in moves:
                    trial = list(ws)
                    if i >= 0:
                        trial[i] += step
                    if j >= 0:
                        if trial[j] - step < mins[j]:
                            continue
                        trial[j] -= step
                    if sum(trial) + gaps > room + 0.01:
                        continue
                    c = cost(trial)
                    if c < best:
                        ws, best, improved = trial, c, True
            step /= 2
        r = rows_of(ws)
        plans[key] = ((r[0] if r else {}), ws)
        return plans[key]

    # 画布宽度：width 是页面上图框的宽度（serve 按浏览器窗口传进来，默认 1180）。展开多了，
    # 窄画布只能把每块压成一列、图拉得很长；宽一点能省下不少高度。在几档宽度里挑
    # 「高度 + 多出来的宽度」最小的——宽出来的部分要在图框里横向滚动，所以宽度比高度更贵一点。
    # 展开得很多、最窄也超过这几档时，再试比最窄宽 15% / 35% 的两档：每块都压在下限上时
    # 一行只放得下一个节点，稍微放宽一点常常能省下好几行
    WIDTH_COST = 1.5
    floor = need[None][1] + MARGIN * 2
    base = max(width, floor)
    steps = [width * k for k in (1.19, 1.39, 1.61, 1.86)]
    cands = sorted({base} | {w for w in steps + [base * 1.15, base * 1.35]
                             if w > base and (w <= steps[-1] or base > steps[-1])})
    best_w, best_cost = cands[0], None
    for w in cands:
        rows_w = plan(None, w - MARGIN * 2)[0]
        cost = ROW_H * sum(rows_w.values()) + WIDTH_COST * (w - width)
        if best_cost is None or cost < best_cost - 1e-6:
            best_w, best_cost = w, cost
    width = best_w
    usable = width - MARGIN * 2

    n_rows: dict[int, int] = {}

    def place_lane(lane, group, x0, x1):
        room = x1 - x0
        rows = wrap(group, room)
        for ri, row in enumerate(rows):
            total = sum(n.w for n in row) + GAP * max(0, len(row) - 1)
            x = x0 + (room - total) / 2.0
            for n in row:
                n.row = ri
                n.x = x + n.w / 2.0            # 先存像素，最后再换成比例
                x += n.w + GAP
        n_rows[lane] = max(n_rows.get(lane, 1), len(rows))

    fx: dict[str, tuple[float, float]] = {}

    def place(a, x0, x1):
        pad = FPAD if a is not None else 0.0
        if a is not None:
            fx[a] = (x0, x1)
        tracks = tracks_of(a)
        groups = by_lane_of(a, leaves.get(a, []))
        ws = list(plan(a, x1 - x0)[1])
        # 规划按 4px 一档缓存，拿到的宽度和这里实际的宽度可能差几个像素：按比例校正，
        # 否则里面的块会伸进框的留白。只有框、没有散节点时，框正好铺满
        room = (x1 - x0) - 2 * pad
        used = sum(ws) + PGAP * max(0, len(ws) - 1)
        if ws and (used > room or not groups):
            k_ = (room - PGAP * (len(ws) - 1)) / sum(ws)
            ws = [w * k_ for w in ws]
        x = x0 + pad
        for (fs, _), w in zip(tracks, ws):
            for c in fs:
                place(c, x, x + w)
            x += w + PGAP
        ends = lane_ends(tracks, ws)
        for lane, g in groups.items():
            e = ends.get(lane, 0.0)
            place_lane(lane, g, x0 + pad + e + (PGAP if e else 0.0), x1 - pad)

    place(None, MARGIN, MARGIN + usable)
    for n in nodes.values():
        n.x = n.x / width

    # 框头叠放：几个嵌套的框从同一条泳道开始时，名字一个压一个往下排；
    # 框底同理，里层的框底在外层的上面。
    def depth(f):
        d, p = 0, fparent[f]
        while p:
            d, p = d + 1, fparent[p]
        return d

    sdepth, edepth = {}, {}
    head_stack: dict[int, int] = {}
    foot_stack: dict[int, int] = {}
    for f in used:
        # 外面有几层框和它从同一条泳道开始 / 在同一条泳道结束：框头往下错开这么多层，
        # 框底往上收这么多层，里层的框才整个落在外层里面
        d, e, p = 0, 0, fparent[f]
        while p:
            d += span[p][0] == span[f][0]
            e += span[p][1] == span[f][1]
            p = fparent[p]
        sdepth[f], edepth[f] = d, e
        head_stack[span[f][0]] = max(head_stack.get(span[f][0], 0), d + 1)
        foot_stack[span[f][1]] = max(foot_stack.get(span[f][1], 0), e + 1)

    # 泳道几何。空泳道压成细条并标出它跳过的高度区间——既不占画布，
    # 又保留「这里有一段高度差」这个信息（把空泳道直接删掉会让纵轴说谎）。
    FULL_H, EMPTY_H, TOP = 118.0, 34.0, 30.0
    HEAD_H, FOOT_H = 22.0, 8.0
    occupied = {n.lane for n in nodes.values()}
    rows = []
    y = TOP
    for i in range(lanes):
        hi = 1.0 - 2.0 * i / lanes
        lo = 1.0 - 2.0 * (i + 1) / lanes
        # 节点上方有 37px 空白，放得下一层框头；多一层框头就多留一层的高度。
        # 节点下方的空白放得下四层框底（每层 8px），再多才加高
        extra_top = HEAD_H * max(0, head_stack.get(i, 0) - 1)
        h = (FULL_H + ROW_H * (n_rows.get(i, 1) - 1) + extra_top
             + FOOT_H * max(0, foot_stack.get(i, 0) - 4)) if i in occupied else EMPTY_H
        rows.append({"i": i, "y": y, "h": h, "empty": i not in occupied, "pad": extra_top,
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
        n.cy = r["y"] + r["pad"] + FULL_H / 2.0 + n.row * ROW_H

    frames = []
    for f in sorted(used, key=lambda f: (depth(f), f)):       # 外层先画，里层盖在上面
        x0, x1 = fx[f]
        lo, hi = span[f]
        fy0 = rows[lo]["y"] + 5 + HEAD_H * sdepth[f]
        fy1 = rows[hi]["y"] + rows[hi]["h"] - 5 - FOOT_H * edepth[f]
        frames.append({"id": f, "label": flabel[f], "lw": round(_text_w(flabel[f]) * 11.5 / 12, 1),
                       "kind": fr_in[f].get("kind"), "count": head_text(f),
                       "parent": fparent[f], "depth": depth(f), "n": len(below[f]),
                       "total": fr_in[f].get("n") or len(below[f]),
                       "x": x0 + 3, "y": fy0, "w": x1 - x0 - 6, "h": fy1 - fy0})

    return {
        "width": width, "height": height, "lanes": lanes,
        "lane_rows": rows, "top": TOP, "frames": frames,
        "nodes": [vars(n) for n in sorted(nodes.values(), key=lambda n: (n.lane, n.order))],
        "edges": [[a, b, w] for a, b, w in edges],
        "root_prefix": root_prefix,
    }

