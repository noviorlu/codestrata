"""一段时间（阶段、时间段）按功能切开：请求、每个进程干活的那一段（stage 段）、段之间的交接、缺口、只在轮询的背景列。

一列的主循环、轮、空转、忙段的判法在 steps.py。这里：
    请求    `--phase` 的那个函数和这一段相交的每一次调用（run 用 --phase 切的时候才有）。
    stage 段 一个进程里几列的前景轮合起来的每一块忙段（steps.busy_blocks）：至少两轮前景的一块一段，按开始的先后编号，
            同一个进程可以出几段（先后两次请求、两个进程交替干活）；只有一轮前景的零星几块记在这个进程的段上，不单出段
            （一块都不够两轮时最长的那块还是出段：干过活的进程不丢）。段的主循环是这块里前景时间最多的那一列。
            持有请求的进程不出段（用「请求」那一行代表）；只有一个进程在干活的程序（单进程的脚本）例外。
    缺口    段开始前后 max(段长 GAP_BEFORE, GAP_MIN_US) 里没录到别的进程交给它的数据：可能走了没录的通道（共享内存、deque…），
            写上一次交给它是什么时候、什么通道，不说是谁交的（看的是整个 run 录到的交接）。REF 开始之前它就在忙（范围把开头切掉了）、
            或者同一个进程在这之前已经出过段，不报。
    独有代码 这段时间里这个进程调到、整个 REF 时间里别的进程都没调到的文件，按次数排——给 agent 认「这是 talker」用的证据。
要 2026-10-01 之后录的 run（span 带父亲、录了交接）；老 run 由调用方拒绝（old_format）。
"""
from __future__ import annotations

import statistics
import threading
from collections import Counter, OrderedDict

from . import lanes as _lanes
from . import seq as _seq
from . import steps as _steps

GAP_BEFORE = 0.10
GAP_MIN_US = 50_000
REQ_SLACK_US = 1000          # 阶段函数的那次调用可能比切阶段的时刻早一点点（hook 在进入函数时才切）


def old_format(rd) -> bool:
    """2026-10-01 之前整理的 span：没录交接（index 里没有 handoffs）——切段会切错"""
    return "handoffs" not in _seq.span_index(rd)


def head_window(run: dict, end_us: int | None, lo: int, hi: int, phase: str | None) -> tuple[str | None, tuple[int, int]]:
    """认轮头用的那段和它的阶段名：[lo, hi) 落在某个阶段的一段里就用那整段（REF 是阶段里的一小段时也一样：轮头和轮号不随 REF 的
    范围变）；跨阶段、没分阶段时用 [lo, hi) 自己。phase 是 REF 写的（阶段名、t=起-止 或 None）。命令行和页面用同一份"""
    name = phase if phase and not phase.startswith("t=") else None
    if end_us:
        for nm, a, b in _seq.phase_segments(run, end_us):
            if a <= lo and hi <= b:
                return name or nm, (a, b)
    return name, (lo, hi)


def analyse(rd, lo: int, hi: int, p: _steps.Params | None = None, head: dict | None = None,
            pids: set[int] | None = None, head_window: tuple[int, int] | None = None) -> dict:
    """读整个 run 的 span，每一列认主循环、切轮。返回 {lanes: {列 id: 信息}, rows: {pid: 行}, tid_lane, aliases, procs, ix}。
    列的信息：{id, alias, pid, tids, lr, loop, rounds, regular, win（这段里的轮）, kind, ho_out, ho_in}。
    [lo, hi) 是要看的那段；head_window 是认轮头用的那段（REF 所在的阶段，缺省同 [lo, hi)）。
    head：{列 id: 轮头的键下标集合}（--head）；pids：只读这几个进程（steps 只要一列）"""
    p = p or _steps.Params()
    hlo, hhi = head_window or (lo, hi)
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
        ln["ho_out"], ln["ho_in"] = [], []
    for h in ix.get("handoffs") or []:
        for end, key in ((h["from"], "ho_out"), (h["to"], "ho_in")):
            lid = tid_lane.get((end[0], end[1]))
            if lid:
                lanes[lid][key].append((end[1], end[2], end[3]))     # (线程号, span 下标, 时刻)
    if pids is not None:
        lanes = {lid: ln for lid, ln in lanes.items() if ln["pid"] in pids}
    for ln in lanes.values():
        lr = _steps.lane_rows(rows.get(ln["pid"]) or [], ln["tids"])
        ln["lr"] = lr
        loop = _steps.find_loop(lr, hlo, hhi, p, head=(head or {}).get(ln["id"])) if lr else None
        ln["loop"] = loop
        if loop:
            ln["rounds"], ln["regular"] = _steps.cut_rounds(loop, lr, ln["ho_out"], ln["ho_in"], p)
            ln["win"] = _steps.in_window(ln["rounds"], lo, hi)
        else:
            ln["rounds"], ln["regular"], ln["win"] = [], set(), []
        has = any(lo <= r[0] < hi for _, r in lr)
        ln["kind"] = "external" if not lr and (ln["ho_out"] or ln["ho_in"]) else _steps.kind(len(ln["tids"]), has, loop, ln["win"])
    return {"lanes": lanes, "rows": rows, "tid_lane": tid_lane, "aliases": aliases, "procs": _lanes.proc_aliases(rd), "ix": ix,
            "window": (lo, hi), "head_window": (hlo, hhi), "handoffs_any": bool(ix.get("handoffs")), "p": p}


def requests(A: dict, run: dict, phase: str | None, lo: int, hi: int, label) -> list[dict]:
    """阶段函数（--phase 名字=函数）和这段时间相交的每一次调用：[{fn, lane, pid, t0_us, t1_us}]。phase 是 REF 所在的阶段名"""
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
            end = r[0] + r[1] if r is not None and r[1] >= 0 else None
            # 和这段时间相交的都算（看的是请求中间的一小段时，那次请求在这段之前就开始了）
            if r is not None and len(r) <= 9 and r[5] in want and r[0] < hi and (end is None or end > lo - REQ_SLACK_US):
                lid = A["tid_lane"].get((pid, r[2]))
                out.append({"fn": node, "lane": A["aliases"].get(lid, lid), "pid": pid, "t0_us": r[0], "t1_us": end})
    return sorted(out, key=lambda x: x["t0_us"])


def stage_segments(A: dict, lo: int, hi: int, skip_pids: set[int]) -> list[dict]:
    """每个进程的每一块忙段（按开始的先后编号 S1、S2…）。skip_pids：持有请求的进程。都没有时（单进程的程序）不跳过它们，
    这时段就是这段时间里主循环的全部轮"""
    by_pid: dict[int, list] = {}
    for ln in A["lanes"].values():
        if ln["kind"] == "loop":
            by_pid.setdefault(ln["pid"], []).append(ln)
    segs = [sg for pid, lns in by_pid.items() if pid not in skip_pids for sg in _process_segments(A, lns, lo, hi)]
    alone = not segs
    if alone:
        # 只有持有请求的进程在干活（单进程的脚本）：没有别的进程交接，每轮干一样的活也像空转——段就是这段时间里的全部轮，不看缺口
        whole: dict[int, list] = {}
        for ln in A["lanes"].values():
            if ln["loop"] and ln["win"]:
                whole.setdefault(ln["pid"], []).append(ln)
        segs = [_whole_segment(A, lns) for lns in whole.values()]
    segs.sort(key=lambda s: s["slices_us"][0][0])
    files = _files_by_pid(A, lo, hi)
    for n, s in enumerate(segs, 1):
        s["id"] = f"S{n}"
        s["evidence"] = {"own_files": _own_files(A, s, files), "alone": alone}   # alone：没有别的进程可比，own_files 只是调得最多的
        s["gaps"] = [] if alone else _gaps(A, s, lo, segs)
    return segs


def _process_segments(A: dict, lns: list[dict], lo: int, hi: int) -> list[dict]:
    """一个进程的段：几列的前景轮合起来切块，至少两轮前景的一块一段；零星的（一轮）记在离它最近的段上"""
    items = [(x["t0_us"], x["t1_us"], ln["id"], x["work_us"]) for ln in lns for x in ln["win"] if not x["spin"]]
    hlo, hhi = A["head_window"]                     # 切块的空转门槛按 REF 所在的阶段的长度算：REF 缩小了也切得一样
    blocks = _steps.busy_blocks(items, lo, hi, A["p"], scale=hhi - hlo)
    if not blocks:
        return []
    big = [bl for bl in blocks if len(bl) >= 2] or [max(blocks, key=lambda bl: max(x[1] for x in bl) - bl[0][0])]
    segs = [_segment(A, lns, bl, hi) for bl in big]
    for bl in blocks:
        if any(bl is x for x in big):
            continue
        t = bl[0][0]
        near = min(segs, key=lambda sg: abs(sg["slices_us"][0][0] - t))
        near["stray"].append([t, max(x[1] for x in bl), sorted({A["lanes"][x[2]]["alias"] for x in bl})])
    return segs


def _segment(A: dict, lns: list[dict], blk: list[tuple], hi: int) -> dict:
    """一块忙段 → 段（到 hi 为止：最后一轮可能一直到下一阶段才有下一次轮头）。
    主循环是这块里前景轮「在仓库函数里的时间」最多的那一列（不按墙上时长：被别的线程挡住的轮也很长）"""
    a, b = blk[0][0], min(max(x[1] for x in blk), hi)
    work: Counter = Counter()
    for _, _, lid, w in blk:
        work[lid] += w
    main = next(ln for ln in lns if ln["id"] == max(work, key=lambda lid: (work[lid], lid)))
    part = [x for x in main["rounds"] if a <= x["t0_us"] < b]
    return _describe(A, main, part, a, b)


def _whole_segment(A: dict, lns: list[dict]) -> dict:
    main = max(lns, key=lambda ln: (sum(x["work_us"] for x in ln["win"]), len(ln["win"]), ln["id"]))
    part = main["win"]
    return _describe(A, main, part, part[0]["t0_us"], min(part[-1]["t1_us"], A["window"][1]))


def _describe(A: dict, main: dict, part: list[dict], a: int, b: int) -> dict:
    pid = main["pid"]
    longest = max(part, key=lambda x: x["dur_us"])
    mine = [ln for ln in A["lanes"].values() if ln["pid"] == pid]
    busy = [ln["alias"] for ln in mine if any(a <= r[0] < b for _, r in ln["lr"])
            or any(a <= t < b for _, _, t in ln["ho_out"] + ln["ho_in"])]
    return {"kind": "stage", "pid": pid, "proc": A["procs"].get(pid, str(pid)), "main": main["alias"],
            "lanes": sorted(ln["alias"] for ln in mine), "busy_lanes": sorted(busy),
            "slices_us": [[a, b]], "dur_us": b - a,
            "rounds": {"first": part[0]["k"], "last": part[-1]["k"], "n": len(part), "fg": sum(1 for x in part if not x["spin"]),
                       "out": sum(x["out"] for x in part), "head": main["loop"]["head"],
                       "median_us": int(statistics.median(x["dur_us"] for x in part)),
                       "longest": {"k": longest["k"], "dur_us": longest["dur_us"]}},
            "stray": [], "routine_word": "空转" if A.get("handoffs_any") else "常规轮",
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


def _gaps(A: dict, s: dict, lo: int, segs: list[dict]) -> list[dict]:
    """段开始前后没录到别的进程交给它的数据"""
    a, b = s["slices_us"][0]
    win = max(GAP_MIN_US, int(GAP_BEFORE * (b - a)))
    ln = next((x for x in A["lanes"].values() if x["alias"] == s["main"] and x["pid"] == s["pid"]), None)
    k = s["rounds"]["first"] - 1                    # 段的第一轮在整个 run 的轮里的下标
    if ln is not None and k >= 1 and ln["rounds"][k - 1]["t0_us"] < lo and not ln["rounds"][k - 1]["spin"]:
        return []                                   # REF 开始之前它就在忙（范围把前面切掉了）：看不到开头，不说没录到
    if any(x["pid"] == s["pid"] and x["slices_us"][0][0] < a for x in segs):
        return []                                   # 这个进程之前已经出过段：数据可能是它自己前面的活（进程里的通道没录）
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


def unsegmented(A: dict, lo: int, hi: int, segs: list[dict], skip_pids: set[int]) -> list[dict]:
    """这段时间里有调用、却没出段的进程（认不出主循环：只来了一两次请求的 worker、线程池…）：
    [{pid, proc, lanes, calls（最外层的调用几次）, busy_us（它们合起来多长）, first_us, last_us}]，按开始的先后。只看没有主循环的列"""
    have = {s["pid"] for s in segs} | skip_pids
    out: dict[int, dict] = {}
    for ln in A["lanes"].values():
        if ln["pid"] in have or ln["loop"] is not None:
            continue
        rows = {i: r for i, r in ln["lr"] if lo <= r[0] < hi}
        for i, r in rows.items():
            if r[8] in rows:                        # 只数这段时间里最外层的调用
                continue
            e = out.setdefault(ln["pid"], {"pid": ln["pid"], "proc": A["procs"].get(ln["pid"], str(ln["pid"])), "lanes": set(),
                                           "calls": 0, "busy_us": 0, "first_us": r[0], "last_us": r[0]})
            end = r[0] + r[1] if r[1] >= 0 else hi
            e["lanes"].add(ln["alias"])
            e["calls"] += r[6]
            e["busy_us"] += min(end, hi) - r[0]
            e["first_us"], e["last_us"] = min(e["first_us"], r[0]), max(e["last_us"], min(end, hi))
    for e in out.values():
        e["lanes"] = sorted(e["lanes"])
    return sorted(out.values(), key=lambda e: e["first_us"])


def background(A: dict, segs: list[dict]) -> list[str]:
    """只在轮询的列（不在任何段里当主循环的）"""
    mains = {s["main"] for s in segs}
    return sorted(ln["alias"] for ln in A["lanes"].values() if ln["kind"] == "poll" and ln["alias"] not in mains)


_ORDER: "OrderedDict[tuple, dict]" = OrderedDict()   # (span 目录, index 的 mtime, 时间段) → proc_order 的结果（最近 8 个）
_ORDER_LOCK = threading.Lock()


def proc_order(rd, run: dict, phase: str | None, lo: int, hi: int, label, head_window: tuple | None = None) -> dict[int, int]:
    """进程的先后（用户 10-10 定：按这一段里开始干活的先后）：{pid: 开始干活的时刻}。持有请求的进程从请求开始算，
    别的进程从它的 stage 段开始算；没有段的不在里面（调用方按第一次活动排在后面）。切段靠不住时是空的（调用方退回按启动的先后）：
    老 run（没录交接）、这段时间里一次交接都没录到；只有一轮的段不算。phase 是 REF 所在的阶段名
    按 (run, 时间段) 缓存：分列改切面、收起进程都不再算"""
    spans = rd / "events" / "spans"
    try:
        key = (str(spans), (spans / "index.json").stat().st_mtime_ns, lo, hi, phase, head_window)
    except OSError:
        return {}
    with _ORDER_LOCK:
        hit = _ORDER.get(key)
    if hit is not None:
        return hit
    out: dict[int, int] = {}
    ho = [] if old_format(rd) else [h for h in _seq.span_index(rd).get("handoffs") or [] if lo <= h["from"][3] < hi]
    if ho:
        A = analyse(rd, lo, hi, head_window=head_window)
        reqs = requests(A, run, phase, lo, hi, label)
        for q in reqs:
            out[q["pid"]] = min(out.get(q["pid"], q["t0_us"]), max(q["t0_us"], lo))
        for sg in stage_segments(A, lo, hi, {q["pid"] for q in reqs}):      # 按开始排好了：同一个进程取最早的一段
            if sg["rounds"]["n"] >= 2:
                out.setdefault(sg["pid"], sg["slices_us"][0][0])
    with _ORDER_LOCK:
        _ORDER[key] = out
        while len(_ORDER) > 8:
            _ORDER.popitem(last=False)
    return out
