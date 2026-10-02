"""运行时按进程 · 线程分列（P0，用户 2026-10-01 定的展示）：叠了 run 之后，模块图按线程分成并排的几列。

一列（lane）是一个进程里的一类线程：名字归一之后（thread_group：`Thread-3 (save_loop)` → save_loop，线程池的
`ThreadPoolExecutor-3_0…_3` → `ThreadPoolExecutor-3`，`worker-0` → worker）同名的合成一列，记下合了几个（每步新开的 output-builder ×249）。
每列只有这条线程调到的节点（当前切面上的文件 / 目录）和它们之间的边；同一个节点在几列里各有一份。列之间的连线：
  - 共用同一个节点：几列里都有它（前端按节点 id 找，这里不单列）；
  - 谁起了谁（spawn）：线程是在哪一列的哪个节点里 Thread.start 的，子进程是在哪里 exec / fork 出来的（events 的 thread_from、spawns），
    连到被起的那一列的入口节点；
  - 谁把数据交给谁（handoff）：进程内的队列、跨进程的 ZMQ（events 的 handoffs），按 (起点列, 起点节点, 终点列, 终点节点, 通道) 合起来；
  - 谁回收了谁（join）：线程是在哪一列的哪个节点里被 join 等到结束的，子进程是在哪里被 waitpid 等到退出的（events 的
    thread_end、reaps），从被回收的那一列的入口节点连过去。
每一头都带着那一行代码（起线程、放 / 取、发 / 收、join 的那一行）。每列还有起止的摘要（start / stop）。
数据：时序事件的 span（seq.span_index / pid_rows；带 parent 的才准，老 run 也能出列，只是没有连线）+ 这次 run 的叠加 hot
（录制之后改过的文件走 hot["keymap"]、构造挪到类上走 hot["redirect"]、函数对和代码比的结果 hot["calls"]）。
时间都是微秒、相对 run 起点；只算选的阶段（时间段）里的调用（seq.calls_in）。
每列可以有自己的切面（cuts：在一列里展开 / 收起不动别的列），没给的列用共用的那个（open_）。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from . import align as _align
from . import cut as _cut
from . import seq as _seq


_TARGET = re.compile(r"^Thread-\d+ \((.+)\)$")
_NUMBERED = re.compile(r"^(.+?)[-_]\d+$")


def thread_group(name: str) -> str:
    """线程名归一（同一类的合成一列）：`Thread-3 (save_loop)` → save_loop；末尾的 -N / _N 去掉一段
    （worker-0 → worker，ThreadPoolExecutor-3_0 → ThreadPoolExecutor-3，Thread-12 → Thread）"""
    m = _TARGET.match(name)
    if m:
        return m.group(1)
    m = _NUMBERED.match(name)
    return m.group(1) if m else name


def build(idx: dict, rd: Path, run: dict, phase: str | None, hot: dict, open_, text=None,
          cuts: dict | None = None) -> dict:
    """{"phase", "window": [起, 止], "segs": [[起, 止]…]（阶段的各个时间片）, "scope", "lanes": [列], "links": [连线],
    "units": [各列调到的单元（排好序）]}。open_ 是共用的切面（None 是默认切面）；cuts 是 {列 id: 这一列自己的切面}——
    列里的节点、边、入口，连线在这一列的那一头，都落在这一列的切面上。列按进程启动的先后排，进程里主线程在前。
    列：{"id": "pid:线程名", "pid", "proc": 进程名, "thread": 归一之后的线程名, "names": 合进来的原名（最多 6 个）,
         "open": 这一列用的切面（规整过、排好序）, "u": 这一列调到的单元（units 的下标；和切面无关）,
         "n_threads", "first", "last", "entry": 入口节点,
         "nodes": {节点: {"n": 被调次数, "first", "handoff": 这一列里它只是交接的地方（这一段里这条线程没调到它）}},
         "edges": [{"a", "b", "n", "only": 其中代码里看不出的（约数）, "first", "last"}],
         "external": 只跑仓库外的代码、因为是交接的一头才有这一列（没有节点）,
         "idle": 跑过仓库代码、这一段里没有调用、因为是交接的一头才有这一列（只放交接的那个节点；起 / 收不算它）,
         "proc_main": 这一列代表整个子进程（fork / exec / waitpid 接在它上面：主线程，或者从非主线程 fork 的子进程里唯一的线程）,
         "start": {"n": 知道是谁起的线程数, "t": 最早起的时刻, "lane": 起它的列（这一段里没跑的线程也写，那一列不在 lanes 里）,
                   "daemon": 其中守护线程数, "out": 段外的是 before / after} 或 None（不知道谁起的：
                  程序的主线程、hook 装上之前起的）,
         "stop": {"joined": 被 join / waitpid 等到的个数, "t": 最晚那一次的时刻, "lane": 等它的列,
                  "exited": 自己跑完、没人等的个数, "running": 到录制结束还没跑完的个数（子进程是不知道有没有退出）} 或 None}
    连线：{"kind": "spawn" | "handoff" | "join", "via": thread / exec / fork / queue / asyncio / janus / zmq / join / wait,
           "from": {"lane", "node", "fn", "t", "line"}, "to": {…}, "n", "first", "last",
           "pairs": [{"a": 起点函数, "b": 终点函数, "la" / "lb": 那一头的行（0 不知道）, "ta" / "tb": 那一行的代码,
                      "xa" / "xb": 那一头经仓库外的代码, "da" / "db": 定义 {f, l, k}, "n", "first"}]
           （次数最多的 8 对）, "n_pairs"}
    ——同样两头（列和节点）、同一种的合成一条，n 是几次；from / to 的 t 是最早的一次，first / last 是首末时刻（join 是等到的时刻，
    其余是起点那头的）；fn 是那一头的函数（span 的被调方；放 / 取发生在仓库外的代码里时是那一刻这条线程栈底的仓库函数——
    线程名写着的 target，或者那一刻还没返回的深度 0 调用的调用方——ext 为真，认不出是 None），
    line 是那个函数里起线程、放 / 取、发 / 收、join 的那一行（录制之后文件改过的，跟着函数挪；被起 / 被回收的那一头是 0：
    那一头是线程的入口函数）。text(文件, 行) 给的话，pairs 里带上那一行的代码。
    "out"：整条连线的首末时刻都在这一段之外（before / after），起 / 收的线程在这一段里跑过、起 / 收本身在段外。
    还有 "truncated": [时序事件录到了上限的进程]。没有时序事件、没有这个阶段的时刻抛 LookupError"""
    ix = _seq.span_index(rd)
    segs, win, end = _seq.window_segments(run, rd, phase)
    lo, hi = segs[0][0], segs[-1][1]
    keys, threads = ix["keys"], ix["threads"]
    keymap, redirect = hot.get("keymap"), hot.get("redirect") or {}
    label = _labeler(idx)
    share = _only_share(hot, label)
    names = proc_names(rd)
    cuts = {lid: sorted(_cut.norm_open(idx, o)) for lid, o in (cuts or {}).items()}
    maps: dict = {}                              # 切面的键 → cut_map：这一次请求里每个不同的切面只建一次（不管 cut_map 的缓存怎么挤）
    lane_map: dict[str, tuple] = {}              # 列 → (切面的键, cut_map)
    node_cache: dict[tuple, tuple] = {}          # (切面的键, 键下标) → (节点,)
    fn_cache: dict[int, str | None] = {}

    def map_of(lid: str) -> tuple:
        """一列的切面：(切面的键, cut_map)。cuts 里没有这一列就是共用的切面"""
        hit = lane_map.get(lid)
        if hit is None:
            o = cuts.get(lid, open_)
            k = None if o is None else ",".join(sorted(o))
            if k not in maps:
                maps[k] = _seq.cut_map(idx, o)
            hit = lane_map[lid] = (k, maps[k])
        return hit

    def key_at(a: int) -> str:
        """键下标 → 现在的键（录制之后文件改过的，换成函数现在的行号）；越界是 ?"""
        ka = keys[a] if 0 <= a < len(keys) else "?"
        return keymap(ka) if keymap is not None else ka

    def fn_of(a: int) -> str | None:
        """键下标 → 函数级的节点（file#Qual），落不到函数上是 None"""
        if a not in fn_cache:
            ka = keys[a] if 0 <= a < len(keys) else "?"
            fn_cache[a] = label(keymap(ka) if keymap is not None else ka) if ka != "?" else None
        return fn_cache[a]

    def line_of(b: int, ln: int) -> int:
        """span 被调方（键下标 b）的函数里的第 ln 行 → 现在的行号：录制之后文件改过的，跟着函数整个挪；挪不了是 0"""
        if not ln or keymap is None or not 0 <= b < len(keys):
            return ln
        kb = keys[b]
        rel, _, old = kb.rpartition(":")
        if rel not in keymap.todo:
            return ln
        now = int(keymap(kb).rpartition(":")[2])
        return ln + now - int(old) if int(old) > 0 and now > 0 else 0

    def nodes_of(a: int, b: int, lid: str):
        """span 两端的键下标 → (调用方节点, 被调方节点（都落在 lid 这一列的切面上）, 被调方是不是定义时的执行,
        这对函数代码里看不出的比例, 调用方单元, 被调方单元)"""
        ka, kb = key_at(a), key_at(b)
        to = redirect.get(f"{ka}|{kb}")
        m = map_of(lid)[1]
        na = m.of(ka)[0]
        if to and to in m.syms:
            nb, defining, ub = m.file_node(m.syms[to]["f"]), False, m.files.get(m.syms[to]["f"])
        else:
            (nb, defining), ub = m.of(kb), m.unit(kb)
        return na, nb, defining, share(ka, kb), m.unit(ka), ub

    def node(a: int, lid: str) -> str | None:
        """键下标 → lid 这一列的切面上的节点"""
        ck, m = map_of(lid)
        hit = node_cache.get((ck, a))
        if hit is None:
            hit = node_cache[(ck, a)] = (m.of(key_at(a))[0],)
        return hit[0]

    def unit_of(a: int, lid: str) -> str | None:
        """键下标 → 它所在的单元（和切面无关；落不到 index 里是 None）"""
        return map_of(lid)[1].unit(key_at(a))

    lanes: dict[str, dict] = {}
    rows_of: dict[int, list] = {}
    tid_lane: dict[tuple, str] = {}
    # (pid, tid) → {调用方键下标: [最早开始, 最晚结束]}：深度 0 的调用的调用方是这条线程最底下的仓库函数，它至少在这段时间里在栈上
    # （不限这一段）。交接发生在仓库外的代码里（不在任何 span 里）时，按它认那一刻在跑的是哪个仓库函数
    held: dict[tuple, dict] = {}
    first_in: dict[tuple, int] = {}              # (pid, tid) → 这一段里第一次调用的时刻（入口在这一段之前就开始了的，按这一刻认入口）
    for pid in dict.fromkeys(c["pid"] for c in ix["chunks"]):
        rows = rows_of[pid] = _seq.pid_rows(rd, pid)
        tnames = threads.get(str(pid)) or {}
        for r in rows:
            got = None
            for i, (a, b) in enumerate(segs):
                got = _seq.calls_in(r[0], r[1], r[6], a, b, open_hi=not win and (i + 1 < len(segs) or b < end))
                if got:
                    break
            raw = tnames.get(str(r[2])) or f"线程 {r[2]}"
            tname = thread_group(raw)
            lid = f"{pid}:{tname}"
            tid_lane[(pid, r[2])] = lid
            if r[3] == 0:
                hk = held.setdefault((pid, r[2]), {}).setdefault(r[4], [r[0], r[0]])
                hk[0] = min(hk[0], r[0])
                hk[1] = max(hk[1], r[0] + r[1] if r[1] >= 0 else math.inf)
            if not got:
                continue
            n, first, last = got
            first_in[(pid, r[2])] = min(first_in.get((pid, r[2]), first), first)
            na, nb, defining, only, ua, ub = nodes_of(r[4], r[5], lid)
            if na is None or nb is None or defining:
                continue
            L = lanes.get(lid)
            if L is None:
                L = lanes[lid] = {"id": lid, "pid": pid, "proc": names.get(pid) or f"pid {pid}", "thread": tname,
                                  "names": set(), "tids": set(), "ran": set(), "first": first, "last": last, "entry": None,
                                  "entry_fn": None, "entry_t": None, "nodes": {}, "edges": {}, "u": set()}
            L["u"].update((ua, ub))
            L["tids"].add(r[2])
            L["ran"].add(r[2])
            L["names"].add(raw)
            L["first"], L["last"] = min(L["first"], first), max(L["last"], last)
            if r[3] == 0 and (L["entry_t"] is None or first < L["entry_t"]):
                L["entry"], L["entry_fn"], L["entry_t"] = na, fn_of(r[4]), first
            for x, cnt in ((na, 0), (nb, n)):
                v = L["nodes"].get(x)
                if v is None:
                    L["nodes"][x] = {"n": cnt, "first": first}
                else:
                    v["n"] += cnt
                    v["first"] = min(v["first"], first)
            if na != nb:
                e = L["edges"].get((na, nb))
                if e is None:
                    L["edges"][(na, nb)] = {"a": na, "b": nb, "n": n, "only": n * only, "first": first, "last": last}
                else:
                    e["n"] += n
                    e["only"] += n * only
                    e["first"], e["last"] = min(e["first"], first), max(e["last"], last)

    def root_at(pid: int, tid: int, t: int | None) -> int | None:
        """t 那一刻这条线程最底下的仓库函数（键下标）：正好一个对得上就是它，一个都没有或几个都对得上是 None"""
        if t is None:
            return None
        ks = [k for k, (a, b) in (held.get((pid, tid)) or {}).items() if a <= t <= b]
        return ks[0] if len(ks) == 1 else None

    # 阶段 / 时间段里，入口调用在这一段之前就开始了、一直没返回的线程：这一段里它没有深度 0 的调用，入口按那个还在跑的调用补上
    for L in lanes.values():
        if L["entry"] is not None:
            continue
        for tid in sorted(L["tids"]):
            k = root_at(L["pid"], tid, first_in.get((L["pid"], tid), lo))
            nd = node(k, L["id"]) if k is not None else None
            if nd is not None:
                L["entry"], L["entry_fn"] = nd, fn_of(k)
                L["nodes"].setdefault(nd, {"n": 0, "first": L["first"]})
                L["u"].add(unit_of(k, L["id"]))
                break

    def named_target(pid: int, tid: int) -> tuple[bool, int | None]:
        """线程名写着 target（Thread-3 (x)）时：(True, x 那个仓库函数的键下标；x 在仓库外就是 None)；没写是 (False, None)。
        x 在仓库里时它从线程起来到结束一直在栈底，这种线程任何时刻最底下的仓库函数都是它"""
        m = _TARGET.match((threads.get(str(pid)) or {}).get(str(tid)) or "")
        if not m:
            return False, None
        for k in held.get((pid, tid)) or {}:
            f = fn_of(k)
            if f and f.rsplit("#", 1)[-1].rsplit(".", 1)[-1] == m.group(1):
                return True, k
        return True, None

    def end_of(pid: int, tid: int, row: int, t: int | None, line: int = 0, create: bool = False) -> dict | None:
        """一条连线的一头：哪一列、哪个节点（span 的被调方；不在任何 span 里就是那一刻在跑的仓库函数）、哪一行。
        create（交接的两头）：这一段里没有列的线程也给它一列，交接链才不断——只跑仓库外代码的线程（vLLM 收发 ZMQ 的线程）
        是空的一列（external）；跑过仓库代码、只是这一段里没有调用的（交接按放 / 发的时刻算进来，取的那头还没开始调用）
        是 idle 的一列，放上交接的那个节点（标 handoff）。起 / 收只连这一段里跑过的线程（ran）：idle 的不算（这一段里它没有调用，
        卡在放 / 取里）；只跑仓库外代码的线程能看到的活动就是交接，它这一头的放 / 取在这一段里就算"""
        lid = tid_lane.get((pid, tid))
        raw = (threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"
        if lid is None:
            lid = tid_lane[(pid, tid)] = f"{pid}:{thread_group(raw)}"
        new = lid not in lanes
        if new:
            if not create or t is None:
                return None
            idle = (pid, tid) in held                # 这条线程跑过仓库代码（深度 0 的调用都记在 held 里）
            lanes[lid] = {"id": lid, "pid": pid, "proc": names.get(pid) or f"pid {pid}", "thread": lid.partition(":")[2],
                          "names": set(), "tids": set(), "ran": set(), "first": t, "last": t, "entry": None, "entry_fn": None,
                          "entry_t": None, "nodes": {}, "edges": {}, "u": set(), ("idle" if idle else "external"): True}
        L = lanes[lid]
        inw = t is not None and any(a <= t <= b for a, b in segs)
        # 交接的这一头不在这一段里的线程不算进这一列（列头的 ×N、原名、首末时刻），除非这一列就是为它建的
        if create and t is not None and tid not in L["ran"] and (inw or new):
            L["tids"].add(tid)
            L["names"].add(raw)
            L["first"], L["last"] = min(L["first"], t), max(L["last"], t)
            if inw and L.get("external"):
                L["ran"].add(tid)
        rows = rows_of.get(pid) or []
        r = rows[row] if 0 <= row < len(rows) else None
        if r is not None:
            k = r[5]
            nd, fn = node(k, lid) or lanes[lid]["entry"], fn_of(k)
        else:
            # 不在任何 span 里（放 / 取发生在仓库外的代码里，比如 vLLM 引擎循环取请求）：那一刻这条线程最底下在跑的仓库函数
            # （线程名写着的 target，或者 root_at）；没有在跑的（vLLM 自己的收发循环）就是仓库外的代码，接在列头上
            k = named_target(pid, tid)[1]
            if k is None:                            # target 在仓库外（asyncio.run 之类）：按那一刻还没返回的深度 0 调用认
                k = root_at(pid, tid, t)
            nd, fn = (node(k, lid), fn_of(k)) if k is not None else (None, None)
        if create and nd is not None and not L.get("external"):
            # 交接的那个节点这一列里没有（这条线程这一段里没调到它，交接却在这一段里）：放上去，连线接在节点上而不是列头上；
            # 标 handoff：它在这一列里只是交接的地方，不是调了谁
            L["nodes"].setdefault(nd, {"n": 0, "first": t if t is not None else L["first"], "handoff": True})
            L["u"].add(unit_of(k, lid))              # 落回入口节点的（k 落不到 index 里）是 None，出结果时去掉
        return {"lane": lid, "node": nd, "fn": fn, "ext": r is None,
                "t": t if t is not None else (r[0] if r else None), "line": line_of(r[5], line) if r else 0}

    def end_via(pid: int, tid: int, row: int, t: int | None, line: int) -> dict | None:
        """join 的那一头：等它的线程没有列（asyncio.run 收尾时起的 _do_shutdown 线程替它 join 线程池）的话，顺着「谁起了它」
        往上找到有列的那一处（起这条中间线程的那一行），via 记下经过的线程"""
        via = []
        for _ in range(4):
            e = end_of(pid, tid, row, t, line)
            if e:
                if via:
                    e["via"] = via
                return e
            x = (tfrom.get(str(pid)) or {}).get(str(tid))
            if not x:
                return None
            via.append(thread_group((threads.get(str(pid)) or {}).get(str(tid)) or f"线程 {tid}"))
            tid, row, line = x[0], x[1], (x[2] if len(x) > 2 else 0)
        return None

    agg: dict[tuple, dict] = {}                  # 同样两头、同一种的连线合起来：(起点列, 起点节点, 终点列, 终点节点, 种类, 通道)

    def link(kind: str, via: str, a: dict, b: dict, t: int | None = None) -> None:
        k = (a["lane"], a["node"], b["lane"], b["node"], kind, via)
        x = agg.get(k)
        if t is None:
            t = a["t"] if a["t"] is not None else b["t"]
        if x is None:
            x = agg[k] = {"kind": kind, "via": via, "from": a, "to": b, "n": 1, "first": t, "last": t, "pairs": {}}
        else:
            x["n"] += 1
            for end, new in (("from", a), ("to", b)):  # 时刻取最早的一次
                if new["t"] is not None and (x[end]["t"] is None or new["t"] < x[end]["t"]):
                    x[end] = new
            if t is not None:
                x["first"] = t if x["first"] is None else min(x["first"], t)
                x["last"] = t if x["last"] is None else max(x["last"], t)
        pr = x["pairs"].setdefault((a["fn"], a.get("line", 0), b["fn"], b.get("line", 0), a.get("ext", False), b.get("ext", False)),
                                   [0, t])
        pr[0] += 1
        if t is not None and (pr[1] is None or t < pr[1]):
            pr[1] = t

    # 先连交接：只跑仓库外代码的线程的列（external）是这时候建的，之后起它、回收它的连线才接得上
    for h in ix.get("handoffs") or []:
        t = h["from"][3] if h["from"][3] is not None else h["to"][3]   # 按放 / 发的时刻算在不在这一段里（用户 10-01 定），和连线上写的时刻一致
        if not any(x <= t <= y for x, y in segs):
            continue
        a, b = end_of(*h["from"][:4], line=_at(h["from"], 4), create=True), end_of(*h["to"][:4], line=_at(h["to"], 4), create=True)
        if a and b and a["lane"] != b["lane"]:
            link("handoff", h["via"], a, b)
    tfrom, tend = ix.get("thread_from") or {}, ix.get("thread_end") or {}
    starts: dict[str, list] = {}                 # 列 → [(起的时刻, 起它的列, 守护)]：每列的 start 摘要
    stops: dict[str, list] = {}                  # 列 → [(结束 / 等到的时刻, 等它的列 或 None, 状态)]：stop 摘要

    def ran_lane(lid: str | None) -> bool:
        return lid in lanes and bool(lanes[lid]["ran"])

    proc_main: set = set()                       # 代表整个子进程的列（fork / exec / waitpid 接在它上面）

    def main_of(pid: int) -> str | None:
        """子进程的主线程那一列；这一段里主线程没跑仓库代码就没有（不拿别的线程顶替：exec / waitpid 说的是整个进程）。
        从非主线程 fork 的子进程里没有 MainThread：唯一的那条线程沿用父进程里那条线程的名字（Python 把它当成主线程），
        号最小的就是它（fork 之后先有它，hook 起别的线程之前先记下当前线程）"""
        lid = f"{pid}:MainThread"
        if ran_lane(lid):
            return lid
        tn = threads.get(str(pid)) or {}
        if not tn or any(thread_group(x) == "MainThread" for x in tn.values()):
            return None
        t0 = min(tn, key=int)
        lid = tid_lane.get((pid, int(t0))) or f"{pid}:{thread_group(tn[t0])}"
        return lid if ran_lane(lid) else None

    ext_first: dict[tuple, float] = {}           # (pid, tid) → 最早一次在仓库外的代码里交接（不在任何 span 里）的时刻
    for h in ix.get("handoffs") or []:
        for sd in (h["from"], h["to"]):
            if sd[2] < 0 and sd[3] is not None:
                ext_first[(sd[0], sd[1])] = min(ext_first.get((sd[0], sd[1]), math.inf), sd[3])

    def target_of(pid: int, tid: int) -> int | None:
        """线程的入口函数（Thread 的 target）：这条线程最早的深度 0 调用的调用方。线程名写着 target（Thread-3 (x)）的按名字认，
        对不上就是仓库外的代码；名字里没写的，在那之前已经在仓库外的代码里交接过，入口就是仓库外的代码（vLLM 的收发线程）。返回 None"""
        named, k = named_target(pid, tid)
        if named:                                # 线程名写着 target：按名字认（target 里第一件事就是 q.get() 也认得出）
            return k
        hs = held.get((pid, tid)) or {}
        if not hs:
            return None
        k, (a, _) = min(hs.items(), key=lambda kv: kv[1][0])
        return None if ext_first.get((pid, tid), math.inf) < a else k

    def entry_end(e: dict | None, pid: int, tid: int) -> dict | None:
        """被起 / 被回收的那一头：这条线程的入口函数（target_of）；入口在仓库外的代码里就接在列头上"""
        if e is None:
            return None
        k = target_of(pid, tid)
        e["fn"], e["node"] = (fn_of(k), node(k, e["lane"]) or e["node"]) if k is not None else (None, None)
        return e

    for pid, by_tid in tfrom.items():
        for tid, x in by_tid.items():
            ftid, frow = x[0], x[1]
            fln, ft, dmn = (x[2], x[3], x[4]) if len(x) > 4 else (0, None, False)
            lid = tid_lane.get((int(pid), int(tid)))
            # 只算这一段里跑过的线程（用户 10-01：选了阶段时起 / 收只算这一段里跑过的线程，段外的时刻照写、标段前 / 段后）
            if lid not in lanes or int(tid) not in lanes[lid]["ran"]:
                continue
            a, b = end_of(int(pid), ftid, frow, ft, fln), entry_end(_lane_start(lanes, lid), int(pid), int(tid))
            # 起它的线程这一段里没跑（没有列）：摘要里照样写是哪条线程
            starts.setdefault(lid, []).append((ft, a["lane"] if a else tid_lane.get((int(pid), ftid)), dmn))
            if a and b and a["lane"] != b["lane"]:
                link("spawn", "thread", a, b)
    for pid, by_tid in tend.items():
        for tid, e in by_tid.items():
            lid = tid_lane.get((int(pid), int(tid)))
            if lid not in lanes or int(tid) not in lanes[lid]["ran"]:
                continue
            j = e.get("by")
            b = end_via(int(pid), j[0], j[1], j[3], j[2]) if j else None
            stops.setdefault(lid, []).append((j[3] if j else e.get("t"), b["lane"] if b else tid_lane.get((int(pid), j[0])) if j else None,
                                              "joined" if j else "exited" if e.get("t") is not None else "running"))
            a = entry_end(_lane_end(lanes, lid, e.get("t")), int(pid), int(tid))
            if a and b and a["lane"] != b["lane"]:
                link("join", "join", a, b, t=j[3])
    pstart: dict[int, int] = {}                  # 进程映像最早的起点：fork 出来的子进程就是在这一刻起的（B 行没有时刻）
    for p in ix.get("procs") or []:
        pstart[p["pid"]] = min(pstart.get(p["pid"], p["t0_us"]), p["t0_us"])
    for s in ix.get("spawns") or []:
        # fork 没有记时刻：用子进程映像的起点（不用调 fork 的那个 span 的开始——它可能早得多），连线和列头的「起」是同一刻
        tf = s.get("t_us", pstart.get(s["child"]))
        a = end_of(s["pid"], s["tid"], s["row"], tf, s.get("line", 0))
        main = main_of(s["child"])
        if main:
            proc_main.add(main)
        b = _lane_start(lanes, main)
        if b:
            starts.setdefault(main, []).append((tf, a["lane"] if a else tid_lane.get((s["pid"], s["tid"])), False))
        if a and b:
            link("spawn", s["how"], a, b, t=tf)
    reaped = set()
    for s in ix.get("reaps") or []:
        main = main_of(s["child"])
        if main is None or main in reaped:
            continue
        proc_main.add(main)
        reaped.add(main)
        b = end_of(s["pid"], s["tid"], s["row"], s["t_us"], s["line"])
        stops.setdefault(main, []).append((s["t_us"], b["lane"] if b else tid_lane.get((s["pid"], s["tid"])), "joined"))
        a = _lane_end(lanes, main, None)
        if a and b:
            link("join", "wait", a, b, t=s["t_us"])
    for lid in starts:                           # 知道是谁起的子进程、没看到谁等它退出：不知道
        if lid in proc_main and lid not in stops:
            stops[lid] = [(None, None, "running")]
    def out_of(t: int | None, late: bool) -> str | None:
        """t 在不在这一段里：在任何一个时间片里是 None；之前 / 之后是 before / after；落在阶段的两个时间片之间的，
        起算 before（之后的那一片里才跑）、收算 after（之前的那一片里跑过）"""
        if t is None or any(a <= t <= b for a, b in segs):
            return None
        return "before" if t < lo else "after" if t > hi else "after" if late else "before"

    links = list(agg.values())
    for x in links:                              # 整条都在段外（起 / 收的线程在这一段里跑过，起 / 收本身在段外）：画淡
        late = x["kind"] == "join"
        o1, o2 = out_of(x["first"], late), out_of(x["last"], late)
        x["out"] = o1 if o1 == o2 else None
    for x in links:
        prs = sorted(x["pairs"].items(), key=lambda kv: (-kv[1][0], kv[1][1] if kv[1][1] is not None else 0))
        x["n_pairs"] = len(prs)
        x["pairs"] = []
        for (fa, la, fb, lb, xa, xb), (n, f) in prs[:8]:
            da, db = _align.node_def(idx, fa) if fa else None, _align.node_def(idx, fb) if fb else None
            pr = {"a": fa, "b": fb, "la": la, "lb": lb, "xa": xa, "xb": xb, "n": n, "first": f, "da": da, "db": db}
            if text is not None:
                pr["ta"] = text(da["f"], la) if da and la else ""
                pr["tb"] = text(db["f"], lb) if db and lb else ""
            x["pairs"].append(pr)

    units = sorted({u for L in lanes.values() for u in L["u"] if u is not None})
    at = {u: i for i, u in enumerate(units)}
    out = []
    for L in lanes.values():
        L["open"] = sorted(_cut.norm_open(idx, cuts.get(L["id"], open_)))
        L["u"] = sorted(at[u] for u in L["u"] if u is not None)
        L["start"], L["stop"] = _start_sum(starts.get(L["id"])), _stop_sum(stops.get(L["id"]))
        for sm, late in ((L["start"], False), (L["stop"], True)):
            if sm is not None:
                sm["out"] = out_of(sm["t"], late)
        L["n_threads"] = len(L.pop("tids"))
        L.pop("ran")
        if L["id"] in proc_main:
            L["proc_main"] = True
        L["names"] = sorted(L["names"])[:6]
        L.pop("entry_t")
        L.pop("entry_fn")
        L["edges"] = sorted(L["edges"].values(), key=lambda e: e["first"])
        for e in L["edges"]:
            e["only"] = round(e["only"])
        out.append(L)
    # 进程按启动的先后（父进程在前；按第一次调用排的话，一开机就在轮询的进程会排到最前面），进程里按交接的顺序（_order）
    rank = _order(out, links, pstart)
    out.sort(key=lambda L: (pstart.get(L["pid"], L["first"]), L["pid"], rank[L["id"]]))
    links.sort(key=lambda x: (x["from"]["t"] if x["from"]["t"] is not None else 0))
    return {"phase": phase, "window": [lo, hi], "segs": [list(s) for s in segs], "scope": ix.get("scope") or "cross",
            "truncated": ix.get("truncated") or [],
            "lanes": out, "links": links, "units": units}


def _order(lanes: list, links: list, pstart: dict) -> dict:
    """进程里各列的先后（用户 2026-10-01 定：按交接的顺序）：从入口那一列顺着进程里的交接走——vLLM 的 stage 是
    收请求 → 主循环 → 输出线程；入口是第一个从别的进程收到交接的那一列，最早启动的进程（没有谁交给它）是主线程。
    没走到的放后面：主线程在前，其余按第一次活动。返回 {列: 名次}"""
    by_pid: dict[int, list] = {}
    for L in lanes:
        by_pid.setdefault(L["pid"], []).append(L)
    root = min(by_pid, key=lambda p: pstart.get(p, 0)) if by_pid else None
    hand = sorted((x for x in links if x["kind"] == "handoff"), key=lambda x: x["to"]["t"] or 0)
    pid_of = {L["id"]: L["pid"] for L in lanes}
    rank: dict[str, int] = {}
    for pid, ls in by_pid.items():
        main = next((L["id"] for L in ls if L["thread"] == "MainThread"), None)
        entry = main if pid == root else next(
            (x["to"]["lane"] for x in hand if pid_of.get(x["to"]["lane"]) == pid and pid_of.get(x["from"]["lane"]) != pid), main)
        seq: list[str] = []
        todo = [entry] if entry else []
        while todo:
            cur = todo.pop(0)
            if cur in seq:
                continue
            seq.append(cur)
            todo.extend(x["to"]["lane"] for x in hand if x["from"]["lane"] == cur and pid_of.get(x["to"]["lane"]) == pid)
        rest = sorted((L for L in ls if L["id"] not in seq), key=lambda L: (L["thread"] != "MainThread", L["first"]))
        for i, lid in enumerate(seq + [L["id"] for L in rest]):
            rank[lid] = i
    return rank


def _lane_start(lanes: dict, lid: str | None) -> dict | None:
    """被起的那一列的入口：线程的入口函数在哪个节点"""
    if lid is None or lid not in lanes:
        return None
    L = lanes[lid]
    return {"lane": lid, "node": L["entry"] or next(iter(L["nodes"]), None), "fn": L["entry_fn"], "t": L["first"], "line": 0}


def _lane_end(lanes: dict, lid: str | None, t: int | None) -> dict | None:
    """被回收的那一列的一头：线程从入口函数返回就结束了，所以也是入口节点；t 是它跑完的时刻"""
    a = _lane_start(lanes, lid)
    if a is not None:
        a["t"] = t
    return a


def _at(side: list, i: int) -> int:
    """handoffs 的一头 [pid, tid, row, t, line]：老的 run 没有 line"""
    return side[i] if len(side) > i else 0


def _start_sum(xs: list | None) -> dict | None:
    """一列里各线程是谁起的 → start 摘要（见 build）"""
    if not xs:
        return None
    ts = [x for x in xs if x[0] is not None]
    first = min(ts, key=lambda x: x[0]) if ts else xs[0]
    return {"n": len(xs), "t": first[0], "lane": first[1], "daemon": sum(1 for x in xs if x[2])}


def _stop_sum(xs: list | None) -> dict | None:
    """一列里各线程怎么结束的 → stop 摘要（见 build）：t / lane 取最晚被等到的那一次"""
    if not xs:
        return None
    jo = [x for x in xs if x[2] == "joined"]
    last = max(jo, key=lambda x: x[0] if x[0] is not None else -1) if jo else None
    return {"joined": len(jo), "t": last[0] if last else None, "lane": last[1] if last else None,
            "exited": sum(1 for x in xs if x[2] == "exited"), "running": sum(1 for x in xs if x[2] == "running")}


def _labeler(idx: dict):
    """键 rel:行 → graph 的函数级节点（file#Qual）"""
    syms = idx.get("symbols") or {}
    loc2sym, spans = _align.sym_locs(syms)
    return _align.node_labeler(idx, loc2sym, spans)


def _only_share(hot: dict, label):
    """(调用方键, 被调方键) → 这对函数的调用里代码里看不出的比例（hot["calls"] 按函数对算的，不分线程）"""
    calls = hot.get("calls") or {}
    memo: dict[tuple, float] = {}

    def share(ka: str, kb: str) -> float:
        k = (ka, kb)
        v = memo.get(k)
        if v is None:
            x = calls.get(f"{label(ka)}|{label(kb)}")
            v = memo[k] = (x["only"] / x["n"]) if x and x.get("n") else 0.0
        return v
    return share


def proc_names(rd: Path) -> dict[int, str]:
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
