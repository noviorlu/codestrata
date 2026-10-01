"""浏览器里的交互：图、运行叠加、时间轴、时间顺序、代码窗口、文件内查找（tests/web/specs/*.mjs）。

    .venv/bin/python tests/test_browser.py [spec 名…]
要 node（带全局 WebSocket，22+）和 Chrome / Chromium（找不到就跳过；CHROME=路径 可以指定）。
测试数据是仓库自带的假服务（tests/trace_cases/fake_repo）当场录的两次 run，不依赖开发机上的任何录制：
  A = truth：--events，--phase 切出 loop / forks 两个阶段（加上开头的 start），跨模块的调用多，时间顺序有得排
  B = offline：另一个 run，给「换 run」用
另有一个只 scan 的小仓库（_CUT：嵌套目录、一个又有子目录又有十几个文件的目录），给展开 / 收起、搜索定位用（base2）；
再一个录过的小仓库（_DYN：runner 经 self.model.forward 调到按字符串加载的类，代码里看不出），给虚线边用（base3）；
它录了两次，第二次去掉调用行当老 run。
serve 用随机端口，测完关掉；Chrome 由 tests/web/cdp.mjs 自己起、自己关。
"""
from __future__ import annotations

import gzip
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


# 切面用的仓库：cx/ 下有子目录、子目录的子目录；big/ 直接放着 14 个文件又有子目录，展开后是「本层文件」节点
_CUT = {"cx/__init__.py": "", "cx/app.py": "from cx.sansio import app as a\nfrom cx.ops import util\n\n\ndef run():\n    return a.go() + util.u()\n",
        "cx/sansio/__init__.py": "", "cx/sansio/app.py": "def go():\n    return 1\n",
        "cx/ops/__init__.py": "", "cx/ops/util.py": "from cx.ops.kernels import k\n\n\ndef u():\n    return k.kk()\n",
        "cx/ops/kernels/__init__.py": "", "cx/ops/kernels/k.py": "def kk():\n    return 2\n",
        "cx/big/__init__.py": "", "cx/big/sub/__init__.py": "", "cx/big/sub/s.py": "from cx.ops import util\n\n\ndef s():\n    return util.u()\n",
        **{f"cx/big/f{i:02d}.py": f"from cx.ops import util\n\n\ndef f{i:02d}():\n    return util.u()\n" for i in range(14)}}


# runner 经 self.model.forward 调到的 Net 是按字符串加载的：这条调用代码里看不出（图上是橙虚线）
_DYN = {
    "dyn/__init__.py": "",
    "dyn/models/__init__.py": "",
    "dyn/models/net.py": ("class Net:\n    def __init__(self):\n        self.k = 2\n\n"
                          "    def forward(self, x):\n        return x * self.k\n\n\ndef helper():\n    return 0\n"),
    "dyn/runner.py": ("from dyn.models import net\n\n\n"
                      "class Runner:\n    def __init__(self, model):\n        self.model = model\n\n"
                      "    def step(self):\n        return self.model.forward(1)\n\n"
                      "    def warm(self):\n        return net.helper()\n"),
    "dyn/main.py": ("import importlib\n\nfrom dyn.runner import Runner\n\n\n"
                    "def build():\n    return getattr(importlib.import_module('dyn.models.net'), 'Net')()\n\n\n"
                    "if __name__ == '__main__':\n    r = Runner(build())\n    for _ in range(3):\n        r.step()\n"),
}


def _serve(repo) -> tuple:
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
    return srv, base


def fixture() -> dict:
    """录两次 run、起 serve（整个文件只做一次）"""
    if _FX:
        return _FX
    repo = fresh()
    cs("trace", repo, "--case", "truth", "--events",
       "--phase", "loop=fakesvc.truth:s_loop", "--phase", "forks=fakesvc.truth:s_fork", "--", PY, "-m", "fakesvc.truth")
    cs("trace", repo, "--case", "offline", "--events", "--", PY, "-m", "fakesvc.offline")
    srv, base = _serve(repo)
    cut = tmpdir("cs-browser-cut-") / "cutrepo"
    for rel, src in _CUT.items():
        (cut / rel).parent.mkdir(parents=True, exist_ok=True)
        (cut / rel).write_text(src)
    cs("scan", cut)
    srv2, base2 = _serve(cut)
    dyn = tmpdir("cs-browser-dyn-") / "dynrepo"
    for rel, src in _DYN.items():
        (dyn / rel).parent.mkdir(parents=True, exist_ok=True)
        (dyn / rel).write_text(src)
    cs("scan", dyn)
    cs("trace", dyn, "--case", "dyn", "--", PY, "-m", "dyn.main")
    # 同样跑一次、去掉调用行，当 2026-09-30 之前录的老 run
    cs("trace", dyn, "--case", "dynold", "--", PY, "-m", "dyn.main")
    cp = dyn / ".codestrata" / "runs" / _run_id(dyn, "dynold") / "counts.json.gz"
    c = json.loads(gzip.decompress(cp.read_bytes()))
    for ph in c["phases"].values():
        ph.pop("func_lines", None)
    cp.write_bytes(gzip.compress(json.dumps(c).encode()))
    srv3, base3 = _serve(dyn)
    _FX.update(srv3=srv3, base3=base3, dyn=_run_id(dyn, "dyn"), dynold=_run_id(dyn, "dynold"))
    _FX.update(repo=str(repo), base=base, srv=srv, srv2=srv2, base2=base2,
               a=_run_id(repo, "truth"), b=_run_id(repo, "offline"))
    fx = {k: v for k, v in _FX.items() if k not in ("srv", "srv2", "srv3")}
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


def test_viewer():
    _spec("viewer")


def test_findbar():
    _spec("findbar")


def test_cut():
    _spec("cut")


def test_path():
    _spec("path")


def test_calls():
    _spec("calls")


if __name__ == "__main__":
    try:
        rc = run_tests(globals(), sys.argv[1:])
    finally:
        for k in ("srv", "srv2", "srv3"):
            if _FX.get(k):
                _FX[k].kill()
                _FX[k].wait()
    sys.exit(rc)
