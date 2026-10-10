"""切段在大 run 上的冷启动时间和峰值内存（不是回归测试）：造一个 N 行 span 的假 run（几个进程，每个一个主循环），
在新进程里跑 segments.analyse + stage_segments，打出用时和峰值 RSS。

    python tests/bench/segments_scale.py [总行数，默认 3000000] [进程数，默认 4]
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
from synth import Builder  # noqa: E402

KEYS = [f"app/m{i}.py:{i}" for i in range(40)]


def make(d: Path, n_rows: int, n_procs: int) -> Path:
    b = Builder(KEYS)
    per = n_rows // n_procs
    for p in range(n_procs):
        t = b.thread(1000 + p, 1, "MainThread", proc=f"python stage{p}.py")
        k, t0 = 0, 0
        while len(b.rows.get(1000 + p, [])) < per:
            h = t.call(t0, 400, 0)
            for j in range(8):
                t.call(t0 + 10 + j * 40, 30, 1 + (j + k) % 30, parent=h)
            t0 += 500
            k += 1
    return b.write(d)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3_000_000
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    with tempfile.TemporaryDirectory(prefix="cs-scale-") as d:
        t = time.monotonic()
        rd = make(Path(d), n, procs)
        print(f"造了 {n} 行（{procs} 个进程）：{time.monotonic() - t:.1f} s")
        code = ("import resource, sys, time; sys.path.insert(0, %r); from codestrata import segments, seq; "
                "t = time.monotonic(); rd = %r; end = seq.run_end({}, __import__('pathlib').Path(rd)); "
                "A = segments.analyse(__import__('pathlib').Path(rd), 0, end); s = segments.stage_segments(A, 0, end, set()); "
                "print(f'切段：{time.monotonic() - t:.2f} s，{len(s)} 段，峰值 RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB')"
                ) % (str(HERE.parent.parent), str(rd))
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    main()
