"""codestrata path：函数级的请求路径（每个进程、每条线程的调用上下文树）。

默认照旧打整棵树；给了列、--limit 或 --json 时才截（每列 60 行）。节标题是列的稳定写法。
--time：先列出「自己的时间」最多的 5 处（和 steps --why 同一个算法）；--unseen：只列代码里看不出会调到它的调用，按次数排。"""
from __future__ import annotations

from .. import lanes as _lanes
from .. import laneid as _laneid
from .. import path as _path
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "path"
EFFECT = "read"
DOES = "函数级的请求路径：每个进程、每条线程的调用上下文树（默认整棵树，很长；给了列 / --limit / --json 时每列截到 60 行）"
USAGE = "codestrata path REF [--depth N] [--limit N] [--time] [--unseen] [--json]"
EXAMPLE = "codestrata path 20261001-170349-run_single_prompt@serving/stage1/MainThread --limit 30"

LIMIT = 60          # 每列最多几行（给了列 / --json 时的默认）


def add_args(p) -> None:
    p.add_argument("ref", nargs="+", metavar="REF",
                   help="RUN[@范围][/列,…] 或页面地址；老写法 path <repo> RUN 也认（第一个是仓库）")
    p.add_argument("--depth", type=int, default=None, help="只打这么多层（0 是根）")
    p.add_argument("--limit", type=int, default=None, help=f"每列最多几行（给了列或 --json 时默认 {LIMIT}；不算 --depth 藏掉的）")
    p.add_argument("--time", action="store_true", help="先列出自己的时间（减去它调的仓库函数）最多的 5 处")
    p.add_argument("--unseen", action="store_true", help="只列代码里看不出会调到它的调用（按次数排）")


def run(a) -> out.Result:
    if len(a.ref) > 2:
        raise CodestrataError("usage", "path 只收一个 REF（老写法是 path <repo> RUN）")
    if len(a.ref) == 2:                              # 老写法：path <repo> RUN
        if a.C:
            raise CodestrataError("usage", "给了 -C 就不要再写仓库")
        a.C, a.ref = a.ref[0], a.ref[1]
    else:
        a.ref = a.ref[0]
    c = common.context(a)
    common.require_events(c)
    idx = common.index(c)
    r = c.res
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    lane_id = _lanes.lane_id

    try:
        p = _path.request_path(idx, r.rd, r.run, r.phase, hot, max_rows=None)
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    aliases = _lanes.run_aliases(r.rd)
    keep = None
    if r.lanes:
        want = set(_laneid.select(r.lanes, aliases))
        keep = lambda pid, tname: lane_id(pid, tname) in want    # noqa: E731
    cap = a.limit if a.limit is not None else (LIMIT if r.lanes or a.json else None)
    total_rows = {id(th): len([x for x in th["rows"] if a.depth is None or x["d"] <= a.depth])
                  for pr in p["procs"] for th in pr["threads"]}
    _path.trim(p, None, keep, max_depth=a.depth, per_thread=cap)
    lane_of = lambda pid, tname: aliases.get(lane_id(pid, tname), f"{pid}/{tname}")   # noqa: E731
    for pr in p["procs"]:
        for th in pr["threads"]:
            th["lane"] = lane_of(pr["pid"], th["name"])
    ths = [th for pr in p["procs"] for th in pr["threads"]]
    shown = sum(len(th["rows"]) for th in ths)
    more = None
    if p["rows_cut"]:
        widest = max(total_rows[id(th)] for th in ths)
        more = {"shown": shown, "total": shown + p["rows_cut"],
                "how": out.command("path", r.full, *(["--depth", str(a.depth)] if a.depth is not None else []),
                                   "--limit", str(widest), repo=c.flag)}
        for th in ths:                               # 每节末尾写截了几行（format_text 打）
            th["cut"] = total_rows[id(th)] - len(th["rows"])
    if a.unseen:
        text, p = _unseen(p, a.limit or 40)
        more = None
    else:
        text = _path.format_text(p, a.depth, lane_of=lane_of).split("\n")
    if a.time:
        top = _self_time_top(r, {th["lane"] for th in ths}, aliases, common.labeler(idx))
        p["self_time"] = top
        lo, hi = r.slices[0][0], r.slices[-1][1]
        text = [f"自己的时间最多的 {len(top)} 处（时长减去它调的仓库函数；这段 {out.dur(hi - lo)}）："] + [
            f"  {out.dur(x['us']):>10}  {x['lane']}  {common.short(x['fn'])}" for x in top] + [""] + text
    nxt = []
    if not r.lanes and len(p.get("procs") or []) > 1:
        first = p["procs"][0]["threads"][0]
        nxt.append(c.cmd("read", "path", f"{r.text}/{first['lane']}", why="只看一列"))
    return out.Result(data=p, text=text, repo=c.repo, ref=c.ref_json(), next=nxt, more=more, warnings=c.warnings)


def _self_time_top(r, lanes: set[str], aliases: dict[str, str], label, n: int = 5) -> list[dict]:
    """这几列里「自己的时间」最多的 n 处：[{lane, fn, us}]（每条线程各算，同一列合起来）"""
    from collections import Counter
    from .. import steps as _steps
    ix = _seq.span_index(r.rd)
    keys = ix["keys"]
    want = {lid for lid, al in aliases.items() if al in lanes}
    lo, hi = r.slices[0][0], r.slices[-1][1]
    tot: Counter = Counter()
    by_pid: dict[int, set] = {}
    for pid_s, ts in ix["threads"].items():
        for tid_s, name in ts.items():
            if _lanes.lane_id(int(pid_s), name) in want:
                by_pid.setdefault(int(pid_s), set()).add(int(tid_s))
    for pid, tids in by_pid.items():
        lr = _steps.lane_rows(_seq.pid_rows(r.rd, pid), tids)
        for tid in tids:
            own, _, _ = _steps.self_times(lr, tid, lo, hi)
            th = ix["threads"][str(pid)][str(tid)]
            al = aliases.get(_lanes.lane_id(pid, th))
            for b, us in own.items():
                tot[(al, keys[b])] += us
    return [{"lane": al, "key": k, "fn": label(k), "us": us} for (al, k), us in tot.most_common(n)]


def _unseen(p: dict, limit: int) -> tuple[list[str], dict]:
    """只留代码里看不出会调到它的行，按次数排：(文字, 换掉了 procs 的 path)"""
    rows = []
    for pr in p["procs"]:
        for th in pr["threads"]:
            for x in th["rows"]:
                ln = x.get("line") or {}
                if ln.get("status") == "trace" and not x.get("before"):
                    rows.append({"lane": th["lane"], "fn": x["fn"], "from": x.get("from"), "n": x.get("n") or 0,
                                 "line": {"f": ln.get("f"), "l": ln.get("l")}})
    rows.sort(key=lambda x: -x["n"])
    text = [f"代码里看不出会调到它的调用 {len(rows)} 处（按次数排，给了前 {min(limit, len(rows))} 处）："]
    for x in rows[:limit]:
        where = f"  ← {x['line']['f']}:{x['line']['l']}" if x["line"]["l"] else ""
        text.append(f"  ×{x['n']:<6} {x['lane']}  {common.short(x['from'])} → {common.short(x['fn'])}{where}")
    return text, {k: v for k, v in p.items() if k != "procs"} | {"unseen": rows[:limit], "n_unseen": len(rows)}
