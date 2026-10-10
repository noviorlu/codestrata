"""一段时间（阶段、时间段）按功能切开：请求、每个进程干活的那一段（stage 段）、段之间的交接、缺口、只在轮询的背景列。

一列的主循环、轮、空转、忙段的判法在 steps.py。这里：
    请求    `--phase` 的那个函数在这一段里的每一次调用（REF 是阶段名、run 用 --phase 切的时候才有）。
    stage 段 一个进程里前景轮最多的那一列是它的主循环，取主循环最大的那块忙段。持有请求的进程不出段（用「请求」那一行代表）；
            只有一个进程在干活的程序（单进程的脚本）例外。
    缺口    段开始前后 max(段长 GAP_BEFORE, GAP_MIN_US) 里没录到别的进程交给它的数据：可能走了没录的通道（共享内存、deque…），
            写上一次交给它是什么时候、什么通道，不说是谁交的。
    独有代码 这段时间里这个进程调到、整个 REF 时间里别的进程都没调到的文件，按次数排——给 agent 认「这是 talker」用的证据。
要 2026-10-01 之后录的 run（span 带父亲、录了交接）；老 run 由调用方拒绝（old_format）。
"""
from __future__ import annotations

import statistics
from collections import Counter

from . import lanes as _lanes
from . import seq as _seq
from . import steps as _steps

GAP_BEFORE = 0.10
GAP_MIN_US = 50_000
REQ_SLACK_US = 1000          # 阶段函数的那次调用可能比切阶段的时刻早一点点（hook 在进入函数时才切）


def old_format(rd) -> bool:
    """2026-10-01 之前整理的 span：没录交接（index 里没有 handoffs）——切段会切错"""
    return "handoffs" not in _seq.span_index(rd)


def analyse(rd, lo: int, hi: int, p: _steps.Params | None = None, head: dict | None = None,
            pids: set[int] | None = None) -> dict:
    """读整个 run 的 span，每一列认主循环、切轮。返回 {lanes: {列 id: 信息}, rows: {pid: 行}, tid_lane, aliases, procs, ix}。
    列的信息：{id, alias, pid, tids, lr, loop, rounds, regular, win（这段里的轮）, blocks, kind, out_t, in_t}。
    head：{列 id: 轮头的键下标集合}（--head）；pids：只读这几个进程（steps 只要一列）"""
    p = p or _steps.Params()
    ix = _seq.span_index(rd)
    aliases = _lanes.run_aliases(rd)
    lanes: dict[str, dict] = {}
    tid_lane: dict[tuple, str] = {}
    for pid_s, ts in ix["threads"].items():
        for tid_s, name in ts.items():
            pid, tid = int(pid_s), int(tid_s)
            lid = _lanes.lane_id(pid, name)
            tid_lane[(pid, tid)] = lid
            ln = lanes.setdefault(lid, {"id": lid, "alias": aliases.get(lid, lid), "pid": pid, "tids": set()})
            ln["tids"].add(tid)
    rows = {pid: _seq.pid_rows(rd, pid) for pid in sorted({c["pid"] for c in ix["chunks"]}) if pids is None or pid in pids}
    for ln in lanes.values():
        ln["out_t"], ln["in_t"] = [], []
    for h in ix.get("handoffs") or []:
        for end, key in ((h["from"], "out_t"), (h["to"], "in_t")):
            lid = tid_lane.get((end[0], end[1]))
            if lid:
                lanes[lid][key].append(end[3])
    if pids is not None:
        lanes = {lid: ln for lid, ln in lanes.items() if ln["pid"] in pids}
    for ln in lanes.values():
        lr = _steps.lane_rows(rows.get(ln["pid"]) or [], ln["tids"])
        ln["lr"] = lr
        loop = _steps.find_loop(lr, lo, hi, p, head=(head or {}).get(ln["id"])) if lr else None
        ln["loop"] = loop
        if loop:
            ln["rounds"], ln["regular"] = _steps.cut_rounds(loop, lr, ln["out_t"], ln["in_t"], p)
            ln["win"] = _steps.in_window(ln["rounds"], lo, hi)
            ln["blocks"] = _steps.busy_blocks(ln["rounds"], lo, hi, p)
        else:
            ln["rounds"], ln["regular"], ln["win"], ln["blocks"] = [], set(), [], []
        has = any(lo <= r[0] < hi for _, r in lr)
        ln["kind"] = "external" if not lr and (ln["out_t"] or ln["in_t"]) else _steps.kind(len(ln["tids"]), has, loop, ln["win"])
    return {"lanes": lanes, "rows": rows, "tid_lane": tid_lane, "aliases": aliases, "procs": _lanes.proc_aliases(rd), "ix": ix}


def requests(A: dict, run: dict, phase: str | None, lo: int, hi: int, label) -> list[dict]:
    """阶段函数（--phase 名字=函数）在这段时间里的每一次调用：[{fn, lane, pid, t0_us, t1_us}]"""
    pa = {t["name"]: t for t in (run.get("rec") or {}).get("phase_at") or []}
    if phase not in pa:
        return []
    t = pa[phase]
    node = f"{t['file']}#{t['qualname']}"
    keys = A["ix"]["keys"]
    want = {i for i, k in enumerate(keys) if k.startswith(t["file"] + ":") and label(k) == node}
    out = []
    for pid, rows in A["rows"].items():
        for r in rows:
            if r is not None and len(r) <= 9 and r[5] in want and lo - REQ_SLACK_US <= r[0] < hi:
                lid = A["tid_lane"].get((pid, r[2]))
                end = r[0] + r[1] if r[1] >= 0 else None
                out.append({"fn": node, "lane": A["aliases"].get(lid, lid), "pid": pid, "t0_us": r[0], "t1_us": end})
    return sorted(out, key=lambda x: x["t0_us"])


def stage_segments(A: dict, lo: int, hi: int, skip_pids: set[int]) -> list[dict]:
    """每个进程干活的那一段（按开始的先后）。skip_pids：持有请求的进程。都没有时（单进程的程序）不跳过它们"""
    by_pid: dict[int, list] = {}
    for ln in A["lanes"].values():
        if ln["kind"] == "loop" and ln["blocks"]:
            by_pid.setdefault(ln["pid"], []).append(ln)
    segs = [_segment(A, lns) for pid, lns in by_pid.items() if pid not in skip_pids]
    alone = not segs
    if alone:
        # 只有持有请求的进程在干活（单进程的脚本）：没有别的进程交接，每轮干一样的活也像空转——段就是这段时间里的全部轮，不看缺口
        segs = [_segment(A, lns, whole=True) for lns in by_pid.values()]
    segs.sort(key=lambda s: s["slices_us"][0][0])
    files = _files_by_pid(A, lo, hi)
    for n, s in enumerate(segs, 1):
        s["id"] = f"S{n}"
        s["evidence"] = {"own_files": _own_files(A, s, files), "alone": alone}   # alone：没有别的进程可比，own_files 只是调得最多的
        s["gaps"] = [] if alone else _gaps(A, s, lo)
    return segs


def _segment(A: dict, lns: list[dict], whole: bool = False) -> dict:
    main = max(lns, key=lambda ln: sum(1 for x in ln["win"] if not x["spin"]))
    rs = main["rounds"]
    if whole:
        a_i, b_i = rs.index(main["win"][0]), rs.index(main["win"][-1])
    else:
        a_i, b_i = max(main["blocks"], key=lambda ab: rs[ab[1]]["t1_us"] - rs[ab[0]]["t0_us"])
    part = rs[a_i:b_i + 1]
    a, b = part[0]["t0_us"], part[-1]["t1_us"]
    pid = main["pid"]
    mine = [ln for ln in A["lanes"].values() if ln["pid"] == pid]
    busy = [ln["alias"] for ln in mine if any(a <= r[0] < b for _, r in ln["lr"])
            or any(a <= t < b for t in ln["out_t"] + ln["in_t"])]
    return {"kind": "stage", "pid": pid, "proc": A["procs"].get(pid, str(pid)), "main": main["alias"],
            "lanes": sorted(ln["alias"] for ln in mine), "busy_lanes": sorted(busy),
            "slices_us": [[a, b]], "dur_us": b - a,
            "rounds": {"first": part[0]["k"], "last": part[-1]["k"], "n": len(part), "fg": sum(1 for x in part if not x["spin"]),
                       "out": sum(x["out"] for x in part), "head": main["loop"]["head"],
                       "median_us": int(statistics.median(x["dur_us"] for x in part))},
            "truncated": pid in (A["ix"].get("truncated") or [])}


def _files_by_pid(A: dict, lo: int, hi: int) -> dict[int, Counter]:
    keys = A["ix"]["keys"]
    out: dict[int, Counter] = {}
    for pid, rows in A["rows"].items():
        c = out.setdefault(pid, Counter())
        for r in rows:
            if r is not None and len(r) <= 9 and lo <= r[0] < hi:
                c[keys[r[5]].rpartition(":")[0]] += r[6]
    return out


def _own_files(A: dict, s: dict, files: dict[int, Counter], top: int = 3) -> list[list]:
    """这段时间里这个进程调到、整个 REF 时间里别的进程都没调到的文件，按次数排"""
    keys = A["ix"]["keys"]
    a, b = s["slices_us"][0]
    others = set().union(*(set(c) for pid, c in files.items() if pid != s["pid"])) if len(files) > 1 else set()
    mine: Counter = Counter()
    for r in A["rows"].get(s["pid"]) or []:
        if r is not None and len(r) <= 9 and a <= r[0] < b:
            mine[keys[r[5]].rpartition(":")[0]] += r[6]
    return [[f, n] for f, n in mine.most_common() if f not in others and f != "?"][:top]


def _gaps(A: dict, s: dict, lo: int) -> list[dict]:
    """段开始前后没录到别的进程交给它的数据"""
    a, b = s["slices_us"][0]
    win = max(GAP_MIN_US, int(GAP_BEFORE * (b - a)))
    into = [h for h in A["ix"].get("handoffs") or [] if h["to"][0] == s["pid"] and h["from"][0] != s["pid"]]
    if any(a - win <= h["to"][3] <= a + win for h in into):
        return []
    before = [h for h in into if h["to"][3] < a]
    last = max(before, key=lambda h: h["to"][3]) if before else None
    return [{"before_us": a - (last["to"][3] if last else lo), "last_us": last["to"][3] if last else None,
             "last_via": last["via"] if last else None}]


def handoff_groups(A: dict, lo: int, hi: int) -> tuple[list[dict], int]:
    """这段时间里的交接按（通道, 起列, 终列）合成组：(跨进程的组, 进程内的次数)。组：{id, via, from, to, n, first_us, last_us}"""
    groups: dict[tuple, dict] = {}
    intra = 0
    for h in A["ix"].get("handoffs") or []:
        t = h["from"][3]
        if not lo <= t < hi:
            continue
        fa = A["aliases"].get(A["tid_lane"].get((h["from"][0], h["from"][1])), f"{h['from'][0]}/{h['from'][1]}")
        ta = A["aliases"].get(A["tid_lane"].get((h["to"][0], h["to"][1])), f"{h['to'][0]}/{h['to'][1]}")
        if h["from"][0] == h["to"][0]:
            intra += 1
            continue
        g = groups.setdefault((h["via"], fa, ta), {"id": f"l:handoff|{h['via']}|{fa}|{ta}", "via": h["via"], "from": fa,
                                                  "to": ta, "n": 0, "first_us": t, "last_us": t})
        g["n"] += 1
        g["first_us"], g["last_us"] = min(g["first_us"], t), max(g["last_us"], t)
    return sorted(groups.values(), key=lambda g: g["first_us"]), intra


def background(A: dict, segs: list[dict]) -> list[str]:
    """只在轮询的列（不在任何段里当主循环的）"""
    mains = {s["main"] for s in segs}
    return sorted(ln["alias"] for ln in A["lanes"].values() if ln["kind"] == "poll" and ln["alias"] not in mains)
