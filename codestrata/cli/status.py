"""codestrata status：agent 的第一条命令。仓库、索引、run 的状态、REF 规整成什么、各阶段的窗口。"""
from __future__ import annotations

import datetime as _dt

from .. import runs as _runs
from .. import seq as _seq
from ..ui import source as _source
from . import common, out

NAME = "status"
EFFECT = "read"
DOES = "仓库、索引、run 的状态、REF 落在哪几片时间、各阶段的窗口；不给 REF 列最近 5 个 run"
USAGE = "codestrata status [REF|'页面地址'] [-C 目录] [--json]"
EXAMPLE = "codestrata status 'http://127.0.0.1:8900/#run=20261001-170349-run_single_prompt@serving'"

_HOW = {"C": "-C 指定", "page": "按页面地址的端口问到", "run": "按 run id 在已知仓库里找到", "cwd": "从当前目录往上找到"}


def add_args(p) -> None:
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN[@范围][/列]，或页面地址（加单引号）")


def _when(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def run(a) -> out.Result:
    c = common.context(a, need_run=False)
    repo = c.repo
    ix = repo / ".codestrata" / "index.json"
    data: dict = {"repo": str(repo), "found_by": c.how}
    nxt: list[dict] = []
    if ix.is_file():
        lag = _source.index_lag(repo)
        data["index"] = {"scanned": _when(ix.stat().st_mtime), "changed_since": lag}
        idx_text = f"{data['index']['scanned']} scan" + (f"，之后改过 {lag} 个文件" if lag else "")
    else:
        data["index"] = None
        idx_text = "还没 scan"
        nxt.append(c.cmd("write", "scan", why="建索引"))
    lines = [f"仓库  {repo}（{_HOW[c.how]}；{idx_text}）"]

    if c.res is None:                                  # 没给 REF：最近 5 个 run
        try:
            cat = _runs.catalog(repo)
        except SystemExit as e:
            cat = []
            c.warnings.append({"code": "runs_unreadable", "msg": str(e)})
        data["runs"] = [_brief(r) for r in cat[:5]]
        data["n_runs"] = len(cat)
        if not cat:
            lines.append("run   还没录过")
        for r in data["runs"]:
            lines.append(f"run   {r['id']}  {r['status']}  阶段 {', '.join(r['phases']) or '—'}")
        if cat:
            nxt.insert(0, c.cmd("read", "status", cat[0]["id"]))
        if c.ref is not None and c.ref.page and c.ref.run is None:
            c.warnings.append({"code": "need_view", "msg": "页面地址里没有 run（页面只开着静态图）"})
        return out.Result(data=data, text=lines, repo=repo, next=nxt, warnings=c.warnings)

    r = c.res
    run_ = r.run
    st = run_.get("status_shown") or run_.get("status")
    ev = run_.get("events") or {}
    trunc = ev.get("truncated") or []
    flags = [st, "有时序事件" if ev else "没录时序事件", "录了 GPU" if run_.get("gpu") else "没录 GPU",
             f"截断了 {len(trunc)} 个进程" if trunc else "没截断"]
    lines.append(f"run   {run_['id']}（case {run_.get('case')}）：{' · '.join(flags)}")
    for p in run_.get("problems") or []:
        lines.append(f"      问题：{p}")
    end = r.end_us
    phases = []
    if end:
        for name, a0, b0 in _seq.phase_segments(run_, end):
            phases.append({"name": name, "t0_us": a0, "t1_us": b0})
    sl = r.slices
    span = sum(b - a for a, b in sl)
    rng = " · ".join(f"t={a}-{b}" for a, b in sl)
    lines.append(f"范围  {r.full} = {rng}（{out.dur(span)}）" if sl else f"范围  {r.full}（run 的时刻未知）")
    if phases:
        lines.append("阶段  " + " · ".join(f"{p['name']} t={p['t0_us']}-{p['t1_us']}（{out.dur(p['t1_us'] - p['t0_us'])}）"
                                          for p in phases))
    data.update({"run": {"id": run_["id"], "case": run_.get("case"), "status": st, "problems": run_.get("problems") or [],
                         "events": bool(ev), "gpu": bool(run_.get("gpu")), "truncated": trunc,
                         "created": run_.get("created"), "end_us": end},
                 "phases": phases})
    if st in ("中断",):
        nxt.append(c.cmd("write", "runs", "merge", run_["id"], why="录制中断了，从原始数据合并"))
    elif ev:
        nxt.append(c.cmd("read", "lanes", r.full, why="这段时间里有哪几列"))
    if r.lanes:
        data["lanes"] = r.lanes
    return out.Result(data=data, text=lines, repo=repo, ref=c.ref_json(), next=nxt, warnings=c.warnings)


def _brief(r: dict) -> dict:
    return {"id": r["id"], "case": r.get("case"), "status": r.get("status_shown") or r.get("status"),
            "created": r.get("created"), "phases": [p["name"] for p in r.get("phases") or []]}
