"""时序事件：hook 记下的原始事件日志 → 配好对的 span（模块图「时间顺序」的数据，见 seq.py）。

录制（trace 的 hook，CODESTRATA_EVENTS=1 时）记每一次调用，口径和 func_edges 相同（递归自调用不算）。
2026-10-01 之前只记**跨文件**的调用：日志里没有 M 行的就是这种，index.json 的 scope 是 "cross"。
每个进程映像一份文本日志 ev-<pid>-<t0ns>.log，一行一个事件：

    H <pid> <t0_ns> <ppid>              文件头
    M all                               同文件的调用也记了（没有这一行：只记了跨文件的）
    N <tid> <线程名>                     线程登记：进程内的小整数 → 线程名
    K <id> <rel:firstlineno>            键登记：进程内的小整数 → 函数
    C <t_us> <tid> <span> <调用方> <被调方>   调用（t_us 相对这个进程映像的 t0）
    R <t_us> <tid> <span>               返回，或异常展开
    Y <t_us> <tid> <span>               挂起（生成器 / 协程 yield、await）
    S <t_us> <tid> <span>               恢复
    T                                   达到行数上限，之后不再记（计数不受影响）

span 号在进程内唯一；返回、挂起、恢复是 hook 按帧（id(帧)）找回的 span 号，不靠栈的顺序，
所以同一线程里交错执行的 asyncio 协程也配得对。

这里把它整理成 span（派生数据，finalize 和 `runs merge` 都会重做；原始日志打包在
events/raw.tar.gz 里永久保留）：

    [t0_us, dur_us, tid, depth, a, b, rep, n_susp, parent]

  - t0_us 相对整个 run 的起点（run.json 的 clock.mono0_ns）；dur_us 是墙钟时间，挂起过的
    （async）包含挂起的时间；进程结束时还没返回的是 -1。
  - depth：调用那一刻这个线程上正在执行（没返回、也没挂起）的 span 数。
  - a / b：调用方 / 被调方在 keys.json 里的下标。
  - rep：第一级折叠——同一个父 span 下、中间没有挂起 / 恢复、同一对 a→b、自己没有（记下的）子调用的
    连续同步兄弟合成一条，rep 是合了几次；dur 从第一次开始算到最后一次结束。
  - a / b 为 keys.json 里的 "?"：这个键的登记行丢了（日志被截断），不会静默指到别的函数上。
  - n_susp：挂起了几次（>0 就是 async 的 span）。
  - parent：父 span 在这个进程的 span 里的下标（按 t0 排好、跨块连着数），没有是 -1。父 span 是调用那一刻这个线程上
    最里层正在执行的 span（挂起的不算）：async 的也准——协程恢复之后调的，父亲是它自己，不是时间上包住它的别的协程。
    老的 span（2026-10-01 之前整理的）没有这一列，`runs merge` 从原始日志重建就有了。

写出 events/spans/：keys.json {keys, threads}、index.json {chunks, truncated, scope, ...}、
p<pid>-NNN.jsonl.gz（按 t0 排好，每块最多 10 万行）。
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
from pathlib import Path

CHUNK = 100_000


def parse(path: Path) -> dict:
    """读一个 ev 日志：{pid, t0, ppid, keys: {id: key}, threads: {tid: 名}, ev: [(tag, t, tid, span, a, b)],
    truncated}。坏行（进程被强杀时最后一行可能只写了一半）跳过。"""
    out = {"pid": None, "t0": None, "ppid": None, "keys": {}, "threads": {}, "ev": [], "truncated": False,
           "scope": "cross"}
    name = path.name                              # ev-<pid>-<t0>.log：没有 H 行时从文件名取
    try:
        pid_s, t0_s = name[len("ev-"):-len(".log")].split("-")[:2]
        out["pid"], out["t0"] = int(pid_s), int(t0_s)
    except ValueError:
        pass
    ev = out["ev"]
    # 只按 \n 分行（名字里的 \r 不能把一行劈开）；没有换行结尾的最后一行是写到一半被杀的，
    # 字段可能正好够数、值却是截断的，整行不要
    with open(path, encoding="utf-8", errors="replace", newline="\n") as f:
        for ln in f:
            if not ln.endswith("\n"):
                continue
            p = ln.split(" ", 5) if ln[:1] in "CRYS" else None
            try:
                if p is not None:
                    if p[0] == "C":
                        ev.append(("C", int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5])))
                    else:
                        ev.append((p[0], int(p[1]), int(p[2]), int(p[3]), 0, 0))
                elif ln.startswith("K "):
                    _, i, k = ln.rstrip("\n").split(" ", 2)
                    out["keys"][int(i)] = k
                elif ln.startswith("N "):
                    _, i, nm = ln.rstrip("\n").split(" ", 2)
                    out["threads"][int(i)] = nm
                elif ln.startswith("H "):
                    _, pid, t0, ppid = ln.split()
                    out["pid"], out["t0"], out["ppid"] = int(pid), int(t0), int(ppid)
                elif ln.startswith("T"):
                    out["truncated"] = True
                elif ln == "M all\n":
                    out["scope"] = "all"
            except (ValueError, IndexError):
                continue
    return out


def pair(log: dict) -> list[list]:
    """一个进程映像的事件 → span（还没折叠）：[t0, t1, tid, depth, a, b, n_susp, n_children, 父 span, 段, span 号]，
    t0 / t1 相对这个进程映像的 t0（微秒），a / b 是进程内的键号；没返回的 t1 = None。
    「段」：这个线程上每发生一次挂起或恢复加一——fold 只合同一个父 span 下、同一段里的兄弟。
    落盘重试可能把一批行写两遍：重复的调用、已经挂起的再挂起、已经在跑的再恢复，都不算。"""
    spans: dict[int, list] = {}
    active: dict[int, list[int]] = {}             # tid → 正在执行的 span（按进入顺序）
    where: dict[int, int] = {}                    # span → 它现在挂在哪个线程的 active 上（挂起时没有）
    epoch: dict[int, int] = {}
    order: list[int] = []
    for tag, t, tid, sp, a, b in log["ev"]:
        if tag == "C":
            if sp in spans:                       # 重复的调用行（落盘重试写了两遍）：只认第一次
                continue
            st = active.setdefault(tid, [])
            parent = st[-1] if st else 0          # 父 span：这个线程上最里层正在执行的那个
            if parent and parent in spans:
                spans[parent][7] += 1
            spans[sp] = [t, None, tid, len(st), a, b, 0, 0, parent, epoch.get(tid, 0), sp]
            order.append(sp)
            st.append(sp)
            where[sp] = tid
            continue
        s = spans.get(sp)
        if s is None:
            continue                              # 没有对应的调用行（日志坏了一段）
        if tag == "Y" and sp not in where:        # 已经挂起了又来一个挂起：重复行
            continue
        if tag == "S" and sp in where:            # 已经在跑又来一个恢复：重复行
            continue
        if tag in ("R", "Y"):
            st = active.get(where.pop(sp, tid), [])
            if sp in st:                          # 通常就在栈顶；交错时从中间拿掉
                st.remove(sp)
            if tag == "R":
                if s[1] is None:
                    s[1] = t
            else:
                s[6] += 1
                epoch[tid] = epoch.get(tid, 0) + 1
        elif tag == "S":
            active.setdefault(tid, []).append(sp)
            where[sp] = tid
            epoch[tid] = epoch.get(tid, 0) + 1
    return [spans[sp] for sp in order]


def fold(spans: list[list]) -> list[list]:
    """第一级折叠。输入按 t0 排好的同一个线程的 span（pair 的输出）；
    输出 [t0, t1, tid, depth, a, b, rep, n_susp, 父 span 号, span 号]（合起来的那一行用第一次的号：叶子没有孩子，
    不会被谁当父亲）。只合同一个父 span 下紧挨着的同步叶子（没挂起过、没有记下的子调用）：它们之间夹着的只能是
    没记下的工作（递归自调用、老 run 里同文件的调用、仓库外的代码）。按父 span 认「兄弟」而不按深度——同一线程上交错执行的两个协程，各自的
    子调用深度相同，但不是兄弟；还要在同一「段」里（中间这个线程上没有挂起 / 恢复），否则
    合出来的时间窗会盖住别的协程在这期间的调用。"""
    out: list[list] = []
    cand: dict[tuple, int | None] = {}            # (父 span, 段) → 这个父亲最近的一个孩子（out 里的下标）
    for t0, t1, tid, depth, a, b, n_susp, n_child, parent, ep, sp in spans:
        key = (parent, ep)
        leaf = n_susp == 0 and n_child == 0 and t1 is not None
        c = cand.get(key)
        if leaf and c is not None and out[c][4] == a and out[c][5] == b:
            out[c][6] += 1
            out[c][1] = t1
            continue
        out.append([t0, t1, tid, depth, a, b, 1, n_susp, parent, sp])
        cand[key] = len(out) - 1 if leaf else None
    return out


def build(files: list[Path], mono0_ns: int | None, out_dir: Path) -> dict:
    """把一个 run 的所有 ev 日志整理成 span，写进 out_dir（先写到旁边的临时目录，再整个换上）。
    返回 index（也写进 out_dir/index.json）。"""
    keys: list[str] = []
    kidx: dict[str, int] = {}
    threads: dict[str, dict] = {}
    procs: list[dict] = []
    per_pid: dict[int, list] = {}
    truncated: set[int] = set()
    scopes: set[str] = set()
    n_lines = 0
    tid_base: dict[int, int] = {}                 # 同一个 pid 的多个映像（exec 前后）线程号接着编
    for path in sorted(files, key=lambda p: p.name):
        log = parse(path)
        img = path.name                           # 同一个 pid 的几个映像（exec 前后）span 号各自从 1 数
        scopes.add(log["scope"])
        n_lines += len(log["ev"])
        if log["truncated"]:
            truncated.add(log["pid"])
        base = 0 if mono0_ns is None or log["t0"] is None else (log["t0"] - mono0_ns) // 1000
        remap = {}
        for i, k in log["keys"].items():
            if k not in kidx:
                kidx[k] = len(keys)
                keys.append(k)
            remap[i] = kidx[k]
        off = tid_base.get(log["pid"], 0)
        tid_base[log["pid"]] = off + max(log["threads"], default=0)
        threads.setdefault(str(log["pid"]), {}).update({str(t + off): n for t, n in log["threads"].items()})
        raw = pair(log)
        by_tid: dict[int, list] = {}
        for s in raw:
            by_tid.setdefault(s[2], []).append(s)
        rows = []
        for tid, ss in by_tid.items():
            for t0, t1, tid_, depth, a, b, rep, n_susp, parent, sp in fold(sorted(ss, key=lambda s: s[0])):
                ra, rb = remap.get(a), remap.get(b)
                if ra is None or rb is None:           # 键的登记行丢了：指到 "?"，不用 -1（keys[-1] 会静默取到最后一个）
                    if "?" not in kidx:
                        kidx["?"] = len(keys)
                        keys.append("?")
                    ra = kidx["?"] if ra is None else ra
                    rb = kidx["?"] if rb is None else rb
                rows.append([base + t0, -1 if t1 is None else t1 - t0, tid_ + off, depth, ra, rb, rep, n_susp,
                             (img, parent) if parent else None, (img, sp)])
        per_pid.setdefault(log["pid"], []).extend(rows)
        procs.append({"pid": log["pid"], "ppid": log["ppid"], "t0_us": base, "n_events": len(log["ev"]),
                      "n_spans": len(rows), "truncated": log["truncated"]})
    tmp = out_dir.with_name(out_dir.name + f".{os.getpid()}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    chunks = []
    n_spans = n_calls = 0
    for pid, rows in sorted(per_pid.items(), key=lambda kv: kv[0] or 0):
        rows.sort(key=lambda r: (r[0], r[3]))
        at = {r[9]: i for i, r in enumerate(rows)}      # (映像, span 号) → 排好之后的下标
        for r in rows:
            r[8] = at.get(r[8], -1)                     # 父亲被截断在上限之后（没有调用行）的也是 -1
            del r[9]
        for ci in range(0, max(len(rows), 1), CHUNK):
            part = rows[ci:ci + CHUNK]
            if not part:
                break
            name = f"p{pid}-{ci // CHUNK:03d}.jsonl.gz"
            data = "\n".join(json.dumps(r, separators=(",", ":")) for r in part) + "\n"
            (tmp / name).write_bytes(gzip.compress(data.encode(), mtime=0))
            chunks.append({"pid": pid, "chunk": name, "t0_us": part[0][0],
                           "t1_us": max(r[0] + max(r[1], 0) for r in part), "n": len(part)})
        n_spans += len(rows)
        n_calls += sum(r[6] for r in rows)
    index = {"pairing": "frame", "scope": "all" if scopes == {"all"} else "mixed" if "all" in scopes else "cross",
             "chunks": chunks, "procs": procs, "truncated": sorted(p for p in truncated if p),
             "n_lines": n_lines, "n_spans": n_spans, "n_calls": n_calls}
    (tmp / "keys.json").write_text(json.dumps({"keys": keys, "threads": threads}, ensure_ascii=False),
                                   encoding="utf-8")
    (tmp / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    old = out_dir.with_name(out_dir.name + f".{os.getpid()}.old")
    if out_dir.exists():
        os.replace(out_dir, old)
    os.replace(tmp, out_dir)
    shutil.rmtree(old, ignore_errors=True)
    return index


def read_spans(spans_dir: Path, pid: int | None = None) -> list[list]:
    """读回 span（测试用）；pid 为 None 时读全部。"""
    idx = json.loads((spans_dir / "index.json").read_text(encoding="utf-8"))
    out = []
    for c in idx["chunks"]:
        if pid is not None and c["pid"] != pid:
            continue
        for ln in gzip.decompress((spans_dir / c["chunk"]).read_bytes()).decode().splitlines():
            if ln:
                out.append(json.loads(ln))
    return out
