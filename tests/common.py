"""测试共用的：跑 codestrata 命令、在临时目录里拷一份假仓库、不依赖 pytest 的用例运行器。"""
from __future__ import annotations

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
