"""codestrata links：列之间谁把数据交给谁，按（通道, 起列, 终列）合成组、按第一次的先后排，两头的函数和那一行。
连线来自 lanes.build（和页面的分列是同一套），合组在 linkgroups；一组里两头的（函数, 行）有几种时写次数最多的那种。
--follow 顺着交接走一条链（cli/follow.py、chain.py）。"""
from __future__ import annotations

from .. import lanes as _lanes
from .. import linkgroups as _linkgroups
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, follow, out

NAME = "links"
EFFECT = "read"
DOES = "列之间谁把数据交给谁：按第一次的先后排，两头的函数和那一行；--follow 顺着交接走一条链"
USAGE = "codestrata links REF [--limit N] [--follow 起点 [--link 'A列:FN => B列:FN' …]] [--json]"
EXAMPLE = "codestrata links 20261001-170349-run_single_prompt@serving"

def add_args(p) -> None:
    p.add_argument("ref", metavar="REF", help="RUN@范围[/列]，或页面地址；给了列就只看一头在这些列里的")
    p.add_argument("--limit", type=int, default=20, help="最多列几组（默认 %(default)s）")
    p.add_argument("--follow", default=None, metavar="起点",
                   help="顺着交接走一条链：列#k（主循环第 k 轮）、FN#k（这段时间里第 k 次调用 FN）、列:FN#k（只数这一列的）")
    p.add_argument("--link", action="append", default=[], metavar="'A列:FN => B列:FN'",
                   help="接上一跳没录到的交接：这段时间里 A 边第 k 次调用配 B 边第 k 次（按先后，inferred: order），可以给几次；要和 --follow 一起用")


def run(a) -> out.Result:
    if a.link and not a.follow:
        raise CodestrataError("usage", "--link 要和 --follow 一起用（--follow 起点，见 codestrata links --help）")
    c = common.context(a)
    common.require_events(c)
    r = c.res
    idx = common.index(c)
    if a.follow:                                     # 链不用建分列：交接两头的函数按 lanes.EndFns 认（和分列同一份）
        return follow.run(a, c, idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None, proc_order=common.proc_order(c, common.labeler(idx)))
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    aliases = _lanes.run_aliases(r.rd)
    want = None
    if r.lanes:
        from .. import laneid as _laneid
        want = set(_laneid.select(r.lanes, aliases))
    gs = _linkgroups.groups(b, aliases, "handoff", want)
    lo = r.slices[0][0] if r.slices else 0
    cross = sum(1 for g in gs if g["cross"])
    lines = [f"交接 {len(gs)} 组（跨进程 {cross}，进程内 {len(gs) - cross}），按第一次的先后。时刻从这一段开头（t={lo}）算"]
    data = [{k: v for k, v in g.items() if k != "members"} for g in gs]
    for d in data[:a.limit]:
        va, vb = _linkgroups.verbs(d["via"])
        rng = out.secs(d["first_us"], lo) + (f" → {out.secs(d['last_us'], lo)}" if d["last_us"] != d["first_us"] else "")
        kinds = f"，两头有 {d['n_pairs']} 种，这是最多的一种" if d["n_pairs"] > 1 else ""
        lines.append(f"  {rng}  {d['via']}  {d['from']} → {d['to']}  ×{d['n']}{kinds}")
        top = d["pairs"][0] if d["pairs"] else None
        if top:
            lines.append(f"      {va} {common.end_text(top['from'])}  →  {vb} {common.end_text(top['to'])}")
    more = None
    if len(gs) > a.limit:
        more = {"shown": a.limit, "total": len(gs), "how": out.command("links", r.full, "--limit", str(len(gs)), repo=c.flag)}
    return out.Result(data={"links": data}, text=lines, repo=c.repo, ref=c.ref_json(), more=more, warnings=c.warnings)
