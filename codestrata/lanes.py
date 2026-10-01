"""运行时按进程 · 线程分列（P0，用户 2026-10-01 定的展示）：叠了 run 之后，模块图按线程分成并排的几列。

一列（lane）是一个进程里的一类线程：名字归一之后（thread_group：`Thread-3 (save_loop)` → save_loop，线程池的
`ThreadPoolExecutor-3_0…_3` → `ThreadPoolExecutor-3`，`worker-0` → worker）同名的合成一列，记下合了几个（每步新开的 output-builder ×249）。
每列只有这条线程调到的节点（当前切面上的文件 / 目录）和它们之间的边；同一个节点在几列里各有一份。列之间的连线：
  - 共用同一个节点：几列里都有它（前端按节点 id 找，这里不单列）；
  - 谁起了谁（spawn）：线程是在哪一列的哪个节点里 Thread.start 的，子进程是在哪里 exec / fork 出来的（events 的 thread_from、spawns），
    连到被起的那一列的入口节点；
  - 谁把数据交给谁（handoff）：进程内的队列、跨进程的 ZMQ（events 的 handoffs），按 (起点列, 起点节点, 终点列, 终点节点, 通道) 合起来。
数据：时序事件的 span（seq.span_index / pid_rows；带 parent 的才准，老 run 也能出列，只是没有连线）+ 这次 run 的叠加 hot
（录制之后改过的文件走 hot["keymap"]、构造挪到类上走 hot["redirect"]、函数对和代码比的结果 hot["calls"]）。
时间都是微秒、相对 run 起点；只算选的阶段（时间段）里的调用（seq.calls_in）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import align as _align
from . import seq as _seq


_TARGET = re.compile(r"^Thread-\d+ \((.+)\)$")
_NUMBERED = re.compile(r"^(.+?)[-_]\d+$")


def thread_group(name: str) -> str:
    """线程名归一（同一类的合成一列）：`Thread-3 (save_loop)` → save_loop；末尾的 -N / _N 去掉一段
    （worker-0 → worker，ThreadPoolExecutor-3_0 → ThreadPoolExecutor-3，Thread-12 → Thread）"""
    m = _TARGET.match(name)
    if m:
        return m.group(1)
    m = _NUMBERED.match(name)
    return m.group(1) if m else name


def build(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, open_) -> dict:
    """{"phase", "window": [起, 止], "scope", "lanes": [列], "links": [连线]}。列按进程启动的先后排，进程里主线程在前。
    列：{"id": "pid:线程名", "pid", "proc": 进程名, "thread": 归一之后的线程名, "names": 合进来的原名（最多 6 个）,
         "n_threads", "first", "last", "entry": 入口节点,
         "nodes": {节点: {"n": 被调次数, "first"}},
         "edges": [{"a", "b", "n", "only": 其中代码里看不出的（约数）, "first", "last"}],
         "external": 只跑仓库外的代码、因为是交接的一头才有这一列（没有节点）}
    连线：{"kind": "spawn" | "handoff", "via": thread / exec / fork / queue / asyncio / janus / zmq,
           "from": {"lane", "node", "fn", "t"}, "to": {…}, "n", "first", "last",
           "pairs": [{"a": 起点函数, "b": 终点函数, "xa" / "xb": 那一头经仓库外的代码, "da" / "db": 定义 {f, l, k}, "n", "first"}]
           （次数最多的 8 对）, "n_pairs"}
    ——同样两头（列和节点）、同一种的合成一条，n 是几次；from / to 的 t 是最早的一次，first / last 是起点那头的首末时刻；
    fn 是那一头的函数（span 的被调方；放 / 取发生在仓库外的代码里时是这条线程入口的仓库函数，ext 为真）。
    还有 "truncated": [时序事件录到了上限的进程]。没有时序事件、没有这个阶段的时刻抛 LookupError"""
    ix = _seq.span_index(rd)
    segs, win, end = _seq.window_segments(run, rd, phase)
    lo, hi = segs[0][0], segs[-1][1]
    m = _seq.cut_map(idx, open_)
    keys, threads = ix["keys"], ix["threads"]
    keymap, redirect = hot.get("keymap"), hot.get("redirect") or {}
    label = _labeler(idx)
    share = _only_share(hot, label)
    names = proc_names(rd)
    node_cache: dict[int, tuple] = {}
    fn_cache: dict[int, str | None] = {}

    def fn_of(a: int) -> str | None:
        """键下标 → 函数级的节点（file#Qual），落不到函数上是 None"""
        if a not in fn_cache:
            ka = keys[a] if 0 <= a < len(keys) else "?"
            fn_cache[a] = label(keymap(ka) if keymap is not None else ka) if ka != "?" else None
        return fn_cache[a]

    def nodes_of(a: int, b: int):
        """span 两端的键下标 → (调用方节点, 被调方节点, 被调方是不是定义时的执行, 这对函数代码里看不出的比例)"""
        ka, kb = keys[a] if 0 <= a < len(keys) else "?", keys[b] if 0 <= b < len(keys) else "?"
        if keymap is not None:
            ka, kb = keymap(ka), keymap(kb)
        to = redirect.get(f"{ka}|{kb}")
        na = m.of(ka)[0]
        nb, defining = (m.file_node(m.syms[to]["f"]), False) if to and to in m.syms else m.of(kb)
        return na, nb, defining, share(ka, kb)

    def node(a: int) -> str | None:
        hit = node_cache.get(a)
        if hit is None:
            ka = keys[a] if 0 <= a < len(keys) else "?"
            hit = node_cache[a] = (m.of(keymap(ka) if keymap is not None else ka)[0],)
        return hit[0]

    lanes: dict[str, dict] = {}
    rows_of: dict[int, list] = {}
    tid_lane: dict[tuple, str] = {}
    roots: dict[str, tuple] = {}                 # 列 → (最早的深度 0 的 span 的开始, 它的调用方函数)：线程的入口，不限这一段
    for pid in dict.fromkeys(c["pid"] for c in ix["chunks"]):
        rows = rows_of[pid] = _seq.pid_rows(rd, pid)
        tnames = threads.get(str(pid)) or {}
        for r in rows:
            got = None
            for i, (a, b) in enumerate(segs):
                got = _seq.calls_in(r[0], r[1], r[6], a, b, open_hi=not win and (i + 1 < len(segs) or b < end))
                if got:
                    break
            raw = tnames.get(str(r[2])) or f"线程 {r[2]}"
            tname = thread_group(raw)
            lid = f"{pid}:{tname}"
            tid_lane[(pid, r[2])] = lid
            if r[3] == 0 and (lid not in roots or r[0] < roots[lid][0]):
                roots[lid] = (r[0], r[4])
            if not got:
                continue
            n, first, last = got
            na, nb, defining, only = nodes_of(r[4], r[5])
            if na is None or nb is None or defining:
                continue
            L = lanes.get(lid)
            if L is None:
                L = lanes[lid] = {"id": lid, "pid": pid, "proc": names.get(pid) or f"pid {pid}", "thread": tname,
                                  "names": set(), "tids": set(), "first": first, "last": last, "entry": None,
                                  "entry_fn": None, "entry_t": None, "nodes": {}, "edges": {}}
            L["tids"].add(r[2])
            L["names"].add(raw)
            L["first"], L["last"] = min(L["first"], first), max(L["last"], last)
            if r[3] == 0 and (L["entry_t"] is None or first < L["entry_t"]):
                L["entry"], L["entry_fn"], L["entry_t"] = na, fn_of(r[4]), first
            for x, cnt in ((na, 0), (nb, n)):
                v = L["nodes"].get(x)
                if v is None:
                    L["nodes"][x] = {"n": cnt, "first": first}
                else:
                    v["n"] += cnt
                    v["first"] = min(v["first"], first)
            if na != nb:
                e = L["edges"].get((na, nb))
                if e is None:
                    L["edges"][(na, nb)] = {"a": na, "b": nb, "n": n, "only": n * only, "first": first, "last": last}
                else:
                    e["n"] += n
                    e["only"] += n * only
                    e["first"], e["last"] = min(e["first"], first), max(e["last"], last)

    def end_of(pid: int, tid: int, row: int, t: int | None, create: bool = False) -> dict | None:
        """一条连线的一头：哪一列、哪个节点（span 的被调方；不在任何 span 里就是这一列的入口）。只跑仓库外代码的线程
        （vLLM 收发 ZMQ 的线程）没有列：create（交接的两头）时给它一列空的（external），交接链才不断"""
        lid = tid_lane.get((pid, tid))
        raw = (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
        if lid is None:
            lid = tid_lane[(pid, tid)] = f"{pid}:{thread_group(raw)}"
        if lid not in lanes:
            if not create or t is None:
                return None
            lanes[lid] = {"id": lid, "pid": pid, "proc": names.get(pid) or f"pid {pid}", "thread": lid.partition(":")[2],
                          "names": set(), "tids": {tid}, "first": t, "last": t, "entry": None, "entry_fn": None,
                          "entry_t": None, "nodes": {}, "edges": {}, "external": True}
        L = lanes[lid]
        if L.get("external") and t is not None:
            L["tids"].add(tid)
            L["names"].add(raw)
            L["first"], L["last"] = min(L["first"], t), max(L["last"], t)
        rows = rows_of.get(pid) or []
        r = rows[row] if 0 <= row < len(rows) else None
        nd = node(r[5]) if r else None
        # 不在任何 span 里（放 / 取发生在仓库外的代码里，比如 vLLM 引擎循环取请求）：记这条线程入口的那个仓库函数，标 ext
        fn = fn_of(r[5]) if r else lanes[lid]["entry_fn"] or (fn_of(roots[lid][1]) if lid in roots else None)
        return {"lane": lid, "node": nd or lanes[lid]["entry"], "fn": fn, "ext": r is None,
                "t": t if t is not None else (r[0] if r else None)}

    agg: dict[tuple, dict] = {}                  # 同样两头、同一种的连线合起来：(起点列, 起点节点, 终点列, 终点节点, 种类, 通道)

    def link(kind: str, via: str, a: dict, b: dict) -> None:
        k = (a["lane"], a["node"], b["lane"], b["node"], kind, via)
        x = agg.get(k)
        t = a["t"] if a["t"] is not None else b["t"]
        if x is None:
            x = agg[k] = {"kind": kind, "via": via, "from": a, "to": b, "n": 1, "first": t, "last": t, "pairs": {}}
        else:
            x["n"] += 1
            for end, new in (("from", a), ("to", b)):  # 时刻取最早的一次
                if new["t"] is not None and (x[end]["t"] is None or new["t"] < x[end]["t"]):
                    x[end] = new
            if t is not None:
                x["first"] = t if x["first"] is None else min(x["first"], t)
                x["last"] = t if x["last"] is None else max(x["last"], t)
        pr = x["pairs"].setdefault((a["fn"], b["fn"], a.get("ext", False), b.get("ext", False)), [0, t])
        pr[0] += 1
        if t is not None and (pr[1] is None or t < pr[1]):
            pr[1] = t

    for pid, by_tid in (ix.get("thread_from") or {}).items():
        for tid, (ftid, frow) in by_tid.items():
            a, b = end_of(int(pid), ftid, frow, None), _lane_start(lanes, tid_lane.get((int(pid), int(tid))))
            if a and b and a["lane"] != b["lane"]:
                link("spawn", "thread", a, b)
    for s in ix.get("spawns") or []:
        a = end_of(s["pid"], s["tid"], s["row"], s.get("t_us"))
        main = min((lid for (p, _), lid in tid_lane.items() if p == s["child"] and lid in lanes),
                   key=lambda lid: lanes[lid]["first"], default=None)
        b = _lane_start(lanes, main)
        if a and b:
            link("spawn", s["how"], a, b)
    for h in ix.get("handoffs") or []:
        t = h["to"][3]
        if not any(x <= t <= y for x, y in segs):
            continue
        a, b = end_of(*h["from"], create=True), end_of(*h["to"], create=True)
        if a and b and a["lane"] != b["lane"]:
            link("handoff", h["via"], a, b)
    links = list(agg.values())
    for x in links:
        prs = sorted(x["pairs"].items(), key=lambda kv: (-kv[1][0], kv[1][1] if kv[1][1] is not None else 0))
        x["n_pairs"] = len(prs)
        x["pairs"] = [{"a": fa, "b": fb, "xa": xa, "xb": xb, "n": n, "first": f,
                       "da": _align.node_def(idx, fa) if fa else None, "db": _align.node_def(idx, fb) if fb else None}
                      for (fa, fb, xa, xb), (n, f) in prs[:8]]

    out = []
    for L in lanes.values():
        L["n_threads"] = len(L.pop("tids"))
        L["names"] = sorted(L["names"])[:6]
        L.pop("entry_t")
        L.pop("entry_fn")
        L["edges"] = sorted(L["edges"].values(), key=lambda e: e["first"])
        for e in L["edges"]:
            e["only"] = round(e["only"])
        out.append(L)
    # 进程按启动的先后（父进程在前；按第一次调用排的话，一开机就在轮询的进程会排到最前面），进程里按交接的顺序（_order）
    pstart: dict[int, int] = {}
    for p in ix.get("procs") or []:
        pstart[p["pid"]] = min(pstart.get(p["pid"], p["t0_us"]), p["t0_us"])
    rank = _order(out, links, pstart)
    out.sort(key=lambda L: (pstart.get(L["pid"], L["first"]), L["pid"], rank[L["id"]]))
    links.sort(key=lambda x: (x["from"]["t"] if x["from"]["t"] is not None else 0))
    return {"phase": phase, "window": [lo, hi], "scope": ix.get("scope") or "cross", "truncated": ix.get("truncated") or [],
            "lanes": out, "links": links}


def _order(lanes: list, links: list, pstart: dict) -> dict:
    """进程里各列的先后（用户 2026-10-01 定：按交接的顺序）：从入口那一列顺着进程里的交接走——vLLM 的 stage 是
    收请求 → 主循环 → 输出线程；入口是第一个从别的进程收到交接的那一列，最早启动的进程（没有谁交给它）是主线程。
    没走到的放后面：主线程在前，其余按第一次活动。返回 {列: 名次}"""
    by_pid: dict[int, list] = {}
    for L in lanes:
        by_pid.setdefault(L["pid"], []).append(L)
    root = min(by_pid, key=lambda p: pstart.get(p, 0)) if by_pid else None
    hand = sorted((x for x in links if x["kind"] == "handoff"), key=lambda x: x["to"]["t"] or 0)
    pid_of = {L["id"]: L["pid"] for L in lanes}
    rank: dict[str, int] = {}
    for pid, ls in by_pid.items():
        main = next((L["id"] for L in ls if L["thread"] == "MainThread"), None)
        entry = main if pid == root else next(
            (x["to"]["lane"] for x in hand if pid_of.get(x["to"]["lane"]) == pid and pid_of.get(x["from"]["lane"]) != pid), main)
        seq: list[str] = []
        todo = [entry] if entry else []
        while todo:
            cur = todo.pop(0)
            if cur in seq:
                continue
            seq.append(cur)
            todo.extend(x["to"]["lane"] for x in hand if x["from"]["lane"] == cur and pid_of.get(x["to"]["lane"]) == pid)
        rest = sorted((L for L in ls if L["id"] not in seq), key=lambda L: (L["thread"] != "MainThread", L["first"]))
        for i, lid in enumerate(seq + [L["id"] for L in rest]):
            rank[lid] = i
    return rank


def _lane_start(lanes: dict, lid: str | None) -> dict | None:
    """被起的那一列的入口：线程的入口函数在哪个节点"""
    if lid is None or lid not in lanes:
        return None
    L = lanes[lid]
    return {"lane": lid, "node": L["entry"] or next(iter(L["nodes"]), None), "fn": L["entry_fn"], "t": L["first"]}


def _labeler(idx: dict):
    """键 rel:行 → graph 的函数级节点（file#Qual）"""
    syms = idx.get("symbols") or {}
    loc2sym, spans = _align.sym_locs(syms)
    return _align.node_labeler(idx, loc2sym, spans)


def _only_share(hot: dict, label):
    """(调用方键, 被调方键) → 这对函数的调用里代码里看不出的比例（hot["calls"] 按函数对算的，不分线程）"""
    calls = hot.get("calls") or {}
    memo: dict[tuple, float] = {}

    def share(ka: str, kb: str) -> float:
        k = (ka, kb)
        v = memo.get(k)
        if v is None:
            x = calls.get(f"{label(ka)}|{label(kb)}")
            v = memo[k] = (x["only"] / x["n"]) if x and x.get("n") else 0.0
        return v
    return share


def proc_names(rd: Path) -> dict[int, str]:
    """进程的名字：改过的进程标题（vLLM 的 VLLM::StageEngineCoreProc_stage0_…），没有就用命令里的脚本名"""
    try:
        procs = json.loads((rd / "detail.json").read_text(encoding="utf-8")).get("procs") or []
    except (OSError, ValueError):
        return {}
    out = {}
    for p in procs:
        title = (p.get("title") or "").removeprefix("VLLM::")
        argv = p.get("argv") or []
        script = next((Path(a).name for a in argv[1:] if a.endswith(".py")), None)
        mod = argv[argv.index("-m") + 1] if "-m" in argv[:-1] else None
        out[p["pid"]] = title or script or (f"-m {mod}" if mod else Path(argv[0]).name if argv else "")
    return out
