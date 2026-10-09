"""一个 run 的时序事件（events.py 整理好的 span）→ 一段时间（阶段、拖出来的时间段、整个 run）里每个进程、每条线程的调用表。

span 记的是「文件:首行号 → 文件:首行号」的调用（老 run 只有跨文件的），带开始时刻、时长、进程、线程、父 span。这里：

  1. phase_calls：把这一段里的 span 解压、读一遍，聚合成 (进程, 线程, 调用方键, 被调方键) → 第一次 / 最后一次 / 次数 /
     深度 0 的最早一次（GPU 的行另按设备 · 流记一份）；按 (run, 时间段) 缓存。分列（lanes.build、一列的叠加）、请求路径的老做法、
     边详情按先后排、时间段的计数（window_counts）都从这张表取——改切面、换一列展开不再读 span。
  2. run_rows：整个 run 读一遍就有的、和时间段无关的（有 span 的线程、每条线程最底下的仓库函数、按下标取一行的被调方和开始时刻）；按 run 缓存。
  3. cut_map：键 → 切面上的节点（一个 (idx, 切面) 算一次）。
请求路径的调用上下文树要每一行的父 span，那一处（path._contexts）自己逐行读。

时间一律是相对 run 起点（run.json 的 clock.mono0_ns）的微秒，和阶段的 t_us 同一根轴。
"""
from __future__ import annotations

import gzip
import json
import math
import threading
from collections import OrderedDict
from pathlib import Path

from . import align as _align
from . import cut as _cut

_LOCK = threading.Lock()
_INDEX: "OrderedDict[tuple, dict]" = OrderedDict()     # (spans 目录, index mtime) → index + keys（最近 16 个）


# ---------------------------------------------------------------- 读 span

def _put(cache: OrderedDict, key, val, cap: int = 16):
    with _LOCK:
        cache[key] = val
        cache.move_to_end(key)
        while len(cache) > cap:
            cache.popitem(last=False)


def _index(spans: Path) -> dict:
    p = spans / "index.json"
    key = (str(spans), p.stat().st_mtime_ns)
    with _LOCK:
        hit = _INDEX.get(key)
    if hit is None:
        idx = json.loads(p.read_text(encoding="utf-8"))
        keys = json.loads((spans / "keys.json").read_text(encoding="utf-8"))
        hit = {**idx, "keys": keys["keys"], "threads": keys.get("threads") or {}}
        _put(_INDEX, key, hit)
    return hit


def span_index(rd: Path) -> dict:
    """一个 run 的 span 索引（index.json 加上 keys.json 的 keys、threads）；没录时序事件抛 LookupError"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（录的时候用了 --no-events，或者被录的 Python 低于 3.12）")
    return _index(spans)


def pid_rows(rd: Path, pid: int, lo: int | None = None, hi: int | None = None) -> list:
    """一个进程的全部 span 行（按 t0 排好，下标就是 parent / thread_from / handoffs 里的那个下标）。
    给了 [lo, hi]：和它不重叠的块不解压，那些块的位置上放 None（下标不变）"""
    spans = rd / "events" / "spans"
    out: list = []
    for c in span_index(rd)["chunks"]:
        if c["pid"] != pid:
            continue
        if lo is not None and (c["t0_us"] > hi or c["t1_us"] < lo):
            out.extend([None] * c["n"])
        else:
            out.extend(_chunk(spans, c["chunk"]))
    return out


def window_segments(run: dict, rd: Path, phase: str | None) -> tuple[list, bool, int]:
    """阶段（None 是整个 run，「t=起-止」是时间段）→ (时间段 [(起, 止)], 是不是拖出来的时间段, run 的终点)。
    阶段的各段左闭右开，最后一段闭到 run 的终点（calls_in 的 open_hi）。没有这个阶段的时刻抛 LookupError"""
    end = run_end(run, rd) or 0
    win = parse_window(phase)
    if win:
        return [win], True, end
    iv = phase_intervals(run, end)
    if phase not in iv:
        raise LookupError(f"这个 run 里没有阶段 {phase} 的时刻：不知道它从什么时候开始")
    return sorted(iv[phase]), False, end


def _chunk(spans: Path, name: str) -> list:
    """一块 span（gzip 的 JSON 行）→ 行的列表。一块一次 json.loads（拼成一个数组）：逐行 loads 慢三倍，
    大 run 上解压读一遍的时间几乎都花在这里"""
    lines = [ln for ln in gzip.decompress((spans / name).read_bytes()).decode().split("\n") if ln]
    return json.loads("[" + ",".join(lines) + "]")


# ---------------------------------------------------------------- 映射到切面

_MAPS: "OrderedDict[tuple, tuple]" = OrderedDict()   # (id(idx), 切面) → (idx, _Map)（最近 16 个：分列里每列可以有自己的切面）


def cut_map(idx: dict, open_) -> "_Map":
    """键 rel:行 → 切面上的节点（_Map.of / file_node / unit）。一个 (idx, 切面) 算一次"""
    key = (id(idx), None if open_ is None else ",".join(sorted(open_)))
    with _LOCK:
        hit = _MAPS.get(key)
        if hit is not None and hit[0] is idx:      # 缓存里连 idx 一起存着：id 不会被别的 index 复用
            _MAPS.move_to_end(key)
            return hit[1]
    m = _Map(idx, open_)
    with _LOCK:
        _MAPS[key] = (idx, m)
        while len(_MAPS) > 16:
            _MAPS.popitem(last=False)
    return m


class _Map:
    """键 rel:行 → 它在切面上落在哪个节点、是不是定义时的执行。一个 (idx, 切面) 算一次（_map 缓存）。"""

    def __init__(self, idx: dict, open_):
        self.v = _cut.view(idx, set(open_) if open_ is not None else set(idx.get("default_open") or []))
        self.files = idx.get("files") or {}
        self.node_of = self.v["node_of"]
        self.syms = idx.get("symbols") or {}
        self.loc = _align.sym_locs(self.syms)[0]
        self._memo: dict[str, tuple] = {}

    def of(self, key: str) -> tuple:
        """(节点 或 None, 是不是定义时的执行（模块顶层、类体；和模块图同一个判断 align.defining）)"""
        hit = self._memo.get(key)
        if hit is None:
            rel, _, ln = key.rpartition(":")
            try:
                line = int(ln)
            except ValueError:
                line = 0
            hit = self._memo[key] = (self.file_node(rel), bool(_align.defining(self.syms, self.loc, rel, line)))
        return hit

    def file_node(self, rel: str):
        unit = _cut.unit_of_rel(self.files, rel)
        return self.node_of.get(unit) if unit else None

    def unit(self, key: str) -> str | None:
        """键 rel:行 → 它所在的单元（和切面无关）；落不到 index 里是 None"""
        return _cut.unit_of_rel(self.files, key.rpartition(":")[0])


# ---------------------------------------------------------------- 阶段、时间段

_CALLS: "OrderedDict[tuple, dict]" = OrderedDict()   # (spans 目录, index mtime, 时间段) → phase_calls 的结果（最近 8 个）
REPEAT_MIN = 5                                        # 「反复调用」至少要调这么多次（2 次、每个进程一次的不算）


def is_repeat(n: int, first: int, last: int, span_us: int) -> bool:
    """「反复调用」（轮询、每个 token 都走一遍）：至少 REPEAT_MIN 次，而且第一次到最后一次隔了这一段（各个时间片加起来）的一半以上。
    请求路径的 ↻、分列里时间顺序的 ↻ 都按它"""
    return n >= REPEAT_MIN and last - first > span_us / 2


def _phase_log(run: dict) -> list[tuple[str, int]]:
    """切阶段的时刻 [(名字, t_us)]，按时间排：按 phase_log（[名字, t_us, 来源]），老 run 没有就按 phases 的 t_us"""
    log = [(x[0], x[1]) for x in run.get("phase_log") or [] if len(x) > 1 and x[1] is not None]
    if not log:
        log = [(p["name"], p["t_us"]) for p in run.get("phases") or [] if p.get("t_us") is not None]
    return sorted(log, key=lambda x: x[1])


def phase_segments(run: dict, end_us: int) -> list[tuple[str, int, int]]:
    """run 按阶段切成的一段段 [(名字, 起, 止)]（微秒，相对 run 起点，按时间排）：同一个阶段切走又切回来
    就有几段。页面的时间轴画的就是它（runs.load 放进 meta）"""
    log = _phase_log(run)
    return [(name, t, log[i + 1][1] if i + 1 < len(log) else end_us) for i, (name, t) in enumerate(log)]


def phase_intervals(run: dict, end_us: int) -> dict:
    """每个阶段的时间段 {名字: [(起, 止)]}；None 是整个 run"""
    out: dict = {None: [(0, end_us)]}
    for name, a, b in phase_segments(run, end_us):
        out.setdefault(name, []).append((a, b))
    return out


def parse_window(phase: str | None) -> tuple[int, int] | None:
    """「t=起-止」（微秒，相对 run 起点）是时间段，不是阶段名：页面上时间轴拖出来的范围，和阶段名放在
    同一个位置（run 引用的 @ 后面），加载、缓存、地址栏都照走。别的（阶段名、None）→ None"""
    if not phase or not phase.startswith("t="):
        return None
    try:
        a, b = (int(x) for x in phase[2:].split("-", 1))
    except ValueError:
        raise ValueError(f"时间段写成 t=起-止（微秒）：{phase}") from None
    if a < 0 or b <= a:
        raise ValueError(f"时间段的起点要小于终点：{phase}")
    return a, b


def run_end(run: dict, rd: Path) -> int | None:
    """时间轴的终点（微秒，相对 run 起点）：最后一条 span 的结束、最后一次切阶段、run 的时长，取最大的。
    只按 span 不行：被 SIGTERM / SIGKILL 停掉的服务最后的调用没返回，span 停在切到 shutdown 之前，
    最后一个阶段就倒着走了。span 读不出来（文件坏了）时不算它——加载图不该因此失败，
    要读 span 的地方（时间段、时间顺序）各自报错。什么都不知道是 None"""
    ends = [int((run.get("duration_s") or 0) * 1e6)] + [t for _, t in _phase_log(run)]
    spans = rd / "events" / "spans"
    if (spans / "index.json").is_file():
        try:
            ends.append(max((c["t1_us"] for c in _index(spans)["chunks"]), default=0))
        except (OSError, ValueError, KeyError):
            pass
    return max(ends) or None


def unreadable(e: Exception, run_id: str) -> str:
    """span 文件坏了（解压、JSON 出错）时给人看的话"""
    return f"时序数据读不出来：{type(e).__name__}: {e}（可以 codestrata runs <repo> merge {run_id} 重建）"


def gpu_ns(r: list) -> int:
    """GPU 的行（kernel，第 10 列是 [设备, 流, 晚了多少 µs, 在 GPU 上跑了多少 ns]）在 GPU 上跑了多少纳秒。2026-10-08 之前整理的行
    没有第 4 个：按「到跑完的时长 − 晚了多少」算，两个都是取整过的 µs，1 µs 上下的小 kernel 会差出不少"""
    g = r[9]
    return g[3] if len(g) > 3 else max(0, r[1] - g[2]) * 1000


def calls_in(t: int, dur: int, rep: int, lo: int, hi: int, open_hi: bool = False) -> tuple[int, int, int] | None:
    """一行 span 里落在 [lo, hi]（open_hi：[lo, hi)）的调用：(次数, 第一次的开始, 最后一次的开始)，没有是 None。
    折叠行（rep 次连续的同级调用合成一行，只记了第一次的开始和整行的结束）按 rep 次调用均匀摊在
    [开始, 结束] 上：一行能盖住几十秒（vllm-omni 里的轮询，一行 3852 次、从 68 s 到 112 s），整行算在开始的
    那一刻，一秒的时间段里会多出几千次、之后几十秒一次都没有。没返回的（dur < 0）只知道开始，整行算在开始"""
    if rep <= 1 or dur <= 0:
        return (rep, t, t) if lo <= t and (t < hi if open_hi else t <= hi) else None
    step = dur / (rep - 1)
    i0 = max(0, math.ceil((lo - t) / step))
    i1 = min(rep - 1, math.ceil((hi - t) / step) - 1 if open_hi else math.floor((hi - t) / step))
    if i1 < i0:
        return None
    return i1 - i0 + 1, t + round(i0 * step), t + round(i1 * step)


def window_counts(rd: Path, run: dict, t0: int, t1: int, ref_lines: dict | None = None) -> dict:
    """时间段里的调用（折叠行按 calls_in 摊开）→ 和 counts.json.gz 同样形状的 {funcs, func_edges, gpu_us?}
    （键都是 文件:首行），交给 align.to_package_graph，模块图照常叠加。从 phase_calls 那张表加起来（和分列、请求路径同一份）。
    老 run 的时序事件只记了跨文件的调用：那种 run 上同一个文件里的调用这里没有，函数的次数会比按阶段看的少（前端注明）。
    span 读不出来时抛 OSError / ValueError。ref_lines：整个 run 的调用行（counts.json.gz 的 func_lines）。span 不记调用行，
    给了的话每对的次数按它在整个 run 里各行的比例摊到行上（spread_lines），也返回 func_lines，和 scan 比的时候才和按阶段看一样按行比"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（录的时候用了 --no-events，或者被录的 Python 低于 3.12）：只能按阶段看，不能选时间段")
    pc = phase_calls(rd, run, f"t={t0}-{t1}")
    keys, funcs, edges, gpu = pc["keys"], {}, {}, {}
    ok = lambda a, b: 0 <= a < len(keys) and 0 <= b < len(keys)    # noqa: E731
    for (_, _, a, b), (_, _, n, _) in pc["calls"].items():
        if ok(a, b):
            funcs[keys[b]] = funcs.get(keys[b], 0) + n
            edges[f"{keys[a]}|{keys[b]}"] = edges.get(f"{keys[a]}|{keys[b]}", 0) + n
    for (_, _, a, b, _, _), (_, _, _, ns) in pc["gpu"].items():   # GPU 的行（kernel）：按发起的时刻算在不在这一段里，按纳秒加、最后换成 µs
        if ok(a, b):
            gpu[keys[b]] = gpu.get(keys[b], 0) + ns
    out = {"funcs": funcs, "func_edges": edges}
    if gpu:
        out["gpu_us"] = {k: round(ns / 1000) for k, ns in gpu.items()}
    if ref_lines is not None:
        out["func_lines"] = spread_lines(edges, ref_lines)
    return out


def spread_lines(edges: dict, ref_lines: dict) -> dict:
    """{"a|b": 次数} 按 ref_lines（{"a|b|行": 次数}）里这一对在各行的比例摊成 {"a|b|行": 次数}：整数、每对加起来
    正好是它的次数（最大余数法）。ref_lines 里没有这一对的记在第 0 行（不知道是哪一行）"""
    by: dict[str, list] = {}
    for k, m in ref_lines.items():
        ab, _, l = k.rpartition("|")
        by.setdefault(ab, []).append((int(l), m))
    out: dict[str, int] = {}
    for ab, n in edges.items():
        ls = by.get(ab)
        if not ls:
            out[f"{ab}|0"] = n
            continue
        tot = sum(m for _, m in ls)
        share = sorted(((n * m // tot, n * m % tot, l) for l, m in ls), key=lambda s: (-s[1], s[2]))
        left = n - sum(s[0] for s in share)
        for i, (q, _, l) in enumerate(share):
            v = q + int(i < left)
            if v:
                out[f"{ab}|{l}"] = v
    return out


_ROWS: "OrderedDict[tuple, dict]" = OrderedDict()    # (spans 目录, index mtime) → run_rows 的结果（最近 4 个）


def run_rows(rd: Path) -> dict:
    """整个 run 的 span 读一遍就有的、和阶段 / 时间段无关的东西（分列用；按 run 缓存，换阶段、改切面都不再读）：
    {"tids": {pid: {tid, …}}（有 span 的线程），
     "held": {(pid, tid): {调用方键下标: [最早开始, 最晚结束]}}——深度 0 的调用的调用方是这条线程最底下的仓库函数，它至少在这段时间里
             在栈上（没返回的结束是 inf）；交接发生在仓库外的代码里时，按它认那一刻在跑的是哪个仓库函数,
     "rows": {pid: ([被调方键下标…], [开始…])}——按下标取一行 span 的被调方和开始时刻（交接、起线程、子进程记的是 span 下标）}"""
    spans = rd / "events" / "spans"
    ix = span_index(rd)
    key = (str(spans), (spans / "index.json").stat().st_mtime_ns)
    with _LOCK:
        hit = _ROWS.get(key)
    if hit is not None:
        return hit
    tids: dict[int, set] = {}
    held: dict[tuple, dict] = {}
    rows: dict[int, tuple] = {}
    for c in ix["chunks"]:
        pid = c["pid"]
        bs, ts = rows.setdefault(pid, ([], []))
        ti = tids.setdefault(pid, set())
        for r in _chunk(spans, c["chunk"]):
            bs.append(r[5])
            ts.append(r[0])
            ti.add(r[2])
            if r[3] == 0:
                hk = held.setdefault((pid, r[2]), {}).setdefault(r[4], [r[0], r[0]])
                hk[0] = min(hk[0], r[0])
                hk[1] = max(hk[1], r[0] + r[1] if r[1] >= 0 else math.inf)
    out = {"tids": tids, "held": held, "rows": rows}
    _put(_ROWS, key, out, cap=4)
    return out


def phase_calls(rd: Path, run: dict, phase: str | None) -> dict:
    """一个阶段（None 是整个 run，「t=起-止」是时间段）里每个进程、每个线程的调用（请求路径、分列里一列的叠加用）：
    {"window": [起, 止], "span_us": 各段加起来多长, "keys": [键], "threads": {pid: {tid: 名字}}, "truncated": [pid],
     "scope": "all" | "cross"（老 run 的时序事件只记了跨文件的调用）, "calls": {(pid, tid, a, b): [first, last, n, first0]},
     "gpu": {(pid, tid, a, b, 设备, 流): [first, last, n, GPU 上跑了多少 ns]}}
    ——a、b 是 keys 的下标，时刻是微秒、相对 run 起点。折叠行按 calls_in 摊开；阶段的各段左闭右开，最后一段闭到 run 的终点。
    first0 是这一段里深度 0（线程最底下）的这对调用最早的一次：(时刻, 行的先后) 或 None——分列按它认一列的入口，一样早的取先读到的那一行。
    这张表按 (run, 时间段) 缓存：分列里改切面、换一列展开都从它取，不再读 span。
    GPU 的行（trace --gpu 的 kernel，tid 是发起它的线程、a 是调用方、b 是 kernel）在 calls 里照样有（请求路径列它），gpu 里再按设备 · 流记一份。
    没有 span、没有这个阶段的时刻抛 LookupError，span 读不出来抛 OSError / ValueError"""
    spans = rd / "events" / "spans"
    ix = span_index(rd)
    segs, win, end = window_segments(run, rd, phase)
    key = (str(spans), (spans / "index.json").stat().st_mtime_ns, tuple(segs))
    with _LOCK:
        hit = _CALLS.get(key)
    if hit is not None:
        return hit
    calls: dict = {}
    gpu: dict = {}
    order = 0
    for c in ix["chunks"]:
        if all(c["t0_us"] > hi or c["t1_us"] < lo for lo, hi in segs):
            continue
        pid = c["pid"]
        for r in _chunk(spans, c["chunk"]):
            order += 1
            for lo, hi in segs:
                got = calls_in(r[0], r[1], r[6], lo, hi, open_hi=not win and hi < end)
                if got is None:
                    continue
                n, f, last = got
                k = (pid, r[2], r[4], r[5])
                e = calls.get(k)
                if e is None:
                    e = calls[k] = [f, last, n, None]
                else:
                    e[0], e[1], e[2] = min(e[0], f), max(e[1], last), e[2] + n
                if r[3] == 0 and (e[3] is None or (f, order) < e[3]):
                    e[3] = (f, order)
                if len(r) > 9:                   # GPU 的行（kernel）：GPU 上跑的时间按纳秒记（gpu_ns）
                    g = gpu.setdefault(k + tuple(r[9][:2]), [f, last, 0, 0])
                    g[0], g[1], g[2], g[3] = min(g[0], f), max(g[1], last), g[2] + n, g[3] + gpu_ns(r)
    out = {"window": [segs[0][0], segs[-1][1]], "span_us": sum(b - a for a, b in segs), "keys": ix["keys"],
           "threads": ix["threads"], "truncated": ix.get("truncated") or [], "scope": ix.get("scope") or "cross",
           "calls": calls, "gpu": gpu}
    _put(_CALLS, key, out, cap=8)
    return out
