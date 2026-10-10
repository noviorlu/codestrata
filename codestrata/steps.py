"""一列（一个进程里同名的一类线程）的主循环：认轮头、切轮、哪些轮只做常规的事、忙段、一轮里时间花在哪。

只用通用的信号，不写死框架。判法（seg/2，2026-10-10 按 critic 在几种程序形状上造的假 run 改过，见 docs/design/agent-cli.md「切段」）：
    轮头  在「REF 所在的那个阶段」里认（不随 REF 的范围变；轮号按整个 run 数，REF 只决定列出哪几轮）。
          在同一个父函数下面（线程根也算一个父函数；同一个函数的几次调用合在一起看）：这段时间里至少调了 min_calls 次、
          不是合成一行的连续调用的被调方是候选。先去掉次数是别的候选整数倍的（一轮调两次的 has_requests），再按「同票数 × 次数」
          挑次数（同票：差不到 vote），这个次数里第一次最早的是轮头——干活的函数多几个也压不过每轮都调的调度。
          父函数每次调用里平均调轮头两次以上、父函数的调用又盖不住这段时间一半的，是一次调用里面的内层循环
          （worker 处理一个请求时调 20 次 model），不当主循环。
          父函数之间取覆盖时间最长的，差不到 vote 的取外层的（深度小的）。
    轮    第 k 次轮头开始 → 第 k+1 次开始；最后一轮到最后一次轮头调用结束。一个调用算在哪一轮：按它在轮头的父函数下面的那个祖先
          开始的时刻（不按它自己的时刻：同一条线程上别的 asyncio task 不混进来）；交接按它所在的 span 归轮。
    常规  这一列自己的「便宜的那几类轮」（按这一轮调到的函数分类，占得够多的类里，在仓库函数里的时间的中位不超过最少那类 cheap 倍的）
          调到的函数合起来。不和 run 里别处空闲了多久挂钩：忙的轮再多也不会把干活的函数算成常规。
          只有一类轮时它就是常规（只靠交接和超长分前景：每轮都在出 token 的 stage 靠交接，没有交接的单进程程序见 segments 的 alone）。
    超长  墙上时长比便宜的那几类轮的中位长 long 倍以上。
    空转  只调常规的函数、没有交接、也不超长的轮（整个 run 一次交接都没录到时，叫「常规轮」：分不清是空等还是每轮干一样的活）。
    忙段  一个进程里几列的前景轮（不空转的）合在一起按时刻排，在中间空转超过「REF 所在的阶段的长度」的 gap 处切开（segments 一块一段）。
阈值都能在命令行上改（Params），输出里带上用的是哪一套（basis）。

输入是 seq.pid_rows 的行（span：[t0, dur, tid, depth, a, b, rep, n_susp, parent, (gpu)]）。只认带 parent 的 span
（2026-10-01 之后整理的）：老 run 由调用方拒绝。纯计算，不读文件。
"""
from __future__ import annotations

import bisect
import statistics
from collections import Counter
from dataclasses import asdict, dataclass

ALGO = "seg/2"


@dataclass
class Params:
    min_calls: int = 5          # 轮头至少调几次
    vote: float = 0.10          # 次数差不到这么多算同票；覆盖时间差不到这么多取外层的
    class_share: float = 0.05   # 一类轮至少占这么多才算一类（便宜的那几类从这些里挑）
    cheap: float = 2.0          # 中位时长不超过最短那类的这么多倍的，都算便宜的类
    long: float = 5.0           # 超过便宜的那几类轮的中位几倍算超长
    gap: float = 0.25           # 前景轮之间的空转超过这段时间长度的多少就切开

    def basis(self) -> dict:
        return asdict(self)


def lane_rows(rows: list, tids: set) -> list[tuple[int, list]]:
    """一列（几条线程）的 span：[(下标, 行)]，按开始的先后；不含 GPU 的行（kernel）"""
    return [(i, r) for i, r in enumerate(rows) if r is not None and r[2] in tids and len(r) <= 9]


def _multiples(cands: list[tuple], vote: float) -> set:
    """候选里「每轮固定调 2–4 次」的（一轮调两次的 has_requests）：次数是另一个候选的 k 倍（2 ≤ k ≤ 4，差不到 vote），
    而且那个候选相邻两次调用之间几乎总是（1 - vote）正好 k 次。只看次数不够：每轮都调的调度、隔一阵才忙一轮的干活函数，
    次数也可能正好两倍。cands：(键下标, 次数, 第一次的时刻, 整个 run 的调用, 这段里的调用)"""
    out = set()
    for c in cands:
        for o in cands:
            if not 0 < o[1] < c[1]:
                continue
            k = round(c[1] / o[1])
            if not (2 <= k <= 4 and abs(c[1] - k * o[1]) <= vote * k * o[1]):
                continue
            ts = [x[0] for x in c[4]]
            os_ = [x[0] for x in o[4]]
            good = sum(1 for a, b in zip(os_, os_[1:]) if bisect.bisect_left(ts, b) - bisect.bisect_left(ts, a) == k)
            if good >= (1 - vote) * (len(os_) - 1):
                out.add(c[0])
                break
    return out


def find_loop(lr: list, lo: int, hi: int, p: Params | None = None, head: set[int] | None = None) -> dict | None:
    """这一列的主循环：{tid, head（被调方的键下标）, parent（父函数的键下标，None 是线程根）, depth, calls: [(t0, 下标, 行)]
    （整个 run 的每一次轮头调用）, n（[lo, hi) 里几次）, cover}。[lo, hi) 是认轮头用的那段（REF 所在的阶段）。
    head 给了就只认这几个键（--head：同一个函数可能有几个键）。认不出是 None"""
    p = p or Params()
    rowb = {i: r[5] for i, r in lr}
    groups: dict = {}
    pcalls: dict = {}                               # (tid, 父函数) → 这段时间里父函数自己的调用 [(t0, t1)]
    for i, r in lr:
        # 父亲按「哪个函数」认，不按哪一次调用：每个 token 一个生成器帧时，同一个函数的各次调用合在一起
        pk = (r[2], rowb[r[8]]) if r[8] >= 0 and r[8] in rowb else (r[2], None)
        groups.setdefault(pk, {}).setdefault(r[5], []).append((r[0], i, r))
        end = r[0] + r[1] if r[1] >= 0 else hi
        if r[0] < hi and end > lo:
            pcalls.setdefault((r[2], r[5]), []).append((max(r[0], lo), min(end, hi)))
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
        mult = _multiples(cands, p.vote)
        keep = [c for c in cands if c[0] not in mult] or cands
        def score(n: int) -> tuple:
            votes = sum(1 for d in keep if (1 - p.vote) * n <= d[1] <= (1 + p.vote) * n)
            return (votes * n, n)
        n = max((c[1] for c in keep), key=score)
        b, cnt, _, calls, w = min((c for c in keep if (1 - p.vote) * n <= c[1] <= (1 + p.vote) * n), key=lambda c: c[2])
        if pk[1] is not None and head is None:
            pc = pcalls.get(pk, [])
            if cnt >= 2 * max(len(pc), 1) and sum(y - x for x, y in pc) < 0.5 * (hi - lo):
                continue                            # 一次调用里面的内层循环（worker 处理一个请求时调 20 次 model）
        cand = {"tid": pk[0], "head": b, "parent": pk[1], "depth": w[0][2][3], "calls": calls, "n": cnt,
                "cover": w[-1][0] - w[0][0]}
        if best is None or cand["cover"] > best["cover"] * (1 + p.vote) or (
                cand["cover"] >= best["cover"] * (1 - p.vote) and (cand["depth"], -cnt) < (best["depth"], -best["n"])):
            best = cand
    return best


def cut_rounds(loop: dict, lr: list, ho_out: list, ho_in: list, p: Params | None = None) -> tuple[list[dict], set]:
    """切轮：[{k, t0_us, t1_us, dur_us, calls, out, in, extra: [键下标], long, spin, kids: Counter}]（轮号从 1 数，整个 run）
    和常规的被调方。ho_out / ho_in 是这一列交出 / 收到数据的 [(tid, span 下标, 时刻)]：按 span 归轮，不在 span 里的按时刻；
    只算主循环那条线程的"""
    p = p or Params()
    calls = loop["calls"]
    tid, parent = loop["tid"], loop["parent"]
    bounds = [(t0, calls[k + 1][0] if k + 1 < len(calls) else t0 + max(r[1], 0)) for k, (t0, _, r) in enumerate(calls)]
    starts = [a for a, _ in bounds]
    rs = [{"k": k + 1, "t0_us": a, "t1_us": b, "dur_us": b - a, "work_us": 0, "calls": 0, "out": 0, "in": 0, "kids": Counter()}
          for k, (a, b) in enumerate(bounds)]
    row = {i: r for i, r in lr if r[2] == tid}
    memo: dict[int, int | None] = {}

    def top(i: int) -> int | None:
        """i 在轮头的父函数下面的那个祖先（线程根下的循环：最外层的那个）；不在这个循环里（别的 task）是 None"""
        path, j, got = [], i, None
        while True:
            if j in memo:
                got = memo[j]
                break
            path.append(j)
            r = row.get(j)
            par = r[8] if r is not None else -1
            if parent is None:
                if par < 0 or par not in row:
                    got = j
                    break
            elif par in row and row[par][5] == parent:
                got = j
                break
            elif par < 0 or par not in row:
                got = None
                break
            j = par
        for x in path:
            memo[x] = got
        return got

    def at(t: int) -> int | None:
        k = bisect.bisect_right(starts, t) - 1
        return k if k >= 0 and (t < bounds[k][1] or k + 1 < len(bounds)) else None

    for i, r in row.items():
        t = top(i)
        k = at(row[t][0]) if t is not None else None
        if k is not None:
            rs[k]["calls"] += r[6]
            rs[k]["kids"][r[5]] += 1
            if t == i:                              # 这一轮最外层的调用：合起来是这一轮在仓库函数里的时间
                rs[k]["work_us"] += r[1] if r[1] >= 0 else max(0, rs[k]["t1_us"] - r[0])
    for hs, key in ((ho_out, "out"), (ho_in, "in")):
        for htid, hrow, t in hs:
            if htid != tid:
                continue
            tp = top(hrow) if hrow in row else None
            k = at(row[tp][0]) if tp is not None else at(t) if hrow not in row else None
            if k is not None:
                rs[k][key] += 1
    regular, base_med = _baseline(rs, p)
    for x in rs:
        x["extra"] = sorted(b for b in x["kids"] if b not in regular)
        x["long"] = base_med > 0 and x["dur_us"] > p.long * base_med
        x["spin"] = not x["extra"] and not x["out"] and not x["in"] and not x["long"]
    return rs, regular


def _baseline(rs: list[dict], p: Params) -> tuple[set, float]:
    """这一列自己的常规：按这一轮调到的函数把轮分类，占得够多（class_share）的类里，「在仓库函数里的时间」的中位不超过最少那类
    cheap 倍的是「便宜的类」，它们调到的函数合起来是常规。比的是在调用里的时间、不是一轮的墙上时长：定时循环（每轮固定 1 ms）
    闲着和干活的轮一样长。返回 (常规的被调方, 便宜的那几类轮的墙上时长中位——判超长用)"""
    if not rs:
        return set(), 0
    classes: dict[frozenset, list[dict]] = {}
    for x in rs:
        classes.setdefault(frozenset(x["kids"]), []).append(x)
    floor = max(2, p.class_share * len(rs))
    big = {k: v for k, v in classes.items() if len(v) >= floor} or classes
    meds = {k: statistics.median(x["work_us"] for x in v) for k, v in big.items()}
    least = min(meds.values())
    cheap = [k for k, m in meds.items() if m <= p.cheap * max(least, 1)]
    regular = set().union(*cheap)
    return regular, statistics.median([x["dur_us"] for k in cheap for x in big[k]])


def busy_blocks(items: list[tuple], lo: int, hi: int, p: Params | None = None, scale: int | None = None) -> list[list[tuple]]:
    """前景轮（可以是一个进程里几列的）按开始的先后排，在中间空转超过 gap × scale（缺省是这段时间的长度）处切开：[[轮, …], …]。
    items：(开始, 结束, …)，只看开始在 [lo, hi) 里的"""
    p = p or Params()
    limit = p.gap * (scale or (hi - lo))
    out: list[list[tuple]] = []
    end = 0
    for x in sorted((x for x in items if lo <= x[0] < hi), key=lambda x: x[0]):
        if out and x[0] - end <= limit:
            out[-1].append(x)
            end = max(end, x[1])
        else:
            out.append([x])
            end = x[1]
    return out


def in_window(rs: list[dict], lo: int, hi: int) -> list[dict]:
    """开始在 [lo, hi) 里的轮"""
    return [x for x in rs if lo <= x["t0_us"] < hi]


def kind(n_threads: int, has_rows: bool, loop: dict | None, rs_win: list[dict]) -> str:
    """一列在这段时间里是什么样：loop（有主循环、有前景轮）/ poll（有主循环，这段里全是常规轮）/ threads（每条线程干一件：
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
