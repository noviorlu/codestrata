"""scan 产出的 graph（graph.py）：函数之间的调用、定不下被调方的调用处，和调用方是哪个节点。

    .venv/bin/python tests/test_graph.py
只扫描，不录制，几秒钟。
"""
from __future__ import annotations

import json
import sys

from common import cs, run_tests, tmpdir  # noqa: E402

from codestrata import graph, payload, scan, xref  # noqa: E402

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
    assert g["format"] == 4, g["format"]
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
    """索引格式升到 4（多了 graph.json）：旧格式的索引提示重新 scan"""
    repo = _repo()
    cs("scan", repo)
    p = repo / ".codestrata" / "index.json"
    d = json.loads(p.read_text())
    d["format"] = 3
    p.write_text(json.dumps(d))
    try:
        payload.load_index(repo)
        raise AssertionError("旧格式没有被拒绝")
    except SystemExit as e:
        assert "重新跑一次 codestrata scan" in str(e), e
    assert payload.index_summary(repo)["outdated"] is True


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
