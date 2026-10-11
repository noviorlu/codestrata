"""serve 内存里的信箱：agent 推给页面的视图、页面回报的现状。命令行那头是 cli/view.py（view set / get / back / wait），
页面那头是 web/viewsync.js。

    POST /api/view        {view, note?, tab?, timeout?}  agent 推一个视图（视图描述，同地址栏 # 后面那串）：先核对（写错 400 + 候选），
                                                         交给目标标签页，等页面回话或者等到 timeout 秒，回当时的状态
    POST /api/view/back   {tab?, timeout?}               撤销 agent 最近推的那一步（页面后退一条历史）；那之后用户自己改过就拒绝
    POST /api/view/poll   {tab, report, wait?}           页面来问有没有要换的，顺带回报现状；有焦点的页面挂着等，最多 wait 秒
    POST /api/view/bye    {tab}                          页面关了 / 刷新了
    GET  /api/view?tab=                                  各标签页的现状（view get、status、explain --selected）
    GET  /api/view/wait?tab=&for=&timeout=               等用户在页面上改（select / range / lanes / any；applied 等最近一条换好）

一条要求的状态：applied 换好了 · deferred 用户正在操作，松手后换 · queued 标签页在后台，回来时换（只换最后一次）·
offered 用户关了跟随，页面上出了提示条等他点 · sent 交给页面了、页面还没换好 · failed 页面换不过去（带原因）·
superseded 被后来的一条顶掉 · refused（view back）不能撤。页面说收到了（applying 或者处理结果）之前，它每次来问都再交一遍：
交出去的那次请求可能被页面自己断掉了（页面上一有变化就断掉挂着的那次、马上再问），页面按版本号去重。

只在内存里，serve 重启就清（页面会自己重新来问）。标签页的 id 是页面每次加载随机生成的；看得见的标签页 30 s 没来问过算不在了，
看不见的不来问是正常的（回来时会问），留一小时。读写都要 X-Codestrata 头（serve 那边查）：「用户在看什么」也不该让别的网页读到。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ref as _ref
from .errors import CodestrataError

KEYS = ("run", "lanes", "fold", "cut", "lcut", "sel", "mark", "chain", "order", "hide", "panel")
STALE_S = 30.0              # 看得见的标签页多久没来问算不在了
LIVE_S = 3.0                # 看得见、没焦点的页面每秒来问一次：这么久没来问的不当缺省的目标（关了却没来得及说一声的）
HIDDEN_S = 3600.0           # 看不见的标签页留多久
MAX_WAIT = 25.0             # 页面挂着等最多几秒（主菜单转发的超时比它长）
PENDING = ("sent", "deferred", "queued", "offered")
FOR = ("select", "range", "lanes", "any", "applied")


@dataclass
class Tab:
    id: str
    seen: float
    active: float = 0.0         # 最后一次有焦点、或者用户动过的时刻：缺省推给最近在看的那个
    visible: bool = True
    focused: bool = False
    busy: bool = False          # 用户正在操作（按着鼠标、刚按过键 / 滚过轮）
    follow: bool = True         # 「跟随 agent」开着
    view: str = ""              # 页面回报的视图描述（规范写法）
    url: str = ""               # 页面地址（不带 #）
    by: str = "boot"            # 最后是谁改的：boot / user / url / history / agent
    n: int | None = None        # 页面上的编号一共几个（时间顺序开着时）
    push: dict | None = None    # 最新一条要求 {v, op, view, note}
    state: str | None = None    # 它的状态
    error: str | None = None
    handled: int = 0            # 页面说过收到了的最新一条（applying 或者处理结果）：之前每次来问都再交一遍——交给页面的那次请求可能被页面断掉了
    acked: int = 0              # 页面换好的最新一条
    seq: int = 0                # 这个标签页第几次来问：后来的一次到了，挂着的那次就不等了（页面把它断掉了）
    waiting: int = 0            # 正挂着等的请求有几条（有焦点的页面挂着等时不更新 seen，但它活着）
    agent_v: int = 0            # agent 最近推成的那一条（view back 撤它）
    user_after: bool = False    # 那之后用户自己改过
    changes: dict = field(default_factory=lambda: {k: 0 for k in FOR if k != "applied"})

    def brief(self, now: float) -> dict:
        return {"tab": self.id, "visible": self.visible, "focused": self.focused, "busy": self.busy, "follow": self.follow,
                "view": self.view, "url": self.url, "by": self.by, "n": self.n, "seen_s": round(now - self.seen, 1),
                "last": {"v": self.push["v"], "op": self.push["op"], "state": self.state, "error": self.error} if self.push else None}


def _keys(frag: str) -> dict[str, str]:
    r = _ref.parse_fragment(frag)
    out = dict(r.view)
    if r.run:
        out["run"] = r.run + (f"@{r.rest}" if r.rest is not None else "")
    if r.lanes:
        out["lanes"] = ",".join(r.lanes)
    return out


def _aspects(old: str, new: str) -> list[str]:
    """两份视图描述之间变了哪几样：select（选中）、range（run 和范围）、lanes（只看的列、收起）、chain（高亮的链）"""
    a, b = _keys(old), _keys(new)
    out = []
    if a.get("sel") != b.get("sel"):
        out.append("select")
    if a.get("run") != b.get("run"):
        out.append("range")
    if (a.get("lanes"), a.get("fold")) != (b.get("lanes"), b.get("fold")):
        out.append("lanes")
    if a.get("chain") != b.get("chain"):
        out.append("chain")
    return out


class Hub:
    def __init__(self):
        self.tabs: dict[str, Tab] = {}
        self.ver = 0
        self.cv = threading.Condition()

    # ---- 标签页 ----
    def _prune(self, now: float) -> None:
        for k, t in list(self.tabs.items()):
            if now - t.seen > (STALE_S if t.visible else HIDDEN_S):
                del self.tabs[k]

    def _target(self, tab: str | None) -> Tab:
        now = time.monotonic()
        self._prune(now)
        if tab:
            t = self.tabs.get(tab)
            if t is None:
                raise CodestrataError("no_live_page", f"没有标签页 {tab}（关了或刷新了）", candidates=sorted(self.tabs))
            return t
        if not self.tabs:
            raise CodestrataError("no_live_page", "这个图服务上没有开着的页面")
        # 缺省：看得见、还在来问的（挂着等、或者 LIVE_S 秒里问过）里面最近有焦点 / 用户动过的；都不是时最近来问过的
        return max(self.tabs.values(), key=lambda t: (t.visible and (t.waiting > 0 or now - t.seen < LIVE_S), t.active, t.seen))

    def tabs_brief(self) -> dict:
        with self.cv:
            now = time.monotonic()
            self._prune(now)
            default = self._target(None).id if self.tabs else None
            return {"tabs": [t.brief(now) for t in sorted(self.tabs.values(), key=lambda t: -t.active)], "default": default}

    # ---- agent 推 ----
    def push(self, view: str, note: str, tab: str | None, timeout: float, op: str = "set") -> dict:
        with self.cv:
            t = self._target(tab)
            if op == "back":
                if not t.agent_v:
                    return self._out(t, None, "refused", "agent 还没往这个标签页推过视图")
                if t.user_after:
                    return self._out(t, None, "refused", "agent 推了之后用户自己改过视图，不撤（用户可以在浏览器里后退）")
            self.ver += 1
            v = self.ver
            if t.push and t.state in PENDING:
                t.push["superseded"] = v
            t.push = {"v": v, "op": op, "view": view, "note": note}
            # 看不见的标签页不来问，回来时才换：直接回 queued。看得见的等页面自己说（它最清楚用户在不在操作、跟随开没开）
            t.state = "queued" if not t.visible else "sent"
            t.error = None
            self.cv.notify_all()
            if t.state == "queued":
                return self._out(t, v, t.state)
            end = time.monotonic() + max(0.0, min(timeout, MAX_WAIT))
            while True:                              # 等页面回话：换好了、说明了为什么还没换，或者到时间
                if t.push is None or t.push["v"] != v:
                    return self._out(t, v, "superseded")
                if t.acked >= v:
                    return self._out(t, v, "applied")
                if t.handled >= v and t.state != "sent":
                    return self._out(t, v, t.state, t.error)
                left = end - time.monotonic()
                if left <= 0 or self.tabs.get(t.id) is not t:
                    return self._out(t, v, t.state if self.tabs.get(t.id) is t else "failed",
                                     t.error if self.tabs.get(t.id) is t else "标签页关了")
                self.cv.wait(left)

    def _out(self, t: Tab, v: int | None, state: str, error: str | None = None) -> dict:
        return {"state": state, "v": v, "error": error, "tab": t.brief(time.monotonic())}

    # ---- 页面来问 ----
    def poll(self, tab: str, report: dict, wait: float) -> dict:
        with self.cv:
            now = time.monotonic()
            t = self.tabs.get(tab)
            if t is None:
                t = self.tabs[tab] = Tab(id=tab, seen=now, active=now)
            self._report(t, report or {}, now)
            t.seq += 1
            me = t.seq
            self.cv.notify_all()
            end = now + max(0.0, min(float(wait or 0), MAX_WAIT))
            t.waiting += 1
            try:
                while True:
                    p = t.push
                    if p and p["v"] > t.handled and t.state in PENDING:
                        return {"push": {k: p[k] for k in ("v", "op", "view", "note")}}
                    left = end - time.monotonic()
                    if left <= 0 or self.tabs.get(tab) is not t or t.seq != me:
                        return {}
                    self.cv.wait(left)
            finally:
                t.waiting -= 1
                t.seen = time.monotonic()

    def _report(self, t: Tab, r: dict, now: float) -> None:
        t.seen = now
        for k in ("visible", "focused", "busy", "follow"):
            if k in r:
                setattr(t, k, bool(r[k]))
        if isinstance(r.get("url"), str):
            t.url = r["url"][:2000]
        if "n" in r:
            t.n = r["n"] if isinstance(r["n"], int) else None
        by = r.get("by") if r.get("by") in ("boot", "user", "url", "history", "agent") else t.by
        if t.focused or by == "user":
            t.active = now
        view = r.get("view")
        if isinstance(view, str) and view != t.view:
            for a in _aspects(t.view, view) + ["any"]:
                t.changes[a] += 1
            t.view = view[:20000]
            t.by = by
            if by in ("user", "url") and t.agent_v:
                t.user_after = True
        st = r.get("state")                          # 页面处理 agent 那一条的结果 {v, state, error}
        if isinstance(st, dict) and t.push and st.get("v") == t.push["v"]:   # 页面每次来问都带着它：只认头一回
            t.handled = max(t.handled, t.push["v"])
            s = st.get("state")                      # applying：收到了、正在换（状态还是 sent，等换好）
            if s == "applied" and t.acked < t.push["v"]:
                t.acked = t.push["v"]
                t.state, t.error = "applied", None
                if t.push["op"] == "set":
                    t.agent_v, t.user_after = t.push["v"], False
                else:                                # 撤销了：再撤就没有了
                    t.agent_v, t.user_after = 0, False
            elif s in ("deferred", "queued", "offered", "failed") and t.acked < t.push["v"]:
                t.state, t.error = s, (str(st.get("error"))[:500] if st.get("error") else None)
            elif s == "declined" and t.acked < t.push["v"]:    # 关了跟随、用户点了「不用」
                t.state, t.error = "failed", "用户没换过去（点了「不用」）"

    def bye(self, tab: str) -> None:
        with self.cv:
            self.tabs.pop(tab, None)
            self.cv.notify_all()

    # ---- 等用户改 ----
    def wait(self, tab: str | None, what: str, timeout: float) -> dict:
        with self.cv:
            t = self._target(tab)
            base = dict(t.changes)
            want_v = t.push["v"] if t.push else 0
            end = time.monotonic() + max(0.0, min(timeout, 600.0))
            while True:
                if what == "applied":
                    if not t.push or t.acked >= want_v or t.state in ("failed", "superseded"):
                        return {"changed": t.acked >= want_v and want_v > 0, "state": t.state, "tab": t.brief(time.monotonic())}
                elif t.changes[what] > base[what]:
                    return {"changed": True, "tab": t.brief(time.monotonic())}
                left = end - time.monotonic()
                if left <= 0 or self.tabs.get(t.id) is not t:
                    return {"changed": False, "state": t.state, "tab": t.brief(time.monotonic())}
                self.cv.wait(min(left, 5.0))


HUB = Hub()


# ---------------------------------------------------------------- HTTP（serve.py 只转过来）

def check(repo: Path, frag: str) -> str:
    """agent 推来的视图描述：只收认得的键，run 和范围、列、收起的进程对着这个仓库核对（写错抛带候选的 CodestrataError）。
    返回原样（页面按规范写法重写地址）"""
    from . import locate as _locate
    keys = _keys(frag)
    bad = sorted(k for k in keys if k not in KEYS)
    if bad:
        raise CodestrataError("usage", f"视图描述里有不认识的键：{', '.join(bad)}", candidates=list(KEYS))
    if keys.get("chain"):
        from . import chainview as _chainview
        _chainview.parse(keys["chain"])
    r = _ref.parse_fragment(frag)
    if r.run:
        res = _locate.resolve(repo, r)
        fold = [x for x in (keys.get("fold") or "").split(",") if x]
        if fold:
            from . import lanes as _lanes
            try:
                procs = set(_lanes.proc_aliases(res.rd).values())
            except LookupError:
                procs = None
            miss = [x for x in fold if procs is not None and x not in procs]
            if miss:
                raise CodestrataError("lane_not_found", f"没有这些进程：{', '.join(miss)}", candidates=sorted(procs or ()))
    return frag


def post(repo: Path, path: str, body: dict) -> tuple[int, dict]:
    if path == "/api/view":
        frag = body.get("view")
        if not isinstance(frag, str):
            return 400, {"error": "要给 view（视图描述，地址栏 # 后面那串）", "code": "usage"}
        try:
            check(repo, frag)
            return 200, HUB.push(frag, str(body.get("note") or "")[:200], body.get("tab") or None, _num(body.get("timeout"), 3.0))
        except CodestrataError as e:
            return (409 if e.code == "no_live_page" else 400), {"error": e.msg, "code": e.code, "candidates": e.candidates}
    if path == "/api/view/back":
        try:
            return 200, HUB.push("", "撤销", body.get("tab") or None, _num(body.get("timeout"), 3.0), op="back")
        except CodestrataError as e:
            return 409, {"error": e.msg, "code": e.code, "candidates": e.candidates}
    if path == "/api/view/poll":
        tab = body.get("tab")
        if not isinstance(tab, str) or not 4 <= len(tab) <= 64:
            return 400, {"error": "要给 tab"}
        return 200, HUB.poll(tab, body.get("report") if isinstance(body.get("report"), dict) else {}, _num(body.get("wait"), 0.0))
    if path == "/api/view/bye":
        if isinstance(body.get("tab"), str):
            HUB.bye(body["tab"])
        return 200, {}
    return 404, {"error": "unknown"}


def get(path: str, q: dict) -> tuple[int, dict]:
    tab = (q.get("tab") or [""])[0] or None
    if path == "/api/view":
        return 200, HUB.tabs_brief()
    if path == "/api/view/wait":
        what = (q.get("for") or ["select"])[0]
        if what not in FOR:
            return 400, {"error": f"for 是 {' / '.join(FOR)} 之一", "code": "usage", "candidates": list(FOR)}
        try:
            return 200, HUB.wait(tab, what, _num((q.get("timeout") or [""])[0], 60.0))
        except CodestrataError as e:
            return 409, {"error": e.msg, "code": e.code, "candidates": e.candidates}
    return 404, {"error": "unknown"}


def _num(x, default: float) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default
