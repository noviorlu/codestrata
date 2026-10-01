"""时序事件的录制开销（不是回归测试）：一个临时小仓库，每次循环 3 次调用（2 次同文件、1 次跨文件），比四种录法。

    .venv/bin/python tests/bench/events_overhead.py [--n 200000] [--rounds 5] [--old 老代码的目录]

  不录          直接跑负载
  --no-events   trace，只计数
  trace         trace，时序事件（记每一次调用，2026-10-01 起的默认）
  老 trace      --old 给了一份老的 codestrata（只记跨文件的时序事件）时，用它的 trace --events 跑一遍对照
每种跑 --rounds 次、交替着跑，取中位数。「循环」是负载自己量的那一段，「整条」是整条命令（含 trace 收尾时整理事件）。
只在临时目录里录，不碰别的仓库。
"""
from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = sys.executable

_A = '''import time

from bench import b


def leaf(x):
    return x + 1


def mid(x):
    return leaf(x) + b.other(x)


def main(n):
    t = time.perf_counter()
    s = 0
    for i in range(n):
        s += mid(i)
    print("LOOP", time.perf_counter() - t)
    return s
'''
_B = "def other(x):\n    return x * 2\n"
_RUN = "import sys\nfrom bench import a\na.main(int(sys.argv[1]))\n"


def _repo(d: Path) -> Path:
    r = d / "repo"
    (r / "bench").mkdir(parents=True)
    (r / "bench" / "__init__.py").write_text("")
    (r / "bench" / "a.py").write_text(_A)
    (r / "bench" / "b.py").write_text(_B)
    (r / "run.py").write_text(_RUN)
    return r


def _once(cmd: list[str], cwd: Path, env: dict) -> tuple[float, float]:
    t = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    whole = time.perf_counter() - t
    if p.returncode != 0:
        raise SystemExit(f"跑失败了：{' '.join(cmd)}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    loop = next(float(ln.split()[1]) for ln in (p.stdout + p.stderr).splitlines() if ln.startswith("LOOP"))
    return loop, whole


def main(argv: list[str]) -> int:
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 200_000
    rounds = int(argv[argv.index("--rounds") + 1]) if "--rounds" in argv else 5
    old = Path(argv[argv.index("--old") + 1]).resolve() if "--old" in argv else None
    tmp = Path(tempfile.mkdtemp(prefix="cs-bench-ev-"))
    try:
        repo = _repo(tmp)
        env = {**os.environ, "PYTHONPATH": str(repo)}
        work = [PY, "run.py", str(n)]

        def trace(root: Path, case: str, *flags: str) -> list[str]:
            return [PY, "-m", "codestrata", "trace", str(repo), "--case", case, *flags, "--", *work]
        cfgs = {"不录": (work, env),
                "--no-events": (trace(ROOT, "noev", "--no-events"), {**env, "PYTHONPATH": f"{ROOT}:{repo}"}),
                "trace": (trace(ROOT, "ev"), {**env, "PYTHONPATH": f"{ROOT}:{repo}"})}
        if old:
            cfgs["老 trace"] = (trace(old, "old", "--events"), {**env, "PYTHONPATH": f"{old}:{repo}"})
        got: dict[str, list] = {k: [] for k in cfgs}
        for _ in range(rounds):
            for k, (cmd, e) in cfgs.items():
                got[k].append(_once(cmd, repo, e))
        base = statistics.median(x[0] for x in got["不录"])
        base_w = statistics.median(x[1] for x in got["不录"])
        print(f"负载：{n} 次循环，每次 3 次调用（同文件 2、跨文件 1），Python {sys.version.split()[0]}，{rounds} 轮取中位数")
        for k, xs in got.items():
            lo, wh = statistics.median(x[0] for x in xs), statistics.median(x[1] for x in xs)
            print(f"  {k:12} 循环 {lo:.3f} s（{lo / base:.2f}×）  整条 {wh:.2f} s（{wh / base_w:.2f}×）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
