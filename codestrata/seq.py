"""一个 run 的时序事件（events.py 整理好的 span）→ 当前切面上每条边什么时候被调用：模块图的「时间顺序」上色。

span 记的是「文件:首行号 → 文件:首行号」的调用（老 run 只有跨文件的），带开始时刻、时长、进程、父 span。这里：

  1. 把整个 run 的 span 解压、读一遍（_pairs），按阶段聚合成 (调用方键, 被调方键) → 第一次 / 最后一次 /
     次数 / 每个进程里的首末——大 run 上解压读一遍要两秒多，所以换切面、换阶段都不再读。
  2. 两端经 rel → 单元 → 切面节点（cut.view 的 node_of）映射（edge_times）；两端落在同一个节点的
     （节点内部的调用）、import / 类体这种定义时的执行（模块图也不把它算作调用，align.defining）、
     落不到 index 里的都不算。

时间一律是相对 run 起点（run.json 的 clock.mono0_ns）的微秒，和阶段的 t_us 同一根轴。
早先这里还有一张时序图（生命线 + 消息，按时间窗分屏、折叠循环）；模块图上的「时间顺序」
把先后画在同一张图上之后就去掉了。
"""
from __future__ import annotations

import bisect
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


# ---------------------------------------------------------------- 每条边的时间

_PAIRS: "OrderedDict[tuple, dict]" = OrderedDict()    # (spans 目录, index mtime, 阶段划分) → _pairs 的结果（最近 8 个；拖出来的每个时间段各占一个）
_EDGES: "OrderedDict[tuple, tuple]" = OrderedDict()   # (_PAIRS 的键, id(idx), 切面, 阶段) → (idx, edge_times 的结果)
_CALLS: "OrderedDict[tuple, dict]" = OrderedDict()   # (spans 目录, index mtime, 时间段) → phase_calls 的结果（最近 8 个）
_BUSY: dict[tuple, threading.Lock] = {}               # 正在算的 _PAIRS 键：同时来的同一个请求等着用一份结果
REPEAT_MIN = 5                                        # 「反复调用」至少要调这么多次（2 次、每个进程一次的不算）


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


def window_counts(rd: Path, t0: int, t1: int, ref_lines: dict | None = None) -> dict:
    """时间段里的调用（折叠行按 calls_in 摊开）→ 和 counts.json.gz 同样形状的 {funcs, func_edges}
    （键都是 文件:首行），交给 align.to_package_graph，模块图照常叠加。老 run 的时序事件只记了跨文件的调用：那种 run 上
    同一个文件里的调用这里没有，函数的次数会比按阶段看的少（前端注明）。span 读不出来时抛 OSError / ValueError。
    ref_lines：整个 run 的调用行（counts.json.gz 的 func_lines）。span 不记调用行，给了的话每对的次数按它在整个 run
    里各行的比例摊到行上（spread_lines），也返回 func_lines，和 scan 比的时候才和按阶段看一样按行比"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（录的时候用了 --no-events，或者被录的 Python 低于 3.12）：只能按阶段看，不能选时间段")
    ix = _index(spans)
    keys, funcs, edges, gpu = ix["keys"], {}, {}, {}
    for c in ix["chunks"]:
        if c["t0_us"] > t1 or c["t1_us"] < t0:
            continue
        for r in _chunk(spans, c["chunk"]):
            got = calls_in(r[0], r[1], r[6], t0, t1)
            if got is None or not (0 <= r[4] < len(keys) and 0 <= r[5] < len(keys)):
                continue
            a, b, n = keys[r[4]], keys[r[5]], got[0]
            funcs[b] = funcs.get(b, 0) + n
            edges[f"{a}|{b}"] = edges.get(f"{a}|{b}", 0) + n
            if len(r) > 9:                       # GPU 的行（kernel）：按发起的时刻算在不在这一段里，时长是它在 GPU 上跑完为止
                gpu[b] = gpu.get(b, 0) + max(0, r[1] - r[9][2])
    out = {"funcs": funcs, "func_edges": edges}
    if gpu:
        out["gpu_us"] = gpu
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


def _pairs(spans: Path, run: dict, window: tuple[int, int] | None = None) -> tuple[tuple, dict]:
    """把整个 run 的 span 解压、读一遍：每个阶段（None 是整个 run）里，(调用方键, 被调方键) →
    [first, last, n, {pid: [first, last]}]。归到切面的节点是后一步（edge_times，很便宜）——换切面、换阶段
    都不用再解压（158 万条 span 的 run 解一遍要两秒多）。同时来的同一个请求只算一次。
    折叠过的 span（rep 次连续的同级调用合成一行）按 calls_in 均匀摊到它盖住的时间上，跨了阶段的分到各个阶段。
    window（时间轴拖出来的时间段）：只读和它重叠的块、只算在它里面的调用，结果只有 None 一张表"""
    ix = _index(spans)
    end = run_end(run, spans.parent.parent) or 0
    iv = phase_intervals(run, end) if window is None else {None: [window]}
    key = (str(spans), (spans / "index.json").stat().st_mtime_ns,
           tuple((n, tuple(v)) for n, v in sorted(iv.items(), key=lambda kv: (kv[0] is not None, kv[0] or ""))))
    with _LOCK:
        hit = _PAIRS.get(key)
        busy = hit is None and _BUSY.setdefault(key, threading.Lock())
    if hit is not None:
        return key, hit
    with busy:
        with _LOCK:
            hit = _PAIRS.get(key)
        if hit is not None:
            return key, hit
        try:
            out = _pairs_scan(spans, ix, iv, *(window or (0, end)))
            _put(_PAIRS, key, out, cap=8)          # 先放进缓存再撤掉「正在算」：中间来的请求不会再解一遍
        finally:
            with _LOCK:
                _BUSY.pop(key, None)
        return key, out


def _pairs_scan(spans: Path, ix: dict, iv: dict, lo: int, hi: int) -> dict:
    """_pairs 真正读 span 的那一遍：[lo, hi] 里的调用。阶段的各段左闭右开（切阶段那一刻的调用归新阶段），
    最后一段闭到 run 的终点；一行折叠的调用跨了几段就按 calls_in 分到几段"""
    segs = sorted((t0, t1, name) for name, v in iv.items() if name is not None for t0, t1 in v)
    starts = [x[0] for x in segs]
    agg: dict = {name: {} for name in iv}

    def add(d, k, got, pid):
        n, t, last = got
        e = d.get(k)
        if e is None:
            d[k] = [t, last, n, {pid: [t, last]}]
            return
        e[0], e[1], e[2] = min(e[0], t), max(e[1], last), e[2] + n
        q = e[3].get(pid)
        if q is None:
            e[3][pid] = [t, last]
        else:
            q[0], q[1] = min(q[0], t), max(q[1], last)
    for c in ix["chunks"]:
        if c["t0_us"] > hi or c["t1_us"] < lo:
            continue
        pid = c["pid"]
        for r in _chunk(spans, c["chunk"]):
            t, dur, rep, k = r[0], r[1], r[6], (r[4], r[5])
            got = calls_in(t, dur, rep, lo, hi)
            if got is None:
                continue
            add(agg[None], k, got, pid)
            end = t + max(dur, 0) if rep > 1 else t
            i = max(0, bisect.bisect_right(starts, t) - 1)
            while i < len(segs) and segs[i][0] <= end:
                g = calls_in(t, dur, rep, segs[i][0], segs[i][1], open_hi=i + 1 < len(segs))
                if g:
                    add(agg[segs[i][2]], k, g, pid)
                i += 1
    return {"iv": iv, "agg": agg, "keys": ix["keys"], "truncated": ix.get("truncated") or []}


def phase_calls(rd: Path, run: dict, phase: str | None) -> dict:
    """一个阶段（None 是整个 run，「t=起-止」是时间段）里每个进程、每个线程的调用（请求路径、分列里一列的叠加用）：
    {"window": [起, 止], "span_us": 各段加起来多长, "keys": [键], "threads": {pid: {tid: 名字}}, "truncated": [pid],
     "scope": "all" | "cross"（老 run 的时序事件只记了跨文件的调用）, "calls": {(pid, tid, a, b): [first, last, n]},
     "gpu": {(pid, tid, a, b, 设备, 流): [first, last, n, GPU 上跑了多久 µs]}}
    ——a、b 是 keys 的下标，时刻是微秒、相对 run 起点。折叠行按 calls_in 摊开；阶段的各段左闭右开，最后一段闭到 run 的终点（同 _pairs）。
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
    for c in ix["chunks"]:
        if all(c["t0_us"] > hi or c["t1_us"] < lo for lo, hi in segs):
            continue
        pid = c["pid"]
        for r in _chunk(spans, c["chunk"]):
            for lo, hi in segs:
                got = calls_in(r[0], r[1], r[6], lo, hi, open_hi=not win and hi < end)
                if got is None:
                    continue
                n, f, last = got
                k = (pid, r[2], r[4], r[5])
                e = calls.get(k)
                if e is None:
                    calls[k] = [f, last, n]
                else:
                    e[0], e[1], e[2] = min(e[0], f), max(e[1], last), e[2] + n
                if len(r) > 9:                   # GPU 的行（kernel）：时长是它在 GPU 上跑完为止，减去晚了的那段是 GPU 上跑的时间
                    g = gpu.setdefault(k + tuple(r[9][:2]), [f, last, 0, 0])
                    g[0], g[1], g[2], g[3] = min(g[0], f), max(g[1], last), g[2] + n, g[3] + max(0, r[1] - r[9][2])
    out = {"window": [segs[0][0], segs[-1][1]], "span_us": sum(b - a for a, b in segs), "keys": ix["keys"],
           "threads": ix["threads"], "truncated": ix.get("truncated") or [], "scope": ix.get("scope") or "cross",
           "calls": calls, "gpu": gpu}
    _put(_CALLS, key, out, cap=8)
    return out


def edge_times(idx: dict, rd: Path, run: dict, *, open_, phase: str | None = None, keymap=None,
               redirect: dict | None = None) -> dict:
    """切面上每条节点间的边在一个阶段（None 是整个 run）里什么时候被调用：
    {"window": [起, 止], "intervals": [(起, 止)…], "span_us": 各段加起来多长,
     "edges": {"a|b": {first, last, n, spread, repeat}}, "truncated"}（微秒，相对 run 起点）。
    模块图的「时间顺序」按 first 排名上色：控制流第一次走到这条边的时刻，讲一条调用链时的先后就是它。
    spread 是同一个进程里第一次到最后一次隔了多久（取各进程里最长的）；repeat（反复调用）要至少 REPEAT_MIN 次、
    而且 spread 超过这段时间的一半——每个进程各调一次的、只调两次的都不算。
    两端落在同一个节点的（节点内部的调用）、import / 类体这种定义时的执行、落不到 index 里的都不算。
    keymap：录制时的键 → 现在的（align.key_mapper；录制之后改过的文件里函数挪了位置），没给就原样用。
    redirect：同一个 run（阶段、时间段）的 hot["redirect"]（trace 的键对 → 类）——构造 C(…) 跑到的 __init__ 这类，
    模块图上算在 F→C 上（align.classify），这里也算到 C 的文件上，时刻才落在图上画着的那条边上"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（录的时候用了 --no-events，或者被录的 Python 低于 3.12）")
    win = parse_window(phase)
    pkey, P = _pairs(spans, run, win)
    if win:
        phase = None                                   # 时间段：只有一张表（_pairs 的 window）
    elif phase not in P["iv"]:
        raise LookupError(f"这个 run 里没有阶段 {phase} 的时刻：不知道它从什么时候开始，没法按时间排")
    key = (pkey, id(idx), None if open_ is None else ",".join(sorted(open_)), phase, keymap is not None,
           bool(redirect))
    with _LOCK:
        hit = _EDGES.get(key)
    if hit is not None and hit[0] is idx:              # 连 idx 一起存：id 不会被重新扫出来的 index 复用
        return hit[1]
    keys, m = P["keys"], cut_map(idx, open_)
    edges: dict[str, dict] = {}
    pids: dict[str, dict] = {}
    for (a, b), (first, last, n, per) in P["agg"][phase].items():
        ka, kb = keys[a] if 0 <= a < len(keys) else "?", keys[b] if 0 <= b < len(keys) else "?"
        if keymap is not None:
            ka, kb = keymap(ka), keymap(kb)
        na = m.of(ka)[0]
        to = redirect.get(f"{ka}|{kb}") if redirect else None
        nb, defining = (m.file_node(m.syms[to]["f"]), False) if to else m.of(kb)
        if na is None or nb is None or na == nb or defining:
            continue
        k = f"{na}|{nb}"
        e = edges.get(k)
        if e is None:
            edges[k], pids[k] = {"first": first, "last": last, "n": n}, {}
        else:
            e["first"], e["last"], e["n"] = min(e["first"], first), max(e["last"], last), e["n"] + n
        for pid, (f, l) in per.items():
            q = pids[k].get(pid)
            pids[k][pid] = [f, l] if q is None else [min(q[0], f), max(q[1], l)]
    segs = P["iv"][phase]
    span = sum(t1 - t0 for t0, t1 in segs)
    for k, e in edges.items():
        # 反复调用：够多次，而且同一个进程里从头到尾隔了这段时间的一半以上（轮询、每个 token 走一遍）
        e["spread"] = max(l - f for f, l in pids[k].values())
        e["repeat"] = e["n"] >= REPEAT_MIN and e["spread"] > span / 2
    out = {"window": [segs[0][0], segs[-1][1]], "intervals": segs, "span_us": span,
           "edges": edges, "truncated": P["truncated"]}
    _put(_EDGES, key, (idx, out))
    return out
