"""codestrata find：按名字找函数 / 类 / 文件 / 目录，给出在这段时间里被调了几次、在哪几列跑过、落在默认切面的哪个节点。"""
from __future__ import annotations

from .. import finder as _finder
from .. import lanes as _lanes
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "find"
EFFECT = "read"
DOES = "按名字找函数 / 类 / 文件 / 目录（不分大小写，支持 *）：这段时间里被调了几次、在哪几列跑过；默认只列跑过的"
USAGE = "codestrata find 文字 [REF] [--kind fn|class|file|dir] [--under 目录] [--all] [--limit N] [--json]"
EXAMPLE = "codestrata find tts 20261001-170349-run_single_prompt@serving --kind class"


def add_args(p) -> None:
    p.add_argument("text", metavar="文字", help="名字的一部分；带 * 时按通配（加引号）")
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN[@范围][/列]，或页面地址；不给就只按名字找")
    p.add_argument("--kind", choices=_finder.KINDS, default=None, help="只找这一种")
    p.add_argument("--under", default=None, metavar="目录", help="只找这个目录下面的")
    p.add_argument("--all", action="store_true", help="没跑过的也列（默认只列这段时间里跑过的）")
    p.add_argument("--limit", type=int, default=20, help="最多列几个（默认 %(default)s）")


def run(a) -> out.Result:
    c = common.context(a, need_run=False)
    idx = common.index(c)
    found = _finder.match(idx, a.text, a.kind, a.under)
    r = c.res
    per_node = None
    note = None
    if r is not None:
        label = common.labeler(idx)
        if r.run.get("events") and (r.rd / "events" / "spans" / "index.json").is_file():
            try:
                pc = _seq.phase_calls(r.rd, r.run, r.phase)
            except LookupError as e:
                raise CodestrataError("no_events", str(e)) from None
            aliases = _lanes.run_aliases(r.rd)
            want = None
            if r.lanes:
                from .. import laneid as _laneid
                want = set(_laneid.select(r.lanes, aliases))

            def lane_of(pid: int, tname: str) -> str:
                lid = _lanes.lane_id(pid, tname)
                return aliases.get(lid, lid) if want is None or lid in want else None
            per_node = _finder.node_counts(pc["calls"], pc["keys"], pc["threads"], label, lane_of)
            for n in per_node.values():
                n.pop(None, None)
        else:                                    # 没录时序事件：只有整个 run（或阶段）的总数，不分列
            counts = _runs.load_counts(r.rd, None if not r.phase or r.phase.startswith("t=") else r.phase)
            per_node = {}
            for k, n in (counts.get("funcs") or {}).items():
                node = label(k)
                if node:
                    per_node.setdefault(node, {}).setdefault("（不分列）", [0, None, None])[0] += n
            note = "这个 run 没录时序事件：次数是整个阶段的总数，不分列、没有时刻"
    rows = []
    for it in found:
        hits = _finder.hits_of(it, per_node) if per_node is not None else {}
        it = {**it, "lanes": [{"lane": ln, "n": v[0], "first_us": v[1], "last_us": v[2]}
                              for ln, v in sorted(hits.items(), key=lambda kv: -kv[1][0])],
              "n": sum(v[0] for v in hits.values())}
        rows.append(it)
    ran = [x for x in rows if x["n"]]
    shown_from = rows if (a.all or r is None) else ran
    shown_from.sort(key=lambda x: (x["rank"], -x["n"], len(x["name"])))
    shown = shown_from[:a.limit]
    base = r.slices[0][0] if r and r.slices else 0
    kind_word = {"fn": "函数", "class": "类", "file": "文件", "dir": "目录"}.get(a.kind, "东西")
    head = f"名字里带 {a.text!r} 的{kind_word} {len(rows)} 个"
    if r is not None:
        head += f"；这段时间里跑过 {len(ran)} 个" + ("" if a.all else "（--all 看全部）") + f"。时刻从这一段开头（t={base}）算"
    lines = [head]
    for x in shown:
        loc = f"{x['file']}:{x['line']}" if x["line"] else (x["file"] or x["key"])
        lines.append(f"  {x['name'] if x['kind'] != 'fn' else x['key'].partition('#')[2]}  [{_word(x['kind'])}]  {loc}")
        for ln in x["lanes"][:4]:
            when = f"  {out.secs(ln['first_us'], base)} → {out.secs(ln['last_us'], base)}" if ln["first_us"] is not None else ""
            lines.append(f"      {ln['lane']} ×{ln['n']}{when}")
        if len(x["lanes"]) > 4:
            lines.append(f"      …还有 {len(x['lanes']) - 4} 列")
    if note:
        c.warnings.append({"code": "no_lanes", "msg": note})
    more = None
    if len(shown_from) > len(shown):
        more = {"shown": len(shown), "total": len(shown_from),
                "how": out.command("find", a.text, *([r.full] if r else []), *(["--kind", a.kind] if a.kind else []),
                                   *(["--under", a.under] if a.under else []),
                                   *(["--all"] if a.all else []), "--limit", str(len(shown_from)), repo=c.flag)}
    nxt = []
    top = next((x for x in shown if x["kind"] in ("fn", "class")), None)
    if top and r is not None:
        nxt.append(c.cmd("read", "explain", top["key"], r.full, why="它是什么、谁调它、代码原文"))
    if r is None and found:
        c.warnings.append({"code": "no_ref", "msg": "没给 REF：只按名字找，没有次数（给一个 RUN@阶段 就有）"})
    for x in rows:
        x.pop("rank", None)
    return out.Result(data={"items": shown, "total": len(rows), "ran": len(ran)}, text=lines, repo=c.repo, ref=c.ref_json(),
                      next=nxt, more=more, warnings=c.warnings)


def _word(k: str) -> str:
    return {"fn": "函数", "class": "类", "file": "文件", "dir": "目录"}[k]
