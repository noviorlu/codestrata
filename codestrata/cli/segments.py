"""codestrata segments：按功能切段——一次请求在各个进程里各跑的一段、段之间的交接、缺口、背景列。判法见 steps.py、segments.py。"""
from __future__ import annotations

from pathlib import Path

from .. import segments as _seg
from .. import steps as _steps
from ..errors import CodestrataError
from . import common, out

NAME = "segments"
EFFECT = "read"
DOES = "按功能切段：请求、每个进程干活的那一段（各给一个 REF）、段之间的交接、没录到交接的缺口、只在轮询的背景列"
USAGE = "codestrata segments REF [--all] [--min-calls N] [--class-share F] [--cheap F] [--long F] [--gap F] [--json]"
EXAMPLE = "codestrata segments 20261001-170349-run_single_prompt@serving"

MAX_GROUPS = 8          # 文字里列几组跨进程的交接


def add_args(p) -> None:
    p.add_argument("ref", metavar="REF", help="RUN@范围，或页面地址（加单引号）；列选择器在这里不用")
    p.add_argument("--all", action="store_true", help="持有请求的进程也出段（默认用「请求」那一行代表它）")
    common.add_params(p)


def run(a) -> out.Result:
    c = common.context(a)
    common.require_events(c)
    common.refuse_old(c)
    r = c.res
    if len(r.slices) != 1 and not (r.phase or "").startswith("t="):
        raise CodestrataError("bad_window", "这个阶段有几段时间（切走又切回来），切段还只认一段；用 @t=起-止 选其中一段",
                                     candidates=[f"{r.run['id']}@t={x}-{y}" for x, y in r.slices])
    lo, hi, rtext, _ = common.span(c, "切段")
    label = common.labeler(common.index(c))
    p = common.params(a)
    A = _seg.analyse(r.rd, lo, hi, p, head_window=common.head_window(c))
    reqs = _seg.requests(A, r.run, common.phase_name(c), lo, hi, label)
    segs = _seg.stage_segments(A, lo, hi, set() if a.all else {q["pid"] for q in reqs})
    groups, intra = _seg.handoff_groups(A, lo, hi)
    bg = _seg.background(A, segs)
    alone = any(s["evidence"]["alone"] for s in segs)
    loose = [] if alone else _seg.unsegmented(A, lo, hi, segs, set() if a.all else {q["pid"] for q in reqs})
    keys = A["ix"]["keys"]
    rid = r.run["id"]
    for s in segs:
        a_, b_ = s["slices_us"][0]
        s["rounds"]["head"] = label(keys[s["rounds"]["head"]])
        s["ref"] = f"{rid}@t={a_}-{b_}/{s['proc']}"
    base = lo
    lines = [f"{rtext}（{out.dur(hi - lo)}）：{len(segs)} 段。时刻从这一段开头（t={lo}）算"]
    lines += _request_lines(reqs, base)
    for s in segs:
        a_, b_ = s["slices_us"][0]
        rd_ = s["rounds"]
        own = "、".join(Path(f).name for f, _ in s["evidence"]["own_files"][:2]) or "（没有只属于它的文件）"
        fg = f"（前景 {rd_['fg']}）" if rd_["fg"] != rd_["n"] else ""
        lines.append(f"{s['id']}  {s['proc']}  {out.secs(a_, base)} → {out.secs(b_, base)}  {rd_['n']} 轮{fg} · "
                     f"交出 {rd_['out']} · 中位 {out.dur(rd_['median_us'])}   "
                     + ("调得最多的文件" if s["evidence"]["alone"] else "这段里只有它跑") + f"：{own}")
        lg = rd_["longest"]
        if rd_["n"] > 1:
            lines.append(f"    最长 #{lg['k']} {out.dur(lg['dur_us'])}（占这段 {lg['dur_us'] / max(s['dur_us'], 1):.0%}）")
        lines.append(f"    主循环 {s['main']}，每轮从 {common.short(rd_['head'])} 开始；REF {s['ref']}")
        if s["stray"]:
            lines.append(f"    附近还有 {len(s['stray'])} 处零星的前景轮（只有一轮，没列成段）：" + "、".join(
                f"{out.secs(x, base)}（{','.join(ls)}）" for x, _, ls in s["stray"][:4]) + ("…" if len(s["stray"]) > 4 else ""))
        for g in s["gaps"]:
            last = f"上一次是 {out.secs(g['last_us'], base)} 的 {g['last_via']}" if g["last_us"] is not None else "这一段里之前一次都没有"
            lines.append(f"    ⚠ 开始前 {g['before_us'] / 1e6:.1f} s 没录到别的进程交给 {s['proc']} 的数据（{last}）："
                         "可能走了没录的通道（deque、管道…；10-10 之前录的 run 还没录共享内存）")
    if not segs:
        lines.append("没切出段：这段时间里没有认得出主循环、又在干活的列（codestrata lanes 看看有哪些列）")
    for e in loose:
        lines.append(f"没出段  {e['proc']}  {out.secs(e['first_us'], base)} → {out.secs(e['last_us'], base)}  "
                     f"最外层调用 {e['calls']} 次、合计 {out.dur(e['busy_us'])}（认不出主循环：{'、'.join(e['lanes'])}）")
    lines.append(f"交接（录到的跨进程 {len(groups)} 组；进程内 {intra} 次，codestrata links 看全部）")
    for g in groups[:MAX_GROUPS]:
        rng = out.secs(g["first_us"], base) + (f" → {out.secs(g['last_us'], base)}" if g["n"] > 1 else "")
        lines.append(f"  {out.quote(g['id'])}  ×{g['n']}  {rng}")
    if len(groups) > MAX_GROUPS:
        lines.append(f"  …还有 {len(groups) - MAX_GROUPS} 组")
    if bg:
        lines.append(f"背景（只在轮询）  {'、'.join(bg)}")
    if len(reqs) > 1 and not alone:
        c.warnings.append({"code": "many_requests", "msg": f"这段时间里有 {len(reqs)} 次请求：一段里可能混着几次请求（span 里没有请求 id，分不开）"})
    elif reqs and not alone:                        # 一次调用里并发了几个请求：看持有请求的进程开头往外交了几次（推的）
        holder = {A["procs"].get(q["pid"]) for q in reqs}
        first = min((g for g in groups if g["from"].partition("/")[0] in holder), key=lambda g: g["first_us"], default=None)
        if first and first["n"] > len(reqs):
            c.warnings.append({"code": "many_requests", "msg": f"{common.short(reqs[0]['fn'])} 只调了 {len(reqs)} 次，开头却交给 {first['to']} "
                               f"{first['n']} 次（{first['via']}）：多半是一次调用里并发了 {first['n']} 个请求，一段里混着几次请求"
                               "（按开头交出去的次数推的；span 里没有请求 id，分不开）"})
    if r.lanes:
        c.warnings.append({"code": "lanes_ignored", "msg": f"segments 切的是整个范围里的所有进程，REF 里的列（/{','.join(r.lanes)}）没用上"})
    mp = common.main_phase(r.run)
    if _seg.whole_run(r.run, lo, hi, r.end_us):        # 和页面同一个判法：没写范围、或者 t=0-终点
        c.warnings.append({"code": "whole_run", "msg": f"看的是整个 run（大半是启动）；请求在 {mp} 阶段里",
                           "next": c.cmd("read", "segments", f"{r.run['id']}@{mp}")})
    if A["ix"].get("truncated"):
        c.warnings.append({"code": "truncated", "msg": f"这些进程的时序事件录到了上限，之后的切不出来：{A['ix']['truncated']}"})
    if not A["ix"].get("handoffs"):
        c.warnings.append({"code": "handoffs_empty", "msg": "这段时间里一次交接都没录到：空转只能按调用和时长判"})
    nxt = []
    if segs:
        s = max(segs, key=lambda s: s["dur_us"])
        nxt.append(c.cmd("read", "steps", f"{rid}@t={s['slices_us'][0][0]}-{s['slices_us'][0][1]}/{s['main']}",
                         why=f"最长的 {s['id']} 一轮轮"))
    nxt.append(c.cmd("read", "links", rtext, why="全部交接，两头的函数和那一行"))
    for e in loose[:2]:
        nxt.append(c.cmd("read", "path", f"{rid}@t={e['first_us']}-{e['last_us']}/{e['proc']}", "--limit", "40",
                         why=f"{e['proc']} 没出段：看它这段时间调了什么"))
    data = {"requests": reqs, "segments": segs, "unsegmented": loose,
            "handoffs": groups, "handoffs_in_process": intra, "background": bg, "window_us": [lo, hi],
            "basis": p.basis() | {"gap_before": _seg.GAP_BEFORE, "gap_min_us": _seg.GAP_MIN_US}}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=c.warnings, algo=_steps.ALGO)


def _request_lines(reqs: list[dict], base: int) -> list[str]:
    if not reqs:
        return []
    q = reqs[0]
    if len(reqs) <= 3:
        return [f"请求  {common.short(x['fn'])} @ {x['lane']}  {out.secs(x['t0_us'], base)} → {out.secs(x['t1_us'], base)}"
                + (f"（{out.dur(x['t1_us'] - x['t0_us'])}）" if x["t1_us"] else "（没返回）") for x in reqs]
    last = reqs[-1]
    return [f"请求  {common.short(q['fn'])} ×{len(reqs)} @ {q['lane']}  {out.secs(q['t0_us'], base)} → "
            f"{out.secs(last['t1_us'] or last['t0_us'], base)}（阶段函数被调了 {len(reqs)} 次）"]
