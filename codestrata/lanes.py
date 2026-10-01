"""运行时按进程 · 线程分列（P0，用户 2026-10-01 定的展示）：叠了 run 之后，模块图按线程分成并排的几列。

一列（lane）是一个进程里的一个线程；同一个进程里同名的线程（每步新开的 output-builder）合成一列，记下合了几个。
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
from pathlib import Path

from . import align as _align
from . import seq as _seq


def build(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, open_) -> dict:
    """{"phase", "window": [起, 止], "scope", "lanes": [列], "links": [连线]}。列按进程启动的先后排，进程里主线程在前。
    列：{"id": "pid:线程名", "pid", "proc": 进程名, "thread": 线程名, "n_threads", "first", "last", "entry": 入口节点,
         "nodes": {节点: {"n": 被调次数, "first"}}, "edges": [{"a", "b", "n", "only": 其中代码里看不出的（约数）, "first"}]}
    连线：{"kind": "spawn" | "handoff", "via": thread / exec / fork / queue / asyncio / janus / zmq,
           "from": {"lane", "node", "t"}, "to": {"lane", "node", "t"}, "n"}（spawn 的 n 是 1）。
    没有时序事件、没有这个阶段的时刻抛 LookupError"""
    ix = _seq.span_index(rd)
    segs, win, end = _seq.window_segments(run, rd, phase)
    lo, hi = segs[0][0], segs[-1][1]
    m = _seq.cut_map(idx, open_)
    keys, threads = ix["keys"], ix["threads"]
    keymap, redirect = hot.get("keymap"), hot.get("redirect") or {}
    share = _only_share(idx, hot)
    names = proc_names(rd)
    node_cache: dict[int, tuple] = {}

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
    for pid in dict.fromkeys(c["pid"] for c in ix["chunks"]):
        rows = rows_of[pid] = _seq.pid_rows(rd, pid)
        tnames = threads.get(str(pid)) or {}
        for r in rows:
            got = None
            for i, (a, b) in enumerate(segs):
                got = _seq.calls_in(r[0], r[1], r[6], a, b, open_hi=not win and (i + 1 < len(segs) or b < end))
                if got:
                    break
            tname = tnames.get(str(r[2])) or f"线程 {r[2]}"
            lid = f"{pid}:{tname}"
            tid_lane[(pid, r[2])] = lid
            if not got:
                continue
            n, first, last = got
            na, nb, defining, only = nodes_of(r[4], r[5])
            if na is None or nb is None or defining:
                continue
            L = lanes.get(lid)
            if L is None:
                L = lanes[lid] = {"id": lid, "pid": pid, "proc": names.get(pid) or f"pid {pid}", "thread": tname,
                                  "tids": set(), "first": first, "last": last, "entry": None, "entry_t": None,
                                  "nodes": {}, "edges": {}}
            L["tids"].add(r[2])
            L["first"], L["last"] = min(L["first"], first), max(L["last"], last)
            if r[3] == 0 and (L["entry_t"] is None or first < L["entry_t"]):
                L["entry"], L["entry_t"] = na, first
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
                    L["edges"][(na, nb)] = {"a": na, "b": nb, "n": n, "only": n * only, "first": first}
                else:
                    e["n"] += n
                    e["only"] += n * only
                    e["first"] = min(e["first"], first)

    def end_of(pid: int, tid: int, row: int, t: int | None) -> dict | None:
        """一条连线的一头：哪一列、哪个节点（span 的被调方；不在任何 span 里就是这一列的入口）"""
        lid = tid_lane.get((pid, tid))
        if lid is None or lid not in lanes:
            return None
        rows = rows_of.get(pid) or []
        r = rows[row] if 0 <= row < len(rows) else None
        nd = node(r[5]) if r else None
        return {"lane": lid, "node": nd or lanes[lid]["entry"], "t": t if t is not None else (r[0] if r else None)}

    links = []
    for pid, by_tid in (ix.get("thread_from") or {}).items():
        for tid, (ftid, frow) in by_tid.items():
            a, b = end_of(int(pid), ftid, frow, None), _lane_start(lanes, tid_lane.get((int(pid), int(tid))))
            if a and b and a["lane"] != b["lane"]:
                links.append({"kind": "spawn", "via": "thread", "from": a, "to": b, "n": 1})
    for s in ix.get("spawns") or []:
        a = end_of(s["pid"], s["tid"], s["row"], s.get("t_us"))
        main = min((lid for (p, _), lid in tid_lane.items() if p == s["child"] and lid in lanes),
                   key=lambda lid: lanes[lid]["first"], default=None)
        b = _lane_start(lanes, main)
        if a and b:
            links.append({"kind": "spawn", "via": s["how"], "from": a, "to": b, "n": 1})
    agg: dict[tuple, dict] = {}
    for h in ix.get("handoffs") or []:
        t = h["to"][3]
        if not any(x <= t <= y for x, y in segs):
            continue
        a, b = end_of(*h["from"]), end_of(*h["to"])
        if not a or not b or a["lane"] == b["lane"]:
            continue
        k = (a["lane"], a["node"], b["lane"], b["node"], h["via"])
        x = agg.get(k)
        if x is None:
            agg[k] = {"kind": "handoff", "via": h["via"], "from": a, "to": b, "n": 1}
        else:
            x["n"] += 1
    links.extend(agg.values())

    out = []
    for L in lanes.values():
        L["n_threads"] = len(L.pop("tids"))
        L.pop("entry_t")
        L["edges"] = sorted(L["edges"].values(), key=lambda e: e["first"])
        for e in L["edges"]:
            e["only"] = round(e["only"])
        out.append(L)
    # 进程按启动的先后（父进程在前；按第一次调用排的话，一开机就在轮询的进程会排到最前面），进程里主线程在前、其余按先后
    pstart: dict[int, int] = {}
    for p in ix.get("procs") or []:
        pstart[p["pid"]] = min(pstart.get(p["pid"], p["t0_us"]), p["t0_us"])
    out.sort(key=lambda L: (pstart.get(L["pid"], L["first"]), L["pid"], L["thread"] != "MainThread", L["first"]))
    links.sort(key=lambda x: (x["from"]["t"] if x["from"]["t"] is not None else 0))
    return {"phase": phase, "window": [lo, hi], "scope": ix.get("scope") or "cross", "lanes": out, "links": links}


def _lane_start(lanes: dict, lid: str | None) -> dict | None:
    if lid is None or lid not in lanes:
        return None
    L = lanes[lid]
    return {"lane": lid, "node": L["entry"] or next(iter(L["nodes"]), None), "t": L["first"]}


def _only_share(idx: dict, hot: dict):
    """(调用方键, 被调方键) → 这对函数的调用里代码里看不出的比例（hot["calls"] 按函数对算的，不分线程）"""
    calls = hot.get("calls") or {}
    syms = idx.get("symbols") or {}
    loc2sym, spans = _align.sym_locs(syms)
    label = _align.node_labeler(idx, loc2sym, spans)
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
