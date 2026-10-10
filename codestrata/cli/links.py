"""codestrata links：列之间谁交给谁、谁起了谁、谁等到了谁，按（种类, 通道, 起列, 终列）合成组，两头的函数和那一行。
连线来自 lanes.build（和页面的分列是同一套）；组的写法 `l:种类|通道|起列|终列` 以后 view / explain 也认。"""
from __future__ import annotations

from .. import lanes as _lanes
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "links"
EFFECT = "read"
DOES = "列之间谁交给谁（handoff）、谁起了谁（spawn）、谁等到了谁（join）、谁启动了 kernel（launch）：合成组，两头的函数和那一行"
USAGE = "codestrata links REF [--kind handoff|spawn|join|launch|all] [--list] [--limit N] [--json]"
EXAMPLE = "codestrata links 20261001-170349-run_single_prompt@serving"

KINDS = ("handoff", "spawn", "join", "launch")
# 两头各叫什么：放 / 取、发 / 收……
_VERB = {"queue": ("放", "取"), "asyncio": ("放", "取"), "janus": ("放", "取"), "zmq": ("发", "收"),
         "thread": ("起", "线程入口"), "exec": ("起", "子进程"), "fork": ("fork", "子进程"),
         "join": ("被等的", "等到"), "wait": ("被等的", "等到"), "cuda": ("启动", "kernel")}


def add_args(p) -> None:
    p.add_argument("ref", metavar="REF", help="RUN@范围[/列]，或页面地址；给了列就只看一头在这些列里的")
    p.add_argument("--kind", default="handoff", choices=KINDS + ("all",), help="哪种连线（默认 %(default)s）")
    p.add_argument("--list", action="store_true", help="每组下面列出两头的函数对（每组最多 8 对）")
    p.add_argument("--limit", type=int, default=20, help="最多列几组（默认 %(default)s）")


def run(a) -> out.Result:
    c = common.context(a)
    common.require_events(c)
    r = c.res
    idx = common.index(c)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None, proc_order=common.proc_order(c, common.labeler(idx)))
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    aliases = _lanes.run_aliases(r.rd, [ln for ln in b["lanes"] if ln.get("gpu")])
    want = None
    if r.lanes:
        from .. import laneid as _laneid
        want = set(_laneid.select(r.lanes, aliases))
    groups: dict[tuple, dict] = {}
    for lk in b["links"]:
        if a.kind != "all" and lk["kind"] != a.kind or lk.get("out"):
            continue
        fa, ta = aliases.get(lk["from"]["lane"], lk["from"]["lane"]), aliases.get(lk["to"]["lane"], lk["to"]["lane"])
        if want is not None and lk["from"]["lane"] not in want and lk["to"]["lane"] not in want:
            continue
        g = groups.setdefault((lk["kind"], lk["via"], fa, ta), {
            "id": f"l:{lk['kind']}|{lk['via']}|{fa}|{ta}", "kind": lk["kind"], "via": lk["via"], "from": fa, "to": ta,
            "n": 0, "first_us": lk["first"], "last_us": lk["last"], "cross": lk["from"]["lane"].partition(":")[0] != lk["to"]["lane"].partition(":")[0],
            "members": []})
        g["n"] += lk["n"]
        g["first_us"] = min(g["first_us"], lk["first"])
        g["last_us"] = max(g["last_us"], lk["last"])
        g["members"].append(lk)
    gs = sorted(groups.values(), key=lambda g: g["first_us"])
    lo = r.slices[0][0] if r.slices else 0
    cross = sum(1 for g in gs if g["cross"])
    what = "全部种类的" if a.kind == "all" else f"{a.kind} "
    lines = [f"{what}连线 {len(gs)} 组（跨进程 {cross}，进程内 {len(gs) - cross}）。时刻从这一段开头（t={lo}）算"]
    data = []
    for g in gs:
        top = max(g["members"], key=lambda lk: lk["n"])
        va, vb = _VERB.get(g["via"], ("从", "到"))
        ends = {"from": _end(top["from"]), "to": _end(top["to"])}
        data.append({k: v for k, v in g.items() if k != "members"} | {"ends": ends,
                     "pairs": [{"from": _end(lk["from"]), "to": _end(lk["to"]), "n": lk["n"]} for lk in g["members"]]})
    for g, d in list(zip(gs, data))[:a.limit]:
        va, vb = _VERB.get(g["via"], ("从", "到"))
        rng = out.secs(g["first_us"], lo) + (f" → {out.secs(g['last_us'], lo)}" if g["last_us"] != g["first_us"] else "")
        lines.append(f"  {out.quote(g['id'])}  ×{g['n']}  {rng}")
        lines.append(f"      {va} {_where(d['ends']['from'])}  →  {vb} {_where(d['ends']['to'])}")
        if a.list:
            for pr in d["pairs"][:8]:
                lines.append(f"        ×{pr['n']:<5} {_where(pr['from'])} → {_where(pr['to'])}")
    more = None
    if len(gs) > a.limit:
        more = {"shown": a.limit, "total": len(gs), "how": out.command("links", r.full, "--kind", a.kind, "--limit", str(len(gs)),
                                                                       repo=c.flag)}
    nxt = [c.cmd("read", "segments", r.text, why="按功能切段：每个进程干活的那一段")] if a.kind == "handoff" else []
    return out.Result(data={"links": data, "kind": a.kind}, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, more=more,
                      warnings=c.warnings)


def _end(e: dict) -> dict:
    """连线的一头：{fn: 节点, file, line, outside: 放 / 取在仓库外的代码里}"""
    fn = e.get("fn")
    return {"fn": fn, "file": (fn or "").partition("#")[0] or None, "line": e.get("line") or None, "outside": bool(e.get("ext"))}


def _where(e: dict) -> str:
    if not e["fn"]:
        return "（仓库外的代码）"
    loc = f"{e['file']}:{e['line']}" if e["line"] else e["file"]
    return f"{common.short(e['fn'])}（{loc}）" + ("，经仓库外的代码" if e["outside"] else "")
