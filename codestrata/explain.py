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

from . import align as _align
from . import lanes as _lanes
from . import seq as _seq
from .errors import CodestrataError
from .ui import source as _source

CHAIN = 8                       # 调用链最多几层（离这次调用最近的几层）
OUTER = 2                       # 所在分支再往外列几层
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_WRAPS = (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.ExceptHandler, ast.match_case) + \
    ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
_TRIES = (ast.Try,) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())


# ---------------------------------------------------------------- 源码原文

def branch(repo: Path, rel: str, line: int) -> dict | None:
    """这一行所在的分支（按 ast 找，不看缩进）：装着它的最近一个 if / elif / else，到所在的函数为止——
    {line: if / elif / else 那一行, kind: if | elif | else, text: 那一行的原文（条件压成一行）,
     conds: else 时前面都不成立的那几个条件 [{line, text}]（if、elif…，按先后）,
     inside: 这个分支和这一行之间还套着的 for / while / with / try / except / case 的头 [{line, text}],
     outer: 再往外的几层分支（同样的 line / kind / text / conds，由近到远，最多 OUTER 层）}。
    不在任何 if 里时 kind / line / text 是 None（inside 照给）；外面什么都没套是 None"""
    tree = _ast(str(repo / rel), _mtime(repo / rel))
    if tree is None:
        return None
    ls = _lines(repo, rel)
    path = _enclosing(tree, line)
    inside: list[dict] = []
    for j in range(len(path) - 2, -1, -1):
        node, field = path[j][1], path[j + 1][0]
        if isinstance(node, _SCOPES):
            break
        if isinstance(node, ast.If) and field in ("body", "orelse"):
            return _if_branch(path, j, field, ls) | {"inside": inside[::-1], "outer": _outer(path, j, ls)}
        if isinstance(node, _TRIES):
            if field != "handlers":              # except 的头由 ExceptHandler 自己给
                inside.append(_try_part(node, field, ls))
        elif isinstance(node, _WRAPS):
            inside.append(_header(node, ls))
    return {"line": None, "kind": None, "text": None, "conds": [], "inside": inside[::-1]} if inside else None


def _outer(path: list, j: int, ls: tuple) -> list[dict]:
    """j 那个 if 所在的 if / elif 链再往外的分支（到所在的函数为止，最多 OUTER 层，由近到远）"""
    out = []
    m = _chain_head(path, j, ls) - 1
    while m >= 0 and len(out) < OUTER:
        node, field = path[m][1], path[m + 1][0]
        if isinstance(node, _SCOPES):
            break
        if isinstance(node, ast.If) and field in ("body", "orelse"):
            out.append(_if_branch(path, m, field, ls))
            m = _chain_head(path, m, ls)
        m -= 1
    return out


def _chain_head(path: list, j: int, ls: tuple) -> int:
    """elif 在 ast 里是上一个 if 的 orelse：往上走到这条 if / elif 链的开头"""
    while _is_elif(path, j, ls):
        j -= 1
    return j


def _span(n) -> tuple[int, int]:
    if isinstance(n, ast.match_case):            # case 没有行号，按它的 pattern 和最后一条语句
        return n.pattern.lineno, n.body[-1].end_lineno or n.pattern.lineno
    return n.lineno, getattr(n, "end_lineno", None) or n.lineno


def _enclosing(tree, line: int) -> list[tuple[str, object]]:
    """从模块往下、装着这一行的语句一层层：[(它在父节点的哪个字段, 节点)]，最外层在前，最后一个是这一行自己那条语句"""
    out: list[tuple[str, object]] = []
    node = tree
    while True:
        nxt = None
        for field in ("body", "orelse", "handlers", "finalbody", "cases"):
            for ch in getattr(node, field, None) or []:
                if not isinstance(ch, (ast.stmt, ast.ExceptHandler, ast.match_case)):
                    continue
                a, b = _span(ch)
                if a <= line <= b:
                    nxt = (field, ch)
                    break
            if nxt:
                break
        if nxt is None:
            return out
        out.append(nxt)
        node = nxt[1]


def _flat(s: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _header(node, ls: tuple) -> dict:
    a, _ = _span(node)
    return {"line": a, "text": _flat(ls[a - 1]) if 0 < a <= len(ls) else ""}


def _try_part(node, field: str, ls: tuple) -> dict:
    if field == "body":
        return {"line": node.lineno, "text": "try:"}
    xs = node.orelse if field == "orelse" else node.finalbody
    ln = _keyword_line(ls, xs[0].lineno, "else" if field == "orelse" else "finally") if xs else node.lineno
    return {"line": ln, "text": "else:（try 没出异常时）" if field == "orelse" else "finally:"}


def _keyword_line(ls: tuple, before: int, word: str) -> int:
    """before 这一行往上第一个以 word 开头的行（else: / finally: 那一行）"""
    for i in range(before - 1, 0, -1):
        if ls[i - 1].strip().startswith(word):
            return i
    return before


def _cond(node, ls: tuple) -> str:
    seg = ast.get_source_segment("\n".join(ls), node.test)
    return _flat(seg or "?")


def _is_elif(path: list, j: int, ls: tuple) -> bool:
    node = path[j][1]
    if j == 0 or path[j][0] != "orelse":
        return False
    par = path[j - 1][1]
    return isinstance(par, ast.If) and par.orelse == [node] and ls[node.lineno - 1].lstrip().startswith("elif")


def _if_branch(path: list, j: int, field: str, ls: tuple) -> dict:
    node = path[j][1]
    if field == "body":
        kind = "elif" if _is_elif(path, j, ls) else "if"
        return {"line": node.lineno, "kind": kind, "text": f"{kind} {_cond(node, ls)}:", "conds": []}
    conds = []                                   # else：这条 if / elif 链上的条件都不成立
    k = j
    while True:
        n = path[k][1]
        elif_ = _is_elif(path, k, ls)
        conds.append({"line": n.lineno, "text": f"{'elif' if elif_ else 'if'} {_cond(n, ls)}"})
        if not elif_:
            break
        k -= 1
    first = node.orelse[0]
    return {"line": _keyword_line(ls, first.lineno, "else"), "kind": "else", "text": "else:", "conds": conds[::-1]}


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

def link(repo: Path, rd: Path, idx: dict, hot: dict, g: dict, pick: int | None, lo: int, hi: int, label) -> dict:
    """讲一组交接（linkgroups.groups 的一组）：组里两头的（函数, 行）有哪几种，挑一种（pick：第几种，缺省次数最多的）从它第一次讲起——
    两头的列、函数、行的原文和所在分支、定义；那一刻的调用链（放 / 取在仓库外的代码里时：当时这条线程栈上的仓库函数）；
    放之前这条线程最近收到的交接（inferred: time）；取的一头调那个函数调了几次；scan 对「谁调了放 / 取所在的函数」的说法"""
    if g["kind"] != "handoff":
        raise CodestrataError("usage", f"explain 现在只讲交接（handoff）的连线；{g['kind']} 的用 codestrata links --kind {g['kind']} 看两头")
    kinds = g["pairs"]
    if not kinds:
        raise CodestrataError("item_not_found", f"{g['id']} 这组没有记下两头")
    if pick is not None and not 1 <= pick <= len(kinds):
        raise CodestrataError("item_not_found", f"{g['id']} 这组两头只有 {len(kinds)} 种（列出的），没有 #{pick}",
                              candidates=[f"{g['id']}#{k}" for k in range(1, len(kinds) + 1)])
    pr = kinds[(pick or 1) - 1]
    ix = _seq.span_index(rd)
    keys = ix["keys"]
    tal = _lanes.tid_aliases(rd)
    h = (ix.get("handoffs") or [])[pr["h"]] if pr.get("h") is not None else None
    if h is None:
        raise CodestrataError("item_not_found", f"{g['id']} 这一种两头找不到录到的那一次（录制格式太老？）")
    rows = {p: _seq.pid_rows(rd, p) for p in {h["from"][0], h["to"][0]}}

    def end(raw: list, side: dict) -> dict:
        pid, tid, row, t = raw[0], raw[1], raw[2], raw[3]
        rs = rows[pid]
        inspan = 0 <= row < len(rs) and rs[row] is not None
        fn = side["fn"]
        d = definition(repo, idx, fn) if fn else None
        at = row if inspan else _covering(rs, tid, t)   # 放 / 取在仓库外的代码里：当时这条线程上最深的、还没返回的仓库调用
        ch = chain(rs, at, keys, label) if at is not None else []
        return {"lane": tal.get((pid, tid), f"{pid}/{tid}"), "fn": fn, "t_us": t, "outside": side["outside"],
                "maybe_other_task": not inspan and _suspended(rs, at),
                "code": code_at(repo, d["file"] if d else None, side["line"]) if fn else None,
                "def": d, "chain": ch, "pid": pid, "tid": tid, "key": rs[row][5] if inspan else None}
    a, b = end(h["from"], pr["from"]), end(h["to"], pr["to"])
    # 取的一头：这条线程在这段时间里调那个取数函数调了几次（轮询的话很多次，这次取到了）
    take_n = sum(r[6] for r in rows[b["pid"]] if r is not None and r[2] == b["tid"] and r[5] == b["key"] and lo <= r[0] < hi) \
        if b["key"] is not None else None
    out = {"item": g["id"] + (f"#{pick}" if pick else ""), "kind": g["kind"], "via": g["via"], "from_lane": g["from"], "to_lane": g["to"],
           "n": g["n"], "first_us": g["first_us"], "last_us": g["last_us"],
           "kinds": [{"k": k, "n": x["n"], "first_us": x["first_us"], "from": x["from"], "to": x["to"]} for k, x in enumerate(kinds, 1)],
           "n_kinds": g["n_pairs"], "pick": pick or 1, "pick_n": pr["n"],
           "from": a, "to": b, "take_calls": take_n,
           "recent_handoff": recent_handoff(ix, a["pid"], a["tid"], a["t_us"], lambda p_, t_: tal.get((p_, t_), f"{p_}/{t_}")),
           "scan": {"from": _scan_end(hot, a), "to": _scan_end(hot, b)}}
    for e in (a, b):
        e.pop("key", None)
    return out


def _covering(rows: list, tid: int, t: int) -> int | None:
    """t 那一刻 tid 上还没返回的调用里最深的那一个的下标（没有是 None）。没录到返回的行只信深度 0 的（线程入口一直在跑），
    深的多半是没收尾的生成器"""
    best = None
    for i, r in enumerate(rows):
        if r is None or len(r) > 9 or r[2] != tid:
            continue
        if r[0] > t:
            break
        live = r[0] + r[1] >= t if r[1] >= 0 else r[3] == 0
        if live and (best is None or r[3] >= rows[best][3]):
            best = i
    return best


def _suspended(rows: list, i: int | None) -> bool:
    """i 往上的调用里有没有挂起过的 async 调用（有的话「当时栈上」可能混着同一条线程上别的 task）"""
    n = 0
    while i is not None and 0 <= i < len(rows) and rows[i] is not None and n < 64:
        if rows[i][7]:
            return True
        i = rows[i][8] if rows[i][8] >= 0 else None
        n += 1
    return False


def _scan_end(hot: dict, e: dict) -> dict | None:
    """scan 对「调用链上一层调了这一头的函数」的说法（放 / 取在仓库外的代码里时不说：链上最后一个不是放 / 取所在的函数）"""
    if e["outside"] or len(e["chain"]) < 2:
        return None
    x = scan_says(hot, e["chain"][-2]["fn"], e["fn"])
    return x | {"caller": e["chain"][-2]["fn"]} if x else None


# ---------------------------------------------------------------- 一个函数

def function(repo: Path, rd: Path, run: dict, idx: dict, hot: dict, node: str, key_ids: set[int], lo: int, hi: int, label,
             phase: str | None) -> dict:
    ix = _seq.span_index(rd)
    keys = ix["keys"]
    tal = _lanes.tid_aliases(rd)

    def alias_of(pid: int, tid: int) -> str:
        return tal.get((pid, tid), f"{pid}/{tid}")
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
        # 和边详情（ui/edge.py）同一个判法：按只有 trace 的次数；老 run（没有调用行）也对
        only = v.get("only") or 0
        status = "trace" if only >= v["n"] else "both" if not only else "mixed"
        note = _align.top_note(v) if only else None
        return {"fn": fn, "n": v["n"], "only": only, "lines": [ln.get("l") for ln in v.get("lines") or [] if ln.get("l")][:3],
                "status": status, "note": note, "why": _align.note_short(note)}
    # 代码里写成调它、跑的是同名的别的方法（override：子类覆盖的或接口的实现）：explain 一个基类的方法时，它自己可能一次也没跑
    ran_as: dict[str, dict] = {}
    for k, v in calls.items():
        lines = v.get("lines")
        rows = lines if lines is not None else [{"note": v.get("note"), "n": v["n"], "l": (v.get("guessed") or [None])[0]}]
        for ln in rows:
            nt = ln.get("note") or {}
            if nt.get("k") == "override" and nt.get("w") == node:
                caller, _, callee = k.partition("|")
                x = ran_as.setdefault(callee, {"fn": callee, "n": 0, "callers": []})
                x["n"] += ln.get("n") or 0
                x["callers"].append({"fn": caller, "line": ln.get("l")})
    out = {"item": node, "kind": "function", "def": definition(repo, idx, node), "ran": bool(per_lane),
           "lanes": [{"lane": k, "n": v[0], "first_us": v[1], "last_us": v[2]} for k, v in sorted(per_lane.items(), key=lambda kv: -kv[1][0])],
           "callers": [pair(f, v) for f, v in callers[:5]], "callees": [pair(f, v) for f, v in callees[:5]],
           "ran_as": sorted(ran_as.values(), key=lambda x: -x["n"])[:5], "first": None, "recent_handoff": None}
    if first:
        t0, pid, i, rows = first
        r = rows[i]
        out["first"] = {"lane": alias_of(pid, r[2]), "t_us": t0, "chain": chain(rows, i, keys, label)}
        out["recent_handoff"] = recent_handoff(ix, pid, r[2], t0, alias_of)
    return out


def klass(repo: Path, rd: Path, run: dict, idx: dict, hot: dict, node: str, lo: int, hi: int, label, phase: str | None) -> dict:
    """一个类：定义、它的方法这段时间里各调了几次（合起来在哪几列跑过）、第一次调到它的方法那一刻的调用链；谁构造了它（scan 把
    构造算到类上）"""
    keys = _seq.span_index(rd)["keys"]
    pre = node + "."
    meth: dict[str, set[int]] = {}
    for i, k in enumerate(keys):
        lab = label(k) if k != "?" else None
        if lab and lab.startswith(pre):
            meth.setdefault(lab, set()).add(i)
    ids = set().union(*meth.values()) if meth else set()
    d = function(repo, rd, run, idx, hot, node, ids, lo, hi, label, phase)
    pc = _seq.phase_calls(rd, run, phase)
    n_of: dict[str, int] = {}
    for (_, _, _, b), e in pc["calls"].items():
        if b in ids:
            m = label(keys[b])
            n_of[m] = n_of.get(m, 0) + e[2]
    d["kind"] = "class"
    d["methods"] = [{"fn": m, "n": n} for m, n in sorted(n_of.items(), key=lambda kv: -kv[1])]
    d["callees"] = []
    return d


# ---------------------------------------------------------------- 切面上的一个节点（页面上选中的）

def node(rd: Path, run: dict, phase: str | None, label, item: str, lane: str | None, top: int = 10) -> dict:
    """切面上的一个节点（目录 d/、本层文件 d/*、文件）：这段时间里它里面跑过哪些函数、各几次（给了列只算这一列）"""
    from . import finder as _finder
    pc = _seq.phase_calls(rd, run, phase)
    aliases = _lanes.run_aliases(rd)
    per = _finder.node_counts(pc["calls"], pc["keys"], pc["threads"], label,
                              lambda pid, tname: aliases.get(_lanes.lane_id(pid, tname), f"{pid}:{tname}"))

    def inside(fn: str) -> bool:
        f = fn.partition("#")[0]
        if item.endswith("/*"):                      # 本层文件：目录直接装着的文件
            d = item[:-1]
            return f.startswith(d) and "/" not in f[len(d):]
        return f.startswith(item) if item.endswith("/") else f == item
    fns = []
    for fn, lanes_ in per.items():
        if not inside(fn):
            continue
        n = lanes_.get(lane, [0])[0] if lane else sum(x[0] for x in lanes_.values())
        if n:
            fns.append({"fn": fn, "n": n, "lanes": sorted(lanes_)})
    fns.sort(key=lambda x: -x["n"])
    return {"kind": "node", "item": item, "lane": lane, "n": sum(x["n"] for x in fns), "n_fns": len(fns), "fns": fns[:top]}


# ---------------------------------------------------------------- 分列里列中的一条边

def edge(repo: Path, idx: dict, lane_hot: dict, lane_alias: str, e: dict, top: int = 5) -> dict:
    """列中的一条边（切面上两个节点之间、这一列里的调用）：是什么、底下次数最多的几对函数和调用那一行的原文、scan 的说法"""
    from .ui import edge as _edge
    d = _edge.edge_detail(repo, idx, e["a"], e["b"], lane_hot)
    pairs = []
    for c in (d.get("calls") or [])[:top]:
        ln = next(iter(c.get("lines") or []), None)
        note = _align.top_note(c) if c.get("status") != "both" else None
        pairs.append({"caller": c["caller"], "callee": c["callee"], "n": c["n"], "only": c.get("only") or 0, "status": c.get("status"),
                      "note": note, "why": _align.note_short(note),
                      "code": code_at(repo, ln["f"], ln["l"]) if ln and ln.get("l") else None,
                      "def": definition(repo, idx, c["callee"])})
    return {"kind": "edge", "lane": lane_alias, "a": e["a"], "b": e["b"], "n": e.get("n"), "only": e.get("only"),
            "first_us": e.get("first"), "last_us": e.get("last"), "repeat": bool(e.get("repeat")), "pairs": pairs}
