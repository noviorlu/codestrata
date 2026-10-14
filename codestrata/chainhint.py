"""链停下时给 agent 的 --link 候选（links --follow；走法在 chain.py）。只是候选：接不接由 agent 读过代码后定（用户 10-10 定的），
拼好的那条也只写在文字和 JSON 里，不当成命令推给用户。

A 边：这一列这一份里跑的、一份一次的函数（次数和进来的份数一样、第 k 次就在这一份里），挑这一份里结束得最晚的那个（离交出去最近）。
    挑不出来（没有一份一次的）就不给 B 边：配不了。
B 边：所有别的列里和 A 函数次数一样、每一次都不早于同一次 A 的函数（第 k 次配第 k 次配得上的），不限这一份之后多久（积压时对面
    可能隔一秒多才来取）。排序：
    1. 不在链上走过的列在前（已经经过的列多半是上游）；
    2. 交替的在前：每一次 B 都在下一次 A 之前（一份处理完才来下一份）；
    3. A 到 B 的间隔越稳越前（变异系数）；
    4. 间隔越短越前。
    同一列里每一次都离得不到 SAME_US 的几个函数落点一样，只列第一个、写还有几个。最多 CAND_LANES 列、每列 CAND_FNS 处。
"""
from __future__ import annotations

from statistics import mean, pstdev

from . import chain as _chain

CAND_LANES = 3
CAND_FNS = 3
SAME_US = 1000


def _pick(W, pos) -> tuple[list[dict], "_chain.Fn | None"]:
    """A 边：([{fn, n, per_item}], 挑出来的函数)"""
    end = min(pos.until, W.hi)
    nodes = [nd for nd, _ in W.fns_after(pos.lane, pos.t, end, 4 * CAND_FNS)]
    if pos.fn:                                       # 收到的那一头的函数排最前
        nodes = [pos.fn] + [x for x in nodes if x != pos.fn]
    rows, pick = [], None
    for nd in nodes:
        cs = W.calls(pos.lane, W.keys_of(pos.lane, nd))
        if not cs:
            continue
        c = cs[pos.k - 1] if pos.n and len(cs) == pos.n and 0 < pos.k <= len(cs) else None
        per = c is not None and (c[0] <= pos.t <= c[1] or pos.t <= c[0] < end)
        rows.append({"fn": nd, "n": len(cs), "per_item": per})
        if per and (pick is None or c[1] > pick[1]):
            pick = (_chain.Fn(pos.lane, nd, cs), c[1])
    X = pick[0] if pick else None
    top = [x for x in rows if X and x["fn"] == X.node] + [x for x in rows if x["fn"] == pos.fn and not (X and X.node == pos.fn)]
    rest = [x for x in rows if x not in top]
    return top + [x for x in rest if x["per_item"]][:2 * CAND_FNS - len(top)] + [x for x in rest if not x["per_item"]][:2], X


def hints(W, pos, on_chain: set[str]) -> dict:
    """停下时的候选：{a: {lane, fns, pick, n_in}, b: [{lane, fns: [{fn, n, alternate, cv, gap_us, same}]}], link}"""
    a_rows, X = _pick(W, pos)
    out = {"a": {"lane": W.alias(pos.lane), "fns": a_rows, "pick": X.node if X else None, "n_in": pos.n}, "b": [], "link": None}
    if X is None:
        return out
    xs = X.calls
    by_lane: dict[str, list] = {}
    for lid in W.A["lanes"]:
        if lid == pos.lane:
            continue
        for nd, ks in W.nodes_on(lid).items():
            if sum(len(W.by_key(lid)[b]) for b in ks) != len(xs):
                continue
            ys = W.calls(lid, ks)
            if _chain.misfit(xs, ys) is not None:
                continue
            gaps = [y[0] - x[0] for x, y in zip(xs, ys)]
            m = mean(gaps)
            by_lane.setdefault(lid, []).append({"fn": nd, "n": len(ys), "ys": ys, "gap_us": round(m),
                                                "cv": round(pstdev(gaps) / m, 3) if m > 0 else 0.0,
                                                "alternate": all(y[0] < xs[i + 1][0] for i, y in enumerate(ys[:-1]))})
    rank = lambda c: (not c["alternate"], c["cv"], c["gap_us"])         # noqa: E731
    lanes = []
    for lid, cs in by_lane.items():
        cs.sort(key=rank)
        reps: list[dict] = []
        for c in cs:                                 # 同一处：每一次都离得不到 SAME_US
            hit = next((r for r in reps if all(abs(a[0] - b[0]) < SAME_US for a, b in zip(r["ys"], c["ys"]))), None)
            if hit is None:
                reps.append({**c, "same": []})
            else:
                hit["same"].append(c["fn"])
        lanes.append((lid in on_chain, rank(reps[0]), lid, reps[:CAND_FNS]))
    lanes.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, lid, reps in lanes[:CAND_LANES]:
        out["b"].append({"lane": W.alias(lid), "on_chain": lid in on_chain,
                         "fns": [{k: v for k, v in r.items() if k != "ys"} for r in reps]})
    if lanes:
        lid, best = lanes[0][2], lanes[0][3][0]
        out["link"] = f"{W.alias(pos.lane)}:{W.fn_text(pos.lane, X.node)} => {W.alias(lid)}:{W.fn_text(lid, best['fn'])}"
    return out
