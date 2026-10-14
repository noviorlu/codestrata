"""命令行找开着的页面、和它的 serve 说话（view set / get / back / wait、status）。

找法：给了页面（REF 是页面地址，或 --page 端口）就问那个端口；否则按仓库读登记（serves.listed），活着的再问一次 /api/app
核对 repo 和 pid（端口可能被别的程序复用了）。好几个都开着时，挑有看得见的标签页、最近在看的那个。
找不到报 no_live_page、老 serve（没有推视图的接口）报 old_serve，都是退出码 5，说明里写怎么用 view url 把地址交给用户。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from .. import locate as _locate
from .. import serves as _serves
from ..errors import CodestrataError
from . import out

HEADER = "X-Codestrata"


def call(port: int, method: str, path: str, body: dict | None = None, timeout: float = 5.0) -> tuple[int, dict]:
    """问 127.0.0.1:端口 的 serve：(状态码, JSON)。连不上抛 CodestrataError(no_live_page)"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={HEADER: "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except (OSError, ValueError) as e:
        raise CodestrataError("no_live_page", f"连不上 127.0.0.1:{port} 上的 serve：{e}") from None


def find(c, page: str | None) -> dict:
    """这个仓库开着的、能推视图的 serve：{port, pid, repo, url, tabs, default}。page：--page 端口"""
    port = None
    if page:
        try:
            port = int(str(page).rsplit(":", 1)[-1].strip("/"))
        except ValueError:
            raise CodestrataError("usage", f"--page 要写端口（比如 8900）：{page!r}") from None
    elif c.ref is not None and c.ref.page:
        port = c.ref.page["port"]
    if port is not None:
        app = _locate.page_app({"host": "127.0.0.1", "port": port}, timeout=1.0)
        if app is None:
            raise CodestrataError("no_live_page", f"127.0.0.1:{port} 上没有 codestrata serve（关了？）；可以先 codestrata view url 拼地址交给用户")
        if Path(app["repo"]).resolve() != Path(c.repo).resolve():
            raise CodestrataError("no_live_page", f"127.0.0.1:{port} 开的是别的仓库 {app['repo']}，不是 {c.repo}；可以先 codestrata view url 拼地址交给用户")
        return _ready(c, app)
    alive = []
    for rec in _serves.listed(c.repo):
        app = _locate.page_app({"host": "127.0.0.1", "port": rec["port"]}, timeout=1.0)
        if app and app.get("pid") == rec.get("pid"):
            alive.append(app)
    if not alive:
        raise CodestrataError("no_live_page", f"{c.repo} 没有开着的图服务（或者是推视图之前的老版本，没登记）；可以先 codestrata view url 拼地址交给用户")
    best = None
    for app in alive:
        st = _tabs(app["port"])
        score = max(((t["visible"], -t["seen_s"]) for t in st.get("tabs") or []), default=(False, float("-inf")))
        if best is None or score > best[0]:
            best = (score, app, st)
    return _ready(c, best[1], best[2])


def open_pages(repo: Path) -> list[dict]:
    """这个仓库开着的、能推视图的 serve 和它们的标签页（status 用；不报错，问不到的跳过）：[{port, pid, tabs, default}]"""
    out_ = []
    for rec in _serves.listed(repo):
        app = _locate.page_app({"host": "127.0.0.1", "port": rec["port"]}, timeout=1.0)
        if app and app.get("pid") == rec.get("pid") and "view" in (app.get("features") or []):
            st = _tabs(rec["port"])
            out_.append({"port": rec["port"], "pid": rec["pid"], "tabs": st.get("tabs") or [], "default": st.get("default")})
    return out_


def _ready(c, app: dict, st: dict | None = None) -> dict:
    if "view" not in (app.get("features") or []):
        raise CodestrataError("old_serve", f"127.0.0.1:{app['port']} 上的 serve 是能推视图之前的版本：重起它才能推"
                              "（先问用户）；现在先用 codestrata view url 把地址交给用户")
    st = st or _tabs(app["port"])
    return {"port": app["port"], "pid": app.get("pid"), "repo": app["repo"], "home": app.get("home"),
            "tabs": st.get("tabs") or [], "default": st.get("default")}


def _tabs(port: int) -> dict:
    try:
        code, d = call(port, "GET", "/api/view", timeout=2.0)
    except CodestrataError:
        return {}
    return d if code == 200 else {}


def tab_of(pg: dict, tab: str | None) -> dict:
    """要看的那个标签页（给了 --tab 就是它，否则 serve 挑的缺省：最近在看的）"""
    tabs = pg["tabs"]
    if not tabs:
        raise CodestrataError("no_live_page", f"127.0.0.1:{pg['port']} 上没有开着的页面（用户得先在浏览器里打开图）")
    want = tab or pg["default"]
    hit = next((t for t in tabs if t["tab"] == want), None)
    if hit is None:
        raise CodestrataError("no_live_page", f"没有标签页 {want}", candidates=[t["tab"] for t in tabs])
    return hit


def page_url(pg: dict, t: dict, frag: str) -> str:
    """这个标签页的地址换上新的视图描述"""
    base = (t.get("url") or f"http://127.0.0.1:{pg['port']}/").split("#", 1)[0]
    return f"{base}#{frag}" if frag else base


def where(pg: dict, t: dict) -> str:
    """「:8900 标签 a3f9（你正看着）」"""
    how = "用户正看着" if t["focused"] else "看得见、没有焦点" if t["visible"] else "在后台"
    return f":{pg['port']} 标签 {t['tab'][:4]}（{how}）"


def quote(s: str) -> str:
    return out.quote(s)
