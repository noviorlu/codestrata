"""C / C++ / CUDA 的扫描端（native_scan.py）和它装进 scan 的样子。

    .venv/bin/python tests/test_native_scan.py
只扫描，不录制，几秒钟。没装 tree-sitter 的环境整个跳过。
"""
from __future__ import annotations

import json
import sys

from common import cs, run_tests, tmpdir  # noqa: E402

from codestrata import graph, native_scan, scan  # noqa: E402

_SRC = {
    "pkg/__init__.py": "",
    "pkg/run.py": "def go(lib):\n    return lib.launch_it()\n",
    "pkg/csrc/util.h": (
        "#pragma once\n"
        "namespace k {\n"
        "__device__ inline float twice(float x) { return x * 2; }\n"
        "}  // namespace k\n"
        "int helper(int a);\n"
    ),
    "pkg/csrc/kern.cu": (
        '#include "util.h"\n'
        "#include <cstdio>\n"
        "namespace k {\n"
        "struct __align__(16) Box {\n"
        "    int v;\n"
        "    __device__ int get() const { return v; }\n"
        "};\n"
        "__device__ float step(float x) {\n"
        "    float s = 0;\n"
        "    for (int i = 0; i < 4; ++i)\n"
        "#pragma unroll\n"
        "        for (int j = 0; j < 4; ++j) s += twice(x);\n"
        "    return s;\n"
        "}\n"
        "__device__ float step(float x, float y) { return step(x) + y; }\n"
        "__global__ void main_kernel(float* out) {\n"
        "    Box b{1};\n"
        "    out[threadIdx.x] = step(out[0]) + b.get();\n"
        "    __syncthreads();\n"
        "}\n"
        "}  // namespace k\n"
        'extern "C" int launch_it(float* p) {\n'
        "    k::main_kernel<<<1, 32>>>(p);\n"
        "    helper(1);\n"
        "    return 0;\n"
        "}\n"
    ),
    # 另一个文件里也有 helper：kern.cu 调 helper 时两个候选都不在它 include 得到的文件里 → 不连
    "pkg/csrc/a.cpp": "int helper(int a) { return a; }\n",
    "pkg/csrc/b.cpp": "int helper(int a) { return a + 1; }\nint use_b() { return helper(2); }\n",
}


def _repo():
    d = tmpdir("cs-native-")
    for rel, text in _SRC.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def _skip() -> bool:
    if native_scan.available():
        print("  跳过：没装 tree-sitter")
        return True
    return False


def test_symbols_and_calls():
    """定义（命名空间、类、方法、重载、kernel）、按名字对上的调用、启动、include"""
    if _skip():
        return
    d = _repo()
    rels = [r for r in _SRC if native_scan.is_native(r)]
    sh = native_scan.scan_files(d, rels)
    assert not sh["errors"], sh["errors"]                        # __align__、#pragma 都没让它解析失败
    S = sh["symbols"]
    K = "pkg/csrc/kern.cu#"
    assert S[K + "k::main_kernel"]["k"] == "kernel"
    assert S[K + "k::Box"]["k"] == "class" and S[K + "k::Box::get"]["k"] == "func"
    assert S[K + "k::step"]["a"], S[K + "k::step"]              # 重载：同一个键，另一个记在 a 里
    assert S["pkg/csrc/util.h#k::twice"]["s"] == "twice"
    calls = {(c, t, k) for c, xs in sh["calls"].items() for t, l, e, k in xs}
    assert ("pkg/csrc/kern.cu#launch_it", K + "k::main_kernel", native_scan.LAUNCH) in calls, calls
    assert (K + "k::step", "pkg/csrc/util.h#k::twice", native_scan.CALL) in calls, calls   # 经 include 对上
    assert (K + "k::main_kernel", K + "k::step", native_scan.CALL) in calls, calls
    assert (K + "k::main_kernel", K + "k::Box::get", native_scan.CALL) in calls, calls     # 方法调用 b.get()
    assert ("pkg/csrc/b.cpp#use_b", "pkg/csrc/b.cpp#helper", native_scan.CALL) in calls    # 同文件优先
    sites = {(c, n, k) for c, xs in sh["sites"].items() for n, l, e, k in xs}
    assert ("pkg/csrc/kern.cu#launch_it", "helper", native_scan.CALL) in sites, sites       # 两个候选：不连
    assert (K + "k::main_kernel", "__syncthreads", native_scan.EXT) in sites, sites        # 仓库外
    assert ("pkg/csrc/kern.cu", "pkg/csrc/util.h") in sh["includes"]


def test_scan_integrates_native_units():
    """scan：原生文件成单元（不给 label、按路径显示），符号进 symbols，调用进 graph.json，不再挂成 aux"""
    if _skip():
        return
    d = _repo()
    cs("scan", d)
    idx = json.loads((d / ".codestrata" / "index.json").read_text())
    syms = json.loads((d / ".codestrata" / "symbols.json").read_text())
    g = json.loads((d / ".codestrata" / "graph.json").read_text())
    assert "pkg/csrc/kern.cu" in idx["packages"] and "label" not in idx["packages"]["pkg/csrc/kern.cu"]
    assert idx["packages"]["pkg/run.py"]["label"] == "pkg.run"                  # Python 照旧
    assert idx["repo"]["native"]["n_files"] == 4, idx["repo"]["native"]
    assert "native_graph" not in idx
    assert ["pkg/csrc/kern.cu", "pkg/csrc/util.h", 1] in idx["edges"], idx["edges"]
    assert "pkg/csrc/kern.cu" not in syms["aux"], syms["aux"]
    assert syms["symbols"]["pkg/csrc/kern.cu#k::main_kernel"]["lang"] == "cuda"
    assert syms["file_sha"]["pkg/csrc/kern.cu"]
    C = g["callees"]
    launches = [(c, C[i]) for c, xs in g["calls"].items() for i, l, e, k in xs if k == graph.LAUNCH]
    assert launches == [("pkg/csrc/kern.cu#launch_it", "pkg/csrc/kern.cu#k::main_kernel")], launches
    assert any(c == "pkg/run.py#go" for c in g["sites"]), g["sites"]          # Python 那边还在


def test_without_tree_sitter():
    """没装 tree-sitter：原生文件照旧只挂成 aux，repo.native 写明为什么"""
    d = _repo()
    real = native_scan.available
    native_scan.available = lambda: "没装（测试里模拟）"
    try:
        idx = scan.scan(d)
    finally:
        native_scan.available = real
    assert "pkg/csrc/kern.cu" not in idx["packages"] and "pkg/csrc/kern.cu" in idx["aux"]
    assert idx["repo"]["native"] == {"skipped": "没装（测试里模拟）"}, idx["repo"]["native"]
    assert not idx["native_graph"]["calls"]


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
