"""trace --gpu：GPU 录制端。

录制端是一小段 C++（`cupti_inject.cpp`，经 CUPTI 的 activity API 记 kernel 和发起它的启动调用），录的时候用本机的
CUDA 工具链编成共享库（按源码、工具链和编译器的哈希缓存在 ~/.cache/codestrata/cupti/），CUDA 运行时按环境变量
`CUDA_INJECTION64_PATH` 把它载进被录的每个用 CUDA 的进程。产出 `parts/cu-<pid>-<t0_ns>.log`（格式见源码开头）。
在 driver 这一边用；不 import hook / analysis 以外的东西。
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

SRC = Path(__file__).with_name("cupti_inject.cpp")
ENV = "CUDA_INJECTION64_PATH"


def _layout(home: Path) -> tuple[Path, Path] | None:
    """CUDA 工具链目录 → (有 cupti.h 的 include 目录, 有 libcupti.so 的 lib 目录)；不全是 None"""
    incs = [home / "include", *map(Path, glob.glob(str(home / "targets" / "*" / "include"))),
            home / "extras" / "CUPTI" / "include"]
    libs = [home / "lib64", home / "lib", *map(Path, glob.glob(str(home / "targets" / "*" / "lib"))),
            home / "extras" / "CUPTI" / "lib64"]
    inc = next((d for d in incs if (d / "cupti.h").is_file()), None)
    lib = next((d for d in libs if (d / "libcupti.so").exists()), None)
    return (inc, lib) if inc and lib else None


def find_cuda(env: dict[str, str] | None = None) -> tuple[Path, Path, Path] | None:
    """找一个带 CUPTI 的 CUDA 工具链：--env 给的 CUDA_HOME / CUDA_PATH、当前环境的、PATH 上 nvcc 所在的、/usr/local/cuda*。
    返回 (工具链目录, include, lib)，找不到是 None"""
    cands: list[str] = []
    for src in (env or {}), os.environ:
        cands += [src[k] for k in ("CUDA_HOME", "CUDA_PATH") if src.get(k)]
    nvcc = shutil.which("nvcc", path=(env or {}).get("PATH") or os.environ.get("PATH"))
    if nvcc:
        cands.append(str(Path(nvcc).resolve().parent.parent))
    cands += ["/usr/local/cuda", *sorted(glob.glob("/usr/local/cuda-*"), reverse=True)]
    for c in cands:
        home = Path(c)
        lay = _layout(home) if home.is_dir() else None
        if lay:
            return home, *lay
    return None


def injection_lib(env: dict[str, str] | None = None) -> Path:
    """编好的 GPU 录制端的路径（缓存过就直接用）。找不到工具链、编不过时 RuntimeError，写明缺什么"""
    found = find_cuda(env)
    if found is None:
        raise RuntimeError("--gpu 要一个带 CUPTI 的 CUDA 工具链（cupti.h 和 libcupti.so），没找到："
                           "用 --env CUDA_HOME=<工具链目录> 指定，或者把 nvcc 放到 PATH 上")
    home, inc, lib = found
    cxx = os.environ.get("CXX") or shutil.which("g++") or shutil.which("c++")
    if not cxx:
        raise RuntimeError("--gpu 要一个 C++ 编译器（g++）来编 GPU 录制端，PATH 上没有")
    key = hashlib.sha256(SRC.read_bytes() + f"\0{inc}\0{lib}\0{cxx}".encode()).hexdigest()[:16]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "codestrata" / "cupti" / key
    out = cache / "libcodestrata_cupti.so"
    if out.is_file():
        return out
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f".{os.getpid()}.so"
    cmd = [cxx, "-O2", "-std=c++17", "-shared", "-fPIC", str(SRC), f"-I{inc}", f"-L{lib}", "-lcupti",
           f"-Wl,-rpath,{lib}", "-o", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"编 GPU 录制端失败（{home}）：\n{' '.join(cmd)}\n{r.stderr[-2000:]}")
    os.replace(tmp, out)
    return out
