"""codestrata links：列之间谁交给谁、谁起了谁、谁等到了谁，按（种类, 通道, 起列, 终列）合成组，两头的函数和那一行。
连线来自 lanes.build（和页面的分列是同一套），合组在 linkgroups（explain 讲的是同一份）；组的写法 `l:种类|通道|起列|终列`。
一组里两头的（函数, 行）有几种时，默认写次数最多的那种，--list 全列（explain 用 #k 挑）。
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
DOES = "列之间谁交给谁（handoff）、谁起了谁（spawn）、谁等到了谁（join）、谁启动了 kernel（launch）：合成组，两头的函数和那一行"
USAGE = ("codestrata links REF [--kind handoff|spawn|join|launch|all] [--list] [--limit N] "
         "[--follow 起点 [--link 'A列:FN => B列:FN' …]] [--json]")
EXAMPLE = "codestrata links 20261001-170349-run_single_prompt@serving"

KINDS = ("handoff", "spawn", "join", "launch")


def add_args(p) -> None:
    p.add_argument("ref", metavar="REF", help="RUN@范围[/列]，或页面地址；给了列就只看一头在这些列里的")
    p.add_argument("--kind", default="handoff", choices=KINDS + ("all",), help="哪种连线（默认 %(default)s）")
    p.add_argument("--list", action="store_true", help="每组下面列出两头的（函数, 行）有哪几种（每组最多 8 种；explain '组#k' 讲第 k 种）")
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
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    ends = {} if a.follow else None
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None, proc_order=common.proc_order(c, common.labeler(idx)), ends=ends)
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    if a.follow:
        return follow.run(a, c, idx, ends)
    aliases = _lanes.aliases_of(r.rd, b)
    want = None
    if r.lanes:
        from .. import laneid as _laneid
        want = set(_laneid.select(r.lanes, aliases))
    gs = _linkgroups.groups(b, aliases, a.kind, want)
    lo = r.slices[0][0] if r.slices else 0
    cross = sum(1 for g in gs if g["cross"])
    what = "全部种类的" if a.kind == "all" else f"{a.kind} "
    lines = [f"{what}连线 {len(gs)} 组（跨进程 {cross}，进程内 {len(gs) - cross}）。时刻从这一段开头（t={lo}）算"]
    data = [{k: v for k, v in g.items() if k != "members"} for g in gs]
    for d in data[:a.limit]:
        va, vb = _linkgroups.verbs(d["via"])
        rng = out.secs(d["first_us"], lo) + (f" → {out.secs(d['last_us'], lo)}" if d["last_us"] != d["first_us"] else "")
        kinds = f"，两头有 {d['n_pairs']} 种" if d["n_pairs"] > 1 else ""
        lines.append(f"  {out.quote(d['id'])}  ×{d['n']}  {rng}{kinds}")
        top = d["pairs"][0] if d["pairs"] else None
        if top:
            lines.append(f"      {va} {common.end_text(top['from'])}  →  {vb} {common.end_text(top['to'])}" + (f"  （最多的一种，×{top['n']}）" if kinds else ""))
        if a.list and len(d["pairs"]) > 1:
            for k, pr in enumerate(d["pairs"][:8], 1):
                lines.append(f"        #{k} ×{pr['n']:<5} {common.end_text(pr['from'])} → {common.end_text(pr['to'])}")
    more = None
    if len(gs) > a.limit:
        more = {"shown": a.limit, "total": len(gs), "how": out.command("links", r.full, "--kind", a.kind, "--limit", str(len(gs)),
                                                                       repo=c.flag)}
    nxt = [c.cmd("read", "segments", r.text, why="按功能切段：每个进程干活的那一段")] if a.kind == "handoff" else []
    return out.Result(data={"links": data, "kind": a.kind}, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, more=more,
                      warnings=c.warnings)
