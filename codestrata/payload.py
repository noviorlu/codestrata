"""组装前端要的数据。serve（live）和 export（单文件）共用这一份，免得两边漂移。"""
from __future__ import annotations

import json
from pathlib import Path

from . import layout as _layout
from . import notes as _notes
from . import trace as _trace


def load_index(repo: Path) -> dict:
    d = repo / ".codestrata"
    p = d / "index.json"
    if not p.exists():
        raise SystemExit(f"没有 {p}；先跑 codestrata scan {repo}")
    idx = json.loads(p.read_text(encoding="utf-8"))
    sp = d / "symbols.json"
    if sp.exists():
        extra = json.loads(sp.read_text(encoding="utf-8"))
        idx["symbols"] = extra.get("symbols", {})
        idx["files"] = extra.get("files", {})
    return idx


def load_hot(repo: Path, idx: dict, case: str | None) -> tuple[dict | None, dict | None]:
    if not case:
        return None, None
    tp = repo / ".codestrata" / f"trace-{case}.json"
    if not tp.exists():
        raise SystemExit(f"没有 {tp}；先跑 codestrata trace {repo} --case {case} -- <命令>")
    tr = json.loads(tp.read_text(encoding="utf-8"))
    hot = _trace.to_package_graph(tr, idx)
    meta = {"case": tr.get("case"), "cmd": tr.get("cmd"),
            "n_procs": tr.get("n_procs"), "unmapped": hot.get("unmapped"),
            # 老 trace 没存哈希时拿不到这个信息，就不报（而不是误报全部过期）
            "stale_files": _trace.stale_files(repo, tr) if tr.get("file_shas") else []}
    return hot, meta


def _pkg_syms(idx: dict) -> dict:
    out: dict[str, list] = {}
    for key, s in (idx.get("symbols") or {}).items():
        if "." in s["n"]:                  # 只列顶层类/函数，方法太多
            continue
        out.setdefault(s["p"], []).append(
            {"key": key, "n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"],
             "b": s.get("b", [])})
    for v in out.values():
        v.sort(key=lambda d: (d["k"] != "class", d["f"], d["l"]))
    return out


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, lanes="auto", min_files: int = 1) -> dict:
    g = _layout.build(idx, lanes=lanes, min_files=min_files)
    repo_info = dict(idx["repo"])
    repo_info["n_symbols"] = len(idx.get("symbols") or {})
    return {"repo": repo_info, "graph": g, "pkgs": idx["packages"],
            "pkgSyms": _pkg_syms(idx), "hot": hot, "hotMeta": hot_meta}


def symbol_source(repo: Path, idx: dict, key: str, lines: int = 40) -> dict | None:
    s = (idx.get("symbols") or {}).get(key)
    if not s:
        return None
    try:
        src = (repo / s["f"]).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return None
    a = max(0, s["l"] - 1)
    return {"key": key, "name": s["n"], "file": s["f"], "line": s["l"],
            "bases": s.get("b", []), "code": "\n".join(src[a:a + lines])}


def export_payload(repo: Path, idx: dict, *, hot=None, hot_meta=None,
                   per_pkg: int = 10, lines: int = 30) -> dict:
    """单文件导出要的全部数据：图 + 已有解读 + 待办输入包 + 代表符号的源码。"""
    p = graph_payload(repo, idx, hot=hot, hot_meta=hot_meta)
    nts = {name: _notes.load(repo, idx, name) for name in idx["packages"]}
    todo = _notes.tasks(repo, idx)
    packs = {t["target"]: _notes.prompt_pack(repo, idx, t["target"], hot=hot) for t in todo}
    sources = {}
    for pkg, syms in p["pkgSyms"].items():
        for s in syms[:per_pkg]:
            src = symbol_source(repo, idx, s["key"], lines)
            if src:
                sources[s["key"]] = src
    p.update({"notes": nts, "tasks": todo, "packs": packs, "sources": sources})
    return p
