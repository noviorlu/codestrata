"""xref 的类型推断：哪些值是仓库里某个类的实例，好让 `x.m()`、`self.x.m()` 定下被调方（跳转和 graph 的调用记录都用）。

只推代码里写明的：构造 `C(…)`（含 `C(…) if … else None`）；类型标注（参数、`x: C`、类体里的字段、`self.x: C`，
`Optional[C]`、`C | None`、字符串的前向引用也认）；函数 / 方法 / property 的返回值标注（`async def` 不算：调了是协程）；
`list[C]`、`dict[K, C]` 这类容器取出来的元素；`getattr(obj, "x")`。属性在几处赋的推不一样、有一处推不出的，就当不知道
（留给 trace）；有标注的只按标注。

推出来的值是字符串 "{种类}:模块:类"：
  i  C 的实例
  e  元素是 C 的实例的序列（下标、for、推导式取出来是 i；切片还是 e）
  d  值是 C 的实例的映射（下标、.get、.pop、.setdefault 是 i；.values() 是 e；.items() 是 p）
  p  第二项是 C 的实例的二元组的序列（enumerate(e)、d.items()）
第一遍（xref 的 _Collect）只记线索 (解析线索, 种类)，用到时才由 TypeResolver 解析；线索的种类多一个 c：
调用它的结果（类 → 实例，函数 → 按返回值标注）。解析线索是 _Collect.base_spec 的 ("L" | "G", 名字, 其余段, 行)。
这里只认 ast 的形状；名字指向哪由 xref 的 _Repo 解析（binding / at_line / member）。
"""
from __future__ import annotations

import ast

# 标注里的容器：元素（SEQS）或值（MAPS）是仓库里的类时，下标 / 迭代取出来的是它的实例
SEQS = frozenset(("list", "List", "Sequence", "MutableSequence", "Iterable", "Iterator", "Collection",
                  "set", "Set", "frozenset", "FrozenSet", "deque", "Deque"))
MAPS = frozenset(("dict", "Dict", "Mapping", "MutableMapping", "OrderedDict", "defaultdict", "DefaultDict"))
# (容器的种类, 方法名) → 调了之后的种类
_ELEM_CALLS = {("d", "get"): "i", ("d", "pop"): "i", ("d", "setdefault"): "i", ("d", "values"): "e",
               ("d", "items"): "p", ("e", "pop"): "i"}
# 内置函数 → 参数是 e 时结果的种类
_ITER_BUILTINS = {"enumerate": "p", "list": "e", "tuple": "e", "sorted": "e", "reversed": "e", "iter": "e", "set": "e"}
_MISS = object()


def is_none(n) -> bool:
    return type(n) is ast.Constant and n.value is None


def typed(v) -> bool:
    """值推出了类型（见模块说明）"""
    return bool(v) and v[:2] in ("i:", "e:", "d:", "p:")


def ann_class(ann):
    """标注写的是哪个类、套在什么容器里：C、C | None、Optional[C]、"C" → (C 的表达式, "i")；
    list[C]、Sequence[C]、tuple[C, ...] 这类 → (…, "e")；dict[K, C]、Mapping[K, C] 这类 → (…, "d")；别的是 None"""
    t = type(ann)
    if t is ast.Constant and type(ann.value) is str:
        try:
            ann = ast.parse(ann.value, mode="eval").body
        except SyntaxError:
            return None
        t = type(ann)
    if t is ast.BinOp and type(ann.op) is ast.BitOr:
        sides = [x for x in (ann.left, ann.right) if not is_none(x)]
        return ann_class(sides[0]) if len(sides) == 1 else None
    if t is ast.Subscript:
        v = ann.value
        head = v.attr if type(v) is ast.Attribute else v.id if type(v) is ast.Name else ""
        args = ann.slice.elts if type(ann.slice) is ast.Tuple else [ann.slice]
        if head in ("Optional", "Union"):
            sides = [x for x in args if not is_none(x)]
            return ann_class(sides[0]) if len(sides) == 1 else None
        if head in SEQS and len(args) == 1 or head in ("tuple", "Tuple") and len(args) == 2 and \
                type(args[1]) is ast.Constant and args[1].value is Ellipsis:
            inner, kind = ann_class(args[0]), "e"
        elif head in MAPS and len(args) == 2:
            inner, kind = ann_class(args[1]), "d"
        else:
            return None
        return (inner[0], kind) if inner and inner[1] == "i" else None
    if t is ast.Name or t is ast.Attribute:
        return ann, "i"
    return None


def iter_types(tg, it, names: list) -> dict:
    """for tg in it 绑的名字（names：tg 里绑定的 Name 节点）各是什么：it 是 e → tg 是 i；it 是 p → 二元组的第二项是 i；
    别的都不知道（None）"""
    out = {x.id: None for x in names}
    if it and it[:2] == "e:" and type(tg) is ast.Name:
        out[tg.id] = "i:" + it[2:]
    elif it and it[:2] == "p:" and type(tg) is ast.Tuple and len(tg.elts) == 2 and type(tg.elts[1]) is ast.Name:
        out[tg.elts[1].id] = "i:" + it[2:]
    return out


def subscript(v, is_slice: bool) -> str | None:
    """v[…]：序列 / 映射里取出来的是元素的实例；序列切片还是序列"""
    if v and v[:2] in ("e:", "d:"):
        return v if v[0] == "e" and is_slice else "i:" + v[2:]
    return None


def method_call(recv, attr: str) -> str | None:
    """recv.attr(…) 的结果：recv 是推出来的容器时按 _ELEM_CALLS"""
    k = _ELEM_CALLS.get((recv[0], attr)) if recv and recv[:2] in ("e:", "d:") else None
    return f"{k}:{recv[2:]}" if k else None


def builtin_call(name: str, arg) -> str | None:
    """enumerate(e) / list(e) / sorted(e) 这类内置函数的结果"""
    return f"{_ITER_BUILTINS[name]}:{arg[2:]}" if name in _ITER_BUILTINS and arg and arg[:2] == "e:" else None


def if_value(n, a, b) -> str | None:
    """条件表达式 n 的值（a、b 是两边推出来的）：一边是 None 时取另一边；两边推出来一样才算"""
    if is_none(n.orelse):
        return a if typed(a) else None
    if is_none(n.body):
        return b if typed(b) else None
    return a if typed(a) and a == b else None


class TypeResolver:
    """按第一遍记的线索推属性、函数返回值的类型。repo 是 xref 的 _Repo，用它的 symbols、binding、at_line、member 解析名字。"""

    def __init__(self, repo):
        self.repo = repo
        self.var_specs: dict[str, list] = {}         # 属性 "v:模块:类.x" → [(模块, 解析线索, 种类, 是不是标注)]
        self.ret_specs: dict[str, tuple] = {}        # 函数 "模块:限定名" → (模块, 返回值标注的解析线索, 种类)
        self._memo: dict = {}

    def instance(self, target, kind: str = "i") -> str | None:
        """target 是仓库里的一个类（s:模块:类）→ {kind}:模块:类；别的是 None"""
        if target and target[:2] == "s:" and (self.repo.symbols.get(target[2:]) or {}).get("k") == "class":
            return f"{kind}:{target[2:]}"
        return None

    def call_value(self, r) -> str | None:
        """调用 r 的结果：r 是仓库里的类 → 它的实例；是标了返回值类型的函数 → 按标注"""
        return self.instance(r) or (self.ret_type(r[2:]) if r and r[:2] == "s:" else None)

    def spec_value(self, m: str, sp, kind: str) -> str | None:
        """模块 m 里记的一条线索推出来的值"""
        if sp is None:
            return None
        where, first, rest, line = sp
        repo = self.repo
        r = repo.binding(first) if where == "L" else repo.at_line(m, first, line)
        for part in rest:
            r = repo.member(r, part)
        return self.call_value(r) if kind == "c" else self.instance(r, kind)

    def ret_type(self, key: str) -> str | None:
        """函数的返回值标注推出来的值（def make() -> Engine）"""
        rs = self.ret_specs.get(key)
        return self._cached(("r", key), self.spec_value, *rs) if rs else None

    def var_type(self, target: str) -> str | None:
        """属性 v:模块:类.x 的值推出来是什么。有标注的（类体里 x: C、self.x: C = …）只按标注；没有的按方法里
        self.x = 赋的值：C(…) / f(…)、[C(…) for …]、标了类型的参数。都推出同一个才算"""
        return self._cached(("v", target), self._var_type, target)

    def _var_type(self, target):
        specs = self.var_specs.get(target, ())
        found = set()
        for m, sp, kind, _ in [s for s in specs if s[3]] or specs:
            v = self.spec_value(m, sp, kind)
            if v is None:
                return None
            found.add(v)
        return found.pop() if len(found) == 1 else None

    def _cached(self, key, fn, *args):
        r = self._memo.get(key, _MISS)
        if r is _MISS:
            r = self._memo[key] = fn(*args)
        return r
