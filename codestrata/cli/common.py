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


def refuse_old(c: Ctx) -> None:
    """切段要 2026-10-01 之后录的 run（span 带父亲、录了交接）；老 run 切出来是错的，拒绝并说明（用户 10-09 定）"""
    from .. import segments as _segments
    if _segments.old_format(c.res.rd):
        raise CodestrataError("no_handoffs", f"run {c.res.run['id']} 是 2026-10-01 之前录的，没录「谁把数据交给谁」，切段会切错；"
                              "要重新录一次才能切（trace 是 record，先问用户）。原始的调用还能看：", warnings=c.warnings,
                              next=[c.cmd("read", "lanes", c.res.full), c.cmd("read", "path", c.res.full, "--limit", "30")])


def labeler(idx: dict):
    """键 rel:行 → 函数级的节点（file#Qual）"""
    from .. import align as _align
    return _align.node_labeler(idx)


def short(node: str | None) -> str:
    """节点的短写法：限定名；模块顶层写成 上一层目录/文件名:<module>（__init__.py 光看文件名分不出是哪个包）"""
    f, _, q = (node or "?").partition("#")
    if q.startswith("<module>"):
        pth = Path(f)
        return f"{pth.parent.name + '/' if pth.parent.name else ''}{pth.name}:{q}"
    return q or f


def end_text(e: dict) -> str:
    """连线的一头（linkgroups.end：fn、file、line、outside）的文字：函数（文件:行）"""
    if not e["fn"]:
        return "（仓库外的代码）"
    loc = f"{e['file']}:{e['line']}" if e["line"] else e["file"]
    return f"{short(e['fn'])}（{loc}）" + ("（栈底的仓库函数；放 / 取在仓库外的代码里）" if e["outside"] else "")


def add_params(p) -> None:
    """切段的阈值（steps.Params），segments / steps 共用"""
    from .. import steps as _steps
    d = _steps.Params()
    p.add_argument("--min-calls", type=int, default=d.min_calls, help="轮头在这段时间里至少调几次（默认 %(default)s）")
    p.add_argument("--class-share", type=float, default=d.class_share, help="一类轮至少占多少比例才算一类（默认 %(default)s）")
    p.add_argument("--cheap", type=float, default=d.cheap,
                   help="在仓库函数里的时间（中位）不超过最少那类几倍的类算便宜的、调到的算常规（默认 %(default)s）")
    p.add_argument("--long", type=float, default=d.long, help="墙上时长超过便宜的那几类轮的中位几倍算超长（默认 %(default)s）")
    p.add_argument("--gap", type=float, default=d.gap,
                   help="前景轮之间空转超过 REF 所在的阶段长度的多少就切开（默认 %(default)s；交替干活的几块合成一块时调小）")


def params(a):
    from .. import steps as _steps
    return _steps.Params(min_calls=a.min_calls, class_share=a.class_share, cheap=a.cheap, long=a.long, gap=a.gap)


def head_window(c: Ctx) -> tuple[int, int]:
    """认轮头用的那段：REF 所在的那个阶段（segments.head_window）。轮头和轮号不随 REF 的范围变（契约），REF 只决定列出哪几轮"""
    from .. import segments as _segments
    r = c.res
    lo, hi = (r.slices[0][0], r.slices[-1][1]) if r.slices else (0, r.end_us or 0)
    return _segments.head_window(r.run, r.end_us, lo, hi, r.phase)[1]


def phase_name(c: Ctx) -> str | None:
    """REF 所在的阶段名（REF 是 t= 的一小段时，取装着它的那个阶段）：认「请求」用"""
    from .. import segments as _segments
    r = c.res
    lo, hi = (r.slices[0][0], r.slices[-1][1]) if r.slices else (0, r.end_us or 0)
    return _segments.head_window(r.run, r.end_us, lo, hi, r.phase)[0]


def proc_order(c: Ctx, label) -> dict:
    """进程的先后：这一段里开始干活的先后（和页面一样，segments.proc_order）"""
    from .. import segments as _segments
    r = c.res
    lo, hi = (r.slices[0][0], r.slices[-1][1]) if r.slices else (0, 0)
    return _segments.proc_order(r.rd, r.run, phase_name(c), lo, hi, label, head_window(c))
