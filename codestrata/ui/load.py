"""读索引、叠 run。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import cut as _cut
from .. import runs as _runs


def index_summary(repo: Path) -> dict | None:
    """只读 index.json（不读大得多的 symbols.json）：没 scan 过是 None。
    {scanned_at, n_files, n_symbols, n_parse_errors, roots}——主菜单的项目卡片、trace 的默认 roots 用"""
    p = repo / ".codestrata" / "index.json"
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
        at = p.stat().st_mtime
    except (OSError, ValueError):
        return None
    r = idx.get("repo") or {}
    return {"scanned_at": at, "n_files": r.get("n_files"), "n_symbols": idx.get("n_symbols"),
            "n_parse_errors": r.get("n_parse_errors"), "roots": r.get("roots") or [],
            "outdated": idx.get("format") != _cut.INDEX_FORMAT}


def load_index(repo: Path) -> dict:
    d = repo / ".codestrata"
    p = d / "index.json"
    if not p.exists():
        raise SystemExit(f"没有 {p}；先跑 codestrata scan {repo}")
    idx = json.loads(p.read_text(encoding="utf-8"))
    if idx.get("format") != _cut.INDEX_FORMAT:
        raise SystemExit(f"{p} 是旧版本的格式；重新跑一次 codestrata scan {repo}")
    sp = d / "symbols.json"
    if sp.exists():
        extra = json.loads(sp.read_text(encoding="utf-8"))
        idx["symbols"] = extra.get("symbols", {})
        idx["files"] = extra.get("files", {})
        idx["aux"] = extra.get("aux", {})
        idx["edge_sites"] = extra.get("edge_sites", {})
        idx["edge_uses"] = extra.get("edge_uses", {})
        idx["edge_dead"] = extra.get("edge_dead", {})
        idx["name_refs"] = extra.get("name_refs")    # 老的 symbols.json 没有：None（不显示接线点）
        idx["docs"] = extra.get("docs", {})
        idx["file_loc"] = extra.get("file_loc", {})
        idx["file_sha"] = extra.get("file_sha")      # 老的 symbols.json 没有：None
    return idx


def load_hot(repo: Path, idx: dict, ref: str | None) -> tuple[dict | None, dict | None]:
    """ref 是一个 run：完整的 run id，或 case 名（取它最新一次录完的），后面可以加 @阶段，
    只叠加那个阶段的调用（见 trace 的 PHASE 约定）。run 的存储和解析见 runs.py。"""
    if not ref:
        return None, None
    hot, meta = _runs.load(repo, idx, ref)
    print(f"[codestrata] hot 图用的 run：{meta['run_id']}" + (f" @{meta['phase']}" if meta["phase"] else ""),
          file=sys.stderr)
    return hot, meta
