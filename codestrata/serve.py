"""本地部署：前端静态文件 + /api。

    GET  /                        前端（codestrata/web/index.html）
    GET  /<asset>                 前端静态资源（app.css、*.js）
    GET  /api/graph?open=a,b      一个切面上的图 + hot 叠加（open：展开着的目录，缺省是默认切面）
    GET  /api/notes/<target>      解读（含 stale 判定）
    GET  /api/status?ids=a,b      一批节点的解读状态 noted / stale / todo（图上的徽标）
    PUT  /api/notes/<target>      写入解读        ← LLM agent 从这里介入
    GET  /api/tasks               还没解读 / 已过期的目标，按架构高度自底向上
    GET  /api/pack/<target>       给 agent 的输入包（纯文本 Markdown）
    GET  /api/symbol/<key>        一个符号的源码片段
    GET  /api/file?f=             整个文件 + 符号大纲（全文窗口用）
    GET  /api/outline?f=          一个文件的符号大纲（含方法），文件树按需展开
    GET  /api/edge?a=&b=          一条边承载了什么：用到了对方哪些符号、runtime 调了哪些
    GET  /api/open?f=&l=          让本机编辑器跳到 file:line
    GET  /code/<path>?l=N         整个文件，带行号锚点

只用标准库。只监听 127.0.0.1；所有路径 realpath 后必须落在仓库内。
"""
from __future__ import annotations

import html
import json
import mimetypes
import os
import shutil
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import cut as _cut
from . import notes as _notes
from . import payload as _payload

WEB = Path(__file__).resolve().parent / "web"
EDITORS = ("code", "cursor", "codium", "code-insiders", "subl")


def _editor() -> list[str] | None:
    for e in EDITORS:
        p = shutil.which(e)
        if p:
            return [p, "-g"] if e != "subl" else [p]
    return None


def _code_page(repo: Path, rel: str, line: int) -> str:
    try:
        src = (repo / rel).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError as exc:
        return f"<pre>读不到 {html.escape(rel)}: {html.escape(str(exc))}</pre>"
    rows = "".join(
        f'<tr{" class=hi" if i == line else ""} id="L{i}"><td class="n"><a href="#L{i}">{i}</a></td>'
        f'<td class="c">{html.escape(ln) or "&nbsp;"}</td></tr>'
        for i, ln in enumerate(src, 1))
    q = urllib.parse.quote(rel)
    return f"""<!doctype html><meta charset="utf-8"><title>{html.escape(rel)}:{line}</title>
<style>:root{{color-scheme:light dark;--bg:#f6f7f9;--fg:#11161f;--mut:#8a94a3;--hi:#fdf3e2;--line:#e6e9ef}}
@media(prefers-color-scheme:dark){{:root{{--bg:#10141b;--fg:#e6eaf1;--mut:#697485;--hi:#2a2113;--line:#242b37}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:12px/1.62 ui-monospace,Menlo,monospace}}
header{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:9px 14px;display:flex;gap:12px}}
header a{{color:inherit}}.sp{{margin-left:auto}}table{{border-collapse:collapse;width:100%}}
td.n{{text-align:right;color:var(--mut);padding:0 10px 0 14px;user-select:none;width:1%;border-right:1px solid var(--line)}}
td.n a{{color:inherit;text-decoration:none}}td.c{{padding:0 14px;white-space:pre}}tr.hi{{background:var(--hi)}}</style>
<header><b>{html.escape(rel)}</b>:{line}<span class="sp"></span>
<a href="/api/open?f={q}&l={line}" onclick="fetch(this.href);return false">在编辑器打开</a>
<a href="/">← 回到图</a></header><table>{rows}</table>
<script>location.hash||(location.hash='#L{line}');</script>"""


class Handler(BaseHTTPRequestHandler):
    repo: Path
    idx: dict
    hot: dict | None = None
    hot_meta: dict | None = None
    _graphs: dict = {}          # 切面（open 的规范化字符串）→ 已算好的 /api/graph 结果

    def log_message(self, fmt, *a):
        if os.environ.get("CODESTRATA_VERBOSE"):
            super().log_message(fmt, *a)

    # ---- 基础 ----
    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _in_repo(self, rel: str) -> Path | None:
        try:
            p = (self.repo / rel).resolve()
        except OSError:
            return None
        root = self.repo.resolve()
        return p if str(p).startswith(str(root) + os.sep) and p.is_file() else None

    def _target(self, prefix: str, path: str) -> str | None:
        t = urllib.parse.unquote(path[len(prefix):])
        # 只接受目录树上真实存在的节点（和总览这个保留名），防止借 target 写出仓库外的文件
        return t if (_cut.is_node(self.idx, t) or t == _notes.OVERVIEW) else None

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)   # ?open= 是「什么都不展开」，不是缺省
        path = u.path

        if path == "/api/graph":
            raw = (q.get("open") or [None])[0]
            open_ = None if raw is None else [o for o in raw.split(",") if o]
            key = "\u0000" if open_ is None else ",".join(sorted(open_))
            if key not in Handler._graphs:
                if len(Handler._graphs) > 32:          # 切面可以任意组合，缓存只留最近的一些
                    Handler._graphs.pop(next(iter(Handler._graphs)))
                Handler._graphs[key] = json.dumps(_payload.graph_payload(
                    self.repo, self.idx, hot=self.hot, hot_meta=self.hot_meta, open_=open_),
                    ensure_ascii=False).encode()
            return self._send(200, Handler._graphs[key], "application/json; charset=utf-8")

        if path.startswith("/api/notes/"):
            t = self._target("/api/notes/", path)
            if not t:
                return self._json({"error": "unknown target"}, 404)
            nt = _notes.load(self.repo, self.idx, t)
            nt["problems"] = _notes.verify(self.repo, self.idx, t)
            return self._json(nt)

        if path == "/api/status":
            ids = [t for t in (q.get("ids") or [""])[0].split(",")
                   if t and (t == _notes.OVERVIEW or _cut.is_node(self.idx, t))]
            return self._json(_notes.status(self.repo, self.idx, ids))

        if path == "/api/tasks":
            return self._json(_notes.tasks(self.repo, self.idx))

        if path.startswith("/api/pack/"):
            t = self._target("/api/pack/", path)
            if not t:
                return self._send(404, b"unknown target", "text/plain; charset=utf-8")
            txt = _notes.prompt_pack(self.repo, self.idx, t, hot=self.hot)
            return self._send(200, txt.encode(), "text/markdown; charset=utf-8")

        if path.startswith("/api/symbol/"):
            key = urllib.parse.unquote(path[len("/api/symbol/"):])
            s = _payload.symbol_source(self.repo, self.idx, key)
            return self._json(s) if s else self._json({"error": "unknown symbol"}, 404)

        if path == "/api/edge":
            a, b = (q.get("a") or [""])[0], (q.get("b") or [""])[0]
            if not _cut.is_node(self.idx, a) or not _cut.is_node(self.idx, b):
                return self._json({"error": "unknown node"}, 404)
            return self._json(_payload.edge_detail(self.repo, self.idx, a, b, self.hot))

        if path == "/api/outline":
            rel = (q.get("f") or [""])[0]
            ol = _payload.file_outline(self.repo, self.idx, rel) if self._in_repo(rel) else None
            return self._json(ol) if ol else self._json({"error": "不是已扫描的文件"}, 404)

        if path == "/api/file":
            rel = (q.get("f") or [""])[0]
            if not self._in_repo(rel):
                return self._json({"error": "bad path"}, 404)
            fv = _payload.file_view(self.repo, self.idx, rel)
            return self._json(fv) if fv else self._json({"error": "不是已扫描的文件"}, 404)

        if path == "/api/open":
            rel = (q.get("f") or [""])[0]
            try:
                line = int((q.get("l") or ["1"])[0])
            except ValueError:
                line = 1
            p, ed = self._in_repo(rel), _editor()
            if not p:
                return self._send(400, b"bad path", "text/plain")
            if not ed:
                return self._send(501, "没找到编辑器 CLI（code / cursor …）".encode(), "text/plain; charset=utf-8")
            subprocess.Popen(ed + [f"{p}:{line}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self._send(204, b"")

        if path.startswith("/code/"):
            rel = urllib.parse.unquote(path[len("/code/"):])
            try:
                line = int((q.get("l") or ["1"])[0])
            except ValueError:
                line = 1
            if not self._in_repo(rel):
                return self._send(404, b"not found", "text/plain")
            return self._send(200, _code_page(self.repo, rel, line).encode())

        # ---- 前端静态资源 ----
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (WEB / name).resolve()
        if not str(f).startswith(str(WEB) + os.sep) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        return self._send(200, f.read_bytes(), ctype)

    # ---- PUT：写解读 ----
    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/api/notes/"):
            return self._send(404, b"not found", "text/plain")
        t = self._target("/api/notes/", u.path)
        if not t:
            return self._json({"error": "unknown target"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 2_000_000:
            return self._json({"error": "body 为空或过大"}, 400)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "body 不是合法 JSON"}, 400)
        md = (body.get("md") or "").strip()
        if not md:
            return self._json({"error": "md 为空"}, 400)
        meta = {k: str(v) for k, v in (body.get("meta") or {}).items()
                if k in ("written_by", "status", "confidence")}
        meta.setdefault("written_by", "web")
        return self._json(_notes.save(self.repo, self.idx, t, md, meta=meta))


def main(repo: Path, *, port: int = 8900, hot: str | None = None) -> int:
    idx = _payload.load_index(repo)
    h, hm = _payload.load_hot(repo, idx, hot)
    Handler.repo, Handler.idx, Handler.hot, Handler.hot_meta = repo, idx, h, hm
    Handler._graphs = {}
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ed = _editor()
    todo = _notes.tasks(repo, idx)
    print(f"codestrata serve → http://127.0.0.1:{port}/")
    print(f"  仓库   {repo}")
    print(f"  前端   {WEB}")
    n_default = len(_cut.visible(_cut.view(idx, set(idx.get("default_open") or []))))
    print(f"  图     默认切面 {n_default} 个节点（{len(idx['packages'])} 个文件级模块，点节点可展开 / 收起）")
    print(f"  解读   {_notes.notes_root(repo)}  （待写 {len(todo)}）")
    print(f"  编辑器 {' '.join(ed) if ed else '没找到，跳转按钮会返回 501'}")
    if h:
        print(f"  hot    case={hm['case']}，{len(h['packages'])} 个模块跑到")
    print("  Ctrl+C 停止", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
    return 0
