"""trace 在不同 Python 版本上的开销（3.12+ 用 sys.monitoring，更早的退回 sys.setprofile）。不是回归测试。

    .venv/bin/python tests/bench/python_versions.py PY [PY …] [--runs 5]

在临时目录里建一个小仓库，两种负载各跑「不录」和「codestrata trace」，交替跑 --runs 次取中位数：
  lib   仓库里的一个函数循环调标准库（posixpath.join、json.dumps、re.match、sorted），仓库内调用很少
  pylib 仓库里的一个函数用 ast.walk 遍历一棵语法树：几乎全是标准库里的纯 Python 代码和生成器（像大框架里那样）
  repo  仓库里的函数互相调（两层，每次循环两次仓库内调用）
时间是负载自己量的循环那一段（不含启动和 trace 收尾）。PY 是被录的解释器（要 3.10+），codestrata 自己用当前的 Python 跑。
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

N = {"lib": 100_000, "pylib": 30, "repo": 500_000}
_SRC = {
    "bench/__init__.py": "",
    "bench/lib.py": ("import json, posixpath, re\n\n\n"
                     "def work(n):\n"
                     "    s = 0\n"
                     "    for i in range(n):\n"
                     "        s += len(posixpath.join('a', 'b', str(i)))\n"
                     "        s += len(json.dumps({'i': i}))\n"
                     "        s += 1 if re.match(r'\\d+', str(i)) else 0\n"
                     "        s += sorted((3, 1, 2))[0]\n"
                     "    return s\n"),
    "bench/pylib.py": ("import ast, inspect\n\n\n"
                       "def work(n):\n"
                       "    tree = ast.parse(inspect.getsource(ast))\n"
                       "    s = 0\n"
                       "    for _ in range(n):\n"
                       "        for node in ast.walk(tree):\n"
                       "            s += len(list(ast.iter_fields(node)))\n"
                       "    return s\n"),
    "bench/repo.py": ("def g(x):\n    return x * 2\n\n\n"
                      "def f(x):\n    return g(x) + 1\n\n\n"
                      "def work(n):\n"
                      "    s = 0\n"
                      "    for i in range(n):\n"
                      "        s += f(i)\n"
                      "    return s\n"),
    "run.py": ("import sys, time\n"
               "from importlib import import_module\n"
               "w, n = sys.argv[1], int(sys.argv[2])\n"
               "work = import_module('bench.' + w).work\n"
               "t = time.perf_counter(); work(n); print(f'{time.perf_counter() - t:.4f}')\n"),
}


def _loop(cmd: list[str], cwd: Path) -> float:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return float(next(x for x in r.stdout.split() if x.replace(".", "", 1).isdigit()))


def main(argv: list[str]) -> int:
    runs = 5
    if "--runs" in argv:
        i = argv.index("--runs")
        runs, argv = int(argv[i + 1]), argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__)
        return 2
    with tempfile.TemporaryDirectory(prefix="cs-bench-") as tmp:
        repo = Path(tmp) / "repo"
        for rel, src in _SRC.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(src)
        cs = [sys.executable, "-m", "codestrata"]
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        subprocess.run(cs + ["scan", str(repo), "--roots", "bench"], check=True, capture_output=True, env=env)
        for py in argv:
            py = os.path.abspath(py) if os.sep in py else py      # 负载在仓库目录里跑：相对路径要先定下来
            ver = subprocess.run([py, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            for w, n in N.items():
                plain, traced = [], []
                for k in range(runs):
                    plain.append(_loop([py, "run.py", w, str(n)], repo))
                    r = subprocess.run(cs + ["trace", str(repo), "--case", f"b{k}", "--", py, "run.py", w, str(n)],
                                       cwd=repo, capture_output=True, text=True, env=env, check=True)
                    traced.append(float(next(x for x in r.stdout.split() if x.replace(".", "", 1).isdigit())))
                a, b = statistics.median(plain), statistics.median(traced)
                print(f"Python {ver}  {w:<4}  不录 {a:.3f} s  trace {b:.3f} s  {b / a:.2f}×", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
