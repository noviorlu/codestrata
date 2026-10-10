"""一列（一个进程里同名的一类线程）的主循环：认轮头、切轮、哪些轮在空转、忙段、一轮里时间花在哪。

只用通用的信号，不写死框架。判法（2026-10-09 在 MiniCPM、qwen、toy 上定的，见 docs/design/agent-cli.md「切段」）：
    轮头  在同一个父函数下面（线程根也算一个父函数；同一个函数的几次调用合在一起看），在这段时间里至少调了 MIN_CALLS 次、
          不是合成一行的连续调用（轮询的叶子）的被调方是候选。同一个父函数下按次数投票（差不到 VOTE 算同票），取票最多的
          次数，同票里第一次最早的是轮头。父函数之间取覆盖时间最长的，差不到 VOTE 的取外层的（深度小的）。
    轮    第 k 次轮头开始 → 第 k+1 次开始；最后一轮到最后一次轮头调用结束。轮号按整个 run 数。
    常规  在 ≥ MIN_SHARE 的轮里出现过的被调方（这一轮里任意深度的调用都算）。
    超长  比这一列所有轮的中位长 LONG 倍以上。
    空转  只有常规调用、没有交接、也不超长的轮。
    忙段  这段时间里的前景轮（不空转的），在中间空转超过「这段时间长度」的 GAP 处切开。
阈值都能在命令行上改（Params），输出里带上用的是哪一套（basis）。

输入是 seq.pid_rows 的行（span：[t0, dur, tid, depth, a, b, rep, n_susp, parent, (gpu)]）。只认带 parent 的 span
（2026-10-01 之后整理的）：老 run 由调用方拒绝。纯计算，不读文件。
"""
from __future__ import annotations

import bisect
import statistics
from collections import Counter
from dataclasses import asdict, dataclass

ALGO = "seg/1"


@dataclass
class Params:
    min_calls: int = 5          # 轮头至少调几次
    vote: float = 0.10          # 次数差不到这么多算同票；覆盖时间差不到这么多取外层的
    min_share: float = 0.2      # 在这么多比例的轮里出现算常规
    long: float = 5.0           # 超过中位几倍算超长
    gap: float = 0.25           # 前景轮之间的空转超过这段时间长度的多少就切开

    def basis(self) -> dict:
        return asdict(self)


def lane_rows(rows: list, tids: set) -> list[tuple[int, list]]:
    """一列（几条线程）的 span：[(下标, 行)]，按开始的先后；不含 GPU 的行（kernel）"""
    return [(i, r) for i, r in enumerate(rows) if r is not None and r[2] in tids and len(r) <= 9]


def find_loop(lr: list, lo: int, hi: int, p: Params | None = None, head: set[int] | None = None) -> dict | None:
    """这一列的主循环：{tid, head（被调方的键下标）, parent, depth, calls: [(t0, 下标, 行)]（整个 run 的每一次轮头调用）,
    n（这段时间里几次）, cover}。head 给了就只认这几个键（--head：同一个函数可能有几个键）。认不出是 None"""
    p = p or Params()
    rowb = {i: r[5] for i, r in lr}
    groups: dict = {}
    for i, r in lr:
        # 父亲按「哪个函数」认，不按哪一次调用：每个 token 一个生成器帧时，同一个函数的各次调用合在一起
        pk = (r[2], rowb[r[8]]) if r[8] >= 0 and r[8] in rowb else (r[2], None)
        groups.setdefault(pk, {}).setdefault(r[5], []).append((r[0], i, r))
    best = None
    for pk, kids in groups.items():
        cands = []
        for b, calls in kids.items():
            if head is not None and b not in head:
                continue
            w = [c for c in calls if lo <= c[0] < hi]
            if len(w) >= (1 if head is not None else p.min_calls) and all(c[2][6] == 1 for c in w):
                cands.append((b, len(w), w[0][0], calls, w))
        if not cands:
            continue
        votes = {c[1]: sum(1 for d in cands if (1 - p.vote) * c[1] <= d[1] <= (1 + p.vote) * c[1]) for c in cands}
        n = max(votes, key=lambda k: (votes[k], k))
        b, cnt, _, calls, w = min((c for c in cands if (1 - p.vote) * n <= c[1] <= (1 + p.vote) * n), key=lambda c: c[2])
        cand = {"tid": pk[0], "head": b, "parent": pk[1], "depth": w[0][2][3], "calls": calls, "n": cnt,
                "cover": w[-1][0] - w[0][0]}
        if best is None or cand["cover"] > best["cover"] * (1 + p.vote) or (
                cand["cover"] >= best["cover"] * (1 - p.vote) and (cand["depth"], -cnt) < (best["depth"], -best["n"])):
            best = cand
    return best


def cut_rounds(loop: dict, lr: list, out_t: list[int], in_t: list[int], p: Params | None = None) -> tuple[list[dict], set]:
    """切轮：[{k, t0_us, t1_us, dur_us, calls, out, in, extra: [键下标], long, spin, kids: Counter}]（轮号从 1 数，整个 run）
    和常规的被调方。out_t / in_t 是这一列交出 / 收到数据的时刻（按时刻归轮）"""
    p = p or Params()
    calls = loop["calls"]
    tid = loop["tid"]
    bounds = [(t0, calls[k + 1][0] if k + 1 < len(calls) else t0 + max(r[1], 0)) for k, (t0, _, r) in enumerate(calls)]
    starts = [a for a, _ in bounds]
    rs = [{"k": k + 1, "t0_us": a, "t1_us": b, "dur_us": b - a, "calls": 0, "out": 0, "in": 0, "kids": Counter()}
          for k, (a, b) in enumerate(bounds)]

    def at(t: int) -> int | None:
        k = bisect.bisect_right(starts, t) - 1
        return k if k >= 0 and (t < bounds[k][1] or k + 1 < len(bounds)) else None

    for _, r in lr:
        if r[2] != tid:
            continue
        k = at(r[0])
        if k is not None:
            rs[k]["calls"] += r[6]
            rs[k]["kids"][r[5]] += 1
    for ts, key in ((out_t, "out"), (in_t, "in")):
        for t in ts:
            k = at(t)
            if k is not None:
                rs[k][key] += 1
    share = Counter(b for x in rs for b in x["kids"])
    regular = {b for b, c in share.items() if c >= p.min_share * len(rs)}
    med = statistics.median(x["dur_us"] for x in rs) if rs else 0
    for x in rs:
        x["extra"] = sorted(b for b in x["kids"] if b not in regular)
        x["long"] = med > 0 and x["dur_us"] > p.long * med
        x["spin"] = not x["extra"] and not x["out"] and not x["in"] and not x["long"]
    return rs, regular


def busy_blocks(rs: list[dict], lo: int, hi: int, p: Params | None = None) -> list[tuple[int, int]]:
    """这段时间里的前景轮（不空转的），在中间空转超过这段时间长度的 gap 处切开：[(第一轮的下标, 最后一轮的下标)]"""
    p = p or Params()
    fg = [i for i, x in enumerate(rs) if not x["spin"] and lo <= x["t0_us"] < hi]
    if not fg:
        return []
    out, s, prev = [], fg[0], fg[0]
    for i in fg[1:]:
        if rs[i]["t0_us"] - rs[prev]["t1_us"] > p.gap * (hi - lo):
            out.append((s, prev))
            s = i
        prev = i
    out.append((s, prev))
    return out


def in_window(rs: list[dict], lo: int, hi: int) -> list[dict]:
    """开始在 [lo, hi) 里的轮"""
    return [x for x in rs if lo <= x["t0_us"] < hi]


def kind(n_threads: int, has_rows: bool, loop: dict | None, rs_win: list[dict]) -> str:
    """一列在这段时间里是什么样：loop（有主循环、有前景轮）/ poll（有主循环，这段里全在空转）/ threads（每条线程干一件：
    同名的线程很多，没有主循环）/ few（零星的调用）/ quiet（这段里没有调用）"""
    if loop is not None and rs_win:
        return "poll" if all(x["spin"] for x in rs_win) else "loop"
    if not has_rows:
        return "quiet"
    return "threads" if n_threads > 3 else "few"


def self_times(lr: list, tid: int, t0: int, t1: int) -> tuple[Counter, int, bool]:
    """[t0, t1) 里这条线程上每个被调方「自己的时间」（时长减去它直接调的仓库函数的时长）：(Counter{键下标: µs},
    这段时间里没有任何仓库调用在跑的时长, 有没有挂起过的 async 行（它们的时长含挂起，跳过了）)。没返回的行按到 t1 算"""
    own: Counter = Counter()
    rows = [(i, r) for i, r in lr if r[2] == tid and t0 <= r[0] < t1]
    idx = {i for i, _ in rows}

    def span(r) -> int:
        return (r[1] if r[1] >= 0 else t1 - r[0])

    child: Counter = Counter()
    for i, r in rows:
        if r[8] in idx:                          # 父亲在等它（async 的也算：挂起的那段父亲在 await）
            child[r[8]] += span(r)
    skipped = False
    covered = 0
    for i, r in rows:
        if r[7]:                                 # async：时长里含挂起的时间，算不出自己的时间
            skipped = True
            continue
        own[r[5]] += max(0, span(r) - child[i])
        if r[8] not in idx:                      # 这段时间里最外层的仓库调用
            covered += span(r)
    return own, max(0, (t1 - t0) - covered), skipped
