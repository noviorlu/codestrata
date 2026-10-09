"""测试共用的：跑 codestrata 命令、在临时目录里拷一份假仓库、不依赖 pytest 的用例运行器。"""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

PY = sys.executable
FAKE = HERE / "trace_cases" / "fake_repo"


def cs(*args, env=None, check=True, timeout=180) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run([PY, "-m", "codestrata", *map(str, args)], capture_output=True, text=True,
                       env=e, timeout=timeout, cwd=HERE.parent)
    if check and r.returncode != 0:
        raise AssertionError(f"codestrata {' '.join(map(str, args))} → {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


_TMP: list[Path] = []


def tmpdir(prefix: str) -> Path:
    """一个临时目录；全部用例通过时统一删掉，有失败时留着现场"""
    t = Path(tempfile.mkdtemp(prefix=prefix))
    _TMP.append(t)
    return t


def fresh() -> Path:
    """拷一份假仓库并扫描"""
    d = tmpdir("cs-runs-") / "repo"
    shutil.copytree(FAKE, d)
    cs("scan", d)
    return d


def run_tests(ns: dict, argv: list[str]) -> int:
    """跑 ns（一个测试模块的 globals()）里所有 test_ 开头的函数；argv 里给了词就只跑名字里带这些词的"""
    tests = [(n, f) for n, f in ns.items() if n.startswith("test_") and callable(f)]
    if argv:
        tests = [(n, f) for n, f in tests if any(a in n for a in argv)]
    bad = 0
    for n, f in tests:
        t = time.monotonic()
        try:
            f()
            print(f"  ✓ {n}  {time.monotonic() - t:.1f}s", flush=True)
        except Exception as e:
            bad += 1
            print(f"  ✗ {n}\n" + "".join(traceback.format_exception(e))[-3000:], flush=True)
    if not bad:                              # 失败时留着现场
        for t in _TMP:
            shutil.rmtree(t, ignore_errors=True)
    print("全部通过" if not bad else f"{bad} 个失败（临时目录留着：{' '.join(map(str, _TMP))}）")
    return 1 if bad else 0


def run_id(repo, case):
    base = repo / ".codestrata" / "runs"
    hits = sorted(p.name for p in base.iterdir() if p.name.endswith("-" + case))
    assert hits, f"没有 {case} 的 run"
    return hits[-1]


# runner 经 self.model.forward 调到的 Net 是按字符串加载的：这条调用代码里看不出（图上是橙虚线）
DYN = {
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


def gpu_repo() -> tuple:
    """DYN 加一个 .cu 文件，录一次（CPU），再手写一份 GPU 日志：Net.forward 里各启动一次仓库里的 k::scale 和仓库外的
    at::native::foo（三次 step 各一次），runs merge 把它们挂上去。返回 (仓库, run id)"""
    repo = tmpdir("cs-browser-gpu-") / "gpurepo"
    # forward 睡 2 ms：手写的启动时刻放在它中间，离它的进 / 出都远（事件的时刻是微秒）
    net = DYN["dyn/models/net.py"].replace("        return x * self.k\n", "        import time\n        time.sleep(0.002)\n        return x * self.k\n")
    for rel, src in {**DYN, "dyn/models/net.py": net,
                     "dyn/csrc/k.cu": "namespace k {\n__global__ void scale(float* x) { x[0] *= 2; }\n}\n"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "gpu", "--", PY, "-m", "dyn.main")
    rid = run_id(repo, "gpu")
    rd = repo / ".codestrata" / "runs" / rid
    run = json.loads((rd / "run.json").read_text())
    spans = rd / "events" / "spans"
    keys = json.loads((spans / "keys.json").read_text())
    chunk = json.loads((spans / "index.json").read_text())["chunks"][0]
    rows = [json.loads(x) for x in gzip.decompress((spans / chunk["chunk"]).read_bytes()).splitlines()]
    fwd = [r for r in rows if keys["keys"][r[5]] == "dyn/models/net.py:5"]
    pid, mono0 = chunk["pid"], run["clock"]["mono0_ns"]
    ntid = keys["native"][str(pid)][str(fwd[0][2])]
    lines = [f"H {pid} {mono0}"]
    for i, r in enumerate(fwd):
        t = mono0 + (r[0] + max(r[1], 0) // 2) * 1000
        for j, name in enumerate(("void k::scale(float*)", "void at::native::foo<float>(float*)")):
            c = 10 * i + j + 1
            lines += [f"A {t} {t + 1000} {ntid} {c}\tcudaLaunchKernel", f"K {t + 2000} {t + 52000} 0 7 {c}\t_Z\t{name}"]
    (rd / "parts").mkdir(exist_ok=True)
    (rd / "parts" / f"cu-{pid}-{mono0}.log").write_text("\n".join(lines) + "\n")
    cs("runs", repo, "merge", rid)
    return repo, rid


@contextlib.contextmanager
def served(repo: Path):
    """在随机端口上起 serve：给出 get(路径) → (状态码, JSON)，get.base 是地址；用完按 pid 关掉"""
    import socket
    import urllib.request
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
    srv = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)], cwd=HERE.parent,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def get(path):
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
            except OSError:
                time.sleep(0.1)
        raise AssertionError("serve 没起来")
    get.base = f"http://127.0.0.1:{port}"
    try:
        yield get
    finally:
        srv.kill()
        srv.wait()
