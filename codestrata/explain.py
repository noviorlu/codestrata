"""explain 的原料：一条连线（l:handoff|通道|起列|终列）或一个函数——是什么、两头的代码原文、定义的签名和 docstring 第一行、
调用那一行所在的分支、第一次发生那一刻的调用链、这条线程之前最近收到的交接、scan 的说法。只取数和源码原文，不下结论：
「为什么」由 agent 读完代码自己说。

最近收到的交接只是时间上最近（积压时可能不是起因），一律标 inferred: time（用户 10-10 定：附上、标明）。
"""
from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

from . import lanes as _lanes
from . import seq as _seq
from .errors import CodestrataError
from .ui import source as _source

CHAIN = 8                       # 调用链最多几层（离这次调用最近的几层）
_BRANCH = re.compile(r"^(if|elif|else|try|except|finally|for|while|with|match|case)\b")
_SCOPE = re.compile(r"^(async\s+def|def|class)\b")


# ---------------------------------------------------------------- 源码原文

def branch(repo: Path, rel: str, line: int) -> dict | None:
    """这一行所在的分支：往上找最近一个缩进更浅的 if / elif / else / try / except / for / while / with 头（碰到 def / class 就停），只给原文和行号"""
    ls = _lines(repo, rel)
    if not 0 < line <= len(ls):
        return None
    ind = _indent(ls[line - 1])
    for i in range(line - 1, 0, -1):
        s = ls[i - 1]
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        d = _indent(s)
        if d < ind:
            t = s.strip()
            if _SCOPE.match(t):
                return None
            if _BRANCH.match(t):
                return {"line": i, "text": t}
            ind = d
    return None


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
        parts = []
        for i in range(start, min(len(ls), start + 12) + 1):
            parts.append(ls[i - 1].strip())
            if ls[i - 1].rstrip().endswith(":"):
                break
        sig = re.sub(r"\s+", " ", " ".join(parts)).replace("( ", "(").replace(" )", ")")
        doc = _doc(repo, rel, start)
    return {"file": rel, "line": start or s["l"], "end": s.get("e"), "signature": sig, "doc": doc, "kind": s.get("k")}


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


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip())


def code_at(repo: Path, rel: str | None, line: int | None) -> dict | None:
    """一行原文和它所在的分支"""
    if not rel or not line:
        return None
    return {"file": rel, "line": line, "text": _source.line_text(repo, rel, line).strip(), "branch": branch(repo, rel, line)}


# ---------------------------------------------------------------- 运行时

def chain(rows: list, i: int, keys: list[str], label) -> list[dict]:
    """span i 往上的调用链（栈底在前），最多 CHAIN 层：[{fn, t0_us, dur_us}]"""
    out = []
    while 0 <= i < len(rows) and rows[i] is not None and len(out) < 64:
        r = rows[i]
        out.append({"fn": label(keys[r[5]]), "t0_us": r[0], "dur_us": r[1]})
        i = r[8] if len(r) > 8 else -1
    return out[::-1][-CHAIN:]


def recent_handoff(ix: dict, pid: int, tid: int, t: int, alias_of) -> dict | None:
    """这条线程在 t 之前最近收到的那次交接（只是时间上最近：inferred: time）"""
    best = None
    for h in ix.get("handoffs") or []:
        if h["to"][0] == pid and h["to"][1] == tid and h["to"][3] <= t and (best is None or h["to"][3] > best["to"][3]):
            best = h
    if best is None:
        return None
    return {"via": best["via"], "from": alias_of(best["from"][0], best["from"][1]), "sent_us": best["from"][3],
            "received_us": best["to"][3], "ago_us": t - best["to"][3], "basis": "inferred: time"}


def scan_says(hot: dict, caller: str | None, callee: str | None) -> dict | None:
    """scan 对「caller 调 callee」的说法：both（代码里写明的调用，这次也录到了）/ trace（代码里看不出会调到它）"""
    if not caller or not callee:
        return None
    x = (hot.get("calls") or {}).get(f"{caller}|{callee}")
    if not x:
        return None
    st = {ln.get("status") for ln in x.get("lines") or []}
    return {"status": "trace" if st == {"trace"} else "both" if st else None, "lines": x.get("lines") or [], "n": x.get("n")}


# ---------------------------------------------------------------- 一条连线

def parse_link(item: str) -> tuple[str, str, str, str]:
    parts = item.split("|")
    if len(parts) != 4 or not parts[0].startswith("l:"):
        raise CodestrataError("usage", f"连线写成 'l:种类|通道|起列|终列'：{item!r}")
    return parts[0][2:], parts[1], parts[2], parts[3]


def link(repo: Path, rd: Path, idx: dict, hot: dict, item: str, lo: int, hi: int, label, at_us: int | None = None) -> dict:
    """at_us：页面上画的那一条连线第一次的时刻（explain 24 按视图挑出来的）：这一组里从那次讲起"""
    kind, via, fa, ta = parse_link(item)
    if kind != "handoff":
        raise CodestrataError("usage", f"explain 现在只讲交接（handoff）的连线；{kind} 的用 codestrata links --kind {kind} 看两头")
    ix = _seq.span_index(rd)
    keys = ix["keys"]
    aliases = _lanes.run_aliases(rd)
    threads = ix["threads"]

    def alias_of(pid: int, tid: int) -> str:
        lid = _lanes.lane_id(pid, (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}")
        return aliases.get(lid, lid)
    evs = [h for h in ix.get("handoffs") or [] if h["via"] == via and lo <= h["from"][3] < hi
           and alias_of(h["from"][0], h["from"][1]) == fa and alias_of(h["to"][0], h["to"][1]) == ta]
    if not evs:
        cands = sorted({f"l:handoff|{h['via']}|{alias_of(h['from'][0], h['from'][1])}|{alias_of(h['to'][0], h['to'][1])}"
                        for h in ix.get("handoffs") or [] if lo <= h["from"][3] < hi})
        raise CodestrataError("item_not_found", f"这段时间里没有 {item} 这组交接", candidates=cands)
    evs.sort(key=lambda h: h["from"][3])
    h = next((x for x in evs if at_us is not None and x["from"][3] >= at_us), evs[0])
    rows = {p: _seq.pid_rows(rd, p) for p in {h["from"][0], h["to"][0]}}

    def end(e: list) -> dict:
        pid, tid, row, t = e[0], e[1], e[2], e[3]
        line = e[4] if len(e) > 4 else 0
        r = rows[pid][row] if 0 <= row < len(rows[pid]) and rows[pid][row] is not None else None
        fn = label(keys[r[5]]) if r else None
        d = definition(repo, idx, fn) if fn else None
        return {"lane": alias_of(pid, tid), "fn": fn, "t_us": t, "code": code_at(repo, d["file"] if d else None, line) if fn else None,
                "def": d, "chain": chain(rows[pid], row, keys, label) if r else [], "pid": pid, "tid": tid, "key": r[5] if r else None}
    a, b = end(h["from"]), end(h["to"])
    # 取的一头：这条线程在这段时间里调那个取数函数调了几次（轮询的话很多次，这次取到了）
    take_n = sum(r[6] for r in rows[b["pid"]] if r is not None and r[2] == b["tid"] and r[5] == b["key"] and lo <= r[0] < hi) \
        if b["key"] is not None else None
    caller = a["chain"][-2]["fn"] if len(a["chain"]) > 1 else None
    out = {"item": item, "kind": kind, "via": via, "from_lane": fa, "to_lane": ta, "n": len(evs),
           "events": [{"sent_us": x["from"][3], "received_us": x["to"][3]} for x in evs[:5]],
           "from": a, "to": b, "take_calls": take_n,
           "recent_handoff": recent_handoff(ix, a["pid"], a["tid"], a["t_us"], alias_of),
           "scan": {"from": scan_says(hot, caller, a["fn"]),
                    "to": scan_says(hot, b["chain"][-2]["fn"] if len(b["chain"]) > 1 else None, b["fn"])}}
    for e in (a, b):
        e.pop("key", None)
    return out


# ---------------------------------------------------------------- 一个函数

def function(repo: Path, rd: Path, run: dict, idx: dict, hot: dict, node: str, key_ids: set[int], lo: int, hi: int, label,
             phase: str | None) -> dict:
    ix = _seq.span_index(rd)
    keys = ix["keys"]
    aliases = _lanes.run_aliases(rd)
    threads = ix["threads"]

    def alias_of(pid: int, tid: int) -> str:
        lid = _lanes.lane_id(pid, (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}")
        return aliases.get(lid, lid)
    pc = _seq.phase_calls(rd, run, phase)
    per_lane: dict[str, list] = {}
    for (pid, tid, _, b), e in pc["calls"].items():
        if b in key_ids:
            x = per_lane.setdefault(alias_of(pid, tid), [0, e[0], e[1]])
            x[0] += e[2]
            x[1], x[2] = min(x[1], e[0]), max(x[2], e[1])
    first = None                                 # 这段时间里第一次调用：(t0, pid, 下标, 行)
    for pid in sorted({k[0] for k in pc["calls"] if k[3] in key_ids}):
        rows = _seq.pid_rows(rd, pid)
        for i, r in enumerate(rows):
            if r is not None and len(r) <= 9 and r[5] in key_ids and lo <= r[0] < hi and (first is None or r[0] < first[0]):
                first = (r[0], pid, i, rows)
                break
    calls = hot.get("calls") or {}
    callers = sorted(((k.partition("|")[0], v) for k, v in calls.items() if k.partition("|")[2] == node), key=lambda kv: -kv[1]["n"])
    callees = sorted(((k.partition("|")[2], v) for k, v in calls.items() if k.partition("|")[0] == node), key=lambda kv: -kv[1]["n"])

    def pair(fn: str, v: dict) -> dict:
        st = {ln.get("status") for ln in v.get("lines") or []}
        return {"fn": fn, "n": v["n"], "lines": [ln.get("l") for ln in v.get("lines") or [] if ln.get("l")][:3],
                "status": "trace" if st == {"trace"} else "both"}
    out = {"item": node, "def": definition(repo, idx, node),
           "lanes": [{"lane": k, "n": v[0], "first_us": v[1], "last_us": v[2]} for k, v in sorted(per_lane.items(), key=lambda kv: -kv[1][0])],
           "callers": [pair(f, v) for f, v in callers[:5]], "callees": [pair(f, v) for f, v in callees[:5]],
           "first": None, "recent_handoff": None}
    if first:
        t0, pid, i, rows = first
        r = rows[i]
        out["first"] = {"lane": alias_of(pid, r[2]), "t_us": t0, "chain": chain(rows, i, keys, label)}
        out["recent_handoff"] = recent_handoff(ix, pid, r[2], t0, alias_of)
    return out


# ---------------------------------------------------------------- 分列里列中的一条边

def edge(repo: Path, idx: dict, lane_hot: dict, lane_alias: str, e: dict, top: int = 5) -> dict:
    """列中的一条边（切面上两个节点之间、这一列里的调用）：是什么、底下次数最多的几对函数和调用那一行的原文、scan 的说法"""
    from .ui import edge as _edge
    d = _edge.edge_detail(repo, idx, e["a"], e["b"], lane_hot)
    pairs = []
    for c in (d.get("calls") or [])[:top]:
        ln = next(iter(c.get("lines") or []), None)
        pairs.append({"caller": c["caller"], "callee": c["callee"], "n": c["n"], "status": c.get("status"),
                      "code": code_at(repo, ln["f"], ln["l"]) if ln and ln.get("l") else None,
                      "def": definition(repo, idx, c["callee"])})
    return {"kind": "edge", "lane": lane_alias, "a": e["a"], "b": e["b"], "n": e.get("n"), "only": e.get("only"),
            "first_us": e.get("first"), "last_us": e.get("last"), "repeat": bool(e.get("repeat")), "pairs": pairs}
