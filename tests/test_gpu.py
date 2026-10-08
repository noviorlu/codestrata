"""GPU 录制（trace --gpu）：找工具链、编录制端、hook 的系统线程号；有 GPU 时真录一个小程序。

    .venv/bin/python tests/test_gpu.py
没有 CUDA 工具链 / GPU / torch 的环境自动跳过对应的用例。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from common import cs, gpu_repo, run_tests, tmpdir  # noqa: E402

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


T0 = 1000000000


def _cu(t, launches, extra=()):
    """手写一份 cu 日志：launches 是 [(启动时刻 µs, 系统线程号, 名字)]，每个 kernel 在启动后 10 µs 开始、跑 5 µs；
    extra 是没有启动调用的 kernel 名字（开始于 60 µs）"""
    lines = [f"H 100 {T0}"]
    for i, (us, ntid, name) in enumerate(launches):
        a = T0 + us * 1000
        lines += [f"A {a} {a + 1000} {ntid} {i + 1}\tcudaLaunchKernel", f"K {a + 10000} {a + 15000} 0 7 {i + 1}\t_Z\t{name}"]
    for j, name in enumerate(extra):
        lines.append(f"K {T0 + 60000} {T0 + 61000} 0 7 {900 + j}\t_Z\t{name}")
    lines.append("D 2")
    p = t / f"cu-100-{T0}.log"
    p.write_text("\n".join(lines) + "\n")
    return p


def _gpu_run(t, ev_text, launches, extra=()):
    """手写的事件日志 + cu 日志 → events.build（gpu=kernels.Gpu）。返回 (index, Gpu, keys, 全部行)"""
    import gzip
    import json
    ev = t / f"ev-100-{T0}.log"
    ev.write_text(f"H 100 {T0} 1\nN 1 MainThread\nU 1 4242\n" + ev_text)
    g = kernels.Gpu([_cu(t, launches, extra)], T0, kernels.resolver(SYMS), lambda us: "start")
    idx = events.build([ev], T0, t / "spans", gpu=g)
    keys = json.loads((t / "spans" / "keys.json").read_text())["keys"]
    rows = [json.loads(ln) for c in idx["chunks"] for ln in gzip.decompress((t / "spans" / c["chunk"]).read_bytes()).splitlines()]
    return idx, g, keys, rows


FOO, MAIN_K = "void at::native::foo<float>(float*)", "void k::main_kernel(float*)"


def test_attach_kernels():
    """kernel 挂到启动那一刻发起它的线程的栈顶（重放事件得到的真实的栈）：调用方是它，第 10 列是 [设备, 流, 晚了多少 µs]；
    仓库里的 kernel 按限定名对到定义行，仓库外的落到 ?gpu/<名字>:0；找不到启动调用的只算次数"""
    t = tmpdir("cs-gpu-")
    idx, g, keys, rows = _gpu_run(t, "K 1 pkg/run.py:0\nK 2 pkg/run.py:1\nK 3 pkg/lib.py:3\n"
                                     "C 10 1 1 1 2\nC 20 1 2 2 3\nR 50 1 2\nR 100 1 1\n",
                                  [(30, 4242, MAIN_K), (15, 4242, FOO)], extra=[FOO])
    gpu_rows = [r for r in rows if len(r) == 10]
    assert len(gpu_rows) == 2 and len(rows) == 4, rows
    by_callee = {keys[r[5]]: r for r in gpu_rows}
    inrepo, outside = by_callee["pkg/csrc/kern.cu:16"], by_callee["?gpu/at::native::foo:0"]
    assert keys[inrepo[4]] == "pkg/lib.py:3" and rows[inrepo[8]][5] == keys.index("pkg/lib.py:3"), inrepo
    assert inrepo[0] == 30 and inrepo[1] == 15 and inrepo[9] == [0, 7, 10, 5000], inrepo     # 启动于 30µs，跑完在 45µs，晚了 10µs，跑了 5000 ns
    assert keys[outside[4]] == "pkg/run.py:1" and outside[3] == rows[outside[8]][3] + 1, outside
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)                             # 和 CPU 的行排在一起
    assert idx["n_calls"] == 2, idx["n_calls"]                                             # 只数 Python 的调用
    s = idx["gpu"]
    assert s["unattached"] == 1 and s["dropped"] == 2 and s["kernels"]["?gpu/at::native::foo:0"]["n"] == 2, s
    assert g.edges["start"]["func_edges"] == {"pkg/lib.py:3|pkg/csrc/kern.cu:16": 1, "pkg/run.py:1|?gpu/at::native::foo:0": 1}
    assert g.edges["start"]["func_lines"]["pkg/run.py:1|?gpu/at::native::foo:0|0"] == 1
    c = g.counts()["start"]                                                                # 次数：找没找到调用方都算
    assert c["funcs"] == {"pkg/csrc/kern.cu:16": 1, "?gpu/at::native::foo:0": 2} and c["gpu_us"]["?gpu/at::native::foo:0"] == 6, c
    assert g.names["?gpu/at::native::foo:0"] == "at::native::foo"


def test_gpu_time_in_nanoseconds():
    """GPU 时间按纳秒加、最后才换成 µs：三个各跑 1.4 µs 的 kernel 是 4 µs（一个个先取整是 3，按「到跑完 − 晚了」的 µs 相减是 6）；
    老的 GPU 行（第 10 列只有三项）照旧按 µs 相减"""
    from codestrata import seq
    k = lambda a: (1, 100, a, a + 1400, 0, 7, "?gpu/x:0", None)          # noqa: E731  (编号, pid, 开始, 结束 ns, 设备, 流, 键, 启动)
    g = kernels.Gpu.__new__(kernels.Gpu)
    g.kernels, g.base, g.phase_at = [k(1_000_600), k(2_000_600), k(3_000_600)], 0, lambda us: "start"
    assert g.counts()["start"]["gpu_us"] == {"?gpu/x:0": 4} and g.kernel_table()["?gpu/x:0"]["gpu_us"] == 4, g.counts()
    assert seq.gpu_ns([0, 12, 1, 0, 0, 0, 1, 0, -1, [0, 7, 10, 1400]]) == 1400
    assert seq.gpu_ns([0, 12, 1, 0, 0, 0, 1, 0, -1, [0, 7, 10]]) == 2000                 # 老的行：(12 − 10) µs


def test_caller_is_real_stack():
    """调用方按重放出来的真实的栈认，不按折叠之后的时间区间猜（critic 10-02 #1）：
    - go 连着调了三次叶子 f（折叠成一行，覆盖 20–42 µs），在第一次和第二次之间（25 µs）go 自己发起的 kernel 算 go 的；
    - 生成器 gen 挂起之后（Y，一直没返回）go 发起的 kernel 算 go 的，不算 gen 的；
    - f 里面（31 µs）发起的算 f 的，挂在折叠的那一行下面"""
    t = tmpdir("cs-gpu-")
    ev = ("K 1 pkg/run.py:0\nK 2 pkg/run.py:1\nK 3 pkg/run.py:5\nK 4 pkg/run.py:9\n"
          "C 10 1 1 1 2\n"
          "C 20 1 2 2 3\nR 22 1 2\nC 30 1 3 2 3\nR 32 1 3\nC 40 1 4 2 3\nR 42 1 4\n"
          "C 50 1 5 2 4\nY 52 1 5\n"
          "R 100 1 1\n")
    idx, g, keys, rows = _gpu_run(t, ev, [(25, 4242, FOO), (31, 4242, MAIN_K), (60, 4242, FOO)])
    callers = sorted((keys[r[4]], keys[r[5]], round(r[0])) for r in rows if len(r) == 10)
    assert callers == [("pkg/run.py:1", "?gpu/at::native::foo:0", 25), ("pkg/run.py:1", "?gpu/at::native::foo:0", 60),
                       ("pkg/run.py:5", "pkg/csrc/kern.cu:16", 31)], callers
    folded = next(r for r in rows if len(r) == 9 and r[6] == 3)                            # f ×3 合成的那一行
    k = next(r for r in rows if len(r) == 10 and keys[r[5]] == "pkg/csrc/kern.cu:16")
    assert rows[k[8]] is folded, (k, folded)
    assert g.summary()["unattached"] == 0


def test_truncated_and_no_events():
    """事件截断之后发起的 kernel 没有调用方（不按截断那一刻的栈瞎猜），但次数和 GPU 时间照算（critic 10-02 #2）；
    完全没有事件时 Gpu.counts 一样是全的"""
    t = tmpdir("cs-gpu-")
    ev = "K 1 pkg/run.py:0\nK 2 pkg/run.py:1\nC 10 1 1 1 2\nT\n"                   # go 进去之后就到了上限
    idx, g, keys, rows = _gpu_run(t, ev, [(10, 4242, FOO), (500, 4242, FOO), (600, 999, FOO)])
    assert [keys[r[4]] for r in rows if len(r) == 10] == ["pkg/run.py:1"], rows            # 10 µs 的那次在 go 里（截断前最后一个事件那一微秒）；之后的没有
    s = g.summary()
    assert s["n_kernels"] == 3 and s["unattached"] == 2, s
    assert g.counts()["start"]["funcs"] == {"?gpu/at::native::foo:0": 3}
    assert g.edges["start"]["func_edges"] == {"pkg/run.py:1|?gpu/at::native::foo:0": 1}
    t2 = tmpdir("cs-gpu-")
    g2 = kernels.Gpu([_cu(t2, [(11, 4242, FOO)], extra=[MAIN_K])], T0, kernels.resolver(SYMS), lambda us: "p")
    assert g2.counts() == {"p": {"funcs": {"?gpu/at::native::foo:0": 1, "pkg/csrc/kern.cu:16": 1},
                                 "gpu_us": {"?gpu/at::native::foo:0": 5, "pkg/csrc/kern.cu:16": 1}}}, g2.counts()
    assert g2.summary()["unattached"] == 2 and not g2.edges


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
    assert not cut.within(cut.VIRTUAL_GPU, cut.ROOT_DIR) and cut.within("run.py", cut.ROOT_DIR)   # 不在根目录里（以前在，搜索定位会抛 KeyError）


def test_gpu_time_in_lanes():
    """分列里 GPU 的列：节点上有 GPU 时间，launch 连线上有次数和 GPU 时间（每对函数也有）；这一列的叠加里每种 kernel
    带着是谁发起的、几次、GPU 上多久（手写的 GPU 日志：三次 forward 各启动 k::scale 和 at::native::foo，每个跑 50 µs）"""
    from codestrata import lanes, runs
    from codestrata.ui import load as ui_load
    repo, rid = gpu_repo()
    idx = ui_load.load_index(repo)
    hot, _ = ui_load.load_hot(repo, idx, rid)
    run, rd, phase = runs.resolve(repo, rid)
    L = lanes.build(idx, rd, run, phase, hot, sorted(idx["dirs"]))
    g = next(x for x in L["lanes"] if x.get("gpu"))
    nodes = list(g["nodes"].values())
    assert sum(v["n"] for v in nodes) == 6 and sum(v["gpu_us"] for v in nodes) == 300, g["nodes"]
    ls = [x for x in L["links"] if x["kind"] == "launch"]
    assert sum(x["n"] for x in ls) == 6 and sum(x["gpu_us"] for x in ls) == 300, ls
    assert all(p["gpu_us"] == 50 * p["n"] for x in ls for p in x["pairs"]), [x["pairs"] for x in ls]
    assert all("gpu_us" not in x for x in L["links"] if x["kind"] != "launch"), "只有 launch 连线带 GPU 时间"
    h = ui_load.load_lane(repo, idx, rid, g["id"])
    assert len(h["kernels"]) == 2 and all(v["callers"] == [{"caller": "dyn/models/net.py#Net.forward", "n": 3, "gpu_us": 150}]
                                          for v in h["kernels"].values()), h["kernels"]
    from codestrata.ui import search
    assert search.reveal(idx, cut.VIRTUAL_GPU, []) == [], "「GPU · 仓库外」不用展开哪个目录"
    main = next(x for x in L["lanes"] if x["thread"] == "MainThread")
    assert not ui_load.load_lane(repo, idx, rid, main["id"])["kernels"], "线程的列不含 GPU 的行"


def test_recorder_compiles_against_cupti_versions():
    """GPU 录制端对着几个版本的 CUPTI 头都编得过（CUDA 12 的头最新的 kernel 记录是 Kernel9，13 的是 Kernel12；
    写死 Kernel12 时 CUDA 12 编不过）：本机工具链的头，加上 CODESTRATA_TEST_CUPTI_INCLUDE（冒号分开的几个只有 CUPTI 头的目录，
    比如 triton 带的 CUDA 12 的那份；cuda.h 取本机工具链的）"""
    cxx = shutil.which("g++")
    found = gpu.find_cuda()
    extra = [p for p in os.environ.get("CODESTRATA_TEST_CUPTI_INCLUDE", "").split(":") if p]
    if not cxx or (found is None and not extra):
        print("  跳过：要 g++ 和 CUPTI 头（CUDA 工具链，或 CODESTRATA_TEST_CUPTI_INCLUDE）")
        return
    base = [f"-I{found[1]}"] if found else []
    for inc in ([str(found[1])] if found else []) + extra:
        r = subprocess.run([cxx, "-std=c++17", "-fsyntax-only", f"-I{inc}", *base, str(gpu.SRC)], capture_output=True, text=True)
        assert r.returncode == 0, (inc, r.stderr[-1500:])


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
    assert run["gpu"]["n_kernels"] > 0 and not run["gpu"]["unattached"], run["gpu"]
    edges = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]["start"]["func_edges"]
    callers = {k.split("|")[0] for k in edges if "|?gpu/" in k}
    assert callers <= {"toy/run.py:4", "toy/run.py:8"} and "toy/run.py:4" in callers, edges


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
