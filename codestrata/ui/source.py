"""代码窗口：整个文件、符号片段、大纲、Ctrl+点击的跳转和引用（给 /api/file、/api/symbol、/api/outline、/api/refs）。"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

from .. import align as _align
from .. import highlight as _hl
from .. import xref as _xref


def known_file(idx: dict, rel: str) -> str | None:
    """只允许打开扫描过的文件（Python 或包内的 C++/CUDA），返回所属单元（C++ 是所在目录）。"""
    if rel in (idx.get("files") or {}):
        return idx["files"][rel]
    if rel in (idx.get("aux") or {}):
        return idx["aux"][rel] or "(无所属包)"
    for pkg, ds in (idx.get("docs") or {}).items():         # 挂在目录 / 单元上的文档也能打开
        if any(d["f"] == rel for d in ds):
            return pkg
    return None


def file_outline(repo: Path, idx: dict, rel: str) -> dict | None:
    """一个文件的完整符号大纲（含方法），给详情面板的文件树按需展开。
    Python 直接取扫描时的符号表，不用读文件；C++ / CUDA 用词法大纲（要高亮一遍，有缓存）。"""
    pkg = known_file(idx, rel)
    if pkg is None:
        return None
    syms = [{"key": k, "n": x["n"], "k": x["k"], "l": x["l"]}
            for k, x in (idx.get("symbols") or {}).items() if x["f"] == rel]
    if syms or rel.endswith((".py", ".pyi")):
        return {"file": rel, "symbols": sorted(syms, key=lambda d: d["l"]), "outline_kind": "ast"}
    fv = file_view(repo, idx, rel)
    return {"file": rel, "symbols": fv["symbols"] if fv else [], "outline_kind": "lexer"}


def file_view(repo: Path, idx: dict, rel: str, hot: dict | None = None) -> dict | None:
    """整个文件（逐行高亮）+ 符号大纲。Python 的大纲来自 ast（精确），
    C++/CUDA 的来自词法 token（启发式）。叠着一个 run（hot）时还有 runtime：见 runtime_lines"""
    pkg = known_file(idx, rel)
    if pkg is None:
        return None
    try:
        h = _hl.highlight_file(repo, rel)
    except OSError:
        return None
    if h["lang"] in ("python", "triton"):
        syms = [{"key": k, "n": x["n"], "k": x["k"], "l": x["l"]}
                for k, x in (idx.get("symbols") or {}).items() if x["f"] == rel]
        syms.sort(key=lambda d: d["l"])
        kind = "ast"
    else:
        syms = [{"key": "", "n": o["n"], "k": o["k"], "l": o["l"]} for o in h["outline"]]
        kind = "lexer"
    return {"file": rel, "pkg": pkg, "lang": h["lang"], "lang_label": h["label"],
            "n_lines": len(h["lines"]), "lines": h["lines"],
            "symbols": syms, "outline_kind": kind, "xref": xref_for(repo, rel),
            **({"runtime": runtime_lines(idx, rel, hot)} if hot else {})}


node_def = _align.node_def           # graph 节点的定义在哪 {f, l, k}（ui 里一直这么叫）


def runtime_lines(idx: dict, rel: str, hot: dict) -> dict:
    """这个文件里「只有 trace」的调用处：{行: [{callee, def: {f, l}, n}]}——代码里看不出会调到谁的那一行，
    这次运行调到了谁、几次；代码窗口在这一行给出跳到它的链接。只有记了调用行的 run 才有（老 run 是空的）；
    不知道是哪一行的（录制之后改过的文件）、被调方对不上的不标"""
    out: dict = {}
    for pk, x in (hot.get("calls") or {}).items():
        if not x.get("only") or x["lines"] is None:
            continue
        caller, _, callee = pk.partition("|")
        if node_def(idx, _align.base_node(caller))["f"] != rel or callee.endswith("#" + _align.UNMATCHED):
            continue
        d = node_def(idx, callee)
        for ln in x["lines"]:
            if ln["status"] == "trace" and ln["l"]:
                out.setdefault(ln["l"], []).append({"callee": callee, "def": {"f": d["f"], "l": d["l"]}, "n": ln["n"]})
    for v in out.values():
        v.sort(key=lambda r: -r["n"])
    return out


def symbol_source(repo: Path, idx: dict, key: str, lines: int = 40) -> dict | None:
    s = (idx.get("symbols") or {}).get(key)
    if not s:
        return None
    try:
        h = _hl.highlight_file(repo, s["f"])      # 整文件高亮后再切：从中间切会让跨行字符串着色出错
    except OSError:
        return None
    a = max(0, s["l"] - 1)
    return {"key": key, "name": s["n"], "file": s["f"], "line": s["l"],
            "bases": s.get("b", []), "lang": h["lang"], "lang_label": h["label"],
            "lines": h["lines"][a:a + lines], "xref": xref_for(repo, s["f"], a + 1, a + lines)}


# ---------------------------------------------------------------- 交叉引用（Ctrl+点击）

_XREF: dict = {"key": None, "x": None}
_XREF_LOCK = threading.Lock()


def load_xref(repo: Path) -> dict | None:
    """scan 写下的 xref.json（按修改时间缓存；重新 scan 之后下一次请求自动换成新的）。
    没有就返回 None：前端不给 Ctrl+点击。serve 是多线程的：新的一份整个建好了再一次性
    换上去，读的人拿到的要么是旧的、要么是新的，不会拿到一半。"""
    global _XREF
    p = repo / ".codestrata" / "xref.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    cur = _XREF
    if cur["key"] == (str(p), mt):
        return cur
    with _XREF_LOCK:
        if _XREF["key"] != (str(p), mt):
            x = json.loads(p.read_text(encoding="utf-8"))
            _XREF = {"key": (str(p), mt), "x": x, "inv": None, "inv_lock": threading.Lock(),
                     "tid": {t: i for i, t in enumerate(x["targets"])}}
        return _XREF


@lru_cache(maxsize=32)
def _xref_fp(path: str, mtime: float) -> dict:
    """xref.json 里每个文件 scan 时的 (大小, mtime)。自己一份小缓存，不走 load_xref 那个单槽的：
    主菜单一次要看好几个仓库，走单槽会互相挤掉、每次都重新解析整个 xref.json"""
    return json.loads(Path(path).read_text(encoding="utf-8")).get("fp") or {}


def _changed(repo: Path, rel: str, fp) -> bool:
    """这个文件和 scan 时记下的 (大小, mtime) 还一样吗；不在了也算改过"""
    try:
        st = (repo / rel).stat()
    except OSError:
        return True
    return [st.st_size, st.st_mtime_ns] != list(fp)


def index_lag(repo: Path) -> int:
    """scan 之后改过（或删掉）了几个文件。index 落后了，图和搜索还是 scan 时的样子
    （Ctrl+点击的交叉引用逐个文件核对，不受影响）。只是提示：算不出来（没 scan、老格式、文件坏了）就当 0"""
    p = repo / ".codestrata" / "xref.json"
    try:
        return sum(_changed(repo, rel, fp) for rel, fp in _xref_fp(str(p), p.stat().st_mtime).items())
    except Exception:                         # noqa: BLE001
        return 0


def _stale(repo: Path, X: dict, rel: str) -> bool:
    """这个文件在 scan 之后改过没有（大小或修改时间变了）。改过的文件，xref 里的行列号
    已经对不上了：链接会落在别的字上、跳到不相干的定义——宁可不给 Ctrl+点击。"""
    fp = (X["x"].get("fp") or {}).get(rel)
    return fp is not None and _changed(repo, rel, fp)   # 老的 xref.json 没记指纹：没法判断，照旧


def xref_for(repo: Path, rel: str, lo: int | None = None, hi: int | None = None) -> dict | None:
    """一个文件（或其中 lo..hi 行）里能解析的名字：[[行, 起, 止, 目标号, 种类], ...]（列是 UTF-16
    下标，和 JS 一致），以及用到的目标 {目标号: [目标, [定义文件, 行] | None]}。
    文件在 scan 之后改过时只回 {"stale": true}。"""
    X = load_xref(repo)
    if not X:
        return None
    if _stale(repo, X, rel):
        return {"stale": True, "toks": [], "targets": {}}
    toks = X["x"]["files"].get(rel) or []
    if lo is not None:
        toks = [t for t in toks if lo <= t[0] <= hi]
    tg, wh = X["x"]["targets"], X["x"]["where"]
    return {"toks": toks, "targets": {i: [tg[i], wh[i]] for i in sorted({t[3] for t in toks})}}


@lru_cache(maxsize=256)
def lines_of(path: str, mtime_ns: int) -> tuple:
    try:
        return tuple(Path(path).read_text(encoding="utf-8", errors="replace").split("\n"))
    except OSError:
        return ()


def line_text(repo: Path, rel: str, line: int) -> str:
    try:
        ls = lines_of(str(repo / rel), (repo / rel).stat().st_mtime_ns)   # 按修改时间失效
    except OSError:
        return ""
    return ls[line - 1] if 0 < line <= len(ls) else ""


def xref_inverted(X: dict) -> dict:
    if X["inv"] is None:
        with X["inv_lock"]:
            if X["inv"] is None:
                X["inv"] = _xref.invert(X["x"])
    return X["inv"]


def refs(repo: Path, target: str, hot: dict | None = None, limit: int = 500) -> dict | None:
    """一个定义被哪些地方引用：调用在前，其次是普通引用、import。同一行的几处合成一条（×N）。
    每条带上那一行的原文；文件在 scan 之后改过的标 stale（行号可能已经不对）。

    方法、类属性还另给一组「同名的 .xxx」：通过别的对象调用（engine.generate()）时，
    静态分析不知道那个对象是什么类型，确认不了是不是它——按名字列出来，标明没确认，
    并说仓库里一共有几个同名的成员（只有它一个时，基本就是它）。"""
    X = load_xref(repo)
    if not X or target not in X["tid"]:
        return None
    i = X["tid"][target]
    rank = {_xref.CALL: 0, _xref.REF: 1, _xref.IMPORT: 2}
    names = {_xref.CALL: "call", _xref.REF: "ref", _xref.IMPORT: "import"}
    counts: dict[str, int] = {}
    merged: dict[tuple, dict] = {}
    for f, l, c, k in xref_inverted(X).get(i, []):
        counts[names[k]] = counts.get(names[k], 0) + 1
        m = merged.get((f, l))
        if m is None or rank[k] < rank[m["k"]]:
            merged[(f, l)] = {"f": f, "l": l, "c": c, "k": k, "n": (m["n"] + 1) if m else 1}
        else:
            m["n"] += 1
    rows = sorted(merged.values(), key=lambda r: (rank[r["k"]], r["f"], r["l"]))
    stale_cache: dict[str, bool] = {}

    def stale(f):
        if f not in stale_cache:
            stale_cache[f] = _stale(repo, X, f)
        return stale_cache[f]

    out = []
    for r in rows[:limit]:
        r["text"] = line_text(repo, r["f"], r["l"]).strip()[:200]
        if stale(r["f"]):
            r["stale"] = True
        out.append(r)
    kind, _, key = target.partition(":")
    wh = X["x"]["where"][i]
    res = {"target": target, "where": wh, "total": sum(counts.values()), "lines": len(rows),
           "counts": counts, "refs": out,
           # 定义本身也放进列表（最上面一条）：跳到某个引用之后，点它就回到定义
           "def": ({"f": wh[0], "l": wh[1], "text": line_text(repo, wh[0], wh[1]).strip()[:200],
                    **({"stale": True} if stale(wh[0]) else {})} if wh else None),
           "calls": ((hot or {}).get("symbols") or {}).get(key, 0) if kind == "s" else 0}
    qual = key.partition("#")[2]
    if kind in ("s", "v") and "." in qual:           # 类的成员：方法、嵌套类、类属性、实例属性
        name = qual.rsplit(".", 1)[1]
        same = sum(1 for t in X["x"]["targets"]
                   if t[0] in "sv" and "." in t.partition("#")[2]
                   and t.rsplit(".", 1)[-1] == name)
        maybe = (X["x"].get("attrs") or {}).get(name) or []
        mrows = {}
        for f, l, c, e, k in maybe:
            m = mrows.get((f, l))
            if m is None:
                mrows[(f, l)] = {"f": f, "l": l, "c": c, "k": k, "n": 1}
            else:
                m["n"] += 1
        mrows = sorted(mrows.values(), key=lambda r: (-r["k"], r["f"], r["l"]))
        for r in mrows[:limit]:
            r["text"] = line_text(repo, r["f"], r["l"]).strip()[:200]
            if stale(r["f"]):
                r["stale"] = True
        res["maybe"] = {"name": name, "same": same, "total": len(maybe), "lines": len(mrows),
                        "refs": mrows[:limit]}
    return res
