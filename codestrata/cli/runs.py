"""runs 命令里给 agent 的部分：`runs ls / show --json`（信封）和 `runs wait`（等还在录的 run 录完）。
文字版的 ls / show 和写的动作还在 __main__.cmd_runs。"""
from __future__ import annotations

import time
from pathlib import Path

from .. import ref as _ref
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from ..ui import load as _load
from . import out


def _repo(a) -> Path:
    repo = Path(a.repo).resolve()
    if not (repo / ".codestrata").is_dir():
        raise CodestrataError("repo_unknown", f"{repo} 下没有 .codestrata：还没 scan / trace 过？")
    return repo


def _pick(repo: Path, name: str) -> dict:
    cat = _ref.catalog(repo)
    hit = _runs.pick(cat, name.partition("@")[0])
    if hit is None:
        raise CodestrataError("run_not_found", f"{repo} 里没有叫 {name!r} 的 run 或 case",
                              candidates=sorted({r.get("case") for r in cat if r.get("case")}))
    return hit


def _windows(run: dict, rd: Path) -> list[dict]:
    """各阶段的微秒窗口"""
    end = _seq.run_end(run, rd)
    return [{"name": n, "t0_us": a, "t1_us": b} for n, a, b in _seq.phase_segments(run, end)] if end else []


def ls(a) -> out.Result:
    repo = _repo(a)
    try:
        idx = _load.load_index(repo)
    except SystemExit:
        idx = None
    rows = []
    for r in _ref.catalog(repo):
        if a.case and r.get("case") != a.case:
            continue
        rd = _runs.runs_dir(repo) / r["id"]
        stale = None
        if idx is not None:
            try:
                stale = _runs.stale_counts(repo, idx, rd)
            except (OSError, ValueError):
                pass
        rows.append({**_runs.brief(r, rd, stale), "phases_us": _windows(r, rd), "end_us": _seq.run_end(r, rd)})
    return out.Result(data={"runs": rows}, text=[], repo=repo, warnings=_ref.legacy_warning(repo))


def show(a) -> out.Result:
    repo = _repo(a)
    run = _pick(repo, a.ref)
    rd = _runs.runs_dir(repo) / run["id"]
    detail = _runs.read_json(rd / "detail.json") if (rd / "detail.json").is_file() else {}
    fs = None
    try:
        fs = _runs.file_state(repo, _load.load_index(repo), detail)
    except SystemExit:
        pass
    data = {"run": run, "phases_us": _windows(run, rd), "end_us": _seq.run_end(run, rd),
            "procs": _runs.procs_grouped(detail.get("procs")), "files": detail.get("files") or [],
            "gpu_devices": detail.get("gpu") or [], "leftovers": detail.get("leftovers") or [],
            "file_state": fs, "rerun": _runs.rerun_command(run, repo), "dir": str(rd.resolve())}
    return out.Result(data=data, text=[], repo=repo, ref={"text": run["id"], "slices_us": [], "lanes": []})


def wait(a) -> out.Result:
    """等 run 录完（不再是 recording，或录制的进程没了）。超时报 timeout（退出码 5）"""
    repo = _repo(a)
    run = _pick(repo, a.ref)
    rid, t0 = run["id"], time.monotonic()
    rj = _runs.runs_dir(repo) / rid / "run.json"
    while True:
        try:
            run = _runs.read_json(rj)
        except (OSError, ValueError):
            pass
        if not _runs.live(run):
            break
        if time.monotonic() - t0 > a.timeout:
            raise CodestrataError("timeout", f"等了 {a.timeout:.0f} s，run {rid} 还在录",
                                  next=[out.step("read", "runs", "wait", rid, "--timeout", str(int(a.timeout)), repo=repo)])
        time.sleep(0.5)
    st = run.get("status")
    if st == "recording":
        st = "中断"
    lines = [f"run {rid}：{st}，等了 {time.monotonic() - t0:.1f} s"]
    nxt = [out.step("read", "status", rid, repo=repo)]
    if st == "中断":
        nxt = [out.step("write", "runs", "merge", rid, repo=repo, why="录制中断了，从原始数据合并")]
    return out.Result(data={"id": rid, "status": st, "problems": run.get("problems") or []}, text=lines, repo=repo,
                      next=nxt)
