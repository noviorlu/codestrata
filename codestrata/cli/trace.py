"""trace --json：被录程序的 stdout 和录制摘要都转到 stderr，stdout 上只有一个结果信封。录制本身在 __main__._trace。"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from .. import runs as _runs
from ..errors import CodestrataError
from . import common, out


def run_json(a, trace) -> int:
    """trace(a, stdout=fd) -> (退出码, run.json)。录完失败（一个函数都没录到）是 failed_run（退出码 4），下一步给 runs show"""
    def go(a) -> out.Result:
        with contextlib.redirect_stdout(sys.stderr):
            _, run = trace(a, stdout=sys.stderr.fileno())
        repo = Path(a.repo).resolve()
        rd = _runs.runs_dir(repo) / run["id"]
        st = _runs.state(run)
        if st == "failed":
            raise CodestrataError("failed_run", f"run {run['id']} 录完了但一个函数都没录到：" + "；".join(run.get("problems") or []),
                                  next=[out.step("read", "runs", "show", run["id"], repo=repo)])
        mp = common.main_phase(run)
        ref = run["id"] + (f"@{mp}" if mp else "")
        nxt = [out.step("read", "status", ref, repo=repo)]
        if run.get("events") and not (run["events"] or {}).get("error"):
            nxt.append(out.step("read", "lanes", ref, repo=repo))
        return out.Result(data={"id": run["id"], "status": st, "problems": run.get("problems") or [],
                                "returncode": run.get("returncode"), "duration_s": run.get("duration_s"),
                                "phases": common.phases(run, rd), "events": run.get("events"), "gpu": run.get("gpu"),
                                "summary": run.get("summary"), "dir": str(rd.resolve())},
                          text=[], repo=repo, ref={"text": ref, "slices_us": [], "lanes": []}, next=nxt,
                          warnings=[{"code": "partial", "msg": "；".join(run.get("problems") or [])}] if st == "partial" else [])
    return out.run("trace", go, a)
