"""链（links --follow）：顺着交接从一处一跳一跳走到别的列，每一跳写明是录到的还是推出来的、按什么推的。

起点（Walker.start）：
    `列#k`          这一列主循环的第 k 轮（轮号和 steps 一样：轮头在 REF 所在的阶段上认，整个 run 上数）；
    `FN#k`          这段时间里第 k 次调用 FN（从 1 数；REF 带了列时只数这几列）；`列:FN#k` 只数这一列的；
    `列:FN@t=微秒`   这一列在这一刻开始（或正在跑）的那次 FN——不随 REF 的范围变，输出里的起点都给这种写法（stable）；
    `列@t=微秒`      这一列在这一刻收到的那一份（只跑仓库外代码的列也能起步；这一刻没收到东西就从这一刻起看这一列）。
次数和 find、分列一样数（seq.each_call：合成一行的连续调用摊开，只算落在这段时间里的）。
在一列里走的是「这一份」：数据在 t 进到这一列，是这一路这段时间里 n 份里的第 k 份。按先后看：
    1. --link 的 A 边是这一列：A 函数这一份里的那次（正包着 t、或者在下一份进来之前开始的第一次）是第 j 次 → 跳到 B 列 B 函数的第 j 次
       （agent 读过代码后明说的；这期间正好有录到的交出到 B 列时记 recorded_too）；
    2. 交出就在这次调用里（起点那次调用 / --link 落到的那次调用里面）：跟它（stay ancestor）；起点是一轮时，这一轮里的第一次交出（round）；
    3. 这一列交出的哪一组正好也是 n 次：第 k 份配这一组的第 k 次交出（不早于进来的那一刻；几组都行取最早的）（order，用户 10-10 深夜定：
       流水线上一份的结果常在下一份进来之后才交出，按时间接会差一份）；
    4. 否则按时间：同一条线程这期间（到同一路的下一份进来为止）第一次交出（time）；
    5. 都没有就停下。
    跳本身：录到的是 recorded，--link 配的是 order。从进来到交出这期间这一列还收到了别的路的数据：记 mixed（交出的不一定只是这一份）。
--link 'A列:FN => B列:FN'（用户 10-10 定：没录到的跳要 agent 显式给）：这段时间里 A 边第 k 次调用配 B 边第 k 次。两边次数不等、
    或者有一次 B 早于同一次的 A，拒绝（link_mismatch），候选是 B 列里配得上的、拼好的 --link。
停下（stop.reason）：
    none   这一份没有交出，也没有能用的 --link：写这一列下一次交出（时刻、通道、到哪列；inferred: time，不往下走）和 --link 的候选（chainhint）；
    range  收到的那一刻已经出了这段时间；
    hops   走了 MAX_HOPS 跳。
走出来的链是一个段（kind chain）：每一列待的那段时间（几片，相隔不到 MERGE_US 的合起来）× 经过的列；最后一列取收到的那一轮
    （有主循环、不是空转 / 在等的轮，最多 TAIL_MAX_US），没有就是收到之后 TAIL_US。
纯计算：输入是 segments.analyse 的结果（span、列、轮）和 lanes.EndFns（交接两头的函数：和页面、links 同一个认法）。看的是 [lo, hi] 一整段
（几片的 REF 由调用方换成整段）。
"""
from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass

from . import funcref as _funcref
from . import laneid as _laneid
from . import linkgroups as _linkgroups
from . import seq as _seq
from .errors import CodestrataError

ALGO = "chain/2"
MAX_HOPS = 40
TAIL_US = 1000
TAIL_MAX_US = 50_000
MERGE_US = 5000


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
    """数据在一列里：t 进来，until 之前（同一路的下一份进来）；这是这一路这段时间里 n 份里的第 k 份（n 是 0：不知道是哪一路）。
    tid：在哪条线程上（不知道是 None）；call：起点那次调用 / --link 落到的那次（pid, span 下标）；at：收到的那一处（pid, span 下标）；
    fn：进来的那一头的函数；group：进来的那一路（录到的交接的组的写法）；round：起点是一轮"""
    lane: str
    t: int
    until: int
    n: int
    k: int
    tid: int | None = None
    call: tuple | None = None
    at: tuple | None = None
    fn: str | None = None
    group: str | None = None
    round: bool = False


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


def _first(calls: list, t: int, end: int) -> int | None:
    """calls 里正包着 t 的那次，或者 [t, end) 里开始的第一次（下标）"""
    i = bisect.bisect_right(calls, (t, float("inf")))
    if i > 0 and calls[i - 1][0] <= t <= calls[i - 1][1]:
        return i - 1
    return i if i < len(calls) and calls[i][0] < end else None


class Walker:
    """一个 run 的一段时间 [lo, hi]：A 是 segments.analyse 的结果，ends 是 lanes.EndFns（交接两头落在哪个函数上，和页面同一个认法）"""

    def __init__(self, A: dict, ends, lo: int, hi: int):
        self.A, self.ends, self.lo, self.hi = A, ends, lo, hi
        self.keys = A["ix"]["keys"]
        self.aliases = A["aliases"]
        self.hs = A["ix"].get("handoffs") or []
        tl = A["tid_lane"]
        self.side: dict[int, tuple] = {}             # 交接下标 → (起列, 终列)
        self.out: dict[str, list] = {}               # 列 → [(交出的时刻, 交接下标)]（整个 run）
        self.dep: dict[str, dict] = {}               # 列 → {组: [(交出的时刻, 交接下标)]}（交出在这段时间里的）
        self.arr: dict[str, list] = {}               # 组 → [收到的时刻]（交出在这段时间里的）
        self.inc: dict[str, list] = {}               # 列 → [(收到的时刻, 组)]（交出在这段时间里的）
        for hx, h in enumerate(self.hs):
            fl, tl_ = tl.get((h["from"][0], h["from"][1])), tl.get((h["to"][0], h["to"][1]))
            if fl is None or tl_ is None or fl == tl_ or h["from"][3] is None or h["to"][3] is None:
                continue
            self.side[hx] = (fl, tl_)
            self.out.setdefault(fl, []).append((h["from"][3], hx))
            if _seq.in_segs(h["from"][3], [(lo, hi)]):
                g = self.group(hx)
                self.dep.setdefault(fl, {}).setdefault(g, []).append((h["from"][3], hx))
                self.arr.setdefault(g, []).append(h["to"][3])
                self.inc.setdefault(tl_, []).append((h["to"][3], g))
        for v in (*self.out.values(), *self.arr.values(), *self.inc.values(), *(x for d in self.dep.values() for x in d.values())):
            v.sort()
        self._by_key: dict[str, dict] = {}           # 列 → {键下标: 这段时间里的每一次调用}
        self._counts: dict[str, Counter] = {}
        self._starts: dict[str, list] = {}           # 列 → 这一列 span 的开始时刻（和 lr 一一对应）
        self._rstarts: dict[str, list] = {}          # 列 → 各轮的开始时刻
        self._nodes: dict[int, str | None] = {}

    # ------------------------------------------------------------ 列、函数

    def alias(self, lid: str) -> str:
        return self.aliases.get(lid, lid)

    def group(self, hx: int) -> str:
        fl, tl = self.side[hx]
        return _linkgroups.group_id("handoff", self.hs[hx]["via"], self.alias(fl), self.alias(tl))

    def label(self, key: str) -> str:
        """键 → 函数的节点，录制之后文件改过的跟着函数挪（和页面一样，EndFns 的 keymap）"""
        km = self.ends.keymap
        return self.ends.label(km(key) if km is not None and key != "?" else key)

    def node_of(self, b: int) -> str | None:
        """键下标 → 函数的节点；落不到函数上（? 、模块顶层）是 None"""
        if b not in self._nodes:
            k = self.keys[b] if 0 <= b < len(self.keys) else "?"
            nd = self.ends.fn_of(b) if k != "?" and not k.endswith(":0") else None
            self._nodes[b] = nd if nd and "#<module>" not in nd else None
        return self._nodes[b]

    def by_key(self, lid: str) -> dict:
        """这一列这段时间里每个被调方（键下标）的每一次调用 [(开始, 结束, pid, 下标)]（合成一行的按 seq.each_call 摊开）"""
        hit = self._by_key.get(lid)
        if hit is None:
            ln = self.A["lanes"][lid]
            hit = self._by_key[lid] = {}
            for i, r in ln["lr"]:
                if r[0] > self.hi or (r[0] + max(r[1], 0) < self.lo):
                    continue
                single = r[6] <= 1 or r[1] <= 0
                for t in _seq.each_call(r[0], r[1], r[6], self.lo, self.hi):
                    hit.setdefault(r[5], []).append((t, r[0] + max(r[1], 0) if single else t, ln["pid"], i))
        return hit

    def counts(self, lid: str) -> Counter:
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

    def nodes_on(self, lid: str) -> dict[str, set]:
        """这一列这段时间里调过的函数 → 它的键下标"""
        out: dict[str, set] = {}
        for b in self.by_key(lid):
            nd = self.node_of(b)
            if nd:
                out.setdefault(nd, set()).add(b)
        return out

    def tid_of(self, pid: int, row: int) -> int | None:
        rows = self.A["rows"].get(pid) or []
        r = rows[row] if 0 <= row < len(rows) else None
        return r[2] if r is not None else None

    def one_lane(self, sel: str) -> str:
        """一个列选择器 → 正好一列（有线程的列）"""
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
            raise CodestrataError("item_not_found", f"{self.alias(lid)} 这段时间里没调过 {node}" + (
                "（这一列只跑仓库外的代码：没有仓库函数可写）" if not self.A["lanes"][lid]["lr"] else ""),
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

    def secs(self, t: int) -> str:
        """错误、警告里的时刻：和文字一样，从这一段开头算的 +秒"""
        return f"{'+' if t >= self.lo else '-'}{abs(t - self.lo) / 1e6:.3f}"

    def _inside(self, pid: int, row: int | None, call: tuple | None) -> bool:
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
        sides = []
        for which, sel, fn in (("A", sa, fa), ("B", sb, fb)):
            try:
                lid = self.one_lane(sel)
                sides.append((lid, self.fn(lid, fn)))
            except CodestrataError as e:              # 写明是哪一条 --link 的哪一边
                raise CodestrataError(e.code, f"--link {text!r} 的 {which} 边：{e.msg}", candidates=e.candidates) from None
        (la, a), (lb, b) = sides
        if la == lb:
            raise CodestrataError("usage", f"--link 的两头是同一列（{self.alias(la)}）：同一列里从进来到交出是自动接的，"
                                           "--link 接的是两列之间没录到的那一跳")
        bad = misfit(a.calls, b.calls)
        if bad:
            fits = self.fitting(lb, a.calls)
            raise CodestrataError("link_mismatch", f"--link {text!r} 配不上：{self._misfit_text(a, b, bad)}；"
                                                   "按先后一一配要两边次数一样、每一次 B 都不早于同一次的 A"
                                  + ("。B 列里配得上的在候选里（拼好的 --link）" if fits else "。B 列里没有配得上的函数"),
                                  candidates=[f"{sa}:{fa} => {self.alias(lb)}:{self.fn_text(lb, n)}" for n in fits][:12])
        return Link(text, a, b)

    def _misfit_text(self, a: Fn, b: Fn, bad: tuple) -> str:
        sa, sb = f"{self.alias(a.lane)} 的 {a.node.partition('#')[2]}", f"{self.alias(b.lane)} 的 {b.node.partition('#')[2]}"
        if bad[0] == "count":
            return f"两边次数不等（A 边 {sa} 这段时间 {bad[1]} 次，B 边 {sb} {bad[2]} 次）"
        return f"第 {bad[1]} 次 B（{sb}，{self.secs(bad[3])}）早于第 {bad[1]} 次 A（{sa}，{self.secs(bad[2])}）"

    def fitting(self, lid: str, xs: list) -> list[str]:
        """lid 这一列里和 xs 一样多次、每一次都不早于同一次 xs 的函数（节点），按第一次的先后"""
        out = []
        for nd, ks in self.nodes_on(lid).items():
            if sum(len(self.by_key(lid)[b]) for b in ks) != len(xs):
                continue
            ys = self.calls(lid, ks)
            if misfit(xs, ys) is None:
                out.append((ys[0][0], nd))
        return [nd for _, nd in sorted(out)]

    def start(self, text: str, lanes: list[str] | None) -> tuple[Pos, dict]:
        """起点 → (Pos, 起点的说明)。lanes：REF 带的列选择器（FN#k 只数这几列）"""
        head, at_, tt = text.rpartition("@t=")
        if at_:
            if not tt.isdigit() or not head:
                raise CodestrataError("usage", f"起点写成 列:FN@t=微秒（这一刻那次调用）或 列@t=微秒（这一列这一刻收到的那一份）：{text!r}")
            sel, colon, fn = head.partition(":")
            lid = self.one_lane(sel)
            return self._call_at(text, lid, fn, int(tt)) if colon else self._lane_at(text, lid, int(tt))
        head, sep, k = text.rpartition("#")
        if not sep or not head or not k.isdigit() or int(k) < 1:
            raise CodestrataError("usage", f"起点写成 列#k（第 k 轮）、FN#k（这段时间里第 k 次调用 FN）、列:FN#k、列:FN@t=微秒 或 列@t=微秒，"
                                           f"k 从 1 数：{text!r}")
        k = int(k)
        sel, colon, fn = head.partition(":")
        if colon and "/" in sel and "#" not in sel and _laneid.select([sel], self.aliases, strict=False):
            return self._call_start(text, fn, [self.one_lane(sel)], k)
        if "#" not in head and ":" not in head and _laneid.select([head], self.aliases, strict=False):
            return self._round_start(text, self.one_lane(head), k)
        lids = [x for x in (_laneid.select(lanes, self.aliases) if lanes else self.A["lanes"]) if x in self.A["lanes"]]
        return self._call_start(text, head, lids, k)

    def _call_pos(self, text: str, lid: str, node: str, mine: list, j: int, k: int, n: int) -> tuple[Pos, dict]:
        c = mine[j]
        pos = Pos(lid, c[0], mine[j + 1][0] if j + 1 < len(mine) else self.hi, len(mine), j + 1,
                  tid=self.tid_of(c[2], c[3]), call=(c[2], c[3]), fn=node)
        return pos, {"kind": "call", "text": text, "lane": self.alias(lid), "fn": node, "k": k, "n": n, "k_lane": j + 1,
                     "n_lane": len(mine), "t0_us": c[0], "t1_us": c[1],
                     "stable": f"{self.alias(lid)}:{self.fn_text(lid, node)}@t={c[0]}"}

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
        return self._call_pos(text, lid, node, mine, mine.index(c), k, len(allc))

    def _call_at(self, text: str, lid: str, fn: str, t: int) -> tuple[Pos, dict]:
        f = self.fn(lid, fn)
        j = next((i for i, c in enumerate(f.calls) if c[0] <= t <= c[1]), None)
        if j is None:
            near = min(f.calls, key=lambda c: abs(c[0] - t))
            raise CodestrataError("usage", f"{self.alias(lid)} 在 {self.secs(t)}（t={t}）没有在跑 {f.node.partition('#')[2]}；"
                                           f"最近的一次从 t={near[0]} 开始：{text!r}")
        return self._call_pos(text, lid, f.node, f.calls, j, j + 1, len(f.calls))

    def _lane_at(self, text: str, lid: str, t: int) -> tuple[Pos, dict]:
        """这一列这一刻收到的那一份（是录到的交接就知道是哪一路的第几份）；这一刻没收到东西：从这一刻起看这一列"""
        hx = next((hx for hx, (fl, tl) in self.side.items() if tl == lid and self.hs[hx]["to"][3] == t), None)
        info = {"kind": "lane", "text": text, "lane": self.alias(lid), "t0_us": t, "t1_us": t, "stable": f"{self.alias(lid)}@t={t}"}
        if hx is None:
            return Pos(lid, t, self.hi, 0, 0), info
        g = self.group(hx)
        arr = self.arr.get(g) or [t]
        k, j = bisect.bisect_left(arr, t), bisect.bisect_right(arr, t)
        to = self.hs[hx]["to"]
        info["group"] = g
        return Pos(lid, t, arr[j] if j < len(arr) else self.hi, len(arr), min(k, len(arr) - 1) + 1, tid=to[1],
                   at=(to[0], to[2]) if to[2] >= 0 else None, group=g), info

    def _round_start(self, text: str, lid: str, k: int) -> tuple[Pos, dict]:
        ln = self.A["lanes"][lid]
        if not ln["loop"]:
            raise CodestrataError("no_loop", f"{self.alias(lid)} 认不出主循环、没有轮号；起点改写成 FN#k、列:FN#k，"
                                             f"只跑仓库外代码的列写 {self.alias(lid)}@t=微秒")
        rs = ln["rounds"]
        if k > len(rs):
            raise CodestrataError("usage", f"{self.alias(lid)} 整个 run 只有 {len(rs)} 轮：{text!r}")
        x = rs[k - 1]
        if x["t1_us"] < self.lo or x["t0_us"] > self.hi:
            first, last = (ln["win"][0]["k"], ln["win"][-1]["k"]) if ln["win"] else (None, None)
            raise CodestrataError("usage", f"第 {k} 轮（t={x['t0_us']}）不在这段时间里" + (f"（这段是第 {first}–{last} 轮）" if first else ""))
        win = [y["k"] for y in ln["win"]]
        pos = Pos(lid, x["t0_us"], x["t1_us"], max(len(win), 1), win.index(k) + 1 if k in win else 1, tid=ln["loop"]["tid"], round=True)
        return pos, {"kind": "round", "text": text, "lane": self.alias(lid), "k": k, "t0_us": x["t0_us"], "t1_us": x["t1_us"],
                     "stable": text}

    # ------------------------------------------------------------ 走

    def walk(self, pos: Pos, links: list[Link], first: tuple[int, int]) -> dict:
        """从 pos 走到停下：{hops, stop, slices_us, lanes, at, seen}（at：停下时数据在哪；seen：走过的列 id——给候选用）。
        first：起点那次调用 / 那一轮的 (开始, 结束)"""
        hops: list[dict] = []
        stays = [first]
        lanes = [self.alias(pos.lane)]
        seen = {pos.lane}
        while True:
            if len(hops) >= MAX_HOPS:
                stop = {"reason": "hops", "lane": self.alias(pos.lane), "t_us": pos.t}
                break
            ex = self._by_link(pos, links) or self._recorded(pos)
            if ex is None:
                stays.append(self._tail(pos))
                stop = self._stop(pos)
                break
            hop, nxt, leave = ex
            hops.append(hop)
            stays.append((pos.t, leave))
            pos = nxt
            seen.add(pos.lane)
            if self.alias(pos.lane) not in lanes:
                lanes.append(self.alias(pos.lane))
            if pos.t > self.hi:
                stop = {"reason": "range", "lane": self.alias(pos.lane), "t_us": pos.t}
                break
        return {"hops": hops, "stop": stop, "slices_us": merge(stays, self.lo, self.hi), "lanes": lanes, "at": pos, "seen": seen}

    def _mixed(self, pos: Pos, t_out: int) -> dict | None:
        """从进来到交出这期间这一列还收到的别的路的数据：{n, groups}（交出的不一定只是这一份）"""
        inc = self.inc.get(pos.lane) or []
        i = bisect.bisect_right(inc, (pos.t, "\U0010ffff"))
        n, gs = 0, set()
        while i < len(inc) and inc[i][0] < t_out:
            if inc[i][1] != pos.group:
                n += 1
                gs.add(inc[i][1])
            i += 1
        return {"n": n, "groups": sorted(gs)} if n else None

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
        mixed = self._mixed(pos, x[0])
        if mixed:
            hop["mixed"] = mixed
        nxt = Pos(L.b.lane, y[0], L.b.calls[j + 1][0] if j + 1 < len(L.b.calls) else self.hi, len(L.b.calls), j + 1,
                  tid=self.tid_of(y[2], y[3]), call=(y[2], y[3]), fn=L.b.node)
        return hop, nxt, x[1]

    def _timed(self, pos: Pos) -> tuple | None:
        """按时间：同一条线程这期间（到同一路的下一份进来为止）第一次交出 (时刻, 交接下标)；不知道线程时这一列的任何一条"""
        end = min(pos.until, self.hi)
        outs = self.out.get(pos.lane) or []
        for t, hx in outs[bisect.bisect_left(outs, (pos.t, -1)):]:
            if t >= end:
                return None
            if pos.tid is None or self.hs[hx]["from"][1] == pos.tid:
                return t, hx
        return None

    def _recorded(self, pos: Pos):
        timed = self._timed(pos)
        if timed and (pos.round or self._inside(self.hs[timed[1]]["from"][0], self.hs[timed[1]]["from"][2], pos.call)):
            return self._hop(pos, timed, "round" if pos.round else "ancestor")
        if pos.n and pos.k:                          # 按先后：这一组交出的次数和进来的份数一样，第 k 份配第 k 次
            best = None
            for dep in (self.dep.get(pos.lane) or {}).values():
                if len(dep) == pos.n and dep[pos.k - 1][0] >= pos.t and (best is None or dep[pos.k - 1][0] < best[0]):
                    best = dep[pos.k - 1]
            if best is not None:
                return self._hop(pos, best, "order")
        return self._hop(pos, timed, "time") if timed else None

    def _hop(self, pos: Pos, out_: tuple, stay: str):
        t, hx = out_
        h = self.hs[hx]
        fl, tl = self.side[hx]
        g = self.group(hx)
        t2 = h["to"][3]
        arr = self.arr.get(g) or [t2]
        k, j = bisect.bisect_left(arr, t2), bisect.bisect_right(arr, t2)
        hop = {"kind": "recorded", "via": h["via"], "group": g, "basis": "recorded", "stay": stay,
               "k": min(k, len(arr) - 1) + 1, "n": len(arr), "from": self._raw_end(fl, h["from"]), "to": self._raw_end(tl, h["to"])}
        if stay == "order":
            hop["stay_k"] = pos.k                    # 第几份配这一组的第几次交出
        mixed = self._mixed(pos, t)
        if mixed:
            hop["mixed"] = mixed
        nxt = Pos(tl, t2, arr[j] if j < len(arr) else self.hi, len(arr), hop["k"], tid=h["to"][1],
                  at=(h["to"][0], h["to"][2]) if h["to"][2] >= 0 else None, fn=hop["to"]["fn"], group=g)
        return hop, nxt, t

    def _fn_end(self, f: Fn, c: tuple) -> dict:
        return {"lane": self.alias(f.lane), "t_us": c[0], **_linkgroups.end(f.node, 0, False, None)}

    def _raw_end(self, lid: str, raw: list) -> dict:
        """交接的一头：函数按 EndFns 认（放 / 取在仓库外时是栈底的仓库函数）"""
        e = self.ends.end(raw[0], raw[1], raw[2], raw[3], raw[4] if len(raw) > 4 else 0)
        return {"lane": self.alias(lid), "t_us": raw[3], **_linkgroups.end(e["fn"], e["line"], e["ext"], None)}

    def _tail(self, pos: Pos) -> tuple[int, int]:
        """最后一列待的那段：收到的那一轮（有主循环、不是空转 / 在等的轮，最多 TAIL_MAX_US），没有就是收到之后 TAIL_US"""
        x = self.round_at(pos.lane, pos.t)
        if x is not None and not x["spin"] and not x["wait"]:
            return pos.t, min(x["t1_us"], pos.t + TAIL_MAX_US)
        return pos.t, pos.t + TAIL_US

    def round_at(self, lid: str, t: int) -> dict | None:
        """这一列 t 那一刻在的那一轮（没有主循环、不在任何一轮里是 None）"""
        ln = self.A["lanes"].get(lid) or {}
        rs = ln.get("rounds") or []
        st = self._rstarts.get(lid)
        if st is None:
            st = self._rstarts[lid] = [x["t0_us"] for x in rs]
        i = bisect.bisect_right(st, t) - 1
        return rs[i] if 0 <= i < len(rs) and t < rs[i]["t1_us"] else None

    # ------------------------------------------------------------ 停下

    def _stop(self, pos: Pos) -> dict:
        outs = self.out.get(pos.lane) or []
        i = bisect.bisect_left(outs, (pos.t, -1))
        nxt = None
        if i < len(outs):
            t, hx = outs[i]
            nxt = {"t_us": t, "via": self.hs[hx]["via"], "to": self.alias(self.side[hx][1]), "group": self.group(hx),
                   "basis": "time", "after_range": t > self.hi}
        return {"reason": "none", "lane": self.alias(pos.lane), "t_us": pos.t, "until_us": pos.until if pos.until < self.hi else None,
                "next_out": nxt}

    def busy(self, lid: str, r: list) -> bool:
        """这一行是不是在干活：主循环的列里，不是常规的函数、不在空转 / 在等的轮里（steps 的前景）；没有主循环的列都算"""
        ln = self.A["lanes"][lid]
        if not ln["loop"]:
            return True
        if r[5] in ln["regular"]:
            return False
        x = self.round_at(lid, r[0])
        return x is None or not (x["spin"] or x["wait"])

    def fns_after(self, lid: str, t: int, end: int, cap: int) -> list[tuple[str, int]]:
        """这一列 [t, end) 里先跑的、在干活的函数 [(节点, 第一次的时刻)]，按第一次的先后"""
        ln = self.A["lanes"][lid]
        st = self._starts.get(lid)
        if st is None:
            st = self._starts[lid] = [r[0] for _, r in ln["lr"]]
        out: dict[str, int] = {}
        for k in range(bisect.bisect_left(st, t), len(st)):
            if st[k] >= end:
                break
            r = ln["lr"][k][1]
            nd = self.node_of(r[5])
            if nd and nd not in out and self.busy(lid, r):
                out[nd] = r[0]
                if len(out) >= cap:
                    break
        return list(out.items())
