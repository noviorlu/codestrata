"""本地服务：图 + 带行号锚点的源码 + 一键跳编辑器。

这是「点节点跳到代码」真正能用的那一半。artifact / 静态 HTML 里做不到，
因为浏览器沙箱不放行 vscode:// 这类 scheme；而从 localhost 页面出发，
普通 http 链接就够了——把跳转这件事交给服务端去 exec 编辑器。

只用标准库。路径一律校验必须落在仓库内，且只监听 127.0.0.1。
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
    rows = []
    for i, ln in enumerate(src, 1):
        cls = ' class="hi"' if i == line else ""
        rows.append(f'<tr{cls} id="L{i}"><td class="n"><a href="#L{i}">{i}</a></td>'
                    f'<td class="c">{html.escape(ln) or "&nbsp;"}</td></tr>')
    return f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(rel)}:{line}</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--fg:#11161f;--mut:#8a94a3;--hi:#fdf3e2;--line:#e6e9ef}}
@media(prefers-color-scheme:dark){{:root{{--bg:#10141b;--fg:#e6eaf1;--mut:#697485;--hi:#2a2113;--line:#242b37}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:12px/1.62 ui-monospace,Menlo,monospace}}
header{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:9px 14px;
 display:flex;gap:12px;align-items:center;font-size:12px}}
header a{{color:inherit}} header .sp{{margin-left:auto}}
table{{border-collapse:collapse;width:100%}}
td.n{{text-align:right;color:var(--mut);padding:0 10px 0 14px;user-select:none;width:1%;white-space:nowrap;
 border-right:1px solid var(--line)}}
td.n a{{color:inherit;text-decoration:none}}
td.c{{padding:0 14px;white-space:pre}}
tr.hi{{background:var(--hi)}}
</style>
<header><b>{html.escape(rel)}</b>:{line}
<span class="sp"></span>
<a href="/open?f={urllib.parse.quote(rel)}&l={line}" onclick="fetch(this.href);return false">在编辑器打开</a>
<a href="/">← 回到图</a></header>
<table>{''.join(rows)}</table>
<script>location.hash||(location.hash='#L{line}');</script>
"""


class Handler(BaseHTTPRequestHandler):
    repo: Path
    page: bytes

    def log_message(self, *a):            # 别把控制台刷满
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safe(self, rel: str) -> Path | None:
        """只允许仓库内的路径。"""
        try:
            p = (self.repo / rel).resolve()
        except OSError:
            return None
        root = self.repo.resolve()
        return p if str(p).startswith(str(root) + os.sep) and p.is_file() else None

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._send(200, self.page)
        if u.path == "/open":
            rel = (q.get("f") or [""])[0]
            line = int((q.get("l") or ["1"])[0])
            p = self._safe(rel)
            ed = _editor()
            if not p:
                return self._send(400, b"bad path")
            if not ed:
                return self._send(501, "没找到编辑器 CLI（code/cursor/...）".encode())
            try:
                subprocess.Popen(ed + [f"{p}:{line}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                return self._send(500, str(exc).encode())
            return self._send(204, b"")
        if u.path.startswith("/code/"):
            rel = urllib.parse.unquote(u.path[len("/code/"):])
            line = int((q.get("l") or ["1"])[0])
            if not self._safe(rel):
                return self._send(404, b"not found")
            return self._send(200, _code_page(self.repo, rel, line).encode())
        self._send(404, b"not found")


def main(repo: Path, *, port: int = 8900, hot: str | None = None) -> int:
    from . import layout as _layout
    from . import render as _render
    from . import trace as _trace
    from .__main__ import _load_index, _outdir

    idx = _load_index(repo)
    g = _layout.build(idx, lanes=9, min_files=1)
    h = hm = None
    if hot:
        tp = _outdir(repo) / f"trace-{hot}.json"
        if tp.exists():
            tr = json.loads(tp.read_text(encoding="utf-8"))
            h = _trace.to_package_graph(tr, idx)
            hm = {"case": tr.get("case"), "cmd": tr.get("cmd"),
                  "n_procs": tr.get("n_procs"), "unmapped": h.get("unmapped")}
    page = _render.render(idx, g, repo, hot=h, hot_meta=hm).encode()

    Handler.repo = repo
    Handler.page = page
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ed = _editor()
    print(f"codestrata serve → http://127.0.0.1:{port}/")
    print(f"  仓库: {repo}")
    print(f"  编辑器: {' '.join(ed) if ed else '（没找到，跳转按钮会返回 501）'}")
    print("  Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
    return 0
