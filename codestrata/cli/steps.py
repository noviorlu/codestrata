"""codestrata steps：一列的主循环一轮轮。按「这一轮多调了什么」分组，每组给中位、p90、超长的轮；--with 只看调过某个函数的轮；
--why 看时间花在哪（自己的时间排行）。轮头和轮号在整个 run 上数，REF 的时间段只决定列出哪几轮。"""
from __future__ import annotations

import statistics
from collections import Counter

from .. import funcref as _funcref
from .. import laneid as _laneid
from .. import lanes as _lanes
from .. import segments as _seg
from .. import seq as _seq
from .. import steps as _steps
from ..errors import CodestrataError
from . import common, out

NAME = "steps"
EFFECT = "read"
DOES = "一列的主循环一轮轮：按多调了什么分组、超长的轮各给 REF；--with FN 只列调过 FN 的轮；--why 看时间花在哪"
USAGE = "codestrata steps REF/列 [--head FN] [--with FN] [--round K[-M]] [--list] [--limit N] [--why] [--json]"
EXAMPLE = "codestrata steps 20261001-170349-run_single_prompt@serving/stage1/MainThread --why"

SHOW_ROUNDS = 10        # 一组里列几个轮号


def add_args(p) -> None:
    p.add_argument("ref", metavar="REF/列", help="RUN@范围/进程/线程（只能是一列），或页面地址（lanes= 只选一列）")
    p.add_argument("--head", default=None, metavar="FN", help="自己指定轮头（认错了的时候）：函数的限定名或 路径#限定名")
    p.add_argument("--with", dest="with_", default=None, metavar="FN", help="只列调过 FN 的轮（任意深度）")
    p.add_argument("--round", default=None, metavar="K[-M]", help="只看第 K（到 M）轮")
    p.add_argument("--list", action="store_true", help="逐轮列出，不分组")
    p.add_argument("--limit", type=int, default=12, help="最多列几组 / 几轮（默认 %(default)s）")
    p.add_argument("--why", action="store_true", help="时间花在哪：这几轮里每个函数自己的时间（减去它调的仓库函数）")
    common.add_params(p)


def _rounds_arg(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    a, _, b = text.partition("-")
    try:
        k0, k1 = int(a.lstrip("#")), int((b or a).lstrip("#"))
    except ValueError:
        raise CodestrataError("usage", f"--round 写成 K 或 K-M：{text!r}") from None
    return min(k0, k1), max(k0, k1)


def run(a) -> out.Result:
    c = common.context(a)
    common.require_events(c)
    common.refuse_old(c)
    r = c.res
    lo, hi = r.slices[0][0], r.slices[-1][1]
    aliases = _lanes.run_aliases(r.rd)
    if not r.lanes:
        raise CodestrataError("usage", "steps 要一列：REF 后面加 /进程/线程", candidates=_loop_lanes(aliases))
    lids = _laneid.select(r.lanes, aliases)
    if len(lids) != 1:
        raise CodestrataError("ambiguous_lane", f"{','.join(r.lanes)} 对上了 {len(lids)} 列，steps 只看一列",
                              candidates=[aliases[x] for x in lids][:20])
    lid = lids[0]
    lane = aliases[lid]
    idx = common.index(c)
    label = common.labeler(idx)
    keys = _seq.span_index(r.rd)["keys"]
    pid = int(lid.partition(":")[0])
    p = common.params(a)
    head = None
    if a.head:
        A0 = _seg.analyse(r.rd, lo, hi, p, pids={pid})
        head = {lid: _funcref.resolve(a.head, keys, label, _calls(A0["lanes"][lid], lo, hi))[1]}
    A = _seg.analyse(r.rd, lo, hi, p, head=head, pids={pid})
    ln = A["lanes"].get(lid)
    if ln is None or not ln["loop"]:
        top = _calls(ln, lo, hi).most_common(8) if ln else []
        raise CodestrataError("no_loop", f"{lane} 在这段时间里认不出主循环（{ln['kind'] if ln else '没有调用'}）；可以用 --head 指定轮头",
                              candidates=[common.short(label(keys[b])) for b, _ in top], warnings=c.warnings,
                              next=[c.cmd("read", "path", f"{r.text}/{lane}", "--limit", "30")])
    rs = ln["rounds"]
    rk = _rounds_arg(a.round)
    sel = [x for x in rs if rk[0] <= x["k"] <= rk[1]] if rk else ln["win"]
    with_keys = None
    if a.with_:
        node, with_keys = _funcref.resolve(a.with_, keys, label, _calls(ln, lo, hi))
        sel = [x for x in sel if any(b in x["kids"] for b in with_keys)]
    head_node = label(keys[ln["loop"]["head"]])
    rid = r.run["id"]

    def rref(x: dict) -> str:
        return f"{rid}@t={x['t0_us']}-{x['t1_us']}/{lane}"

    def names(x: dict) -> list[str]:
        """这一轮多调的函数，调得多的在前（import 时执行的模块顶层、类体排在最后）"""
        n: Counter = Counter()
        for b in x["extra"]:
            nm = common.short(label(keys[b]))
            if nm != "?":
                n[nm] += x["kids"][b]
        return sorted(n, key=lambda nm: ("<module>" in nm or "." not in nm and nm[:1].isupper(), -n[nm], nm))

    med_all = statistics.median(x["dur_us"] for x in rs)
    where = f"@{r.phase}" if r.phase and not r.phase.startswith("t=") else (f"@{r.phase}" if r.phase else "整个 run")
    lines = [f"{lane} {where}：这段 {len(ln['win'])} 轮（整个 run {len(rs)} 轮，每轮从 {common.short(head_node)} 开始），"
             f"交出 {sum(x['out'] for x in ln['win'])}，空转 {sum(1 for x in ln['win'] if x['spin'])}"]
    if a.with_:
        lines.append(f"其中调过 {common.short(node)} 的 {len(sel)} 轮：" + " ".join(f"#{x['k']}" for x in sel[:40])
                     + (" …" if len(sel) > 40 else ""))
    more = None
    groups = []
    if a.why:
        lines += _why(r, ln, sel, label, keys)
    elif a.list:
        for x in sel[:a.limit]:
            tag = "超长" if x["long"] else ("空转" if x["spin"] else "")
            ex = names(x)
            lines.append(f"  #{x['k']:<6} {out.secs(x['t0_us'], lo)}  {out.dur(x['dur_us']):>10}  {x['calls']:>5} 次调用"
                         f"  交出 {x['out']}  {tag}" + (f"  多调了 {'、'.join(ex[:3])}" + (f" 等 {len(ex)} 个" if len(ex) > 3 else "") if ex else ""))
        if len(sel) > a.limit:
            more = {"shown": a.limit, "total": len(sel), "how": out.command("steps", r.full, "--list", "--limit", str(len(sel)),
                                                                            *(["--round", a.round] if a.round else []), repo=c.flag)}
    else:
        groups = _group(sel, names)
        for g in groups[:a.limit]:
            xs = g["rounds"]
            ex = g["extra"]
            extra = f"  多调了 {'、'.join(ex[:3])}" + (f" 等 {len(ex)} 个" if len(ex) > 3 else "") if ex else ""
            if len(xs) == 1:
                x = xs[0]
                tag = f"超长（中位的 {x['dur_us'] / med_all:.0f} 倍）" if x["long"] else ("空转" if x["spin"] else "")
                lines.append(f"  #{x['k']:<10} {out.dur(x['dur_us']):>10}  {tag}{extra}")
                if x["long"]:
                    lines.append(f"      REF {rref(x)}")
            else:
                ds = sorted(x["dur_us"] for x in xs)
                ks = [f"#{x['k']}" for x in xs]
                shown = " ".join(ks if len(ks) <= SHOW_ROUNDS else ks[:5]) + ("" if len(ks) <= SHOW_ROUNDS else " …")
                lines.append(f"  ×{len(xs):<10} 中位 {out.dur(int(statistics.median(ds)))} · p90 {out.dur(ds[int(0.9 * (len(ds) - 1))])}"
                             f"{'  空转' if all(x['spin'] for x in xs) else ''}（{shown}）{extra}")
        if len(groups) > a.limit:
            more = {"shown": a.limit, "total": len(groups), "how": out.command("steps", r.full, "--limit", str(len(groups)), repo=c.flag)}
        if any(len(g["rounds"]) > SHOW_ROUNDS for g in groups):
            lines.append("（逐轮看：加 --list）")
    longest = max(sel, key=lambda x: x["dur_us"]) if sel else None
    nxt = []
    if longest and not a.why:
        nxt.append(c.cmd("read", "steps", rref(longest), "--why", why=f"最长的 #{longest['k']} 时间花在哪"))
    if longest:
        nxt.append(c.cmd("read", "path", rref(longest), "--limit", "40", why=f"#{longest['k']} 的调用树"))
    data = {"lane": lane, "head": head_node, "n_rounds": len(rs), "median_us": int(med_all),
            "rounds": [{k: v for k, v in x.items() if k != "kids"} | {"extra": names(x), "ref": rref(x)} for x in sel],
            "groups": [{"rounds": [x["k"] for x in g["rounds"]], "extra": g["extra"]} for g in groups],
            "basis": p.basis()}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, more=more, warnings=c.warnings,
                      algo=_steps.ALGO)


def _loop_lanes(aliases: dict[str, str]) -> list[str]:
    return sorted(aliases.values())[:20]


def _calls(ln: dict | None, lo: int, hi: int) -> Counter:
    """这一列在这段时间里每个被调方调了几次（funcref 挑同名的、认不出主循环时给候选）"""
    c: Counter = Counter()
    for _, r in (ln or {}).get("lr") or []:
        if lo <= r[0] < hi:
            c[r[5]] += r[6]
    return c


def _group(sel: list[dict], names) -> list[dict]:
    """按「多调了什么 + 是不是超长」分组，组按第一轮的先后"""
    groups: dict[tuple, dict] = {}
    for x in sel:
        ex = names(x)
        g = groups.setdefault((x["long"], frozenset(ex)), {"extra": ex, "rounds": []})
        g["rounds"].append(x)
    return sorted(groups.values(), key=lambda g: g["rounds"][0]["k"])


def _why(r, ln: dict, sel: list[dict], label, keys) -> list[str]:
    """这几轮里每个函数自己的时间排行（只看主循环那条线程）"""
    if not sel:
        return ["（没有轮）"]
    t0, t1 = sel[0]["t0_us"], sel[-1]["t1_us"]
    own, idle, skipped = _steps.self_times(ln["lr"], ln["loop"]["tid"], t0, t1)
    tot = max(t1 - t0, 1)
    lines = [f"时间花在哪（#{sel[0]['k']}–#{sel[-1]['k']}，{out.dur(tot)}；自己的时间 = 时长减去它调的仓库函数）："]
    for b, us in own.most_common(10):
        node = label(keys[b])
        lines.append(f"  {out.dur(us):>10}  {us / tot:4.0%}  {common.short(node)}  {node.partition('#')[0]}")
    lines.append(f"  {out.dur(idle):>10}  {idle / tot:4.0%}  （没有仓库函数在跑：仓库外的代码或在等）")
    if skipped:
        lines.append("  （挂起过的 async 调用时长含挂起，没算进来）")
    if not r.run.get("gpu"):
        lines.append("提示  这个 run 没录 GPU：模型在 GPU 上的时间算在发起它的 Python 函数的「自己的时间」里；"
                     "要分开看用 trace --gpu 重录（record，先问用户）")
    return lines
