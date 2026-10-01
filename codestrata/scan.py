"""静态扫描：用 ast 遍历一个 Python 仓库，产出总图需要的一切。

只用标准库。产出两个文件：

  index.json（画总图要的，小）
    format     2（单元、目录按路径认；1 是点分名）
    packages   单元：每个 .py 文件一个，id 是相对仓库根的路径；label 是点分的模块名（包的 __init__.py 是
               <包>.__init__），sep 是 "."；含「架构高度」
    edges      单元之间的 import 边，权重 = import 语句条数（不含 TYPE_CHECKING 里的）。图上不画（图上只有调用，
               见 graph.py），只给排版当权重、算架构高度
    dirs       目录树；default_open 是默认切面（图上显示哪一层，见 cut.py）
  symbols.json（按需加载，大）
    symbols    每个类/函数的 file:line、结束行、基类、所属单元
    files      文件 → 单元的映射，给 runtime tracer 反查用
    aux        包目录里的 C/C++/CUDA 文件 → 所在目录
    name_refs  字符串里按名字提到的仓库内的类（注册表、getattr、插件表）
    docs       作者写的文档 → 目录 / 单元（包内 README、frontmatter 声明了代码路径的设计文档）

「架构高度」= (出边 − 入边) / (出边 + 入边)，范围 [-1, +1]：

    +1  谁都不依赖它，它依赖一切  → 入口层（CLI、API server）
     0  双向都多                  → 中间层（引擎、调度）
    -1  只被依赖，自己不依赖别人  → 叶子工具（协议定义、metrics）

架构高度现在只是详情面板上的一个指标。图的纵轴改成了按依赖分层（layout.layers）：
出入度比值只看每个模块自己，不看谁连着谁，边会画成往上指。早先不用分层的理由是循环 import——vllm-omni
上 30 个二级包有 20 个在同一个强连通分量里、缩点后分层信息全丢；layers 不缩点，而是按边的权重打断
最轻的那些回边（贪心 + sifting），层太多时再压到 16 条泳道。
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import cut as _cut

SKIP_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", ".tox", ".venv", "venv", "env",
    "node_modules", "build", "dist", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".eggs", "site-packages",
}

# 包目录里的 C/C++/CUDA 源文件：挂在所在的包下供浏览，不参与 import 图
AUX_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".cu", ".cuh"}

# 这些顶层目录默认不进总图。它们 import 一切、却几乎无人 import，
# 算进去会把「架构高度」彻底冲掉：在 vllm-omni 上，把 tests/ 算进来会让
# entrypoints 从 +0.85 掉到 -0.33（因为测试大量 import 它，入度暴涨）。
# 注意 examples/ 仍然是 hot 图的 case 来源，只是不参与静态图与高度计算。
NON_LIB_DIRS = {
    "tests", "test", "testing", "examples", "example", "samples",
    "benchmarks", "benchmark", "bench", "docs", "doc", "scripts",
    "tools", "ci", "buildkite",
}


# 带语句体的节点：只有这些内部才可能出现 def / class。
# 用 getattr 兜住不同 Python 版本的差异（TryStar 是 3.11+，Match 是 3.10+）。
STMT_CONTAINERS = tuple(t for t in (
    ast.Module, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith,
    ast.Try, getattr(ast, "TryStar", None), getattr(ast, "Match", None),
    getattr(ast, "match_case", None), ast.ExceptHandler,
) if t is not None)


# 字符串里写的带模块的类路径：插件表、配置里的 worker_cls 之类（"a.b.Cls"、entry point 式的 "a.b:Cls"）
_QUALNAME_STR = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)[.:]([A-Z]\w*)")
# 打日志 / 打印的调用：参数里的字符串（"AsyncOmniEngine started"）不是按名字接线
_LOG_CALLS = frozenset(("debug", "info", "warning", "warn", "error", "exception", "critical", "log", "print",
                        "info_once", "warning_once", "debug_once"))


@dataclass
class Symbol:
    """一个类或函数的定义点。"""
    name: str            # 限定名，如 DuplexOmni 或 OmniBase._create_engine
    kind: str            # "class" | "func"
    file: str            # 相对仓库根
    line: int            # def/class 所在行
    dline: int           # 第一个装饰器所在行（无装饰器时等于 line）
    module: str          # 点分模块名
    pkg: str             # 聚合用的包名
    bases: list[str] = field(default_factory=list)
    end: int = 0         # 最后一行；runtime 里的闭包 / lambda 靠它归到外层符号
    decos: list[str] = field(default_factory=list)   # 装饰器名（最后一段）：类的 dataclass 之类，函数的 property 之类
    also: list[list[int]] = field(default_factory=list)  # 同名的另几个 def（property 的 setter、overload）：[[行, 装饰器行, 末行]]

    def key(self) -> str:
        """符号键：<文件路径>#<限定名>（不认语言；C++ / Rust 的限定名里有 ::，所以不拿冒号分）"""
        return f"{self.file}#{self.name}"

    def as_json(self) -> dict:
        d = {"n": self.name, "s": self.name.rsplit(".", 1)[-1], "k": self.kind, "f": self.file, "l": self.line,
             "m": self.module, "p": self.pkg, "lang": "python"}
        if self.kind == "class":
            # 类体在 class 语句执行时跑一次：落在类定义行上的帧是定义，不是调用（trace.analysis.defining）
            d["x"] = ["defexec"]
        if self.dline != self.line:
            d["dl"] = self.dline
        if self.bases:
            d["b"] = self.bases
        if self.end:
            d["e"] = self.end
        if self.decos:
            d["d"] = self.decos
        if self.also:
            d["a"] = self.also
        return d


def _deco_names(node) -> list[str]:
    """装饰器的名字，只留最后一段：@dataclass(frozen=True) → dataclass，@x.setter → setter，
    @functools.cached_property → cached_property"""
    out = []
    for d in node.decorator_list:
        fn = d.func if isinstance(d, ast.Call) else d
        try:
            out.append(ast.unparse(fn).split(".")[-1])
        except Exception:
            pass
    return out


def _skip_dir(parent: str, name: str) -> bool:
    """遍历时跳过的子目录：隐藏目录，和 SKIP_DIRS 里的名字——但只在它不是 Python 包的时候。
    build/、dist/ 这类名字在仓库顶层是构建产物，在包里却可能是真正的子包（pip 的
    _internal/operations/build/），有 __init__.py 的照扫"""
    if name.startswith("."):
        return True
    return name in SKIP_DIRS and not os.path.isfile(os.path.join(parent, name, "__init__.py"))


def _is_env(files, dirs) -> bool:
    """虚拟环境（pyvenv.cfg）或 conda 环境（conda-meta/）：里面是装好的第三方库和标准库，不是仓库代码。
    名字不固定（envs/xxx、venv-hx），SKIP_DIRS 按名字挡不住，按里面有什么认"""
    return "pyvenv.cfg" in files or "conda-meta" in dirs


def _subdirs(d: Path) -> list[Path]:
    """能进去找代码的子目录：不是隐藏目录、不在 SKIP_DIRS 里、不是环境目录，也不是软链（数据、模型目录
    常软链到大盘上，进去数文件会很慢；扫描本身（os.walk）也不跟软链）"""
    out = []
    for p in sorted(d.iterdir()):
        if p.is_dir() and not p.is_symlink() and not _skip_dir(str(d), p.name):
            try:
                names = os.listdir(p)
            except OSError:
                continue
            if not _is_env(names, names):
                out.append(p)
    return out


def iter_py_files(root: Path) -> Iterable[Path]:
    for dp, dn, fn in os.walk(root):
        if _is_env(fn, dn):
            dn[:] = []
            continue
        dn[:] = [d for d in dn if not _skip_dir(dp, d)]
        for f in fn:
            if f.endswith(".py"):
                yield Path(dp) / f


def detect_roots(root: Path) -> list[str]:
    """不给 --roots 时猜要扫哪些目录（只在命令行 scan 不指定、trace 找不到 scan 结果时用；主菜单里
    是用户自己勾）。依次：顶层的库包（跳过 tests/、examples/ 这类）→ src/<包> → 只有测试之类的包也行 →
    含 .py 最多的顶层目录"""
    pkgs = [p.name for p in _subdirs(root) if (p / "__init__.py").exists()]
    lib = [n for n in pkgs if n not in NON_LIB_DIRS]
    if lib:
        return sorted(lib)
    src = root / "src"
    if src.is_dir():
        inner = [p.name for p in _subdirs(src) if (p / "__init__.py").exists()]
        inner = [n for n in inner if n not in NON_LIB_DIRS] or inner
        if inner:
            return sorted(f"src/{n}" for n in inner)
    if pkgs:
        return sorted(pkgs)
    counts: dict[str, int] = {}
    for f in iter_py_files(root):
        rel = f.relative_to(root).parts
        if len(rel) > 1:
            counts[rel[0]] = counts.get(rel[0], 0) + 1
    return [max(counts, key=counts.get)] if counts else []


def clean_roots(roots: list[str]) -> list[str]:
    """命令行给的目录写法归一：去掉结尾的 /（shell 补全会带上）、开头的 ./，重复的只留一个。
    模块名按最后一段起：pkg/ 的最后一段是空的，仓库内的 import 就全对不上了"""
    out: list[str] = []
    for r in roots:
        r = os.path.normpath(r)
        if r not in out:
            out.append(r)
    return out


def check_roots(roots: list[str]) -> None:
    """这几个目录能不能一起扫，不能就 ValueError（说明为什么）：最后一段同名的（root_clashes），
    或者一个在另一个里面的（src 和 src/pkg：里面的文件会按两个模块名各扫一遍）"""
    clash = root_clashes(roots)
    if clash:
        raise ValueError("这些目录的最后一段同名，模块名会撞在一起、互相覆盖，一次只能扫其中一个："
                         + "；".join(f"{k}：{'、'.join(v)}" for k, v in clash.items()))
    nested = [(a, b) for a in roots for b in roots if a != b and b.startswith(a + "/")]
    if nested:
        raise ValueError("这些目录一个在另一个里面，里面的文件会按两个模块名各扫一遍，只能选其中一个："
                         + "；".join(f"{a} 包含 {b}" for a, b in nested))


def root_clashes(roots: list[str]) -> dict[str, list[str]]:
    """最后一段同名的几个目录（src/foo 和 tests/foo、hw1/tests 和 hw2/tests）：模块名按目录名起，
    一起扫会撞成同一批模块、互相覆盖。返回 {名字: [目录, …]}，没有冲突是空的"""
    by: dict[str, list[str]] = {}
    for r in roots:
        by.setdefault(r.rstrip("/").split("/")[-1], []).append(r)
    return {k: v for k, v in by.items() if len(v) > 1}


PROJECT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg")

# 扫描目录「.」：仓库根目录直接放着的 .py（研究代码的 train.py / render.py 这类入口脚本）。只取这一层，
# 不往下——下面的目录各自是别的扫描目录。图上它们装在一个以仓库名命名的目录节点里（scripts_package）
ROOT_SCRIPTS = "."


def root_py_files(root: Path, r: str) -> list[Path]:
    """一个扫描目录下要扫的 .py"""
    if r == ROOT_SCRIPTS:
        return [p for p in sorted(root.iterdir()) if p.suffix == ".py" and p.is_file()]
    base = root / r
    return list(iter_py_files(base)) if base.is_dir() else []


def scripts_package(root: Path, roots: list[str]) -> str:
    """「.」里的脚本在图上装进的目录节点名：仓库名（换掉点号、横杠这类字符）；和别的扫描目录撞名
    （仓库名和包名一样很常见）就加 _scripts"""
    name = re.sub(r"\W", "_", root.name) or "repo"
    others = {r.split("/")[-1] for r in roots if r != ROOT_SCRIPTS}
    return name + "_scripts" if name in others else name


def root_name(r: str, scripts: str) -> str:
    """扫描目录在模块名里的第一段（包名）"""
    return scripts if r == ROOT_SCRIPTS else r.split("/")[-1]


def candidate_roots(root: Path, depth: int = 3) -> list[dict]:
    """仓库里能选来扫描的目录（主菜单「静态扫描」的勾选框）。只列不挑——扫哪些由用户决定。
    从每个顶层目录往下找（最多 depth 层），列出的目录互不重叠：
      - 是 Python 包（有 __init__.py）：列它，不再往下
      - 是嵌套的工程（有 pyproject.toml / setup.py，比如仓库里 src/<项目>/）：进去接着找，里面的
        setup.py 不算「零散脚本」
      - 直接放着 .py（examples/、scripts/、放测试文件的 tests/）：列它本身（它下面的包也在里面）
      - 别的：进去接着找；到了 depth 层还不是包就列它本身
    环境目录（venv、conda env）不进去。返回 [{path（相对仓库根）, files（.py 文件数）, package}]"""
    root = root.resolve()
    out: list[dict] = []

    def add(d: Path, package: bool) -> None:
        n = sum(1 for _ in iter_py_files(d))
        if n:
            out.append({"path": str(d.relative_to(root)), "files": n, "package": package})

    def visit(d: Path, level: int) -> None:
        if (d / "__init__.py").exists():
            return add(d, True)
        kids = _subdirs(d)
        project = any((d / m).exists() for m in PROJECT_MARKERS)
        loose = not project and any(f.suffix == ".py" and f.is_file() for f in d.iterdir())
        if loose or not kids or level >= depth:
            return add(d, False)
        for k in kids:
            visit(k, level + 1)

    for d in _subdirs(root):
        visit(d, 1)
    n = len(root_py_files(root, ROOT_SCRIPTS))
    if n:
        out.insert(0, {"path": ROOT_SCRIPTS, "files": n, "package": False})
    return out


# 设计文档在 frontmatter 里声明自己管哪些代码（vllm-omni 的 docs/design 就是这样），
# 这几个键下面的列表项是仓库内路径（文件、目录或 dir/**）
DOC_PATH_KEYS = {"primary_code_paths": "primary", "code_paths": "primary",
                 "related_code_paths": "related"}


def collect_docs(root: Path, files: dict[str, str]) -> dict[str, list]:
    """把作者写的文档挂到包上：包目录里的 README，和 frontmatter 声明了代码路径的设计文档。

    「为什么这样写」作者往往在文档里写过。详情面板会列出它们，读代码的人先看作者自己的说法，
    而不是从命名去猜。
    """
    dir_pkg: dict[str, str] = {}
    for rel, unit in files.items():
        dir_pkg.setdefault(os.path.dirname(rel), _cut.unit_dir(unit))   # README 挂到它所在的目录
    out: dict[str, dict] = {}

    rank = {"readme": 0, "primary": 1, "related": 2, "mentions": 3}

    def paths_to_pkgs(path: str) -> set[str]:
        path = path.removesuffix("/**").removesuffix("/*").rstrip("/")
        if path in files:
            return {files[path]}
        return {pkg for fr, pkg in files.items()
                if fr.startswith(path + "/") or fr.startswith(path + ".")}

    def add(pkg: str, rel: str, kind: str, title: str) -> None:
        cur = out.setdefault(pkg, {}).get(rel)
        if cur is None or rank[kind] < rank[cur["kind"]]:
            out[pkg][rel] = {"f": rel, "kind": kind, "title": title}

    n = 0
    for dp, dn, fn in os.walk(root):
        if _is_env(fn, dn):
            dn[:] = []
            continue
        dn[:] = [d for d in dn if not _skip_dir(dp, d)]
        for f in fn:
            if not f.lower().endswith(".md"):
                continue
            n += 1
            if n > 5000:
                break
            p = Path(dp, f)
            rel = str(p.relative_to(root))
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), f)
            if f.lower().startswith("readme"):
                pkg = dir_pkg.get(os.path.dirname(rel))
                if pkg:
                    add(pkg, rel, "readme", title)
            if not text.startswith("---"):
                # 没有 frontmatter 的设计文档常在开头一段写「本文负责 `pkg/sub/**`」：
                # 开头 40 行里用反引号写出的仓库路径算「提到」（最弱的一档）
                head = "\n".join(text.splitlines()[:40])
                for m in re.finditer(r"`([\w./*-]+/[\w./*-]+)`", head):
                    for pkg in paths_to_pkgs(m.group(1)):
                        add(pkg, rel, "mentions", title)
                continue
            end = text.find("\n---", 3)
            if end < 0:
                continue
            kind = None
            for line in text[3:end].splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if not line.startswith((" ", "\t", "-")):          # 新的顶层键
                    k = s.split(":", 1)[0].strip()
                    kind = DOC_PATH_KEYS.get(k)
                    if k == "title":
                        title = s.split(":", 1)[1].strip().strip('"') or title
                    continue
                if kind and s.startswith("- "):
                    for pkg in paths_to_pkgs(s[2:].strip().strip('"').strip("'")):
                        add(pkg, rel, kind, title)
    return {pkg: sorted(v.values(), key=lambda d: (rank[d["kind"]], d["f"]))
            for pkg, v in out.items()}


def module_of(rel: Path) -> str:
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        parts.pop()
    elif parts:
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def scan(root: Path, depth: int | None = None, roots: list[str] | None = None,
         expand: list[str] | None = None) -> dict:
    """扫描仓库，返回 index 字典。

    记录的是最细的粒度（每个 .py 文件一个单元）和目录树；图上显示哪一层是 cut.py 的事。
    depth / expand 只决定默认切面：给了 depth 就展开所有深度小于它的目录（depth=2 是老的
    「二级包」）；不给就按规模自动拆分。expand 额外展开指定的目录。
    """
    root = root.resolve()
    # 用户给了 roots 就照单全收（包括 tests/ 这类：要不要扫是用户的决定）；没给才自动探测
    roots = clean_roots(roots) if roots else detect_roots(root)
    try:
        check_roots(roots)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    if not roots:
        raise SystemExit(f"在 {root} 下没找到 Python 包；用 --roots 手动指定")
    # 顶层包名集合，用来判断一条 import 是不是「内部依赖」
    scripts = scripts_package(root, roots)
    top = {root_name(r, scripts) for r in roots}

    def module_name(r: str, path: Path) -> str:
        # 模块名相对于包根的**父目录**算，文件路径仍相对仓库根。
        # src-layout（src/mypkg/...）下若相对仓库根算，模块名会变成 src.mypkg.x，
        # 而代码里写的是 import mypkg.x——所有边都指向不存在的包，图上一条边都画不出来。
        # 根目录的脚本装进 <仓库名>.<脚本名>（见 ROOT_SCRIPTS）
        if r == ROOT_SCRIPTS:
            return f"{scripts}.{path.stem}"
        return module_of(path.relative_to((root / r).parent))

    symbols: dict[str, Symbol] = {}
    files: dict[str, str] = {}
    pkg_files: dict[str, int] = {}
    pkg_loc: dict[str, int] = {}
    pkg_cls: dict[str, int] = {}
    pkg_fn: dict[str, int] = {}
    edges: dict[tuple[str, str], int] = {}
    file_loc: dict[str, int] = {}          # 文件 → 行数（含 C/C++/CUDA）
    file_sha: dict[str, str] = {}          # .py 文件 → 内容哈希
    str_refs: dict[str, list] = {}         # 像类名的字符串 → [[文件, 行], ...]（扫完只留仓库里有的类名）
    n_files = n_err = 0

    # 最细的粒度：每个 .py 文件是一个「单元」，依赖边、符号、调用明细都记在单元之间。
    # 单元 id 是文件相对仓库根的路径（不认语言，见 cut.py）；点分的模块名只作显示（label）：
    # 包目录的 __init__.py 显示成 <包>.__init__，目录本身的名字（vllm_omni.engine）留给
    # 图上「整个目录收起来」的那个节点——图上显示哪一层，由 cut.py 在目录树上取切面。
    unit_of_module: dict[str, str] = {}      # 点分模块名 → 单元（文件路径）：import 按模块名解析
    unit_label: dict[str, str] = {}
    for r in roots:
        for p in root_py_files(root, r):
            m = module_name(r, p)
            u = str(p.relative_to(root))
            unit_of_module[m] = u
            unit_label[u] = m + ".__init__" if p.name == "__init__.py" and r != ROOT_SCRIPTS else m
    # 不在包里的文件（examples/ 下的脚本、根目录的脚本）之间 `import helpers`：Python 把脚本所在目录放在
    # sys.path 最前面，找到的是同目录的 helpers.py / helpers/，模块名是 <那个目录的模块名>.helpers
    # （根目录的脚本是 <仓库名>.helpers）。仓库顶层有同名的包时包优先（根目录的脚本和顶层包在同一个目录里；
    # xref 的 script_module 同一个规则）
    in_pkg = {str(Path(u).parent) for u in unit_of_module.values() if u.endswith("__init__.py")}
    pkgs = {m for m, u in unit_of_module.items() if u.endswith("__init__.py")} | {   # 包和命名空间目录
        ".".join(m.split(".")[:i]) for m in unit_of_module for i in range(1, m.count(".") + 1)}

    def canon(name: str, rel: Path, module: str) -> str | None:
        """import 写的绝对模块名 → 仓库里的模块名；不是仓库里的（标准库、第三方）是 None"""
        head = name.split(".")[0]
        d = module.rpartition(".")[0]
        sib = f"{d}.{head}"
        # import a.b：同目录的 a 得是包（目录）才有子模块；import a：模块、包都行
        if d and str(rel.parent) not in in_pkg and head not in top and (
                sib in pkgs or ("." not in name and sib in unit_of_module)):
            return f"{d}.{name}"
        return name if head in top else None
    unresolved: dict[tuple[str, str], int] = {}

    for r in roots:
        for path in root_py_files(root, r):
            rel = path.relative_to(root)
            n_files += 1
            try:
                raw = path.read_bytes()
                # utf-8-sig：开头带 BOM 的文件（Windows 编辑器存的）照样能解析，早先整个文件被当成解析失败。
                # 换行和 read_text 一样统一成 \n
                src = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                tree = ast.parse(src)
            except (SyntaxError, ValueError, OSError):
                n_err += 1
                continue
            module = module_name(r, path)
            pkg = unit_of_module[module]           # 这个文件自己的单元
            files[str(rel)] = pkg
            file_loc[str(rel)] = src.count("\n") + 1
            # 内容哈希：和 trace 录制时记下的哈希同一种（runs.sha16），用来判断某个 run
            # 录制之后这个文件改过没有——叠加用的行号来自这份 index
            file_sha[str(rel)] = hashlib.sha256(raw).hexdigest()[:16]
            pkg_files[pkg] = pkg_files.get(pkg, 0) + 1
            pkg_loc[pkg] = pkg_loc.get(pkg, 0) + src.count("\n") + 1

            # 符号：类与顶层/类内函数，带限定名
            def add(s: Symbol) -> None:
                # 同一个名字又定义了一次（property 的 setter、overload、if/else 里的两个版本）：符号表照旧
                # 留最后一个，前面几个的位置记在 also 里——trace 按「文件:首行」记，哪一个跑到都是这个符号
                # 只合并同一个文件里、同一种（都是函数或都是类）的：不同文件同名是模块名撞了（root_clashes 挡着），
                # 一个是函数一个是类的，trace 要靠种类分「调用」和「定义」，不能混成一个
                old = symbols.get(s.key())
                if old is not None and old.file == s.file and old.kind == s.kind:
                    s.also = old.also + [[old.line, old.dline, old.end]]
                symbols[s.key()] = s

            def walk(node: ast.AST, prefix: str = "") -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.ClassDef):
                        qn = f"{prefix}{child.name}"
                        bases = []
                        for b in child.bases:
                            try:
                                bases.append(ast.unparse(b))
                            except Exception:
                                pass
                        dl = min([d.lineno for d in child.decorator_list] + [child.lineno])
                        add(Symbol(qn, "class", str(rel), child.lineno, dl, module, pkg, bases,
                                   child.end_lineno or 0, _deco_names(child)))
                        pkg_cls[pkg] = pkg_cls.get(pkg, 0) + 1
                        walk(child, qn + ".")
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qn = f"{prefix}{child.name}"
                        dl = min([d.lineno for d in child.decorator_list] + [child.lineno])
                        add(Symbol(qn, "func", str(rel), child.lineno, dl, module, pkg,
                                   end=child.end_lineno or 0, decos=_deco_names(child)))
                        pkg_fn[pkg] = pkg_fn.get(pkg, 0) + 1
                        walk(child, qn + ".")
                    elif isinstance(child, STMT_CONTAINERS):
                        # def/class 只能出现在语句位置，所以只需下潜进「带语句体的节点」。
                        # 早先只白名单了 If/Try/With，for 循环体里的嵌套函数全漏了
                        # （codestrata 自扫描时这一个漏洞吃掉 86 次调用）；
                        # 但换成无条件递归又会退化成遍历整棵 AST（含表达式子树），
                        # 在 vllm-omni 上慢一个量级。白名单语句容器兼顾两者。
                        walk(child, prefix)

            walk(tree)

            # 字符串里写着的类名：注册表按名字登记类（{"Arch": ("pkg", "mod", "Cls")}）、getattr(mod, "Cls")、
            # 插件表。先收下所有像类名的字符串（大写开头的标识符），扫完再只留仓库里真有这个类名的——
            # 动态分派调到的类，边详情（align.hints）靠它回答「是在哪儿按名字接上的」。__all__ 里的是再导出清单，不算
            # 类型标注里的字符串（前向引用 `x: "Cls"`、`-> "Cls"`）、f-string、打日志的字符串也不算：它们不是在接线
            in_all: set[int] = set()
            named: list[tuple[str, int]] = []
            for n2 in ast.walk(tree):
                skip = None
                if isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    skip = [a.annotation for a in n2.args.args + n2.args.posonlyargs + n2.args.kwonlyargs
                            + [n2.args.vararg, n2.args.kwarg] if a is not None and a.annotation is not None] + [n2.returns]
                elif isinstance(n2, ast.AnnAssign):
                    skip = [n2.annotation]
                elif isinstance(n2, ast.JoinedStr):
                    skip = [n2]
                elif (isinstance(n2, ast.Call) and isinstance(n2.func, (ast.Attribute, ast.Name))
                      and (n2.func.attr if isinstance(n2.func, ast.Attribute) else n2.func.id) in _LOG_CALLS):
                    skip = n2.args
                for s in skip or ():
                    if s is not None:
                        in_all.update(id(c) for c in ast.walk(s))
                if isinstance(n2, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    tg = n2.targets if isinstance(n2, ast.Assign) else [n2.target]
                    if any(isinstance(t, ast.Name) and t.id == "__all__" for t in tg) and n2.value is not None:
                        in_all.update(id(c) for c in ast.walk(n2.value))
                elif isinstance(n2, ast.Constant) and isinstance(n2.value, str) and 2 < len(n2.value) < 200:
                    v = n2.value
                    if v[0].isupper() and v.isidentifier():
                        named.append((v, None, n2.lineno, id(n2)))
                    elif (q := _QUALNAME_STR.fullmatch(v)):     # "pkg.mod.Cls" / "pkg.mod:Cls"：带着模块，没有歧义
                        named.append((q.group(2), q.group(1), n2.lineno, id(n2)))
            for v, mod, ln, i in named:
                if i not in in_all:
                    str_refs.setdefault(v, []).append([str(rel), ln] + ([mod] if mod else []))

            # 单元间 import 边（只算内部依赖）。`if TYPE_CHECKING:` 里的 import 只服务于类型标注，运行时根本
            # 不执行：不算依赖
            typeonly: set[int] = set()
            for n2 in ast.walk(tree):
                if isinstance(n2, ast.If):
                    t = n2.test
                    if (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or \
                       (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"):
                        for n3 in n2.body:
                            for n4 in ast.walk(n3):
                                if isinstance(n4, (ast.Import, ast.ImportFrom)):
                                    typeonly.add(id(n4))
            is_init = rel.name == "__init__.py"
            for node in ast.walk(tree):
                # 每个导入名各自解析：`from pkg import a, b` 里 a、b 可能是子模块，也可能是 pkg 里的名字
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    mod0 = None
                    if node.level:
                        # 相对 import。先算出「点号指向的那个包」：一个点是当前文件所在的包。
                        # __init__.py 的模块名就是包本身，所以它不用再往上退一层——早先按
                        # 普通模块处理，pkg/__init__.py 里的 `from .x import` 被解析成
                        # 兄弟包 x，vllm-omni 上凭空多出 15 条指向不存在的包的边。
                        up = module.split(".")
                        up = up[: max(0, len(up) - node.level + (1 if is_init else 0))]
                        base = ".".join(up)
                        mod0 = (f"{base}.{node.module}" if base else node.module) if node.module else base
                    elif node.module:
                        mod0 = canon(node.module, rel, module)
                    if mod0:
                        for a in node.names:
                            sub = f"{mod0}.{a.name}"
                            # from . import layout / from pkg import submodule：导入的是子模块
                            targets.append(sub if a.name != "*" and sub in unit_of_module else mod0)
                elif isinstance(node, ast.Import):
                    targets = [c for a in node.names if (c := canon(a.name, rel, module))]
                seen_dst: set[str] = set()
                for target in targets:
                    dst = unit_of_module.get(target)
                    if dst is None:
                        # 指向仓库里不存在的模块（构建时生成的 _version.py、可选依赖的桩……）：
                        # 没有节点可画，只记数
                        unresolved[(pkg, target)] = unresolved.get((pkg, target), 0) + 1
                        continue
                    if dst != pkg and dst not in seen_dst and id(node) not in typeonly:
                        seen_dst.add(dst)
                        edges[(pkg, dst)] = edges.get((pkg, dst), 0) + 1

    # 架构高度
    out: dict[str, int] = {}
    inn: dict[str, int] = {}
    for (a, b), w in edges.items():
        out[a] = out.get(a, 0) + w
        inn[b] = inn.get(b, 0) + w
    packages = {}
    for p in sorted(pkg_files):
        o, i = out.get(p, 0), inn.get(p, 0)
        packages[p] = {
            "files": pkg_files[p], "loc": pkg_loc.get(p, 0),
            "classes": pkg_cls.get(p, 0), "funcs": pkg_fn.get(p, 0),
            "out": o, "in": i,
            "alt": round((o - i) / (o + i), 4) if (o + i) else 0.0,
            "label": unit_label[p], "sep": ".",
        }

    # 包目录里的 C++ / CUDA 源文件：挂到所在的包下，供浏览和高亮。
    # 它们不进 import 图——C++ 与 Python 之间的绑定边（pybind、torch.ops）
    # 需要真正的 C++ 解析（tree-sitter），是另一件事。
    aux: dict[str, str] = {}

    def add_aux(p: Path, where: str) -> None:
        aux[str(p.relative_to(root))] = where
        try:
            with open(p, "rb") as fh:
                file_loc[str(p.relative_to(root))] = fh.read().count(b"\n") + 1
        except OSError:
            pass

    def walk_aux(top_dir: Path, skip: set[Path]):
        for dp, dn, fn in os.walk(top_dir):
            if _is_env(fn, dn):
                dn[:] = []
                continue
            dn[:] = [d for d in dn if not _skip_dir(dp, d) and Path(dp, d) not in skip]
            for f in fn:
                if os.path.splitext(f)[1].lower() in AUX_EXTS:
                    yield Path(dp, f)

    chosen = {(root / r).resolve() for r in roots if r != ROOT_SCRIPTS}
    for r in roots:
        base = root / r
        if r == ROOT_SCRIPTS or not base.is_dir():
            continue
        for p in walk_aux(base, set()):
            # 挂到所在目录；图上显示在包含这个目录的节点里
            add_aux(p, _cut.unit_dir(str(p.relative_to(root))))
        # 包在一个嵌套的工程里（submodules/<工程>/<包>，工程目录有 setup.py）：C++ / CUDA 源码常放在
        # 包旁边（3DGS 的 diff-gaussian-rasterization/cuda_rasterizer/），也挂到这个包上。
        # 仓库根目录这一层不这么做：那会把整个仓库的 C 代码都挂到一个包上
        proj = base.parent
        if proj.resolve() != root and any((proj / m).exists() for m in PROJECT_MARKERS):
            for p in walk_aux(proj, chosen):
                add_aux(p, _cut.root_dir(r))

    docs = collect_docs(root, files)
    class_names = {s.name.rsplit(".", 1)[-1] for s in symbols.values() if s.kind == "class"}
    index = {
        "format": _cut.INDEX_FORMAT,
        "docs": docs, "file_loc": file_loc,
        "repo": {"root": str(root), "name": root.name, "roots": roots,
                 "n_files": n_files, "n_parse_errors": n_err,
                 # 哪个文件 import 了哪个模块：文件写路径，模块写 import 语句里的点分名（仓库里没有它，也就没有路径）
                 "unresolved_imports": sorted(f"{a}：import {b}" for a, b in unresolved),
                 "n_aux": len(aux)},
        "aux": aux,
        # 字符串里按名字提到的仓库内的类：{"类名": [[文件, 行], ...]}（注册表、getattr、插件表）
        "name_refs": {k: v for k, v in sorted(str_refs.items()) if k in class_names},
        "packages": packages,
        "edges": [[a, b, w] for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1])],
        "symbols": {k: s.as_json() for k, s in symbols.items()},
        "files": files,
        "file_sha": file_sha,
        "dirs": _cut.dir_tree(packages, roots),
    }
    # 图上默认显示哪一层：按规模自动拆分，或按用户给的 depth / expand
    index["default_open"], index["repo"]["auto_split"] = _cut.default_open(index, depth=depth, expand=expand)
    return index


def write_index(root: Path, index: dict, outdir: Path | None = None) -> Path:
    """写盘。符号表单独存 symbols.json——它比图数据大一两个数量级，
    渲染总图时不需要全量加载。"""
    outdir = outdir or (root / ".codestrata")
    outdir.mkdir(parents=True, exist_ok=True)
    symbols = index.pop("symbols", {})
    files = index.pop("files", {})
    aux = index.pop("aux", {})
    name_refs = index.pop("name_refs", {})
    docs = index.pop("docs", {})
    file_loc = index.pop("file_loc", {})
    file_sha = index.pop("file_sha", {})
    (outdir / "symbols.json").write_text(
        json.dumps({"symbols": symbols, "files": files, "aux": aux, "docs": docs, "file_loc": file_loc,
                    "file_sha": file_sha, "name_refs": name_refs},
                   ensure_ascii=False),
        encoding="utf-8")
    index["n_symbols"] = len(symbols)
    p = outdir / "index.json"
    p.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    index["symbols"], index["files"], index["aux"] = symbols, files, aux   # 调用方还要用
    index["name_refs"] = name_refs
    index["docs"] = docs
    index["file_loc"] = file_loc
    index["file_sha"] = file_sha
    return p
