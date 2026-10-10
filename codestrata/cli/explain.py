"""codestrata explain：讲一条连线或一个函数——是什么、两头的代码原文、定义、调用链、之前最近收到的交接、scan 的说法。
只给原料，「为什么」由 agent 读代码后说。页面上的编号（24）要按页面的视图算，阶段 C 起才认。"""
from __future__ import annotations

import re

from .. import explain as _explain
from .. import funcref as _funcref
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "explain"
EFFECT = "read"
DOES = "讲一条连线（'l:handoff|通道|起列|终列'）或一个函数：是什么、两头的代码原文和所在分支、定义、调用链、之前最近收到的交接；只给原料"
USAGE = "codestrata explain 东西 REF [--json]"
EXAMPLE = "codestrata explain 'l:handoff|janus|end2end/orchestrator|end2end/MainThread' 20261001-170349-run_single_prompt@t=79600000-81800000"

_NUM = re.compile(r"^#?\d+$")


def add_args(p) -> None:
    p.add_argument("item", metavar="东西", help="连线 'l:种类|通道|起列|终列'（加引号）、函数（路径#限定名、限定名）；页面上的编号要阶段 C 起")
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN@范围，或页面地址（加单引号）")
    p.add_argument("--in", dest="in_", default=None, metavar="REF", help="同 REF（写在后面更清楚时用）")


def run(a) -> out.Result:
    if a.ref is None and a.in_ is None and (a.item.startswith("http") or "@" in a.item):
        raise CodestrataError("usage", "explain 要先写讲什么（连线、函数），再写 REF；只给了一个 REF")
    a.ref = a.in_ or a.ref
    if _NUM.match(a.item):
        raise CodestrataError("need_view", f"编号 {a.item} 要按页面上的那个视图算（哪些列、开没开时间顺序）：请用户把浏览器地址栏整个复制过来；"
                              "现在先用 codestrata links 看连线的写法，再 explain 'l:…'")
    c = common.context(a)
    common.require_events(c)
    r = c.res
    lo, hi = r.slices[0][0], r.slices[-1][1]
    idx = common.index(c)
    label = common.labeler(idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    if a.item.startswith("l:"):
        d = _explain.link(c.repo, r.rd, idx, hot, a.item, lo, hi, label)
        lines = _link_text(d, lo)
        nxt = [c.cmd("read", "links", f"{r.run['id']}@t={max(lo, d['from']['t_us'] - 2000)}-{min(hi, d['from']['t_us'] + 2000)}",
                     why="这一刻前后 4 ms 里的交接")]
    else:
        keys = _seq.span_index(r.rd)["keys"]
        node, ids = _funcref.resolve(a.item, keys, label)
        d = _explain.function(c.repo, r.rd, r.run, idx, hot, node, ids, lo, hi, label, r.phase)
        lines = _fn_text(d, lo)
        nxt = []
        if d["lanes"]:
            nxt.append(c.cmd("read", "path", f"{r.text}/{d['lanes'][0]['lane']}", "--limit", "40", why="它所在那一列的调用树"))
    c.warnings += _stale(c, r, d)
    return out.Result(data=d, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=c.warnings)


def _stale(c, r, d) -> list[dict]:
    """录制之后改过的文件：行号按函数挪过，原文可能对不上"""
    files = set()
    for e in (d.get("from"), d.get("to")):
        if e and e.get("def"):
            files.add(e["def"]["file"])
    if d.get("def"):
        files.add(d["def"]["file"])
    try:
        fs = _runs.file_state(c.repo, common.index(c), _runs.read_detail(r.rd))
    except (OSError, ValueError):
        return []
    bad = sorted(f for f in files if fs.get(f) in ("changed", "gone"))
    return [{"code": "stale", "msg": f"这些文件录制之后改过，原文可能和录的时候对不上：{'、'.join(bad)}"}] if bad else []


def _code(e: dict | None, indent: str = "    ") -> list[str]:
    if not e:
        return []
    out_ = [f"{indent}{e['text']}"] if e.get("text") else []
    if e.get("branch"):
        out_.append(f"{indent}所在分支（原文）  {e['branch']['line']}  {e['branch']['text']}")
    return out_


def _def(dd: dict | None, indent: str = "    ") -> list[str]:
    if not dd:
        return []
    out_ = [f"{indent}定义  {dd['signature'] or '?'}  {dd['file']}:{dd['line']}"]
    if dd.get("doc"):
        out_.append(f'{indent}      "{dd["doc"]}"')
    return out_


def _chain(ch: list[dict]) -> str:
    return " → ".join(common.short(x["fn"]) for x in ch) or "（不在任何仓库函数里：经仓库外的代码）"


def _link_text(d: dict, lo: int) -> list[str]:
    a, b = d["from"], d["to"]
    va, vb = {"zmq": ("发", "收")}.get(d["via"], ("放", "取"))
    L = [f"连线 {out.quote(d['item'])}：这段时间里 {d['n']} 次；第一次 {out.secs(a['t_us'], lo)}（t={a['t_us']}），"
         f"{out.secs(b['t_us'], lo)} 收到。时刻从这一段开头（t={lo}）算"]
    for verb, e in ((va, a), (vb, b)):
        where = f"{e['code']['file']}:{e['code']['line']}" if e.get("code") else "（仓库外的代码）"
        L.append(f"{verb}  {e['lane']}  {common.short(e['fn']) if e['fn'] else '？'}  {where}")
        L += _code(e.get("code"))
        L += _def(e.get("def"))
    L.append("前后发生了什么（运行时）")
    L.append(f"  {va}的一头的调用链  {_chain(a['chain'])}")
    rh = d.get("recent_handoff")
    if rh:
        L.append(f"  之前最近收到的交接（inferred: time，只是时间上最近）  {out.dur(rh['ago_us'])} 前，{rh['from']} 经 {rh['via']} 交来"
                 f"（t={rh['sent_us']} 发、{rh['received_us']} 收到）")
    if d.get("take_calls"):
        L.append(f"  {vb}的一头  {b['lane']} 在这段时间里调 {common.short(b['fn'])} {d['take_calls']} 次，这一次取到了")
    sc = d.get("scan") or {}
    says = []
    for side, verb in (("from", va), ("to", vb)):
        x = sc.get(side)
        if x and x.get("status"):
            says.append(f"{verb}的函数：" + ("代码里看不出会调到它" if x["status"] == "trace" else "代码里写明的调用"))
    if says:
        L.append("  scan 的说法  " + "；".join(says))
    return L


def _fn_text(d: dict, lo: int) -> list[str]:
    L = [f"函数 {d['item']}。时刻从这一段开头（t={lo}）算"]
    L += _def(d.get("def"), "  ")
    if d["lanes"]:
        L.append("这段时间里  " + "；".join(f"{x['lane']} ×{x['n']}（{out.secs(x['first_us'], lo)} → {out.secs(x['last_us'], lo)}）"
                                         for x in d["lanes"][:4]))
    else:
        L.append("这段时间里没调到它")
    for title, xs in (("谁调它", d["callers"]), ("它调谁", d["callees"])):
        if xs:
            L.append(title)
            for x in xs:
                ln = "、".join(map(str, x["lines"]))
                L.append(f"  ×{x['n']:<6} {common.short(x['fn'])}" + (f"  行 {ln}" if ln else "")
                         + ("  [代码里看不出]" if x["status"] == "trace" else ""))
    f = d.get("first")
    if f:
        L.append(f"第一次  {out.secs(f['t_us'], lo)} 在 {f['lane']}：{_chain(f['chain'])}")
        rh = d.get("recent_handoff")
        if rh:
            L.append(f"  之前最近收到的交接（inferred: time，只是时间上最近）  {out.dur(rh['ago_us'])} 前，{rh['from']} 经 {rh['via']} 交来")
    return L
