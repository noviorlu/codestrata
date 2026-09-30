"""一个 run 的时序事件（events.py 整理好的 span）→ 当前切面上每条边什么时候被调用：模块图的「时间顺序」上色。

span 记的是「文件:首行号 → 文件:首行号」的跨文件调用，带开始时刻、时长、进程。这里：

  1. 把整个 run 的 span 解压、读一遍（_pairs），按阶段聚合成 (调用方键, 被调方键) → 第一次 / 最后一次 /
     次数 / 每个进程里的首末——大 run 上解压读一遍要两秒多，所以换切面、换阶段都不再读。
  2. 两端经 rel → 单元 → 切面节点（cut.view 的 node_of）映射（edge_times）；两端落在同一个节点的
     （节点内部的调用）、import / 类体这种定义时的执行（模块图也不把它算作调用，trace.defining）、
     落不到 index 里的都不算。

时间一律是相对 run 起点（run.json 的 clock.mono0_ns）的微秒，和阶段的 t_us 同一根轴。
早先这里还有一张时序图（生命线 + 消息，按时间窗分屏、折叠循环）；模块图上的「时间顺序」
把先后画在同一张图上之后就去掉了。
"""
from __future__ import annotations

import bisect
import gzip
import json
import threading
from collections import OrderedDict
from pathlib import Path

from . import cut as _cut
from . import trace as _trace

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
        hit = {**idx, "keys": keys["keys"]}
        _put(_INDEX, key, hit)
    return hit


def _chunk(spans: Path, name: str) -> list:
    """一块 span（gzip 的 JSON 行）→ 行的列表。一块一次 json.loads（拼成一个数组）：逐行 loads 慢三倍，
    大 run 上解压读一遍的时间几乎都花在这里"""
    lines = [ln for ln in gzip.decompress((spans / name).read_bytes()).decode().split("\n") if ln]
    return json.loads("[" + ",".join(lines) + "]")


# ---------------------------------------------------------------- 映射到切面

_MAPS: "OrderedDict[tuple, tuple]" = OrderedDict()   # (id(idx), 切面) → (idx, _Map)


def _map(idx: dict, open_) -> "_Map":
    key = (id(idx), None if open_ is None else ",".join(sorted(open_)))
    with _LOCK:
        hit = _MAPS.get(key)
        if hit is not None and hit[0] is idx:      # 缓存里连 idx 一起存着：id 不会被别的 index 复用
            _MAPS.move_to_end(key)
            return hit[1]
    m = _Map(idx, open_)
    with _LOCK:
        _MAPS[key] = (idx, m)
        while len(_MAPS) > 8:
            _MAPS.popitem(last=False)
    return m


class _Map:
    """键 rel:行 → 它在切面上落在哪个节点、是不是定义时的执行。一个 (idx, 切面) 算一次（_map 缓存）。"""

    def __init__(self, idx: dict, open_):
        self.v = _cut.view(idx, set(open_) if open_ is not None else set(idx.get("default_open") or []))
        self.files = idx.get("files") or {}
        self.node_of = self.v["node_of"]
        self.syms = idx.get("symbols") or {}
        self.loc = _trace.sym_locs(self.syms)[0]
        self._memo: dict[str, tuple] = {}

    def of(self, key: str) -> tuple:
        """(节点 或 None, 是不是定义时的执行（模块顶层、类体；和模块图同一个判断 trace.defining）)"""
        hit = self._memo.get(key)
        if hit is None:
            rel, _, ln = key.rpartition(":")
            try:
                line = int(ln)
            except ValueError:
                line = 0
            unit = self.files.get(rel)
            hit = self._memo[key] = (self.node_of.get(unit) if unit else None,
                                     bool(_trace.defining(self.syms, self.loc, rel, line)))
        return hit


# ---------------------------------------------------------------- 每条边的时间

_PAIRS: "OrderedDict[tuple, dict]" = OrderedDict()    # (spans 目录, index mtime, 阶段划分) → _pairs 的结果（最近 4 个）
_EDGES: "OrderedDict[tuple, tuple]" = OrderedDict()   # (_PAIRS 的键, id(idx), 切面, 阶段) → (idx, edge_times 的结果)
_BUSY: dict[tuple, threading.Lock] = {}               # 正在算的 _PAIRS 键：同时来的同一个请求等着用一份结果
REPEAT_MIN = 5                                        # 「反复调用」至少要调这么多次（2 次、每个进程一次的不算）


def phase_intervals(run: dict, end_us: int) -> dict:
    """每个阶段在 run 里的时间段 [(起, 止)]（微秒，相对 run 起点）：同一个阶段切走又切回来就有几段；
    None 是整个 run。时刻按 phase_log（[名字, t_us, 来源]），老 run 没有就按 phases 的 t_us"""
    log = [(x[0], x[1]) for x in run.get("phase_log") or [] if len(x) > 1 and x[1] is not None]
    if not log:
        log = [(p["name"], p["t_us"]) for p in run.get("phases") or [] if p.get("t_us") is not None]
    log.sort(key=lambda x: x[1])
    out: dict = {None: [(0, end_us)]}
    for i, (name, t) in enumerate(log):
        out.setdefault(name, []).append((t, log[i + 1][1] if i + 1 < len(log) else end_us))
    return out


def _pairs(spans: Path, run: dict) -> tuple[tuple, dict]:
    """把整个 run 的 span 解压、读一遍：每个阶段（None 是整个 run）里，(调用方键, 被调方键) →
    [first, last, n, {pid: [first, last]}]。归到切面的节点是后一步（edge_times，很便宜）——换切面、换阶段
    都不用再解压（158 万条 span 的 run 解一遍要两秒多）。同时来的同一个请求只算一次。
    折叠过的 span（rep 次连续的同级调用合成一行）：first 是第一次的开始，last 取这一行的结束
    （最后一次调用的开始不会晚于它），不超过所在时间段的终点"""
    ix = _index(spans)
    end_us = max((c["t1_us"] for c in ix["chunks"]), default=0)
    iv = phase_intervals(run, end_us)
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
            out = _pairs_scan(spans, ix, iv, end_us)
            _put(_PAIRS, key, out, cap=4)          # 先放进缓存再撤掉「正在算」：中间来的请求不会再解一遍
        finally:
            with _LOCK:
                _BUSY.pop(key, None)
        return key, out


def _pairs_scan(spans: Path, ix: dict, iv: dict, end_us: int) -> dict:
    """_pairs 真正读 span 的那一遍"""
    segs = sorted((t0, t1, name) for name, v in iv.items() if name is not None for t0, t1 in v)
    starts = [x[0] for x in segs]
    agg: dict = {name: {} for name in iv}

    def add(d, k, t, last, rep, pid):
        e = d.get(k)
        if e is None:
            d[k] = [t, last, rep, {pid: [t, last]}]
            return
        e[0], e[1], e[2] = min(e[0], t), max(e[1], last), e[2] + rep
        q = e[3].get(pid)
        if q is None:
            e[3][pid] = [t, last]
        else:
            q[0], q[1] = min(q[0], t), max(q[1], last)
    for c in ix["chunks"]:
        pid = c["pid"]
        for r in _chunk(spans, c["chunk"]):
            t, dur, rep, k = r[0], r[1], r[6], (r[4], r[5])
            end = t + max(dur, 0) if rep > 1 else t
            add(agg[None], k, t, min(end, end_us), rep, pid)
            i = bisect.bisect_right(starts, t) - 1
            if i >= 0 and t <= segs[i][1]:
                add(agg[segs[i][2]], k, t, min(end, segs[i][1]), rep, pid)
    return {"iv": iv, "agg": agg, "keys": ix["keys"], "truncated": ix.get("truncated") or []}


def edge_times(idx: dict, rd: Path, run: dict, *, open_, phase: str | None = None) -> dict:
    """切面上每条节点间的边在一个阶段（None 是整个 run）里什么时候被调用：
    {"window": [起, 止], "intervals": [(起, 止)…], "span_us": 各段加起来多长,
     "edges": {"a|b": {first, last, n, spread, repeat}}, "truncated"}（微秒，相对 run 起点）。
    模块图的「时间顺序」按 first 排名上色：控制流第一次走到这条边的时刻，讲一条调用链时的先后就是它。
    spread 是同一个进程里第一次到最后一次隔了多久（取各进程里最长的）；repeat（反复调用）要至少 REPEAT_MIN 次、
    而且 spread 超过这段时间的一半——每个进程各调一次的、只调两次的都不算。
    两端落在同一个节点的（节点内部的调用）、import / 类体这种定义时的执行、落不到 index 里的都不算"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（codestrata trace --events）")
    pkey, P = _pairs(spans, run)
    if phase not in P["iv"]:
        raise LookupError(f"这个 run 里没有阶段 {phase} 的时刻：不知道它从什么时候开始，没法按时间排")
    key = (pkey, id(idx), None if open_ is None else ",".join(sorted(open_)), phase)
    with _LOCK:
        hit = _EDGES.get(key)
    if hit is not None and hit[0] is idx:              # 连 idx 一起存：id 不会被重新扫出来的 index 复用
        return hit[1]
    keys, m = P["keys"], _map(idx, open_)
    edges: dict[str, dict] = {}
    pids: dict[str, dict] = {}
    for (a, b), (first, last, n, per) in P["agg"][phase].items():
        na = m.of(keys[a] if 0 <= a < len(keys) else "?")[0]
        nb, defining = m.of(keys[b] if 0 <= b < len(keys) else "?")
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
