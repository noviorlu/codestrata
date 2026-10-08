"""打包和发布：非 -e 安装的包里要有前端（web/ 下每个文件），不然 serve 全是 404、graph 导出崩；拿整个工作区打出来的
sdist / wheel 里不能有内部文档、.codestrata/、构建残留；装进一个干净的 venv 能跑 scan / trace / serve；公开文档里没有内部内容。

    .venv/bin/python tests/test_package.py
要 uv（用它构建、建 venv）；没有就跳过那几个。
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

from common import HERE, run_tests, tmpdir  # noqa: E402

ROOT = HERE.parent
# 工作区里有、但不能进 sdist / wheel 的：内部文档（.gitignore 里那几样）、数据目录、构建残留
INTERNAL = ("CLAUDE.md", "docs/README.md", "docs/STATUS.md", "docs/TODO.md", "docs/FINDINGS.md",
            "docs/log/", "docs/archive/", "docs/plans/", ".codestrata/", "build/", "dist/")
_BUILT: dict = {}


def _release_build(uv: str):
    """把整个工作区（连 .gitignore 挡着的内部文档、.codestrata/ 一起，只去掉 .venv、.git、__pycache__）拷一份，打 sdist 和 wheel：
    从工作区直接打包的最坏情况。返回 (sdist 路径, wheel 路径)，同一次运行里只打一次"""
    if "dist" not in _BUILT:
        tmp = tmpdir("cs-release-")
        src, out = tmp / "src", tmp / "dist"
        shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "*.pyc", "node_modules"))
        r = subprocess.run([uv, "build", "--out-dir", str(out), str(src)], capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, r.stdout + r.stderr
        _BUILT["dist"] = (next(out.glob("*.tar.gz")), next(out.glob("*.whl")))
    return _BUILT["dist"]


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
    assert "codestrata/trace/cupti_inject.cpp" in names, "wheel 里没有 GPU 录制端的源码（trace --gpu 现编要它）"


def test_release_artifacts_clean():
    """拿整个工作区打的 sdist / wheel：wheel 只有 codestrata 包和它的 dist-info；sdist 是包、README、LICENSE、pyproject 和完整的测试
    （MANIFEST.in），没有内部文档、.codestrata/、构建残留"""
    uv = shutil.which("uv")
    if not uv:
        print("    （没有 uv，跳过）")
        return
    sdist, wheel = _release_build(uv)
    wn = zipfile.ZipFile(wheel).namelist()
    bad = [n for n in wn if not (n.startswith("codestrata/") or re.match(r"codestrata-[^/]+\.dist-info/", n))]
    assert not bad, f"wheel 里有包以外的东西：{bad[:10]}"
    with tarfile.open(sdist) as t:
        sn = [n.split("/", 1)[1] for n in t.getnames() if "/" in n]
    leak = [n for n in sn if any(n == x or n.startswith(x) for x in INTERNAL) or n.endswith((".pyc", ".pyo"))]
    assert not leak, f"sdist 里有内部文件 / 数据 / 构建残留：{leak[:10]}"
    for need in ("README.md", "LICENSE", "pyproject.toml", "codestrata/web/index.html", "tests/common.py", "tests/web/run.mjs"):
        assert need in sn, f"sdist 里没有 {need}"
    assert any(n.startswith("tests/trace_cases/") for n in sn), "sdist 里的测试缺了 trace_cases/（跑不起来）"


def test_wheel_installs_and_runs():
    """发布出去的 wheel 装进一个干净的 venv（不带源码树）：命令能跑，scan、trace（hook 注入、子进程照样录）、serve 起页面和 /api/graph 都通"""
    uv = shutil.which("uv")
    if not uv:
        print("    （没有 uv，跳过）")
        return
    _, wheel = _release_build(uv)
    tmp = tmpdir("cs-install-")
    venv, repo = tmp / "venv", tmp / "repo"
    r = subprocess.run([uv, "venv", "-q", "--python", sys.executable, str(venv)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([uv, "pip", "install", "-q", "--python", str(venv / "bin" / "python"), str(wheel)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    cs = str(venv / "bin" / "codestrata")
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "b.py").write_text("def work(x):\n    return x * 2\n")
    (repo / "pkg" / "a.py").write_text("from pkg.b import work\n\n\ndef main():\n    return sum(work(i) for i in range(3))\n\n\n"
                                       "if __name__ == '__main__':\n    print(main())\n")
    env = {"PATH": f"{venv / 'bin'}:/usr/bin:/bin", "HOME": str(tmp)}
    run = lambda *a: subprocess.run([cs, *a], capture_output=True, text=True, timeout=120, env=env, cwd=repo)  # noqa: E731
    r = run("--help")
    assert r.returncode == 0 and "codestrata scan" in r.stdout and "codestrata path" in r.stdout, r.stdout + r.stderr
    ver = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    r = run("--version")
    assert r.returncode == 0 and r.stdout.strip() == f"codestrata {ver}", r.stdout + r.stderr
    r = run("scan", str(repo))
    assert r.returncode == 0 and (repo / ".codestrata" / "index.json").is_file(), r.stdout + r.stderr
    r = run("trace", str(repo), "--case", "hello", "--", str(venv / "bin" / "python"), "-m", "pkg.a")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("runs", str(repo), "ls")
    assert r.returncode == 0 and "hello" in r.stdout, r.stdout + r.stderr
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
    srv = subprocess.Popen([cs, "serve", str(repo), "--port", str(port), "--hot", "hello"], env=env, cwd=repo,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def get(path: str) -> tuple[int, bytes]:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as resp:
                        return resp.status, resp.read()
                except OSError:
                    time.sleep(0.1)
            raise AssertionError("serve 没起来")
        st, body = get("/")
        assert st == 200 and b"<title>codestrata</title>" in body, body[:200]
        assert all(get(f"/{f}")[0] == 200 for f in ("app.js", "lanes.js", "app.css")), "装好的包里前端文件取不到"
        st, body = get("/api/graph?run=hello")
        g = json.loads(body)
        # 叠上了这次录的调用：a.py → b.py 的 work 被调 3 次（hook 是从装好的包里注入的）
        assert st == 200 and g["graph"]["nodes"] and g["hot"] and (g["hot"].get("packages") or {}).get("pkg/b.py") == 3, \
            (st, (g.get("hot") or {}).get("packages"))
    finally:
        srv.kill()
        srv.wait()


def test_public_docs_no_internal_content():
    """公开文档（README、docs/usage、ARCHITECTURE、design/）不写内部内容：对话原话、「用户…定的」、评审、内部标记、
    也不链接内部文档（它们在 .gitignore 里，发布出去的仓库里没有）"""
    pat = re.compile(r"用户 ?(?:20\d\d-)?\d\d-\d\d|用户：「|用户的原话|外部评审|critic|xiaochun|主会话|子 agent|\bP0\b|设计稿第|设计稿 \d"
                     r"|STATUS\.md|TODO\.md|FINDINGS\.md|CLAUDE\.md|docs/log/|docs/archive|docs/plans")
    bad = []
    # git 管着的 .md 就是公开的（内部文档在 .gitignore 里）；没有 git（从 sdist 跑测试）时按公开文档的清单
    r = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True)
    docs = [ROOT / f for f in r.stdout.split("\n") if f] if r.returncode == 0 and r.stdout.strip() else \
        [ROOT / "README.md", ROOT / "docs" / "usage.md", ROOT / "docs" / "ARCHITECTURE.md", *sorted((ROOT / "docs" / "design").glob("*.md"))]
    for p in docs:
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            m = pat.search(line)
            if m:
                bad.append(f"{p.relative_to(ROOT)}:{i}: {m.group(0)}")
    assert not bad, bad[:20]


def test_web_scripts_all_loaded():
    """web/ 下每个 .js 都有页面用 <script> 加载：漏了的话，调到它的地方会报错（时间轴的 timebar.js 就漏过）"""
    import re
    web = HERE.parent / "codestrata" / "web"
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
