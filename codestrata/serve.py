"""本地部署：前端静态文件 + /api。

    GET  /                        前端（codestrata/web/index.html）
    GET  /<asset>                 前端静态资源（app.css、*.js）
    GET  /api/app                 {home}：从主菜单（codestrata app）打开时主菜单的地址，页面上放回去的链接
    GET  /api/runs                录下的所有 run（按新到旧）+ 打开页面时默认选哪个（serve --hot）
    GET  /api/seq/edges?run=&open=   切面上每条边在 run 选的阶段里第一次 / 最后一次被调用的时刻和次数
                                  （模块图的「时间顺序」上色）
    GET  /api/path?run=           请求路径：run 选的阶段里每个进程、每个线程的函数级调用上下文树（path.py）
    GET  /api/lanes?run=&open=&cuts=
                                  按进程 · 线程分列：每列这条线程调到的切面节点和边，列之间谁起了谁、谁交给谁（lanes.py），
                                  加上节点信息、框、名字、子层（ui/lanesview.py）。open 是共用的切面，
                                  cuts（JSON [{"lanes": [列 id…], "open": [目录…]}…]）是各列自己的切面。
                                  每列的 names 是图上的名字 {id: 字}，合进来的线程原名在 thread_names
    GET  /api/graph?open=a,b&w=&run=
                                  一个切面上的图 + 某个 run 的 hot 叠加（open：展开着的目录，缺省是
                                  默认切面；w：页面上图框的宽度，按它排版；run：run id 或 case 名，
                                  可加 @阶段，空 = 只看静态图）。edge / refs 也接受 run=
    GET  /api/symbol/<key>        一个符号的源码片段
    GET  /api/file?f=&run=        整个文件 + 符号大纲（全文窗口用）；带 run 时还有这个文件里「只有 trace」的调用处
    GET  /api/outline?f=          一个文件的符号大纲（含方法），文件树按需展开
    GET  /api/refs?t=             一个定义被哪些地方引用（全文窗口里 Ctrl+点击定义）
    GET  /api/search-index        搜索栏要的全部名字（模块、文件、类 / 函数），前端自己搜
    GET  /api/reveal?node=&open=  让一个模块在图上露出来要展开哪些目录
    GET  /api/edge?a=&b=&run=&lane=
                                  一条边承载了什么：两端底下函数之间的调用，scan 写的和 trace 录到的；
                                  给了 lane（分列里的列 id）就只算这一列里的调用
    GET  /api/lanehot?run=&lane=  分列里一列的叠加（只算这一列里的调用）：节点详情里的次数、文件树、kernel 表用
    GET  /api/open?f=&l=          让本机编辑器跳到 file:line（要带 X-Codestrata 头：别的网页触发不了）
    GET  /code/<path>?l=N         整个文件，带行号锚点

只用标准库。只监听 127.0.0.1，Host 头必须是本机这个端口（防 DNS rebinding）；所有路径 realpath 后
必须落在仓库内。
"""
from __future__ import annotations

import html
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import cut as _cut
from . import lanes as _lanes
from . import path as _path
from . import runs as _runs
from . import seq as _seq
from .ui import edge as _edge
from .ui import graphview as _graphview
from .ui import lanesview as _lanesview
from .ui import load as _load
from .ui import search as _search
from .ui import source as _source

WEB = Path(__file__).resolve().parent / "web"
# 页面自己发的请求带着它：别的网页跨源设不了自定义头（这里不回 CORS），所以带着它的请求一定来自我们的页面。
# 会在本机做事的接口（开编辑器、主菜单的一切）都要它——光看 Host 挡不住普通网页用 <img src> 发的 GET
HEADER = "X-Codestrata"
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
<a href="/api/open?f={q}&l={line}" onclick="fetch(this.href,{{headers:{{'{HEADER}':'1'}}}});return false">在编辑器打开</a>
<a href="/">← 回到图</a></header><table>{rows}</table>
<script>location.hash||(location.hash='#L{line}');</script>"""


def asset(name: str) -> tuple[bytes, str] | None:
    """前端静态文件（web/ 下）：(内容, Content-Type)；不在 web/ 里或不存在就是 None"""
    f = (WEB / name).resolve()
    if not str(f).startswith(str(WEB) + os.sep) or not f.is_file():
        return None
    ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript",):
        ctype += "; charset=utf-8"
    return f.read_bytes(), ctype


class BaseHandler(BaseHTTPRequestHandler):
    """两个本地服务（serve 和 app）共用的：发响应、发 JSON、读 JSON 请求体、静默日志"""

    def log_message(self, fmt, *a):
        if os.environ.get("CODESTRATA_VERBOSE"):
            super().log_message(fmt, *a)

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _from_page(self) -> bool:
        """请求是我们自己的页面发的（带着 HEADER）"""
        return self.headers.get(HEADER) == "1"

    def _host_ok(self) -> bool:
        """Host 头必须是本机的这个端口：防 DNS rebinding（别的域名解析到 127.0.0.1，浏览器就会把
        那个网页的请求发到这里来；Host 头还是那个域名）。两个本地服务都能执行本机操作（开编辑器、
        跑命令），都要挡"""
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _body_json(self, limit: int = 2_000_000):
        """请求体按 JSON 对象读：(dict, None) 或 (None, 错误说明)"""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            return None, "body 为空或过大"
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "body 不是合法 JSON"
        return (body, None) if isinstance(body, dict) else (None, "body 要是一个 JSON 对象")

    def _asset(self, path: str):
        """GET 前端静态文件；/ 是 index"""
        a = asset("index.html" if path in ("/", "") else path.lstrip("/"))
        return self._send(200, *a) if a else self._send(404, b"not found", "text/plain")


class Handler(BaseHandler):
    repo: Path
    idx: dict
    default_run: str | None = None   # serve --hot 解析成的「完整 id@阶段」：页面没指定时先选它
    home: str | None = None          # 从主菜单（codestrata app）打开的：页面上放一个回主菜单的链接
    _graphs: dict = {}          # (切面, 宽度, run) → 已算好的 /api/graph 结果
    _search: bytes | None = None  # /api/search-index，算一次
    _hots: dict = {}            # (run id, 阶段, (counts、run.json 的 mtime)) → (hot, meta)；最近 8 个
    _lanehots: dict = {}        # (run id, 阶段, counts 的 mtime, 列) → 分列里一列的 hot；最近 16 个
    _stale: dict = {}           # (run id, detail 的 mtime) → 录制后改过几个文件（下拉列表用）
    _lock = threading.Lock()

    # ---- 基础 ----
    def _in_repo(self, rel: str) -> Path | None:
        try:
            p = (self.repo / rel).resolve()
        except OSError:
            return None
        root = self.repo.resolve()
        return p if str(p).startswith(str(root) + os.sep) and p.is_file() else None

    def _hot(self, q: dict):
        """请求里的 run=（完整 id 或 case 名，可加 @阶段；没有 / 空 = 静态图）→ (hot, meta, 缓存键)。
        按 (run id, 阶段, counts.json.gz 和 run.json 的 mtime) 缓存：counts 只在 runs merge 时才会变，
        run.json 在改 tag / 备注时变（meta 里带着它们）。找不到这个 run 抛 LookupError。"""
        ref = (q.get("run") or [""])[0].strip()
        if not ref:
            return None, None, None
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
        except SystemExit as e:
            raise LookupError(str(e)) from None
        try:
            # counts 变了（runs merge）要重算；run.json 变了（改 tag / 备注）meta 也要换
            mt = ((rd / "counts.json.gz").stat().st_mtime_ns, (rd / "run.json").stat().st_mtime_ns)
        except OSError:
            raise LookupError(f"run {run['id']} 还没有计数（还在录，或录制中断了要 runs merge）") from None
        key = (run["id"], phase, mt)
        with Handler._lock:
            hit = Handler._hots.get(key)
        if hit is None:
            try:
                hot, meta = _runs.load(self.repo, self.idx, run["id"] + (f"@{phase}" if phase else ""))
            except SystemExit as e:
                raise LookupError(str(e)) from None
            hit = (hot, meta)
            with Handler._lock:
                Handler._hots[key] = hit
                while len(Handler._hots) > 8:
                    Handler._hots.pop(next(iter(Handler._hots)))
        return hit[0], hit[1], key

    def _first(self, q: dict, hot: dict | None, lane: str | None = None) -> dict | None:
        """边详情按先后排要的：这个 run（阶段）里每个函数对第一次调用的时刻（给了 lane 只算这一列）；没录时序事件的是 None"""
        ref = (q.get("run") or [""])[0].strip()
        if not hot or not ref:
            return None
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
            return _path.first_calls(self.idx, rd, run, phase, hot, lane=lane)
        except (SystemExit, LookupError, OSError, ValueError):
            return None

    def _lane_hot(self, q: dict, lane: str) -> dict:
        """分列里一列的叠加（load.load_lane）：按 (run id, 阶段, counts.json.gz 的 mtime, 列) 缓存最近 16 个。
        没选 run、找不到 run / 列、没有时序事件抛 LookupError，span 读不出来抛 OSError / ValueError"""
        ref = (q.get("run") or [""])[0].strip()
        if not ref:
            raise LookupError("要先选一个 run（录了时序事件的）")
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
            mt = (rd / "counts.json.gz").stat().st_mtime_ns
        except SystemExit as e:
            raise LookupError(str(e)) from None
        except OSError:
            raise LookupError("这个 run 还没有计数（还在录，或录制中断了要 runs merge）") from None
        key = (run["id"], phase, mt, lane)
        with Handler._lock:
            hit = Handler._lanehots.get(key)
        if hit is None:
            try:
                hit = _load.load_lane(self.repo, self.idx, run["id"] + (f"@{phase}" if phase else ""), lane)
            except SystemExit as e:
                raise LookupError(str(e)) from None
            with Handler._lock:
                Handler._lanehots[key] = hit
                while len(Handler._lanehots) > 16:
                    Handler._lanehots.pop(next(iter(Handler._lanehots)))
        return hit

    def _lanehot(self, q: dict):
        """/api/lanehot：分列里一列的叠加，只给节点详情要的（各单元 / 符号 / 文件的次数、kernel 的次数和 GPU 时间）"""
        lane = (q.get("lane") or [""])[0].strip()
        if not lane:
            return self._json({"error": "要给 lane（分列里的列 id）"}, 400)
        try:
            h = self._lane_hot(q, lane)
        except LookupError as e:
            return self._json({"error": str(e)}, 404)
        except (OSError, ValueError) as e:
            return self._json({"error": _seq.unreadable(e, (q.get("run") or [""])[0])}, 500)
        return self._json({"lane": lane, "run": h["run"], "packages": h["packages"], "symbols": h["symbols"],
                           "files": h["files"], "kernels": h["kernels"], "lines_approx": h["lines_approx"]})

    def _path(self, q: dict):
        """/api/path：请求路径（path.request_path）。run 必填，@阶段（或 @t=）决定时间段"""
        ref = (q.get("run") or [""])[0].strip()
        if not ref:
            return self._json({"error": "要先选一个 run（录了时序事件的）"}, 400)
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
            hot = self._hot(q)[0]
            return self._json(_path.request_path(self.idx, rd, run, phase, hot))
        except (SystemExit, LookupError) as e:
            return self._json({"error": str(e)}, 404)
        except (OSError, ValueError) as e:
            return self._json({"error": _seq.unreadable(e, run["id"])}, 500)

    def _lanes(self, q: dict):
        """/api/lanes：按进程 · 线程分列（lanes.build + lanesview.decorate）。run 必填，@阶段（或 @t=）决定时间段，
        open 是共用的切面，cuts 是各列自己的切面"""
        ref = (q.get("run") or [""])[0].strip()
        if not ref:
            return self._json({"error": "要先选一个 run（录了时序事件的）"}, 400)
        raw = (q.get("open") or [None])[0]
        open_ = None if raw is None else sorted(_cut.norm_open(self.idx, [o for o in raw.split(",") if o]))
        try:
            cuts = _lanesview.parse_cuts(self.idx, (q.get("cuts") or [None])[0])
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        run = None
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
            hot = self._hot(q)[0]
            L = _lanes.build(self.idx, rd, run, phase, hot, open_, cuts=cuts,
                             text=lambda f, l: _source.line_text(self.repo, f, l).strip()[:160])
            return self._json(_lanesview.decorate(self.idx, hot, L, open_))
        except (SystemExit, LookupError) as e:
            return self._json({"error": str(e)}, 404)
        except (OSError, ValueError) as e:
            # 还没认出是哪个 run 就出错（读 runs 目录失败）：没有 run id 可写
            return self._json({"error": _seq.unreadable(e, run["id"]) if run else f"{type(e).__name__}: {e}"}, 500)

    def _seq(self, path: str, q: dict):
        """/api/seq/edges：模块图「时间顺序」上色要的数据。run 必填（run id 或 case 名，@阶段决定时间窗）。"""
        ref = (q.get("run") or [""])[0].strip()
        if not ref:
            return self._json({"error": "要先选一个 run（录了时序事件的）"}, 400)
        try:
            run, rd, phase = _runs.resolve(self.repo, ref)
        except SystemExit as e:
            return self._json({"error": str(e)}, 404)
        raw = (q.get("open") or [None])[0]
        open_ = None if raw is None else [o for o in raw.split(",") if o]
        open_ = sorted(_cut.norm_open(self.idx, open_))
        try:
            hot = self._hot(q)[0]                  # 带着录制时的键 → 现在的键（改过的文件里函数挪了位置）
        except LookupError as e:
            return self._json({"error": str(e)}, 404)
        try:
            return self._json(_seq.edge_times(self.idx, rd, run, open_=open_, phase=phase,
                                              keymap=(hot or {}).get("keymap"), redirect=(hot or {}).get("redirect")))
        except (LookupError, FileNotFoundError) as e:
            return self._json({"error": str(e) if isinstance(e, LookupError)
                               else "这个 run 没有录时序事件（录的时候用了 --no-events，或者被录的 Python 低于 3.12），或者 span 没整理好（runs merge 重来）"}, 404)
        except (OSError, ValueError) as e:            # span 文件坏了：说清楚，不让连接直接断
            return self._json({"error": _seq.unreadable(e, run["id"])}, 500)

    def _runs(self) -> dict:
        """/api/runs：下拉列表要的摘要，新的在前。「录制后改过几个文件」要读 detail.json 和当前
        index 比，按 (run id, detail 的 mtime) 缓存。"""
        out = []
        for r in _runs.catalog(self.repo):
            rd = _runs.runs_dir(self.repo) / r["id"]
            changed = None
            try:
                mt = (rd / "detail.json").stat().st_mtime_ns
                key = (r["id"], mt)
                with Handler._lock:
                    changed = Handler._stale.get(key)
                if changed is None:
                    fs = _runs.file_state(self.repo, self.idx, _runs.read_json(rd / "detail.json"))
                    changed = {"changed": sum(1 for v in fs.values() if v in ("changed", "gone")),
                               "mismatch": sum(1 for v in fs.values() if v == "mismatch")}
                    with Handler._lock:
                        Handler._stale[key] = changed
            except (OSError, ValueError):
                pass
            sm = r.get("summary") or {}
            ev = r.get("events")
            out.append({"id": r["id"], "case": r.get("case"), "status": r.get("status_shown") or r.get("status"),
                        "problems": r.get("problems") or [], "created": r.get("created"),
                        "duration_s": r.get("duration_s"), "git": (r.get("git") or {}).get("commit"),
                        "tags": r.get("tags") or [], "note": r.get("note") or "",
                        "phases": [{"name": p["name"], "n_funcs": p.get("n_funcs")} for p in r.get("phases") or []],
                        "n_procs_active": sm.get("n_procs_active"), "n_funcs": sm.get("n_funcs"),
                        "events": bool(ev and not ev.get("error")), "events_error": bool(ev and ev.get("error")),
                        "stale": changed,
                        "loadable": (rd / "counts.json.gz").is_file(), "migrated": bool(r.get("migrated_from"))})
        return {"default": Handler.default_run, "runs": out}

    # ---- GET ----
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"bad host", "text/plain")
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)   # ?open= 是「什么都不展开」，不是缺省
        path = u.path

        if path == "/api/app":
            return self._json({"home": self.home})

        if path == "/api/runs":
            try:
                return self._json(self._runs())
            except SystemExit as e:                  # runs/ 是软链、指向的盘没挂上
                return self._json({"error": str(e)}, 503)

        if path == "/api/seq/edges":
            return self._seq(path, q)

        if path == "/api/path":
            return self._path(q)

        if path == "/api/lanes":
            return self._lanes(q)

        if path == "/api/lanehot":
            return self._lanehot(q)

        hot = hot_meta = hot_key = None
        if path in ("/api/graph", "/api/edge", "/api/refs", "/api/file"):
            try:
                hot, hot_meta, hot_key = self._hot(q)
            except LookupError as e:
                return self._json({"error": str(e)}, 404)

        if path == "/api/graph":
            raw = (q.get("open") or [None])[0]
            open_ = None if raw is None else [o for o in raw.split(",") if o]
            # 图框多宽就按多宽排版（按 40px 取整，窗口拖一点点不必重排）
            try:
                width = max(700, min(4000, round(float((q.get("w") or ["1180"])[0]) / 40) * 40))
            except (ValueError, OverflowError):       # w=abc / w=inf / w=1e999：按默认宽度
                width = 1180
            # run 也进缓存键：同一个切面，换一个 run 叠加就不一样（hot_key 里有 counts 的 mtime，
            # runs merge 重算之后自然换一份）
            key = (("\u0000" if open_ is None else ",".join(sorted(open_))) + f"@{width}", hot_key)
            body = Handler._graphs.get(key)
            if body is None:
                body = json.dumps(_graphview.graph_payload(
                    self.repo, self.idx, hot=hot, hot_meta=hot_meta, open_=open_, width=width),
                    ensure_ascii=False).encode()
                with Handler._lock:
                    Handler._graphs[key] = body
                    while len(Handler._graphs) > 32:   # 切面可以任意组合，缓存只留最近的一些
                        Handler._graphs.pop(next(iter(Handler._graphs)))
            return self._send(200, body, "application/json; charset=utf-8")

        if path.startswith("/api/symbol/"):
            key = urllib.parse.unquote(path[len("/api/symbol/"):])
            s = _source.symbol_source(self.repo, self.idx, key)
            return self._json(s) if s else self._json({"error": "unknown symbol"}, 404)

        if path == "/api/edge":
            a, b = (q.get("a") or [""])[0], (q.get("b") or [""])[0]
            if not _cut.is_node(self.idx, a) or not _cut.is_node(self.idx, b):
                return self._json({"error": "unknown node"}, 404)
            lane = (q.get("lane") or [""])[0].strip() or None
            if lane:                                  # 分列里的边：只算这一列里的调用
                try:
                    hot = self._lane_hot(q, lane)
                except LookupError as e:
                    return self._json({"error": str(e)}, 404)
                except (OSError, ValueError) as e:
                    return self._json({"error": _seq.unreadable(e, (q.get("run") or [""])[0])}, 500)
            d = _edge.edge_detail(self.repo, self.idx, a, b, hot, first=self._first(q, hot, lane))
            if lane:
                d["lane"] = lane
            return self._json(d)

        if path == "/api/search-index":
            if Handler._search is None:
                Handler._search = json.dumps(_search.search_index(self.idx), ensure_ascii=False,
                                             separators=(",", ":")).encode()
            return self._send(200, Handler._search, "application/json; charset=utf-8")

        if path == "/api/reveal":
            raw = (q.get("open") or [None])[0]
            open_ = None if raw is None else [o for o in raw.split(",") if o]
            r = _search.reveal(self.idx, (q.get("node") or [""])[0], open_)
            return self._json({"open": r}) if r is not None else self._json({"error": "unknown node"}, 404)

        if path == "/api/refs":
            r = _source.refs(self.repo, (q.get("t") or [""])[0], hot)
            return self._json(r) if r else self._json({"error": "unknown target"}, 404)

        if path == "/api/outline":
            rel = (q.get("f") or [""])[0]
            ol = _source.file_outline(self.repo, self.idx, rel) if self._in_repo(rel) else None
            return self._json(ol) if ol else self._json({"error": "不是已扫描的文件"}, 404)

        if path == "/api/file":
            rel = (q.get("f") or [""])[0]
            if not self._in_repo(rel):
                return self._json({"error": "bad path"}, 404)
            fv = _source.file_view(self.repo, self.idx, rel, hot)
            return self._json(fv) if fv else self._json({"error": "不是已扫描的文件"}, 404)

        if path == "/api/open":
            if not self._from_page():            # 会在本机启动编辑器：只认我们自己的页面
                return self._send(403, b"forbidden", "text/plain")
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

        return self._asset(path)



def main(repo: Path, *, port: int = 8900, hot: str | None = None, home: str | None = None) -> int:
    idx = _load.load_index(repo)
    Handler.repo, Handler.idx, Handler.home = repo, idx, home
    Handler._graphs, Handler._hots, Handler._stale, Handler._lanehots = {}, {}, {}, {}
    Handler._search = None
    # --hot 只决定页面打开时先选哪个 run（页面上随时能换）；启动时先加载一遍：写错了当场报出来
    h = hm = None
    if hot:
        h, hm = _load.load_hot(repo, idx, hot)
        Handler.default_run = hm["run_id"] + (f"@{hm['phase']}" if hm.get("phase") else "")
    else:
        Handler.default_run = None
    try:
        n_runs = len(_runs.catalog(repo)) if (repo / ".codestrata").is_dir() else 0
    except SystemExit as e:                   # runs/ 是软链、盘没挂上：静态图照样能看
        print(f"  ⚠ {e}")
        n_runs = 0
    # index 落后多少：图和搜索用的是启动时的 index，落后了就说一声
    lag = _source.index_lag(repo)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ed = _editor()
    print(f"codestrata serve → http://127.0.0.1:{port}/")
    print(f"  仓库   {repo}")
    print(f"  前端   {WEB}")
    n_default = len(_cut.visible(_cut.view(idx, set(idx.get("default_open") or []))))
    print(f"  图     默认切面 {n_default} 个节点（{len(idx['packages'])} 个文件级模块，点节点可展开 / 收起）")
    print(f"  编辑器 {' '.join(ed) if ed else '没找到，跳转按钮会返回 501'}")
    print(f"  run    录下的 {n_runs} 个，页面上方「运行」里切换（serve 开着时新录的也看得到）")
    if lag:
        print(f"  注意   scan 之后改过 {lag} 个文件：图和搜索还是 scan 时的样子，重新 scan 后重启 serve")
    if h:
        print(f"  默认   run {hm['run_id']}" + (f" @{hm['phase']}" if hm.get("phase") else "")
              + f"（case {hm['case']}，{hm['status']}），{len(h['packages'])} 个模块跑到")
    print("  Ctrl+C 停止", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
    return 0
