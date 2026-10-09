"""列的稳定写法：进程别名、列别名、列选择器。纯函数，命令行和页面（经 /api/lanes）共用这一份。

    进程别名  去掉扩展名，再去掉同一族进程（第一个词相同）共有的开头和结尾几个词，取从左往右最短的、
             能唯一认出它的前缀：VLLM::StageEngineCoreProc_stage1_replica0_DP0 → stage1，end2end.py → end2end。
             名字完全一样的几个进程（几个 python -c）加 -<pid>。整个 run 算一次，和时间段无关。
    列别名    进程别名/线程（线程照 lanes.thread_group 归一）：stage1/MainThread；GPU 列是 stage1/gpu0.7。
             [A-Za-z0-9._-] 以外的字符换成 _，撞了加 -2、-3。
    选择器    进程/线程、进程（这个进程的所有列）、进程/*、*/线程、*/gpu*，也认 pid:线程（页面的列 id）。
             不分大小写，按整段匹配（stage1 不配 stage10）。
"""
from __future__ import annotations

import fnmatch
import re

from .errors import CodestrataError

_SPLIT = re.compile(r"[_\-. ]+")
_BAD = re.compile(r"[^A-Za-z0-9._-]")


def clean(s: str) -> str:
    """别名里只留 [A-Za-z0-9._-]，其余换成 _（空的写成 _）"""
    return _BAD.sub("_", s) or "_"


def _base(name: str) -> str:
    name = name.removeprefix("VLLM::").removeprefix("-m ")
    for ext in (".py", ".pyw"):
        if name.endswith(ext) and len(name) > len(ext):
            name = name[: -len(ext)]
    return name


def proc_aliases(names: dict[int, str]) -> dict[int, str]:
    """{pid: 进程名}（lanes.proc_names）→ {pid: 别名}"""
    base = {pid: _base(n or str(pid)) for pid, n in names.items()}
    words = {pid: [w for w in _SPLIT.split(b) if w] or [b] for pid, b in base.items()}
    fams: dict[str, list[int]] = {}
    for pid, ws in words.items():
        fams.setdefault(ws[0].lower(), []).append(pid)
    out: dict[int, str] = {}
    for pids in fams.values():
        distinct = sorted({tuple(words[p]) for p in pids})
        if len(distinct) == 1:
            ws = distinct[0]
            name = clean(base[pids[0]])
            for p in pids:
                out[p] = name if len(pids) == 1 else f"{name}-{p}"
            continue
        # 去掉共有的开头、结尾（至少留一个词）
        n_min = min(len(d) for d in distinct)
        pre = 0
        while pre < n_min - 1 and len({d[pre] for d in distinct}) == 1:
            pre += 1
        suf = 0
        while suf < n_min - pre - 1 and len({d[len(d) - 1 - suf] for d in distinct}) == 1:
            suf += 1
        rest = {d: d[pre:len(d) - suf] for d in distinct}
        short: dict[tuple, str] = {}
        for d, r in rest.items():
            for j in range(1, len(r) + 1):
                if sum(1 for o in rest.values() if o[:j] == r[:j]) == 1 or j == len(r):
                    short[d] = clean("_".join(r[:j]))
                    break
        groups: dict[tuple, list[int]] = {}
        for p in pids:
            groups.setdefault(tuple(words[p]), []).append(p)
        for d, ps in groups.items():
            for p in ps:
                out[p] = short[d] if len(ps) == 1 else f"{short[d]}-{p}"
    # 不同族撞了名（很少见）：后来的加 pid
    seen: dict[str, int] = {}
    for pid in sorted(out):
        a = out[pid]
        if a in seen and seen[a] != pid:
            out[pid] = f"{a}-{pid}"
        seen.setdefault(out[pid], pid)
    return out


def lane_aliases(lanes: list[dict], procs: dict[int, str]) -> dict[str, str]:
    """lanes.build 的列 → {列 id: 列别名}。procs 是 proc_aliases 的结果"""
    out: dict[str, str] = {}
    used: set[str] = set()
    for ln in lanes:
        pa = procs.get(ln["pid"]) or str(ln["pid"])
        if ln.get("gpu"):
            th = f"gpu{ln['gpu'][0]}.{ln['gpu'][1]}"
        else:
            th = clean(ln.get("thread") or "?")
        a, k = f"{pa}/{th}", 2
        while a.lower() in used:
            a, k = f"{pa}/{th}-{k}", k + 1
        used.add(a.lower())
        out[ln["id"]] = a
    return out


def _match(sel: str, alias: str, lane_id: str) -> bool:
    s = sel.lower()
    if s == lane_id.lower():
        return True
    proc, _, th = alias.lower().partition("/")
    sp, slash, st = s.partition("/")
    if not slash:                               # 只写进程：这个进程的所有列
        return fnmatch.fnmatchcase(proc, sp)
    return fnmatch.fnmatchcase(proc, sp) and fnmatch.fnmatchcase(th, st)


def select(selectors: list[str], aliases: dict[str, str]) -> list[str]:
    """选择器 → 列 id（按 aliases 的先后，去重）。哪个选择器一列都没配上就报 lane_not_found，带候选"""
    out: list[str] = []
    for sel in selectors:
        hit = [lid for lid, a in aliases.items() if _match(sel, a, lid)]
        if not hit:
            raise CodestrataError("lane_not_found", f"没有和 {sel!r} 对上的列", candidates=_near(sel, aliases))
        out += [h for h in hit if h not in out]
    return [lid for lid in aliases if lid in out]


def _near(sel: str, aliases: dict[str, str]) -> list[str]:
    """写错的选择器的候选：先给进程名对上的列，再给别的进程别名"""
    proc = sel.lower().partition("/")[0]
    same = [a for a in aliases.values() if a.lower().partition("/")[0] == proc]
    procs = sorted({a.partition("/")[0] for a in aliases.values()})
    return same[:12] or procs


def parse_list(text: str | None) -> list[str]:
    """逗号隔开的选择器"""
    return [x.strip() for x in (text or "").split(",") if x.strip()]
