"""codestrata explain：讲一条连线或一个函数——是什么、两头的代码原文、定义、调用链、之前最近收到的交接、scan 的说法。
只给原料，「为什么」由 agent 读代码后说。页面上的编号（24）要按页面的视图算，阶段 C 起才认。"""
from __future__ import annotations

import re

from .. import explain as _explain
from .. import funcref as _funcref
from .. import lanes as _lanes
from .. import linkgroups as _linkgroups
from .. import locate as _locate
from .. import ref as _ref
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out, pages

NAME = "explain"
EFFECT = "read"
DOES = "讲一组交接（'l:handoff|通道|起列|终列'）、一个函数或类：是什么、两头的代码原文和所在分支、定义、调用链、之前最近收到的交接；只给原料"
USAGE = "codestrata explain 东西 REF [--json]（连线 'l:…' 可加 #k 讲组里第 k 种两头；页面上的编号：explain 24 '<页面地址>'，地址里要有 order=1）"
EXAMPLE = "codestrata explain 'l:handoff|janus|end2end/orchestrator|end2end/MainThread' 20261001-170349-run_single_prompt@t=79600000-81800000"

_NUM = re.compile(r"^#?\d+$")


def add_args(p) -> None:
    p.add_argument("item", nargs="?", default=None, metavar="东西",
                   help="连线 'l:种类|通道|起列|终列[#k]'（加引号）、函数或类（路径#限定名、限定名），或页面上的编号（24，配页面地址）")
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN@范围，或页面地址（加单引号）")
    p.add_argument("--in", dest="in_", default=None, metavar="REF", help="同 REF（写在后面更清楚时用）")
    p.add_argument("--selected", action="store_true", help="讲用户在开着的页面上选中的那个（连线、列中的边、节点）；view wait 等他点")
    p.add_argument("--page", default=None, metavar="端口", help="--selected：页面在本机哪个端口（缺省按仓库找开着的）")
    p.add_argument("--tab", default=None, metavar="ID", help="--selected：哪个标签页（缺省是用户最近在看的那个）")


def run(a) -> out.Result:
    if a.selected:
        return _selected(a)
    if a.item is None:
        raise CodestrataError("usage", "explain 要写讲什么（连线、函数、类、页面上的编号），或者 --selected 讲用户在页面上选中的")
    if a.ref is None and a.in_ is None and (a.item.startswith("http") or "@" in a.item):
        raise CodestrataError("usage", "explain 要先写讲什么（连线、函数），再写 REF；只给了一个 REF")
    a.ref = a.in_ or a.ref
    c = common.context(a)
    if _NUM.match(a.item):
        return _numbered(a, c)
    common.require_events(c)
    r = c.res
    lo, hi = r.slices[0][0], r.slices[-1][1]
    idx = common.index(c)
    label = common.labeler(idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    if a.item.startswith("l:"):
        _linkgroups.parse(a.item)                    # 先查写法（写错报 usage，不用先建分列）
        d, lines = _sel(c, a.item, c.ref)
        nxt = [c.cmd("read", "links", f"{r.run['id']}@t={max(lo, d['from']['t_us'] - 2000)}-{min(hi, d['from']['t_us'] + 2000)}",
                     why="这一刻前后 4 ms 里的交接")]
    elif a.item[:2] in ("n:", "f:", "e:"):           # 页面上的选中写法（地址栏的 sel=）原样也认
        d, lines = _sel(c, a.item, c.ref)
        nxt = []
    else:
        d = _thing(c, r, idx, hot, label, a.item, lo, hi)
        lines = _node_text(d) if d.get("kind") == "node" else _fn_text(d, lo)
        nxt = []
        if d.get("lanes"):
            nxt.append(c.cmd("read", "path", f"{r.text}/{d['lanes'][0]['lane']}", "--limit", "40", why="它所在那一列的调用树"))
    c.warnings += _stale(c, r, d)
    return out.Result(data=d, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=c.warnings)


def _built(c, idx: dict, hot: dict) -> tuple[dict, dict]:
    """这个 REF 的分列（连线的两头用它认，和页面、links 同一份）和列别名"""
    r = c.res
    try:
        b = _lanes.build(idx, r.rd, r.run, r.phase, hot, None)
    except LookupError as e:
        raise CodestrataError("no_events", str(e)) from None
    except (OSError, ValueError) as e:
        raise CodestrataError("spans_unreadable", _seq.unreadable(e, r.run["id"])) from None
    return b, _lanes.aliases_of(r.rd, b)


def _thing(c, r, idx: dict, hot: dict, label, item: str, lo: int, hi: int) -> dict:
    """一个类、函数、文件或目录：类合它的方法；文件 / 目录讲里面跑过的函数；录到的键里找不到的函数退到 scan 的索引（这段时间里没跑过）"""
    syms = idx.get("symbols") or {}
    if item in (idx.get("files") or {}) or item in (idx.get("dirs") or {}):
        return _explain.node(r.rd, r.run, r.phase, label, item, None)
    cls = _funcref.resolve_symbol(item, syms, ("class",))
    if cls:
        return _explain.klass(c.repo, r.rd, r.run, idx, hot, cls, lo, hi, label, r.phase)
    keys = _seq.span_index(r.rd)["keys"]
    try:
        node, ids = _funcref.resolve(item, keys, label)
    except CodestrataError as e:
        node = _funcref.resolve_symbol(item, syms, ("func", "method", "function"))
        if e.code != "item_not_found" or node is None:
            raise
        ids = set()
    return _explain.function(c.repo, r.rd, r.run, idx, hot, node, ids, lo, hi, label, r.phase)


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
    br = e.get("branch")
    if br and br.get("kind"):
        out_.append(f"{indent}所在分支（原文）  {_branch_text(br)}")
    if br and br.get("inside"):
        out_.append(f"{indent}{'分支里' if br.get('kind') else ''}还套着  " + " · ".join(f"{x['line']} {x['text']}" for x in br["inside"]))
    for o in (br or {}).get("outer") or []:
        out_.append(f"{indent}外层分支  {_branch_text(o)}")
    return out_


def _branch_text(br: dict) -> str:
    if br["kind"] != "else":
        return f"{br['line']}  {br['text']}"
    return f"{br['line']}  else:（上面的都不成立：" + "；".join(f"{x['line']} {x['text']}" for x in br["conds"]) + "）"


def _def(dd: dict | None, indent: str = "    ") -> list[str]:
    if not dd:
        return []
    out_ = [f"{indent}定义  {dd['signature'] or '?'}  {dd['file']}:{dd['line']}"]
    if dd.get("doc"):
        out_.append(f'{indent}      "{dd["doc"]}"')
    return out_


def _chain(ch: list[dict]) -> str:
    return " → ".join(common.short(x["fn"]) for x in ch) or "（这条线程上当时没有在跑的仓库函数）"


def _where(e: dict) -> str:
    if not e["fn"]:
        return "（仓库外的代码：这条线程上没有仓库函数）"
    loc = f"{e['code']['file']}:{e['code']['line']}" if e.get("code") else (e["def"]["file"] if e.get("def") else "")
    return f"{common.short(e['fn'])}  {loc}" + ("（放 / 取在仓库外的代码里；这是当时栈底的仓库函数）" if e["outside"] else "")


def _link_text(d: dict, lo: int) -> list[str]:
    a, b = d["from"], d["to"]
    va, vb = {"zmq": ("发", "收"), "shm": ("写", "读")}.get(d["via"], ("放", "取"))
    rng = out.secs(d["first_us"], lo) + (f" → {out.secs(d['last_us'], lo)}" if d["last_us"] != d["first_us"] else "")
    L = [f"连线 {out.quote(d['item'])}：这段时间里 {d['n']} 次（{rng}）。时刻从这一段开头（t={lo}）算"]
    if len(d["kinds"]) > 1 or d["n_kinds"] > len(d["kinds"]):
        more = f"（只列了前 {len(d['kinds'])} 种）" if d["n_kinds"] > len(d["kinds"]) else ""
        L.append(f"两头的（函数, 行）有 {d['n_kinds']} 种{more}：")
        for x in d["kinds"]:
            mark = "→" if x["k"] == d["pick"] else " "
            fa_ = f"{common.short(x['from']['fn']) if x['from']['fn'] else '仓库外'}:{x['from']['line'] or '?'}"
            tb_ = f"{common.short(x['to']['fn']) if x['to']['fn'] else '仓库外'}:{x['to']['line'] or '?'}"
            L.append(f" {mark}#{x['k']} ×{x['n']:<5} {va} {fa_} → {vb} {tb_}  第一次 {out.secs(x['first_us'], lo)}")
        L.append(f"下面讲 #{d['pick']}（×{d['pick_n']}）的第一次：{out.secs(a['t_us'], lo)}（t={a['t_us']}）{va}，{out.secs(b['t_us'], lo)} {vb}到"
                 f"（换一种：explain '{d['item'].partition('#')[0]}#k' REF）")
    else:
        L.append(f"第一次 {out.secs(a['t_us'], lo)}（t={a['t_us']}）{va}，{out.secs(b['t_us'], lo)} {vb}到")
    for verb, e in ((va, a), (vb, b)):
        L.append(f"{verb}  {e['lane']}  {_where(e)}")
        if not e["outside"]:
            L += _code(e.get("code"))
        L += _def(e.get("def"))
    L.append("前后发生了什么（运行时）")
    for verb, e in ((va, a), (vb, b)):
        if e["outside"] and e["fn"] and e["chain"]:
            L.append(f"  {verb}的一头：{verb}在仓库外的代码里；当时这条线程上还没返回的仓库调用  {_chain(e['chain'])}"
                     + ("（有挂起过的 async 调用：可能是同一条线程上别的 task）" if e.get("maybe_other_task") else ""))
        elif e["outside"] and e["fn"]:              # 栈底的函数是按它调出去的调用认的，它自己没录到一行：没有链可给
            L.append(f"  {verb}的一头：{verb}在仓库外的代码里；栈底的仓库函数是 {common.short(e['fn'])}（按它调出去的调用认的），"
                     "当时它下面没有还在跑的仓库调用")
        elif e is a and not e["outside"]:
            L.append(f"  {verb}的一头的调用链  {_chain(e['chain'])}")
    rh = d.get("recent_handoff")
    if rh:
        L.append(f"  {va}之前，这条线程最近收到的交接（inferred: time，只是时间上最近）  {out.dur(rh['ago_us'])} 前，{rh['from']} 经 {rh['via']} 交来"
                 f"（t={rh['sent_us']} 发、{rh['received_us']} 收到）")
    if d.get("take_calls"):
        L.append(f"  {vb}的一头  {b['lane']} 在这段时间里调 {common.short(b['fn'])} {d['take_calls']} 次，这一次取到了")
    for side, verb in (("from", va), ("to", vb)):
        x = (d.get("scan") or {}).get(side)
        if x and x.get("status"):
            L.append(f"  scan 对「{common.short(x['caller'])} 调 {common.short(d[side]['fn'])}」（{verb}所在的函数被谁调）的说法  "
                     + ("代码里看不出会调到它" if x["status"] == "trace" else "代码里写明的调用"))
    return L


def _fn_text(d: dict, lo: int) -> list[str]:
    word = "类" if d.get("kind") == "class" else "函数"
    L = [f"{word} {d['item']}。时刻从这一段开头（t={lo}）算"]
    L += _def(d.get("def"), "  ")
    if d["lanes"]:
        L.append(("它的方法这段时间里  " if word == "类" else "这段时间里  ")
                 + "；".join(f"{x['lane']} ×{x['n']}（{out.secs(x['first_us'], lo)} → {out.secs(x['last_us'], lo)}）" for x in d["lanes"][:4]))
    else:
        L.append("这段时间里没跑过" + ("它的方法" if word == "类" else "") + "（仓库里有，scan 的索引里找到的）")
    if d.get("methods"):
        L.append("方法  " + "；".join(f"{common.short(m['fn'])} ×{m['n']}" for m in d["methods"][:8])
                 + (f"；…还有 {len(d['methods']) - 8} 个" if len(d["methods"]) > 8 else ""))
    for title, xs in (("谁调它" if word == "函数" else "谁构造它", d["callers"]), ("它调谁", d["callees"])):
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


def _numbered(a, c) -> out.Result:
    """页面上的第 N 号：按地址里的那个视图（切面、只看的列、收起、开关）算出同样的编号，再讲它"""
    from .. import viewspec as _viewspec
    n = int(a.item.lstrip("#"))
    ref = c.ref
    if ref is None or not ref.page:
        raise CodestrataError("need_view", f"编号 {n} 要按页面上的那个视图算（哪些列、收起了什么、开关）：请用户把浏览器地址栏整个复制过来，"
                              f"再 codestrata explain {n} '<地址>'")
    v = _viewspec.from_keys(ref.run, ref.lanes, ref.view)
    if not v.order:
        raise CodestrataError("need_view", "地址里的视图没开时间顺序（order=1）：页面上没有编号。请用户在页面上开「时间顺序」，再复制地址")
    common.require_events(c)
    r = c.res
    idx = common.index(c)
    label = common.labeler(idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    L, aliases, order = _viewspec.lanes_for(idx, r.rd, r.run, r.phase, hot, v, label, common.proc_order(c, label))
    if not 1 <= n <= order["n"]:
        raise CodestrataError("item_not_found", f"这个视图里一共 {order['n']} 个编号，没有 {n}",
                              candidates=[str(k) for k in range(1, min(order["n"], 10) + 1)])
    inner = next(k for k, rk in order["keys"].items() if rk == n - 1)
    lo, hi = r.slices[0][0], r.slices[-1][1]
    head = (f"按这个视图算：{r.full}" + (f" · 收起 {','.join(v.fold)}" if v.fold else "") + (f" · 藏起 {','.join(v.hide)}" if v.hide else "")
            + f" · 时间顺序开 · 共 {order['n']} 个编号；{n} 号是 {order['ids'][n - 1]}")
    if inner.startswith("l:"):
        k = L["links"][int(inner[2:])]                 # 页面上画的这一条（这两个节点之间的）：只讲它的两头
        g = _linkgroups.groups({"links": [k]}, aliases, "all")[0]
        g["id"] = order["ids"][n - 1]                  # 稳定写法带两头的节点：explain '…#k' 照着它挑，k 的编法一样
        d = _explain.link(c.repo, r.rd, idx, hot, g, None, lo, hi, label)
        lines = [head] + _link_text(d, lo)
    else:
        lid, _, rest = inner[2:].partition("|")
        a_, _, b_ = rest.partition("|")
        d = _edge_in(c, idx, L, aliases, lid, a_, b_)
        lines = [head] + _edge_text(d, lo)
    d["number"] = n
    d["view"] = {"n": order["n"], "id": order["ids"][n - 1]}
    nxt = [c.cmd("read", "links", f"{r.run['id']}@t={max(lo, (d.get('from') or {}).get('t_us', d.get('first_us') or lo) - 2000)}"
                                  f"-{min(hi, (d.get('from') or {}).get('t_us', d.get('first_us') or lo) + 2000)}", why="这一刻前后 4 ms 里的交接")]
    return out.Result(data=d, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=c.warnings)


def _edge_text(d: dict, lo: int) -> list[str]:
    L = [f"列中的边  {d['lane']}  {d['a']} → {d['b']}：这段时间里 {d['n']} 次，第一次 {out.secs(d['first_us'], lo)}"
         + ("，一直在反复（↻）" if d["repeat"] else "") + (f"；其中约 {d['only']} 次代码里看不出" if d.get("only") else "")]
    L.append("底下次数最多的几对函数：")
    for p in d["pairs"]:
        L.append(f"  ×{p['n']:<6} {common.short(p['caller'])} → {common.short(p['callee'])}"
                 + ("  [代码里看不出]" if p.get("status") == "trace" else ""))
        L += _code(p.get("code"), "      ")
        L += _def(p.get("def"), "      ")
    return L


def _edge_in(c, idx: dict, L: dict, aliases: dict, lid: str, a_: str, b_: str) -> dict:
    """分列（按某个视图算的）里一列中的一条边 → explain.edge 的原料"""
    from ..ui import load as _uiload
    ln = next((x for x in L["lanes"] if x["id"] == lid), None)
    e = next((x for x in (ln or {}).get("edges") or [] if x["a"] == a_ and x["b"] == b_), None)
    if e is None:
        raise CodestrataError("item_not_found", f"这个视图里 {aliases.get(lid, lid)} 这一列没有 {a_} → {b_} 这条边")
    lane_hot = _uiload.load_lane(c.repo, idx, c.res.text, lid)
    return _explain.edge(c.repo, idx, lane_hot, aliases.get(lid, lid), e)


def _selected(a) -> out.Result:
    """用户在开着的页面上选中的：连线（l:）、列中的边（e:）、节点 / 框（n: / f:）"""
    if a.item and not a.ref:                         # explain --selected '<页面地址>'：那是用来找页面的
        a.ref, a.item = a.item, None
    a.ref = a.in_ or a.ref
    c = common.context(a, need_run=False)
    pg = pages.find(c, a.page)
    t = pages.tab_of(pg, a.tab)
    cur = _ref.parse_fragment(t["view"] or "")
    sel = cur.view.get("sel")
    if not sel or not cur.run:
        raise CodestrataError("need_view", "页面上没选中东西：请用户点一下要问的那条线 / 那个节点，再讲（view wait 等他点）",
                              next=[c.cmd("read", "view", "wait", "--timeout", "60", why="等用户点")])
    c.ref, c.res = cur, _locate.resolve(c.repo, cur)
    c.warnings += c.res.warnings
    common.require_events(c)
    d, lines = _sel(c, sel, cur)
    d["selected"] = sel
    d["tab"] = t["tab"]
    return out.Result(data=d, text=[f"用户在页面上选中的：{sel}（{pages.where(pg, t)}；{c.res.full}）"] + lines, repo=c.repo,
                      ref=c.ref_json(), warnings=c.warnings)


def _sel(c, sel: str, ref) -> tuple[dict, list[str]]:
    """页面上选中的那种写法（l: 连线、e: 列中的边 / 模块图的边、n: / f: 节点 / 框）→ (原料, 文字)。
    列中的边按 ref（页面地址或视图）里的切面算；没给切面就是默认的"""
    from .. import viewspec as _viewspec
    r = c.res
    lo = r.slices[0][0]
    hi = r.slices[-1][1]
    idx = common.index(c)
    label = common.labeler(idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    if sel.startswith("l:"):
        built, aliases = _built(c, idx, hot)
        g, pick, cands = _linkgroups.find(built, aliases, sel)
        if g is None:
            raise CodestrataError("item_not_found", f"这段时间里没有 {sel.partition('#')[0]} 这条连线", candidates=cands[:20])
        d = _explain.link(c.repo, r.rd, idx, hot, g, pick, lo, hi, label)
        return d, _link_text(d, lo)
    rest = sel[2:]
    if sel.startswith("e:") and rest.count("|") >= 2:                     # 分列里一列中的边 e:列|a|b
        v = _viewspec.from_keys(r.text, list(getattr(ref, "lanes", []) or []), dict(getattr(ref, "view", {}) or {}))
        L, aliases, _ = _viewspec.lanes_for(idx, r.rd, r.run, r.phase, hot, v, label, common.proc_order(c, label))
        lane, a_, b_ = rest.split("|")[:3]
        lid = next((k for k, al in aliases.items() if al == lane), lane)
        d = _edge_in(c, idx, L, aliases, lid, a_, b_)
        return d, _edge_text(d, lo)
    lane, node = (rest.split("|", 1) if "|" in rest and not sel.startswith("e:") else (None, rest))
    if sel.startswith("e:"):                         # 模块图上的边 e:a|b：先讲起点那个节点里跑了什么
        node = rest.split("|")[0]
    d = _explain.node(r.rd, r.run, r.phase, label, node, lane)
    return d, _node_text(d)


def _node_text(d: dict) -> list[str]:
    where = f"（{d['lane']} 这一列里）" if d["lane"] else ""
    L = [f"节点 {d['item']}{where}：这段时间里跑过它里面的 {d['n_fns']} 个函数，共 {d['n']} 次调用"]
    for x in d["fns"]:
        L.append(f"  ×{x['n']:<6} {common.short(x['fn'])}  {x['fn'].partition('#')[0]}")
    if d["n_fns"] > len(d["fns"]):
        L.append(f"  …还有 {d['n_fns'] - len(d['fns'])} 个")
    return L
