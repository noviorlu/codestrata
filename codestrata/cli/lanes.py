"""status REF 里的「列」那一段：这段时间里有哪几列（进程 · 线程），和页面的分列是同一套；每列给稳定写法。"""
from __future__ import annotations

from .. import lanedefault as _lanedefault
from .. import lanes as _lanes
from .. import laneid as _laneid
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

LIMIT = 40


def activity(ln: dict) -> str:
    """一列在这一段里是什么样：external（只跑仓库外的代码，只做交接）/ idle（这一段没调用，只是交接的一头）/ busy（有调用，轮询也算）"""
    if ln.get("external"):
        return "external"
    if ln.get("idle"):
        return "idle"
    return "busy"


_KIND = {"external": "只跑仓库外的代码，只做交接", "idle": "这段没调用，只是交接的一头", "busy": "有调用"}


def build(c: common.Ctx) -> tuple[dict, dict[str, str], dict[int, str], dict[str, str]]:
    """(lanes.build 的结果, {列 id: 列别名}, {pid: 进程别名}, {页面默认收起的列 id: 为什么})"""
    common.require_events(c)
    idx = common.index(c)
    r = c.res
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    label = common.labeler(idx)
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None, proc_order=common.proc_order(c, label))
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    procs = _lanes.proc_aliases(r.rd)
    folded = _lanedefault.default_folded(b)    # 和页面同一份
    return b, _lanes.run_aliases(r.rd), procs, folded


def section(c: common.Ctx) -> tuple[list[str], dict, dict | None]:
    """(文字的几行, data 里的列, more)：status REF 用"""
    r = c.res
    b, aliases, procs, folded = build(c)
    want = set(_laneid.select(r.lanes, aliases)) if r.lanes else set(aliases)
    names = _lanes.proc_names(r.rd)
    base = r.slices[0][0] if r.slices else 0
    rows = []
    for ln in b["lanes"]:
        if ln["id"] not in want:
            continue
        rows.append({"lane": aliases[ln["id"]], "id": ln["id"], "pid": ln["pid"], "proc": procs.get(ln["pid"]),
                     "proc_name": names.get(ln["pid"]), "thread": ln.get("thread"), "thread_names": ln.get("names") or [],
                     "n_threads": ln.get("n_threads") or 1, "activity": activity(ln),
                     "n_calls": sum(v.get("n") or 0 for v in (ln.get("nodes") or {}).values()),
                     "first_us": ln.get("first"), "last_us": ln.get("last"), "page_folded": folded.get(ln["id"])})
    shown = rows[:LIMIT]
    lines = [f"列    {len(rows)} 列，{len({x['pid'] for x in rows})} 个进程（时刻从这一段开头算）"]
    if folded:
        lines.append(f"      页面默认只看 {len(b['lanes']) - len(folded)} / {len(b['lanes'])} 列：标「页面默认收起」的收进每个进程的「其他 N 列」")
    label = {x["id"]: x["lane"] + (f" ×{x['n_threads']}" if x["n_threads"] > 1 else "") for x in shown}
    width = max((len(v) for v in label.values()), default=0)
    cur = None
    for x in shown:
        if x["pid"] != cur:
            cur = x["pid"]
            lines.append(f"  {x['proc']}  {x['proc_name']}  pid {x['pid']}")
        what = _KIND[x["activity"]] + (f" · {x['n_calls']} 次" if x["activity"] == "busy" else "")
        lines.append(f"    {label[x['id']].ljust(width)}  {what}  {out.secs(x['first_us'], base)} → {out.secs(x['last_us'], base)}"
                     + (f"  （页面默认收起：{x['page_folded']}）" if x["page_folded"] else ""))
    if r.lanes and not rows:
        c.warnings.append({"code": "lane_idle", "msg": f"选的列（{','.join(r.lanes)}）在这段时间里没有活动"})
    if b.get("truncated"):
        c.warnings.append({"code": "truncated", "msg": f"这些进程的时序事件录到了上限：{b['truncated']}"})
    more = {"shown": len(shown), "total": len(rows), "how": "REF 里加 /进程 只看一个进程的列"} if len(shown) < len(rows) else None
    data = {"lanes": shown, "procs": [{"proc": procs[p], "pid": p, "name": names.get(p)}
                                     for p in dict.fromkeys(x["pid"] for x in rows)],
            "window_us": b.get("window"), "truncated": b.get("truncated") or [],
            "page_default": None if not folded else {"shown": len(b["lanes"]) - len(folded), "total": len(b["lanes"])}}
    return lines, data, more
