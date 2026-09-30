"""打包：非 -e 安装的包里要有前端（web/ 下每个文件），不然 serve 全是 404、graph 导出崩。

    .venv/bin/python tests/test_package.py
要 uv（用它构建 wheel）；没有就跳过。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile

from common import HERE, run_tests, tmpdir  # noqa: E402


def test_wheel_ships_web():
    uv = shutil.which("uv")
    if not uv:
        print("    （没有 uv，跳过）")
        return
    # 在一份干净的拷贝上构建（只有 git 管的文件，含还没提交的）：工作区里 -e 安装留下的
    # codestrata.egg-info 会让 setuptools 照着它的文件清单把 web/ 带上，掩盖掉配置漏写
    tmp = tmpdir("cs-pkg-")
    src, out = tmp / "src", tmp / "dist"
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=HERE.parent,
                           capture_output=True, text=True, check=True).stdout.split("\n")
    for f in filter(None, files):
        if (HERE.parent / f).is_file():
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HERE.parent / f, src / f)
    r = subprocess.run([uv, "build", "--wheel", "--out-dir", str(out), str(src)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    wheel = next(out.glob("*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    web = HERE.parent / "codestrata" / "web"
    missing = [f.name for f in web.iterdir() if f.is_file() and f"codestrata/web/{f.name}" not in names]
    assert not missing, f"wheel 里没有这些前端文件：{missing}"


def test_export_scripts_match_index():
    """前端脚本清单有两份：index.html 末尾的 script 标签（serve 用）和 render.SCRIPTS（导出时拼进单文件）。
    两份要一致、web/ 下每个 .js 都在里面——漏了导出版会在调到它的地方报错（时间轴的 timebar.js 就漏过）"""
    import re
    sys.path.insert(0, str(HERE.parent))
    from codestrata import render
    web = HERE.parent / "codestrata" / "web"
    tags = re.findall(r'<script src="([^"]+)"></script>', (web / "index.html").read_text(encoding="utf-8"))
    assert tags == ["hl.js", *render.SCRIPTS], (tags, render.SCRIPTS)      # hl.js 导出时单独一个 <script>
    used = {t for h in web.glob("*.html") for t in re.findall(r'<script src="([^"]+)"></script>', h.read_text(encoding="utf-8"))}
    assert sorted(f.name for f in web.glob("*.js")) == sorted(used), (sorted(f.name for f in web.glob("*.js")), sorted(used))


def test_trace_layering():
    """录制的三块：driver 用 hook 和 analysis；hook、analysis 不 import driver（analysis 在任何系统上都要能用，
    hook 里注入被测进程的那段源码不能 import codestrata 自己——被测程序的 Python 里没有它）"""
    import ast
    base = HERE.parent / "codestrata" / "trace"

    def rel_imports(name):
        t = ast.parse((base / f"{name}.py").read_text(encoding="utf-8"))
        return {(n.module or "") for n in ast.walk(t) if isinstance(n, ast.ImportFrom) and n.level}
    assert not any("driver" in m for m in rel_imports("hook") | rel_imports("analysis")), (rel_imports("hook"), rel_imports("analysis"))
    assert rel_imports("hook") == set(), rel_imports("hook")
    sys.path.insert(0, str(HERE.parent))
    from codestrata.trace import hook
    src = ast.parse(hook._SITECUSTOMIZE)
    mods = {a.name for n in ast.walk(src) if isinstance(n, ast.Import) for a in n.names} | \
           {n.module for n in ast.walk(src) if isinstance(n, ast.ImportFrom)}
    assert not any(m and m.split(".")[0] == "codestrata" for m in mods), mods


def test_no_cross_module_private_names():
    """模块之间不用下划线开头的名字：别的模块要用的就是接口，该公开（`_模块._名字`，或 `from .模块 import _名字`，
    函数里面的也算）"""
    import ast
    bad = []
    for p in (HERE.parent / "codestrata").rglob("*.py"):
        t = ast.parse(p.read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.level:
                for a in n.names:
                    if a.name.startswith("_") and a.name != "__future__":
                        bad.append(f"{p.name}:{n.lineno} from .{n.module or ''} import {a.name}")
                    mods.add(a.asname or a.name)
        for n in ast.walk(t):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in mods
                    and n.attr.startswith("_") and not n.attr.startswith("__")):
                bad.append(f"{p.name}:{n.lineno} {n.value.id}.{n.attr}")
    assert not bad, bad


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
