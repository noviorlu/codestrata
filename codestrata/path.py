"""请求路径：一个阶段里，每个进程、每个线程按第一次调用的先后排出来的函数级调用树——「这次请求走了哪条路」。

span 带父 span 的 run（2026-10-01 起录的、或者 runs merge 重建过的）：调用上下文树（_contexts）。树上一个节点是从线程的根
到这里的一条调用链（同一条链上的多次调用合成一个节点），父亲就是调用那一刻真正在跑的那个；这一段之前就在跑的祖先
（引擎循环、请求处理的协程）照样列出来当上下文，标 before。下面 1–4 是老 run（没有父 span）的做法：

数据：时序事件（seq.phase_calls：每次调用，带时刻、进程、线程；老 run 只有跨文件的）+ 这次 run 的叠加（hot：函数对、调用行、和 scan 比的结果）。
  1. 每个（进程, 线程）里，trace 的键落到 graph 的节点上（align.node_labeler；录制之后改过的文件先走 hot["keymap"]）。
     定义时的执行（import 触发的模块顶层、类体）不算；整个挪到构造 F→C 上的（hot["redirect"]）算到类上。
  2. 一个函数挂在第一次调用它的那个调用方下面，同一个调用方下面按第一次被调用的先后排。
     找不到带时刻的调用方的是根：线程的入口、这一段之前就进去了的。
  3. 老 run（2026-10-01 之前录的）的时序事件只记了跨文件的调用，同一个文件里的调用没有时刻：根要是在 hot 里有同一个文件里的
     调用方、而它也在这棵树上，就挂到它下面，标 untimed（这一跳没有时刻，位置是按它自己第一次往外调的时刻排的）。
  4. 反复调用（seq.is_repeat：REPEAT_MIN 次以上、首末隔了这段时间的一半以上：轮询、每个 token 都走一遍）标 rep。
每一行带调用写在调用方的哪一行（hot 里这对函数次数最多的那一行）、代码里看不看得出（status、note，见 align.judge）。
"""
from __future__ import annotations

from pathlib import Path

from . import align as _align
from . import lanes as _lanes
from . import seq as _seq

MAX_ROWS = 4000          # 一张图（整个 run、不分阶段）上可能有上万行：页面只给前这么多行，命令行全打


def request_path(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, max_rows: int | None = MAX_ROWS) -> dict:
    """{"phase", "window": [起, 止], "span_us", "truncated": [pid], "rows_cut": 截掉的行数, "scope": "all" | "cross",
        "procs": [{"pid", "name", "first", "threads": [{"name", "n": 同名线程几个, "first", "rows": [行]}]}]}。
    行：{"d": 深度, "t": 第一次的时刻（微秒、相对 run 起点）, "fn": 节点, "def": {f, l}, "from": 调用方 或 null,
         "n": 这个线程里这对调用的次数（根、untimed 的是 null）, "rep": 反复调用, "untimed": 同一个文件里调过来的（没有时刻）,
         "line": {f, l, n, status, note} 或 null, "before": 这一段之前就在跑、这一段里没调过（调用上下文树里的祖先）}
    ——line 是 hot 里这对函数次数最多的调用行（不分进程；老 run 是按名字猜的，带 guessed）。max_rows：最多给几行（None 不截）。
    没有时序事件、没有这个阶段的时刻抛 LookupError"""
    pc = _seq.phase_calls(rd, run, phase)
    calls = hot.get("calls") or {}
    span = pc["span_us"] or 1
    trees = _contexts(idx, rd, run, phase, hot, calls, span) if pc["scope"] == "all" else None
    n_threads: dict[tuple, set] = {}             # 同名的线程（线程池里几百个 omni-async-output-builder）合成一个
    if trees is None:
        by: dict[tuple, dict] = {}               # (pid, 线程名) → {(F, G): [first, last, n]}
        for pid, tid, tname, f_, g, first, last, n in _labeled(idx, pc, hot):
            n_threads.setdefault((pid, tname), set()).add(tid)
            e = by.setdefault((pid, tname), {}).setdefault((f_, g), [first, last, 0])
            e[0], e[1], e[2] = min(e[0], first), max(e[1], last), e[2] + n
        trees = {k: _tree(edges, calls, idx, span, pc["scope"] != "all") for k, edges in by.items()}
    else:
        for (pid, tid, _, _) in pc["calls"]:
            tname = (pc["threads"].get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
            n_threads.setdefault((pid, tname), set()).add(tid)
    names = _lanes.proc_names(rd)
    procs: dict[int, dict] = {}
    for (pid, tname), rows in trees.items():
        if not rows or all(r.get("before") for r in rows):
            continue
        p = procs.setdefault(pid, {"pid": pid, "name": names.get(pid) or f"pid {pid}", "threads": []})
        p["threads"].append({"name": tname, "n": len(n_threads.get((pid, tname)) or ()) or 1,
                             "first": min(r["t"] for r in rows if not r.get("before")), "rows": rows})
    out = []
    for p in procs.values():
        # 主线程排在前面（请求从它进来），其余线程按第一次调用的先后
        p["threads"].sort(key=lambda th: (th["name"] != "MainThread", th["first"]))
        p["first"] = p["threads"][0]["first"]
        out.append(p)
    out.sort(key=lambda p: p["first"])
    cut, left = 0, max_rows if max_rows is not None else float("inf")
    for p in out:
        for th in p["threads"]:
            if len(th["rows"]) > left:
                cut += len(th["rows"]) - left
                th["rows"] = th["rows"][:int(left)]
            left -= len(th["rows"])
    return {"phase": phase, "window": pc["window"], "span_us": pc["span_us"], "truncated": pc["truncated"],
            "rows_cut": cut, "scope": pc["scope"], "procs": out}


def first_calls(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, lane: str | None = None) -> dict[str, int]:
    """{"F|G": 这一段里第一次调用的时刻}（不分进程、线程；给了 lane 就只算分列里这一列）：边详情按先后排函数对用。没有时序事件抛 LookupError"""
    out: dict[str, int] = {}
    keep = _lanes.in_lane(lane) if lane else None
    for pid, _, tname, f_, g, first, _, _ in _labeled(idx, _seq.phase_calls(rd, run, phase), hot):
        if keep is not None and not keep(pid, tname):
            continue
        k = f"{f_}|{g}"
        if k not in out or first < out[k]:
            out[k] = first
    return out


def _pair_labeler(idx: dict, hot: dict):
    """(调用方键, 被调方键) → (调用方节点, 被调方节点)：落到 graph 的节点上。录制之后改过的文件先走 keymap；整个挪到构造 F→C 上的
    算到类上；被调方是定义时的执行（import 触发的模块顶层、类体）、case 自己的代码的是 (调用方, None)；调用方是 case 的代码是 None"""
    syms = idx.get("symbols") or {}
    loc2sym, spans = _align.sym_locs(syms)
    label = _align.node_labeler(idx, loc2sym, spans)
    keymap, redirect = hot.get("keymap"), hot.get("redirect") or {}

    def pair(ka: str, kb: str):
        if keymap is not None:
            ka, kb = keymap(ka), keymap(kb)
        if ka.rpartition(":")[0][:1] == "<":
            return None
        to = redirect.get(f"{ka}|{kb}")
        rel, _, ln = kb.rpartition(":")
        if to is None and (rel[:1] == "<" or _align.defining(syms, loc2sym, rel, int(ln) if ln.lstrip("-").isdigit() else 0)):
            return label(ka), None
        return label(ka), to or label(kb)
    return pair


def _labeled(idx: dict, pc: dict, hot: dict):
    """seq.phase_calls 的每一项落到 graph 的节点上：(pid, tid, 线程名, 调用方, 被调方, first, last, n)（见 _pair_labeler；
    被调方落不上的不要）"""
    pair = _pair_labeler(idx, hot)
    keys, threads = pc["keys"], pc["threads"]
    for (pid, tid, a, b), (first, last, n, _) in pc["calls"].items():
        if not (0 <= a < len(keys) and 0 <= b < len(keys)):
            continue
        fg = pair(keys[a], keys[b])
        if fg is None or fg[1] is None:
            continue
        tname = (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
        yield pid, tid, tname, fg[0], fg[1], first, last, n


def _contexts(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, calls: dict, span: int) -> dict | None:
    """span 带父 span 的 run：{(pid, 线程名): 行}（行的样子见 request_path）。没有父 span（老格式）是 None。
    一个节点是从线程的根（第一个 span 的调用方）到这里的一条调用链；被调方落不到节点上的 span（定义时的执行这类）透明：
    它下面的调用挂到它的父亲那条链上"""
    ix = _seq.span_index(rd)
    segs, win, end = _seq.window_segments(run, rd, phase)
    keys, threads = ix["keys"], ix["threads"]
    pair = _pair_labeler(idx, hot)
    memo: dict[tuple, tuple | None] = {}
    nodes: dict[tuple, dict] = {}                # (pid, 线程名) → {链: [这一段里第一次, 最后一次, 次数, 任何时候最早的开始]}
    for pid in dict.fromkeys(c["pid"] for c in ix["chunks"]):
        rows = _seq.pid_rows(rd, pid)
        if rows and len(rows[0]) < 9:
            return None
        tn = threads.get(str(pid)) or {}
        chain: list = [None] * len(rows)
        for i, r in enumerate(rows):
            k = (r[4], r[5])
            fg = memo.get(k, ())
            if fg == ():
                fg = memo[k] = pair(keys[r[4]], keys[r[5]]) if 0 <= r[4] < len(keys) and 0 <= r[5] < len(keys) else None
            if fg is None:
                continue
            base = chain[r[8]] if r[8] >= 0 else (fg[0],)
            if base is None:
                continue
            c = chain[i] = base + (fg[1],) if fg[1] is not None else base
            tname = tn.get(str(r[2])) or f"线程 {r[2]}"
            nd = nodes.setdefault((pid, tname), {})
            for j in range(1, len(c) + 1):        # 链上的每一层都要有（之前就在跑的祖先当上下文）
                x = nd.get(c[:j])
                if x is None:
                    nd[c[:j]] = [None, None, 0, r[0]]
                elif r[0] < x[3]:
                    x[3] = r[0]
            if fg[1] is None:
                continue
            for a, b in segs:
                got = _seq.calls_in(r[0], r[1], r[6], a, b, open_hi=not win and b < end)
                if got:
                    x = nd[c]
                    x[0] = got[1] if x[0] is None else min(x[0], got[1])
                    x[1] = got[2] if x[1] is None else max(x[1], got[2])
                    x[2] += got[0]
    out = {}
    for key, nd in nodes.items():
        kids: dict[tuple, list] = {}
        for c in nd:
            kids.setdefault(c[:-1], []).append(c)
        when = lambda c: nd[c][0] if nd[c][0] is not None else nd[c][3]   # noqa: E731
        rows_out: list[dict] = []

        def walk(c: tuple) -> None:
            first, last, n, _ = nd[c]
            via = c[-2] if len(c) > 1 else None
            row = {"d": len(c) - 1, "t": when(c), "fn": c[-1], "def": _align.node_def(idx, c[-1]), "from": via,
                   "n": n or None, "rep": bool(n and _seq.is_repeat(n, first, last, span)), "untimed": False,
                   "before": first is None, "line": _line(calls, via, c[-1]) if via else None}
            if row["line"]:
                row["line"]["f"] = _align.node_def(idx, via)["f"]
            rows_out.append(row)
            for k in sorted(kids.get(c, ()), key=when):
                walk(k)
        for root in sorted(kids.get((), ()), key=when):
            walk(root)
        # 这一段里一次都没调过的子树不要（祖先只在它下面有这一段里的调用时才留着当上下文）
        up, stack = [-1] * len(rows_out), []      # 每行的父亲（先序排的：深度少一的最近一行）
        for i, r in enumerate(rows_out):
            del stack[r["d"]:]
            up[i] = stack[-1] if stack else -1
            stack.append(i)
        keep = [False] * len(rows_out)
        for i in range(len(rows_out) - 1, -1, -1):
            if not rows_out[i]["before"] or keep[i]:
                keep[i] = True
                if up[i] >= 0:
                    keep[up[i]] = True
        out[key] = [r for r, k in zip(rows_out, keep) if k]
    return out


def _tree(edges: dict, calls: dict, idx: dict, span: int, fill_same_file: bool) -> list[dict]:
    """一个线程里的调用 {(F, G): [first, last, n]} → 按先后排好的行（见 request_path）。fill_same_file：
    时序事件只记了跨文件的调用（老 run），同一个文件里调过来的按 hot 补上（第 3 条）"""
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
    for r in [x for x in seen if x not in parent] if fill_same_file else ():
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
    def walk(node: str, d: int, via: str | None) -> None:
        done.add(node)
        e = edges.get((via, node)) if via else None
        row = {"d": d, "t": seen[node], "fn": node, "def": _align.node_def(idx, node), "from": via,
               "n": e[2] if e and node not in untimed else None,
               "rep": bool(e and _seq.is_repeat(e[2], e[0], e[1], span)),
               "untimed": node in untimed, "line": _line(calls, via, node) if via else None}
        if row["line"]:
            row["line"]["f"] = _align.node_def(idx, via)["f"]
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


def _line(calls: dict, f_: str, g: str) -> dict | None:
    x = calls.get(f"{f_}|{g}")
    if not x:
        return None
    if x.get("lines"):
        y = max(x["lines"], key=lambda z: z["n"])
        return {"l": y["l"], "n": y["n"], "status": y["status"], "note": y["note"]}
    g0 = (x.get("guessed") or [None])[0]
    return {"l": g0, "n": None, "status": x.get("status"), "note": x.get("note"), "guessed": True} if g0 else None


def format_text(path: dict, max_depth: int | None = None) -> str:
    """命令行打印：一个线程一节，缩进是调用的层次；+秒数是相对这一段开头的第一次调用"""
    t0 = path["window"][0]
    out = [f"请求路径{'（阶段 ' + path['phase'] + '）' if path['phase'] else ''}："
           f"{t0 / 1e6:.2f}–{path['window'][1] / 1e6:.2f} s。↻ 是反复调用，[看不出] 是代码里看不出会调到它"
           + ("；这个 run 的时序事件只记了跨文件的调用，（同文件）是同一个文件里调过来的、没有时刻" if path.get("scope") != "all" else "")]
    for p in path["procs"]:
        for th in p["threads"]:
            out.append(f"\n== {p['name']}（pid {p['pid']}）· {th['name']}" + (f"（{th['n']} 个线程）" if th["n"] > 1 else ""))
            for r in th["rows"]:
                if max_depth is not None and r["d"] > max_depth:
                    continue
                ln = r["line"]
                where = f"  ← {Path(ln['f']).name}:{ln['l']}" if ln and ln.get("l") else ""
                tags = ("  ↻" if r["rep"] else "") + ("  （同文件）" if r["untimed"] else "") \
                    + ("  [GPU]" if ln and (ln.get("note") or {}).get("k") == "gpu" else
                       "  [看不出]" if ln and ln.get("status") == "trace" else "")
                n = f"  ×{r['n']}" if r["n"] else ""
                when = "（之前）" if r.get("before") else f"+{(r['t'] - t0) / 1e6:.3f}s"
                out.append(f"{'  ' * r['d']}{when}  {_short(r['fn'])}{n}{tags}{where}")
    if path["rows_cut"]:
        out.append(f"\n（还有 {path['rows_cut']} 行没列出）")
    if path["truncated"]:
        out.append(f"⚠ 进程 {', '.join(map(str, path['truncated']))} 的时序事件录到了上限，之后的调用不在这里")
    return "\n".join(out)


def _short(node: str | None) -> str:
    """节点的短名字：限定名；模块顶层的带上文件名（光写 <module> 认不出是哪个文件）"""
    f, _, q = (node or "").partition("#")
    if q.startswith("<module>"):
        return f"{Path(f).name}:{q}"
    return q or f
