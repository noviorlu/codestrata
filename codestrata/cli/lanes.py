"""codestrata lanes：这段时间里有哪几列（进程 · 线程），和页面的分列是同一套；每列给稳定写法。"""
from __future__ import annotations

from .. import lanes as _lanes
from .. import laneid as _laneid
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "lanes"
EFFECT = "read"
DOES = "这段时间里有哪几列（进程 · 线程）：稳定写法、有没有调用（轮询也算调用）、是不是只做交接、首末时刻"
USAGE = "codestrata lanes REF [--limit N] [--json]"
EXAMPLE = "codestrata lanes 20261001-170349-run_single_prompt@serving/stage1"

LIMIT = 40


def add_args(p) -> None:
    p.add_argument("ref", metavar="REF", help="RUN[@范围][/列,…]，或页面地址（加单引号）")
    p.add_argument("--limit", type=int, default=LIMIT, help="最多列几列（默认 %(default)s）")


def activity(ln: dict) -> str:
    """一列在这一段里是什么样：gpu / external（只跑仓库外的代码，只做交接）/ idle（这一段没调用，只是交接的一头）/ busy（有调用，轮询也算）"""
    if ln.get("gpu"):
        return "gpu"
    if ln.get("external"):
        return "external"
    if ln.get("idle"):
        return "idle"
    return "busy"


_KIND = {"gpu": "GPU kernel", "external": "只跑仓库外的代码，只做交接", "idle": "这段没调用，只是交接的一头", "busy": "有调用"}


def build(c: common.Ctx) -> tuple[dict, dict[str, str], dict[int, str]]:
    """(lanes.build 的结果, {列 id: 列别名}, {pid: 进程别名})"""
    common.require_events(c)
    idx = common.index(c)
    r = c.res
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None, proc_order=common.proc_order(c, common.labeler(idx)))
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"]),
                              next=[c.cmd("write", "runs", "merge", r.run["id"])]) from None
    procs = _lanes.proc_aliases(r.rd)
    return b, _lanes.run_aliases(r.rd, [ln for ln in b["lanes"] if ln.get("gpu")]), procs


def run(a) -> out.Result:
    c = common.context(a)
    r = c.res
    b, aliases, procs = build(c)
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
                     "first_us": ln.get("first"), "last_us": ln.get("last")})
    shown = rows[:max(a.limit, 1)]
    span = sum(y - x for x, y in r.slices)
    lines = [f"run {r.run['id']} {('@' + r.phase) if r.phase else '整个 run'}（{out.dur(span)}）："
             f"{len(rows)} 列，{len({x['pid'] for x in rows})} 个进程。时刻从这一段开头算"]
    label = {x["id"]: x["lane"] + (f" ×{x['n_threads']}" if x["n_threads"] > 1 else "") for x in shown}
    width = max((len(v) for v in label.values()), default=0)
    cur = None
    for x in shown:
        if x["pid"] != cur:
            cur = x["pid"]
            lines.append(f"{x['proc']}  {x['proc_name']}  pid {x['pid']}")
        what = _KIND[x["activity"]] + (f" · {x['n_calls']} 次" if x["activity"] == "busy" else "")
        lines.append(f"  {label[x['id']].ljust(width)}  {what}  {out.secs(x['first_us'], base)} → {out.secs(x['last_us'], base)}")
    if r.lanes and not rows:
        c.warnings.append({"code": "lane_idle", "msg": f"选的列（{','.join(r.lanes)}）在这段时间里没有活动"})
    if b.get("truncated"):
        c.warnings.append({"code": "truncated", "msg": f"这些进程的时序事件录到了上限：{b['truncated']}"})
    more = None
    if len(shown) < len(rows):
        more = {"shown": len(shown), "total": len(rows),
                "how": out.command("lanes", r.full, "--limit", str(len(rows)), repo=c.flag)}
    nxt = []
    busy = sorted((x for x in rows if x["activity"] == "busy"), key=lambda x: -x["n_calls"])
    if busy:
        nxt.append(c.cmd("read", "path", f"{r.text}/{busy[0]['lane']}", "--limit", "30",
                         why="调用最多的这一列在调什么（调用树）"))
    procs_seen = list(dict.fromkeys(x["proc"] for x in rows))
    if not r.lanes and len(procs_seen) > 1:
        nxt.append(c.cmd("read", "lanes", f"{r.text}/{(busy[0] if busy else rows[0])['proc']}", why="只看一个进程的列"))
    data = {"lanes": shown, "procs": [{"proc": procs[p], "pid": p, "name": names.get(p)}
                                     for p in dict.fromkeys(x["pid"] for x in rows)],
            "window_us": b.get("window"), "truncated": b.get("truncated") or []}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, more=more, warnings=c.warnings)
