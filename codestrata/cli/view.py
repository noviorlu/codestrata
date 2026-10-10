"""codestrata view：页面的视图描述。现在有 view url——拼出一个视图的页面地址（只看列、收起、标记、选中、展开、时间顺序…），
用户粘进页面（同一个标签页也行）就换过去，不用刷新。推给开着的页面（view set / get / back / wait）在后面的阶段。"""
from __future__ import annotations

from .. import finder as _finder
from .. import funcref as _funcref
from .. import laneid as _laneid
from .. import lanes as _lanes
from .. import seq as _seq
from .. import viewspec as _viewspec
from ..errors import CodestrataError
from ..ui import search as _search
from . import common, out

NAME = "view"
EFFECT = "read"
DOES = "页面的视图描述：view url 拼出一个视图的页面地址（只看列、收起、标记、选中、展开到函数、时间顺序），粘进页面就换过去"
USAGE = ("codestrata view url [REF|'页面地址'] [--lanes 列,…] [--fold 进程,…] [--mark 东西,…] [--expand 东西,…] [--focus 东西] "
         "[--select 东西] [--order on|off] [--hide hot,dyn|none] [--path] [--page 端口] [--json]")
EXAMPLE = "codestrata view url 20261001-170349-run_single_prompt@serving --focus MiniCPMO45OmniTTSForConditionalGeneration.sample"


def add_args(p) -> None:
    p.add_argument("action", choices=["url"], help="url：只拼地址、不推（推给开着的页面在后面的阶段）")
    p.add_argument("ref", nargs="?", default=None, metavar="REF", help="RUN@范围[/列]，或页面地址（在它的视图上改）")
    p.add_argument("--lanes", default=None, help="只看这几列（选择器，逗号隔开；all 是全部）")
    p.add_argument("--fold", default=None, help="收起这些进程（别名，逗号隔开；none 是都不收）")
    p.add_argument("--mark", default=None, help="标出这些文件 / 目录 / 函数所在的节点（逗号隔开，最多 20；none 清掉）")
    p.add_argument("--expand", default=None, help="把切面展开到这些文件 / 函数所在的文件：在它跑过的每一列里")
    p.add_argument("--focus", default=None, metavar="东西", help="简写：只看它跑过的列 + 展开 + 标出 + 选中它")
    p.add_argument("--select", default=None, metavar="东西", help="选中：n:列|节点、e:列|a|b、l:种类|通道|起列|终列，或一个函数（选它所在的文件）")
    p.add_argument("--order", choices=["on", "off"], default=None, help="时间顺序开 / 关")
    p.add_argument("--hide", default=None, help="藏起的边：hot、dyn，none 是都不藏")
    p.add_argument("--path", action="store_true", help="详情栏讲请求路径")
    p.add_argument("--page", default=None, metavar="端口", help="页面在本机哪个端口（给了就拼完整的地址）")


def run(a) -> out.Result:
    c = common.context(a)
    r = c.res
    ref = c.ref
    idx = common.index(c)
    label = common.labeler(idx)
    v = _viewspec.from_keys(None, [], ref.view) if ref.page else _viewspec.View()
    v.run = r.text
    v.lanes = list(r.lanes)
    aliases = _lanes.run_aliases(r.rd)
    procs = _lanes.proc_aliases(r.rd)
    if a.lanes is not None:
        v.lanes = [] if a.lanes == "all" else _laneid.canonical(_laneid.parse_list(a.lanes), aliases)
    if a.fold is not None:
        names = set(procs.values())
        bad = [x for x in _laneid.parse_list(a.fold) if x not in names and a.fold != "none"]
        if bad:
            raise CodestrataError("lane_not_found", f"没有这些进程：{', '.join(bad)}", candidates=sorted(names))
        v.fold = [] if a.fold == "none" else sorted(_laneid.parse_list(a.fold))
    keys = _seq.span_index(r.rd)["keys"]
    lo, hi = r.slices[0][0], r.slices[-1][1]
    ran = None                                      # 函数节点 → {列别名: [次数, 首, 末]}（--expand / --focus 要知道它在哪几列跑过）

    def where(item: str) -> tuple[str, dict]:
        """一个东西 → (标记 / 展开用的写法, 它跑过的列 {列别名: [次数, 首, 末]})"""
        nonlocal ran
        if ran is None:
            pc = _seq.phase_calls(r.rd, r.run, r.phase)
            ran = _finder.node_counts(pc["calls"], pc["keys"], pc["threads"], label,
                                      lambda pid, t: aliases.get(_lanes.lane_id(pid, t), f"{pid}:{t}"))
        if item.endswith("/") and item.rstrip("/") in (idx.get("dirs") or {}):
            kind, key = "dir", item
        elif item in (idx.get("files") or {}):
            kind, key = "file", item
        else:
            kind, key = "fn", _funcref.resolve(item, keys, label)[0]
        hits = _finder.hits_of({"kind": kind, "key": key}, ran)
        return key, {ln: x for ln, x in hits.items() if x[0]}

    marks = list(v.mark)
    if a.mark is not None:
        marks = [] if a.mark == "none" else [where(x)[0] for x in _laneid.parse_list(a.mark)]
    expand = [where(x) for x in _laneid.parse_list(a.expand)] if a.expand else []
    sel = v.sel
    if a.focus:
        key, lanes_ran = where(a.focus)
        if not lanes_ran:
            raise CodestrataError("item_not_found", f"{a.focus} 这段时间里在哪一列都没跑过：换一段时间，或者只用 --mark")
        expand.append((key, lanes_ran))
        if key not in marks:
            marks.append(key)
        if a.lanes is None:
            v.lanes = sorted(lanes_ran, key=lambda ln: list(aliases.values()).index(ln) if ln in aliases.values() else 0)
        first = min(lanes_ran, key=lambda ln: lanes_ran[ln][1])
        sel = f"n:{first}|{key.split('#')[0]}"
    for key, lanes_ran in expand:
        node = key.split("#")[0].rstrip("/") + ("/" if key.endswith("/") else "")
        base = v.cut if v.cut is not None else (idx.get("default_open") or [])
        for ln in lanes_ran:
            cur = v.lcut.get(ln, base)
            opened = _search.reveal(idx, node, cur)
            if opened is not None and sorted(opened) != sorted(cur):
                v.lcut[ln] = sorted(opened)
    if a.select:
        sel = a.select if a.select[:2] in ("n:", "e:", "f:", "l:") else None
        if sel is None:
            key, lanes_ran = where(a.select)
            if not lanes_ran:
                raise CodestrataError("item_not_found", f"{a.select} 这段时间里在哪一列都没跑过，选不中")
            sel = f"n:{min(lanes_ran, key=lambda ln: lanes_ran[ln][1])}|{key.split('#')[0]}"
    v.sel = sel
    v.mark = marks[:20]
    if a.order is not None:
        v.order = a.order == "on"
    if a.hide is not None:
        v.hide = [] if a.hide == "none" else [x for x in _laneid.parse_list(a.hide) if x in ("hot", "dyn")]
    if a.path:
        v.panel = "path"
    frag = _viewspec.fragment(v)
    prefix = None
    if ref.page:
        p = ref.page
        prefix = p["url"].split("#", 1)[0]
    elif a.page:
        prefix = f"http://127.0.0.1:{int(a.page)}/"
    url = f"{prefix}#{frag}" if prefix else f"#{frag}"
    lines = [f"地址  {out.quote(url)}"]
    what = []
    if v.lanes:
        what.append("只看 " + ",".join(v.lanes) + "（别的列每个进程收成一窄列）")
    if v.fold:
        what.append("收起 " + ",".join(v.fold))
    if v.lcut:
        what.append("展开：" + "；".join(f"{ln} 展开到 {','.join(d[-1:])}" for ln, d in sorted(v.lcut.items())))
    if v.mark:
        what.append("标记 " + "、".join(v.mark))
    if v.sel:
        what.append("选中 " + v.sel)
    if v.order:
        what.append("时间顺序开")
    lines += [f"  {x}" for x in what]
    if not prefix:
        c.warnings.append({"code": "no_page", "msg": "没给页面：把上面这一段（# 开头）粘到浏览器地址栏里页面地址的后面；"
                                                   "或者加 --page 端口 拼完整的地址"})
    else:
        lines.append("粘进浏览器地址栏（同一个标签页也行），回车就换过去，不用刷新；后退回到原来的")
    data = {"url": url, "fragment": frag, "view": v.__dict__}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), warnings=c.warnings)

