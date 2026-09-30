"""浏览器里的交互：图、运行叠加、时间轴、时间顺序、对比、代码窗口、文件内查找（tests/web/specs/*.mjs）。

    .venv/bin/python tests/test_browser.py [spec 名…]
要 node（带全局 WebSocket，22+）和 Chrome / Chromium（找不到就跳过；CHROME=路径 可以指定）。
测试数据是仓库自带的假服务（tests/trace_cases/fake_repo）当场录的两次 run，不依赖开发机上的任何录制：
  A = truth：--events，--phase 切出 loop / forks 两个阶段（加上开头的 start），跨模块的调用多，时间顺序有得排
  B = offline：走另一批代码（fork 出工作进程），给对比用
serve 用随机端口，测完关掉；Chrome 由 tests/web/cdp.mjs 自己起、自己关。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from common import HERE, PY, cs, fresh, run_tests, tmpdir  # noqa: E402

WEB = HERE / "web"
_FX: dict = {}


def _tools():
    node = shutil.which("node")
    chrome = os.environ.get("CHROME") or next(
        (p for p in (shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")) if p), None)
    if node:
        v = subprocess.run([node, "-e", "process.stdout.write(String(typeof WebSocket))"], capture_output=True, text=True).stdout
        if v != "function":
            node = None                       # 老 node 没有全局 WebSocket
    return node, chrome


def _run_id(repo, case):
    base = repo / ".codestrata" / "runs"
    hits = sorted(p.name for p in base.iterdir() if p.name.endswith("-" + case))
    assert hits, f"没有 {case} 的 run"
    return hits[-1]


def fixture() -> dict:
    """录两次 run、起 serve（整个文件只做一次）"""
    if _FX:
        return _FX
    repo = fresh()
    cs("trace", repo, "--case", "truth", "--events",
       "--phase", "loop=fakesvc.truth:s_loop", "--phase", "forks=fakesvc.truth:s_fork", "--", PY, "-m", "fakesvc.truth")
    cs("trace", repo, "--case", "offline", "--events", "--", PY, "-m", "fakesvc.offline")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)], cwd=HERE.parent,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(base, timeout=2)
            break
        except OSError:
            time.sleep(0.1)
    _FX.update(repo=str(repo), base=base, srv=srv,
               a=_run_id(repo, "truth"), b=_run_id(repo, "offline"))
    fx = {k: v for k, v in _FX.items() if k != "srv"}
    path = tmpdir("cs-browser-") / "fixture.json"
    path.write_text(json.dumps(fx, ensure_ascii=False))
    _FX["path"] = str(path)
    return _FX


def _spec(name: str):
    node, chrome = _tools()
    if not (node and chrome):
        print(f"    （没有{'node 22+' if not node else 'Chrome / Chromium'}，跳过）")
        return
    fx = fixture()
    r = subprocess.run([node, str(WEB / "run.mjs"), chrome, fx["base"], fx["path"], name],
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    if os.environ.get("CS_VERBOSE"):
        print(out)
    assert r.returncode == 0 and out.rstrip().endswith("全部通过"), out[-6000:]


def test_graph():
    _spec("graph")


def test_overlay():
    _spec("overlay")


def test_timebar():
    _spec("timebar")


def test_timeorder():
    _spec("timeorder")


def test_compare():
    _spec("compare")


def test_viewer():
    _spec("viewer")


def test_findbar():
    _spec("findbar")


if __name__ == "__main__":
    try:
        rc = run_tests(globals(), sys.argv[1:])
    finally:
        if _FX.get("srv"):
            _FX["srv"].kill()
            _FX["srv"].wait()
    sys.exit(rc)
