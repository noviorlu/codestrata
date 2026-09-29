"""codestrata app：浏览器里的主菜单——选文件夹、点按钮扫描 / 录制运行 / 打开图。

    GET    /                          主菜单页面（web/home.html）；/?t=<口令> 把口令设进 cookie 后跳回 /
    GET    /<asset>                   前端静态文件
    GET    /api/projects              项目卡片：每个打开过的仓库的状态、最近的任务（图服务地址只由 POST /api/open 给）
    POST   /api/projects {path}       加一个项目（打开文件夹）
    DELETE /api/projects?path=        从清单里去掉（不动仓库本身）
    GET    /api/browse?path=          列一个目录下的子目录（挑文件夹）
    GET    /api/symbols?repo=&q=      「录制运行」里阶段输入框的函数补全
    GET    /api/template?repo=&run=   录制表单的初始值：给了 run 就照它还原（复刻），没给是空白的
    POST   /api/scan {repo}           起一个扫描任务
    POST   /api/trace {表单}           起一个录制任务（字段见 jobs.TraceSpec）
    GET    /api/jobs/<id>?since=N     任务状态 + 第 N 行之后的输出
    POST   /api/jobs/<id>/stop        停任务（SIGINT，和终端里 Ctrl+C 一样）
    POST   /api/open {repo}           起（或复用）这个仓库的图服务（codestrata serve），返回地址

这里只做 HTTP：路由、鉴权、JSON 进出。数据在 projects，任务在 jobs，图服务在 viewers。

安全：主菜单能在本机执行命令，所以
  - 只监听 127.0.0.1；Host 头必须是 127.0.0.1:端口 或 localhost:端口（防 DNS rebinding）
  - /api/ 请求要带口令 cookie（SameSite=Strict、HttpOnly）和 X-Codestrata 头：别的网页发起的请求
    带不上前者，跨源也设不了后者（这里不回 CORS），知道端口也调不动
  - 口令存在配置目录（只有自己能读），用启动时打印的链接（/?t=口令）打开一次就设进了 cookie
  - 扫描、录制、打开图只接受清单里的项目
"""
from __future__ import annotations

import os
import re
import secrets
import signal
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path

from . import payload as _payload
from . import projects as _projects
from . import runs as _runs
from .jobs import Busy, JobError, JobManager, TraceSpec, scan_argv
from .serve import BaseHandler
from .viewers import ViewerError, Viewers

COOKIE = "codestrata_app"
HEADER = "X-Codestrata"
_JOB = re.compile(r"^/api/jobs/(\d+)(/stop)?$")

_LOGIN_PAGE = """<!doctype html><meta charset="utf-8"><title>codestrata</title>
<body style="font:15px/1.6 system-ui,sans-serif;max-width:560px;margin:15vh auto;padding:0 16px">
<h2>codestrata 主菜单</h2>
<p>请用启动 <code>codestrata app</code> 时终端里打印的链接打开（带 <code>?t=…</code>）。
打开一次之后这个浏览器就记住了，以后直接访问这个地址就行。</p></body>"""


def load_token(path: Path) -> str:
    """口令：第一次生成，之后一直用同一个（书签不会失效）；文件只有自己能读"""
    try:
        t = path.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t)
    return t


@dataclass
class App:
    """主菜单的全部状态：Handler 只通过它干活"""
    registry: _projects.Registry
    jobs: JobManager
    viewers: Viewers
    token: str
    # 改清单和起任务互斥：「没有任务在跑 → 移除」和「在清单里 → 起任务」都得是一口气做完的
    lock: threading.Lock = field(default_factory=threading.Lock)

    def card(self, repo: str) -> dict:
        """一个项目卡片：仓库状态 + 最近一个任务（不带输出，输出页面另外轮询）"""
        jobs = self.jobs.for_repo(repo)
        last = max(jobs, key=lambda j: j.started) if jobs else None
        return {**_projects.status(Path(repo)), "job": last.snapshot(since=last.n) if last else None}

    def token_ok(self, value: str | None) -> bool:
        return bool(value) and secrets.compare_digest(value.encode(), self.token.encode())


def _restart_after_scan(viewers: Viewers, job) -> None:
    """任务结束的回调（在任务标成结束之前跑）：扫描成功后，开着的图服务在原端口重启、读新的 index。
    结果写进这个任务的输出，页面上看得到"""
    if job.kind != "scan" or job.returncode != 0:
        return
    try:
        viewers.restart(job.repo)
    except ViewerError as e:
        job.add(f"[codestrata app] 图服务没能重启：{e}")


def _arg(q: dict, k: str) -> str:
    return (q.get(k) or [""])[0]


def _cookie(header: str, name: str) -> str | None:
    """从 Cookie 头里取一个值。不用 http.cookies：127.0.0.1 上别的端口的服务设的 cookie 也会带过来，
    其中一个格式它不认，它就把后面的全丢了"""
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def _symbols(repo: Path) -> dict | None:
    """仓库的静态索引里的符号（--phase 按 模块:函数 解析要用）；没 scan 过是 None"""
    return _payload.load_index(repo).get("symbols") if _payload.index_summary(repo) else None


class AppHandler(BaseHandler):
    app: App

    # ---- 鉴权 ----
    def _cookie_ok(self) -> bool:
        return self.app.token_ok(_cookie(self.headers.get("Cookie", ""), COOKIE))

    def _guard(self, path: str) -> bool:
        """不放行就直接回 403 并返回 False"""
        if not self._host_ok():
            self._send(403, b"bad host", "text/plain")
            return False
        if path.startswith("/api/") and not (self._cookie_ok() and self.headers.get(HEADER) == "1"):
            self._json({"error": "未授权：请用启动时打印的链接打开主菜单"}, 403)
            return False
        return True

    def _registered(self, repo: str | None) -> str | None:
        """只认清单里的项目（任务、打开图都是在本机执行东西，不接受任意路径）"""
        return repo if repo and self.app.registry.has(Path(repo)) else None

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        if not self._guard(path):
            return
        if path in ("/", ""):
            t = _arg(q, "t")
            if self.app.token_ok(t):
                return self._send(303, b"", headers={
                    "Location": "/",
                    "Set-Cookie": f"{COOKIE}={t}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"})
            if not self._cookie_ok():
                return self._send(200, _LOGIN_PAGE.encode())
            return self._asset("home.html")
        if not path.startswith("/api/"):
            return self._asset(path)

        if path == "/api/projects":
            return self._json([self.app.card(str(p)) for p in self.app.registry.paths()])
        if path == "/api/browse":
            try:
                return self._json(_projects.browse(_arg(q, "path") or None))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/symbols":
            repo = self._registered(_arg(q, "repo"))
            return self._json(_projects.find_symbols(Path(repo), _arg(q, "q")) if repo else [])
        if path == "/api/template":
            return self._template(_arg(q, "repo"), _arg(q, "run"))
        m = _JOB.match(path)
        if m and not m.group(2):
            job = self.app.jobs.get(m.group(1))
            if not job:
                return self._json({"error": "没有这个任务"}, 404)
            try:
                since = int(_arg(q, "since") or 0)
            except ValueError:
                since = 0
            return self._json(job.snapshot(since))
        return self._json({"error": "not found"}, 404)

    def _template(self, repo: str, run_id: str):
        repo = self._registered(repo)
        if not repo:
            return self._json({"error": "不是清单里的项目"}, 404)
        if not run_id:
            return self._json(TraceSpec(repo=repo, case="demo", command="").to_json())
        try:
            run = next((r for r in _runs.catalog(Path(repo)) if r.get("id") == run_id), None)
        except SystemExit as e:
            return self._json({"error": str(e)}, 503)
        if not run:
            return self._json({"error": f"没有 run {run_id}"}, 404)
        return self._json(TraceSpec.from_run(Path(repo), run).to_json())

    # ---- POST ----
    _POST = ("/api/projects", "/api/scan", "/api/trace", "/api/open")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._guard(path):
            return
        m = _JOB.match(path)
        if m and m.group(2):
            return self._json({"stopped": self.app.jobs.stop(m.group(1))})
        if path not in self._POST:
            return self._json({"error": "not found"}, 404)
        body, err = self._body_json()
        if err:
            return self._json({"error": err}, 400)
        if path == "/api/projects":
            try:
                repo = self.app.registry.add(Path(str(body.get("path") or "")))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json(self.app.card(str(repo)))
        repo = self._registered(str(body.get("repo") or ""))
        if not repo:
            return self._json({"error": "不是清单里的项目"}, 404)
        if path == "/api/scan":
            return self._start("scan", repo, lambda: scan_argv(Path(repo)))
        if path == "/api/trace":
            return self._start("trace", repo, lambda: self._trace_argv(repo, body))
        try:                                     # /api/open
            url = self.app.viewers.ensure(repo)
        except ViewerError as e:
            return self._json({"error": str(e)}, 500)
        self.app.registry.touch(Path(repo))
        return self._json({"url": url})

    def _trace_argv(self, repo: str, body: dict) -> list[str]:
        """表单 → trace 的命令行；表单不对就 ValueError。只有设了阶段才去读索引（大仓库的索引有十几 MB）"""
        spec = TraceSpec.from_json({**body, "repo": repo})
        spec.validate(_symbols(Path(repo)) if spec.phases else None)
        return spec.argv()

    def _start(self, kind: str, repo: str, make_argv):
        """先看有没有任务在跑（有就 409，不去读正在被重写的索引），再拼命令行、起任务。
        和移除项目互斥：不会给一个刚被移除的项目起任务"""
        with self.app.lock:
            if not self._registered(repo):
                return self._json({"error": "不是清单里的项目"}, 404)
            if self.app.jobs.active(repo):
                return self._json({"error": f"{repo} 已经有任务在跑，等它结束或先停掉"}, 409)
            try:
                job = self.app.jobs.start(kind, repo, make_argv())
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except Busy as e:
                return self._json({"error": str(e)}, 409)
            except JobError as e:
                return self._json({"error": str(e)}, 500)
        return self._json(job.snapshot())

    # ---- DELETE ----
    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        if not self._guard(u.path):
            return
        if u.path != "/api/projects":
            return self._json({"error": "not found"}, 404)
        repo = _arg(urllib.parse.parse_qs(u.query), "path")
        with self.app.lock:
            if self.app.jobs.active(repo):
                return self._json({"error": "这个项目还有任务在跑，先停掉"}, 409)
            removed = self.app.registry.remove(Path(repo))
        self.app.viewers.stop(repo)
        return self._json({"removed": removed})


def make_app(port: int, config: Path | None = None) -> App:
    """按配置目录装配主菜单（测试里给临时目录）"""
    config = config or _projects.config_dir()
    viewers = Viewers(f"http://127.0.0.1:{port}/", config / "logs")
    return App(registry=_projects.Registry(config / "projects.json"),
               jobs=JobManager(on_done=lambda job: _restart_after_scan(viewers, job)),
               viewers=viewers, token=load_token(config / "app-token"))


def _interrupt(*_) -> None:
    raise KeyboardInterrupt


def main(*, port: int, open_browser: bool = True) -> int:
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    except OSError as e:
        raise SystemExit(f"端口 {port} 用不了（{e.strerror}）：换一个，codestrata app --port N") from None
    AppHandler.app = app = make_app(port)
    url = f"http://127.0.0.1:{port}/?t={app.token}"
    print(f"codestrata app → {url}")
    print(f"  项目清单 {app.registry.path}（{len(app.registry.paths())} 个）")
    print(f"  这个链接带着口令：打开一次浏览器就记住了，之后直接访问 http://127.0.0.1:{port}/ 即可")
    print("  Ctrl+C 停止（会一起停掉由这里起的扫描、录制和图服务）", flush=True)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    signal.signal(signal.SIGTERM, _interrupt)      # kill 也走下面的 finally：别把子进程留下
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止：等还在跑的扫描 / 录制收尾（录制最多等 2 分钟，把 run 收好）…", flush=True)
    finally:
        srv.server_close()
        app.jobs.stop_all()
        app.viewers.stop_all()
    return 0
