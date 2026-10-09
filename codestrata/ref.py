"""REF 的写法：命令行和页面共用的「看哪个 run、哪段时间、哪几列」。只管语法，不碰文件和网络
（对上仓库和 run 在 locate.py；runs.resolve 的范围也走这里，页面和命令行认同一套写法）。

    REF   := 页面地址 | RUN [ "@" 范围 ] [ "/" 列选择器 { "," 列选择器 } ]
    RUN   := 完整 run id | case 名
    范围  := 阶段名 | "t=" 起 "-" 止（从 run 起点算的微秒；也收 78.024s-80.492s）| 阶段名 "+" 秒 "s-" 秒 "s"（从阶段开头算）
    页面地址 := http://127.0.0.1:端口/[v/端口/]#run=RUN@范围&lanes=列,…&…（其余的键原样留在 view 里）

阶段名按这个 run 里实际有的名字做最长匹配，不靠分隔符。不收 run id 前缀（和日期撞）。
范围一律规整成交给老接口的写法：阶段名，或 `t=起-止`（整数微秒）。
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from . import seq as _seq
from .errors import CodestrataError

_URL = re.compile(r"^https?://", re.I)
RUN_ID = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9._-]+$")
_NUM = r"(\d+(?:\.\d+)?)"
_T_US = re.compile(r"^(\d+)-(\d+)$")
_T_S = re.compile(rf"^{_NUM}s-{_NUM}s$")
_REL = re.compile(rf"^\+{_NUM}s-{_NUM}s$")


@dataclass
class Ref:
    """解析出来、还没对上 run 的 REF"""
    run: str | None                  # RUN 原样（页面地址里没有 run 键时是 None）
    rest: str | None = None          # @ 后面的原样（可能带 /列）；没有 @ 是 None
    lanes: list[str] = field(default_factory=list)   # 页面地址的 lanes 键，或没有 @ 时 / 后面的
    view: dict = field(default_factory=dict)         # 页面地址里 run、lanes 之外的键
    page: dict | None = None         # 页面地址：{url, host, port, prefix}
    text: str = ""


def _unq(s: str) -> str:
    """地址里的值：只按 %XX 解（不把 + 当空格：阶段名 + 秒数的写法里有 +）"""
    return urllib.parse.unquote(s)


def _list(s: str) -> list[str]:
    return [x for x in s.split(",") if x]


def parse(text: str) -> Ref:
    text = (text or "").strip()
    if _URL.match(text):
        return _parse_url(text)
    if not text:
        raise CodestrataError("usage", "没给 REF")
    run, at, rest = text.partition("@")
    lanes: list[str] = []
    if not at:
        run, slash, ln = run.partition("/")
        lanes = _list(ln) if slash else []
    if not run:
        raise CodestrataError("usage", f"REF 要以 run id 或 case 名开头：{text!r}")
    return Ref(run=run, rest=rest if at else None, lanes=lanes, text=text)


def _parse_url(text: str) -> Ref:
    u = urllib.parse.urlsplit(text)
    try:
        port = u.port
    except ValueError:
        port = None
    if not u.hostname or not port:
        raise CodestrataError("usage", f"页面地址要带端口：{text!r}")
    prefix = "/"
    m = re.match(r"^/v/(\d+)/", u.path or "")
    if m:                                        # 主菜单转发的 /v/<端口>/：图服务自己的端口
        prefix, port = m.group(0), int(m.group(1))
    keys: dict[str, str] = {}
    for part in (u.fragment or "").split("&"):
        if part:
            k, _, v = part.partition("=")
            keys[_unq(k)] = _unq(v)
    run_text = keys.pop("run", "") or None
    lanes = _list(keys.pop("lanes", ""))
    page = {"url": text, "host": u.hostname, "port": port, "prefix": prefix}
    if run_text is None:
        return Ref(run=None, lanes=lanes, view=keys, page=page, text=text)
    run, at, rest = run_text.partition("@")
    return Ref(run=run, rest=rest if at else None, lanes=lanes, view=keys, page=page, text=text)


# ---------------------------------------------------------------- 范围（对着一个 run 的 run.json）

def phase_names(run: dict) -> list[str]:
    names = [p["name"] for p in run.get("phases") or []]
    names += [x[0] for x in run.get("phase_log") or [] if x and x[0] not in names]
    return names


def window_hint(run: dict, end: int | None) -> list[str]:
    """越界、写错范围时的候选（都是能直接用的 REF）：各阶段，和整个 run 的 t="""
    rid = run["id"]
    return [f"{rid}@{n}" for n in phase_names(run)] + ([f"{rid}@t=0-{end}"] if end else [])


def _phase_text(run: dict, end: int | None) -> str:
    """错误说明里的各阶段时刻"""
    if not end:
        return ""
    return "；各阶段：" + "，".join(f"{n} t={a}-{b}" for n, a, b in _seq.phase_segments(run, end))


def _secs(x: str) -> int:
    return round(float(x) * 1_000_000)


def split_range(run: dict, rest: str) -> tuple[str, list[str] | None]:
    """@ 后面 → (范围, 列选择器或 None)。阶段名按实际有的做最长匹配"""
    if rest.startswith("t="):
        rng, slash, ln = rest.partition("/")
        return rng, (_list(ln) if slash else None)
    for name in sorted(phase_names(run), key=len, reverse=True):
        if rest == name or rest.startswith(name + "/") or rest.startswith(name + "+"):
            rel, slash, ln = rest[len(name):].partition("/")
            return name + rel, (_list(ln) if slash else None)
    rng, slash, ln = rest.partition("/")
    return rng, (_list(ln) if slash else None)


def parse_range(run: dict, rng: str, end: int | None, bounds: bool = True) -> tuple[str, list[tuple[int, int]]]:
    """范围 → (交给老接口的 phase：阶段名或 t=起-止, 微秒片)。写错都报带候选的错；bounds 时 t= 落在 run 之外也报
    （命令行要报；页面收下超出终点的时间段、把时间条放长，不查）"""
    names = phase_names(run)
    hint = window_hint(run, end)
    if not rng:
        raise CodestrataError("bad_window", "@ 后面是空的", candidates=hint)
    if rng.startswith("t="):
        body = rng[2:]
        if "," in body:
            raise CodestrataError("bad_window", f"多片时间段（{rng}）还不支持", candidates=hint)
        m, ms = _T_US.match(body), _T_S.match(body)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        elif ms:
            a, b = _secs(ms.group(1)), _secs(ms.group(2))
        else:
            raise CodestrataError("bad_window", f"时间段写成 t=起-止（微秒）或 t=78.024s-80.492s：{rng}", candidates=hint)
        return _window(run, a, b, end if bounds else None, rng, hint)
    name = next((n for n in sorted(names, key=len, reverse=True) if rng == n or rng.startswith(n + "+")), None)
    if name is None:
        raise CodestrataError("phase_not_found", f"run {run['id']} 里没有阶段 {rng!r}" + _phase_text(run, end),
                              candidates=hint)
    segs = _seq.phase_intervals(run, end).get(name) if end else None
    if rng == name:
        return name, list(segs or [])
    m = _REL.match(rng[len(name):])
    if not m:
        raise CodestrataError("bad_window", f"阶段里的一段写成 {name}+起s-止s（从阶段开头算的秒）：{rng}", candidates=hint)
    if not segs:
        raise CodestrataError("no_events", f"run {run['id']} 不知道阶段 {name} 的时刻", candidates=hint)
    t0 = segs[0][0]
    return _window(run, t0 + _secs(m.group(1)), t0 + _secs(m.group(2)), end if bounds else None, rng, hint,
                   within=(name, segs[0]))


def _window(run: dict, a: int, b: int, end: int | None, rng: str, hint: list[str], within=None):
    if within and b > within[1][1]:
        raise CodestrataError("window_out_of_range", f"{rng} 超出了阶段 {within[0]} 的结尾"
                              f"（它长 {(within[1][1] - within[1][0]) / 1e6:.3f} s）；跨阶段的时间段写成 t=起-止",
                              candidates=hint)
    if b <= a:
        raise CodestrataError("bad_window", f"时间段的起点要小于终点：{rng}", candidates=hint)
    if end is not None and (a < 0 or b > end):
        raise CodestrataError("window_out_of_range", f"{rng} 落在 run 之外（run 是 t=0-{end}）" + _phase_text(run, end),
                              candidates=hint)
    return f"t={a}-{b}", [(a, b)]
