"""链（links --follow）：顺着交接从一处一跳一跳走到别的列，每一跳写明是录到的还是推出来的、按什么推的。

起点（Walker.start）：
    `列#k`     这一列主循环的第 k 轮（轮号和 steps 一样：轮头在 REF 所在的阶段上认，整个 run 上数）；
    `FN#k`     这段时间里第 k 次调用 FN（从 1 数；REF 带了列时只数这几列）；`列:FN#k` 只数这一列的。
在一列里走的是「这一份」：
    数据在 t 进到这一列（起点：那一轮 / 那次调用开始；之后：收到的那一刻），到同一路的下一份进来为止（起点：这一轮结束 / 这一列下一次
    调用 FN；录到的交接：同一组的下一次收到；--link：B 边的下一次调用）。这期间：
      1. 有 --link 的 A 边是这一列：A 函数这期间第一次调用（正包着 t 的那次也算）是这一列的第 j 次 → 跳到 B 列 B 函数的第 j 次
         （agent 明说了走这条；这期间正好也有录到的交出到 B 列的，记下 recorded_too）；
      2. 否则这一列这期间第一次交出（录到的交接）→ 跟过去；
      3. 都没有就停下。
    跳本身：录到的是 recorded，--link 配的是 order。在一列里从进来到交出（stay）：交出发生在起点那次调用 / --link 落到的那次调用里面、
    或者 A 函数那次调用包着收到的那一处的是 ancestor；其余是 time（进来之后、下一份进来之前的第一次）。time 接的那一组交出的次数正好和
    进来的份数一样、按先后配（第 k 份配第 k 次）却是另一次时，写在 alt 里（不改走法）。
--link 'A列:FN => B列:FN'（用户 10-10 定：没录到的跳要 agent 显式给）：这段时间里 A 边第 k 次调用配 B 边第 k 次。两边次数不等、
    或者有一次 B 早于同一次的 A，就拒绝（link_mismatch），候选是 B 列里配得上的函数。
停下（stop.reason）：
    none   这期间没交出、也没有能用的 --link：写这一列下一次交出（时刻、通道、到哪列；inferred: time，不往下走）和 --link 的候选；
    range  收到的那一刻已经出了这段时间；
    hops   走了 MAX_HOPS 跳。
--link 的候选：A 边是这一列这期间跑的函数（和进来的那一路一样多次的是 per_item：一份一次）；B 边是同一个进程里（不够再别的进程）
    接下来先干活的几列各自先跑的函数（空转、在等的轮里的和常规的不算）。和挑出来的 A 函数次数一样、每次都不早于它的标 fits，
    最早的一个拼成能直接用的 --link。
走出来的链是一个段（kind chain）：每一列待的那段时间（几片，相隔不到 MERGE_US 的合起来）× 经过的列；最后一列取收到之后 TAIL_US。
纯计算：输入是 segments.analyse 的结果（span、列、轮）和 lanes.build 的 ends（每次交接两头的函数：和页面、links 同一个认法）。
"""
from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass

from . import funcref as _funcref
from . import laneid as _laneid
from . import linkgroups as _linkgroups
from .errors import CodestrataError

ALGO = "chain/1"
MAX_HOPS = 40
TAIL_US = 1000
MERGE_US = 1000
CAND_LANES = 3
CAND_FNS = 6


@dataclass
class Fn:
    """一列上一个函数这段时间里的每一次调用 [(开始, 结束, pid, span 下标)]，按开始排"""
    lane: str
    node: str
    calls: list


@dataclass
class Link:
    text: str
    a: Fn
    b: Fn


@dataclass
class Pos:
    """数据在一列里：t 进来，until 之前（同一路的下一份进来）；这是这一路这段时间里 n 份里的第 k 份。
    call：起点那次调用 / --link 落到的那次（pid, span 下标）；at：收到的那一处（pid, span 下标）；fn：进来的那一头的函数"""
    lane: str
    t: int
    until: int
    n: int
    k: int
    call: tuple | None = None
    at: tuple | None = None
    fn: str | None = None


def parse_link(text: str) -> tuple[str, str, str, str]:
    """'A列:FN => B列:FN' → (A列, A 函数, B列, B 函数)"""
    a, sep, b = text.partition("=>")
    out = []
    for side in (a, b):
        ln, colon, fn = side.strip().partition(":")
        if not sep or not colon or not ln.strip() or not fn.strip():
            raise CodestrataError("usage", "--link 写成 'A列:函数 => B列:函数'（比如 'stage2/recv_loop:Adapter.commit => "
                                           f"stage2/MainThread:Runner.run'）：{text!r}")
        out += [ln.strip(), fn.strip()]
    return out[0], out[1], out[2], out[3]


def misfit(xs: list, ys: list) -> tuple | None:
    """按先后一一配（第 k 次 x 配第 k 次 y）配不上的地方：("count", x 几次, y 几次)、("order", k, x 的时刻, y 的时刻)；配得上是 None"""
    if len(xs) != len(ys):
        return ("count", len(xs), len(ys))
    for k, (x, y) in enumerate(zip(xs, ys), 1):
        if y[0] < x[0]:
            return ("order", k, x[0], y[0])
    return None


def merge(stays: list[tuple[int, int]], lo: int, hi: int) -> list[list[int]]:
    """几段停留 → 时间片（截在 [lo, hi] 里；相隔不到 MERGE_US 的合起来；每片至少 1 µs）"""
    out: list[list[int]] = []
    for a, b in sorted((max(a, lo), min(max(a, b), hi)) for a, b in stays):
        if b < a:
            continue
        b = max(b, a + 1)
        if out and a <= out[-1][1] + MERGE_US:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _spread(r: list, pid: int, i: int) -> list[tuple]:
    """一行 span 的每一次调用 (开始, 结束, pid, 下标)：合成一行的连续调用（rep 次）按次数摊在这一行的时长上"""
    end = r[0] + max(r[1], 0)
    if r[6] <= 1:
        return [(r[0], end, pid, i)]
    step = max(r[1], 0) / (r[6] - 1)
    return [(r[0] + round(k * step), r[0] + round(k * step), pid, i) for k in range(r[6] - 1)] + [(end, end, pid, i)]


def _first(calls: list, t: int, end: int) -> int | None:
    """calls 里正包着 t 的那次，或者 [t, end) 里开始的第一次（下标）"""
    i = bisect.bisect_right(calls, (t, float("inf")))
    if i > 0 and calls[i - 1][0] <= t <= calls[i - 1][1]:
        return i - 1
    return i if i < len(calls) and calls[i][0] < end else None


class Walker:
    """一个 run 的一段时间 [lo, hi]：A 是 segments.analyse 的结果，ends 是 lanes.build 填的 {交接下标: (起点那头, 终点那头)}"""

    def __init__(self, A: dict, ends: dict, label, lo: int, hi: int):
        self.A, self.ends, self.label, self.lo, self.hi = A, ends, label, lo, hi
        self.keys = A["ix"]["keys"]
        self.aliases = A["aliases"]
        self.hs = A["ix"].get("handoffs") or []
        tl = A["tid_lane"]
        self.side: dict[int, tuple] = {}             # 交接下标 → (起列, 终列)
        self.out: dict[str, list] = {}               # 列 → [(交出的时刻, 交接下标)]（整个 run）
        self.arr: dict[tuple, list] = {}             # (通道, 起列, 终列) → [收到的时刻]（交出在这段时间里的）
        self.dep: dict[tuple, list] = {}             # (通道, 起列, 终列) → [(交出的时刻, 交接下标)]（交出在这段时间里的）
        for hx, h in enumerate(self.hs):
            fl, tl_ = tl.get((h["from"][0], h["from"][1])), tl.get((h["to"][0], h["to"][1]))
            if fl is None or tl_ is None or fl == tl_ or h["from"][3] is None or h["to"][3] is None:
                continue
            self.side[hx] = (fl, tl_)
            self.out.setdefault(fl, []).append((h["from"][3], hx))
            if lo <= h["from"][3] <= hi:
                self.arr.setdefault((h["via"], fl, tl_), []).append(h["to"][3])
                self.dep.setdefault((h["via"], fl, tl_), []).append((h["from"][3], hx))
        for v in (*self.out.values(), *self.arr.values(), *self.dep.values()):
            v.sort()
        self._by_key: dict[str, dict] = {}           # 列 → {键下标: 这段时间里的每一次调用}
        self._counts: dict[str, Counter] = {}
        self._starts: dict[str, list] = {}           # 列 → 这一列 span 的开始时刻（和 lr 一一对应）
        self._rstarts: dict[str, list] = {}          # 列 → 各轮的开始时刻
        self._nodes: dict[int, str | None] = {}

    # ------------------------------------------------------------ 列、函数

    def alias(self, lid: str) -> str:
        return self.aliases.get(lid, lid)

    def node_of(self, b: int) -> str | None:
        """键下标 → 函数的节点；落不到函数上（? 、模块顶层）是 None"""
        if b not in self._nodes:
            k = self.keys[b] if 0 <= b < len(self.keys) else "?"
            nd = self.label(k) if k != "?" and not k.endswith(":0") else None
            self._nodes[b] = nd if nd and "#<module>" not in nd else None
        return self._nodes[b]

    def by_key(self, lid: str) -> dict:
        hit = self._by_key.get(lid)
        if hit is None:
            ln = self.A["lanes"][lid]
            hit = self._by_key[lid] = {}
            for i, r in ln["lr"]:
                if self.lo <= r[0] < self.hi:
                    hit.setdefault(r[5], []).extend(_spread(r, ln["pid"], i))
        return hit

    def counts(self, lid: str) -> Counter:
        """这一列这段时间里每个被调方（键下标）调了几次"""
        hit = self._counts.get(lid)
        if hit is None:
            hit = self._counts[lid] = Counter({b: len(cs) for b, cs in self.by_key(lid).items()})
        return hit

    def calls(self, lid: str, ks) -> list:
        """这一列这段时间里调 ks（一个函数的几个键）的每一次，按开始排"""
        bk = self.by_key(lid)
        return sorted(c for b in ks for c in bk.get(b, ()))

    def keys_of(self, lid: str, node: str) -> set[int]:
        return {b for b in self.by_key(lid) if self.node_of(b) == node}

    def one_lane(self, sel: str) -> str:
        """一个列选择器 → 正好一列（有 Python 调用的列）"""
        lids = _laneid.select([sel], self.aliases)
        if len(lids) != 1:
            raise CodestrataError("ambiguous_lane", f"{sel!r} 对上了 {len(lids)} 列，这里要正好一列",
                                  candidates=[self.alias(x) for x in lids][:20])
        if lids[0] not in self.A["lanes"]:
            raise CodestrataError("lane_not_found", f"{sel!r} 这一列没有线程（GPU 的列没有交接）")
        return lids[0]

    def fn(self, lid: str, text: str) -> Fn:
        """一列上的一个函数（同名的先挑这一列调过的）"""
        node, ks = _funcref.resolve(text, self.keys, self.label, self.counts(lid))
        cs = self.calls(lid, ks)
        if not cs:
            top = [n for b, _ in self.counts(lid).most_common(30) if (n := self.node_of(b))]
            raise CodestrataError("item_not_found", f"{self.alias(lid)} 这段时间里没调过 {node}",
                                  candidates=[f"{self.alias(lid)}:{self.fn_text(lid, n)}" for n in dict.fromkeys(top)][:12])
        return Fn(lid, node, cs)

    def fn_text(self, lid: str, node: str) -> str:
        """命令行上写这个函数：限定名在这一列认得出它就写限定名，否则写全路径#限定名"""
        q = node.partition("#")[2]
        try:
            if q and _funcref.resolve(q, self.keys, self.label, self.counts(lid))[0] == node:
                return q
        except CodestrataError:
            pass
        return node

    def _inside(self, pid: int, row: int, call: tuple | None) -> bool:
        """(pid, row) 这个 span 是不是 call 那次调用本身或者它里面的"""
        if call is None or call[0] != pid or row is None or row < 0:
            return False
        rows = self.A["rows"].get(pid) or []
        for _ in range(256):
            if row == call[1]:
                return True
            r = rows[row] if 0 <= row < len(rows) else None
            if r is None or r[8] < 0:
                return False
            row = r[8]
        return False

    # ------------------------------------------------------------ 起点、--link

    def link(self, text: str) -> Link:
        sa, fa, sb, fb = parse_link(text)
        la, lb = self.one_lane(sa), self.one_lane(sb)
        if la == lb:
            raise CodestrataError("usage", f"--link 的两头是同一列（{self.alias(la)}）：同一列里从进来到交出是自动接的，"
                                           "--link 接的是两列之间没录到的那一跳")
        a, b = self.fn(la, fa), self.fn(lb, fb)
        bad = misfit(a.calls, b.calls)
        if bad:
            fits = self.fitting(lb, a.calls)
            raise CodestrataError("link_mismatch", f"--link {text!r} 配不上：{self._misfit_text(a, b, bad)}；"
                                                   "按先后一一配要两边次数一样、每一次 B 都不早于同一次的 A"
                                  + ("。B 列里配得上的函数在候选里" if fits else "。B 列里没有配得上的函数"),
                                  candidates=[f"{self.alias(lb)}:{self.fn_text(lb, n)}" for n in fits][:12])
        return Link(text, a, b)

    def _misfit_text(self, a: Fn, b: Fn, bad: tuple) -> str:
        sa, sb = f"{self.alias(a.lane)} 的 {a.node.partition('#')[2]}", f"{self.alias(b.lane)} 的 {b.node.partition('#')[2]}"
        if bad[0] == "count":
            return f"两边次数不等（A 边 {sa} 这段时间 {bad[1]} 次，B 边 {sb} {bad[2]} 次）"
        return f"第 {bad[1]} 次 B（{sb}，t={bad[3]}）早于第 {bad[1]} 次 A（{sa}，t={bad[2]}）"

    def fitting(self, lid: str, xs: list) -> list[str]:
        """lid 这一列里和 xs 一样多次、每一次都不早于同一次 xs 的函数（节点），按第一次的先后"""
        by: dict[str, set] = {}
        for b, cs in self.by_key(lid).items():
            nd = self.node_of(b)
            if nd:
                by.setdefault(nd, set()).add(b)
        out = []
        for nd, ks in by.items():
            if sum(len(self.by_key(lid)[b]) for b in ks) != len(xs):
                continue
            ys = self.calls(lid, ks)
            if misfit(xs, ys) is None:
                out.append((ys[0][0], nd))
        return [nd for _, nd in sorted(out)]

    def start(self, text: str, lanes: list[str] | None) -> tuple[Pos, dict]:
        """起点 → (Pos, 起点的说明)。lanes：REF 带的列选择器（FN#k 只数这几列）"""
        head, sep, k = text.rpartition("#")
        if not sep or not head or not k.isdigit() or int(k) < 1:
            raise CodestrataError("usage", f"起点写成 列#k（第 k 轮）、FN#k（这段时间里第 k 次调用 FN）或 列:FN#k，k 从 1 数：{text!r}")
        k = int(k)
        sel, colon, fn = head.partition(":")
        if colon and "/" in sel and "#" not in sel and _laneid.select([sel], self.aliases, strict=False):
            return self._call_start(text, fn, [self.one_lane(sel)], k)
        if "#" not in head and ":" not in head and _laneid.select([head], self.aliases, strict=False):
            return self._round_start(text, self.one_lane(head), k)
        lids = [x for x in (_laneid.select(lanes, self.aliases) if lanes else self.A["lanes"]) if x in self.A["lanes"]]
        return self._call_start(text, head, lids, k)

    def _call_start(self, text: str, fn: str, lids: list[str], k: int) -> tuple[Pos, dict]:
        cnt: Counter = Counter()
        for lid in lids:
            cnt.update(self.counts(lid))
        node, ks = _funcref.resolve(fn, self.keys, self.label, cnt)
        allc = sorted((c, lid) for lid in lids for c in self.calls(lid, ks))
        if not allc:
            raise CodestrataError("item_not_found", f"这段时间里没调过 {node}" + ("（只数了 REF 里的列）" if len(lids) < len(self.A["lanes"]) else ""))
        if k > len(allc):
            raise CodestrataError("usage", f"这段时间里 {node.partition('#')[2]} 只调了 {len(allc)} 次：{text!r}")
        c, lid = allc[k - 1]
        mine = [x for x, ln in allc if ln == lid]
        j = mine.index(c)
        pos = Pos(lid, c[0], mine[j + 1][0] if j + 1 < len(mine) else self.hi, len(mine), j + 1, call=(c[2], c[3]), fn=node)
        return pos, {"kind": "call", "text": text, "lane": self.alias(lid), "fn": node, "k": k, "n": len(allc),
                     "k_lane": j + 1, "n_lane": len(mine), "t0_us": c[0], "t1_us": c[1]}

    def _round_start(self, text: str, lid: str, k: int) -> tuple[Pos, dict]:
        ln = self.A["lanes"][lid]
        if not ln["loop"]:
            raise CodestrataError("no_loop", f"{self.alias(lid)} 认不出主循环、没有轮号；起点改写成 FN#k 或 列:FN#k")
        rs = ln["rounds"]
        if k > len(rs):
            raise CodestrataError("usage", f"{self.alias(lid)} 整个 run 只有 {len(rs)} 轮：{text!r}")
        x = rs[k - 1]
        if x["t1_us"] < self.lo or x["t0_us"] > self.hi:
            first, last = (ln["win"][0]["k"], ln["win"][-1]["k"]) if ln["win"] else (None, None)
            raise CodestrataError("usage", f"第 {k} 轮（t={x['t0_us']}）不在这段时间里" + (f"（这段是第 {first}–{last} 轮）" if first else ""))
        win = [y["k"] for y in ln["win"]]
        pos = Pos(lid, x["t0_us"], x["t1_us"], max(len(win), 1), win.index(k) + 1 if k in win else 1)
        return pos, {"kind": "round", "text": text, "lane": self.alias(lid), "k": k, "t0_us": x["t0_us"], "t1_us": x["t1_us"]}

    # ------------------------------------------------------------ 走

    def walk(self, pos: Pos, links: list[Link], first: tuple[int, int]) -> dict:
        """从 pos 走到停下：{hops, stop, slices_us, lanes}。first：起点那次调用 / 那一轮的 (开始, 结束)"""
        hops: list[dict] = []
        stays = [first]
        lanes = [self.alias(pos.lane)]
        while True:
            if len(hops) >= MAX_HOPS:
                stop = {"reason": "hops", "lane": self.alias(pos.lane), "t_us": pos.t}
                break
            ex = self._by_link(pos, links) or self._recorded(pos)
            if ex is None:
                stays.append((pos.t, min(pos.t + TAIL_US, self.hi)))
                stop = self._stop(pos)
                break
            hop, nxt, leave = ex
            hops.append(hop)
            stays.append((pos.t, leave))
            pos = nxt
            if self.alias(pos.lane) not in lanes:
                lanes.append(self.alias(pos.lane))
            if pos.t > self.hi:
                stop = {"reason": "range", "lane": self.alias(pos.lane), "t_us": pos.t}
                break
        return {"hops": hops, "stop": stop, "slices_us": merge(stays, self.lo, self.hi), "lanes": lanes}

    def _by_link(self, pos: Pos, links: list[Link]):
        end = min(pos.until, self.hi)
        best = None
        for L in links:
            if L.a.lane != pos.lane:
                continue
            j = _first(L.a.calls, pos.t, end)
            if j is not None and (best is None or L.a.calls[j][0] < best[0].a.calls[best[1]][0]):
                best = (L, j)
        if best is None:
            return None
        L, j = best
        x, y = L.a.calls[j], L.b.calls[j]
        inside = (pos.at is not None and self._inside(pos.at[0], pos.at[1], (x[2], x[3]))) or self._inside(x[2], x[3], pos.call)
        hop = {"kind": "link", "via": "link", "link": L.text, "basis": "order", "stay": "ancestor" if inside else "time",
               "k": j + 1, "n": len(L.a.calls), "from": self._fn_end(L.a, x), "to": self._fn_end(L.b, y)}
        rec = self._recorded(pos)
        if rec and rec[0]["to"]["lane"] == hop["to"]["lane"]:
            hop["recorded_too"] = rec[0]["group"]         # 这一跳其实录到了：--link 可以不给（给了照它配）
        nxt = Pos(L.b.lane, y[0], L.b.calls[j + 1][0] if j + 1 < len(L.b.calls) else self.hi, len(L.b.calls), j + 1,
                  call=(y[2], y[3]), fn=L.b.node)
        return hop, nxt, x[1]

    def _recorded(self, pos: Pos):
        end = min(pos.until, self.hi)
        outs = self.out.get(pos.lane) or []
        i = bisect.bisect_left(outs, (pos.t, -1))
        if i >= len(outs) or outs[i][0] >= end:
            return None
        t, hx = outs[i]
        h = self.hs[hx]
        fl, tl = self.side[hx]
        t2 = h["to"][3]
        arr = self.arr.get((h["via"], fl, tl)) or [t2]
        k, j = bisect.bisect_left(arr, t2), bisect.bisect_right(arr, t2)
        ea, eb = self.ends.get(hx) or (None, None)
        hop = {"kind": "recorded", "via": h["via"], "group": _linkgroups.group_id("handoff", h["via"], self.alias(fl), self.alias(tl)),
               "basis": "recorded", "stay": "ancestor" if self._inside(h["from"][0], h["from"][2], pos.call) else "time",
               "k": min(k, len(arr) - 1) + 1, "n": len(arr), "from": self._raw_end(fl, h["from"], ea), "to": self._raw_end(tl, h["to"], eb)}
        # 按时间接的（进来之后第一次交出）和按先后配的（这一组交出的次数和进来的份数一样时，第 k 份配第 k 次）不是同一次：
        # 照旧按时间走（用户 10-10 定的），把按先后的那次写出来——流水线上前一份的结果常在这一份进来之后才交出
        dep = self.dep.get((h["via"], fl, tl)) or []
        if hop["stay"] == "time" and len(dep) == pos.n and 0 < pos.k <= len(dep) and dep[pos.k - 1][1] != hx:
            mine = next((i for i, (_, x) in enumerate(dep) if x == hx), None)
            hop["alt"] = {"basis": "order", "k": pos.k, "t_us": dep[pos.k - 1][0], "n": len(dep), "picked_k": None if mine is None else mine + 1}
        nxt = Pos(tl, t2, arr[j] if j < len(arr) else self.hi, len(arr), hop["k"],
                  at=(h["to"][0], h["to"][2]) if h["to"][2] >= 0 else None, fn=hop["to"]["fn"])
        return hop, nxt, t

    def _fn_end(self, f: Fn, c: tuple) -> dict:
        return {"lane": self.alias(f.lane), "t_us": c[0], **_linkgroups.end(f.node, 0, False, None)}

    def _raw_end(self, lid: str, raw: list, e: dict | None) -> dict:
        """交接的一头：函数按 lanes.build 认的（放 / 取在仓库外时是栈底的仓库函数）；它没给的（不该有）按 span 的被调方"""
        if e is not None:
            d = _linkgroups.end(e["fn"], e.get("line") or 0, e.get("ext", False), None)
        else:
            rows = self.A["rows"].get(raw[0]) or []
            r = rows[raw[2]] if 0 <= raw[2] < len(rows) else None
            d = _linkgroups.end(self.node_of(r[5]) if r else None, raw[4] if len(raw) > 4 else 0, r is None, None)
        return {"lane": self.alias(lid), "t_us": raw[3], **d}

    # ------------------------------------------------------------ 停下

    def _stop(self, pos: Pos) -> dict:
        outs = self.out.get(pos.lane) or []
        i = bisect.bisect_left(outs, (pos.t, -1))
        nxt = None
        if i < len(outs):
            t, hx = outs[i]
            via = self.hs[hx]["via"]
            fl, tl = self.side[hx]
            nxt = {"t_us": t, "via": via, "to": self.alias(tl), "group": _linkgroups.group_id("handoff", via, self.alias(fl), self.alias(tl)),
                   "basis": "time", "after_range": t > self.hi}
        return {"reason": "none", "lane": self.alias(pos.lane), "t_us": pos.t, "until_us": pos.until if pos.until < self.hi else None,
                "next_out": nxt, "candidates": self.candidates(pos)}

    def _rows_after(self, lid: str, t: int, end: int):
        """这一列 [t, end) 里开始的 span（行）"""
        ln = self.A["lanes"][lid]
        st = self._starts.get(lid)
        if st is None:
            st = self._starts[lid] = [r[0] for _, r in ln["lr"]]
        for k in range(bisect.bisect_left(st, t), len(st)):
            if st[k] >= end:
                break
            yield ln["lr"][k][1]

    def _busy(self, lid: str, r: list, t: int | None) -> bool:
        """这一行是不是在干活：主循环的列里，不是常规的函数、不在空转 / 在等的轮里；t 给了的话那一轮还要在 t 之后才开始
        （t 之前就开始的那一轮干的是上一份）。没有主循环的列都算"""
        ln = self.A["lanes"][lid]
        if not ln["loop"]:
            return True
        if r[5] in ln["regular"]:
            return False
        st = self._rstarts.get(lid)
        if st is None:
            st = self._rstarts[lid] = [x["t0_us"] for x in ln["rounds"]]
        k = bisect.bisect_right(st, r[0]) - 1
        x = ln["rounds"][k] if 0 <= k < len(ln["rounds"]) and r[0] < ln["rounds"][k]["t1_us"] else None
        return x is None or not (x["spin"] or x["wait"] or (t is not None and x["t0_us"] < t))

    def _fns_after(self, lid: str, t: int, end: int, cap: int, fresh: bool) -> list[tuple[str, int]]:
        """这一列 [t, end) 里先跑的、在干活的函数（_busy）[(节点, 第一次的时刻)]，按第一次的先后；fresh：只看 t 之后才开始的轮"""
        out: dict[str, int] = {}
        for r in self._rows_after(lid, t, end):
            nd = self.node_of(r[5])
            if nd and nd not in out and self._busy(lid, r, t if fresh else None):
                out[nd] = r[0]
                if len(out) >= cap:
                    break
        return list(out.items())

    def candidates(self, pos: Pos) -> dict:
        """停下时 --link 的候选（见模块说明）"""
        end = min(pos.until, self.hi)
        a_nodes = [nd for nd, _ in self._fns_after(pos.lane, pos.t, end, 4 * CAND_FNS, False)]
        if pos.fn:                                   # 收到的那一头的函数排最前
            a_nodes = [pos.fn] + [x for x in a_nodes if x != pos.fn]
        a_all, pick = [], None
        for nd in a_nodes:
            cs = self.calls(pos.lane, self.keys_of(pos.lane, nd))
            if not cs:
                continue
            # 一份一次：次数和这一路的份数一样，而且第 k 次就在这一份里（包着 t，或者在 [t, end) 里开始）
            c = cs[pos.k - 1] if len(cs) == pos.n and 0 < pos.k <= len(cs) else None
            per = c is not None and (c[0] <= pos.t <= c[1] or pos.t <= c[0] < end)
            a_all.append({"fn": nd, "n": len(cs), "per_item": per})
            if per and (pick is None or c[1] > pick[1]):          # 一份一次的里面，这一份的那次结束得最晚的（离交出去最近）
                pick = (Fn(pos.lane, nd, cs), c[1])
        X = pick[0] if pick else None
        top = [x for x in a_all if X and x["fn"] == X.node] + [x for x in a_all if x["fn"] == pos.fn and not (X and X.node == pos.fn)]
        rest = [x for x in a_all if x not in top]
        a_list = top + [x for x in rest if x["per_item"]][:CAND_FNS - len(top)] + [x for x in rest if not x["per_item"]][:2]
        pid = self.A["lanes"][pos.lane]["pid"]
        lanes = []
        for lid, ln in self.A["lanes"].items():
            if lid == pos.lane or not ln["lr"]:
                continue
            fns = self._fns_after(lid, pos.t, end, CAND_FNS, True)
            if fns:
                lanes.append((ln["pid"] != pid, fns[0][1], lid, fns))
        lanes.sort(key=lambda x: (x[0], x[1], x[2]))
        b_list, link = [], None
        for _, t1, lid, fns in lanes[:CAND_LANES]:
            items = []
            for nd, _ in fns:
                ys = self.calls(lid, self.keys_of(lid, nd))
                fits = X is not None and misfit(X.calls, ys) is None
                items.append({"fn": nd, "n": len(ys), "fits": fits})
                if fits and link is None:
                    link = f"{self.alias(pos.lane)}:{self.fn_text(pos.lane, X.node)} => {self.alias(lid)}:{self.fn_text(lid, nd)}"
            b_list.append({"lane": self.alias(lid), "first_us": t1, "fns": items})
        return {"a": {"lane": self.alias(pos.lane), "fns": a_list, "pick": X.node if X else None, "n_in": pos.n},
                "b": b_list, "link": link}
