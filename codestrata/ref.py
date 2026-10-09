"""REF：命令行和页面共用的「看哪个 run、哪段时间、哪几列」。

    REF   := 页面地址 | RUN [ "@" 范围 ] [ "/" 列选择器 { "," 列选择器 } ]
    RUN   := 完整 run id | case 名（runs.pick：最新一次 ok 的，没有就最新的 partial）
    范围  := 阶段名 | "t=" 起 "-" 止（从 run 起点算的微秒；也收 78.024s-80.492s）| 阶段名 "+" 秒 "s-" 秒 "s"（从阶段开头算）
    页面地址 := http://127.0.0.1:端口/[v/端口/]#run=RUN@范围&lanes=列,…&…（其余的键原样留在 view 里）

阶段名按这个 run 里实际有的名字做最长匹配，不靠分隔符。不收 run id 前缀（和日期撞）。
解析出来的东西一律规整成完整 id：`<id>@<阶段>` 或 `<id>@t=起-止`，输出里只给规整过的。

仓库查找（只对读命令）：-C → 页面地址（问那个端口的 serve 的 /api/app）→ 完整 run id 在已知仓库里唯一找到的 →
从当前目录往上找。当前目录的仓库里没有这个 run、别的已知仓库里有时用那个，并警告 repo_from_run。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import confdir as _confdir
from . import runs as _runs
from . import seq as _seq
from .errors import CodestrataError

_URL = re.compile(r"^https?://", re.I)
_RUN_ID = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9._-]+$")
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


@dataclass
class Resolved:
    """对上了 run 的 REF"""
    repo: Path
    run: dict
    rd: Path
    phase: str | None                # 交给老接口（runs.load、lanes.build、path）的：阶段名、t=起-止，或 None（整个 run）
    slices: list[tuple[int, int]]    # 落在哪几片微秒（从 run 起点算）
    end_us: int | None               # run 的终点
    lanes: list[str]                 # 列选择器
    text: str                        # 规整过的 REF（不带列）
    warnings: list[dict] = field(default_factory=list)

    @property
    def full(self) -> str:
        """规整过的 REF，带列"""
        return self.text + ("/" + ",".join(self.lanes) if self.lanes else "")


def _unq(s: str) -> str:
    """地址里的值：只按 %XX 解（不把 + 当空格：阶段名 + 秒数的写法里有 +）"""
    return urllib.parse.unquote(s)


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
        rest = None
        lanes = [x for x in ln.split(",") if x] if slash else []
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
    lanes = [x for x in keys.pop("lanes", "").split(",") if x]
    page = {"url": text, "host": u.hostname, "port": port, "prefix": prefix}
    if run_text is None:
        return Ref(run=None, lanes=lanes, view=keys, page=page, text=text)
    run, at, rest = run_text.partition("@")
    return Ref(run=run, rest=rest if at else None, lanes=lanes, view=keys, page=page, text=text)


# ---------------------------------------------------------------- 仓库

def _is_repo(d: Path) -> bool:
    return (d / ".codestrata").is_dir()


def _has_run(repo: Path, run_id: str) -> bool:
    return (repo / ".codestrata" / "runs" / run_id / "run.json").is_file()


def page_app(page: dict, timeout: float = 0.3) -> dict | None:
    """问页面那个端口的 serve 它是谁：{repo, pid, port, …}；连不上、不是 codestrata、老 serve（没有 repo）是 None"""
    if page.get("host") not in ("127.0.0.1", "localhost"):
        return None
    req = urllib.request.Request(f"http://127.0.0.1:{page['port']}/api/app", headers={"X-Codestrata": "1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("repo") else None


def find_repo(ref: Ref | None, chdir: str | None, cwd: Path) -> tuple[Path, str, list[dict]]:
    """(仓库, 怎么找到的: C / page / run / cwd, 警告)"""
    warns: list[dict] = []
    if chdir:
        d = Path(chdir).expanduser().resolve()
        if not d.is_dir():
            raise CodestrataError("repo_unknown", f"-C 给的不是目录：{chdir}")
        return d, "C", warns
    if ref is not None and ref.page:
        app = page_app(ref.page)
        if app:
            return Path(app["repo"]), "page", warns
        warns.append({"code": "page_unknown",
                      "msg": f"问不到 :{ref.page['port']} 是哪个仓库（serve 没开、是老版本，或是转发过来的端口），按别的办法找"})
    here = next((d for d in (cwd, *cwd.parents) if _is_repo(d)), None)
    if ref is not None and ref.run and _RUN_ID.match(ref.run) and not (here and _has_run(here, ref.run)):
        hits = [r for r in dict.fromkeys(p.resolve() for p in _confdir.known_repos()) if _has_run(r, ref.run)]
        if len(hits) == 1:
            if here:
                warns.append({"code": "repo_from_run", "msg": f"{here} 里没有这个 run，用的是 {hits[0]}"})
            return hits[0], "run", warns
    if here:
        return here, "cwd", warns
    tried = [str(p) for p in _confdir.known_repos()][:8]
    raise CodestrataError("repo_unknown", f"从 {cwd} 往上没找到用过 codestrata 的仓库（没有 .codestrata/）；用 -C 指定",
                          candidates=tried)


# ---------------------------------------------------------------- run 和范围

def _phase_names(run: dict) -> list[str]:
    names = [p["name"] for p in run.get("phases") or []]
    names += [x[0] for x in run.get("phase_log") or [] if x and x[0] not in names]
    return names


def _window_hint(run: dict, end: int | None) -> list[str]:
    """越界、写错范围时的候选（都是能直接用的 REF）：各阶段，和整个 run 的 t="""
    rid = run["id"]
    return [f"{rid}@{n}" for n in _phase_names(run)] + ([f"{rid}@t=0-{end}"] if end else [])


def _phase_text(run: dict, end: int | None) -> str:
    """错误说明里的各阶段时刻"""
    if not end:
        return ""
    return "；各阶段：" + "，".join(f"{n} t={a}-{b}" for n, a, b in _seq.phase_segments(run, end))


def _secs(x: str) -> int:
    return round(float(x) * 1_000_000)


def resolve(repo: Path, ref: Ref) -> Resolved:
    if not ref.run:
        raise CodestrataError("need_view", "页面地址里没有 run（页面只开着静态图）；先在页面上选一个 run，或者直接写 RUN")
    try:
        cat = _runs.catalog(repo)
    except SystemExit as e:                      # runs/ 是软链、盘没挂上
        raise CodestrataError("internal", str(e)) from None
    hit = _runs.pick(cat, ref.run)
    if hit is None:
        cases = sorted({r.get("case") for r in cat if r.get("case")})
        raise CodestrataError("run_not_found", f"{repo} 里没有叫 {ref.run!r} 的 run 或 case（不收 run id 前缀）",
                              candidates=cases)
    warns: list[dict] = []
    if hit["id"] != ref.run and hit.get("status") != "ok":
        warns.append({"code": "partial", "msg": f"case {ref.run} 没有完整录完的 run，用的是 {hit['id']}（{hit.get('status')}）",
                      "problems": hit.get("problems") or []})
    rd = _runs.runs_dir(repo) / hit["id"]
    end = _seq.run_end(hit, rd)
    rest, lanes = ref.rest, list(ref.lanes)
    phase, slices = None, [(0, end)] if end else []
    if rest is not None:
        rng, lanes2 = _split_range(hit, rest)
        if lanes2 is not None:
            if ref.page:
                raise CodestrataError("usage", "页面地址后面不能再接 /列（列写在地址的 lanes= 里）")
            lanes = lanes2
        phase, slices = _range(hit, rng, end)
    text = hit["id"] + (f"@{phase}" if phase else "")
    return Resolved(repo=repo, run=hit, rd=rd, phase=phase, slices=slices, end_us=end, lanes=lanes, text=text,
                    warnings=warns)


def _split_range(run: dict, rest: str) -> tuple[str, list[str] | None]:
    """@ 后面 → (范围, 列选择器或 None)。阶段名按实际有的做最长匹配"""
    if rest.startswith("t="):
        rng, slash, ln = rest.partition("/")
        return rng, ([x for x in ln.split(",") if x] if slash else None)
    for name in sorted(_phase_names(run), key=len, reverse=True):
        if rest == name or rest.startswith(name + "/") or rest.startswith(name + "+"):
            tail = rest[len(name):]
            rel, slash, ln = tail.partition("/")
            return name + rel, ([x for x in ln.split(",") if x] if slash else None)
    rng, slash, ln = rest.partition("/")
    return rng, ([x for x in ln.split(",") if x] if slash else None)


def _range(run: dict, rng: str, end: int | None) -> tuple[str | None, list[tuple[int, int]]]:
    """范围 → (交给老接口的 phase, 微秒片)。越界、写错都报带候选的错"""
    names = _phase_names(run)
    hint = _window_hint(run, end)
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
        return _window(run, a, b, end, rng, hint)
    name = next((n for n in sorted(names, key=len, reverse=True) if rng == n or rng.startswith(n + "+")), None)
    if name is None:
        raise CodestrataError("phase_not_found", f"run {run['id']} 里没有阶段 {rng!r}" + _phase_text(run, end),
                              candidates=hint)
    if rng == name:
        segs = _seq.phase_intervals(run, end).get(name) if end else None
        return name, list(segs or [])
    m = _REL.match(rng[len(name):])
    if not m:
        raise CodestrataError("bad_window", f"阶段里的一段写成 {name}+起s-止s（从阶段开头算的秒）：{rng}", candidates=hint)
    segs = _seq.phase_intervals(run, end).get(name) if end else None
    if not segs:
        raise CodestrataError("no_events", f"run {run['id']} 不知道阶段 {name} 的时刻", candidates=hint)
    t0 = segs[0][0]
    return _window(run, t0 + _secs(m.group(1)), t0 + _secs(m.group(2)), end, rng, hint, within=(name, segs[0]))


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


def from_cli(text: str | None, chdir: str | None, cwd: Path) -> tuple[Ref | None, Path, str, list[dict]]:
    """命令行的 REF 参数 → (Ref 或 None, 仓库, 怎么找到的, 警告)"""
    ref = parse(text) if text else None
    repo, how, warns = find_repo(ref, chdir, cwd)
    return ref, repo, how, warns
