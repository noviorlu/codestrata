"""codestrata links --follow：顺着交接走一条链（走法在 chain.py），渲染成文字 / JSON。
走出来的链是一个段：几片时间 × 经过的列，带 REF（可以直接 view）。"""
from __future__ import annotations

from .. import chain as _chain
from .. import linkgroups as _linkgroups
from .. import segments as _seg
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out


def run(a, c: common.Ctx, idx: dict, ends: dict) -> out.Result:
    """links 建好分列（ends 填好了每次交接两头的函数）之后接着走链"""
    common.refuse_old(c)
    r = c.res
    lo, hi = r.slices[0][0], r.slices[-1][1]
    try:
        A = _seg.analyse(r.rd, lo, hi, head_window=common.head_window(c))
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    W = _chain.Walker(A, ends, common.labeler(idx), lo, hi)
    links = [W.link(t) for t in a.link]
    pos, start = W.start(a.follow, r.lanes)
    ch = W.walk(pos, links, (start["t0_us"], start["t1_us"]))
    hops, st = ch["hops"], ch["stop"]
    ref = f"{r.run['id']}@t=" + ",".join(f"{x}-{y}" for x, y in ch["slices_us"]) + "/" + ",".join(ch["lanes"])
    used = {h["link"] for h in hops if h["kind"] == "link"}
    warns = list(c.warnings) + [{"code": "link_unused", "msg": f"--link {out.quote(L.text)} 没用上：链没走到 A 列，或者走到时这一份进来之后没调 A 函数"}
                                for L in links if L.text not in used]
    warns += [{"code": "link_recorded", "msg": f"--link {out.quote(h['link'])} 这一跳其实录到了（{h['recorded_too']}），可以不给；给了就按 --link 配"}
              for h in hops if h.get("recorded_too")]
    warns += [{"code": "order_differs", "msg": f"第 {i} 跳：按时间接的是 {h['from']['lane']} 这一组交出的第 {h['alt']['picked_k']} 次，按先后配（第 {h['alt']['k']} 份配第 "
                                            f"{h['alt']['k']} 次）是 t={h['alt']['t_us']} 那次：链从这里起可能接到了别的那一份"}
              for i, h in enumerate(hops, 1) if h.get("alt")]
    lines = _lines(ch, start, lo, ref)
    nxt = []
    cand = st.get("candidates") or {}
    if cand.get("link"):
        more = [x for t in [*a.link, cand["link"]] for x in ("--link", t)]
        nxt.append(c.cmd("read", "links", r.full, "--follow", a.follow, *more,
                         why="读过代码、确认数据真是这么交的之后：接上这一跳（inferred: order）"))
    nxt.append(c.cmd("page", "view", "set", ref, "--note", f"链：{a.follow}", why="在页面上只看这条链经过的列和那几片时间"))
    total = hops[-1]["to"]["t_us"] - start["t0_us"] if hops else 0
    data = {"chain": {"start": start, "hops": hops, "stop": st, "total_us": total,
                      "links": [{"text": L.text, "a": {"lane": W.alias(L.a.lane), "fn": L.a.node, "n": len(L.a.calls)},
                                 "b": {"lane": W.alias(L.b.lane), "fn": L.b.node, "n": len(L.b.calls)}, "used": L.text in used}
                                for L in links],
                      "segment": {"kind": "chain", "slices_us": ch["slices_us"], "lanes": ch["lanes"], "ref": ref}}}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=warns, algo=_chain.ALGO)


def _gap(us: int) -> str:
    """跳之间等了多久：不到 1 ms 的写 µs（交给同一个进程里的线程常常只要几十 µs）"""
    return f"{us} µs" if us < 1000 else out.dur(us)


def _stay(h: dict, first: bool) -> str:
    """在这一列里从进来到交出是怎么接上的"""
    if h["stay"] == "ancestor":
        return "  ← 就在这次调用里" if first or h["kind"] == "recorded" else "  ← 收到的那一处就在这次调用里"
    return f"  ← {'起点' if first else '收到'}之后第一次{'调它' if h['kind'] == 'link' else '交出'}（inferred: time）"


def _lines(ch: dict, s: dict, lo: int, ref: str) -> list[str]:
    hops, st = ch["hops"], ch["stop"]
    if s["kind"] == "call":
        what = f"{s['lane']} 上 {common.short(s['fn'])} 的第 {s['k']} 次（{out.secs(s['t0_us'], lo)}" + (
            f"；这一列的第 {s['k_lane']} 次）" if s["k_lane"] != s["k"] else "）")
    else:
        what = f"{s['lane']} 的第 {s['k']} 轮（{out.secs(s['t0_us'], lo)}）"
    end = hops[-1]["to"] if hops else None
    L = [f"链：从 {what}走了 {len(hops)} 跳"
         + (f"，到 {end['lane']}（{out.secs(end['t_us'], lo)}），共 {_gap(end['t_us'] - s['t0_us'])}" if end else "")
         + f"。时刻从这一段开头（t={lo}）算"]
    for i, h in enumerate(hops, 1):
        a, b = h["from"], h["to"]
        if h["kind"] == "link":
            L.append(f"  {i}. {out.secs(a['t_us'], lo)}  {a['lane']}  {common.short(a['fn'])} 第 {h['k']} 次{_stay(h, i == 1)}")
            L.append(f"       ─ --link · 第 {h['k']} 次配第 {h['k']} 次（两边各 {h['n']} 次）· inferred: order · {_gap(b['t_us'] - a['t_us'])} →")
            L.append(f"     {out.secs(b['t_us'], lo)}  {b['lane']}  {common.short(b['fn'])} 第 {h['k']} 次")
        else:
            va, vb = _linkgroups.verbs(h["via"])
            L.append(f"  {i}. {out.secs(a['t_us'], lo)}  {a['lane']}  {va} {common.end_text(a)}{_stay(h, i == 1)}")
            if h.get("alt"):
                L.append(f"       ⚠ 这一组交出的次数和进来的份数一样（{h['alt']['n']}）：按先后配，第 {h['alt']['k']} 份该配第 {h['alt']['k']} 次交出"
                         f"（{out.secs(h['alt']['t_us'], lo)}），不是这一次——可能接到了别的那一份")
            L.append(f"       ─ {h['via']} · 录到（这一组 ×{h['n']} 里的第 {h['k']} 次）· {_gap(b['t_us'] - a['t_us'])} →")
            L.append(f"     {out.secs(b['t_us'], lo)}  {b['lane']}  {vb} {common.end_text(b)}")
    if st["reason"] == "none":
        L += _stop_none(st, lo)
    elif st["reason"] == "range":
        L.append(f"停下：{st['lane']} 收到的那一刻（{out.secs(st['t_us'], lo)}）已经出了这段时间；放宽 REF 的范围再走")
    else:
        L.append(f"停下：走了 {_chain.MAX_HOPS} 跳还没停，截在 {st['lane']}（{out.secs(st['t_us'], lo)}）")
    L.append(f"这条链的段（{len(ch['slices_us'])} 片时间 × 经过的 {len(ch['lanes'])} 列）：{out.quote(ref)}")
    return L


def _stop_none(st: dict, lo: int) -> list[str]:
    until = f"、同一路下一份进来（{out.secs(st['until_us'], lo)}）之前" if st["until_us"] else ""
    L = [f"停下：{st['lane']} {out.secs(st['t_us'], lo)} 进来之后{until}没再交给别的列（录到的），也没有用得上的 --link"]
    no = st["next_out"]
    if no:
        L.append(f"  这一列下一次交出：{out.secs(no['t_us'], lo)} 经 {no['via']} 到 {no['to']}" + ("（已经出了这段时间）" if no["after_range"] else "")
                 + "——不一定是同一份数据（inferred: time），没往下走")
    else:
        L.append("  之后这一列再没交给别的列（录到的）")
    cd = st["candidates"]
    L.append("  如果走的是没录到的通道（共享的 dict / deque、管道……），读过代码确认之后加 --link 'A列:函数 => B列:函数' 接上"
             "（第 k 次配第 k 次，inferred: order）：")
    if cd["a"]["fns"]:
        L.append(f"    A 边 {cd['a']['lane']} 进来之后跑的（* 是一份一次：这一路共 {cd['a']['n_in']} 份）："
                 + "、".join(f"{common.short(x['fn'])} ×{x['n']}{'*' if x['per_item'] else ''}" for x in cd["a"]["fns"]))
    for x in cd["b"]:
        L.append(f"    B 边 {x['lane']}（{out.secs(x['first_us'], lo)} 起先跑的）："
                 + "、".join(f"{common.short(f['fn'])} ×{f['n']}{' ✓' if f['fits'] else ''}" for f in x["fns"]))
    if not cd["b"]:
        L.append("    这期间别的列都没在干活")
    if cd["link"]:
        L.append(f"    ✓ 是和 A 边的 {common.short(cd['a']['pick'])} 次数一样、每次都不早于它的。比如 --link {out.quote(cd['link'])}")
    return L
