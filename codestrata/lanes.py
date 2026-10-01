"""运行时按进程 · 线程分列（P0，用户 2026-10-01 定的展示）：叠了 run 之后，模块图按线程分成并排的几列。

一列（lane）是一个进程里的一类线程：名字归一之后（thread_group：`Thread-3 (save_loop)` → save_loop，线程池的
`ThreadPoolExecutor-3_0…_3` → `ThreadPoolExecutor-3`，`worker-0` → worker）同名的合成一列，记下合了几个（每步新开的 output-builder ×249）。
每列只有这条线程调到的节点（当前切面上的文件 / 目录）和它们之间的边；同一个节点在几列里各有一份。列之间的连线：
  - 共用同一个节点：几列里都有它（前端按节点 id 找，这里不单列）；
  - 谁起了谁（spawn）：线程是在哪一列的哪个节点里 Thread.start 的，子进程是在哪里 exec / fork 出来的（events 的 thread_from、spawns），
    连到被起的那一列的入口节点；
  - 谁把数据交给谁（handoff）：进程内的队列、跨进程的 ZMQ（events 的 handoffs），按 (起点列, 起点节点, 终点列, 终点节点, 通道) 合起来；
  - 谁回收了谁（join）：线程是在哪一列的哪个节点里被 join 等到结束的，子进程是在哪里被 waitpid 等到退出的（events 的
    thread_end、reaps），从被回收的那一列的入口节点连过去。
每一头都带着那一行代码（起线程、放 / 取、发 / 收、join 的那一行）。每列还有起止的摘要（start / stop）。
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


def build(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, open_, text=None) -> dict:
    """{"phase", "window": [起, 止], "scope", "lanes": [列], "links": [连线]}。列按进程启动的先后排，进程里主线程在前。
    列：{"id": "pid:线程名", "pid", "proc": 进程名, "thread": 归一之后的线程名, "names": 合进来的原名（最多 6 个）,
         "n_threads", "first", "last", "entry": 入口节点,
         "nodes": {节点: {"n": 被调次数, "first"}},
         "edges": [{"a", "b", "n", "only": 其中代码里看不出的（约数）, "first", "last"}],
         "external": 只跑仓库外的代码、因为是交接的一头才有这一列（没有节点）,
         "start": {"n": 知道是谁起的线程数, "t": 最早起的时刻, "lane": 起它的列, "daemon": 其中守护线程数} 或 None（不知道谁起的：
                  程序的主线程、hook 装上之前起的）,
         "stop": {"joined": 被 join / waitpid 等到的个数, "t": 最晚那一次的时刻, "lane": 等它的列,
                  "exited": 自己跑完、没人等的个数, "running": 到录制结束还没跑完的个数（子进程是不知道有没有退出）} 或 None}
    连线：{"kind": "spawn" | "handoff" | "join", "via": thread / exec / fork / queue / asyncio / janus / zmq / join / wait,
           "from": {"lane", "node", "fn", "t", "line"}, "to": {…}, "n", "first", "last",
           "pairs": [{"a": 起点函数, "b": 终点函数, "la" / "lb": 那一头的行（0 不知道）, "ta" / "tb": 那一行的代码,
                      "xa" / "xb": 那一头经仓库外的代码, "da" / "db": 定义 {f, l, k}, "n", "first"}]
           （次数最多的 8 对）, "n_pairs"}
    ——同样两头（列和节点）、同一种的合成一条，n 是几次；from / to 的 t 是最早的一次，first / last 是首末时刻（join 是等到的时刻，
    其余是起点那头的）；fn 是那一头的函数（span 的被调方；放 / 取发生在仓库外的代码里时是这条线程入口的仓库函数，ext 为真），
    line 是那个函数里起线程、放 / 取、发 / 收、join 的那一行（录制之后文件改过的，跟着函数挪；被起 / 被回收的那一头是 0：
    那一头是线程的入口函数）。text(文件, 行) 给的话，pairs 里带上那一行的代码。
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

    def line_of(b: int, ln: int) -> int:
        """span 被调方（键下标 b）的函数里的第 ln 行 → 现在的行号：录制之后文件改过的，跟着函数整个挪；挪不了是 0"""
        if not ln or keymap is None or not 0 <= b < len(keys):
            return ln
        kb = keys[b]
        rel, _, old = kb.rpartition(":")
        if rel not in keymap.todo:
            return ln
        now = int(keymap(kb).rpartition(":")[2])
        return ln + now - int(old) if int(old) > 0 and now > 0 else 0

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

    def end_of(pid: int, tid: int, row: int, t: int | None, line: int = 0, create: bool = False) -> dict | None:
        """一条连线的一头：哪一列、哪个节点（span 的被调方；不在任何 span 里就是这一列的入口）、哪一行。只跑仓库外代码的线程
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
        if create and L.get("external") and t is not None:
            L["tids"].add(tid)
            L["names"].add(raw)
            L["first"], L["last"] = min(L["first"], t), max(L["last"], t)
        rows = rows_of.get(pid) or []
        r = rows[row] if 0 <= row < len(rows) else None
        nd = node(r[5]) if r else None
        # 不在任何 span 里（放 / 取发生在仓库外的代码里，比如 vLLM 引擎循环取请求）：记这条线程入口的那个仓库函数，标 ext
        fn = fn_of(r[5]) if r else lanes[lid]["entry_fn"] or (fn_of(roots[lid][1]) if lid in roots else None)
        return {"lane": lid, "node": nd or lanes[lid]["entry"], "fn": fn, "ext": r is None,
                "t": t if t is not None else (r[0] if r else None), "line": line_of(r[5], line) if r else 0}

    def end_via(pid: int, tid: int, row: int, t: int | None, line: int) -> dict | None:
        """join 的那一头：等它的线程没有列（asyncio.run 收尾时起的 _do_shutdown 线程替它 join 线程池）的话，顺着「谁起了它」
        往上找到有列的那一处（起这条中间线程的那一行），via 记下经过的线程"""
        via = []
        for _ in range(4):
            e = end_of(pid, tid, row, t, line)
            if e:
                if via:
                    e["via"] = via
                return e
            x = (tfrom.get(str(pid)) or {}).get(str(tid))
            if not x:
                return None
            via.append(thread_group((threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"))
            tid, row, line = x[0], x[1], (x[2] if len(x) > 2 else 0)
        return None

    agg: dict[tuple, dict] = {}                  # 同样两头、同一种的连线合起来：(起点列, 起点节点, 终点列, 终点节点, 种类, 通道)

    def link(kind: str, via: str, a: dict, b: dict, t: int | None = None) -> None:
        k = (a["lane"], a["node"], b["lane"], b["node"], kind, via)
        x = agg.get(k)
        if t is None:
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
        pr = x["pairs"].setdefault((a["fn"], a.get("line", 0), b["fn"], b.get("line", 0), a.get("ext", False), b.get("ext", False)),
                                   [0, t])
        pr[0] += 1
        if t is not None and (pr[1] is None or t < pr[1]):
            pr[1] = t

    # 先连交接：只跑仓库外代码的线程的列（external）是这时候建的，之后起它、回收它的连线才接得上
    for h in ix.get("handoffs") or []:
        t = h["to"][3]
        if not any(x <= t <= y for x, y in segs):
            continue
        a, b = end_of(*h["from"][:4], line=_at(h["from"], 4), create=True), end_of(*h["to"][:4], line=_at(h["to"], 4), create=True)
        if a and b and a["lane"] != b["lane"]:
            link("handoff", h["via"], a, b)
    tfrom, tend = ix.get("thread_from") or {}, ix.get("thread_end") or {}
    starts: dict[str, list] = {}                 # 列 → [(起的时刻, 起它的列, 守护)]：每列的 start 摘要
    stops: dict[str, list] = {}                  # 列 → [(结束 / 等到的时刻, 等它的列 或 None, 状态)]：stop 摘要

    def main_of(pid: int) -> str | None:
        """子进程的主线程那一列（没有叫 MainThread 的就取最早有调用的那一列）"""
        return min((lid for (p, _), lid in tid_lane.items() if p == pid and lid in lanes),
                   key=lambda lid: (lanes[lid]["thread"] != "MainThread", bool(lanes[lid].get("external")), lanes[lid]["first"]),
                   default=None)

    for pid, by_tid in tfrom.items():
        for tid, x in by_tid.items():
            ftid, frow = x[0], x[1]
            fln, ft, dmn = (x[2], x[3], x[4]) if len(x) > 4 else (0, None, False)
            lid = tid_lane.get((int(pid), int(tid)))
            a, b = end_of(int(pid), ftid, frow, ft, fln), _lane_start(lanes, lid)
            if b and int(tid) in lanes[lid]["tids"]:
                starts.setdefault(lid, []).append((ft, a["lane"] if a else None, dmn))
            if a and b and a["lane"] != b["lane"]:
                link("spawn", "thread", a, b)
    for pid, by_tid in tend.items():
        for tid, e in by_tid.items():
            lid = tid_lane.get((int(pid), int(tid)))
            if lid not in lanes or int(tid) not in lanes[lid]["tids"]:
                continue
            j = e.get("by")
            b = end_via(int(pid), j[0], j[1], j[3], j[2]) if j else None
            stops.setdefault(lid, []).append((j[3] if j else e.get("t"), b["lane"] if b else None,
                                              "joined" if j else "exited" if e.get("t") is not None else "running"))
            a = _lane_end(lanes, lid, e.get("t"))
            if a and b and a["lane"] != b["lane"]:
                link("join", "join", a, b, t=j[3])
    pstart: dict[int, int] = {}                  # 进程映像最早的起点：fork 出来的子进程就是在这一刻起的（B 行没有时刻）
    for p in ix.get("procs") or []:
        pstart[p["pid"]] = min(pstart.get(p["pid"], p["t0_us"]), p["t0_us"])
    for s in ix.get("spawns") or []:
        a = end_of(s["pid"], s["tid"], s["row"], s.get("t_us"), s.get("line", 0))
        main = main_of(s["child"])
        b = _lane_start(lanes, main)
        if b:
            starts.setdefault(main, []).append((s.get("t_us", pstart.get(s["child"])), a["lane"] if a else None, False))
        if a and b:
            link("spawn", s["how"], a, b)
    reaped = set()
    for s in ix.get("reaps") or []:
        main = main_of(s["child"])
        if main is None or main in reaped:
            continue
        reaped.add(main)
        b = end_of(s["pid"], s["tid"], s["row"], s["t_us"], s["line"])
        stops.setdefault(main, []).append((s["t_us"], b["lane"] if b else None, "joined"))
        a = _lane_end(lanes, main, None)
        if a and b:
            link("join", "wait", a, b, t=s["t_us"])
    for lid in starts:                           # 知道是谁起的子进程、没看到谁等它退出：不知道
        if lanes[lid]["thread"] == "MainThread" and lid not in stops:
            stops[lid] = [(None, None, "running")]
    links = list(agg.values())
    for x in links:
        prs = sorted(x["pairs"].items(), key=lambda kv: (-kv[1][0], kv[1][1] if kv[1][1] is not None else 0))
        x["n_pairs"] = len(prs)
        x["pairs"] = []
        for (fa, la, fb, lb, xa, xb), (n, f) in prs[:8]:
            da, db = _align.node_def(idx, fa) if fa else None, _align.node_def(idx, fb) if fb else None
            pr = {"a": fa, "b": fb, "la": la, "lb": lb, "xa": xa, "xb": xb, "n": n, "first": f, "da": da, "db": db}
            if text is not None:
                pr["ta"] = text(da["f"], la) if da and la else ""
                pr["tb"] = text(db["f"], lb) if db and lb else ""
            x["pairs"].append(pr)

    out = []
    for L in lanes.values():
        L["start"], L["stop"] = _start_sum(starts.get(L["id"])), _stop_sum(stops.get(L["id"]))
        L["n_threads"] = len(L.pop("tids"))
        L["names"] = sorted(L["names"])[:6]
        L.pop("entry_t")
        L.pop("entry_fn")
        L["edges"] = sorted(L["edges"].values(), key=lambda e: e["first"])
        for e in L["edges"]:
            e["only"] = round(e["only"])
        out.append(L)
    # 进程按启动的先后（父进程在前；按第一次调用排的话，一开机就在轮询的进程会排到最前面），进程里按交接的顺序（_order）
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
    return {"lane": lid, "node": L["entry"] or next(iter(L["nodes"]), None), "fn": L["entry_fn"], "t": L["first"], "line": 0}


def _lane_end(lanes: dict, lid: str | None, t: int | None) -> dict | None:
    """被回收的那一列的一头：线程从入口函数返回就结束了，所以也是入口节点；t 是它跑完的时刻"""
    a = _lane_start(lanes, lid)
    if a is not None:
        a["t"] = t
    return a


def _at(side: list, i: int) -> int:
    """handoffs 的一头 [pid, tid, row, t, line]：老的 run 没有 line"""
    return side[i] if len(side) > i else 0


def _start_sum(xs: list | None) -> dict | None:
    """一列里各线程是谁起的 → start 摘要（见 build）"""
    if not xs:
        return None
    ts = [x for x in xs if x[0] is not None]
    first = min(ts, key=lambda x: x[0]) if ts else xs[0]
    return {"n": len(xs), "t": first[0], "lane": first[1], "daemon": sum(1 for x in xs if x[2])}


def _stop_sum(xs: list | None) -> dict | None:
    """一列里各线程怎么结束的 → stop 摘要（见 build）：t / lane 取最晚被等到的那一次"""
    if not xs:
        return None
    jo = [x for x in xs if x[2] == "joined"]
    last = max(jo, key=lambda x: x[0] if x[0] is not None else -1) if jo else None
    return {"joined": len(jo), "t": last[0] if last else None, "lane": last[1] if last else None,
            "exited": sum(1 for x in xs if x[2] == "exited"), "running": sum(1 for x in xs if x[2] == "running")}


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
