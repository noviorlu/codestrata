"""点开一条边：两端底下函数之间的调用（给 /api/edge）。两边怎么对上由 align 定，这里只取数、配上源码那一行。"""
from __future__ import annotations

import re
from pathlib import Path

from .. import align as _align
from .. import cut as _cut
from .. import graph as _graph
from . import source as _source

MAX_ITEMS = 60


def _sig(repo: Path, d: dict | None) -> list[str] | None:
    """被调函数的签名（def 那一行到冒号为止，最多 6 行），多行的压成一行"""
    if not d or d.get("k") not in ("func", "class"):
        return None
    ls = _source.lines_of(str(repo / d["f"]), (repo / d["f"]).stat().st_mtime_ns) if (repo / d["f"]).exists() else ()
    if not 0 < d["l"] <= len(ls):
        return None
    out = []
    for t in ls[d["l"] - 1:d["l"] + 5]:
        out.append(t.rstrip())
        if t.split("#", 1)[0].rstrip().endswith(":"):
            break
    if len(out) == 1:
        return [out[0].strip()[:200]]
    one = re.sub(r"\(\s+", "(", re.sub(r",?\s*\)", ")", " ".join(t.strip() for t in out)))
    closed = out[-1].split("#", 1)[0].rstrip().endswith(":")
    return [one[:200] + ("" if closed else " …")]


def edge_detail(repo: Path, idx: dict, a: str, b: str, hot: dict | None = None) -> dict:
    """点开一条边：a、b 可以是目录、本层文件或单个文件节点。两端底下函数之间的调用：
      calls      这次 trace 到的函数对 [{caller, callee, caller_def, def, sig, n, only, status, lines, guessed, note, wiring}]：
                 n 次数、only 其中代码里看不出的次数；status：both（两边都有）/ trace（只有 trace）/ mixed（有的行对得上、有的对不上）；
                 lines 是 trace 记的调用行 [{f, l, n, status, note, s}]（note 见 align.judge）；老 run 没有调用行：lines 是 null，
                 guessed 是在调用方里按名字找到的 [{f, l, s}]，note 是整个函数对的；wiring 见 align.wiring（只给有只有 trace 的）
      scan_only  代码里写了、这次没录到的 [{caller, callee, caller_def, def, sig, lines: [{f, l, s, k}], n_lines, unseen}]
                 （k 是 graph.py 的种类）；unseen：只是构造一个构造时不跑仓库里代码的类，跑没跑 trace 都看不到
    两种都按次数 / 调用处多的在前，各最多 MAX_ITEMS 条（counts 里是全部的）。
    lines_approx：时间段的次数没有调用行，每行的次数是按整个 run 的调用行摊的（seq.window_counts）"""
    A, B = set(_cut.units_of(idx, a)), set(_cut.units_of(idx, b))
    unit = {}

    def u(key):
        if key not in unit:
            unit[key] = _align.node_unit(idx, key)
        return unit[key]

    def text(f: str, l: int) -> str:
        return _source.line_text(repo, f, l).strip()[:200]

    calls, ran = [], set()
    for pk, x in ((hot or {}).get("calls") or {}).items():
        if x["a"] not in A or x["b"] not in B:
            continue
        caller, _, callee = pk.partition("|")
        cd, d = _source.node_def(idx, caller), _source.node_def(idx, callee)
        it = {"caller": caller, "callee": callee, "caller_def": cd, "def": d, "sig": _sig(repo, d),
              "n": x["n"], "only": x["only"],
              "status": "trace" if x["only"] >= x["n"] else "both" if not x["only"] else "mixed",
              "lines": None, "guessed": None, "note": x.get("note")}
        if x["lines"] is not None:
            it["lines"] = [{**ln, "f": cd["f"], "s": text(cd["f"], ln["l"]) if ln["l"] else ""} for ln in x["lines"]]
        else:
            it["guessed"] = [{"f": cd["f"], "l": l, "s": text(cd["f"], l)} for l in x["guessed"] or []]
        if x["only"]:
            w = _align.wiring(idx, callee)
            if w:
                it["wiring"] = {**w, "refs": [{**r, "s": text(r["f"], r["l"])} for r in w["refs"]]}
        calls.append(it)
        ran.add(pk)
    # scan 记录：两端在这两个节点底下、定下了被调方的调用
    g = idx.get("graph") or {}
    C = g.get("callees") or []
    scan: dict[str, list] = {}
    for caller, xs in (g.get("calls") or {}).items():
        if u(caller) not in A:
            continue
        for i, l, e, k in xs:
            if u(C[i]) in B:
                scan.setdefault(f"{caller}|{C[i]}", []).append((l, e, k))
    ctors = g.get("ctors") or {}
    scan_only = []
    for pk, sl in scan.items():
        if pk in ran:
            continue
        caller, _, callee = pk.partition("|")
        cd, d = _source.node_def(idx, caller), _source.node_def(idx, callee)
        scan_only.append({"caller": caller, "callee": callee, "caller_def": cd, "def": d, "sig": _sig(repo, d),
                          "lines": [{"f": cd["f"], "l": l, "k": k, "s": text(cd["f"], l)} for l, _, k in sl[:5]],
                          "n_lines": len(sl),
                          # 构造一个构造时不跑仓库里代码的类（dataclass 生成的 __init__、仓库外基类的）：trace 看不到
                          "unseen": all(k == _graph.NEW for _, _, k in sl) and ctors.get(callee) == []})
    order = {"trace": 0, "mixed": 1, "both": 2}
    calls.sort(key=lambda x: (order[x["status"]], -x["n"], x["callee"]))
    scan_only.sort(key=lambda x: (x["unseen"], -x["n_lines"], x["callee"]))
    return {"a": a, "b": b, "has_runtime": bool(hot), "lines_approx": bool((hot or {}).get("lines_approx")),
            "calls": calls[:MAX_ITEMS], "scan_only": scan_only[:MAX_ITEMS],
            "counts": {"calls": sum(x["n"] for x in calls), "only": sum(x["only"] for x in calls),
                       "pairs": len(calls), "scan_only": len(scan_only)}}
