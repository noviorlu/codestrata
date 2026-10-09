"""命令行的 REF 对上仓库和 run（读命令用，真的只读：不迁移老文件、不建目录）。语法在 ref.py。

仓库：-C（往上找最近的 .codestrata/，像 git -C）→ 页面地址（问那个端口的 serve 的 /api/app；问到的仓库里要真有这个 run）
→ 完整 run id 在已知仓库里唯一找到的 → 从当前目录往上找。当前目录的仓库里没有这个 run、别的已知仓库里有时用那个，
并警告 repo_from_run。找不到时，候选和下一步里写上别的已知仓库。
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import confdir as _confdir
from . import ref as _ref
from . import runs as _runs
from . import seq as _seq
from .cmdline import step
from .errors import CodestrataError


@dataclass
class Resolved:
    """对上了 run 的 REF"""
    repo: Path
    run: dict
    rd: Path
    phase: str | None                # 交给老接口（runs.load、lanes.build、path）的：阶段名、t=起-止，或 None（整个 run）
    slices: list[tuple[int, int]]    # 落在哪几片微秒（从 run 起点算）
    end_us: int | None               # run 的终点
    lanes: list[str]                 # 列选择器（规整过：对得上的换成标准写法、去重）
    text: str                        # 规整过的 REF（不带列）
    warnings: list[dict] = field(default_factory=list)

    @property
    def full(self) -> str:
        """规整过的 REF，带列"""
        return self.text + ("/" + ",".join(self.lanes) if self.lanes else "")


def _is_repo(d: Path) -> bool:
    return (d / ".codestrata").is_dir()


def _up(d: Path) -> Path | None:
    """d 和它往上最近的用过 codestrata 的目录"""
    return next((x for x in (d, *d.parents) if _is_repo(x)), None)


def _has_run(repo: Path, run_id: str) -> bool:
    return (repo / ".codestrata" / "runs" / run_id / "run.json").is_file()


def _known(but: Path | None = None) -> list[Path]:
    """主菜单记得的、还在的仓库（去重）"""
    out = []
    for p in _confdir.known_repos():
        p = p.expanduser().resolve()
        if p not in out and p != but and _is_repo(p):
            out.append(p)
    return out


def catalog(repo: Path) -> list[dict]:
    """只读地列出 run（不迁移老文件、不建目录）"""
    try:
        return _runs.catalog(repo, migrate_legacy=False)
    except SystemExit as e:                      # runs/ 是软链、盘没挂上
        raise CodestrataError("internal", str(e)) from None


def _has(repo: Path, name: str) -> bool:
    """仓库里有没有这个 run（完整 id）或 case"""
    if _ref.RUN_ID.match(name) and _has_run(repo, name):
        return True
    try:
        return _runs.pick(catalog(repo), name) is not None
    except CodestrataError:
        return False


def legacy_warning(repo: Path) -> list[dict]:
    old = _runs.legacy_files(repo)
    if not old:
        return []
    return [{"code": "legacy_runs", "msg": f"有 {len(old)} 个老格式的录制（.codestrata/trace-*.json）还没迁进 runs/，这里看不到；"
                                           "serve 起来或下一次 trace 时会自动迁（write）"}]


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


def _unknown(msg: str, warns: list[dict], again: str | None) -> CodestrataError:
    """repo_unknown：候选是已知的仓库，下一步每个给一条 status -C（带上原来的 REF）"""
    known = _known()
    return CodestrataError("repo_unknown", msg, candidates=[str(p) for p in known],
                           next=[step("read", "status", *([again] if again else []), repo=p) for p in known[:5]],
                           warnings=warns)


def find_repo(ref: _ref.Ref | None, chdir: str | None, cwd: Path, allow_fresh: bool = False) -> tuple[Path, str, list[dict]]:
    """(仓库, 怎么找到的: C / page / run / cwd, 警告)。allow_fresh：-C 指的目录往上都没有 .codestrata/ 时照样用它（status 看「还没 scan」）"""
    warns: list[dict] = []
    again = ref.text if ref is not None else None
    if chdir:
        d = Path(chdir).expanduser().resolve()
        if not d.is_dir():
            raise _unknown(f"-C 给的不是目录：{chdir}", warns, again)
        hit = _up(d)
        if hit is not None:
            return hit, "C", warns
        if allow_fresh:
            return d, "C", warns
        raise _unknown(f"{d} 和它往上都没有 .codestrata/（没 scan、也没 trace 过）", warns, again)
    if ref is not None and ref.page:
        app = page_app(ref.page)
        if app and (not ref.run or _has(Path(app["repo"]), ref.run)):
            return Path(app["repo"]), "page", warns
        warns.append({"code": "page_mismatch" if app else "page_unknown",
                      "msg": f":{ref.page['port']} 上的 serve 开的是 {app['repo']}，里面没有 {ref.run}；按别的办法找" if app else
                      f"问不到 :{ref.page['port']} 是哪个仓库（serve 没开、是老版本，或是转发过来的端口），按别的办法找"})
    here = _up(cwd)
    if ref is not None and ref.run and _ref.RUN_ID.match(ref.run) and not (here and _has_run(here, ref.run)):
        hits = [r for r in _known() if _has_run(r, ref.run)]
        if len(hits) == 1:
            if here:
                warns.append({"code": "repo_from_run", "msg": f"{here} 里没有这个 run，用的是 {hits[0]}"})
            return hits[0], "run", warns
    if here is not None:
        return here, "cwd", warns
    raise _unknown(f"从 {cwd} 往上没找到用过 codestrata 的仓库（没有 .codestrata/）；用 -C 指定", warns, again)


def _not_found(repo: Path, name: str, cat: list[dict], again: str) -> CodestrataError:
    """run_not_found：候选是这个仓库里以它开头的完整 id 和所有 case；别的已知仓库里有的，写进说明和下一步（不自动用）"""
    pre = [r["id"] for r in cat if r["id"].startswith(name)][:10]
    cases = sorted({r.get("case") for r in cat if r.get("case")})
    elsewhere = [p for p in _known(but=repo) if _has(p, name)]
    msg = f"{repo} 里没有叫 {name!r} 的 run 或 case（不收 run id 前缀）"
    if elsewhere:
        msg += "；" + "、".join(map(str, elsewhere)) + " 里有"
    return CodestrataError("run_not_found", msg, candidates=pre + cases,
                           next=[step("read", "status", again, repo=p) for p in elsewhere[:3]])


def resolve(repo: Path, ref: _ref.Ref) -> Resolved:
    if not ref.run:
        raise CodestrataError("need_view", "页面地址里没有 run（页面只开着静态图）；先在页面上选一个 run，或者直接写 RUN")
    cat = catalog(repo)
    hit = _runs.pick(cat, ref.run)
    if hit is None:
        raise _not_found(repo, ref.run, cat, ref.text)
    warns = legacy_warning(repo) + _run_warnings(repo, ref.run, hit, cat)
    rd = _runs.runs_dir(repo) / hit["id"]
    end = _seq.run_end(hit, rd)
    lanes = list(ref.lanes)
    phase, slices = None, ([(0, end)] if end else [])
    if ref.rest is not None:
        rng, lanes2 = _ref.split_range(hit, ref.rest)
        if lanes2 is not None:
            if ref.page:
                raise CodestrataError("usage", "页面地址后面不能再接 /列（列写在地址的 lanes= 里）")
            lanes = lanes2
        phase, slices = _ref.parse_range(hit, rng, end)
    if lanes:
        lanes, w = _check_lanes(rd, lanes)
        warns += w
    return Resolved(repo=repo, run=hit, rd=rd, phase=phase, slices=slices, end_us=end, lanes=lanes,
                    text=hit["id"] + (f"@{phase}" if phase else ""), warnings=warns)


def _run_warnings(repo: Path, name: str, hit: dict, cat: list[dict]) -> list[dict]:
    """这个 run 不完整、录制中断了、还在录；按 case 名挑到了旧的、同一个 case 有一次更新的正在录"""
    w: list[dict] = []
    st = hit.get("status_shown") or hit.get("status")
    if st == "partial":
        w.append({"code": "partial", "msg": f"run {hit['id']} 只录了一部分：" + ("；".join(hit.get("problems") or []) or "（没写原因）"),
                  "problems": hit.get("problems") or []})
    elif st == "中断":
        w.append({"code": "interrupted", "msg": f"run {hit['id']} 录制中断了（录制的进程没了），数据要先合并",
                  "next": step("write", "runs", "merge", hit["id"], repo=repo)})
    elif st == "recording":
        w.append({"code": "recording", "msg": f"run {hit['id']} 还在录",
                  "next": step("read", "runs", "wait", hit["id"], repo=repo)})
    if hit["id"] != name:                        # 按 case 名挑的
        newer = [r for r in cat if r.get("case") == name and r["id"] > hit["id"] and _runs.live(r)]
        if newer:
            w.append({"code": "newer_recording", "msg": f"case {name} 有一次更新的正在录（{newer[0]['id']}），这里用的是录完的 {hit['id']}",
                      "next": step("read", "runs", "wait", newer[0]["id"], repo=repo)})
    return w


def _check_lanes(rd: Path, lanes: list[str]) -> tuple[list[str], list[dict]]:
    """列选择器对着整个 run 的列核对、规整；没录时序事件的 run 核对不了，原样留着并警告"""
    from . import laneid as _laneid
    from . import lanes as _lanes
    try:
        aliases = _lanes.run_aliases(rd)
    except LookupError:
        return lanes, [{"code": "lanes_unchecked", "msg": "这个 run 没录时序事件，列没核对"}]
    return _laneid.canonical(lanes, aliases), []


def from_cli(text: str | None, chdir: str | None, cwd: Path, allow_fresh: bool = False) -> tuple[_ref.Ref | None, Path, str, list[dict]]:
    """命令行的 REF 参数 → (Ref 或 None, 仓库, 怎么找到的, 警告)"""
    r = _ref.parse(text) if text else None
    repo, how, warns = find_repo(r, chdir, cwd, allow_fresh=allow_fresh)
    return r, repo, how, warns
