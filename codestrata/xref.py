"""交叉引用：代码里的每个名字指向哪个定义。给全文窗口的 Ctrl+点击用——点一个名字跳到
它的定义；点一个定义，列出所有引用它的地方。

只用 ast，静态地、尽力而为地解析，能确定的才记——宁可不跳，也不跳错：

  - 模块顶层定义的函数 / 类 / 变量，以及 import 进来的名字（`from x import y as z`、
    `import a.b as c`、`from x import *`——x 在仓库里时按它字面量的 __all__，没有就按不以 _ 开头的
    顶层名字展开）。`from pkg import name` 先看 pkg 的 __init__ 自己把 name 绑成了什么
    （`from .x import x` 会把子模块 x 换成函数 x），没绑、或者绑的就是那个子模块，才算子模块；
    再导出顺着 __init__ 里的 import 追到真正定义它的地方——否则所有引用都会停在 __init__ 上；
  - 模块顶层同一个名字绑了几次：if / try 里的备选（`try: import a except: import b`）取第一次，
    通常那才是真正想用的；顶层无条件的 def / class 盖掉前面的 import / 赋值
    （`from m import Base` 之后 `class Base(Base)`，后面的 `Base()` 是这个新类），
    而盖之前就执行的模块级代码（包括这个 class 自己的基类、装饰器、类体）仍指向旧的；
  - 属性链：`mod.func`、`pkg.sub.Class.method`、`Class.method`；
  - 方法里的 `self.x` / `cls.x` / `super().x`：按 C3 MRO 在仓库里的基类里找方法、嵌套类、类属性、
    实例属性（每个类里第一次 `self.x = …` 的地方算定义）。MRO 上先碰到仓库外 / 解析不了的基类
    就停——那个基类自己可能就有 x；
  - 作用域：函数的局部名字（参数、赋值、for / with / except / match 的目标、里面的 import 和 def）
    遮住外面的同名名字；推导式、lambda 的变量只在它们里面遮；类体里的语句看得见类体里前面已经绑定
    的名字（`@x.setter` 的 x 是上面的 getter），方法体看不见（Python 的规则）。遮住了就不解析。

确定不了的（局部变量的属性、仓库外的类的方法、getattr 之类）一律不记。仓库外的名字
（torch、vllm……）只记下它的点分路径，前端据此说「定义不在仓库里」。

分两遍，每遍都是逐个文件 parse、用完就丢：第一遍收模块顶层绑定、类属性、实例属性、基类；第二遍
带作用域走一遍记 token。整仓的 AST 一起攥在手里太贵（vllm-omni 的 1600 个文件要吃掉近 1 GB）。

产出 xref.json：
  targets  [目标, ...]            目标是 "s:模块:限定名"（类 / 函数）、"v:模块:限定名"（变量、类属性、
                                  实例属性）、"m:模块"（模块）、"x:点分路径"（仓库外）
  where    [[文件, 行] | null, ...]  和 targets 对齐：定义在哪（同名的 getter / setter 取第一个）
  files    {文件: [[行, 起, 止, 目标下标, 种类], ...]}
           起止是 UTF-16 码元下标（JS 的字符串下标；U+FFFF 以上的字符占 2），不是字节，也不是码点。
           文件开头的 BOM 不算（Pygments 高亮时会去掉它）。import 的点分路径每段一个 token：
           `import a.b.c` 里的 b 指向 a.b——前端只能包住落在同一个高亮文本节点里的 token
  fp       {文件: [字节数, mtime_ns]}   构建时走过的每个 .py 的 stat：前端据此认出 scan 之后改过的文件
  attrs    {属性名: [[文件, 行, 起, 止, 种类], ...]}   解析不了的 `<表达式>.属性名`（种类只有 0 / 1），
           只收和仓库里某个类的成员（方法、嵌套类、类属性、实例属性）同名、而且接收者的类型确实拿不准的
           （字面量、模块、函数、MRO 全在仓库里的类都不算）：引用面板据此列出「同名调用，接收者类型没核实」
  names    {"模块:名字": 目标下标}   scan 的边明细（edge_uses）引用了、却不在符号表里的名字——模块级变量、
           __init__ 等处再导出的类 / 函数 / 变量——按 `from 模块 import 名字` 追到的类 / 函数 / 变量（s: / v:）。
           边详情的「to」据此和 Ctrl+点击落在同一个地方
种类：0 引用、1 调用、2 import、3 定义本身。
"""
from __future__ import annotations

import ast
import gc
import json
import os
from pathlib import Path

REF, CALL, IMPORT, DEF = 0, 1, 2, 3

_MISSING = object()
_GLOBAL = object()               # 函数里 `global x`：x 直接去模块顶层找，跳过外层函数
_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_MATCH = getattr(ast, "Match", None)
_TYPEALIAS = getattr(ast, "TypeAlias", None)          # 3.12 的 `type X = ...`
_TRY = tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t)
_FOR = (ast.For, ast.AsyncFor)
_WITH = (ast.With, ast.AsyncWith)
# 带语句体的语句：里面还可能有 def / class / 赋值（同 scan 的 STMT_CONTAINERS）
_CONTAINERS = (ast.If, ast.While) + _FOR + _WITH + _TRY + ((_MATCH,) if _MATCH else ())
_ASSIGNS = (ast.Assign, ast.AnnAssign, ast.AugAssign)
_COMPS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
# 类型一眼就知道（内置类型）的接收者：`"".join`、`[...].append` 不进 attrs
_LITERALS = frozenset((ast.Constant, ast.JoinedStr, ast.List, ast.Tuple, ast.Dict, ast.Set) + _COMPS)
# 仓库外、但不带什么普通属性的基类：MRO 上碰到它们接着往后找（dunder 除外）
_TRANSPARENT = frozenset({"x:typing.Generic", "x:typing.Protocol", "x:typing_extensions.Generic",
                          "x:typing_extensions.Protocol", "x:abc.ABC"})
# 这些表达式没有自己的作用域，把列出来的子节点挨个走一遍就行
_EXPR_FIELDS = {
    ast.BoolOp: ("values",), ast.Compare: ("left", "comparators"),
    ast.UnaryOp: ("operand",), ast.Subscript: ("value", "slice"), ast.Tuple: ("elts",),
    ast.List: ("elts",), ast.Set: ("elts",), ast.Dict: ("keys", "values"), ast.Starred: ("value",),
    ast.IfExp: ("test", "body", "orelse"), ast.JoinedStr: ("values",),
    ast.FormattedValue: ("value", "format_spec"), ast.Slice: ("lower", "upper", "step"),
    ast.Await: ("value",), ast.Yield: ("value",), ast.YieldFrom: ("value",),
    ast.NamedExpr: ("value",), ast.keyword: ("value",),
}


def module_name(unit: str) -> str:
    return unit[:-len(".__init__")] if unit.endswith(".__init__") else unit


def _bodies(st):
    """一个带语句体的语句里的各段语句列表。"""
    for f in ("body", "orelse", "finalbody"):
        b = getattr(st, f, None)
        if b:
            yield b
    for h in getattr(st, "handlers", None) or ():
        yield h.body
    for c in getattr(st, "cases", None) or ():
        yield c.body


def _flat(stmts):
    """语句，连同 if / try / with ... 里面的（类体里的 def / 赋值常常包在 if TYPE_CHECKING 之类里）。"""
    for st in stmts:
        yield st
        if isinstance(st, _CONTAINERS):
            for b in _bodies(st):
                yield from _flat(b)


def _names(tg, out: list) -> list:
    """赋值目标里被绑定的 Name 节点（`a, *b = ...` 拆开；`x.y = ` / `x[0] = ` 不绑名字）。"""
    t = type(tg)
    if t is ast.Name:
        out.append(tg)
    elif t is ast.Tuple or t is ast.List:
        for e in tg.elts:
            _names(e, out)
    elif t is ast.Starred:
        _names(tg.value, out)
    return out


def _captures(p, out: list) -> list:
    """match 的 case 模式里捕获的名字（`case Point(x=a)` 的 a、`case [*rest]`、`case {**kw}`）。"""
    t = type(p)
    if t is ast.MatchAs:
        if p.pattern is not None:
            _captures(p.pattern, out)
        if p.name:
            out.append(p.name)
    elif t is ast.MatchStar:
        if p.name:
            out.append(p.name)
    elif t is ast.MatchMapping:
        for x in p.patterns:
            _captures(x, out)
        if p.rest:
            out.append(p.rest)
    elif t is ast.MatchClass:
        for x in p.patterns + p.kwd_patterns:
            _captures(x, out)
    elif t is ast.MatchSequence or t is ast.MatchOr:
        for x in p.patterns:
            _captures(x, out)
    return out


def _strs(node):
    """字面量的字符串列表 / 元组 → [str]；别的 → None。"""
    if type(node) in (ast.List, ast.Tuple) and all(
            type(e) is ast.Constant and type(e.value) is str for e in node.elts):
        return [e.value for e in node.elts]
    return None


def _is_static(fn) -> bool:
    return any((type(d) is ast.Name and d.id == "staticmethod")
               or (type(d) is ast.Attribute and d.attr == "staticmethod") for d in fn.decorator_list)


def _first_param(fn, cls) -> str | None:
    """方法的第一个位置参数（self / cls）；不是方法、staticmethod、没有位置参数时为 None。"""
    if not cls or _is_static(fn):
        return None
    a = fn.args
    ps = a.posonlyargs or a.args
    return ps[0].arg if ps else None


def _all_args(a):
    out = a.posonlyargs + a.args + a.kwonlyargs
    if a.vararg:
        out = out + [a.vararg]
    if a.kwarg:
        out = out + [a.kwarg]
    return out


def _u16(s: str) -> int:
    """JS 里的长度：UTF-16 码元数。"""
    return len(s) if s.isascii() else len(s.encode("utf-16-le")) // 2


def _read(p: Path):
    """(源码, AST)；读不了 / 语法错时 AST 为 None。开头的 BOM 去掉（Pygments 也去掉，列号才对得上）。"""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        return text, ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return text, None


def _fn_locals(fn, key: str, cls: str | None, symbols: dict, walrus: bool, imp) -> dict:
    """函数的局部名字 → 目标（None 表示局部变量：遮住外面，但不知道指向什么）。

    参数、赋值 / for / with / except / match / del 的目标、里面定义的函数和类（→ 它们的符号）、
    里面的 import（→ imp(模块, 名字 | None, 层级) 给的绑定）。同一个名字绑了几次取第一次——
    `x = None` 之后又 `from m import x` 的，宁可不跳。global 的名字标成 _GLOBAL，nonlocal 的拿掉
    （往外层找）。只走语句；文件里有 `:=` 时才把表达式也走一遍找海象赋值。key 是这个函数的「模块:限定名」。"""
    out: dict = {}
    for x in _all_args(fn.args):
        out[x.arg] = None
    p0 = _first_param(fn, cls)
    if p0:
        out[p0] = f"self:{cls}"
    decl: dict = {}
    _local_walk(fn.body, out, decl, key, symbols, imp)
    if walrus:
        stack = list(fn.body)
        while stack:
            n = stack.pop()
            t = type(n)
            if t in _DEFS or t is ast.Lambda:
                continue                        # 里层作用域（它的海象绑在它自己里面）
            if t is ast.NamedExpr and type(n.target) is ast.Name:
                out.setdefault(n.target.id, None)
            stack.extend(ast.iter_child_nodes(n))
    for g, how in decl.items():
        if how is _GLOBAL:
            out[g] = _GLOBAL
        else:
            out.pop(g, None)
    return out


def _local_walk(stmts, out: dict, decl: dict, key: str, symbols: dict, imp) -> None:
    """_fn_locals 的语句遍历。写成模块级函数而不是闭包：递归的闭包自己引用自己，成了环，
    build 关着 GC 时会把整个文件的状态一直攥到最后。"""
    for s in stmts:
        t = type(s)
        if t in _DEFS:
            k = f"{key}.{s.name}"
            out.setdefault(s.name, f"s:{k}" if k in symbols else None)
        elif t is ast.Assign:
            for tg in s.targets:
                for n in _names(tg, []):
                    out.setdefault(n.id, None)
        elif t is ast.AnnAssign or t is ast.AugAssign or t is ast.Delete or t in _FOR:
            # `x: int` 不赋值也让 x 成了局部名字
            for tg in (s.targets if t is ast.Delete else [s.target]):
                for n in _names(tg, []):
                    out.setdefault(n.id, None)
            if t in _FOR:
                _local_walk(s.body, out, decl, key, symbols, imp)
                _local_walk(s.orelse, out, decl, key, symbols, imp)
        elif t in _WITH:
            for it in s.items:
                if it.optional_vars is not None:
                    for n in _names(it.optional_vars, []):
                        out.setdefault(n.id, None)
            _local_walk(s.body, out, decl, key, symbols, imp)
        elif t is ast.If or t is ast.While:
            _local_walk(s.body, out, decl, key, symbols, imp)
            _local_walk(s.orelse, out, decl, key, symbols, imp)
        elif t in _TRY:
            _local_walk(s.body, out, decl, key, symbols, imp)
            for h in s.handlers:
                if h.name:
                    out.setdefault(h.name, None)
                _local_walk(h.body, out, decl, key, symbols, imp)
            _local_walk(s.orelse, out, decl, key, symbols, imp)
            _local_walk(s.finalbody, out, decl, key, symbols, imp)
        elif t is _MATCH:
            for c in s.cases:
                for n in _captures(c.pattern, []):
                    out.setdefault(n, None)
                _local_walk(c.body, out, decl, key, symbols, imp)
        elif t is ast.Import:
            for al in s.names:
                if al.asname:
                    out.setdefault(al.asname, imp(al.name, None, 0))
                else:
                    root = al.name.split(".")[0]
                    out.setdefault(root, imp(root, None, 0))
        elif t is ast.ImportFrom:
            for al in s.names:
                if al.name != "*":
                    out.setdefault(al.asname or al.name, imp(s.module, al.name, s.level))
        elif t is ast.Global:
            for g in s.names:
                decl[g] = _GLOBAL
        elif t is ast.Nonlocal:
            for g in s.names:
                decl[g] = None
        elif t is _TYPEALIAS:
            out.setdefault(s.name.id, None)


class _Repo:
    """全仓的名字表：哪些模块、每个模块顶层绑定了什么、类的成员和基类。"""

    def __init__(self, index: dict):
        self.symbols = index.get("symbols") or {}
        self.file_of: dict[str, str] = {}            # 模块 → 文件
        self.init: set[str] = set()                  # 是包（__init__.py）的模块
        units = index.get("packages") or {}
        for rel, unit in (index.get("files") or {}).items():
            if not rel.endswith(".py"):
                continue
            lab = (units.get(unit) or {}).get("label") or unit   # 单元 id 是路径，点分的模块名在 label 里
            m = module_name(lab)
            self.file_of[m] = rel
            if lab.endswith(".__init__"):
                self.init.add(m)
        # 没有 __init__.py 的目录（命名空间包）：能穿过去找子模块，但它自己没有文件可跳
        self.ns: set[str] = set()
        for m in self.file_of:
            parts = m.split(".")
            for i in range(1, len(parts)):
                p = ".".join(parts[:i])
                if p not in self.file_of:
                    self.ns.add(p)
        # ---- 第一遍收的 ----
        self.tops: dict[str, dict] = {}              # 模块 → {名字: 绑定}（最终的）
        self.hist: dict[str, dict] = {}              # 模块 → {名字: [(被 def/class 盖掉的行, 之前的绑定), ...]}
        self.stars: dict[str, list] = {}             # 模块 → [from X import * 的 X, ...]
        self.alls: dict[str, frozenset] = {}         # 模块 → 字面量的 __all__
        self.vars: dict[str, list] = {}              # "v:模块:限定名" → [文件, 行]
        self.first: dict[str, int] = {}              # "模块:限定名" → 第一次 def / class 的行（和符号表不同时才记）
        self.cbases: dict[str, list] = {}            # 类 → 基类的解析线索（见 _Collect.base_spec）
        self.member_names: set[str] = set()          # 仓库里各个类的成员名（attrs 只收这些）
        # 绑定是目标字符串，或 ("from", 模块, 名字)：还没追的 from-import。
        # 目标之外还有几种只在内部用、不会写进 xref 的：n:命名空间包、self:类（方法的第一个参数）、
        # super:类（super() 的结果）
        # ---- 第二遍记的 ----
        self.targets: list[str] = []
        self.tid: dict[str, int] = {}
        # 行号、目标下标这些要留到最后的 int，一律用这里事先建好的同一个对象：留住 AST 里的 int
        # 会把它所在的整块内存（连同周围早该释放的 AST 节点的空位）一直钉住
        self.ints = list(range(1 << 16))
        self.attrs: dict[str, list] = {}
        # ---- 缓存 ----
        self._memo: dict = {}
        self._busy: set = set()
        self._cut = False

    # ---- 目标编号 ----
    def t(self, target: str) -> int:
        i = self.tid.get(target)
        if i is None:
            i = self.tid[target] = self.int(len(self.targets))
            self.targets.append(target)
        return i

    def int(self, n: int) -> int:
        return self.ints[n] if n < len(self.ints) else n

    def where(self, target: str):
        kind, _, rest = target.partition(":")
        if kind == "s":
            s = self.symbols.get(rest)
            return [s["f"], self.first.get(rest) or s["l"]] if s else None
        if kind == "v":
            return self.vars.get(target)
        if kind == "m":
            f = self.file_of.get(rest)
            return [f, 1] if f else None
        return None

    # ---- 模块名 ----
    def abs_module(self, m: str, level: int, module: str | None) -> str:
        """相对 import 的绝对模块名。__init__.py 的模块名就是包本身，「一个点」指它自己（同 scan）。"""
        if not level:
            return module or ""
        up = m.split(".")
        up = up[:max(0, len(up) - level + (1 if m in self.init else 0))]
        base = ".".join(up)
        return (f"{base}.{module}" if base else module) if module else base

    def module_target(self, full: str) -> str | None:
        if full in self.file_of:
            return f"m:{full}"
        return f"n:{full}" if full in self.ns else None

    def import_target(self, full: str) -> str:
        """一个点分路径（import 语句里写的）落在哪：仓库里的模块 / 命名空间包，还是仓库外。"""
        return self.module_target(full) or f"x:{full}"

    def from_binding(self, m: str, module: str | None, name: str | None, level: int):
        """import 语句给的绑定（还没追）。name 为 None 是 `import module`。"""
        if name is None:
            return self.import_target(module)
        return ("from", self.abs_module(m, level, module), name)

    # ---- 解析（带缓存；成环的那一圈不缓存，免得把「环上暂时找不到」记成定论） ----
    def _memo_call(self, key, fn, *args):
        r = self._memo.get(key, _MISSING)
        if r is not _MISSING:
            return r
        if key in self._busy:
            self._cut = True
            return None
        self._busy.add(key)
        outer, self._cut = self._cut, False
        try:
            r = fn(*args)
        finally:
            self._busy.discard(key)
        if not self._cut:
            self._memo[key] = r
        self._cut = self._cut or outer
        return r

    def binding(self, b):
        return self.from_import(b[1], b[2]) if type(b) is tuple else b

    def lookup_top(self, m: str, name: str):
        """模块 m 跑完之后，顶层的 name 指向哪。"""
        return self._memo_call(("t", m, name), self._lookup_top, m, name)

    def _lookup_top(self, m, name):
        tops = self.tops.get(m)
        if tops is None:
            return None
        b = tops.get(name, _MISSING)
        if b is not _MISSING:
            return self.binding(b)
        for base in self.stars.get(m, ()):
            if self.exports(base, name):
                return self.from_import(base, name)
        return None

    def at_line(self, m: str, name: str, line: int | None):
        """模块 m 的顶层代码执行到第 line 行（那条顶层语句）时，name 指向哪。line 为 None：跑完之后。"""
        if line is not None:
            for ln, b in self.hist.get(m, {}).get(name, ()):
                if line <= ln:
                    return self.binding(b)
        return self.lookup_top(m, name)

    def exports(self, base: str, name: str) -> bool:
        """`from base import *` 会不会带出 name。仓库外的模块不知道，当它不带。"""
        return bool(self._memo_call(("e", base, name), self._exports, base, name))

    def _exports(self, base, name):
        if base not in self.file_of:
            return False
        al = self.alls.get(base)
        if al is not None:
            return name in al
        if name.startswith("_"):
            return False
        return name in self.tops.get(base, ()) or any(self.exports(s, name) for s in self.stars.get(base, ()))

    def from_import(self, base: str, name: str):
        """`from base import name`：base 自己绑定的 name（包括再导出、星号导入），没绑才是子模块 base.name。"""
        return self._memo_call(("f", base, name), self._from_import, base, name)

    def _from_import(self, base, name):
        full = f"{base}.{name}"
        if base not in self.file_of:
            if base in self.ns:                       # 命名空间包里只有子模块
                return self.module_target(full)
            return f"x:{full}"
        b = self.tops.get(base, {}).get(name, _MISSING)
        if b is not _MISSING:
            if b == ("from", base, name):             # 包里 `from . import name`：就是那个子模块
                return self.module_target(full)
            return self.binding(b)                    # 包自己的绑定优先（`from .x import x` 换成了函数 x）
        for s in self.stars.get(base, ()):
            if self.exports(s, name):
                return self.from_import(s, name)
        sub = self.module_target(full)
        if sub:
            return sub
        if f"{base}:{name}" in self.symbols:
            return f"s:{base}:{name}"
        return None

    def member(self, target, attr: str):
        """target.attr 指向哪。"""
        if target is None:
            return None
        return self._memo_call(("a", target, attr), self._member, target, attr)

    def _member(self, target, attr):
        kind, _, rest = target.partition(":")
        if kind == "m":
            return self.from_import(rest, attr)
        if kind == "x":
            return f"{target}.{attr}"
        if kind == "s" or kind == "self":
            return self.class_member(rest, attr, False)
        if kind == "super":
            return self.class_member(rest, attr, True)
        if kind == "n":
            return self.module_target(f"{rest}.{attr}")
        return None

    # ---- 类：C3 MRO ----
    def bases(self, key: str) -> list:
        """直接基类：仓库里的类 → 它的键；typing.Generic 之类 → "~目标"；别的（仓库外、变量、调用、
        解析不了）→ "?..."（同一个仓库外的类用同一个记号，C3 合并时才认得出是同一个）。"""
        specs = self.cbases.get(key)
        if specs is None:                             # 第一遍没见过（scan 之后文件改过）：不知道
            return [f"?{key}"]
        m = key.partition(":")[0]
        out = []
        for i, sp in enumerate(specs):
            t = None
            if sp is not None:
                where, first, rest, line = sp
                t = self.binding(first) if where == "L" else self.at_line(m, first, line)
                for p in rest:
                    t = self.member(t, p)
                if t is None and where == "G" and first == "object" and not rest:
                    t = "x:object"                    # 内置的 object（没被别的名字盖掉）
            if t and t.startswith("s:") and (self.symbols.get(t[2:]) or {}).get("k") == "class":
                out.append(t[2:])
            elif t in _TRANSPARENT or t == "x:object":
                out.append(f"~{t}")
            elif t and t.startswith("x:"):
                out.append(f"?{t}")
            else:
                out.append(f"?{key}#{i}")
        return out

    def mro(self, key: str):
        return self._memo_call(("mro", key), self._mro, key)

    def _mro(self, key):
        direct = self.bases(key)
        seqs = []
        for i, b in enumerate(direct):
            if b[0] in "?~":
                seqs.append([b])
                continue
            sub = self.mro(b)
            if sub is None:                           # 基类自己线性化不了 / 成环：当成不知道的基类
                direct[i] = b = f"?{b}"
                seqs.append([b])
            else:
                seqs.append(list(sub))
        seqs.append(list(direct))
        out = [key]
        seqs = [s for s in seqs if s]
        while seqs:
            for s in seqs:
                head = s[0]
                if not any(head in t[1:] for t in seqs):
                    break
            else:
                return None                           # C3 不一致：Python 自己也建不出这个类，不猜
            out.append(head)
            for s in seqs:
                if s[0] == head:
                    del s[0]
            seqs = [s for s in seqs if s]
        return out

    def class_member(self, key: str, attr: str, skip_self: bool):
        """沿 MRO 找成员：方法 / 嵌套类（符号表）、类属性 / 实例属性（vars）。先碰到仓库外 / 不知道的
        基类就放弃——它自己可能就定义了 attr。skip_self：super() 从下一个类开始。"""
        s = self.symbols.get(key)
        if not s or s["k"] != "class":
            return None
        mro = self.mro(key)
        if not mro:
            return None
        dunder = attr.startswith("__") and attr.endswith("__")
        for c in (mro[1:] if skip_self else mro):
            k = c[0]
            if k == "?":
                return None
            if k == "~":
                if dunder:
                    return None
                continue
            if f"{c}.{attr}" in self.symbols:
                return f"s:{c}.{attr}"
            v = f"v:{c}.{attr}"
            if v in self.vars:
                return v
        return None

    def unsure(self, target, attr: str) -> bool:
        """target.attr 没解析出来，是不是因为接收者的类型拿不准：不知道是什么（局部变量、调用的结果、
        模块级变量），或者是个类、但 MRO 上有仓库外 / 解析不了的基类。模块、仓库外的东西、函数、
        MRO 全在仓库里却哪儿都没定义 attr 的类，都不算。"""
        if target is None:
            return True
        kind, _, rest = target.partition(":")
        if kind == "v":
            return True
        if kind not in ("s", "self", "super"):
            return False
        s = self.symbols.get(rest)
        if not s or s["k"] != "class":
            return kind != "s"
        mro = self.mro(rest)
        if not mro:
            return True
        dunder = attr.startswith("__") and attr.endswith("__")
        return any(c[0] == "?" or (c[0] == "~" and dunder) for c in (mro[1:] if kind == "super" else mro))

    def finish_first_pass(self) -> None:
        """仓库里各个类的成员名：方法 / 嵌套类（父级是类的符号）、类属性和实例属性（带点的 v:）。"""
        names = self.member_names
        syms = self.symbols
        for key in syms:
            mod, _, q = key.partition(":")
            parent, dot, last = q.rpartition(".")
            if dot and (syms.get(f"{mod}:{parent}") or {}).get("k") == "class":
                names.add(last)
        for v in self.vars:
            parent, dot, last = v.split(":", 2)[2].rpartition(".")
            if dot:
                names.add(last)


class _Collect:
    """第一遍，一个文件：模块顶层的绑定、类属性、实例属性（每个类第一次 self.x = …）、基类的线索、
    每个 def / class 第一次出现的行。只走语句，不走表达式。"""

    def __init__(self, repo: _Repo, m: str, rel: str, walrus: bool):
        self.repo, self.m, self.rel, self.walrus = repo, m, rel, walrus
        self.tops: dict = {}
        self.hist: dict = {}
        self.stars: list = []
        self.all = None                               # 字面量的 __all__；没有或不是字面量时 None
        self._locals: dict = {}                       # 外层函数的局部名字（嵌套类的基类用；按需算）

    def run(self, tree) -> None:
        repo, m = self.repo, self.m
        if tree is not None:
            self.top_block(tree.body, False)
        repo.tops[m] = self.tops
        if self.hist:
            repo.hist[m] = self.hist
        if self.stars:
            repo.stars[m] = self.stars
        if self.all is not None:
            repo.alls[m] = frozenset(self.all)

    # ---- 模块顶层 ----
    def bind(self, name: str, b, override: bool = False, line: int = 0) -> None:
        """同一个名字绑定几次：默认第一次算（if / try 里的备选）；顶层无条件的 def / class 盖掉前面的。"""
        cur = self.tops.get(name, _MISSING)
        if cur is _MISSING:
            self.tops[name] = b
        elif override and cur != b:
            self.hist.setdefault(name, []).append((line, cur))
            self.tops[name] = b

    def top_block(self, stmts, cond: bool) -> None:
        repo, m = self.repo, self.m
        for st in stmts:
            t = type(st)
            if t in _DEFS:
                self.bind(st.name, f"s:{m}:{st.name}", override=not cond, line=st.lineno)
                self.define(st, "", [], None)
            elif t is ast.Import:
                for a in st.names:
                    local = a.asname or a.name.split(".")[0]
                    self.bind(local, repo.import_target(a.name if a.asname else local))
            elif t is ast.ImportFrom:
                for a in st.names:
                    if a.name == "*":
                        self.stars.append(repo.abs_module(m, st.level, st.module))
                    else:
                        self.bind(a.asname or a.name, repo.from_binding(m, st.module, a.name, st.level))
            elif t in _ASSIGNS:
                for tg in (st.targets if t is ast.Assign else [st.target]):
                    for n in _names(tg, []):
                        key = f"v:{m}:{n.id}"
                        repo.vars.setdefault(key, [self.rel, repo.int(n.lineno)])
                        self.bind(n.id, key)
                self.dunder_all(st)
            elif t is _TYPEALIAS:
                key = f"v:{m}:{st.name.id}"
                repo.vars.setdefault(key, [self.rel, repo.int(st.name.lineno)])
                self.bind(st.name.id, key)
            elif t is ast.Expr:
                self.dunder_all(st)
            elif t in _CONTAINERS:
                for b in _bodies(st):
                    self.top_block(b, True)

    def dunder_all(self, st) -> None:
        """__all__ = [...] / += [...] / .extend([...]) / .append("x")：都是字面量才算数。"""
        t = type(st)
        if t is ast.Expr:
            c = st.value
            if not (type(c) is ast.Call and type(c.func) is ast.Attribute
                    and type(c.func.value) is ast.Name and c.func.value.id == "__all__"):
                return
            vals = None
            if len(c.args) == 1 and not c.keywords:
                if c.func.attr == "extend":
                    vals = _strs(c.args[0])
                elif c.func.attr == "append" and type(c.args[0]) is ast.Constant and type(c.args[0].value) is str:
                    vals = [c.args[0].value]
            self.all = self.all + vals if self.all is not None and vals is not None else None
            return
        tgs = st.targets if t is ast.Assign else [st.target]
        if not any(type(x) is ast.Name and x.id == "__all__" for x in tgs):
            return
        vals = _strs(st.value) if st.value is not None else None
        if t is ast.AugAssign:
            self.all = self.all + vals if self.all is not None and vals is not None else None
        else:
            self.all = vals

    # ---- def / class（任意嵌套；限定名同 scan） ----
    def define(self, st, prefix: str, env: list, cls: str | None) -> None:
        """env：外层作用域，由外到里。("f", 函数节点, 它的键, 所在类)；("c", 类体里到目前为止的绑定)
        ——类体只对直接写在里面的东西可见，所以 env 里最多最后一个是 "c"。"""
        q = prefix + st.name
        key = f"{self.m}:{q}"
        self.first(key, st.lineno)
        if type(st) is ast.ClassDef:
            self.klass(st, q, key, env)
        else:
            fenv = [e for e in env if e[0] != "c"] + [("f", st, key, cls)]
            self.func_body(st.body, q + ".", fenv, _first_param(st, cls), cls)

    def first(self, key: str, line: int) -> None:
        """同名的 def 出现几次（property 的 getter / setter、overload）：scan 的符号表留的是最后一个，
        这里记下第一个。第一次见到时行号就和符号表一致的，说明只有一个，不用记。"""
        first = self.repo.first
        if key not in first and (self.repo.symbols.get(key) or {}).get("l", line) != line:
            first[key] = self.repo.int(line)

    def klass(self, st, q: str, key: str, env: list) -> None:
        repo = self.repo
        repo.cbases[key] = [self.base_spec(b, env, st.lineno) for b in st.bases]
        body = list(_flat(st.body))
        # 类属性先收齐：实例属性用 setdefault，类里声明过的（dataclass 字段之类）优先
        for s in body:
            t = type(s)
            if t in _ASSIGNS:
                for tg in (s.targets if t is ast.Assign else [s.target]):
                    for n in _names(tg, []):
                        repo.vars.setdefault(f"v:{key}.{n.id}", [self.rel, repo.int(n.lineno)])
        cenv: dict = {}
        benv = [e for e in env if e[0] != "c"] + [("c", cenv)]
        symbols = repo.symbols
        for s in body:
            t = type(s)
            if t in _DEFS:
                self.define(s, q + ".", benv, key)
                k = f"{key}.{s.name}"
                cenv[s.name] = f"s:{k}" if k in symbols else None
            elif t in _ASSIGNS:
                for tg in (s.targets if t is ast.Assign else [s.target]):
                    for n in _names(tg, []):
                        cenv[n.id] = f"v:{key}.{n.id}"
            elif t is ast.Import:
                for a in s.names:
                    local = a.asname or a.name.split(".")[0]
                    cenv[local] = repo.import_target(a.name if a.asname else local)
            elif t is ast.ImportFrom:
                for a in s.names:
                    if a.name != "*":
                        cenv[a.asname or a.name] = repo.from_binding(self.m, s.module, a.name, s.level)

    def func_body(self, stmts, prefix: str, env: list, selfname: str | None, cls: str | None) -> None:
        """函数体：找里面的 def / class，以及 `self.x = …`（selfname 是方法的第一个参数）。"""
        for s in stmts:
            t = type(s)
            if t in _FUNC:
                self.first(f"{self.m}:{prefix}{s.name}", s.lineno)
                # 闭包里的 self.x = … 也算，除非里层函数自己也有个同名参数
                sn = selfname if selfname and selfname not in {x.arg for x in _all_args(s.args)} else None
                self.func_body(s.body, f"{prefix}{s.name}.", env + [("f", s, f"{self.m}:{prefix}{s.name}", None)],
                               sn, cls)
            elif t is ast.ClassDef:
                self.define(s, prefix, env, None)
            else:
                if selfname and (t is ast.Assign or t is ast.AnnAssign):
                    for tg in (s.targets if t is ast.Assign else [s.target]):
                        self.inst(tg, selfname, cls)
                if t in _CONTAINERS:
                    for b in _bodies(s):
                        self.func_body(b, prefix, env, selfname, cls)

    def inst(self, tg, selfname: str, cls: str) -> None:
        t = type(tg)
        if t is ast.Attribute:
            if type(tg.value) is ast.Name and tg.value.id == selfname:
                self.repo.vars.setdefault(f"v:{cls}.{tg.attr}", [self.rel, self.repo.int(tg.end_lineno or tg.lineno)])
        elif t is ast.Tuple or t is ast.List:
            for e in tg.elts:
                self.inst(e, selfname, cls)
        elif t is ast.Starred:
            self.inst(tg.value, selfname, cls)

    def base_spec(self, b, env: list, line: int):
        """一个基类表达式的解析线索：("L", 外层局部 / 类体里的绑定, 其余段, None) 或
        ("G", 模块顶层的名字, 其余段, 行)。行是这条 class 语句：盖掉同名 import 的 def / class
        在它之后的话，基类仍是旧的；在函数里的类等函数跑起来才建，取最终的绑定（行 None）。
        不是点分名字（调用之类）→ None。"""
        while type(b) is ast.Subscript:               # Generic[T] → Generic
            b = b.value
        parts = []
        while type(b) is ast.Attribute:
            parts.append(b.attr)
            b = b.value
        if type(b) is not ast.Name:
            return None
        parts.reverse()
        name = b.id
        infunc = False
        for e in reversed(env):
            if e[0] == "c":
                if name in e[1]:
                    return ("L", e[1][name], parts, None)
                continue
            infunc = True
            loc = self._locals.get(id(e[1]))
            if loc is None:
                loc = self._locals[id(e[1])] = _fn_locals(
                    e[1], e[2], e[3], self.repo.symbols, self.walrus,
                    lambda mod, nm, lv: self.repo.from_binding(self.m, mod, nm, lv))
            if name in loc:
                if loc[name] is _GLOBAL:
                    break
                return ("L", loc[name], parts, None)
        return ("G", name, parts, None if infunc else line)


class _ClsScope(dict):
    """类体的作用域：只对直接写在类体里的语句可见。"""


class _Walk:
    """第二遍，一个文件：带作用域走一遍 AST，把能确定指向的名字记成 token。"""

    def __init__(self, repo: _Repo, m: str, rel: str, text: str):
        self.repo, self.m, self.rel = repo, m, rel
        self.lines = text.split("\n")
        self.walrus = ":=" in text
        self.toks: list[tuple] = []
        self.scopes: list[dict] = []                  # 由外到里：函数局部、临时遮住的名字、类体（_ClsScope）
        self.cscope: dict | None = None               # 直接在类体里时：这个类体的作用域
        self.fn = False                               # 在函数体里
        self.late = False                             # 模块顶层跑完之后才执行（函数体、lambda、注解）
        self.top_line = 0                             # 当前这条模块顶层语句的行
        self.meth: str | None = None                  # 在方法里：它的类（super() 用）
        self.seen: set[str] = set()                   # 已经记过定义 token 的变量
        self.gcache: dict = {}
        self.hist = repo.hist.get(m) or {}
        self.tops = repo.tops.get(m) or {}
        self.symbols = repo.symbols

    def run(self, tree) -> list[tuple]:
        for st in tree.body:
            self.top_line = st.lineno
            self.block((st,), "", None)
        return self.toks

    # ---- 位置 ----
    def span(self, line: int, bcol: int, name: str, from_end: bool = False):
        """ast 给的是 UTF-8 字节列；换成 UTF-16 的 [起, 止)。那儿的文字不是 name 就不记（免得下划线画歪）。"""
        if not 0 < line <= len(self.lines):
            return None
        text = self.lines[line - 1]
        if text.isascii():
            s = bcol - len(name) if from_end else bcol
            if s < 0 or text[s:s + len(name)] != name:
                return None
            return s, s + len(name)
        c = len(text.encode("utf-8")[:bcol].decode("utf-8", errors="replace"))
        s = c - len(name) if from_end else c
        if s < 0 or text[s:s + len(name)] != name:
            return None
        s16 = _u16(text[:s])
        return s16, s16 + _u16(name)

    def emit(self, line: int, bcol: int, name: str, target: str, kind: int, from_end: bool = False) -> None:
        sp = self.span(line, bcol, name, from_end)
        if sp:
            self.toks.append((self.repo.int(line), sp[0], sp[1], self.repo.t(target), kind))

    def find_kw(self, line: int, bcol: int, name: str, kw: str) -> int | None:
        """一行里 bcol 之后、关键字 kw 之后的 name 的字节列（def / class 名的位置 ast 不给）。"""
        if not 0 < line <= len(self.lines):
            return None
        text = self.lines[line - 1].encode("utf-8")
        i = text.find(kw.encode(), bcol)
        if i < 0:
            return None
        j = text.find(name.encode(), i + len(kw))
        return j if j >= 0 else None

    # ---- 名字 ----
    def lookup(self, name: str):
        for sc in reversed(self.scopes):
            if name in sc:
                v = sc[name]
                if v is _GLOBAL:
                    break
                return v                              # None：局部变量，遮住了外面的
        if not self.late and name in self.hist:
            return self.repo.at_line(self.m, name, self.top_line)
        r = self.gcache.get(name, _MISSING)
        if r is _MISSING:
            r = self.gcache[name] = self.repo.lookup_top(self.m, name)
        return r

    def outer_chain(self) -> list:
        """进函数 / lambda / 推导式 / 另一个类体：外面的类体看不见了。"""
        return [s for s in self.scopes if type(s) is not _ClsScope]

    # ---- 语句 ----
    def block(self, stmts, q: str, cls: str | None) -> None:
        state = self.scopes, self.cscope, self.fn, self.late, self.meth
        for st in stmts:
            try:
                self.stmt(st, q, cls)
            except RecursionError:
                # 生成的代码里嵌套上千层的表达式：这条语句剩下的不记了，接着走下一条。
                # 每条语句走完都会把作用域状态还原，所以这里还原成进这一段时的样子就对
                self.scopes, self.cscope, self.fn, self.late, self.meth = state

    def stmt(self, st, q: str, cls: str | None) -> None:
        """q：限定名前缀（"A." / "f."）；cls：直接在类体里时是这个类（"模块:限定名"）。"""
        t = type(st)
        ex = self.ex
        if t is ast.Expr:
            ex(st.value)
        elif t is ast.Assign:
            ex(st.value)
            self.assign(st.targets, cls, True)
        elif t is ast.Return:
            if st.value is not None:
                ex(st.value)
        elif t is ast.If or t is ast.While:
            ex(st.test)
            self.block(st.body, q, cls)
            self.block(st.orelse, q, cls)
        elif t in _FUNC:
            self.funcdef(st, q, cls)
        elif t is ast.ClassDef:
            self.classdef(st, q, cls)
        elif t is ast.AnnAssign:
            late, self.late = self.late, True         # 注解按推迟求值算（PEP 563 / 649）
            ex(st.annotation)
            self.late = late
            if st.value is not None:
                ex(st.value)
            self.assign([st.target], cls, st.value is not None)
        elif t is ast.AugAssign:
            ex(st.value)
            self.assign([st.target], cls, True)
        elif t in _FOR:
            ex(st.iter)
            self.loop_target(st.target, st.body, q, cls)
            self.block(st.orelse, q, cls)
        elif t in _WITH:
            names = []
            for it in st.items:
                ex(it.context_expr)
                if it.optional_vars is not None:
                    ex(it.optional_vars)
                    _names(it.optional_vars, names)
            self.shadowed([n.id for n in names] if not self.fn else [], st.body, q, cls)
        elif t is ast.Import or t is ast.ImportFrom:
            self.imports(st)
        elif t in _TRY:
            self.block(st.body, q, cls)
            for h in st.handlers:
                if h.type is not None:
                    ex(h.type)
                self.shadowed([h.name] if h.name else [], h.body, q, cls)
            self.block(st.orelse, q, cls)
            self.block(st.finalbody, q, cls)
        elif t is ast.Raise:
            if st.exc is not None:
                ex(st.exc)
            if st.cause is not None:
                ex(st.cause)
        elif t is ast.Assert:
            ex(st.test)
            if st.msg is not None:
                ex(st.msg)
        elif t is ast.Delete:
            for tg in st.targets:
                ex(tg)
        elif t is _MATCH:
            ex(st.subject)
            for c in st.cases:
                names = []
                self.pattern(c.pattern, names)
                pushed = bool(names)
                if pushed:
                    self.scopes = self.scopes + [dict.fromkeys(names)]
                    if self.cscope is not None:
                        for n in names:
                            self.cscope[n] = None
                if c.guard is not None:
                    ex(c.guard)
                self.block(c.body, q, cls)
                if pushed:
                    self.scopes = self.scopes[:-1]
        elif t is _TYPEALIAS:
            self.assign([st.name], cls, True)
            saved = self.scopes, self.late
            if st.type_params:
                self.scopes = self.scopes + [{p.name: None for p in st.type_params}]
            self.late = True                          # 值是惰性求值的
            ex(st.value)
            self.scopes, self.late = saved
        # Pass / Break / Continue / Global / Nonlocal：没有名字要记

    def shadowed(self, names: list, body, q: str, cls: str | None) -> None:
        """body 里 names 是另一个东西（except 的 as、模块顶层 / 类体里 for / with 的目标）。"""
        if not names:
            self.block(body, q, cls)
            return
        saved = self.scopes
        self.scopes = saved + [dict.fromkeys(names)]
        if self.cscope is not None:
            for n in names:
                self.cscope[n] = None
        self.block(body, q, cls)
        self.scopes = saved

    def loop_target(self, tg, body, q: str, cls: str | None) -> None:
        self.ex(tg)
        # 函数里的循环变量已经是局部名字；模块顶层 / 类体里的，循环体里把同名的全局遮住
        self.shadowed([n.id for n in _names(tg, [])] if not self.fn else [], body, q, cls)

    def assign(self, targets, cls: str | None, binds: bool) -> None:
        """赋值目标。模块顶层 / 类体里的第一次赋值就是这个变量的定义；类体里赋过的名字，类体后面看得见。"""
        at_class = self.cscope is not None
        if at_class or not self.fn:
            repo, rel = self.repo, self.rel
            for tg in targets:
                for n in _names(tg, []):
                    key = f"v:{cls}.{n.id}" if at_class else f"v:{self.m}:{n.id}"
                    w = repo.vars.get(key)
                    if key not in self.seen and w and w[1] == n.lineno and w[0] == rel:
                        self.seen.add(key)
                        self.emit(n.lineno, n.col_offset, n.id, key, DEF)
                    if at_class and binds:
                        self.cscope[n.id] = key if w else None
        for tg in targets:
            if type(tg) is not ast.Name:
                self.ex(tg)                           # x.y = / x[i] = / 元组里的属性

    def funcdef(self, st, q: str, cls: str | None) -> None:
        ex = self.ex
        for d in st.decorator_list:
            ex(d)
        a = st.args
        for d in a.defaults:
            ex(d)
        for d in a.kw_defaults:
            if d is not None:
                ex(d)
        saved = self.scopes, self.cscope, self.fn, self.late, self.meth
        tps = getattr(st, "type_params", None)
        if tps:
            self.scopes = self.scopes + [{p.name: None for p in tps}]
        self.late = True
        for x in _all_args(a):
            if x.annotation is not None:
                ex(x.annotation)
        if st.returns is not None:
            ex(st.returns)
        qn = q + st.name
        key = f"{self.m}:{qn}"
        if key in self.symbols:
            col = self.find_kw(st.lineno, st.col_offset, st.name, "def")
            if col is not None:
                self.emit(st.lineno, col, st.name, f"s:{key}", DEF)
        loc = _fn_locals(st, key, cls, self.symbols, self.walrus, self.import_binding)
        self.scopes = self.outer_chain() + [loc]
        self.cscope = None
        self.fn = True
        self.meth = cls if _first_param(st, cls) else None
        self.block(st.body, qn + ".", None)
        self.scopes, self.cscope, self.fn, self.late, self.meth = saved
        if self.cscope is not None:
            self.cscope[st.name] = f"s:{key}" if key in self.symbols else None

    def classdef(self, st, q: str, cls: str | None) -> None:
        ex = self.ex
        for d in st.decorator_list:
            ex(d)
        saved = self.scopes, self.cscope, self.meth
        tps = getattr(st, "type_params", None)
        if tps:
            self.scopes = self.scopes + [{p.name: None for p in tps}]
        for b in st.bases:
            ex(b)
        for k in st.keywords:
            ex(k.value)
        qn = q + st.name
        key = f"{self.m}:{qn}"
        if key in self.symbols:
            col = self.find_kw(st.lineno, st.col_offset, st.name, "class")
            if col is not None:
                self.emit(st.lineno, col, st.name, f"s:{key}", DEF)
        cs = _ClsScope()
        self.scopes = self.outer_chain() + [cs]
        self.cscope = cs
        self.meth = None
        self.block(st.body, qn + ".", key)
        self.scopes, self.cscope, self.meth = saved
        if self.cscope is not None:
            self.cscope[st.name] = f"s:{key}" if key in self.symbols else None

    def import_binding(self, module: str | None, name: str | None, level: int):
        return self.repo.binding(self.repo.from_binding(self.m, module, name, level))

    def imports(self, st) -> None:
        repo, m = self.repo, self.m
        if type(st) is ast.Import:
            for a in st.names:
                self.dotted(a.lineno, a.col_offset, a.name.split("."), "")
                if self.cscope is not None:
                    local = a.asname or a.name.split(".")[0]
                    self.cscope[local] = repo.import_target(a.name if a.asname else local)
            return
        base = repo.abs_module(m, st.level, st.module)
        if st.module:
            # `from` 之后、跳过空白和相对 import 的点，就是模块路径
            line = self.lines[st.lineno - 1].encode("utf-8") if 0 < st.lineno <= len(self.lines) else b""
            i = st.col_offset + 4
            while i < len(line) and line[i:i + 1] in (b" ", b"\t", b"."):
                i += 1
            self.dotted(st.lineno, i, st.module.split("."), repo.abs_module(m, st.level, None) if st.level else "")
        for a in st.names:
            if a.name == "*":
                continue
            t = repo.from_import(base, a.name)
            if t and t[1] == ":" and t[0] in "svmx":
                self.emit(a.lineno, a.col_offset, a.name, t, IMPORT)
            if self.cscope is not None:
                self.cscope[a.asname or a.name] = t

    def dotted(self, line: int, bcol: int, parts: list, prefix: str) -> None:
        """点分路径每段一个 token，各自指向到这一段为止的前缀：`a.b.c` 的 b → a.b。"""
        if not 0 < line <= len(self.lines):
            return
        text = self.lines[line - 1].encode("utf-8")
        pos, acc = bcol, prefix
        for i, p in enumerate(parts):
            pb = p.encode("utf-8")
            if text[pos:pos + len(pb)] != pb:
                return
            acc = f"{acc}.{p}" if acc else p
            t = self.repo.import_target(acc)
            if t and t[0] != "n":
                self.emit(line, pos, p, t, IMPORT)
            pos += len(pb)
            if i + 1 < len(parts):
                while text[pos:pos + 1] in (b" ", b"\t"):
                    pos += 1
                if text[pos:pos + 1] != b".":
                    return
                pos += 1
                while text[pos:pos + 1] in (b" ", b"\t"):
                    pos += 1

    def pattern(self, p, names: list) -> None:
        """match 的模式：值模式 / 类模式 / 映射的键是表达式，照常解析；捕获的名字收进 names。"""
        t = type(p)
        if t is ast.MatchValue:
            self.ex(p.value)
        elif t is ast.MatchClass:
            self.ex(p.cls)
            for x in p.patterns + p.kwd_patterns:
                self.pattern(x, names)
        elif t is ast.MatchMapping:
            for k in p.keys:
                self.ex(k)
            for x in p.patterns:
                self.pattern(x, names)
            if p.rest:
                names.append(p.rest)
        elif t is ast.MatchAs:
            if p.pattern is not None:
                self.pattern(p.pattern, names)
            if p.name:
                names.append(p.name)
        elif t is ast.MatchStar:
            if p.name:
                names.append(p.name)
        elif t is ast.MatchSequence or t is ast.MatchOr:
            for x in p.patterns:
                self.pattern(x, names)

    # ---- 表达式 ----
    def ex(self, n, kind: int = REF):
        """记下表达式里每个能解析的名字；返回它自己指向的目标（给外层的属性链用）。"""
        t = type(n)
        if t is ast.Name:
            if type(n.ctx) is not ast.Load:
                return None
            r = self.lookup(n.id)
            if r and r[1] == ":" and r[0] in "svmx":
                self.emit(n.lineno, n.col_offset, n.id, r, kind)
            return r
        if t is ast.Attribute:
            base = self.ex(n.value)
            attr = n.attr
            r = self.repo.member(base, attr) if base is not None else None
            if r is not None:
                if r[1] == ":" and r[0] in "svmx":
                    k = kind
                    if (r[0] == "v" and type(n.ctx) is ast.Store and r not in self.seen
                            and base.startswith("self:") and r == f"v:{base[5:]}.{attr}"
                            and self.repo.vars.get(r) == [self.rel, n.end_lineno]):
                        self.seen.add(r)              # 这个类里第一次 self.x = …：实例属性的定义
                        k = DEF
                    self.emit(n.end_lineno, n.end_col_offset, attr, r, k, True)
            elif (attr in self.repo.member_names and type(n.value) not in _LITERALS
                    and self.repo.unsure(base, attr)):
                sp = self.span(n.end_lineno, n.end_col_offset, attr, True)
                if sp:
                    self.repo.attrs.setdefault(attr, []).append(
                        (self.rel, self.repo.int(n.end_lineno), sp[0], sp[1], CALL if kind == CALL else REF))
            return r
        if t is ast.Constant:
            return None
        if t is ast.Call:
            f = n.func
            if (type(f) is ast.Name and f.id == "super" and self.meth and "super" not in self.tops
                    and not any("super" in s for s in self.scopes)):
                return self.super_call(n)
            self.ex(f, CALL)
            for x in n.args:
                self.ex(x)
            for k in n.keywords:
                self.ex(k.value)
            return None
        if t is ast.BinOp:                            # a + b + c + ...：左边嵌套的长链，别递归下去
            rights = []
            while type(n) is ast.BinOp:
                rights.append(n.right)
                n = n.left
            self.ex(n)
            for x in reversed(rights):
                self.ex(x)
            return None
        fields = _EXPR_FIELDS.get(t)
        if fields is not None:
            for fname in fields:
                v = getattr(n, fname)
                if v is None:
                    continue
                if type(v) is list:
                    for x in v:
                        if x is not None:             # Dict 的 ** 展开，键是 None
                            self.ex(x)
                else:
                    self.ex(v)
            return None
        if t in _COMPS:
            self.comp(n)
            return None
        if t is ast.Lambda:
            self.lam(n)
            return None
        for x in ast.iter_child_nodes(n):             # 以后的版本新加的表达式
            if isinstance(x, ast.expr):
                self.ex(x)
        return None

    def super_call(self, n):
        """方法里的 super() / super(本类, self)：从 MRO 上本类的下一个开始找。别的写法不解析。"""
        if not n.args and not n.keywords:
            return f"super:{self.meth}"
        ok = len(n.args) == 2 and not n.keywords and type(n.args[1]) is ast.Name
        c = None
        for i, x in enumerate(n.args):
            r = self.ex(x)
            if i == 0:
                c = r
        for k in n.keywords:
            self.ex(k.value)
        if ok and c == f"s:{self.meth}" and self.lookup(n.args[1].id) == f"self:{self.meth}":
            return f"super:{self.meth}"
        return None

    def comp(self, n) -> None:
        """推导式：第一个 for 的可迭代对象在外面求值；其余在自己的作用域里，循环变量只在里面遮。"""
        gens = n.generators
        self.ex(gens[0].iter)
        sh = {}
        for g in gens:
            for x in _names(g.target, []):
                sh[x.id] = None
        saved = self.scopes
        self.scopes = self.outer_chain() + [sh]
        for i, g in enumerate(gens):
            if i:
                self.ex(g.iter)
            if type(g.target) is not ast.Name:
                self.ex(g.target)
            for c in g.ifs:
                self.ex(c)
        if type(n) is ast.DictComp:
            self.ex(n.key)
            self.ex(n.value)
        else:
            self.ex(n.elt)
        self.scopes = saved

    def lam(self, n) -> None:
        a = n.args
        for d in a.defaults:
            self.ex(d)
        for d in a.kw_defaults:
            if d is not None:
                self.ex(d)
        saved = self.scopes, self.late, self.meth
        self.scopes = self.outer_chain() + [{x.arg: None for x in _all_args(a)}]
        self.late = True
        self.meth = None                              # lambda 里 super() 没有参数可用
        self.ex(n.body)
        self.scopes, self.late, self.meth = saved


ATTRS_MAX_SAME = 3       # 同名成员超过这么多个的名字，不记「同名的 .xxx」（见 _build 末尾）

def build(root: Path, index: dict) -> dict:
    # 建 AST 时一路触发的分代 GC 白白扫描几百万个节点；这里不产生循环引用，先关掉
    was = gc.isenabled()
    gc.disable()
    try:
        return _build(root, index)
    finally:
        if was:
            gc.enable()


def _build(root: Path, index: dict) -> dict:
    repo = _Repo(index)
    for m, rel in repo.file_of.items():              # 第一遍：先把所有模块顶层的绑定、类的成员收齐
        text, tree = _read(root / rel)
        _Collect(repo, m, rel, text is not None and ":=" in text).run(tree)
        del text, tree
    repo.finish_first_pass()
    files: dict[str, list] = {}
    fp: dict[str, list] = {}
    for m in sorted(repo.file_of):                   # 第二遍：逐个文件记 token
        rel = repo.file_of[m]
        p = root / rel
        try:
            st = os.stat(p)                           # 先 stat 再读：读完之后才改的，一定会被认成改过
        except OSError:
            continue
        text, tree = _read(p)
        if text is None:
            continue
        fp[rel] = [st.st_size, st.st_mtime_ns]
        if tree is None:
            continue
        toks = _Walk(repo, m, rel, text).run(tree)
        del text, tree
        if toks:
            toks.sort()
            files[rel] = toks
    # 边详情引用的名字按 `from 模块 import 名字` 的语义追到定义（和 Ctrl+点击同一套解析）
    names = {}
    for uses in (index.get("edge_uses") or {}).values():
        for key in uses:
            if key in repo.symbols or key in names:
                continue
            mod, _, name = key.partition(":")
            t = repo.from_import(mod, name)
            if t and t[:2] in ("s:", "v:") and repo.where(t):
                names[key] = repo.t(t)
    # 「同名的 .xxx」只对罕见的名字有用：仓库里叫这个名字的成员超过 3 个（get、shape、to、append……），
    # 按名字列出来的一大半都不是它，还占掉 xref.json 的三分之一。这些就不记了
    same: dict[str, int] = {}
    for t in repo.targets:
        if t[:2] in ("s:", "v:"):
            qual = t.split(":", 2)[2]
            if "." in qual:
                n = qual.rsplit(".", 1)[1]
                same[n] = same.get(n, 0) + 1
    attrs = {k: v for k, v in repo.attrs.items() if same.get(k, 0) <= ATTRS_MAX_SAME}
    for v in attrs.values():
        v.sort()
    return {"targets": repo.targets, "where": [repo.where(t) for t in repo.targets], "files": files,
            "fp": fp, "attrs": attrs, "names": names}


def write(outdir: Path, xref: dict) -> Path:
    p = outdir / "xref.json"
    p.write_text(json.dumps(xref, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


def invert(xref: dict) -> dict[int, list]:
    """目标下标 → 引用它的所有地方 [[文件, 行, 列, 种类], ...]（不含定义本身）。"""
    out: dict[int, list] = {}
    for rel, toks in xref["files"].items():
        for line, c, _, t, kind in toks:
            if kind != DEF:
                out.setdefault(t, []).append([rel, line, c, kind])
    return out
