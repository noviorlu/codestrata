"""codestrata view：页面的视图描述。

    view url   只拼地址（read）：用户粘进页面（同一个标签页也行）就换过去，不用刷新
    view set   推给开着的页面（page）：页面直接换，带过渡和横幅，后退就是撤销；用户正在操作时等他松手
    view get   读用户此刻在看什么（read）
    view back  撤销 agent 最近推的那一步（page）；那之后用户自己改过就拒绝
    view wait  等用户在页面上改（read）：点一下要问的那条线，就拿到它的稳定写法

推给页面要 serve 开着、是能推视图的版本（serve 登记、viewhub.py）；找不到就退到 view url，把地址交给用户。"""
from __future__ import annotations

import argparse
import time

from .. import chainview as _chainview
from .. import finder as _finder
from .. import funcref as _funcref
from .. import laneid as _laneid
from .. import lanes as _lanes
from .. import locate as _locate
from .. import ref as _ref
from .. import runs as _runs
from .. import seq as _seq
from .. import viewspec as _viewspec
from ..errors import CodestrataError
from ..ui import search as _search
from . import common, out, pages

NAME = "view"
EFFECT = "page"
DOES = ("页面的视图描述：view set 推给开着的页面（只看列、收起、标记、选中、展开到函数、时间顺序）、view back 撤销（page）；"
        "view url 只拼地址、view get 读用户在看什么、view wait 等用户点（read）")
USAGE = ("codestrata view url|set|get|back|wait [REF|'页面地址'] [--lanes 列,…] [--fold 进程,…] [--mark 东西,…] [--expand 东西,…] "
         "[--focus 东西] [--select 东西] [--chain 范围~起点~--link…] [--order on|off] [--path] [--reset] [--note 一句话] "
         "[--page 端口] [--tab ID] [--for select|range|lanes|any|applied] [--timeout 秒] [--json]")
EXAMPLE = "codestrata view set 20261001-170349-run_single_prompt@serving --focus MiniCPMO45OmniTTSForConditionalGeneration.sample --note 'talker 的采样'"

ACTIONS = ("url", "set", "get", "back", "wait")
STATES = {"applied": "已换好", "deferred": "还没换：用户正在操作，松手约 1 s 后换", "queued": "还没换：标签页在后台，用户切回来时换",
          "offered": "还没换：用户关了「跟随 agent」，页面上出了提示条，等他点「换过去」", "sent": "交给页面了，页面还没回话"}
_BY = {"boot": "页面打开时", "user": "用户", "url": "粘进来的地址", "history": "浏览器后退 / 前进", "agent": "agent"}


def add_args(p) -> None:
    """每个动作一个子命令（-C、--json 在动作前后都能写：view -C 仓库 set REF、view set -C 仓库 REF）"""
    sp = p.add_subparsers(dest="action", required=True, metavar="url|set|get|back|wait")
    helps = {"url": "只拼地址（read）", "set": "推给开着的页面（page）", "get": "读用户此刻在看什么（read）",
             "back": "撤销 agent 最近推的那一步（page）", "wait": "等用户在页面上改（read）"}
    for name in ACTIONS:
        q = sp.add_parser(name, help=helps[name], description=f"codestrata view {name}：{helps[name]}")
        q.add_argument("-C", dest="C", default=argparse.SUPPRESS, metavar="目录", help="仓库目录（同 view 前面的 -C）")
        q.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="打印 JSON 信封")
        q.add_argument("ref", nargs="?", default=None, metavar="REF",
                       help="RUN@范围[/列]，或页面地址" + ("（在它的视图上改）" if name == "url" else
                                                     "；不给就沿用页面现在的 run" if name == "set" else "（用来找页面）"))
        if name in ("url", "set"):
            _view_opts(q)
        q.add_argument("--page", default=None, metavar="端口",
                       help="页面在本机哪个端口" + ("（给了就拼完整的地址）" if name == "url" else "（缺省按仓库找开着的）"))
        if name != "url":
            q.add_argument("--tab", default=None, metavar="ID", help="哪个标签页（view get 列出来的 id；缺省是用户最近在看的那个）")
        if name == "set":
            q.add_argument("--reset", action="store_true", help="不沿用页面现在的键（收起、切面、标记…），全部从缺省开始")
            q.add_argument("--note", default="", help="一句话说明换到了什么（页面的横幅上显示）")
        if name == "wait":
            q.add_argument("--for", dest="for_", default="select", choices=["select", "range", "lanes", "any", "applied"],
                           help="等什么变（缺省 select：用户点了一个东西）")
        if name in ("set", "back", "wait"):
            q.add_argument("--timeout", type=float, default=None,
                           help="最多等几秒（set / back 等页面换好，缺省 3；wait 缺省 60）")


def _view_opts(q) -> None:
    q.add_argument("--lanes", default=None, help="只看这几列（选择器，逗号隔开；all 或 * 是全部列，不写是页面默认收起转一手的列，"
                                                  "+进程 是在默认上再放出这个进程的列）")
    q.add_argument("--fold", default=None, help="收起这些进程（别名，逗号隔开；none 是都不收）")
    q.add_argument("--mark", default=None, help="标出这些文件 / 目录 / 函数所在的节点（逗号隔开，最多 20；none 清掉；+东西 是追加）")
    q.add_argument("--expand", default=None, help="把切面展开到这些文件 / 函数所在的文件：在它跑过的每一列里")
    q.add_argument("--focus", default=None, metavar="东西", help="简写：只看它跑过的列 + 展开 + 标出 + 选中它")
    q.add_argument("--select", default=None, metavar="东西",
                   help="选中：n:列|节点、e:列|a|b、l:种类|通道|起列|终列，或一个函数（选它所在的文件）；none 取消")
    q.add_argument("--order", choices=["on", "off"], default=None, help="时间顺序开 / 关")
    q.add_argument("--path", action="store_true", help="详情栏讲请求路径")
    q.add_argument("--chain", default=None, metavar="范围~起点~--link…",
                   help="页面高亮一条链（links --follow 的下一步里拼好了）：链上的跳亮出来、推出来的画虚线；none 清掉")


def run(a) -> out.Result:
    return {"url": _url, "set": _set, "get": _get, "back": _back, "wait": _wait}[a.action](a)


# ---------------------------------------------------------------- 拼视图（url、set 共用）

# 没写 lanes= 的视图：页面默认收起转一手的列（lanedefault）。说一句，哪几列、为什么在 lanes 命令里
_DEFAULT_LANES = ("列：没写 lanes=，按页面默认（转一手的列收起；老 run、这一段没录到交接时不收）——收哪几列、为什么见 codestrata lanes；"
                  "--lanes all 看全部")


def _compose(c, a, v: _viewspec.View) -> list[str]:
    """把命令行的选项套到视图 v 上（v.run、v.lanes 已经按 REF 定好）；返回说明「这个视图是什么」的几行"""
    r = c.res
    idx = common.index(c)
    label = common.labeler(idx)
    aliases = _lanes.run_aliases(r.rd)
    procs = _lanes.proc_aliases(r.rd)
    if a.lanes is not None:
        try:
            # all 写成 *：不写 lanes= 是默认（转一手的列收起），不是全部
            v.lanes = ["*"] if a.lanes == "all" else _laneid.canonical(_laneid.parse_list(a.lanes), aliases)
        except CodestrataError:                     # 录了 GPU 的 run：再加上 GPU 的列认一次
            v.lanes = _laneid.canonical(_laneid.parse_list(a.lanes), _lanes.run_aliases(r.rd, _lanes.gpu_lanes(r.rd, r.run)))
    if a.fold is not None:
        by = {x.lower(): x for x in procs.values()}            # 进程别名不分大小写（同列选择器）
        bad = [x for x in _laneid.parse_list(a.fold) if x.lower() not in by and a.fold != "none"]
        if bad:
            raise CodestrataError("lane_not_found", f"没有这些进程：{', '.join(bad)}", candidates=sorted(by.values()))
        v.fold = [] if a.fold == "none" else sorted(by[x.lower()] for x in _laneid.parse_list(a.fold))
    keys = _seq.span_index(r.rd)["keys"]
    ran = None                                      # 函数节点 → {列别名: [次数, 首, 末]}（--expand / --focus 要知道它在哪几列跑过）

    def where(item: str) -> tuple[str, dict]:
        """一个东西 → (标记 / 展开用的写法, 它跑过的列 {列别名: [次数, 首, 末]})"""
        nonlocal ran
        if ran is None:
            ran = _finder.ran_per_node(r.rd, r.run, r.phase, label, lambda pid, t: aliases.get(_lanes.lane_id(pid, t), f"{pid}:{t}"))
        if item.endswith("/") and item in (idx.get("dirs") or {}):      # 索引里的目录键带结尾的 /
            key = item
        elif item in (idx.get("files") or {}):
            key = item
        else:
            key = _funcref.resolve(item, keys, label)[0]
        return key, _finder.ran_lanes(idx, ran, [key])[key]

    marks = list(v.mark)
    if a.mark is not None:
        items = _laneid.parse_list(a.mark)
        if a.mark == "none":
            marks = []
        elif items and all(x.startswith("+") for x in items):           # +东西：追加
            marks += [k for k in (where(x[1:])[0] for x in items) if k not in marks]
        else:
            marks = [where(x.lstrip("+"))[0] for x in items]
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
            order = list(aliases.values())
            v.lanes = sorted(lanes_ran, key=lambda ln: order.index(ln) if ln in order else 0)
        first = min(lanes_ran, key=lambda ln: lanes_ran[ln][1])
        sel = f"n:{first}|{key.split('#')[0]}"
    if a.select and a.select != "none" and a.select[:2] not in ("n:", "e:", "f:", "l:"):
        key, lanes_ran = where(a.select)                # 选一个函数：选它的文件在最早那一列里的那一份，那一列先展开到它
        if not lanes_ran:
            raise CodestrataError("item_not_found", f"{a.select} 这段时间里在哪一列都没跑过，选不中")
        first = min(lanes_ran, key=lambda ln: lanes_ran[ln][1])
        expand.append((key, {first: lanes_ran[first]}))
    for key, lanes_ran in expand:
        node = key.split("#")[0].rstrip("/") + ("/" if key.endswith("/") else "")
        base = v.cut if v.cut is not None else (idx.get("default_open") or [])
        for ln in lanes_ran:
            cur = v.lcut.get(ln, base)
            opened = _search.reveal(idx, node, cur)
            if opened is not None and sorted(opened) != sorted(cur):
                v.lcut[ln] = sorted(opened)
    if a.select:
        if a.select == "none":
            sel = None
        elif a.select[:2] in ("n:", "e:", "f:", "l:"):
            sel = a.select
        else:
            key, lanes_ran = where(a.select)
            if not lanes_ran:
                raise CodestrataError("item_not_found", f"{a.select} 这段时间里在哪一列都没跑过，选不中")
            sel = f"n:{min(lanes_ran, key=lambda ln: lanes_ran[ln][1])}|{key.split('#')[0]}"
    v.sel = sel
    v.mark = marks[:20]
    if a.order is not None:
        v.order = a.order == "on"
    if a.path:
        v.panel = "path"
    if a.chain is not None:
        if a.chain == "none":
            v.chain = None
        else:
            hot = _runs.load_run(c.repo, idx, r.run, r.rd, None)[0]
            info, _ = _chainview.for_page(idx, r.rd, r.run, hot, a.chain)
            if info.get("error"):
                raise CodestrataError(info.get("code") or "usage", f"--chain 在这个 run 上走不出来：{info['error']}")
            v.chain = a.chain
    what = []
    if v.lanes == ["*"]:
        what.append("全部列（不收起转一手的）")
    elif _laneid.plus_only(v.lanes):
        what.append("默认收起转一手的列，再放出 " + ",".join(x[1:] for x in v.lanes))
    elif v.lanes:
        what.append("只看 " + ",".join(v.lanes) + "（别的列每个进程收成一窄列）")
    else:
        what.append(_DEFAULT_LANES)
    if v.fold:
        what.append("收起 " + ",".join(v.fold))
    if expand:
        what.append("展开：" + "；".join(f"{ln} 展开到 {key.split('#')[0]}" for key, lanes_ran in expand for ln in sorted(lanes_ran)
                                       if ln in v.lcut))
    if v.mark:
        what.append("标记 " + "、".join(v.mark))
    if v.chain:
        what.append("高亮链 " + _chainview.parse(v.chain)[1] + "（链上的跳亮出来，推出来的画虚线）")
    if v.sel:
        what.append("选中 " + v.sel)
    if v.order:
        what.append("时间顺序开")
    return [f"  {x}" for x in what]


def _url(a) -> out.Result:
    c = common.context(a)
    r, ref = c.res, c.ref
    v = _viewspec.from_keys(None, [], ref.view) if ref.page else _viewspec.View()
    v.run, v.lanes = r.text, list(r.lanes)
    what = _compose(c, a, v)
    frag = _viewspec.fragment(v)
    prefix = None
    if ref.page:
        prefix = ref.page["url"].split("#", 1)[0]
    elif a.page:
        try:
            port = int(str(a.page).rsplit(":", 1)[-1].strip("/"))
        except ValueError:
            raise CodestrataError("usage", f"--page 要写端口（比如 8900）：{a.page!r}") from None
        prefix = f"http://127.0.0.1:{port}/"
        app = _locate.page_app({"host": "127.0.0.1", "port": port}, timeout=1.0)
        if app is None:
            c.warnings.append({"code": "page_unknown", "msg": f"127.0.0.1:{port} 上没有 codestrata serve：地址拼了，但用户粘进去打不开"})
        elif str(app.get("repo")) != str(c.repo):
            c.warnings.append({"code": "page_mismatch", "msg": f"127.0.0.1:{port} 开的是别的仓库 {app.get('repo')}，不是 {c.repo}"})
    url = f"{prefix}#{frag}" if prefix else f"#{frag}"
    lines = ["地址（交给用户粘进浏览器地址栏；不带引号）", f"  {url}"] + what
    if not prefix:
        c.warnings.append({"code": "no_page", "msg": "没给页面：把上面这一段（# 开头）粘到浏览器地址栏里页面地址的后面；"
                                                   "或者加 --page 端口 拼完整的地址"})
    else:
        lines.append("粘进浏览器地址栏（同一个标签页也行），回车就换过去，不用刷新；后退回到原来的")
    data = {"url": url, "fragment": frag, "view": v.__dict__}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), warnings=c.warnings)


# ---------------------------------------------------------------- 推给页面

def _page(a):
    """(Ctx, 开着的 serve, 要推 / 读的标签页)"""
    c = common.context(a, need_run=False)
    pg = pages.find(c, a.page)
    t = pages.tab_of(pg, a.tab)
    return c, pg, t


def _set(a) -> out.Result:
    c, pg, t = _page(a)
    cur = _ref.parse_fragment(t["view"] or "")
    own = c.res is not None                         # 命令行给了 REF：按它定 run、范围和列；没给就沿用页面现在的
    if not own:
        if not cur.run:
            raise CodestrataError("need_view", "页面上没选 run（只开着静态图）：给一个 REF")
        c.ref, c.res = cur, _locate.resolve(c.repo, cur)
        c.warnings += c.res.warnings
    v = _viewspec.View() if a.reset else _viewspec.from_keys(None, [], cur.view)
    if own and not a.reset and cur.run and _locate.resolve(c.repo, cur).run["id"] != c.res.run["id"]:
        v.sel, v.lcut = None, {}                    # 换了 run：选中和各列的切面清掉（其余沿用）
    v.run = c.res.text
    v.lanes = list(c.res.lanes) if own else list(cur.lanes)
    what = _compose(c, a, v)
    frag = _viewspec.fragment(v)
    timeout = 3.0 if a.timeout is None else a.timeout
    t0 = time.monotonic()
    code, d = pages.call(pg["port"], "POST", "/api/view", {"view": frag, "note": a.note, "tab": t["tab"], "timeout": timeout},
                         timeout=timeout + 5)
    if code != 200:
        raise CodestrataError(d.get("code") or "page_failed", d.get("error") or f"serve 回了 {code}", candidates=d.get("candidates"))
    return _pushed(c, pg, d, frag, what, time.monotonic() - t0, "set")


def _pushed(c, pg: dict, d: dict, frag: str, what: list[str], took: float, op: str) -> out.Result:
    st, t = d["state"], d["tab"]
    url = pages.page_url(pg, t, frag) if frag else None
    if st in ("failed", "superseded", "refused"):
        code = {"failed": "page_failed"}.get(st, st)
        why = d.get("error") or {"superseded": "被后来的一条要求顶掉了"}.get(st, "")
        nxt = [c.cmd("read", "view", "url", c.res.text, why="把地址交给用户")] if (url and c.res) else []
        raise CodestrataError(code, f"页面没换（{st}）：{why}", next=nxt)
    head = ("已撤销" if op == "back" else STATES["applied"]) if st == "applied" else STATES.get(st, st)
    lines = [f"{head}（{st}）· {pages.where(pg, t)} · {took:.2f} s"]
    if op == "set":
        lines += what
        if t.get("n") is not None and st == "applied":
            lines.append(f"  页面上的编号一共 {t['n']} 个（时间顺序开着时）")
        lines.append("  撤销  浏览器后退，或 codestrata view back")
        lines.append(f"  地址  {url}")
    nxt, exit_ = [], 0
    if st in ("deferred", "queued", "offered", "sent"):
        exit_ = 6
        nxt.append(c.cmd("read", "view", "wait", "--for", "applied", "--timeout", "30", why="等页面换好"))
    data = {"state": st, "v": d.get("v"), "tab": t, "url": url, "fragment": frag, "port": pg["port"]}
    return out.Result(data=data, text=lines, repo=c.repo, ref=c.ref_json(), next=nxt, warnings=c.warnings, exit=exit_)


def _get(a) -> out.Result:
    c, pg, t = _page(a)
    lines = [f"{pages.where(pg, t)}  最后是{_BY.get(t['by'], t['by'])}改的",
             f"  视图  {t['view'] or '（静态图）'}"]
    if t["view"] and t["view"].startswith("run=") and "lanes=" not in t["view"]:
        lines.append("  " + _DEFAULT_LANES)
    if t.get("n") is not None:
        lines.append(f"  编号  一共 {t['n']} 个")
    if t.get("last"):
        L = t["last"]
        lines.append(f"  agent 最近推的一条  {L['op']} · {L['state']}" + (f"（{L['error']}）" if L.get("error") else ""))
    if not t["follow"]:
        lines.append("  用户关了「跟随 agent」：推过去的视图要用户点了才换")
    for x in pg["tabs"]:
        if x["tab"] != t["tab"]:
            lines.append(f"  另一个标签页 {x['tab'][:4]}（{'看得见' if x['visible'] else '在后台'}）  {x['view'] or '（静态图）'}")
    nxt = []
    sel = _ref.parse_fragment(t["view"] or "").view.get("sel")
    if sel:
        nxt.append(c.cmd("read", "explain", "--selected", *(["--page", str(pg["port"])] if a.page else []), why=f"讲用户选中的 {sel}"))
    data = {"tab": t, "tabs": pg["tabs"], "port": pg["port"], "url": pages.page_url(pg, t, t["view"])}
    return out.Result(data=data, text=lines, repo=c.repo, next=nxt, warnings=c.warnings)


def _back(a) -> out.Result:
    c, pg, t = _page(a)
    timeout = 3.0 if a.timeout is None else a.timeout
    t0 = time.monotonic()
    code, d = pages.call(pg["port"], "POST", "/api/view/back", {"tab": t["tab"], "timeout": timeout}, timeout=timeout + 5)
    if code != 200:
        raise CodestrataError(d.get("code") or "page_failed", d.get("error") or f"serve 回了 {code}", candidates=d.get("candidates"))
    return _pushed(c, pg, d, "", [], time.monotonic() - t0, "back")


def _wait(a) -> out.Result:
    c, pg, t = _page(a)
    timeout = 60.0 if a.timeout is None else a.timeout
    code, d = pages.call(pg["port"], "GET", f"/api/view/wait?tab={t['tab']}&for={a.for_}&timeout={timeout}", timeout=timeout + 5)
    if code != 200:
        raise CodestrataError(d.get("code") or "page_failed", d.get("error") or f"serve 回了 {code}", candidates=d.get("candidates"))
    t2 = d["tab"]
    sel = _ref.parse_fragment(t2["view"] or "").view.get("sel")
    if not d["changed"]:
        what = f"页面还没换好（{d.get('state')}）" if a.for_ == "applied" else "用户没改"
        lines = [f"等了 {timeout:.0f} s，{what}（{pages.where(pg, t2)}）"]
    elif a.for_ == "applied":
        lines = [f"页面换好了（{pages.where(pg, t2)}）"]
    else:
        lines = [f"用户改了（{pages.where(pg, t2)}）", f"  视图  {t2['view']}"] + ([f"  选中  {sel}"] if sel else [])
    nxt = []
    if d["changed"] and sel and a.for_ in ("select", "any"):
        nxt.append(c.cmd("read", "explain", "--selected", *(["--page", str(pg["port"])] if a.page else []), why=f"讲用户选中的 {sel}"))
    data = {"changed": d["changed"], "for": a.for_, "tab": t2, "selected": sel, "port": pg["port"]}
    return out.Result(data=data, text=lines, repo=c.repo, next=nxt, warnings=c.warnings)
