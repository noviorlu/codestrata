"""codestrata status：agent 的第一条命令。仓库、索引、run 的状态、REF 规整成什么、各阶段的窗口。"""
from __future__ import annotations

import datetime as _dt

from .. import locate as _locate
from .. import runs as _runs
from ..ui import source as _source
from . import common, out

NAME = "status"
EFFECT = "read"
DOES = "仓库、索引、run 的状态、REF 落在哪几片时间、各阶段的窗口；不给 REF 列最近 5 个 run"
USAGE = "codestrata status [REF|'页面地址'] [-C 目录] [--json]"
EXAMPLE = "codestrata status 'http://127.0.0.1:8900/#run=20261001-170349-run_single_prompt@serving'"

_HOW = {"C": "-C 指定", "page": "按页面地址的端口问到", "run": "按 run id 在已知仓库里找到", "cwd": "从当前目录往上找到"}
_STATE = {"ok": "录完了", "partial": "只录了一部分", "failed": "失败", "recording": "还在录", "interrupted": "录制中断了"}
SHOW = 5


def add_args(p) -> None:
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN[@范围][/列]，或页面地址（加单引号）")


def run(a) -> out.Result:
    c = common.context(a, need_run=False, allow_fresh=True)
    repo = c.repo
    ix = repo / ".codestrata" / "index.json"
    data: dict = {"repo": str(repo), "found_by": c.how}
    nxt: list[dict] = []
    if ix.is_file():
        lag = _source.index_lag(repo)
        when = _dt.datetime.fromtimestamp(ix.stat().st_mtime).astimezone()
        data["index"] = {"scanned": when.isoformat(timespec="seconds"), "changed_since": lag}
        idx_text = f"{when:%Y-%m-%d %H:%M} scan" + (f"，之后改过 {lag} 个文件" if lag else "")
    else:
        data["index"] = None
        idx_text = "还没 scan"
        nxt.append(out.step("write", "scan", repo=repo, why="建索引"))
    lines = [f"仓库  {repo}（{_HOW[c.how]}；{idx_text}）"]
    if c.res is None:
        return _recent(c, data, lines, nxt)

    r = c.res
    run_ = r.run
    st = _runs.state(run_)
    ev = run_.get("events") or {}
    trunc = ev.get("truncated") or []
    flags = [_STATE.get(st, st)]
    if st == "recording":
        flags.append("时序事件录完才有")
        nxt.append(c.cmd("read", "runs", "wait", run_["id"], why="等它录完"))
    else:
        flags += ["有时序事件" if ev else "没录时序事件", "录了 GPU" if run_.get("gpu") else "没录 GPU",
                  f"{len(trunc)} 个进程的时序事件到了行数上限" if trunc else "时序事件没到行数上限"]
    lines.append(f"run   {run_['id']}（case {run_.get('case')}）：{' · '.join(flags)}")
    for p in run_.get("problems") or []:
        lines.append(f"      问题：{p}")
    phases = common.phases(run_, r.rd)
    sl = r.slices
    span = sum(b - a for a, b in sl)
    rng = " · ".join(f"t={a}-{b}" for a, b in sl)
    lines.append(f"范围  {r.full} = {rng}（{out.dur(span)}）" if sl else f"范围  {r.full}（run 的时刻未知）")
    if phases:
        lines.append("阶段  " + " · ".join(f"{p['name']} t={p['t0_us']}-{p['t1_us']}（{out.dur(p['t1_us'] - p['t0_us'])}）"
                                          for p in phases))
    data.update({"run": {"id": run_["id"], "case": run_.get("case"), "status": st, "problems": run_.get("problems") or [],
                         "events": bool(ev), "gpu": bool(run_.get("gpu")), "truncated": trunc,
                         "created": run_.get("created"), "end_us": r.end_us},
                 "phases": phases, "lanes": r.lanes})
    if st == "interrupted":
        nxt.append(c.cmd("write", "runs", "merge", run_["id"], why="录制中断了，从原始数据合并"))
    elif ev and st != "recording":
        # 没给范围、有 serving 的：建议看 serving（整个 run 里大半是启动）
        target = r.full if r.phase or not common.main_phase(run_) else f"{run_['id']}@{common.main_phase(run_)}" + (
            "/" + ",".join(r.lanes) if r.lanes else "")
        nxt.append(c.cmd("read", "lanes", target, why="这段时间里有哪几列"))
    return out.Result(data=data, text=lines, repo=repo, ref=c.ref_json(), next=nxt, warnings=c.warnings)


def _recent(c: common.Ctx, data: dict, lines: list[str], nxt: list[dict]) -> out.Result:
    """没给 REF：最近 SHOW 个 run"""
    cat = _locate.catalog(c.repo)
    c.warnings += _locate.legacy_warning(c.repo)
    rows = [{"id": r["id"], "case": r.get("case"), "status": _runs.state(r), "created": r.get("created"),
             "phases": [p["name"] for p in r.get("phases") or []]} for r in cat[:SHOW]]
    data["runs"], data["n_runs"] = rows, len(cat)
    if not cat:
        lines.append("run   还没录过")
    for r in rows:
        lines.append(f"run   {r['id']}  {_STATE.get(r['status'], r['status'])}  阶段 {', '.join(r['phases']) or '—'}")
    if cat:
        mp = common.main_phase(cat[0])
        nxt.insert(0, c.cmd("read", "status", cat[0]["id"] + (f"@{mp}" if mp else "")))
    more = None
    if len(cat) > len(rows):
        more = {"shown": len(rows), "total": len(cat), "how": out.command("runs", "ls", repo=c.repo)}
    if c.ref is not None and c.ref.page and c.ref.run is None:
        c.warnings.append({"code": "need_view", "msg": "页面地址里没有 run（页面只开着静态图）"})
    return out.Result(data=data, text=lines, repo=c.repo, next=nxt, warnings=c.warnings, more=more)
