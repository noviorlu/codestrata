"""GPU 录制（trace --gpu）：找工具链、编录制端、hook 的系统线程号；有 GPU 时真录一个小程序。

    .venv/bin/python tests/test_gpu.py
没有 CUDA 工具链 / GPU / torch 的环境自动跳过对应的用例。
"""
from __future__ import annotations

import os
import shutil
import sys
import tarfile
from pathlib import Path

from common import cs, run_tests, tmpdir  # noqa: E402

from codestrata import events  # noqa: E402
from codestrata.trace import gpu  # noqa: E402

TOY = '''import torch


def step(x, w):
    return torch.relu(x @ w).sum()


def main():
    x = torch.randn(32, 32, device="cuda")
    w = torch.randn(32, 32, device="cuda")
    for _ in range(3):
        step(x, w)
    torch.cuda.synchronize()


if __name__ == "__main__":
    main()
'''


def _cuda_python():
    """一个装了能用 CUDA 的 torch 的 Python：CODESTRATA_TEST_CUDA_PY 指定，没有就跳过"""
    py = os.environ.get("CODESTRATA_TEST_CUDA_PY")
    return py if py and Path(py).exists() else None


def test_find_cuda_layouts():
    """include / lib 在 targets/<arch>/ 下（conda 的 CUDA）、在 lib64/（/usr/local/cuda）都认；缺 libcupti 的不算"""
    t = tmpdir("cs-gpu-")
    a = t / "conda"
    (a / "targets" / "x86_64-linux" / "include").mkdir(parents=True)
    (a / "targets" / "x86_64-linux" / "include" / "cupti.h").write_text("")
    (a / "lib").mkdir()
    (a / "lib" / "libcupti.so").write_text("")
    b = t / "half"
    (b / "include").mkdir(parents=True)
    (b / "include" / "cupti.h").write_text("")
    home, inc, lib = gpu.find_cuda({"CUDA_HOME": str(a)})
    assert home == a and inc.name == "include" and "targets" in str(inc) and lib == a / "lib", (home, inc, lib)
    found = gpu.find_cuda({"CUDA_HOME": str(b), "PATH": ""})
    assert found is None or found[0] != b, found


def test_native_thread_ids_parsed():
    """事件日志的 U 行：线程号 → 系统线程号，整理后进 keys.json 的 native"""
    t = tmpdir("cs-gpu-")
    log = t / "ev-100-5000.log"
    log.write_text("H 100 5000 1\nN 1 MainThread\nU 1 100\nN 2 worker\nU 2 4242\nK 1 a.py:1\nC 1 1 1 1 1\nR 2 1 1\n")
    p = events.parse(log)
    assert p["native"] == {1: 100, 2: 4242}, p["native"]
    out = t / "spans"
    events.build([log], 5000, out)
    import json
    keys = json.loads((out / "keys.json").read_text())
    assert keys["native"] == {"100": {"1": 100, "2": 4242}}, keys["native"]


def test_trace_gpu_toy():
    """真录一次：cu-*.log 里有 kernel 和发起它的启动调用（同一个关联号），启动调用的线程是 hook 记的主线程"""
    py = _cuda_python()
    if not py or gpu.find_cuda() is None or not shutil.which("g++"):
        print("  跳过：要 CODESTRATA_TEST_CUDA_PY（装了 CUDA 版 torch 的 Python）、CUDA 工具链和 g++")
        return
    repo = tmpdir("cs-gpu-")
    (repo / "toy").mkdir()
    (repo / "toy" / "__init__.py").write_text("")
    (repo / "toy" / "run.py").write_text(TOY)
    cs("scan", repo)
    cs("trace", repo, "--case", "toy", "--gpu", "--", py, "-m", "toy.run", timeout=600)
    rd = next((repo / ".codestrata" / "runs").glob("*-toy"))
    with tarfile.open(rd / "parts.tar.gz") as tf:
        cu = [m for m in tf.getmembers() if m.name.split("/")[-1].startswith("cu-")]
        assert cu, [m.name for m in tf.getmembers()]
        text = tf.extractfile(cu[0]).read().decode()
    K = [ln for ln in text.splitlines() if ln.startswith("K ")]
    A = [ln for ln in text.splitlines() if ln.startswith("A ")]
    assert K and A, text[:500]
    corr_k = {ln.split("\t")[0].split()[5] for ln in K}
    corr_a = {ln.split("\t")[0].split()[4] for ln in A}
    assert corr_k <= corr_a, (corr_k - corr_a)
    with tarfile.open(rd / "events" / "raw.tar.gz") as tf:
        ev = next(m for m in tf.getmembers() if m.name.split("/")[-1].startswith("ev-"))
        u = [ln for ln in tf.extractfile(ev).read().decode().splitlines() if ln.startswith("U ")]
    native = {ln.split()[2] for ln in u}
    assert {ln.split("\t")[0].split()[3] for ln in A} <= native, (A[:2], u)


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
