"""几个命令共用的：REF → 仓库 + run，要求有时序事件，加载索引。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import locate as _locate
from .. import ref as _ref
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from ..ui import load as _load
from . import out


@dataclass
class Ctx:
    repo: Path
    how: str                     # 仓库怎么找到的：C / page / run / cwd
    flag: Path | None            # next 里的命令要不要带 -C（仓库不是从当前目录找到的就带）
    warnings: list[dict]
    ref: _ref.Ref | None
    res: _locate.Resolved | None = None

    def cmd(self, effect: str, *parts: str, why: str = "") -> dict:
        return out.step(effect, *parts, repo=self.flag, why=why)

    def ref_json(self) -> dict | None:
        r = self.res
        if r is None:
            return None
        return {"text": r.full, "slices_us": [list(s) for s in r.slices], "lanes": r.lanes}


def context(a, need_run: bool = True, allow_fresh: bool = False) -> Ctx:
    """命令行的 REF（a.ref）和 -C（a.C）→ Ctx。出错时把之前的警告（比如页面地址问不到）带进错误里"""
    ref, repo, how, warns = _locate.from_cli(getattr(a, "ref", None), a.C, Path.cwd(), allow_fresh=allow_fresh)
    c = Ctx(repo=repo, how=how, flag=None if how == "cwd" else repo, warnings=warns, ref=ref)
    if ref is not None and (need_run or ref.run):
        try:
            c.res = _locate.resolve(repo, ref)
        except CodestrataError as e:
            e.warnings = warns + e.warnings
            raise
        c.warnings += c.res.warnings
    elif need_run:
        raise CodestrataError("usage", "要给 REF（run id / case 名，可加 @阶段、/列；或页面地址）")
    return c


def index(c: Ctx) -> dict:
    """仓库的索引；没 scan 过报 not_scanned"""
    if not (c.repo / ".codestrata" / "index.json").is_file():
        raise CodestrataError("not_scanned", f"{c.repo} 还没 scan", next=[out.step("write", "scan", repo=c.repo)])
    return _load.load_index(c.repo)


def require_events(c: Ctx) -> None:
    """要读时序事件的命令：run 要录完、录了 --events"""
    run = c.res.run
    st = run.get("status")
    if st == "recording":
        if _runs.live(run):
            raise CodestrataError("recording", f"run {run['id']} 还在录", warnings=c.warnings,
                                  next=[c.cmd("read", "runs", "wait", run["id"], why="等它录完")])
        raise CodestrataError("interrupted_run", f"run {run['id']} 录制中断了，要先从原始数据合并", warnings=c.warnings,
                              next=[c.cmd("write", "runs", "merge", run["id"])])
    if not (c.res.rd / "counts.json.gz").is_file():
        raise CodestrataError("failed_run", f"run {run['id']} 没有计数（{st}）", warnings=c.warnings,
                              next=[c.cmd("read", "runs", "show", run["id"])])
    if not run.get("events"):
        raise CodestrataError("no_events", f"run {run['id']} 没录时序事件（trace 时加了 --no-events，或是 3.12 以下的老 run）",
                              warnings=c.warnings)


def phases(run: dict, rd: Path) -> list[dict]:
    """各阶段的时间段 [{name, t0_us, t1_us}]（同一个阶段切走又切回来就有几段）；不知道 run 的终点时是空的"""
    end = _seq.run_end(run, rd)
    return [{"name": n, "t0_us": a, "t1_us": b} for n, a, b in _seq.phase_segments(run, end)] if end else []


def main_phase(run: dict) -> str | None:
    """默认建议看的阶段：有 serving 就是它（启动时的初始化会淹没请求本身）"""
    return "serving" if any(p.get("name") == "serving" for p in run.get("phases") or []) else None
