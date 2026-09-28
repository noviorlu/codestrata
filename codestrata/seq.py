"""时序图的数据：一个 run 的 span（events.py 整理好的）→ 当前切面上的消息序列。

span 记的是「文件:首行号 → 文件:首行号」的跨文件调用；时序图画的是切面上的节点之间的消息。
所以这里每次请求现算（依赖切面，和模块图一样）：

  1. 取时间窗里的 span（按块读，解压过的块放进 LRU）。
  2. 两端经 rel → 单元 → 切面节点（cut.view 的 node_of）映射；两端落在同一个节点的不画
     （节点内部的调用），import 触发的模块顶层执行不画（模块图也不把它算作调用），落不到
     index 里的（scan 排除了的 examples 等）也不画，都只计数。
  3. 生命线 = (进程, 切面节点)：按进程分组，组内按架构高度从高到低（和模块图从上到下一致）。
  4. 画得下就不折；画不下才把同一线程的消息按 (调用方节点, 被调方节点, 被调函数) 转成记号，
     从左到右贪心地找周期 p ≤ 8、至少重复 3 次的片段，折成一行「loop ×N」；点开时请求那一段、
     而且不折（fold=False），长的分屏看。
  5. 折完还超过上限不静默截断：返回 too_dense 和一个建议的时间窗。「下一屏」从 next_t0 接着看；
     同一微秒里的几次调用不会被拆到两屏。
  6. 相邻两行间隔超过 50 ms 插一行「空闲」；子进程在它起来的时刻从父进程画一条派生。

时间一律是相对 run 起点（run.json 的 clock.mono0_ns）的微秒，和阶段的 t_us 同一根轴。
"""
from __future__ import annotations

import gzip
import json
import threading
from collections import OrderedDict
from pathlib import Path

from . import cut as _cut

MAX_ROWS = 300
MAX_ROWS_HARD = 2000
IDLE_US = 50_000
LOOP_P = 8
LOOP_MIN = 3
BINS = 400
ESTIMATE_X = 60          # 给定窗口里的 span 超过 max_rows 的这么多倍：不整段折叠，按自动收窄估

_LOCK = threading.Lock()
_CHUNKS: "OrderedDict[tuple, list]" = OrderedDict()     # (chunk 路径, mtime) → 解压好的行
_INDEX: "OrderedDict[tuple, dict]" = OrderedDict()     # (spans 目录, index mtime) → index + keys（最近 16 个）
_OVER: "OrderedDict[tuple, dict]" = OrderedDict()      # (spans 目录, index mtime) → overview（最近 16 个）


def _put(cache: OrderedDict, key, val, cap: int = 16):
    with _LOCK:
        cache[key] = val
        cache.move_to_end(key)
        while len(cache) > cap:
            cache.popitem(last=False)


# ---------------------------------------------------------------- 读 span

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


def _chunk(spans: Path, name: str, cache: bool = True) -> list:
    p = spans / name
    key = (str(p), p.stat().st_mtime_ns)
    with _LOCK:
        rows = _CHUNKS.get(key)
        if rows is not None:
            _CHUNKS.move_to_end(key)
            return rows
    rows = [json.loads(ln) for ln in gzip.decompress(p.read_bytes()).decode().splitlines() if ln]
    if not cache:                                    # 整个 run 扫一遍（概览）：不挤掉正在看的那几块
        return rows
    with _LOCK:
        _CHUNKS[key] = rows
        while len(_CHUNKS) > 16:
            _CHUNKS.popitem(last=False)
    return rows


def spans_in(spans: Path, t0: int, t1: int) -> list[tuple]:
    """时间窗 [t0, t1] 里开始的 span：[(pid, t0, dur, tid, depth, a, b, rep, n_susp)]，按开始时刻排好。"""
    ix = _index(spans)
    out = []
    for c in ix["chunks"]:
        # 块里的行按开始时刻排好；t1_us 不小于块里任何一行的开始时刻（没返回的按开始算）
        if c["t0_us"] > t1 or c["t1_us"] < t0:
            continue
        for r in _chunk(spans, c["chunk"]):
            if t0 <= r[0] <= t1:
                out.append((c["pid"], *r))
    out.sort(key=lambda r: (r[1], r[4]))
    return out


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
    """键 rel:行 → (切面节点, 函数名)。一个 (idx, 切面) 算一次（_map 缓存）。"""

    def __init__(self, idx: dict, open_):
        self.v = _cut.view(idx, set(open_) if open_ is not None else set(idx.get("default_open") or []))
        self.files = idx.get("files") or {}
        self.node_of = self.v["node_of"]
        loc: dict[tuple, str] = {}
        spans: dict[str, list] = {}
        self.syms = idx.get("symbols") or {}
        for k, s in self.syms.items():
            loc.setdefault((s["f"], s["l"]), k)
            if "dl" in s:
                loc.setdefault((s["f"], s["dl"]), k)
            if s.get("e"):
                spans.setdefault(s["f"], []).append((s.get("dl", s["l"]), s["e"], k))
        self.loc, self.sspans = loc, spans
        self._memo: dict[str, tuple] = {}

    def of(self, key: str) -> tuple:
        """(节点 或 None, 显示名, 符号键 或 None, rel, 行)"""
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        rel, _, ln = key.rpartition(":")
        try:
            line = int(ln)
        except ValueError:
            line = 0
        unit = self.files.get(rel)
        node = self.node_of.get(unit) if unit else None
        sk = None if line == 0 else self.loc.get((rel, line))
        if sk:
            name = self.syms[sk]["n"]
        elif line == 0:
            name = "<module>"
        else:
            inner = max((s for s in self.sspans.get(rel, ()) if s[0] <= line <= s[1]),
                        key=lambda s: s[0], default=None)
            name = f"{self.syms[inner[2]]['n']}.<L{line}>" if inner else f"<L{line}>"
        hit = (node, name, sk, rel, line)
        self._memo[key] = hit
        return hit


# ---------------------------------------------------------------- 折叠、出图

def _messages(raw: list[tuple], keys: list[str], m: _Map) -> tuple[list[dict], list[tuple]]:
    """span → 消息（两端落在不同节点上的）。没画的也按时刻记下来（t, 为什么, 次数），
    窗口收窄之后才好按真正显示的那一段数：internal 节点内部、imports import 触发的模块顶层执行
    （模块图也不把它算作调用）、unmapped 落在 index 之外的文件上。"""
    out, skipped = [], []
    for pid, t0, dur, tid, depth, a, b, rep, n_susp in raw:
        ka, kb = keys[a] if 0 <= a < len(keys) else "?", keys[b] if 0 <= b < len(keys) else "?"
        na, nameA, _, _, _ = m.of(ka)
        nb, nameB, skB, relB, lineB = m.of(kb)
        if na is None or nb is None:
            skipped.append((t0, "unmapped", rep))
        elif lineB == 0:
            skipped.append((t0, "imports", rep))
        elif na == nb:
            skipped.append((t0, "internal", rep))
        else:
            out.append({"t": t0, "d": dur, "pid": pid, "tid": tid, "depth": depth, "a": na, "b": nb,
                        "fa": nameA, "fb": nameB, "sym": skB, "f": relB, "l": lineB, "rep": rep,
                        "async": n_susp > 0, "susp": n_susp})
    return out, skipped


def _stat(skipped: list[tuple], t0: int, hi: int) -> dict:
    st = {"internal": 0, "imports": 0, "unmapped": 0}
    for t, why, rep in skipped:
        if t0 <= t <= hi:
            st[why] += rep
    return st


def _fold_loops(msgs: list[dict]) -> list[dict]:
    """同一 (pid, tid) 上的消息找重复的片段折成一行。msgs 已按时间排好；返回的行也按时间排好。
    记号是 (调用方节点, 被调方节点, 被调函数的文件和行)——不用显示名：不同文件里同名的函数、
    不同模块的 <module> 不能当成同一个调用。"""
    by: dict[tuple, list[int]] = {}
    for i, x in enumerate(msgs):
        by.setdefault((x["pid"], x["tid"]), []).append(i)
    covered: dict[int, dict] = {}                 # 第一条消息的下标 → loop 行
    skip: set[int] = set()
    for (pid, tid), ids in by.items():
        tok = [(msgs[i]["a"], msgs[i]["b"], msgs[i]["f"], msgs[i]["l"]) for i in ids]
        n, i = len(tok), 0
        while i < n:
            best = None                            # (覆盖的条数, 周期, 重复次数)
            for p in range(1, LOOP_P + 1):
                if i + p * LOOP_MIN > n:
                    break
                k = 1
                while i + (k + 1) * p <= n and tok[i + k * p:i + (k + 1) * p] == tok[i:i + p]:
                    k += 1
                if k >= LOOP_MIN and (best is None or p * k > best[0]):
                    best = (p * k, p, k)
            if best is None:
                i += 1
                continue
            cover, p, k = best
            first, last = ids[i], ids[i + cover - 1]
            body = [msgs[j] for j in ids[i:i + p]]
            end = max(msgs[j]["t"] + max(msgs[j]["d"], 0) for j in ids[i:i + cover])
            covered[first] = {"k": "loop", "t": msgs[first]["t"], "d": end - msgs[first]["t"], "pid": pid,
                              "tid": tid, "n": k, "p": p, "rep": sum(msgs[j]["rep"] for j in ids[i:i + cover]),
                              "body": body, "t1": msgs[last]["t"]}
            skip.update(ids[i:i + cover])
            i += cover
    rows = []
    for i, x in enumerate(msgs):
        if i in covered:
            rows.append(covered[i])
        elif i not in skip:
            rows.append({"k": "m", **x})
    return rows


def _with_idle(rows: list[dict]) -> list[dict]:
    """相邻两行间隔超过 IDLE_US 时插一行「空闲」。消息按开始时刻算，loop 按它结束的时刻算。"""
    out, prev = [], None
    for r in rows:
        if prev is not None and r["t"] - prev > IDLE_US:
            out.append({"k": "idle", "t": prev, "d": r["t"] - prev})
        out.append(r)
        cur = r["t"] + max(r.get("d") or 0, 0) if r["k"] == "loop" else r["t"]
        prev = cur if prev is None else max(prev, cur)
    return out


def _plain(msgs: list[dict]) -> list[dict]:
    return _with_idle([{"k": "m", **x} for x in msgs])


def _rows(msgs: list[dict], max_rows: int, fold: bool = True) -> list[dict]:
    """画得下就不折（三次请求也是三次，折成 loop ×3 反而看不出结构）；画不下才折循环。
    fold=False（点开一个 loop 时）：一律不折。"""
    plain = _plain(msgs)
    return plain if (len(plain) <= max_rows or not fold) else _with_idle(_fold_loops(msgs))


def _fit(msgs: list[dict], max_rows: int, fold: bool = True) -> int:
    """最长的前缀，折叠（fold=False 时不折）、插空闲后不超过 max_rows 行（行数随前缀单调不减，二分）；
    再退到时刻的边界上——同一微秒里的几次调用不能一半在这一屏、一半在下一屏（下一屏从这一屏
    最后一条之后开始，会把另一半漏掉）。一个时刻的调用多到一屏放不下时，整组都放进来。"""
    count = (lambda k: len(_with_idle(_fold_loops(msgs[:k])))) if fold else (lambda k: len(_plain(msgs[:k])))
    lo, hi = 0, len(msgs)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count(mid) <= max_rows:
            lo = mid
        else:
            hi = mid - 1
    def snap(n):
        while 0 < n < len(msgs) and msgs[n]["t"] == msgs[n - 1]["t"]:
            n -= 1
        return n
    n = snap(lo)
    # 贪心折叠的行数并不严格随前缀单调（前缀多一条，可能正好凑成一个 loop、行数反而少了）：
    # 退到时刻边界之后再核一遍，超了就再往回退（有上限，退不动就算了）
    for _ in range(64):
        if n <= 1 or count(n) <= max_rows:
            break
        n = snap(n - 1)
    if n == 0 and msgs:
        n = 1
        while n < len(msgs) and msgs[n]["t"] == msgs[0]["t"]:
            n += 1
    return n


def _proc_label(argv: list[str] | None, title: str | None) -> str:
    if title:
        return title
    a = [x for x in (argv or []) if x]
    if not a:
        return "?"
    short = [a[0].rsplit("/", 1)[-1]] + a[1:]
    if short[0].startswith("python") and len(short) > 1:
        short = short[1:]
        if short[0] == "-m" and len(short) > 1:
            short = short[1:]
    return " ".join(short)[:80]


def _procs(detail: dict) -> dict:
    """pid → 进程信息。exec 前后是同一个 pid 的两个映像：起始时刻和父进程取最早的那个（fork 的
    时刻），命令和标题取最后那个（exec 之后真正在跑的程序）。"""
    out: dict[int, dict] = {}
    for p in sorted((p for p in detail.get("procs") or [] if p.get("pid") is not None),
                    key=lambda p: (p.get("t0_us") is None, p.get("t0_us") or 0)):
        q = out.get(p["pid"])
        if q is None:
            out[p["pid"]] = dict(p)
        else:
            q.update({k: p.get(k) for k in ("argv", "title", "t1_us") if p.get(k) is not None})
    return out


def _grow(spans: Path, keys, m, t0: int, limit: int, max_rows: int, fold: bool):
    """从 t0 开始、窗口逐步放宽（每次 ×4），直到放不下或到了 limit，返回 (消息, 没画的, 窗口右端)。
    serving 阶段有几十万次跨文件调用，不能一次全读进来折叠。"""
    width = 200_000
    while True:
        hi = min(limit, t0 + width)
        msgs, skipped = _messages(spans_in(spans, t0, hi), keys, m)
        if hi >= limit or len(_rows(msgs, max_rows, fold)) > max_rows:
            return msgs, skipped, hi
        width *= 4


def build(repo: Path, idx: dict, rd: Path, run: dict, detail: dict, *, open_=None, t0: int | None = None,
          t1: int | None = None, phase: str | None = None, max_rows: int = MAX_ROWS, fold: bool = True) -> dict:
    """一个时间窗的时序图数据。
      没给 t1：从 t0（或阶段起点）开始，自动收窄到折叠后不超过 max_rows 行；
      给了 t1：就看这一段，折叠后还放不下时不截断，返回 too_dense 和一个建议的窗口；
      fold=False（点开一个 loop）：不折，放不下就只给前 max_rows 行，其余用 next_t0 接着看。
    next_t0 是这一屏之后的第一条消息的时刻（「下一屏」从这里开始；到头了是 None）。"""
    spans = rd / "events" / "spans"
    if not (spans / "index.json").is_file():
        raise LookupError("这个 run 没有录时序事件（codestrata trace --events）")
    ix = _index(spans)
    keys = ix["keys"]
    max_rows = max(20, min(MAX_ROWS_HARD, int(max_rows)))
    phases = run.get("phases") or []
    bounds = [(p["name"], p.get("t_us")) for p in phases if p.get("t_us") is not None]
    end_all = max((c["t1_us"] for c in ix["chunks"]), default=0)
    limit = end_all                                  # 自动收窄时最远到哪：阶段的终点
    if t0 is None:
        t0 = 0
        names = [n for n, _ in bounds]
        if phase in names:
            i = names.index(phase)
            t0 = bounds[i][1]
            limit = bounds[i + 1][1] if i + 1 < len(bounds) else end_all
    m = _map(idx, open_)
    auto = t1 is None
    too_dense = None
    more = False                                     # 窗口右边还有没显示的消息
    if auto:
        msgs, skipped, hi = _grow(spans, keys, m, t0, limit, max_rows, fold)
        n = _fit(msgs, max_rows, fold)
        if n < len(msgs):
            msgs, more = msgs[:n], True
            hi = msgs[-1]["t"] if msgs else t0
        rows = _rows(msgs, max_rows, fold)
    else:
        hi = max(t0, min(t1, end_all))
        raw = spans_in(spans, t0, hi)
        if len(raw) > max_rows * ESTIMATE_X or not fold:
            # 很多：不把整段都折一遍（几十万条要好几秒、几百 MB）——按自动收窄的办法从 t0 往后放宽，
            # 到 hi 为止。放宽到 hi 都画得下（画的只是跨节点的那些），就照常出图；画不下：
            #   折叠时给建议的窗口；不折叠（点开的 loop）时给前一屏，其余用 next_t0 接着看
            msgs, skipped, g_hi = _grow(spans, keys, m, t0, hi, max_rows, fold)
            n = _fit(msgs, max_rows, fold)
            if g_hi >= hi and n == len(msgs):
                rows = _rows(msgs, max_rows, fold)
            elif fold:
                too_dense = {"rows": None, "calls": len(raw), "suggest": [t0, msgs[n - 1]["t"] if n else t0],
                             "estimate": True}
                msgs, rows = [], []
            else:
                msgs, more = msgs[:n], True
                hi = msgs[-1]["t"] if msgs else t0
                rows = _rows(msgs, max_rows, fold)
        else:
            msgs, skipped = _messages(raw, keys, m)
            rows = _rows(msgs, max_rows, fold)
            if len(rows) > max_rows:
                n = _fit(msgs, max_rows, fold)
                if fold:
                    # 给定的窗口太密：不截断，建议一个画得下的窗口（从 t0 起，按同样的办法收窄）
                    too_dense = {"rows": len(rows), "suggest": [t0, msgs[n - 1]["t"] if n else t0]}
                    msgs, rows = [], []
                else:
                    # 点开的 loop 太长：给前面一屏，其余接着看
                    msgs, more = msgs[:n], True
                    hi = msgs[-1]["t"] if msgs else t0
                    rows = _rows(msgs, max_rows, fold)
    next_t0 = (msgs[-1]["t"] + 1) if (more and msgs) else (hi + 1 if hi < end_all else None)
    if next_t0 is not None and next_t0 > end_all:
        next_t0 = None
    stat = _stat(skipped, t0, hi)
    # 生命线：窗口里出现过的 (进程, 节点)
    procs = _procs(detail)
    alt = {n: x.get("alt", 0) for n, x in m.v["nodes"].items()}
    used: dict[tuple, int] = {}

    def lane(pid, node):
        k = (pid, node)
        if k not in used:
            used[k] = len(used)
        return used[k]
    for r in rows:
        if r["k"] == "m":
            r["from"], r["to"] = lane(r["pid"], r["a"]), lane(r["pid"], r["b"])
        elif r["k"] == "loop":
            for x in r["body"]:
                x["from"], x["to"] = lane(x["pid"], x["a"]), lane(x["pid"], x["b"])
    # 同一 argv 的进程按启动先后编号 #1…#n
    argv_seen: dict[str, list] = {}
    for pid, p in sorted(procs.items(), key=lambda kv: (kv[1].get("t0_us") or 0)):
        argv_seen.setdefault(_proc_label(p.get("argv"), None), []).append(pid)
    pinfo = []
    lane_pids = sorted({pid for pid, _ in used}, key=lambda pid: (procs.get(pid, {}).get("t0_us") or 0, pid))
    pos = {pid: i for i, pid in enumerate(lane_pids)}
    from .runs import _redact_argv           # 页面上显示的命令行：--api-key 的值、URL 里的密码隐去（同 runs.load）
    for pid in lane_pids:
        p = procs.get(pid, {})
        argv = _redact_argv(p.get("argv") or [])
        lab = _proc_label(argv, p.get("title"))
        same = argv_seen.get(_proc_label(p.get("argv"), None), [])
        pinfo.append({"pid": pid, "ppid": p.get("ppid"),
                      "label": lab + (f" #{same.index(pid) + 1}" if len(same) > 1 and pid in same else ""),
                      "argv": argv, "t0_us": p.get("t0_us"), "t1_us": p.get("t1_us")})
    order = sorted(used, key=lambda k: (pos[k[0]], -alt.get(k[1], 0), k[1]))
    remap = {used[k]: i for i, k in enumerate(order)}
    for r in rows:
        if r["k"] == "m":
            r["from"], r["to"] = remap[r["from"]], remap[r["to"]]
        elif r["k"] == "loop":
            for x in r["body"]:
                x["from"], x["to"] = remap[x["from"]], remap[x["to"]]
    lifelines = [{"pid": pid, "node": node, "alt": alt.get(node, 0), "kind": _cut.kind(idx, node)} for pid, node in order]
    # 派生：窗口里起来的子进程（fork 的时刻），父进程也在图上时画一条
    on = {q["pid"] for q in pinfo}
    spawns = [{"k": "spawn", "t": p["t0_us"], "pid": p["pid"], "ppid": p["ppid"]} for p in pinfo
              if p.get("t0_us") is not None and t0 <= p["t0_us"] <= hi and p.get("ppid") in on]
    if spawns and rows:
        rows = sorted(rows + spawns, key=lambda r: r["t"])
    return {"window": [t0, hi], "auto": auto, "fold": fold, "phases": [{"name": n, "t_us": t} for n, t in bounds],
            "end_us": end_all, "next_t0": next_t0, "procs": pinfo, "lifelines": lifelines, "rows": rows,
            "stat": {**stat, "messages": len(msgs), "rows": len(rows)}, "too_dense": too_dense,
            "truncated": ix.get("truncated") or []}


def overview(rd: Path, bins: int = BINS) -> dict:
    """每个进程在整个 run 上的跨文件调用密度（bins 格），时间刷用。按 index 的 mtime 缓存。"""
    spans = rd / "events" / "spans"
    ix = _index(spans)
    key = (str(spans), (spans / "index.json").stat().st_mtime_ns, bins)
    with _LOCK:
        hit = _OVER.get(key)
    if hit is not None:
        return hit
    end = max((c["t1_us"] for c in ix["chunks"]), default=0) or 1
    width = end / bins
    dens: dict[int, list] = {}
    for c in ix["chunks"]:
        row = dens.setdefault(c["pid"], [0] * bins)
        for r in _chunk(spans, c["chunk"], cache=False):
            row[min(bins - 1, int(r[0] / width))] += r[6]
    out = {"end_us": end, "bins": bins, "procs": [{"pid": pid, "density": d} for pid, d in dens.items()]}
    _put(_OVER, key, out)
    return out


def find(idx: dict, rd: Path, *, open_, a: str, b: str, after: int = -1,
         window: tuple | None = None) -> dict | None:
    """切面上 a → b 这条边在 after 之后第一次出现的时刻（边详情里「在时序图里看」）。
    window=(t0, t1)（当前阶段）：先在这一段里找，没有再在整个 run 里找。import 触发的模块顶层执行
    不算（模块图上也不把它当调用）。"""
    spans = rd / "events" / "spans"
    ix = _index(spans)
    keys = ix["keys"]
    m = _map(idx, open_)

    def scan(lo, hi):
        best = None
        for c in ix["chunks"]:
            if c["t1_us"] <= lo or c["t0_us"] > hi or (best is not None and c["t0_us"] >= best["t"]):
                continue
            for r in _chunk(spans, c["chunk"]):
                if r[0] <= lo:
                    continue
                if r[0] > hi or (best is not None and r[0] >= best["t"]):
                    break
                ka = keys[r[4]] if 0 <= r[4] < len(keys) else "?"
                kb = keys[r[5]] if 0 <= r[5] < len(keys) else "?"
                if kb.endswith(":0"):
                    continue
                if m.of(ka)[0] == a and m.of(kb)[0] == b:
                    best = {"t": r[0], "pid": c["pid"], "tid": r[2], "d": r[1]}
                    break
        return best
    if window:
        hit = scan(max(after, window[0] - 1), window[1])
        if hit:
            return hit
    return scan(after, float("inf"))
