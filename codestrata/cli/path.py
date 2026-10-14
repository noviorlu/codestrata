"""codestrata path：函数级的请求路径（每个进程、每条线程的调用上下文树）。

每列默认截到 60 行（--limit 改，--limit 0 不截）。节标题是列的稳定写法。
--time：先列出「自己的时间」最多的 5 处；--unseen：只列代码里看不出会调到它的调用，按次数排。"""
from __future__ import annotations

from .. import align as _align
from .. import lanes as _lanes
from .. import laneid as _laneid
from .. import path as _path
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "path"
EFFECT = "read"
DOES = "函数级的请求路径：每个进程、每条线程的调用上下文树（每列默认截到 60 行）"
USAGE = "codestrata path REF [--depth N] [--limit N] [--time] [--unseen] [--json]"
EXAMPLE = "codestrata path 20261001-170349-run_single_prompt@serving/stage1/MainThread --limit 30"

LIMIT = 60          # 每列最多几行（默认）


def add_args(p) -> None:
    p.add_argument("ref", nargs="+", metavar="REF",
                   help="RUN[@范围][/列,…] 或页面地址；老写法 path <repo> RUN 也认（第一个是仓库）")
    p.add_argument("--depth", type=int, default=None, help="只打这么多层（0 是根）")
    p.add_argument("--limit", type=int, default=None,
                   help=f"每列最多几行（默认 {LIMIT}，0 是不截；不算 --depth 藏掉的）；和 --unseen 一起时是列几处（默认 40）")
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
        p = _path.request_path(idx, r.rd, r.run, r.phase, hot, max_rows=None, proc_order=common.proc_order(c, common.labeler(idx)))
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    aliases = _lanes.run_aliases(r.rd)
    keep = None
    if r.lanes:
        want = set(_laneid.select(r.lanes, aliases))
        keep = lambda pid, tname: lane_id(pid, tname) in want    # noqa: E731
    # --unseen 先筛「看不出」的再截（截了树再筛，总数会跟着 --limit 变）；--limit 在这里是列几处
    cap = None if a.unseen else (a.limit or None) if a.limit is not None else LIMIT
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
        limit = a.limit or 40
        text, p = _unseen(p, limit)
        if p["n_unseen"] > limit:
            more = {"shown": limit, "total": p["n_unseen"],
                    "how": out.command("path", r.full, "--unseen", *(["--depth", str(a.depth)] if a.depth is not None else []),
                                       "--limit", str(p["n_unseen"]), repo=c.flag)}
    else:
        text = _path.format_text(p, a.depth, lane_of=lane_of).split("\n")
    if a.time:
        top = _self_time_top(r, {th["lane"] for th in ths}, aliases, common.labeler(idx))
        p["self_time"] = top
        span_us = sum(y - x for x, y in r.slices)
        text = [f"自己的时间最多的 {len(top)} 处（时长减去它调的仓库函数；这段 {out.dur(span_us)}"
                + (f"，{len(r.slices)} 片加起来" if len(r.slices) > 1 else "") + "）："] + [
            f"  {out.dur(x['us']):>10}  {x['lane']}  {common.short(x['fn'])}" for x in top] + [""] + text
    return out.Result(data=p, text=text, repo=c.repo, ref=c.ref_json(), more=more, warnings=c.warnings)


def _self_time_top(r, lanes: set[str], aliases: dict[str, str], label, n: int = 5) -> list[dict]:
    """这几列里「自己的时间」最多的 n 处：[{lane, fn, us}]（每条线程各算、每一片各算，同一列合起来）"""
    from collections import Counter
    from .. import steps as _steps
    ix = _seq.span_index(r.rd)
    keys = ix["keys"]
    want = {lid for lid, al in aliases.items() if al in lanes}
    tot: Counter = Counter()
    by_pid: dict[int, set] = {}
    for pid_s, ts in ix["threads"].items():
        for tid_s, name in ts.items():
            if _lanes.lane_id(int(pid_s), name) in want:
                by_pid.setdefault(int(pid_s), set()).add(int(tid_s))
    for pid, tids in by_pid.items():
        lr = _steps.lane_rows(_seq.pid_rows(r.rd, pid), tids)
        for tid in tids:
            th = ix["threads"][str(pid)][str(tid)]
            al = aliases.get(_lanes.lane_id(pid, th))
            for lo, hi in r.slices:              # 几片的 REF（还有几段的阶段）：一片一片算再加起来，和树一样只算片里的
                own, _, _ = _steps.self_times(lr, tid, lo, hi)
                for b, us in own.items():
                    tot[(al, keys[b])] += us
    return [{"lane": al, "key": k, "fn": label(k), "us": us} for (al, k), us in tot.most_common(n)]


def _unseen(p: dict, limit: int) -> tuple[list[str], dict]:
    """只留代码里看不出会调到它的行，按次数排：(文字, 换掉了 procs 的 path)。GPU kernel 不列，单说一句有几处
    （Python 经扩展 / PyTorch 转几道才启动它，本来就看不出是哪一行；用户 10-13 定）"""
    rows, gpu = [], 0
    for pr in p["procs"]:
        for th in pr["threads"]:
            for x in th["rows"]:
                ln = x.get("line") or {}
                if ln.get("status") == "trace" and not x.get("before"):
                    if (ln.get("note") or {}).get("k") == "gpu":
                        gpu += 1
                        continue
                    rows.append({"lane": th["lane"], "fn": x["fn"], "from": x.get("from"), "n": x.get("n") or 0,
                                 "line": {"f": ln.get("f"), "l": ln.get("l")}, "note": ln.get("note"),
                                 "why": _align.note_short(ln.get("note"))})
    rows.sort(key=lambda x: -x["n"])
    text = [f"代码里看不出会调到它的调用 {len(rows)} 处（按次数排，给了前 {min(limit, len(rows))} 处）："]
    for x in rows[:limit]:
        where = f"  ← {x['line']['f']}:{x['line']['l']}" if x["line"]["l"] else ""
        text.append(f"  ×{x['n']:<6} {x['lane']}  {common.short(x['from'])} → {common.short(x['fn'])}{where}"
                    + (f"  （{x['why']}）" if x["why"] else ""))
    if gpu:
        text.append(f"另有 {gpu} 处是 GPU kernel（Python 经扩展 / PyTorch 转几道才启动它，本来就看不出是哪一行；不列在上面）")
    return text, {k: v for k, v in p.items() if k != "procs"} | {"unseen": rows[:limit], "n_unseen": len(rows), "n_unseen_gpu": gpu}
