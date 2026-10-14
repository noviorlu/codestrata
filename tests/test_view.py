"""agent 推视图（viewhub.py、serves.py、cli/view.py、cli/pages.py）：信箱的规矩、serve 的登记和安全检查、命令行配一个假页面。

    python tests/test_view.py [名字里的词…]
页面那一头（viewsync.js：过渡、横幅、等松手、跟随、后台标签页）在浏览器里测（tests/web/specs/viewsync.mjs）。
"""
from __future__ import annotations

import http.client
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from common import HERE, PY, cs, fresh, run_tests  # noqa: E402

from codestrata import serves, viewhub  # noqa: E402


class FakePage(threading.Thread):
    """假页面：一直来问（poll(tab, report, wait) → {push?}）；收到 agent 推来的照 mode 回话：
    applied 换好（自己的视图换成推来的）、deferred 用户在操作、offered 跟随关着、silent 不回话"""

    def __init__(self, poll, tab="tab-0001", view="", mode="applied"):
        super().__init__(daemon=True)
        self.poll, self.tab, self.view, self.mode = poll, tab, view, mode
        self.visible, self.by, self.state, self.stop, self.got = True, "boot", None, False, []

    def report(self) -> dict:
        return {"view": self.view, "visible": self.visible, "focused": self.visible, "follow": self.mode != "offered",
                "busy": self.mode == "deferred", "by": self.by, "state": self.state, "url": "http://127.0.0.1:1/"}

    def user(self, view: str) -> None:
        """用户自己在页面上改了"""
        self.view, self.by = view, "user"

    def run(self) -> None:
        while not self.stop:
            r = self.poll(self.tab, self.report(), 0.3) if self.visible else {}
            p = (r or {}).get("push")
            if not p:
                if not self.visible:
                    time.sleep(0.05)
                continue
            self.got.append(p)
            if self.mode == "silent":
                continue
            if self.mode in ("deferred", "offered"):
                self.state = {"v": p["v"], "state": self.mode}
                continue
            if p["op"] == "set":
                self.view, self.by = p["view"], "agent"
            else:
                self.by = "history"
            self.state = {"v": p["v"], "state": "applied"}


def _bg(fn, *a):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn(*a)), daemon=True)
    t.start()
    return t, out


def test_hub_rules():
    """看得见的标签页换好了回 applied；看不见的回 queued、回来时只换最后一条；页面说用户在操作 → deferred；
    后来的顶掉前面的 → superseded；撤销：没推过、推了之后用户自己改过 → refused，否则后退；等用户选中"""
    hub = viewhub.Hub()
    pg = FakePage(hub.poll, view="run=a@x")
    pg.start()
    time.sleep(0.2)
    r = hub.push("run=a@y&lanes=s1", "第一条", None, 3.0)
    assert r["state"] == "applied" and pg.view == "run=a@y&lanes=s1", r
    assert hub.tabs_brief()["tabs"][0]["by"] == "agent"
    r = hub.push("", "撤销", None, 3.0, op="back")
    assert r["state"] == "applied" and pg.got[-1]["op"] == "back", r
    r = hub.push("", "撤销", None, 1.0, op="back")
    assert r["state"] == "refused", r                           # 撤过了：没有可撤的
    hub.push("run=a@z", "再推", None, 3.0)
    pg.user("run=a@z&order=1")
    time.sleep(0.6)
    assert hub.push("", "撤销", None, 1.0, op="back")["state"] == "refused"   # 用户之后自己改过
    # 页面说用户在操作 / 跟随关着
    pg.mode = "deferred"
    assert hub.push("run=a@w", "", None, 3.0)["state"] == "deferred"
    pg.mode = "offered"
    assert hub.push("run=a@w", "", None, 3.0)["state"] == "offered"
    # 后来的顶掉前面的：页面没回话时推第二条，第一条回 superseded；页面回过神来只换第二条
    pg.mode = "silent"
    t, out = _bg(hub.push, "run=a@1", "", None, 5.0)
    time.sleep(0.3)
    t2, out2 = _bg(hub.push, "run=a@2", "", None, 5.0)
    t.join(3)
    assert out["r"]["state"] == "superseded", out
    pg.mode = "applied"
    t2.join(5)
    assert out2["r"]["state"] == "applied" and pg.view == "run=a@2", (out2, pg.view)
    # 看不见：直接 queued；回来时只换最后一条
    pg.visible = False
    pg.poll(pg.tab, pg.report(), 0)
    n0 = len(pg.got)
    assert hub.push("run=a@3", "", None, 3.0)["state"] == "queued"
    assert hub.push("run=a@4", "", None, 3.0)["state"] == "queued"
    pg.visible = True
    t0 = time.time()
    while pg.view != "run=a@4" and time.time() - t0 < 3:
        time.sleep(0.05)
    assert pg.view == "run=a@4" and [p["view"] for p in pg.got[n0:]] == ["run=a@4"], pg.got[n0:]
    # 等用户选中：只等选中变了（别的变化不算）
    t, out = _bg(hub.wait, None, "select", 3.0)
    time.sleep(0.2)
    pg.user("run=a@4&order=1")
    time.sleep(0.5)
    assert "r" not in out
    pg.user("run=a@4&order=1&sel=l:handoff|queue|a/x|b/y")
    t.join(3)
    assert out["r"]["changed"] and "sel=" in out["r"]["tab"]["view"], out
    pg.stop = True


def test_hub_targets_and_stale():
    """缺省推给看得见的、最近在看的标签页；--tab 写错报 no_live_page 带候选；看得见的标签页久不来问算不在了"""
    hub = viewhub.Hub()
    hub.poll("tab-a", {"visible": True, "focused": False}, 0)
    hub.poll("tab-b", {"visible": True, "focused": True}, 0)
    hub.poll("tab-c", {"visible": False}, 0)
    assert hub.tabs_brief()["default"] == "tab-b"
    try:
        hub.push("run=a", "", "tab-x", 0.1)
        raise AssertionError("tab 写错没报错")
    except viewhub.CodestrataError as e:
        assert e.code == "no_live_page" and "tab-a" in e.candidates
    old = viewhub.STALE_S
    viewhub.STALE_S = 0.2
    try:
        time.sleep(0.3)
        assert [t["tab"] for t in hub.tabs_brief()["tabs"]] == ["tab-c"]   # 看不见的留着
    finally:
        viewhub.STALE_S = old


# ---------------------------------------------------------------- serve：登记、安全检查、核对

_TRUTH: list = []


def truth():
    if not _TRUTH:
        repo = fresh()
        cs("trace", repo, "--case", "truth", "--phase", "work=fakesvc.truth:s_threads", "--", PY, "-m", "fakesvc.truth")
        rid = sorted(p.name for p in (repo / ".codestrata" / "runs").iterdir() if p.name.endswith("-truth"))[-1]
        _TRUTH.append((repo, rid))
    return _TRUTH[0]


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(repo):
    port = _port()
    srv = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)], cwd=HERE.parent,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app", timeout=1)
            break
        except OSError:
            time.sleep(0.05)
    return srv, port


def call(port, method, path, body=None, headers=None, raw=None):
    h = {"X-Codestrata": "1", "Content-Type": "application/json"} if headers is None else headers
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            b = r.read()
            return r.status, (json.loads(b) if b.startswith(b"{") else b.decode())
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (json.loads(b) if b.startswith(b"{") else b.decode())


def http_page(port):
    """假页面经 HTTP 来问（serve 关了就歇一下再问）"""
    def poll(tab, report, wait):
        try:
            code, d = call(port, "POST", "/api/view/poll", {"tab": tab, "report": report, "wait": wait})
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
            return {}
        return d if code == 200 else {}
    return poll


def test_serve_registration_and_checks():
    """serve 起来登记、SIGTERM 退出时删掉；/api/app 有 features；/api/view… 要 X-Codestrata 头、POST 要 application/json；
    推来的视图先核对：阶段写错 400 + 候选、不认识的键 400、几片的时间段照收、写错 400、没有页面 409；进程不在的登记查找时删掉"""
    repo, rid = truth()
    srv, port = serve(repo)
    try:
        reg = [r for r in serves.listed(repo) if r["port"] == port]
        assert reg and reg[0]["pid"] == srv.pid and reg[0]["features"] == ["view"], serves.listed()
        code, app = call(port, "GET", "/api/app")
        assert app["features"] == ["view"] and app["algo"], app
        assert call(port, "GET", "/api/view", headers={})[0] == 403
        assert call(port, "POST", "/api/view", {"view": "x"}, headers={"Content-Type": "application/json"})[0] == 403
        assert call(port, "POST", "/api/view", raw=b"x", headers={"X-Codestrata": "1", "Content-Type": "text/plain"})[0] == 415
        assert call(port, "POST", "/api/view", {"view": "x"}, headers={"X-Codestrata": "1", "Content-Type": "application/json",
                                                                       "Host": "evil.example:80"})[0] == 403
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@nosuchphase"})
        assert code == 400 and d["code"] == "phase_not_found" and d["candidates"], d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@work&bogus=1"})
        assert code == 400 and d["code"] == "usage", d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@work"})
        assert code == 409 and d["code"] == "no_live_page", d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@t=1000-2000,5000-6000"})      # 几片（links --follow 的链）照样收
        assert code == 409 and d["code"] == "no_live_page", d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@t=1000-2000,x"})
        assert code == 400 and d["code"] == "bad_window", d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@work&chain=work~a/b:f@t=1"})       # 高亮的链：写法对就收（走不走得通页面上说）
        assert code == 409 and d["code"] == "no_live_page", d
        code, d = call(port, "POST", "/api/view", {"view": f"run={rid}@work&chain=nosep"})
        assert code == 400 and d["code"] == "usage", d
        # 一个进程已经不在的登记：查找时删掉
        dead = serves.register(1, 999_999_9, repo, "x")
        assert dead.exists() and all(r["port"] != 1 for r in serves.listed()) and not dead.exists()
    finally:
        srv.send_signal(signal.SIGTERM)
        srv.wait(10)
    assert all(r["port"] != port for r in serves.listed()), "SIGTERM 之后登记还在"


# ---------------------------------------------------------------- 命令行配假页面

def j(r) -> dict:
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    assert len(lines) == 1, r.stdout + r.stderr
    return json.loads(lines[0])


def test_cli_with_fake_page():
    """view set 推给页面（applied 退出码 0；用户在操作 → pending 退出码 6，下一步 view wait --for applied）；view get、status 读回；
    serve 关了 status 不再列它；
    view back 撤销、用户改过之后拒绝（5）；view wait 等到用户选中；explain --selected 讲它；没有页面 → no_live_page（5）带 view url"""
    repo, rid = truth()
    r = cs("view", "get", "-C", repo, "--json", check=False)
    d = j(r)
    assert r.returncode == 5 and d["error"]["code"] == "no_live_page" and any("view url" in n["cmd"] for n in d["next"]), d
    srv, port = serve(repo)
    pg = FakePage(http_page(port), view=f"run={rid}@work")
    pg.start()
    try:
        time.sleep(0.5)
        d = j(cs("view", "set", "-C", repo, f"{rid}@work", "--order", "on", "--note", "看 work", "--json"))
        assert d["data"]["state"] == "applied" and "order=1" in pg.view, (d, pg.view)
        d = j(cs("view", "get", "-C", repo, "--json"))
        assert d["data"]["tab"]["view"] == pg.view and d["data"]["tab"]["by"] == "agent", d
        d = j(cs("status", "-C", repo, "--json"))
        assert [p["port"] for p in d["data"]["pages"]] == [port] and d["data"]["pages"][0]["tabs"][0]["tab"] == pg.tab, d["data"]["pages"]
        d = j(cs("view", "back", "-C", repo, "--json"))
        assert d["data"]["state"] == "applied" and pg.got[-1]["op"] == "back", d
        cs("view", "set", "-C", repo, "--order", "off", "--json")             # 不给 REF：沿用页面现在的 run
        assert pg.got[-1]["view"].startswith(f"run={rid}@work"), pg.got[-1]
        pg.user(pg.view + "&order=1")
        time.sleep(0.6)
        r = cs("view", "back", "-C", repo, "--json", check=False)
        assert r.returncode == 5 and j(r)["error"]["code"] == "refused", r.stdout
        pg.mode = "deferred"
        r = cs("view", "set", "-C", repo, f"{rid}@work", "--json", check=False)
        d = j(r)
        assert r.returncode == 6 and d["data"]["state"] == "deferred" and "--for applied" in d["next"][0]["cmd"], (r.returncode, d)
        pg.mode = "applied"
        links = j(cs("links", "-C", repo, f"{rid}@work", "--json"))["data"]["links"]
        assert links, "truth 的 work 里有交接"
        t, out = _bg(cs, "view", "wait", "-C", repo, "--timeout", "10", "--json")
        time.sleep(1.0)
        pg.user(f"run={rid}@work&sel={links[0]['id']}")
        t.join(15)
        d = j(out["r"])
        assert d["data"]["changed"] and d["data"]["selected"] == links[0]["id"] and "--selected" in d["next"][0]["cmd"], d
        d = j(cs("explain", "--selected", "-C", repo, "--json"))
        assert d["ok"] and d["data"]["selected"] == links[0]["id"] and d["data"]["from_lane"] == links[0]["from"], d
    finally:
        pg.stop = True
        srv.send_signal(signal.SIGTERM)
        srv.wait(10)
    assert j(cs("status", "-C", repo, "--json"))["data"]["pages"] == [], "serve 关了 status 还列着它"


class _OldApp(http.server.BaseHTTPRequestHandler):
    repo = ""

    def do_GET(self):
        b = json.dumps({"repo": self.repo, "pid": os.getpid(), "port": self.server.server_address[1]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def test_url_has_no_lanes():
    """view url 不再写 lanes=（页面的默认收起不进地址）；--lanes 没有了"""
    repo, rid = truth()
    d = j(cs("view", "url", "-C", repo, f"{rid}@work", "--json"))
    assert "lanes=" not in d["data"]["fragment"], d["data"]
    r = cs("view", "url", "-C", repo, f"{rid}@work", "--lanes", "all", check=False)
    assert r.returncode != 0, r.stdout


def test_old_serve():
    """推视图之前的老 serve（/api/app 没有 features）：old_serve（退出码 5），下一步给 view url"""
    repo, rid = truth()
    _OldApp.repo = str(repo)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OldApp)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        r = cs("view", "set", f"http://127.0.0.1:{port}/#run={rid}@work", "-C", repo, "--json", check=False)
        d = j(r)
        assert r.returncode == 5 and d["error"]["code"] == "old_serve" and any("view url" in n["cmd"] for n in d["next"]), d
    finally:
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
