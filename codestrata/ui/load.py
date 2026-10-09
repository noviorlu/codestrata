"""读索引、叠 run。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import align as _align
from .. import cut as _cut
from .. import lanes as _lanes
from .. import runs as _runs
from .. import seq as _seq


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
        idx["name_refs"] = extra.get("name_refs")    # 老的 symbols.json 没有：None（不显示接线点）
        idx["docs"] = extra.get("docs", {})
        idx["file_loc"] = extra.get("file_loc", {})
        idx["file_sha"] = extra.get("file_sha")      # 老的 symbols.json 没有：None
    gp = d / "graph.json"
    # graph 的 scan 记录（函数之间的调用），scan-trace alignment 和图上的边都靠它；格式 4 的索引都有
    idx["graph"] = json.loads(gp.read_text(encoding="utf-8")) if gp.exists() else {"callees": [], "calls": {}, "sites": {}}
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


def load_lane(repo: Path, idx: dict, ref: str, lane: str) -> dict:
    """分列里一列的叠加：和 load_hot 一样的 hot，只是次数只算这一列（这个进程里的这一类线程，或一个 GPU 流）在这一段里的
    调用（lanes.lane_counts，来自时序事件）。span 不记调用行：调用行按这一段（时间段是整个 run）所有线程记的比例摊开，
    lines_approx 为真。老 run 的时序事件只记了跨文件的调用，这种 run 上同一个文件里的调用这里没有。
    找不到 run 抛 SystemExit，没有时序事件、列 id 不对抛 LookupError，span 读不出来抛 OSError / ValueError"""
    run, rd, phase = _runs.resolve(repo, ref)
    win = _seq.parse_window(phase)
    base, names = _runs.load_counts(rd, None if win else phase, with_names=True)
    counts = _lanes.lane_counts(rd, run, phase, lane)
    pairs = counts.pop("gpu_pairs", None)
    if base.get("func_lines") is not None:
        counts["func_lines"] = _seq.spread_lines(counts["func_edges"], base["func_lines"])
    hot, _ = _runs.overlay(idx, counts, names, _runs.file_state(repo, idx, _runs.read_detail(rd)))
    if pairs:                                    # GPU 的列：每种 kernel 是谁发起的、各几次、各占多少 GPU 时间（多的在前）
        label, km = _align.node_labeler(idx), hot["keymap"] or (lambda k: k)
        for k, (n, us) in pairs.items():
            ka, _, kb = k.partition("|")
            x = hot["kernels"].get(label(km(kb)))
            if x is not None:
                x.setdefault("callers", []).append({"caller": label(km(ka)), "n": n, "gpu_us": us})
        for x in hot["kernels"].values():
            x.get("callers", []).sort(key=lambda c: (-c["gpu_us"], -c["n"], c["caller"]))
    hot["run"] = run["id"] + (f"@{phase}" if phase else "")
    hot["lane"] = lane
    hot["lines_approx"] = "func_lines" in counts
    return hot
