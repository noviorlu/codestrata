"""scan-trace alignment：把一个 run 的 trace 记录放到 graph 现在的节点上，再和 scan 记录比。

核心模型见 ARCHITECTURE 开头。这是加载 run 时做的一步（serve 打开一个 run 的时候），不运行程序：

  1. 放到现在的节点上：trace 的键是「文件:首行」。录制之后改过的文件，按录制时记下的函数名挪到函数
     现在的行号（remap）；再折到单元（文件）上，同时留下单元间每条边上「哪个函数调了哪个函数」
     （to_package_graph）。定义时的执行（import 时的模块顶层、class 语句的类体）不算调用（defining）。
  2. 和 scan 记录比：现在还按切面比——被调的方法先收到它的类上（top），在这条切面边的静态引用里
     就算两边都有，否则是只有 trace（页面上的「动态分派」）：hot_on_cut、dyn_only 给图，
     pair_items、restatus 给边详情。
  3. 给只有 trace 的调用找线索（hints）：调用方里哪几行在调它（按写法找），仓库里哪些字符串
     按名字提到了它（注册表、插件表）。
"""
from __future__ import annotations

import ast
import re
from functools import lru_cache
from pathlib import Path

from . import graph as _graph


# ---------------------------------------------------------------- 1 放到现在的节点上

def sym_locs(symbols: dict) -> tuple[dict, dict]:
    """trace 的键「文件:首行」怎么对回符号：((文件, 行) → 符号键, 文件 → [(起, 止, 符号键)])。
    装饰过的函数 co_firstlineno 指向第一个装饰器，所以 def 行和装饰器行都建索引；同名的另几个 def
    （property 的 setter，scan 记在 "a" 里）也算这个符号。范围给没有名字的帧（闭包、lambda）找外层符号用。"""
    loc2sym: dict[tuple[str, int], str] = {}
    spans: dict[str, list] = {}
    for key, s in symbols.items():
        for l, dl, e in [(s["l"], s.get("dl", s["l"]), s.get("e"))] + (s.get("a") or []):
            loc2sym.setdefault((s["f"], l), key)
            loc2sym.setdefault((s["f"], dl), key)
            if e:
                spans.setdefault(s["f"], []).append((dl, e, key))
    return loc2sym, spans


def defining(symbols: dict, loc2sym: dict, rel: str, ln: int) -> str | None:
    """键 rel:ln 的这一帧是定义时的执行、不是调用："module" / "class"，是调用返回 None。模块图（to_package_graph）
    和「时间顺序」（seq）用同一个判断。loc2sym 是 sym_locs(symbols) 的第一项。
      module —— <module> 帧（第 0 行；老 trace 记成第 1 行，那一行又没有符号），import 触发的模块顶层执行
      class  —— 类体：class 语句执行时跑一次的帧，co_firstlineno 是 class 行（有装饰器是第一个装饰器那一行），
                正好落在类符号的 l / dl 上（扫描端给这种符号标 x: ["defexec"]，这里只认标记，不认语言）。类不会被「调用」——实例化跑的是 __init__ / __new__，它们有自己的
                def 行——所以落在类符号上的帧只能是定义（3.12 泛型类的 <generic parameters of X> 帧也在这一行）。
                按行号认，已经录好的老 run 加载时一样分得出来"""
    if ln == 0:
        return "module"
    sk = loc2sym.get((rel, ln))
    if sk:                                      # 扫描端标了 defexec 的符号（Python 的类）：落在定义行上的是定义时的执行
        return "class" if "defexec" in (symbols[sk].get("x") or ()) else None
    return "module" if ln == 1 else None


def to_package_graph(trace: dict, index: dict) -> dict:
    """把函数粒度的 trace 折算到单元（文件）粒度，界面（ui.graphview）再按切面汇总叠到图上；同时保留
    每条单元间边上「谁调了谁」的明细，给点开箭头时用。

    返回 {"packages": {pkg: hits}, "edges": {"a|b": 调用次数},
          "symbols": {symbol_key: hits},
          "edge_calls": {"a|b": {被调符号: {n, f, l, callers: {调用方: {n, f, l}}}}},
          "edge_import_exec": {"a|b": import 触发的模块执行次数},
          "module_exec": [顶层代码执行过的文件], "module_frames": n, "class_frames": n,
          "anon": n, "unmapped": n}
    """
    files = index.get("files") or {}
    symbols = index.get("symbols") or {}
    loc2sym, spans = sym_locs(symbols)

    pkg_hits: dict[str, int] = {}
    sym_hits: dict[str, int] = {}
    file_hits: dict[str, int] = {}
    module_exec: set[str] = set()       # 哪些模块的顶层代码真的执行过——用来判断「副作用 import」是否在 runtime 生效了
    # 不算调用的帧（定义时的执行）和映射不到命名符号的调用，都是正常现象、不是丢数据：
    #   module / class —— 见 defining：只被 import 过的包、只定义过的类不算「跑到了」
    #   anon           —— 闭包、lambda、生成器表达式，本来就没有自己的符号
    module_frames = class_frames = anon = 0
    for k, n in trace["funcs"].items():
        rel, _, ln = k.rpartition(":")
        try:
            lineno = int(ln)
        except ValueError:
            continue
        d = defining(symbols, loc2sym, rel, lineno)
        if d == "module":
            module_frames += n
            module_exec.add(rel)
            continue
        if d == "class":
            class_frames += n
            continue
        sk = loc2sym.get((rel, lineno))
        if sk:
            sym_hits[sk] = sym_hits.get(sk, 0) + n
        else:
            anon += n
        pkg = files.get(rel)
        if pkg:
            pkg_hits[pkg] = pkg_hits.get(pkg, 0) + n
            file_hits[rel] = file_hits.get(rel, 0) + n

    # 没有名字的帧（闭包、lambda、生成器表达式）归到包住它的最内层命名符号，
    # 标成 外层符号.<L行号>，这样面板上能说「scan() 里的某个闭包调了它」。
    def label(rel: str, ln: int) -> tuple[str, int]:
        if ln < 0:                      # runs.remap 对不上的（录制之后改过的文件里）：归到文件、不归到函数
            return f"{rel}:<改过、对不上>", 1
        sk = None if ln == 0 else loc2sym.get((rel, ln))
        if sk:
            return sk, symbols[sk]["l"]
        if ln <= 1:
            return f"{rel}:<module>", 1
        inner = max((sp for sp in spans.get(rel, ()) if sp[0] <= ln <= sp[1]),
                    key=lambda sp: sp[0], default=None)
        return (f"{inner[2]}.<L{ln}>" if inner else f"{rel}:{ln}"), ln

    # 包间的 runtime 边和函数粒度的明细从同一份 func_edges 算，两边的数字才对得上。
    # 被调方是定义时的执行（defining：<module> 帧、类体）的不算调用——那是 import 语句触发的模块顶层执行，
    # 单独记在 edge_import_exec 里；否则每条 import 边都会因为「导入过」而被染成橙色。
    edge_hits: dict[str, int] = {}
    edge_calls: dict[str, dict] = {}
    import_exec: dict[str, int] = {}
    for k, n in (trace.get("func_edges") or {}).items():
        a, _, b = k.partition("|")
        fa, _, la = a.rpartition(":")
        fb, _, lb = b.rpartition(":")
        try:
            la_i, lb_i = int(la), int(lb)
        except ValueError:
            continue
        pa, pb = files.get(fa), files.get(fb)
        if not pa or not pb or pa == pb:
            continue
        ek = f"{pa}|{pb}"
        if defining(symbols, loc2sym, fb, lb_i):
            import_exec[ek] = import_exec.get(ek, 0) + n
            continue
        edge_hits[ek] = edge_hits.get(ek, 0) + n
        (callee, cl), (caller, rl) = label(fb, lb_i), label(fa, la_i)
        slot = edge_calls.setdefault(ek, {}).setdefault(
            callee, {"n": 0, "f": fb, "l": cl, "callers": {}})
        slot["n"] += n
        c = slot["callers"].setdefault(caller, {"n": 0, "f": fa, "l": rl})
        c["n"] += n

    return {"packages": pkg_hits, "edges": edge_hits, "symbols": sym_hits, "files": file_hits,
            "edge_calls": edge_calls, "edge_import_exec": import_exec,
            "module_exec": sorted(module_exec),
            "module_frames": module_frames, "class_frames": class_frames, "anon": anon,
            "unmapped": module_frames + class_frames + anon}


def remap(counts: dict, names: dict, fs: dict, idx: dict) -> tuple[dict, list[str]]:
    """录制之后改过的文件（changed / mismatch）里，按录制时记下的 qualname 把键改到函数现在的行号上。

    计数的键是「文件:首行号」，代码一改行号就变，叠加会落到别的函数上、或者落空。录制时 hook 给
    每个键记了 co_qualname（counts.json.gz 的 names）；这里用当前 index 的符号表（文件, 名字）→
    现在的行号（装饰过的函数，trace 记的是第一个装饰器那一行，所以有 dl 用 dl）把键改过来：
      - 嵌套函数的 qualname 是「outer.<locals>.inner」，符号表里记的是「outer.inner」：去掉 .<locals> 就对上；
      - lambda、生成器表达式这类没有名字的、老 run 没存 qualname 的、名字在现在的代码里找不到的
        （改名了、删了），计入 unmatched，键改成「文件:-1」：次数还算在这个文件（和它的模块）上，
        但不算到任何函数上——原来那一行现在可能是别的函数的定义，留着会把次数记到它头上；
      - 改写后撞到同一个键的，次数相加。
    只动这些文件；没改过的文件原样返回，模块顶层（第 0 行）也不动。返回 (新的计数, unmatched 的键)。"""
    # 只管 index 里有的文件：scan 排除了的（examples 之类）本来就不叠加，不该算进 unmatched
    files = idx.get("files") or {}
    todo = {rel for rel, st in fs.items() if st in ("changed", "mismatch") and rel in files}
    if not todo:
        return counts, []
    by: dict[tuple, int] = {}
    for s in (idx.get("symbols") or {}).values():
        if s["f"] in todo:
            by.setdefault((s["f"], s["n"]), s.get("dl", s["l"]))
    memo: dict[str, str] = {}
    unmatched: set[str] = set()

    def new(key: str) -> str:
        hit = memo.get(key)
        if hit is not None:
            return hit
        rel, _, ln = key.rpartition(":")
        nk = key
        q = names.get(key)
        # 模块顶层（第 0 行；老 trace 记成第 1 行、没有名字）不动
        if rel in todo and ln != "0" and not (ln == "1" and not q):
            if q and "<" not in q.replace(".<locals>", ""):
                line = by.get((rel, q.replace(".<locals>", "")))
                if line is not None:
                    nk = f"{rel}:{line}"
                else:
                    nk = f"{rel}:-1"
                    unmatched.add(key)
            else:
                nk = f"{rel}:-1"
                unmatched.add(key)
        memo[key] = nk
        return nk
    funcs: dict[str, int] = {}
    for k, v in counts["funcs"].items():
        nk = new(k)
        funcs[nk] = funcs.get(nk, 0) + v
    edges: dict[str, int] = {}
    for k, v in counts["func_edges"].items():
        a, _, b = k.partition("|")
        nk = new(a) + "|" + new(b)
        edges[nk] = edges.get(nk, 0) + v
    return {"funcs": funcs, "func_edges": edges}, sorted(unmatched)

# ---------------------------------------------------------------- 2 和 scan 记录比（按切面）

def top(symkey: str) -> str:
    """<路径>#Cls.method → <路径>#Cls。runtime 调到的是方法，静态引用的往往是类。"""
    f, sep, q = symkey.partition("#")
    return f"{f}#{q.split('.')[0]}" if sep and q else symkey


def hot_on_cut(hot: dict, node_of: dict, used: dict | None = None) -> tuple[dict, dict, dict]:
    """一个 run 的 hot（单元粒度）按切面汇总：(节点 → 次数, "a|b" 节点间的边 → 次数,
    "a|b" → 其中动态分派的次数)。

    动态分派和边详情（edge_detail）同一个口径：被调的符号（方法归到类）不在这条切面边的静态引用
    （used，边 → 引用到的符号）里。这个数要按切面算、不能按单元对算完再加：同一个符号可能一对单元里
    静态引用、另一对里 runtime 调到，合成一条边之后算「确认」。"""
    hp: dict[str, int] = {}
    for u, n in hot["packages"].items():
        if u in node_of:
            hp[node_of[u]] = hp.get(node_of[u], 0) + n
    he: dict[str, int] = {}
    for k, n in hot["edges"].items():
        a, _, b = k.partition("|")
        if a in node_of and b in node_of and node_of[a] != node_of[b]:
            kk = f"{node_of[a]}|{node_of[b]}"
            he[kk] = he.get(kk, 0) + n
    hd: dict[str, int] = {}
    for k, calls in (hot.get("edge_calls") or {}).items():
        a, _, b = k.partition("|")
        if a in node_of and b in node_of and node_of[a] != node_of[b]:
            kk = f"{node_of[a]}|{node_of[b]}"
            refs = (used or {}).get(kk, ())
            n = sum(x["n"] for c, x in calls.items() if top(c) not in refs)
            if n:
                hd[kk] = hd.get(kk, 0) + n
    return hp, he, hd


def edge_uses_on_cut(idx: dict, node_of: dict) -> dict[str, set]:
    """切面边 "a|b" → 两端底下各对单元之间静态引用到的符号（合起来）"""
    uses = idx.get("edge_uses") or {}
    out: dict[str, set] = {}
    for a, b, _ in idx.get("edges") or []:
        na, nb = node_of[a], node_of[b]
        if na != nb:
            out.setdefault(f"{na}|{nb}", set()).update(uses.get(f"{a}|{b}", {}))
    return out


def dyn_only(kinds: dict, he: dict, hd: dict) -> list[str]:
    """有静态边、但这次跑到的调用全是动态分派的切面边。
    这种边不能画成「引用 + runtime」的实线：import 的是一回事（比如一个常量），跑到的是另一回事
    （经由 self.model、注册表调到的类），展开之后实线就变成了没跑到的灰边加一条动态分派的虚线"""
    return sorted(k for k in kinds if he.get(k) and hd.get(k, 0) >= he[k])

def pair_items(uses: dict, calls: dict) -> list[tuple[str, list, list, str]]:
    """一对单元之间被引用 / 被调到的每个符号：(符号, 静态引用的位置, trace 调到的 [(被调符号, 明细)], 状态)。
    uses 是这对单元的 edge_uses，calls 是 to_package_graph 的 edge_calls 里这对单元的。被调的方法先收到它的类上
    （top）再和静态引用对：对上了是 confirmed，只有静态引用是 static，只有 trace 是 dynamic（「动态分派」）"""
    rt_by_top: dict[str, list] = {}
    for callee, info in calls.items():
        rt_by_top.setdefault(top(callee), []).append((callee, info))
    out = []
    for sym, locs in uses.items():
        rt = rt_by_top.pop(sym, [])
        out.append((sym, locs, rt, "confirmed" if rt else "static"))
    out += [(t, [], rts, "dynamic") for t, rts in rt_by_top.items()]
    return out


def merged_status(uses: list, runtime: list) -> str:
    """几对单元的明细合成一条边之后再定状态（同一个符号可能一对里静态引用、另一对里 trace 调到）"""
    return "confirmed" if runtime and uses else "dynamic" if runtime else "static"


# ---------------------------------------------------------------- 3 只有 trace 的调用的线索

@lru_cache(maxsize=256)
def _file_lines(path: str, mtime_ns: int) -> tuple[str, ...]:
    return tuple(Path(path).read_text(encoding="utf-8", errors="replace").splitlines())


@lru_cache(maxsize=64)
def _code_facts(path: str, mtime_ns: int) -> tuple[frozenset, frozenset, dict]:
    """一个文件的语法事实（docstring 行、签名行、每行由语法触发的特殊方法），找调用处用；见 graph.syntax_facts。
    解析不了的文件三样都是空的"""
    try:
        tree = ast.parse(Path(path).read_bytes())
    except (SyntaxError, ValueError, OSError):
        tree = None
    return _graph.syntax_facts(tree)


_DEF_LINE = re.compile(r"\s*(?:async\s+)?(?:def|class)\s")

# 被调的是特殊方法时，调用方那一行上多半不写它的名字，写的是触发它的语法：页面上怎么说这种写法。
# 按语法找（_code_facts）的：下面这些；写法里没有能认的记号的（对象(…) 调 __call__、取个不存在的
# 属性调 __getattr__）在 _IMPLICIT 里，只找显式写了名字的。没列的特殊方法照普通方法按名字找
_ARITH = {"add": "+", "sub": "-", "mul": "*", "matmul": "@", "truediv": "/", "floordiv": "//", "mod": "%",
          "pow": "**", "lshift": "<<", "rshift": ">>", "and": "&", "or": "|", "xor": "^"}
_BY_SYNTAX: dict[str, str] = {
    **{f"__{p}{op}__": f"… {s}{'=' if p == 'i' else ''} …" for op, s in _ARITH.items() for p in ("", "r", "i")},
    "__eq__": "… == …", "__ne__": "… != …", "__le__": "… <= …", "__ge__": "… >= …", "__lt__": "… < …",
    "__gt__": "… > …", "__enter__": "with …", "__exit__": "with …", "__aenter__": "async with …",
    "__aexit__": "async with …", "__iter__": "for … in …", "__next__": "for … in …", "__aiter__": "async for …",
    "__anext__": "async for …", "__await__": "await …", "__getitem__": "…[…]", "__class_getitem__": "…[…]",
    "__setitem__": "…[…] = …", "__delitem__": "del …[…]", "__contains__": "… in …", "__len__": "len(…) / if 对象",
    "__bool__": "if 对象", "__hash__": "hash(…) / 字典的键", "__str__": "str(…)", "__repr__": "repr(…)",
    "__format__": "f\"{…}\"", "__neg__": "-…", "__pos__": "+…", "__invert__": "~…", "__abs__": "abs(…)",
    "__reversed__": "reversed(…)", "__int__": "int(…)", "__index__": "int(…)", "__float__": "float(…)",
    "__round__": "round(…)",
}
_IMPLICIT = {"__call__": "对象(…)", "__getattr__": "对象.属性（它没有这个属性时）", "__getattribute__": "对象.属性",
             "__setattr__": "对象.属性 = …", "__delattr__": "del 对象.属性", "__get__": "对象.属性（描述符）",
             "__set__": "对象.属性 = …（描述符）", "__delete__": "del 对象.属性（描述符）"}
_ACCESSORS = ("setter", "getter", "deleter")


def _call_form(q: str, d: dict | None):
    """被调函数（限定名 q，符号表条目 d）在调用方那一行上长什么样：(按名字找的 re, 按语法找的特殊方法名或 None,
    {callee, how, form})。how 是怎么找的——call：按名字（`名字(`、getattr 的 `'名字'`、装饰器 `@名字`）；
    attr：property（scan 记下的装饰器），取属性就是调用（`.名字`）；syntax：由语法触发的特殊方法（with、for、[]、
    运算符……，按 _code_facts）；implicit：写法里认不出的特殊方法（对象(…) 调 __call__），只找显式写了名字的。
    form 是页面上说的写法。闭包、模块顶层没有名字可找：None"""
    parts = q.split(".")
    name = parts[-1]
    if not name or name.startswith("<"):
        return None
    # 构造：调用方写的是 类名(…)（__post_init__ 由 dataclass 生成的 __init__ 调，那个 __init__ 不在仓库里）
    names = [parts[-2], name] if name in ("__init__", "__new__", "__post_init__") and len(parts) > 1 else [name]
    alt = "|".join(map(re.escape, names))
    quoted = rf"['\"](?:{alt})['\"]"
    info = {"callee": names[0], "how": "call", "form": f"{names[0]}(…)"}
    if any(x.endswith("property") or x in _ACCESSORS for x in (d or {}).get("d") or ()):
        return re.compile(rf"\.(?:{alt})\b|{quoted}"), None, {**info, "how": "attr", "form": f".{name}"}
    by_name = re.compile(rf"(?<![\w])(?:{alt})\s*\(|{quoted}|^\s*@(?:[\w.]*\.)?(?:{alt})\b")
    if name in _BY_SYNTAX:
        return by_name, name, {**info, "how": "syntax", "form": _BY_SYNTAX[name]}
    if name in _IMPLICIT:
        return by_name, None, {**info, "how": "implicit", "form": _IMPLICIT[name]}
    return by_name, None, info


def _add_call_sites(repo: Path, idx: dict, items: list) -> None:
    """点开一条边时要给看的代码：每个调到的函数 from（调用方里调它的那一行）和 to（它自己的签名）。

    - caller["sites"]：在调用方的函数体里找调用那一行，最多 3 处。按被调函数的写法找（_call_form）：
      普通函数按名字（`名字(`、`'名字'`、`@名字`），property 按 `.名字`，特殊方法按触发它的语法（with、
      for、[]、运算符）；caller["how"]、caller["form"] 记着是怎么找的、页面上怎么说那种写法。
      找过但没找到是 []——中间隔了 __call__、回调或仓库外的代码，这时 caller["sig"] 是调用方自己的签名，
      页面上拿它当 from。动态分派多半就写在这一行上：self.model.compute_logits(…)。
    - runtime 条目的 r["sig"]：被调函数的签名（def 那一行到冒号为止，最多 6 行）
    - 没跑到的静态引用：item["sig"] 是被引用符号的签名，item["use_s"] 是第一处引用那一行
    只在仓库里扫描过的文件里找；只看写法，不做类型推断。"""
    syms, files = idx.get("symbols") or {}, idx.get("files") or {}

    def body(sym: str) -> list[int]:
        """调用方函数体的行下标（从 def 行起：它自己的装饰器是外层执行的）；同名的另几个 def
        （property 的 setter）也算"""
        while sym not in syms and ".<L" in sym:          # 闭包：用包住它的那个函数的范围
            sym = sym.rsplit(".<L", 1)[0]
        d = syms.get(sym)
        if not d or not d.get("e"):
            return []
        return sorted({i for a, e in [(d["l"], d["e"])] + [(x[0], x[2]) for x in d.get("a") or ()]
                       for i in range(a - 1, e)})

    def cached(f: str, reader):
        """扫描过的文件 f 经 reader（按 mtime 缓存的 _file_lines / _code_facts）读出来的东西；不是扫描过的、
        读不了的是 None"""
        if f not in files:
            return None
        try:
            st = (repo / f).stat()
            return reader(str(repo / f), st.st_mtime_ns)
        except OSError:
            return None

    def lines(f: str):
        return cached(f, _file_lines)

    def sites(c: dict, pat, dunder: str | None) -> list | None:
        """调用方 c 的函数体里调被调函数的那几行（最多 3 处）：按名字 pat 找到的，或者（特殊方法）这一行上的语法
        会触发 dunder（_code_facts）。跳过签名、docstring、注释"""
        f = (c.get("def") or {}).get("f")
        rows, ls = body(c["sym"]), lines(f) if f else None
        if not rows or ls is None:
            return None
        prose, sig, syn = cached(f, _code_facts) or (frozenset(), frozenset(), {})

        def hit(i: int) -> bool:
            if i + 1 in prose or i + 1 in sig or _DEF_LINE.match(ls[i]) or ls[i].lstrip().startswith("#"):
                return False
            return bool(pat.search(ls[i])) or (dunder is not None and dunder in syn.get(i + 1, ()))
        return [{"f": f, "l": i + 1, "s": ls[i].strip()[:200]} for i in rows if i < len(ls) and hit(i)][:3]

    def sig(d: dict | None) -> list[str] | None:
        ls = lines(d["f"]) if d else None
        if not ls or not 0 < d["l"] <= len(ls):
            return None
        if d.get("k") == "var":                          # 模块级变量：赋值那一行
            return [ls[d["l"] - 1].strip()[:200]]
        out = []
        for t in ls[d["l"] - 1:d["l"] + 5]:
            out.append(t.rstrip())
            if t.split("#", 1)[0].rstrip().endswith(":"):
                break
        if len(out) == 1:
            return [out[0].strip()[:200]]
        # 多行签名压成一行（面板窄）：def forward(self, input_ids: …, positions: …) -> …:
        one = re.sub(r"\(\s+", "(", re.sub(r",?\s*\)", ")", " ".join(t.strip() for t in out)))
        closed = out[-1].split("#", 1)[0].rstrip().endswith(":")
        return [one[:200] + ("" if closed else " …")]

    for it in items:
        if not it["runtime"]:
            if it.get("def"):
                it["sig"] = sig(it["def"])
            if it.get("uses"):
                ls = lines(it["uses"][0]["f"])
                l = it["uses"][0]["l"]
                it["use_s"] = ls[l - 1].strip()[:200] if ls and 0 < l <= len(ls) else None
            continue
        for r in it["runtime"]:
            r["sig"] = sig(r.get("def"))
            form = _call_form(r["sym"].partition("#")[2], syms.get(r["sym"]))
            if not form:
                continue                                 # 闭包、模块顶层：没有名字可找
            pat, dunder, info = form
            for c in r["callers"]:
                found = sites(c, pat, dunder)
                if found is None:
                    continue
                c["sites"] = found
                c.update(info)
                if not c["sites"]:
                    c["sig"] = sig(c["def"])


def _add_wiring(repo: Path, idx: dict, items: list) -> None:
    """动态分派调到的类：仓库里哪些字符串按名字提到了它（scan 的 name_refs）——注册表
    {"Arch": ("pkg", "mod", "Cls")}、getattr(mod, "Cls")、插件表里的 "pkg.mod.Cls"。调用方和它之间
    没有 import，接线多半就在这几行。记在 item["wiring"] = {refs: [{f, l, s, exact}], n, same_name}：
    带模块的类路径只认模块对得上的（exact）；只有类名的，同一个文件里挨着的几行（注册表的键和元组里的
    类名）只留第一行，same_name > 1 时仓库里有同名类、这些字符串不一定指它。老的 index 没有 name_refs：不加。"""
    refs_by = idx.get("name_refs")
    if refs_by is None:
        return
    syms = idx.get("symbols") or {}
    n_same: dict[str, int] = {}
    for it in items:
        d = it.get("def")
        if it["status"] != "dynamic" or not d or d.get("k") != "class":
            continue
        # 字符串里带的是点分的模块名（"pkg.mod.Cls"），和类所在文件的模块名比
        name, mod = it["name"].rsplit(".", 1)[-1], (syms.get(it["sym"]) or {}).get("m")
        if name not in n_same:
            n_same[name] = sum(1 for x in syms.values() if x["k"] == "class" and x["n"].rsplit(".", 1)[-1] == name)
        kept: list[dict] = []
        for ref in sorted(refs_by.get(name) or [], key=lambda r: (r[0], r[1])):   # scan 按 ast.walk 的顺序收的
            f, l, exact = ref[0], ref[1], len(ref) > 2
            if exact and ref[2] != mod:
                continue                                 # 别的模块里的同名类
            if kept and kept[-1]["f"] == f and 0 <= l - kept[-1]["l"] <= 3:
                if exact and not kept[-1]["exact"]:     # 同一处登记：留带模块的那一行
                    kept[-1] = {"f": f, "l": l, "s": "", "exact": True}
                continue
            kept.append({"f": f, "l": l, "s": "", "exact": exact})
        if not kept:
            continue
        kept.sort(key=lambda r: not r["exact"])          # 带模块的（没有歧义）排前面
        for r in kept[:6]:
            try:
                ls = _file_lines(str(repo / r["f"]), (repo / r["f"]).stat().st_mtime_ns)
                r["s"] = ls[r["l"] - 1].strip()[:200] if 0 < r["l"] <= len(ls) else ""
            except OSError:
                pass
        it["wiring"] = {"refs": kept[:6], "n": len(kept), "same_name": n_same[name]}


def hints(repo: Path, idx: dict, items: list) -> None:
    """动态分派的两条线索：调用方那一行（_add_call_sites）、按名字接线的地方（_add_wiring）"""
    _add_call_sites(repo, idx, items)
    _add_wiring(repo, idx, items)
