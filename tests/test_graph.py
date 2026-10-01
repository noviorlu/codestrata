"""scan 产出的 graph（graph.py）：函数之间的调用、定不下被调方的调用处，和调用方是哪个节点。

    .venv/bin/python tests/test_graph.py
只扫描，不录制，几秒钟。
"""
from __future__ import annotations

import json
import sys

from common import cs, run_tests, tmpdir  # noqa: E402

from codestrata import graph, scan, xref  # noqa: E402
from codestrata.ui import load as ui_load  # noqa: E402

_SRC = {
    "pkg/__init__.py": "",
    "pkg/base.py": (
        "import os\n\n\n"
        "def deco(fn):\n    return fn\n\n\n"
        "def factory(tag):\n    def wrap(fn):\n        return fn\n    return wrap\n\n\n"
        "class Box:\n"
        "    size = len('abc')\n\n"
        "    def __init__(self, n):\n        self.n = n\n\n"
        "    def __getitem__(self, i):\n        return i\n\n"
        "    @property\n    def area(self):\n        return self.n * 2\n\n"
        "    def double(self):\n        return self.area * 2\n\n"
        "    def run(self):\n        return self.helper()\n\n"
        "    def helper(self):\n        return os.getcwd()\n\n\n"
        "class Sub(Box):\n"
        "    def run(self):\n        return super().run()\n"
    ),
    "pkg/use.py": (
        "from pkg.base import Box, Sub, deco, factory\n\n"
        "REG = {}\n\n\n"
        "@deco\n"
        "def a():\n"
        "    b = Box(3)\n"
        "    w = b[0]\n"
        "    f = lambda: Sub(1)\n"
        "    g = sum(x.run() for x in [b])\n"
        "    h = [Box(i) for i in range(2)]\n"
        "    getattr(b, 'helper')()\n"
        "    return thing.go(\n"
        "        1,\n"
        "        2)\n\n\n"
        "@factory('t')\n"
        "def c():\n"
        "    def inner():\n        return a()\n"
        "    return inner()\n\n\n"
        "register = REG.setdefault('k', a)\n"
        "a()\n"
    ),
}


def _repo():
    d = tmpdir("cs-graph-") / "repo"
    for rel, text in _SRC.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def _line(rel: str, needle: str) -> int:
    return next(i for i, x in enumerate(_SRC[rel].splitlines(), 1) if needle in x)


def _edges(g: dict) -> set:
    """(调用方, 被调方, 行, 末行, 种类) 和 (调用方, 名字, 行, 末行, 种类)"""
    out = set()
    for caller, xs in g["calls"].items():
        out |= {(caller, g["callees"][i], l, e, k) for i, l, e, k in xs}
    for caller, xs in g["sites"].items():
        out |= {(caller, n, l, e, k) for n, l, e, k in xs}
    return out


def test_calls_and_sites():
    """定下了被调方的调用、构造、装饰器、property、语法触发的特殊方法、getattr 字符串、仓库外的调用、
    跨行的调用；调用方是函数 / 嵌套函数 / lambda / 生成器表达式 / 模块顶层 / 类体（推导式算外层）"""
    repo = _repo()
    cs("scan", repo)
    g = json.loads((repo / ".codestrata" / "graph.json").read_text())
    assert g["format"] == 5, g["format"]
    E = _edges(g)
    U, B = "pkg/use.py", "pkg/base.py"
    lu = lambda s: _line(U, s)
    lb = lambda s: _line(B, s)
    last = len(_SRC[U].splitlines())
    want = {
        (f"{U}#a", f"{B}#Box", lu("b = Box(3)"), lu("b = Box(3)"), graph.NEW),
        (f"{U}#a", "__getitem__", lu("w = b[0]"), lu("w = b[0]"), graph.SYN),
        (f"{U}#a.<L{lu('lambda')}>", f"{B}#Sub", lu("lambda"), lu("lambda"), graph.NEW),
        (f"{U}#a", "sum", lu("g = sum"), lu("g = sum"), graph.CALL),
        (f"{U}#a.<L{lu('g = sum')}>", "run", lu("g = sum"), lu("g = sum"), graph.CALL),
        (f"{U}#a", f"{B}#Box", lu("h = [Box"), lu("h = [Box"), graph.NEW),        # 列表推导式：算外层
        (f"{U}#a", "helper", lu("getattr"), lu("getattr"), graph.STR),
        (f"{U}#a", None, lu("getattr"), lu("getattr"), graph.CALL),               # getattr(…)()：没有名字
        (f"{U}#a", "go", lu("thing.go("), lu("        2)"), graph.CALL),               # 跨三行
        (f"{U}#<module>", f"{B}#deco", lu("@deco"), lu("@deco"), graph.DECO),
        (f"{U}#<module>", f"{B}#factory", lu("@factory"), lu("@factory"), graph.CALL),
        (f"{U}#c.inner", f"{U}#a", lu("return a()"), lu("return a()"), graph.CALL),
        (f"{U}#c", f"{U}#c.inner", lu("return inner()"), lu("return inner()"), graph.CALL),
        (f"{U}#<module>", "setdefault", lu("register"), lu("register"), graph.CALL),
        (f"{U}#<module>", f"{U}#a", last, last, graph.CALL),                       # 最后一行的 a()
        (f"{B}#Box", "len", lb("size = len"), lb("size = len"), graph.CALL),     # 类体
        (f"{B}#Box.double", f"{B}#Box.area", lb("self.area * 2"), lb("self.area * 2"), graph.PROP),
        (f"{B}#Box.run", f"{B}#Box.helper", lb("self.helper()"), lb("self.helper()"), graph.CALL),
        (f"{B}#Sub.run", f"{B}#Box.run", lb("super().run()"), lb("super().run()"), graph.CALL),
        (f"{B}#Box.helper", "getcwd", lb("os.getcwd"), lb("os.getcwd"), graph.EXT),
    }
    missing = want - E
    assert not missing, sorted(missing, key=str)
    # __init__ 不是语法触发的（构造另记在 calls 里）
    assert not any(k == graph.SYN and n == "__init__" for _, n, _, _, k in E), E


def test_xref_unchanged_by_graph():
    """on_file 只是多收一份调用：xref.json 的内容和不收时逐项一样"""
    repo = _repo()
    idx = scan.scan(repo)
    b = graph.Builder(idx)
    assert xref.build(repo, idx) == xref.build(repo, idx, on_file=b.add_file)
    assert b.result()["calls"], b.result()


def test_old_index_format_refused():
    """索引格式升到 5（graph.json 多了 ctors）：旧格式的索引提示重新 scan"""
    repo = _repo()
    cs("scan", repo)
    p = repo / ".codestrata" / "index.json"
    d = json.loads(p.read_text())
    d["format"] = 4
    p.write_text(json.dumps(d))
    try:
        ui_load.load_index(repo)
        raise AssertionError("旧格式没有被拒绝")
    except SystemExit as e:
        assert "重新跑一次 codestrata scan" in str(e), e
    assert ui_load.index_summary(repo)["outdated"] is True


_CTOR_SRC = {
    "ck/__init__.py": "",
    "ck/root.py": "class Root:\n    def __init__(self):\n        self.r = 1\n",
    "ck/m.py": (
        "from dataclasses import dataclass\n\nfrom ck.root import Root\nfrom other_lib import Ext\n\n\n"
        "class Own:\n    def __init__(self):\n        self.x = 1\n\n\n"
        "class Inherit(Root):\n    pass\n\n\n"
        "class Both:\n    def __new__(cls):\n        return super().__new__(cls)\n\n"
        "    def __init__(self):\n        self.ok = True\n\n\n"
        "@dataclass\nclass Cfg:\n    n: int = 1\n\n\n"
        "@dataclass\nclass Post(Root):\n    n: int = 1\n\n    def __post_init__(self):\n        self.m = self.n\n\n\n"
        "class Plain:\n    pass\n\n\n"
        "class Mixed(Ext, Root):\n    pass\n\n\n"
        "class Prop:\n"
        "    @property\n    def v(self):\n        return 1\n\n"
        "    @v.setter\n    def v(self, x):\n        pass\n\n"
        "    def bump(self):\n        self.v = 5\n        del self.v\n        return self.v\n\n\n"
        "def make():\n    return Own(), Inherit(), Both(), Cfg(), Post(), Plain(), Mixed()\n"
    ),
}


def test_ctor_methods_and_property_setters():
    """构造过的类在 graph.json 的 ctors 里记下构造时跑到的仓库里的方法（沿继承找；dataclass 生成的 __init__、
    只有仓库外基类的都不在仓库里，是 []；仓库外基类后面的仓库里的基类照样找）。
    有 setter 的 property：读、赋值、del 都是调用（PROP）"""
    d = tmpdir("cs-graph-") / "repo"
    for rel, text in _CTOR_SRC.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    cs("scan", d)
    g = json.loads((d / ".codestrata" / "graph.json").read_text())
    M, R = "ck/m.py#", "ck/root.py#"
    assert g["ctors"] == {
        f"{M}Own": [f"{M}Own.__init__"], f"{M}Inherit": [f"{R}Root.__init__"],
        f"{M}Both": [f"{M}Both.__new__", f"{M}Both.__init__"],
        f"{M}Cfg": [], f"{M}Post": [f"{M}Post.__post_init__"],       # 生成的 __init__ 盖住了 Root.__init__
        f"{M}Plain": [], f"{M}Mixed": [f"{R}Root.__init__"]}, g["ctors"]
    src = _CTOR_SRC["ck/m.py"].splitlines()
    want = {i for i, x in enumerate(src, 1) if x.strip() in ("self.v = 5", "del self.v", "return self.v")}
    got = {l for i, l, _, k in g["calls"][f"{M}Prop.bump"] if k == graph.PROP and g["callees"][i] == f"{M}Prop.v"}
    assert got == want, (got, want)


_SCRIPT_SRC = {
    "lib/__init__.py": "",
    "lib/m.py": (
        "from __future__ import annotations\n\n\n"
        "class Config:\n    pass\n\n\n"
        "class Builder:\n"
        "    class Key:\n        pass\n\n"
        "    def Config(self) -> Config:\n        return Config()\n\n"
        "    def build(self, c: Config, k: Key) -> list[Config]:\n        return [c]\n"),
    "examples/demo/helpers.py": "def greet():\n    return 'hi'\n",
    "examples/demo/tool/__init__.py": "def run():\n    return 1\n",
    "examples/demo/main.py": ("import helpers\nimport tool\nfrom helpers import greet\nfrom json.decoder import JSONDecoder\n\n\n"
                              "def main():\n    return helpers.greet() + greet() + tool.run()\n"),
    "examples/demo/json.py": "X = 1\n",                    # 同目录的 json.py 遮住标准库 json，但它不是包，json.decoder 还是标准库的
}


def test_script_imports_and_lazy_annotations():
    """不在包里的脚本（examples/ 下）之间 `import helpers`：找到的是同目录的 helpers.py / tool/（Python 把脚本所在目录
    放在 sys.path 最前面）；`import a.b` 要同目录的 a 是包才算。from __future__ import annotations 下，方法签名里的
    `Config` 不会是类里同名的方法 Config（标注不求值），类里的嵌套类照样看得见"""
    d = tmpdir("cs-graph-") / "repo"
    for rel, text in _SCRIPT_SRC.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    cs("scan", d, "--roots", "lib", "examples")
    cd = d / ".codestrata"
    x = json.loads((cd / "xref.json").read_text())
    T = x["targets"]

    def at(rel, needle, word):
        src = _SCRIPT_SRC[rel].splitlines()
        l = next(i for i, s in enumerate(src, 1) if needle in s)
        col = src[l - 1].index(word, src[l - 1].index(needle))
        hit = [T[t] for ln, a, b, t, k in x["files"][rel] if ln == l and a == col]
        return hit[0] if hit else None
    D = "examples/demo/"
    assert at(f"{D}main.py", "import helpers", "helpers") == f"m:{D}helpers.py"
    assert at(f"{D}main.py", "import tool", "tool") == f"m:{D}tool/__init__.py"
    assert at(f"{D}main.py", "from helpers import greet", "greet") == f"s:{D}helpers.py#greet"
    assert at(f"{D}main.py", "from json.decoder", "decoder") == "x:json.decoder"
    assert at(f"{D}main.py", "return helpers.greet()", "greet") == f"s:{D}helpers.py#greet"
    M = "lib/m.py"
    assert at(M, "def build", "Config") == f"s:{M}#Config", at(M, "def build", "Config")
    assert at(M, "def build", "Key") == f"s:{M}#Builder.Key"
    g = json.loads((cd / "graph.json").read_text())
    called = {g["callees"][i] for i, *_ in g["calls"][f"{D}main.py#main"]}
    assert {f"{D}helpers.py#greet", f"{D}tool/__init__.py#run"} <= called, called
    edges = {(a, b) for a, b, _ in json.loads((cd / "index.json").read_text())["edges"]}
    assert {(f"{D}main.py", f"{D}helpers.py"), (f"{D}main.py", f"{D}tool/__init__.py")} <= edges, edges
    assert not any(b == f"{D}json.py" for _, b in edges), edges


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
