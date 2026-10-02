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

from codestrata import align, cut, events, kernels  # noqa: E402
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


def test_kernel_name():
    """还原后的名字 → 限定名：去掉返回类型、模板参数（可以嵌套）、参数表；匿名命名空间里的空格不拆"""
    for raw, want in [
        ("void at::native::reduce_kernel<512, 1, at::native::R<float, 4>>(at::native::R<float, 4>)", "at::native::reduce_kernel"),
        ("k::main_kernel(float*)", "k::main_kernel"),
        ("void (anonymous namespace)::softmax_warp<float>(float*, int)", "(anonymous namespace)::softmax_warp"),
        ("triton_poi_fused_add_0", "triton_poi_fused_add_0"),
    ]:
        assert kernels.kernel_name(raw) == want, (raw, kernels.kernel_name(raw))


SYMS = {"pkg/csrc/kern.cu#k::main_kernel": {"k": "kernel", "n": "k::main_kernel", "f": "pkg/csrc/kern.cu", "l": 16}}


def _gpu_run(t):
    """手写的一次录制：主线程（系统线程号 4242）里 go 调 launch；三个 kernel——launch 里发起的仓库内 kernel、
    go 里发起的仓库外 kernel、找不到启动调用的一个"""
    ev = t / "ev-100-1000000000.log"
    ev.write_text("H 100 1000000000 1\nN 1 MainThread\nU 1 4242\n"
                  "K 1 pkg/run.py:0\nK 2 pkg/run.py:1\nK 3 pkg/lib.py:3\n"
                  "C 10 1 1 1 2\nC 20 1 2 2 3\nR 50 1 2\nR 100 1 1\n")
    cu = t / "cu-100-1000000000.log"
    cu.write_text("H 100 1000000000\n"
                  "A 1000030000 1000031000 4242 7\tcudaLaunchKernel\n"
                  "K 1000040000 1000045000 0 7 7\t_Z\tvoid k::main_kernel(float*)\n"
                  "A 1000015000 1000016000 4242 8\tcuLaunchKernel\n"
                  "K 1000017000 1000019000 0 7 8\t_Z\tvoid at::native::foo<float>(float*)\n"
                  "K 1000060000 1000061000 0 7 9\t_Z\tvoid at::native::foo<float>(float*)\n"
                  "D 2\n")
    got = {}

    def hook(pid_rows, keys, native):
        got.update(kernels.attach([cu], 1000000000, pid_rows, keys, native, kernels.resolver(SYMS), lambda t: "start"))
        return got
    idx = events.build([ev], 1000000000, t / "spans", gpu=hook)
    return idx, got


def test_attach_kernels():
    """kernel 挂到启动那一刻同一条线程上最里层的 span 下：调用方是它，第 10 列是 [设备, 流, 晚了多少 µs]；
    仓库里的 kernel 按限定名对到定义行，仓库外的落到 ?gpu/<名字>:0；找不到启动调用的只进摘要"""
    import gzip
    import json
    t = tmpdir("cs-gpu-")
    idx, got = _gpu_run(t)
    keys = json.loads((t / "spans" / "keys.json").read_text())["keys"]
    rows = [json.loads(ln) for c in idx["chunks"] for ln in gzip.decompress((t / "spans" / c["chunk"]).read_bytes()).splitlines()]
    gpu_rows = [r for r in rows if len(r) == 10]
    assert len(gpu_rows) == 2 and len(rows) == 4, rows
    by_callee = {keys[r[5]]: r for r in gpu_rows}
    inrepo, outside = by_callee["pkg/csrc/kern.cu:16"], by_callee["?gpu/at::native::foo:0"]
    assert keys[inrepo[4]] == "pkg/lib.py:3" and rows[inrepo[8]][5] == keys.index("pkg/lib.py:3"), inrepo
    assert inrepo[0] == 30 and inrepo[1] == 15 and inrepo[9] == [0, 7, 10], inrepo     # 启动于 30µs，跑完在 45µs，晚了 10µs
    assert keys[outside[4]] == "pkg/run.py:1" and outside[3] == rows[outside[8]][3] + 1, outside
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)                             # 和 CPU 的行排在一起
    assert idx["n_calls"] == 2, idx["n_calls"]                                             # 只数 Python 的调用
    s = idx["gpu"]
    assert s["unattached"] == 1 and s["dropped"] == 2 and s["kernels"]["?gpu/at::native::foo:0"]["n"] == 2, s
    c = got["counts"]["start"]
    assert c["func_edges"] == {"pkg/lib.py:3|pkg/csrc/kern.cu:16": 1, "pkg/run.py:1|?gpu/at::native::foo:0": 1}, c
    assert c["func_lines"]["pkg/run.py:1|?gpu/at::native::foo:0|0"] == 1, c
    assert got["names"]["?gpu/at::native::foo:0"] == "at::native::foo"


def test_virtual_gpu_node():
    """仓库外的 kernel 落到虚拟单元 ?gpu：模块图上叠加时算它的次数，调用方 → ?gpu#<名字> 是只有 trace 的边；
    切面上有这个节点，但只有叠着的 run 跑到了才画"""
    idx = {"files": {"pkg/run.py": "pkg/run.py"}, "symbols": {"pkg/run.py#go": {"k": "func", "n": "go", "f": "pkg/run.py", "l": 1, "e": 2}},
           "packages": {"pkg/run.py": {"files": 1, "loc": 2, "classes": 0, "funcs": 1, "out": 0, "in": 0}},
           "dirs": {}, "edges": []}
    tr = {"funcs": {"pkg/run.py:1": 1, "?gpu/at::native::foo:0": 3},
          "func_edges": {"pkg/run.py:1|?gpu/at::native::foo:0": 3},
          "func_lines": {"pkg/run.py:1|?gpu/at::native::foo:0|0": 3}}
    g = align.to_package_graph(tr, idx)
    assert g["packages"].get(cut.VIRTUAL_GPU) == 3 and g["module_frames"] == 0, g
    x = g["calls"]["pkg/run.py#go|?gpu#at::native::foo"]
    assert x["a"] == "pkg/run.py" and x["b"] == cut.VIRTUAL_GPU and x["only"] == 3 and x["lines"][0]["status"] == "trace", x
    assert x["lines"][0]["note"] == {"k": "gpu"}, x                                        # 不按「代码里看不出」的规则猜
    assert align.node_def(idx, "?gpu#at::native::foo")["virtual"]
    assert cut.unit_of_rel(idx["files"], "?gpu/x") == cut.VIRTUAL_GPU and cut.unit_of_rel(idx["files"], "nope.py") is None
    assert cut.kind(idx, cut.VIRTUAL_GPU) == "virtual" and cut.parent_of(idx, cut.VIRTUAL_GPU) is None


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
    # 导入端：kernel 挂到了 step / main 上，计数里有 ?gpu 的键，run.json 的 events 有 GPU 摘要
    import gzip
    import json
    run = json.loads((rd / "run.json").read_text())
    assert run["events"]["gpu"]["n_kernels"] > 0 and not run["events"]["gpu"]["unattached"], run["events"]
    edges = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]["start"]["func_edges"]
    callers = {k.split("|")[0] for k in edges if "|?gpu/" in k}
    assert callers <= {"toy/run.py:4", "toy/run.py:8"} and "toy/run.py:4" in callers, edges


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
