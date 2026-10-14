"""explain 的原料：一个函数——定义的签名和 docstring 第一行、这段时间里在哪几列跑过、谁调它、它调了谁（仓库里的函数和 GPU kernel 分开）、
代码里写成调它、跑的却是同名的别的方法（子类覆盖的、接口的实现）。只取数和源码原文，不下结论：「为什么」由 agent 读完代码自己说。
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

from . import align as _align
from . import lanes as _lanes
from . import seq as _seq
from .ui import source as _source


def definition(repo: Path, idx: dict, node: str) -> dict | None:
    """函数 / 类的定义：{file, line, end, signature（def 那几行拼成一行）, doc（docstring 第一行）, kind}"""
    s = (idx.get("symbols") or {}).get(node)
    if not s:
        return None
    rel, q = s["f"], s["n"]
    ls = _lines(repo, rel)
    name = q.rsplit(".", 1)[-1]
    start = next((i for i in range(s["l"], min(len(ls), s["l"] + 40) + 1)
                  if re.match(rf"\s*(async\s+def|def|class)\s+{re.escape(name)}\b", ls[i - 1])), None)
    sig = doc = None
    if start:
        body = _body_at(repo, rel, start)
        parts = []
        if body and body[0] == start:              # 一行写完的 def f(...) -> None: ...：截到冒号（不然一直拼到下一个以冒号结尾的行）
            parts.append(ls[start - 1][:body[1]].strip())
        else:
            last = min(len(ls), start + 12, body[0] - 1 if body else len(ls))
            for i in range(start, last + 1):
                parts.append(ls[i - 1].strip())
                if ls[i - 1].rstrip().endswith(":"):
                    break
        sig = re.sub(r"\s+", " ", " ".join(parts)).replace("( ", "(").replace(" )", ")")
        doc = _doc(repo, rel, start)
    return {"file": rel, "line": start or s["l"], "end": s.get("e"), "signature": sig, "doc": doc, "kind": s.get("k")}


def _body_at(repo: Path, rel: str, line: int) -> tuple[int, int] | None:
    """第 line 行的 def / class 的体从哪开始：(行, 列)；找不到是 None"""
    tree = _ast(str(repo / rel), _mtime(repo / rel))
    for n in ast.walk(tree) if tree is not None else ():
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.lineno == line and n.body:
            return n.body[0].lineno, n.body[0].col_offset
    return None


def _doc(repo: Path, rel: str, line: int) -> str | None:
    tree = _ast(str(repo / rel), _mtime(repo / rel))
    if tree is None:
        return None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.lineno == line:
            d = ast.get_docstring(n)
            return d.strip().splitlines()[0] if d else None
    return None


def _mtime(p: Path) -> int:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return 0


@functools.lru_cache(maxsize=32)
def _ast(path: str, mtime: int):
    try:
        return ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None


def _lines(repo: Path, rel: str) -> tuple:
    return _source.lines_of(str(repo / rel), _mtime(repo / rel))


def function(rd: Path, run: dict, hot: dict, node: str, key_ids: set[int], phase: str | None) -> dict:
    """{item, ran, lanes: [{lane, n, first_us, last_us}], callers, calls（仓库里的被调函数）, kernels（启动的 GPU kernel）, ran_as}；
    每个调用方 / 被调方 {fn, n, only, lines, status, note, why}，按次数排，全列"""
    tal = _lanes.tid_aliases(rd)
    pc = _seq.phase_calls(rd, run, phase)
    per_lane: dict[str, list] = {}
    for (pid, tid, _, b), e in pc["calls"].items():
        if b in key_ids:
            x = per_lane.setdefault(tal.get((pid, tid), f"{pid}/{tid}"), [0, e[0], e[1]])
            x[0] += e[2]
            x[1], x[2] = min(x[1], e[0]), max(x[2], e[1])
    calls = hot.get("calls") or {}
    callers = sorted(((k.partition("|")[0], v) for k, v in calls.items() if k.partition("|")[2] == node), key=lambda kv: -kv[1]["n"])
    callees = sorted(((k.partition("|")[2], v) for k, v in calls.items() if k.partition("|")[0] == node), key=lambda kv: -kv[1]["n"])

    def pair(fn: str, v: dict) -> dict:
        # 和边详情（ui/edge.py）同一个判法：按只有 trace 的次数
        only = v.get("only") or 0
        status = "trace" if only >= v["n"] else "both" if not only else "mixed"
        note = _align.top_note(v) if only else None
        return {"fn": fn, "n": v["n"], "only": only, "lines": [ln.get("l") for ln in v.get("lines") or [] if ln.get("l")][:3],
                "status": status, "note": note, "why": _align.note_short(note)}

    def kernel(v: dict) -> bool:
        return any((ln.get("note") or {}).get("k") == "gpu" for ln in v.get("lines") or [])
    # 代码里写成调它、跑的是同名的别的方法（override：子类覆盖的或接口的实现）：explain 一个基类的方法时，它自己可能一次也没跑
    ran_as: dict[str, dict] = {}
    for k, v in calls.items():
        for ln in v.get("lines") or []:
            nt = ln.get("note") or {}
            if nt.get("k") == "override" and nt.get("w") == node:
                caller, _, callee = k.partition("|")
                x = ran_as.setdefault(callee, {"fn": callee, "n": 0, "callers": []})
                x["n"] += ln.get("n") or 0
                x["callers"].append({"fn": caller, "line": ln.get("l")})
    return {"item": node, "ran": bool(per_lane),
            "lanes": [{"lane": k, "n": v[0], "first_us": v[1], "last_us": v[2]} for k, v in sorted(per_lane.items(), key=lambda kv: -kv[1][0])],
            "callers": [pair(f, v) for f, v in callers],
            "calls": [pair(f, v) for f, v in callees if not kernel(v)],
            "kernels": [{"fn": f, "n": v["n"]} for f, v in callees if kernel(v)],
            "ran_as": sorted(ran_as.values(), key=lambda x: -x["n"])}
