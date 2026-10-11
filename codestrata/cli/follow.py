"""codestrata links --follow：顺着交接走一条链（走法在 chain.py，--link 的候选在 chainhint.py），渲染成文字 / JSON。
走出来的链是一个段：几片时间 × 经过的列，带 REF（可以直接 view）。几片的 REF 给进来时按整段走（common.span）。"""
from __future__ import annotations

from .. import chain as _chain
from .. import chainhint as _chainhint
from .. import lanes as _lanes
from .. import linkgroups as _linkgroups
from .. import ref as _ref
from .. import runs as _runs
from .. import segments as _seg
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

_STAY = {"ancestor": "就在这次调用里", "round": "这一轮里交出", "order": "按先后配", "time": "按时间接"}


def run(a, c: common.Ctx, idx: dict) -> out.Result:
    common.refuse_old(c)
    r = c.res
    lo, hi, _, _ = common.span(c, "links --follow ")
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, None)       # 只要 keymap（录制之后改过的文件）：和页面认同一个函数
    try:
        A = _seg.analyse(r.rd, lo, hi, head_window=common.head_window(c))
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    W = _chain.Walker(A, _lanes.EndFns(idx, r.rd, hot), lo, hi)
    links = [W.link(t) for t in a.link]
    pos, start = W.start(a.follow, r.lanes)
    ch = W.walk(pos, links, (start["t0_us"], start["t1_us"]))
    hops, st = ch["hops"], ch["stop"]
    if st["reason"] == "none":
        st["candidates"] = _chainhint.hints(W, ch["at"], ch["seen"])
    ref = _ref.join(r.run["id"], "t=" + ",".join(f"{x}-{y}" for x, y in ch["slices_us"]), ch["lanes"])
    used = {h["link"] for h in hops if h["kind"] == "link"}
    warns = list(c.warnings) + _warnings(hops, links, used, W)
    nxt = []
    if st["reason"] == "range":                      # 出了这段时间：起点换成不随范围变的写法，范围放宽到它所在的阶段（没有就整个 run）
        wider = next((nm for nm, x, y in _seq.phase_segments(r.run, r.end_us or st["t_us"] + 1) if x <= st["t_us"] <= y), None)
        nxt.append(c.cmd("read", "links", _ref.join(r.run["id"], wider), "--follow", start["stable"],
                         *[x for t in a.link for x in ("--link", t)], why="放宽范围接着走（起点同一处）"))
    nxt.append(c.cmd("page", "view", "set", ref, "--note", f"链：{a.follow}",
                     why="在页面上看这几片里这几列（画的是全部连线，不只是这条链）"))
    total = hops[-1]["to"]["t_us"] - start["t0_us"] if hops else 0
    data = {"chain": {"start": start, "hops": hops, "stop": st, "total_us": total, "tally": _tally(hops),
                      "links": [{"text": L.text, "a": {"lane": W.alias(L.a.lane), "fn": L.a.node, "n": len(L.a.calls)},
                                 "b": {"lane": W.alias(L.b.lane), "fn": L.b.node, "n": len(L.b.calls)}, "used": L.text in used}
                                for L in links],
                      "segment": {"kind": "chain", "slices_us": ch["slices_us"], "lanes": ch["lanes"], "ref": ref}}}
    return out.Result(data=data, text=_lines(ch, start, lo, ref), repo=c.repo, ref=c.ref_json(), next=nxt, warnings=warns,
                      algo=_chain.ALGO)


def _tally(hops: list[dict]) -> dict:
    """几跳各是怎么来的：{recorded, link, stay: {ancestor, round, order, time}}"""
    t = {"recorded": 0, "link": 0, "stay": {k: 0 for k in _STAY}}
    for h in hops:
        t[h["kind"]] += 1
        t["stay"][h["stay"]] += 1
    return t


def _warnings(hops: list[dict], links: list, used: set, W) -> list[dict]:
    ws = [{"code": "link_unused", "msg": f"--link {out.quote(L.text)} 没用上：链没走到 A 列，或者走到时这一份进来之后没调 A 函数"}
          for L in links if L.text not in used]
    ws += [{"code": "link_recorded", "msg": f"--link {out.quote(h['link'])} 这一跳其实录到了（{out.quote(h['recorded_too'])}），可以不给；给了就按 --link 配"}
           for h in hops if h.get("recorded_too")]
    ws += [{"code": "mixed_inputs", "msg": f"第 {i} 跳：{h['from']['lane']} 从收到这一份到交出（{W.secs(h['from']['t_us'])}）之间还收到了别的 "
                                           f"{h['mixed']['n']} 份（{'、'.join(h['mixed']['groups'][:3])}）：交出的不一定只是这一份"}
           for i, h in enumerate(hops, 1) if h.get("mixed")]
    return ws


def _gap(us: int) -> str:
    """跳之间隔了多久：不到 1 ms 的写 µs（交给同一个进程里的线程常常只要几十 µs）"""
    return f"{us} µs" if us < 1000 else out.dur(us)


def _stay(h: dict, first: bool) -> str:
    """在这一列里从进来到交出是怎么接上的"""
    if h["kind"] == "link":
        return "  ← 收到的那一处就在这次调用里" if h["stay"] == "ancestor" else "  ← 收到之后第一次调它（inferred: time）"
    if h["stay"] == "ancestor":
        return "  ← 就在这次调用里"
    if h["stay"] == "round":
        return "  ← 这一轮里交出（按时刻归轮）"
    if h["stay"] == "order":
        return f"  ← 第 {h['stay_k']} 份配这一组的第 {h['stay_k']} 次交出（inferred: order）"
    return f"  ← {'起点' if first else '收到'}之后第一次交出（inferred: time）"


def _lines(ch: dict, s: dict, lo: int, ref: str) -> list[str]:
    hops, st = ch["hops"], ch["stop"]
    if s["kind"] == "call":
        what = f"{s['lane']} 上 {common.short(s['fn'])} 的第 {s['k']} 次（{out.secs(s['t0_us'], lo)}" + (
            f"；这一列的第 {s['k_lane']} 次）" if s["k_lane"] != s["k"] else "）")
    elif s["kind"] == "round":
        what = f"{s['lane']} 的第 {s['k']} 轮（{out.secs(s['t0_us'], lo)}）"
    else:
        what = f"{s['lane']} 在 {out.secs(s['t0_us'], lo)} 收到的" + (f"（{s['group']}）" if s.get("group") else "")
    t = _tally(hops)
    end = hops[-1]["to"] if hops else None
    head = f"链：从 {what}走了 {len(hops)} 跳"
    if hops:
        head += f"（录到 {t['recorded']}、--link {t['link']}），到 {end['lane']}（{out.secs(end['t_us'], lo)}），共 {_gap(end['t_us'] - s['t0_us'])}"
        head += "。在列里从进来到交出：" + "、".join(f"{_STAY[k]} {n}" for k, n in t["stay"].items() if n)
    L = [head + f"。时刻从这一段开头（t={lo}）算；起点不随范围变的写法 {out.quote(s['stable'])}"]
    for i, h in enumerate(hops, 1):
        a, b = h["from"], h["to"]
        if h["kind"] == "link":
            L.append(f"  {i}. {out.secs(a['t_us'], lo)}  {a['lane']}  {common.short(a['fn'])} 第 {h['k']} 次{_stay(h, i == 1)}")
            L.append(f"       ─ --link · 第 {h['k']} 次配第 {h['k']} 次（两边各 {h['n']} 次）· inferred: order · 隔 {_gap(b['t_us'] - a['t_us'])} →")
            L.append(f"     {out.secs(b['t_us'], lo)}  {b['lane']}  {common.short(b['fn'])} 第 {h['k']} 次")
        else:
            va, vb = _linkgroups.verbs(h["via"])
            L.append(f"  {i}. {out.secs(a['t_us'], lo)}  {a['lane']}  {va} {common.end_text(a)}{_stay(h, i == 1)}")
            L.append(f"       ─ {h['via']} · 录到（这一组 ×{h['n']} 里的第 {h['k']} 次）· 收到比交出晚 {_gap(b['t_us'] - a['t_us'])} →")
            L.append(f"     {out.secs(b['t_us'], lo)}  {b['lane']}  {vb} {common.end_text(b)}")
        if h.get("mixed"):
            L.append(f"       ⚠ 收到这一份到交出之间，{a['lane']} 还收到了别的 {h['mixed']['n']} 份：交出的不一定只是这一份")
    if st["reason"] == "none":
        L += _stop_none(st, lo)
    elif st["reason"] == "range":
        L.append(f"停下：{st['lane']} 收到的那一刻（{out.secs(st['t_us'], lo)}）已经出了这段时间（下一步给了放宽范围的命令，起点写法不变）")
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
    if not cd["a"]["pick"]:
        L.append("    A 边没有一份一次的函数：按先后配不了，B 边不列")
        return L
    if not cd["b"]:
        L.append(f"    别的列里没有和 {common.short(cd['a']['pick'])} 次数一样、先后配得上的函数（可能是攒批：几份合成一次，或者一份拆成几次）")
        return L
    L.append(f"    B 边（所有列里和 A 边的 {common.short(cd['a']['pick'])} 第 k 次配第 k 次配得上的；交替 = 每一份处理完才来下一份）：")
    for x in cd["b"]:
        L.append(f"      {x['lane']}{'（链上走过）' if x['on_chain'] else ''}：" + "、".join(
            f"{common.short(f['fn'])}（隔 {_gap(f['gap_us'])}，波动 {f['cv']:.0%}{'，交替' if f['alternate'] else ''}"
            + (f"；同一处还有 {len(f['same'])} 个" if f["same"] else "") + "）" for f in x["fns"]))
    L.append(f"    比如 --link {out.quote(cd['link'])}（读过代码确认再加；这条不放进下一步）")
    return L
