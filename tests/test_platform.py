"""平台：录制只支持 Linux，别的系统上 scan / serve / graph 也要能 import、能用（compat.py）。

    .venv/bin/python tests/test_platform.py
没有 Windows / macOS 机器也能测：在子进程里拿掉 Unix 才有的东西（fcntl、signal.SIGKILL），或者改 sys.platform。
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from common import HERE, PY, run_tests, tmpdir  # noqa: E402

# 模拟 Windows：import 前把 fcntl 挡掉、删掉 SIGKILL（真正的 Windows 上这两样都没有）
NO_UNIX = textwrap.dedent("""
    import sys, signal
    sys.modules["fcntl"] = None
    if hasattr(signal, "SIGKILL"):
        del signal.SIGKILL
    sys.path.insert(0, {root!r})
""")


def _py(prelude: str, body: str, cwd=None) -> subprocess.CompletedProcess:
    code = prelude.format(root=str(HERE.parent)) + textwrap.dedent(body)
    return subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=cwd, timeout=120)


def _tiny_repo():
    repo = tmpdir("cs-plat-")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "a.py").write_text("from pkg import b\n\ndef f():\n    return b.g()\n")
    (repo / "pkg" / "b.py").write_text("def g():\n    return 1\n")
    return repo


def test_no_unix_bits_scan_graph_work():
    """没有 fcntl、没有 SIGKILL（= Windows 的样子）：codestrata 的每个模块都能 import，scan、graph、runs ls 照常能用"""
    repo = _tiny_repo()
    out = repo / "g.html"
    r = _py(NO_UNIX, f"""
        import importlib, pkgutil, codestrata
        mods = [m.name for m in pkgutil.iter_modules(codestrata.__path__)]
        for m in mods:
            importlib.import_module("codestrata." + m)
        print("IMPORTED", len(mods))
        from codestrata.__main__ import main
        rc = [main(["scan", {str(repo)!r}]), main(["graph", {str(repo)!r}, "--out", {str(out)!r}]),
              main(["runs", {str(repo)!r}, "ls"])]
        print("RC", rc)
    """)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
    n = int(r.stdout.split("IMPORTED ")[1].split()[0])
    assert n >= 20, r.stdout
    assert "RC [0, 0, 0]" in r.stdout or "RC [None, None, None]" in r.stdout or "RC [0, 0, None]" in r.stdout, r.stdout
    assert (repo / ".codestrata" / "index.json").is_file() and out.is_file() and out.stat().st_size > 1000


def test_trace_refused_off_linux():
    """不是 Linux 时 trace 一开始就停，说清楚只支持 Linux，而且不建 run 目录（不留下一个失败的 run）"""
    repo = _tiny_repo()
    for plat in ("darwin", "win32"):
        r = _py(NO_UNIX, f"""
            from codestrata.__main__ import main
            sys.platform = {plat!r}        # import 完再改：标准库自己会按 sys.platform 找 Windows 专用的模块
            try:
                main(["trace", {str(repo)!r}, "--case", "x", "--", "python", "-c", "pass"])
                print("NOT REFUSED")
            except SystemExit as e:
                print("EXIT", e)
        """)
        assert "EXIT 录制（trace）目前只支持 Linux" in r.stdout and plat in r.stdout, (plat, r.stdout, r.stderr[-2000:])
        runs = repo / ".codestrata" / "runs"
        assert not runs.exists() or not [p for p in runs.iterdir() if p.is_dir()], list(runs.iterdir())


def test_trace_allowed_on_linux():
    from codestrata import compat
    assert compat.can_trace() == sys.platform.startswith("linux")
    compat.require_trace()                     # 测试跑在 Linux 上：不该拒绝


def test_file_lock():
    """文件锁：有 fcntl 时是真的独占锁（另一个进程拿不到），没有 fcntl / msvcrt 时照样能用（不加锁）"""
    d = tmpdir("cs-lock-")
    lock = d / "x.lock"
    holder = subprocess.Popen([PY, "-c", textwrap.dedent(f"""
        import sys, time; sys.path.insert(0, {str(HERE.parent)!r})
        from codestrata.compat import file_lock
        with open({str(lock)!r}, "a") as f, file_lock(f):
            print("HELD", flush=True); time.sleep(3)
    """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "HELD"
        r = _py("import sys, fcntl\nsys.path.insert(0, {root!r})\n", f"""
            with open({str(lock)!r}, "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    print("GOT")
                except BlockingIOError:
                    print("BUSY")
        """)
        assert r.stdout.strip() == "BUSY", r.stdout + r.stderr
    finally:
        holder.wait(timeout=10)
    r = _py(NO_UNIX + "sys.modules['msvcrt'] = None\n", f"""
        from codestrata.compat import file_lock
        with open({str(lock)!r}, "a") as f, file_lock(f):
            print("OK")
    """)
    assert r.stdout.strip() == "OK", r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
