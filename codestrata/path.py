"""请求路径：一个阶段里，每个进程、每个线程按第一次调用的先后排出来的函数级调用树——「这次请求走了哪条路」。

数据：时序事件（seq.phase_calls：跨文件的调用，带时刻、进程、线程）+ 这次 run 的叠加（hot：函数对、调用行、和 scan 比的结果）。
  1. 每个（进程, 线程）里，trace 的键落到 graph 的节点上（align.node_labeler；录制之后改过的文件先走 hot["keymap"]）。
     定义时的执行（import 触发的模块顶层、类体）不算；整个挪到构造 F→C 上的（hot["redirect"]）算到类上。
  2. 一个函数挂在第一次调用它的那个调用方下面，同一个调用方下面按第一次被调用的先后排。
     找不到带时刻的调用方的是根：线程的入口、经仓库外的代码调进来的（vllm 的引擎循环调 scheduler）、同一个文件里调过来的。
  3. 同一个文件里的调用没有时刻（时序事件只记跨文件的）：根要是在 hot 里有同一个文件里的调用方、而它也在这棵树上，
     就挂到它下面，标 untimed（这一跳没有时刻，位置是按它自己第一次往外调的时刻排的）。
  4. 反复调用（seq.REPEAT_MIN 次以上、首末隔了这段时间的一半以上：轮询、每个 token 都走一遍）标 rep。
每一行带调用写在调用方的哪一行（hot 里这对函数次数最多的那一行）、代码里看不看得出（status、note，见 align.judge）。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import align as _align
from . import seq as _seq

MAX_ROWS = 4000          # 一张图（整个 run、不分阶段）上可能有上万行：页面只给前这么多行，命令行全打


def request_path(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict) -> dict:
    """{"phase", "window": [起, 止], "span_us", "truncated": [pid], "rows_cut": 截掉的行数,
        "procs": [{"pid", "name", "first", "threads": [{"name", "n": 同名线程几个, "first", "rows": [行]}]}]}。
    行：{"d": 深度, "t": 第一次的时刻（微秒、相对 run 起点）, "fn": 节点, "def": {f, l}, "from": 调用方 或 null,
         "n": 这个线程里这对调用的次数（根、untimed 的是 null）, "rep": 反复调用, "untimed": 同一个文件里调过来的（没有时刻）,
         "line": {f, l, n, status, note} 或 null}——line 是 hot 里这对函数次数最多的调用行（不分进程；老 run 是按名字猜的，带 guessed）。
    没有时序事件、没有这个阶段的时刻抛 LookupError"""
    pc = _seq.phase_calls(rd, run, phase)
    calls = hot.get("calls") or {}
    by: dict[tuple, dict] = {}                   # (pid, 线程名) → {(F, G): [first, last, n]}
    n_threads: dict[tuple, set] = {}             # 同名的线程（线程池里几百个 omni-async-output-builder）合成一个
    for pid, tid, tname, f_, g, first, last, n in _labeled(idx, pc, hot):
        n_threads.setdefault((pid, tname), set()).add(tid)
        e = by.setdefault((pid, tname), {}).setdefault((f_, g), [first, last, 0])
        e[0], e[1], e[2] = min(e[0], first), max(e[1], last), e[2] + n
    names = _proc_names(rd)
    span = pc["span_us"] or 1
    procs: dict[int, dict] = {}
    for (pid, tname), edges in by.items():
        rows = _tree(edges, calls, idx, span)
        if not rows:
            continue
        p = procs.setdefault(pid, {"pid": pid, "name": names.get(pid) or f"pid {pid}", "threads": []})
        p["threads"].append({"name": tname, "n": len(n_threads[(pid, tname)]), "first": min(r["t"] for r in rows),
                             "rows": rows})
    out = []
    for p in procs.values():
        # 主线程排在前面（请求从它进来），其余线程按第一次调用的先后
        p["threads"].sort(key=lambda th: (th["name"] != "MainThread", th["first"]))
        p["first"] = p["threads"][0]["first"]
        out.append(p)
    out.sort(key=lambda p: p["first"])
    cut, left = 0, MAX_ROWS
    for p in out:
        for th in p["threads"]:
            if len(th["rows"]) > left:
                cut += len(th["rows"]) - left
                th["rows"] = th["rows"][:left]
            left -= len(th["rows"])
    return {"phase": phase, "window": pc["window"], "span_us": pc["span_us"], "truncated": pc["truncated"],
            "rows_cut": cut, "procs": out}


def first_calls(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict) -> dict[str, int]:
    """{"F|G": 这一段里第一次调用的时刻}（不分进程、线程）：边详情按先后排函数对用。没有时序事件抛 LookupError"""
    out: dict[str, int] = {}
    for _, _, _, f_, g, first, _, _ in _labeled(idx, _seq.phase_calls(rd, run, phase), hot):
        k = f"{f_}|{g}"
        if k not in out or first < out[k]:
            out[k] = first
    return out


def _labeled(idx: dict, pc: dict, hot: dict):
    """seq.phase_calls 的每一项落到 graph 的节点上：(pid, tid, 线程名, 调用方, 被调方, first, last, n)。
    录制之后改过的文件先走 keymap；整个挪到构造 F→C 上的算到类上；定义时的执行、case 自己的代码（调用方或被调方）不算"""
    syms = idx.get("symbols") or {}
    loc2sym, spans = _align.sym_locs(syms)
    label = _align.node_labeler(idx, loc2sym, spans)
    keymap, redirect = hot.get("keymap"), hot.get("redirect") or {}
    keys, threads = pc["keys"], pc["threads"]
    for (pid, tid, a, b), (first, last, n) in pc["calls"].items():
        if not (0 <= a < len(keys) and 0 <= b < len(keys)):
            continue
        ka, kb = keys[a], keys[b]
        if keymap is not None:
            ka, kb = keymap(ka), keymap(kb)
        to = redirect.get(f"{ka}|{kb}")
        rel, _, ln = kb.rpartition(":")
        if to is None and (rel[:1] == "<" or _align.defining(syms, loc2sym, rel, int(ln) if ln.lstrip("-").isdigit() else 0)):
            continue
        if ka.rpartition(":")[0][:1] == "<":
            continue
        tname = (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
        yield pid, tid, tname, label(ka), to or label(kb), first, last, n


def _tree(edges: dict, calls: dict, idx: dict, span: int) -> list[dict]:
    """一个线程里的调用 {(F, G): [first, last, n]} → 按先后排好的行（见 request_path）"""
    first_in: dict[str, tuple] = {}              # G → (第一次被调的时刻, 那次的调用方)
    seen: dict[str, int] = {}                     # 节点 → 在这个线程里第一次出现（被调或往外调）的时刻
    for (f_, g), (t, _, _) in edges.items():
        if f_ != g and (g not in first_in or t < first_in[g][0]):
            first_in[g] = (t, f_)
        seen[g] = min(seen.get(g, t), t)
        seen[f_] = min(seen.get(f_, t), t)
    parent = {g: fc for g, (_, fc) in first_in.items()}
    untimed: set[str] = set()
    # 同一个文件里调过来的根：挂到同文件的调用方下面（这一跳没有时刻）
    for r in [x for x in seen if x not in parent]:
        file_r = _file(r)
        cands = [c for c in seen if c != r and _file(c) == file_r and f"{c}|{r}" in calls and not _below(c, r, parent)]
        if cands:
            parent[r] = min(cands, key=lambda c: seen[c])
            untimed.add(r)
    kids: dict[str, list] = {}
    for g, f_ in parent.items():
        kids.setdefault(f_, []).append(g)
    rows: list[dict] = []
    done: set[str] = set()
    repeat = _seq.REPEAT_MIN

    def walk(node: str, d: int, via: str | None) -> None:
        done.add(node)
        e = edges.get((via, node)) if via else None
        row = {"d": d, "t": seen[node], "fn": node, "def": _def(idx, node), "from": via,
               "n": e[2] if e and node not in untimed else None,
               "rep": bool(e and e[2] >= repeat and e[1] - e[0] > span / 2),
               "untimed": node in untimed, "line": _line(calls, via, node) if via else None}
        if row["line"]:
            row["line"]["f"] = _def(idx, via)["f"]
        rows.append(row)
        for k in sorted(kids.get(node, ()), key=lambda x: seen[x]):
            if k not in done:
                walk(k, d + 1, node)
    for r in sorted((x for x in seen if x not in parent), key=lambda x: seen[x]):
        walk(r, 0, None)
    # 互相调用成环、没有根的：从环上最早出现的那个开始
    for x in sorted((x for x in seen if x not in done), key=lambda x: seen[x]):
        if x not in done:
            walk(x, 0, None)
    return rows


def _below(c: str, r: str, parent: dict) -> bool:
    """c 是不是 r 的子孙（挂上去会成环）"""
    hops = 0
    while c in parent and hops < 10000:
        c = parent[c]
        if c == r:
            return True
        hops += 1
    return False


def _file(node: str) -> str:
    return node.partition("#")[0]


def _def(idx: dict, node: str) -> dict:
    s = (idx.get("symbols") or {}).get(_align.base_node(node))
    f = s["f"] if s else _file(node)
    rest = node.partition(".<L")[2]
    return {"f": f, "l": int(rest.rstrip(">")) if rest else (s["l"] if s else 1)}


def _line(calls: dict, f_: str, g: str) -> dict | None:
    x = calls.get(f"{f_}|{g}")
    if not x:
        return None
    if x.get("lines"):
        y = max(x["lines"], key=lambda z: z["n"])
        return {"l": y["l"], "n": y["n"], "status": y["status"], "note": y["note"]}
    g0 = (x.get("guessed") or [None])[0]
    return {"l": g0, "n": None, "status": x.get("status"), "note": x.get("note"), "guessed": True} if g0 else None


def _proc_names(rd: Path) -> dict[int, str]:
    """进程的名字：改过的进程标题（vLLM 的 VLLM::StageEngineCoreProc_stage0_…），没有就用命令里的脚本名"""
    try:
        procs = json.loads((rd / "detail.json").read_text(encoding="utf-8")).get("procs") or []
    except (OSError, ValueError):
        return {}
    out = {}
    for p in procs:
        title = (p.get("title") or "").removeprefix("VLLM::")
        argv = p.get("argv") or []
        script = next((Path(a).name for a in argv[1:] if a.endswith(".py")), None)
        mod = argv[argv.index("-m") + 1] if "-m" in argv[:-1] else None
        out[p["pid"]] = title or script or (f"-m {mod}" if mod else Path(argv[0]).name if argv else "")
    return out


def format_text(path: dict, max_depth: int | None = None) -> str:
    """命令行打印：一个线程一节，缩进是调用的层次；+秒数是相对这一段开头的第一次调用"""
    t0 = path["window"][0]
    out = [f"请求路径{'（阶段 ' + path['phase'] + '）' if path['phase'] else ''}："
           f"{t0 / 1e6:.2f}–{path['window'][1] / 1e6:.2f} s。只有跨文件的调用有时刻，↻ 是反复调用，"
           "（同文件）是同一个文件里调过来的、没有时刻，[看不出] 是代码里看不出会调到它"]
    for p in path["procs"]:
        for th in p["threads"]:
            out.append(f"\n== {p['name']}（pid {p['pid']}）· {th['name']}" + (f"（{th['n']} 个线程）" if th["n"] > 1 else ""))
            for r in th["rows"]:
                if max_depth is not None and r["d"] > max_depth:
                    continue
                ln = r["line"]
                where = f"  ← {Path(ln['f']).name}:{ln['l']}" if ln and ln.get("l") else ""
                tags = ("  ↻" if r["rep"] else "") + ("  （同文件）" if r["untimed"] else "") \
                    + ("  [看不出]" if ln and ln.get("status") == "trace" else "")
                n = f"  ×{r['n']}" if r["n"] else ""
                out.append(f"{'  ' * r['d']}+{(r['t'] - t0) / 1e6:.3f}s  {_short(r['fn'])}{n}{tags}{where}")
    if path["rows_cut"]:
        out.append(f"\n（还有 {path['rows_cut']} 行没列出）")
    if path["truncated"]:
        out.append(f"⚠ 进程 {', '.join(map(str, path['truncated']))} 的时序事件录到了上限，之后的调用不在这里")
    return "\n".join(out)


def _short(node: str | None) -> str:
    return (node or "").partition("#")[2] or (node or "")
