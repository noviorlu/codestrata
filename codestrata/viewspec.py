"""视图描述（地址栏 # 后面那串）的 Python 一侧：和页面的 web/view.js 同一套键、同一种写法（view url 拼出来）。

    run=RUN@范围 & fold=进程,… & cut=目录,… & lcut=列~目录,目录;列~… & sel=… & mark=… & chain=范围~起点~--link…
    & order=1 & panel=path
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
    fold: list[str] = field(default_factory=list)
    cut: list[str] | None = None
    lcut: dict[str, list[str]] = field(default_factory=dict)
    sel: str | None = None
    mark: list[str] = field(default_factory=list)
    chain: str | None = None
    order: bool = False
    panel: str | None = None


def from_keys(run: str | None, keys: dict[str, str]) -> View:
    """ref.parse 解出来的页面地址（run 和其余的键）→ View（老地址里的 lanes= 不认）"""
    v = View(run=run)
    v.fold = _list(keys.get("fold"))
    v.cut = _list(keys["cut"]) if "cut" in keys else None
    for part in (keys.get("lcut") or "").split(";"):
        lane, sep, dirs = part.partition("~")
        if sep and lane:
            v.lcut[lane] = _list(dirs)
    v.sel = keys.get("sel") or None
    v.mark = _list(keys.get("mark"))
    v.chain = keys.get("chain") or None
    v.order = keys.get("order") in ("1", "on")
    v.panel = keys.get("panel") or None
    return v


def fragment(v: View) -> str:
    """规范写法（同 view.js 的 format）"""
    out = []
    if v.run:
        out.append("run=" + _enc(v.run))
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
    if v.chain:
        out.append("chain=" + _enc(v.chain))
    if v.order:
        out.append("order=1")
    if v.panel:
        out.append("panel=" + _enc(v.panel))
    return "&".join(out)

