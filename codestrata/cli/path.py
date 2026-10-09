"""codestrata path：函数级的请求路径（每个进程、每条线程的调用上下文树）。

默认照旧打整棵树；给了列、--limit 或 --json 时才截（默认 200 行）。节标题是列的稳定写法。"""
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
DOES = "函数级的请求路径：每个进程、每条线程的调用上下文树（默认整棵树，很长；给了列 / --limit / --json 时截到 200 行）"
USAGE = "codestrata path REF [--depth N] [--limit N] [--json]"
EXAMPLE = "codestrata path 20261001-170349-run_single_prompt@serving/stage1/MainThread --limit 60"

LIMIT = 200


def add_args(p) -> None:
    p.add_argument("ref", nargs="+", metavar="REF",
                   help="RUN[@范围][/列,…] 或页面地址；老写法 path <repo> RUN 也认（第一个是仓库）")
    p.add_argument("--depth", type=int, default=None, help="只打这么多层（0 是根）")
    p.add_argument("--limit", type=int, default=None, help=f"最多几行（给了列或 --json 时默认 {LIMIT}）")


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
    procs = _laneid.proc_aliases(_lanes.proc_names(r.rd))

    def lane_id(pid: int, tname: str) -> str:
        return f"{pid}:{_lanes.thread_group(tname)}"

    try:
        p = _path.request_path(idx, r.rd, r.run, r.phase, hot, max_rows=None)
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    aliases = _aliases(p, procs, lane_id)           # 对着这一段里全部的节算（截之前）
    keep = None
    if r.lanes:
        want = set(_laneid.select(r.lanes, aliases))
        keep = lambda pid, tname: lane_id(pid, tname) in want    # noqa: E731
    _path.trim(p, a.limit if a.limit is not None else (LIMIT if r.lanes or a.json else None), keep)
    lane_of = lambda pid, tname: aliases.get(lane_id(pid, tname), f"{pid}/{tname}")   # noqa: E731
    for pr in p["procs"]:
        for th in pr["threads"]:
            th["lane"] = lane_of(pr["pid"], th["name"])
    shown = sum(len(th["rows"]) for pr in p["procs"] for th in pr["threads"])
    more = None
    if p["rows_cut"]:
        more = {"shown": shown, "total": shown + p["rows_cut"],
                "how": out.command("path", r.full, "--limit", str(shown + p["rows_cut"]), repo=c.flag)}
    text = _path.format_text(p, a.depth, lane_of=lane_of).split("\n")
    if p["rows_cut"]:
        text = [x for x in text if not x.startswith("（还有 ")]
    nxt = []
    if not r.lanes and len(p["procs"]) > 1:
        first = p["procs"][0]["threads"][0]
        nxt.append(c.cmd("read", "path", f"{r.text}/{first['lane']}", why="只看一列"))
    return out.Result(data=p, text=text, repo=c.repo, ref=c.ref_json(), next=nxt, more=more, warnings=c.warnings)


def _aliases(p: dict, procs: dict[int, str], lane_id) -> dict[str, str]:
    """请求路径的各节 → {列 id: 列别名}（和 lanes 同一套写法）"""
    seen: dict[str, dict] = {}
    for pr in p["procs"]:
        for th in pr["threads"]:
            lid = lane_id(pr["pid"], th["name"])
            seen.setdefault(lid, {"id": lid, "pid": pr["pid"], "thread": _lanes.thread_group(th["name"])})
    return _laneid.lane_aliases(list(seen.values()), procs)
