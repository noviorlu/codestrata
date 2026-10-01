"""scan 产出的 graph：函数之间的调用（边的 scan 记录），和 scan 定不下被调方的调用处。

graph 是 codestrata 的中心数据结构（见 ARCHITECTURE 开头）：节点是函数，边是「函数 → 函数」的调用，
一条边上记 scan 看到的和 trace 看到的两样。这里只管 scan 那一半，扫描时和 xref 走同一遍
（xref.build 的 on_file），名字解析就是 xref 那一套。

节点用符号键 <文件路径>#<限定名>，另有几种符号表里没有的：
  <文件路径>#<module>      模块顶层的代码（import 时的注册、logger = …）
  <外层>.<L行>             lambda、生成器表达式（运行时是单独的帧）
类体里的代码记在类自己身上。

产出 graph.json：
  format   和 index.json 一样的格式版本（cut.INDEX_FORMAT）
  callees  [被调方的符号键, ...]
  calls    {调用方: [[被调方下标, 行, 末行, 种类], ...]}   定下了被调方的调用
  sites    {调用方: [[名字, 行, 末行, 种类], ...]}         定不下被调方的调用处：名字是写的那个
           （x.m(…) 的 m；语法触发的是特殊方法名）；没有名字（f()()、fs[i]()）是 null
行、末行是调用那个表达式占的行（跨行的调用末行更大）。种类：
  0 调用  1 构造（被调方是类）  2 装饰器（@x 定义时调 x）  3 取 property（调 getter）
  4 语法触发的特殊方法（with、for、[]、运算符、len() 这类，只记仓库里有类定义过的特殊方法）
  5 getattr(…, "名字")  6 调的是仓库外的（名字是写的那个）
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from . import cut as _cut
from . import xref as _xref

CALL, NEW, DECO, PROP, SYN, STR, EXT = range(7)
_HOW = {_xref.HOW_CALL: CALL, _xref.HOW_DECO: DECO, _xref.HOW_PROP: PROP, _xref.HOW_STR: STR}


class Builder:
    """xref.build(…, on_file=b.add_file) 走完之后，b.result() 就是 graph.json 的内容"""

    def __init__(self, index: dict):
        self.symbols = index.get("symbols") or {}
        # 语法触发的特殊方法只记仓库里有类定义过的：trace 只录仓库里的函数，别的永远对不上
        self.dunders = {s["s"] for s in self.symbols.values()
                        if s.get("k") == "func" and "." in s["n"] and s["s"].startswith("__") and s["s"].endswith("__")}
        self.callees: list[str] = []
        self._cid: dict[str, int] = {}
        self.calls: dict[str, list] = {}
        self.sites: dict[str, list] = {}

    def add_file(self, rel: str, tree, calls: list, spans: list) -> None:
        syms = self.symbols
        for caller, l, e, target, name, how in calls:
            kind = _HOW[how]
            if target and target.startswith("s:") and target[2:] in syms:
                key = target[2:]
                if kind == CALL and syms[key].get("k") == "class":
                    kind = NEW
                i = self._cid.get(key)
                if i is None:
                    i = self._cid[key] = len(self.callees)
                    self.callees.append(key)
                self.calls.setdefault(caller, []).append([i, l, e, kind])
            else:
                if kind == CALL and target and target.startswith("x:"):
                    kind = EXT
                self.sites.setdefault(caller, []).append([name, l, e, kind])
        syn = {l: names & self.dunders for l, names in syntax_facts(tree)[2].items()}
        syn = {l: v for l, v in syn.items() if v}
        if syn:
            node = _line_nodes(spans, max(syn), f"{rel}#<module>")
            for l in sorted(syn):
                for name in sorted(syn[l]):
                    self.sites.setdefault(node[l], []).append([name, l, l, SYN])

    def result(self) -> dict:
        for v in self.calls.values():
            v.sort()
        for v in self.sites.values():
            v.sort(key=lambda x: (x[1], x[2], x[3], x[0] or ""))
        return {"format": _cut.INDEX_FORMAT, "callees": self.callees, "calls": self.calls, "sites": self.sites}


def _line_nodes(spans: list, last: int, top: str) -> list[str]:
    """第 1..last 行各属于哪个节点：最里层的那个范围，都不在就是模块顶层 top"""
    node = [top] * (last + 1)
    for a, b, k in sorted(spans, key=lambda x: (x[0], -x[1])):     # 外层先填，里层后填盖掉
        for i in range(a, min(b, last) + 1):
            node[i] = k
    return node


def write(outdir: Path, graph: dict) -> Path:
    p = outdir / "graph.json"
    p.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


# ---- 语法触发的特殊方法 ----
_TRUTH = ("__bool__", "__len__")
_BIN = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.MatMult: "matmul", ast.Div: "truediv",
        ast.FloorDiv: "floordiv", ast.Mod: "mod", ast.Pow: "pow", ast.LShift: "lshift", ast.RShift: "rshift",
        ast.BitAnd: "and", ast.BitOr: "or", ast.BitXor: "xor"}
_CMP = {ast.Eq: ("__eq__",), ast.NotEq: ("__ne__", "__eq__"), ast.Lt: ("__lt__", "__gt__"),
        ast.LtE: ("__le__", "__ge__"), ast.Gt: ("__gt__", "__lt__"), ast.GtE: ("__ge__", "__le__"),
        ast.In: ("__contains__", "__iter__", "__eq__", "__hash__"),
        ast.NotIn: ("__contains__", "__iter__", "__eq__", "__hash__")}
_UNARY = {ast.USub: ("__neg__",), ast.UAdd: ("__pos__",), ast.Invert: ("__invert__",)}
_ITERATES = ("__iter__", "__next__")
# 内置函数调的特殊方法：len(x) 调 x.__len__
_BUILTIN = {"len": ("__len__",), "iter": _ITERATES, "next": ("__next__",), "str": ("__str__",), "print": ("__str__",),
            "repr": ("__repr__",), "hash": ("__hash__",), "bool": _TRUTH, "abs": ("__abs__",),
            "format": ("__format__",), "reversed": ("__reversed__", "__len__", "__getitem__"),
            "int": ("__int__", "__index__"), "float": ("__float__",), "round": ("__round__",),
            **{k: _ITERATES for k in ("list", "tuple", "set", "frozenset", "dict", "sorted", "sum", "min", "max",
                                      "any", "all", "enumerate", "zip", "map", "filter")}}
_NOT_CODE = ("annotation", "returns", "type_comment", "type_params")   # 标注里的 list[int]、a | b 不是运算


def _code_nodes(node: ast.AST):
    """ast.walk，但不进类型标注（参数、返回值、AnnAssign 的标注）：那里的 [] 和 | 不会在运行时触发特殊方法"""
    todo = [node]
    while todo:
        n = todo.pop()
        yield n
        for field, v in ast.iter_fields(n):
            if field in _NOT_CODE:
                continue
            if isinstance(v, ast.AST):
                todo.append(v)
            elif isinstance(v, list):
                todo.extend(x for x in v if isinstance(x, ast.AST))


def _end(n: ast.AST) -> int:
    return getattr(n, "end_lineno", None) or n.lineno


def syntax_facts(tree) -> tuple[frozenset, frozenset, dict]:
    """一个文件的三样事实（按语法树，不按文本）：
      - docstring 占的行：文档里写的「for all … in」「a + b」不是代码
      - 函数 / 类签名占的行（def 行到函数体第一句之前，多行签名的续行）：参数默认值、标注不是调用处
      - {行号: 这一行上由语法触发的特殊方法}：下标、运算符、比较和 in、with、for 和推导式、await、
        f-string、真值判断（if / while / and / or / not）、字典和集合的键、解包赋值、len() 这类内置函数。
        类型标注里的不算（_code_nodes）
    行号从 1 起；tree 是 None（解析不了的文件）时三样都是空的"""
    if tree is None:
        return frozenset(), frozenset(), {}
    prose, sig, syn = set(), set(), {}

    def mark(line: int, names) -> None:
        syn.setdefault(line, set()).update(names)

    def truth(e: ast.AST) -> None:
        """e 被当真假用（if e、while e、e and …、not e）：调的是 e 的 __bool__ / __len__——除非 e 本身是比较、
        and / or、常量（那判断的是它们算出来的 bool，不是某个对象）。not x 看的是 x"""
        if type(e) is ast.UnaryOp and type(e.op) is ast.Not:
            truth(e.operand)
        elif type(e) not in (ast.Compare, ast.BoolOp, ast.Constant):
            mark(e.lineno, _TRUTH)

    for n in _code_nodes(tree):
        t = type(n)
        if t is ast.Expr and type(n.value) is ast.Constant and type(n.value.value) is str:
            prose.update(range(n.lineno, _end(n) + 1))
        elif t in (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef) and n.body:
            first = n.body[0]                    # 函数体第一句；被装饰的定义从第一个装饰器算起
            sig.update(range(n.lineno, min([first.lineno] + [x.lineno for x in getattr(first, "decorator_list", ())])))
        elif t is ast.Subscript:
            mark(_end(n.value), {ast.Load: ("__getitem__", "__class_getitem__"), ast.Store: ("__setitem__",),
                                 ast.Del: ("__delitem__",)}[type(n.ctx)])
        elif t is ast.BinOp and type(n.op) in _BIN:
            op = _BIN[type(n.op)]
            mark(_end(n.left), (f"__{op}__", f"__r{op}__"))
        elif t is ast.AugAssign and type(n.op) in _BIN:
            op = _BIN[type(n.op)]
            mark(n.lineno, (f"__i{op}__", f"__{op}__", f"__r{op}__"))
        elif t is ast.UnaryOp and type(n.op) in _UNARY:
            mark(n.lineno, _UNARY[type(n.op)])
        elif t is ast.UnaryOp and type(n.op) is ast.Not:
            truth(n.operand)
        elif t is ast.Compare:
            for o in n.ops:
                names = _CMP.get(type(o), ())
                # x in 容器：容器的 __contains__（没有就 __iter__），字典 / 集合还要 x 的 __hash__、__eq__——
                # x 是常量（3 in b）时那是 int 的，不会是仓库里的方法
                if type(o) in (ast.In, ast.NotIn) and type(n.left) is ast.Constant:
                    names = ("__contains__", "__iter__")
                mark(_end(n.left), names)
        elif t in (ast.With, ast.AsyncWith):
            names = ("__enter__", "__exit__") if t is ast.With else ("__aenter__", "__aexit__")
            for item in n.items:
                mark(item.context_expr.lineno, names)
        elif t in (ast.For, ast.AsyncFor):
            mark(n.iter.lineno, _ITERATES if t is ast.For else ("__aiter__", "__anext__"))
        elif t is ast.comprehension:
            mark(n.iter.lineno, ("__aiter__", "__anext__") if n.is_async else _ITERATES)
            for c in n.ifs:
                truth(c)
        elif t is ast.Await:
            mark(n.lineno, ("__await__",))
        elif t is ast.YieldFrom:
            mark(n.lineno, ("__iter__",))
        elif t is ast.FormattedValue:
            mark(n.value.lineno, ("__repr__",) if n.conversion in (114, 97) else ("__format__", "__str__"))
        elif t in (ast.If, ast.While, ast.IfExp, ast.Assert):
            truth(n.test)
        elif t is ast.BoolOp:
            for v in n.values:
                truth(v)
        elif t in (ast.Dict, ast.Set):
            for k in (n.keys if t is ast.Dict else n.elts):
                if k is not None:
                    mark(k.lineno, ("__hash__", "__eq__"))
        elif t is ast.Assign and any(type(x) in (ast.Tuple, ast.List, ast.Starred) for x in n.targets):
            mark(n.value.lineno, _ITERATES)
        elif t is ast.Call and type(n.func) is ast.Name and n.func.id in _BUILTIN:
            mark(n.lineno, _BUILTIN[n.func.id])
    return frozenset(prose), frozenset(sig), {k: frozenset(v) for k, v in syn.items()}
