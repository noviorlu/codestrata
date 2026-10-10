"""视图描述（地址栏 # 后面那串）的 Python 一侧：和页面的 web/view.js 同一套键、同一种写法（view url 拼出来、explain 24 按它算编号）。

    run=RUN@范围 & lanes=选择器,… & fold=进程,… & cut=目录,… & lcut=列~目录,目录;列~… & sel=… & mark=… & order=1 & hide=hot,dyn & panel=path

也在这里按一个视图算出分列（lanes.build，用视图里的切面）和时间顺序的编号（laneorder.rank），和页面拿到的一样。
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

_SAFE = "@,/~|:;+*=!'()"        # 和 view.js 的 enc 一样：这些字符不转义（encodeURIComponent 本来就不转义 ! ' ( ) * ~）


def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe=_SAFE)


def _list(s: str | None) -> list[str]:
    return [x for x in (s or "").split(",") if x]


@dataclass
class View:
    run: str | None = None
    lanes: list[str] = field(default_factory=list)
    fold: list[str] = field(default_factory=list)
    cut: list[str] | None = None
    lcut: dict[str, list[str]] = field(default_factory=dict)
    sel: str | None = None
    mark: list[str] = field(default_factory=list)
    order: bool = False
    hide: list[str] = field(default_factory=list)
    panel: str | None = None


def from_keys(run: str | None, lanes: list[str], keys: dict[str, str]) -> View:
    """ref.parse 解出来的页面地址（run、lanes 和其余的键）→ View"""
    v = View(run=run, lanes=list(lanes))
    v.fold = _list(keys.get("fold"))
    v.cut = _list(keys["cut"]) if "cut" in keys else None
    for part in (keys.get("lcut") or "").split(";"):
        lane, sep, dirs = part.partition("~")
        if sep and lane:
            v.lcut[lane] = _list(dirs)
    v.sel = keys.get("sel") or None
    v.mark = _list(keys.get("mark"))
    v.order = keys.get("order") in ("1", "on")
    v.hide = _list(keys.get("hide"))
    v.panel = keys.get("panel") or None
    return v


def fragment(v: View) -> str:
    """规范写法（同 view.js 的 format）"""
    out = []
    if v.run:
        out.append("run=" + _enc(v.run))
    if v.lanes:
        out.append("lanes=" + _enc(",".join(v.lanes)))
    if v.fold:
        out.append("fold=" + _enc(",".join(v.fold)))
    if v.cut is not None:
        out.append("cut=" + _enc(",".join(v.cut)))
    if v.lcut:
        out.append("lcut=" + _enc(";".join(f"{k}~{','.join(v.lcut[k])}" for k in sorted(v.lcut))))
    if v.sel:
        out.append("sel=" + _enc(v.sel))
    if v.mark:
        out.append("mark=" + _enc(",".join(v.mark)))
    if v.order:
        out.append("order=1")
    if v.hide:
        out.append("hide=" + _enc(",".join(v.hide)))
    if v.panel:
        out.append("panel=" + _enc(v.panel))
    return "&".join(out)


def lanes_for(idx: dict, rd, run: dict, phase: str | None, hot: dict, v: View, label, proc_order: dict | None):
    """按这个视图（切面、各列的切面）算分列，和页面取到的一样：(lanes.build 的结果, 列别名, 编号)"""
    from . import cut as _cut
    from . import laneid as _laneid
    from . import laneorder as _laneorder
    from . import lanes as _lanes
    aliases0 = _lanes.run_aliases(rd)
    inv = {a: lid for lid, a in aliases0.items()}
    open_ = sorted(_cut.norm_open(idx, v.cut if v.cut is not None else (idx.get("default_open") or [])))
    cuts = {inv[a]: dirs for a, dirs in v.lcut.items() if a in inv}
    L = _lanes.build(idx, rd, run, phase, hot, open_, cuts=cuts or None, proc_order=proc_order)
    aliases = _lanes.run_aliases(rd, [ln for ln in L["lanes"] if ln.get("gpu")])
    procs = {a: pid for pid, a in _lanes.proc_aliases(rd).items()}
    fold = {procs[a] for a in v.fold if a in procs}
    want = set(_laneid.select(v.lanes, aliases)) if v.lanes else None
    return L, aliases, _laneorder.rank(L, aliases, fold=fold, hide=set(v.hide), lanes=want)
