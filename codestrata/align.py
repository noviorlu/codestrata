"""scan-trace alignment：把一个 run 的 trace 记录放到 graph 现在的节点上，再和 scan 记录比。

核心模型见 ARCHITECTURE 开头。这是加载 run 时做的一步（serve 打开一个 run 的时候），不运行程序：

  1. 放到现在的节点上：trace 的键是「文件:首行」。录制之后改过的文件，按录制时记下的函数名挪到函数
     现在的行号（remap）；再落到 graph 的节点上（符号键、<文件>#<module>、<外层>.<L行>），
     得到「哪个函数在哪一行调了哪个函数、几次」（to_package_graph）。定义时的执行（import 时的模块顶层、
     class 语句的类体）不算调用（defining）。
  2. 和 scan 记录比（graph.json，见 graph.py）：trace 说 F 在第 L 行调了 G，看 scan 在 F 的第 L 行记的那处调用
     （classify）。scan 定下的被调方就是 G，或者写的是构造 C(…)、跑的是 C 沿继承找到的 __init__ 这类：两边都有；
     其余是「只有 trace」——代码里看不出会调到 G（定到了基类的方法、只知道名字、这一行 scan 什么都没看到），
     记下是哪一种。构造的调用挪到 F→C 上，和 scan 的记录对上。老 run 没有调用行：在 F 整个函数里比，调用处按名字猜。
     切面上按节点合起来：scan_edges_on_cut、hot_on_cut。
  3. 只有 trace 的调用的线索：仓库里哪些字符串按名字提到了被调的类（注册表、插件表；wiring）。
"""
from __future__ import annotations

from . import graph as _graph


# ---------------------------------------------------------------- 1 放到现在的节点上

UNMATCHED = "<改过、对不上>"     # remap 对不上的调用方 / 被调方：<文件>#<改过、对不上>，只归到文件

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
    """把一个 run 的 trace 记录（计数，键是「文件:首行」）放到当前 index 的节点上，并和 scan 记录比（classify）。

    返回 {"packages": {单元: 次数}, "symbols": {符号键: 次数}, "files": {文件: 次数},
          "calls": {"调用方|被调方": {a, b, n, only, lines, guessed, …}},   见 classify；a、b 是两端的单元（没有是 null）
          "redirect": {"trace 的键对": 类},   整个归到构造 F→C 上的调用（见 classify），「时间顺序」、请求路径也算到 C 上
          "module_exec": [顶层代码执行过的文件], "module_frames": n, "class_frames": n, "anon": n, "unmapped": n}
    calls 里同一个文件里的调用也有（代码窗口要）；图上只画不同节点之间的。
    """
    files = index.get("files") or {}
    symbols = index.get("symbols") or {}
    loc2sym, spans = sym_locs(symbols)

    pkg_hits: dict[str, int] = {}
    sym_hits: dict[str, int] = {}
    file_hits: dict[str, int] = {}
    module_exec: set[str] = set()       # 哪些模块的顶层代码真的执行过
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

    label = node_labeler(index, loc2sym, spans)

    # 函数对和它们的调用行。被调方是定义时的执行（<module> 帧、类体）的不算调用：import 语句触发的模块顶层执行、
    # class 语句执行类体
    pairs: dict[str, dict] = {}
    raw: dict[str, list] = {}           # 函数对 → 落到它上面的 trace 键对（seq 要按同样的规则改道，见 redirect）
    for k, n in (trace.get("func_edges") or {}).items():
        a, _, b = k.partition("|")
        fa, _, la = a.rpartition(":")
        fb, _, lb = b.rpartition(":")
        try:
            int(la)
            lb_i = int(lb)
        except ValueError:
            continue
        if defining(symbols, loc2sym, fb, lb_i) or fa[:1] == "<":
            continue                    # 定义时的执行；调用方是 case 自己的代码（图上没有它）
        pk = f"{label(a)}|{label(b)}"
        x = pairs.get(pk)
        if x is None:
            x = pairs[pk] = {"a": files.get(fa), "b": files.get(fb), "n": 0, "lines": None}
            raw[pk] = []
        x["n"] += n
        raw[pk].append(k)
    lines = trace.get("func_lines")
    if lines is not None:                # 这个 run 记了调用行（2026-09-30 之后录的）
        for x in pairs.values():
            x["lines"] = {}
        for k, n in lines.items():
            ab, _, ln = k.rpartition("|")
            a, _, b = ab.partition("|")
            x = pairs.get(f"{label(a)}|{label(b)}") if ":" in a and ":" in b else None
            if x is not None:
                x["lines"][int(ln)] = x["lines"].get(int(ln), 0) + n
    calls, moved = classify(pairs, index)
    # 整个挪到构造 F→C 上的函数对：「时间顺序」、请求路径读 span 时这些键对也算到 C 上
    redirect = {k: c for pk, c in moved.items() if c in symbols for k in raw[pk]}

    return {"packages": pkg_hits, "symbols": sym_hits, "files": file_hits,
            "calls": calls, "redirect": redirect,
            "module_exec": sorted(module_exec),
            "module_frames": module_frames, "class_frames": class_frames, "anon": anon,
            "unmapped": module_frames + class_frames + anon}


def node_labeler(index: dict, loc2sym: dict | None = None, spans: dict | None = None):
    """trace 的键「文件:首行」→ graph 的节点（和 graph.json 同一种写法）：符号键；模块顶层是 <文件>#<module>；
    没有名字的帧（lambda、生成器表达式）归到包住它的最内层命名符号，标成 <外层>.<L行>；remap 对不上的（行号 -1）
    是 <文件>#<改过、对不上>。返回带缓存的函数。loc2sym、spans 是 sym_locs 的结果（给了就不再算）"""
    if loc2sym is None or spans is None:
        loc2sym, spans = sym_locs(index.get("symbols") or {})
    memo: dict[str, str] = {}

    def label(key: str) -> str:
        hit = memo.get(key)
        if hit is None:
            rel, _, ln = key.rpartition(":")
            ln_i = int(ln)
            if ln_i < 0:                # remap 对不上的（录制之后改过的文件里）：归到文件、不归到函数
                hit = f"{rel}#{UNMATCHED}"
            elif (sk := None if ln_i == 0 else loc2sym.get((rel, ln_i))):
                hit = sk
            elif ln_i <= 1:
                hit = f"{rel}#<module>"
            else:
                inner = max((sp for sp in spans.get(rel, ()) if sp[0] <= ln_i <= sp[1]),
                            key=lambda sp: sp[0], default=None)
                hit = f"{inner[2] if inner else rel + '#<module>'}.<L{ln_i}>"
            memo[key] = hit
        return hit
    return label


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
    只动这些文件；没改过的文件原样返回，模块顶层（第 0 行）也不动。有调用行（func_lines）的话调用行跟着调用方挪；
    挪不了的（调用方是模块顶层或者对不上）行记成 0，classify 把它当成不知道是哪一行。
    返回 (新的计数, unmatched 的键)。"""
    new = key_mapper(names, fs, idx)
    if new is None:
        return counts, []
    funcs: dict[str, int] = {}
    for k, v in counts["funcs"].items():
        nk = new(k)
        funcs[nk] = funcs.get(nk, 0) + v
    edges: dict[str, int] = {}
    for k, v in counts["func_edges"].items():
        a, _, b = k.partition("|")
        nk = new(a) + "|" + new(b)
        edges[nk] = edges.get(nk, 0) + v
    out = {"funcs": funcs, "func_edges": edges}
    if "func_lines" in counts:
        # 调用行跟着调用方挪：函数整个挪了几行，里面的调用也挪几行（函数体里面改过的，行就可能偏）；
        # 调用方是模块顶层（文件:0，没有可以对的 def 行）、对不上的（文件:-1），不知道挪到哪了，行记成 0
        lines: dict[str, int] = {}
        for k, v in counts["func_lines"].items():
            ab, _, ln = k.rpartition("|")
            a, _, b = ab.partition("|")
            na, line = new(a), int(ln)
            if line and a.rpartition(":")[0] in new.todo:
                old, now = int(a.rpartition(":")[2]), int(na.rpartition(":")[2])
                line = line + now - old if old > 0 and now > 0 else 0
            nk = f"{na}|{new(b)}|{line}"
            lines[nk] = lines.get(nk, 0) + v
        out["func_lines"] = lines
    return out, sorted(new.unmatched)


def key_mapper(names: dict, fs: dict, idx: dict):
    """remap 的那一步单拿出来：返回 new(键) → 现在的键（规则见 remap），带着 new.unmatched（对不上的老键）、
    new.todo（要挪的文件）；
    没有要挪的文件时是 None。「时间顺序」读 span 时也用它（span 里存的是录制时的键）。"""
    # 只管 index 里有的文件：scan 排除了的（examples 之类）本来就不叠加，不该算进 unmatched
    files = idx.get("files") or {}
    todo = {rel for rel, st in fs.items() if st in ("changed", "mismatch") and rel in files}
    if not todo:
        return None
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
    new.unmatched = unmatched
    new.todo = todo
    return new


# ---------------------------------------------------------------- 2 和 scan 记录比

_CTOR = ("__init__", "__new__", "__post_init__")


def base_node(key: str) -> str:
    """lambda、生成器表达式这种 <外层>.<L行> 节点 → 外层的命名节点"""
    return key.split(".<L", 1)[0]


def _last(key: str) -> str:
    """节点键的最后一段名字：pkg/a.py#A.run → run"""
    return key.partition("#")[2].rsplit(".", 1)[-1]


def scan_by_base(index: dict) -> dict:
    """graph.json 的记录按调用方的命名节点分组（lambda 里的调用也算在外层上，按行区分）：
    {外层节点: [(行, 末行, 被调方 或 None, 名字, 种类), …]}。算一次存在 index 里"""
    if "_scan_by_base" not in index:
        g = index.get("graph") or {}
        C, out = g.get("callees") or [], {}
        for caller, xs in (g.get("calls") or {}).items():
            out.setdefault(base_node(caller), []).extend((l, e, C[i], None, k) for i, l, e, k in xs)
        for caller, xs in (g.get("sites") or {}).items():
            out.setdefault(base_node(caller), []).extend((l, e, None, nm, k) for nm, l, e, k in xs)
        index["_scan_by_base"] = out
    return index["_scan_by_base"]


def ctor_classes(index: dict, recs: list, callee: str) -> list[str]:
    """recs 里写的构造 C(…) 中，构造时会跑到 callee 的那些类（graph.json 的 ctors：沿继承找到的 __new__ / __init__ /
    __post_init__）"""
    if _last(callee) not in _CTOR:
        return []
    ctors = (index.get("graph") or {}).get("ctors") or {}
    out: list[str] = []
    for r in recs:
        if r[4] == _graph.NEW and r[2] not in out and callee in (ctors.get(r[2]) or ()):
            out.append(r[2])
    return out


# 把生成器 / 协程真正跑起来的写法：这一行写的是它们的时候，被调方多半写在函数里别处（晚一步才启动）
_STARTERS = frozenset(("__enter__", "__aenter__", "__next__", "next", "send", "asend", "__anext__", "__await__"))
_NEAR = 3                 # with ( / 推导式的开头一行，往下看这么多行


def judge(recs: list, callee: str, whole: bool = False, *, fn: list | None = None, line: int = 0,
          prop: bool = False) -> tuple[str, dict | None]:
    """scan 在这一行记的调用（whole：不知道是哪一行，调用方整个函数的）和「trace 调到了 callee」对不对得上
    （构造另算，见 classify）：("both", 说明 或 None) / ("trace", 说明)。fn 是调用方整个函数的记录、line 是这一行，
    prop 是被调方是 property（或 __getattr__）。说明：
      {"k": "deferred", "at": [行]}   两边都有：写在第几行，到这一行才开始跑（生成器、协程、with：帧在被消费的那一行才起）
      {"k": "override", "w": 被调方}   写的是 w（比如基类的方法），跑的是 callee（子类覆盖的）
      {"k": "name", "names": [名字]}  scan 只知道写的名字，就是 callee 的名字（构造方法也认类名），定不下被调方
                                      （self.model.compute_logits、语法触发的特殊方法、getattr(m, "Net")()）
      {"k": "prop", "name": 名字}     这一行读了属性（property），接收者的类型定不下
      {"k": "getattr"}                这一行读的属性在类里没定义，走了 __getattr__
      {"k": "line", "c": [...], "ext": [...], "names": [...]}   这一行 scan 看到的别的调用，经其中一个转了一道：
                                      c 定下的仓库里的函数（装饰器、框架），ext 仓库外的（sorted(key=…)、线程池回调），
                                      names 定不下的名字（"" 是调一个表达式的结果：f()()、fs[i]()；super().x 是 MRO 上的下一个类）；
                                      只看从这一行开始的调用（跨过这一行的多行外层调用不算），语法触发的特殊方法不算；没有的键不给
      {"k": "none"}                   这一行 scan 没看到调用（取普通属性触发的、模块级 __getattr__）
      {"k": "nomatch"}                whole：调用方里没有同名的调用（不知道是哪一行，别的就不猜了）"""
    last = _last(callee)
    if any(r[2] == callee for r in recs):
        return "both", None
    w = next((r[2] for r in recs if r[2] and _last(r[2]) == last), None)
    if w:
        return "trace", {"k": "override", "w": w}
    own = {last, _last(callee.rpartition(".")[0])} if last in _CTOR else {last}
    named = sorted({r[3] for r in recs if r[2] is None and r[3] in own})
    if named:
        return "trace", {"k": "name", "names": named}
    if whole:
        return "trace", {"k": "nomatch"}
    here = [r for r in recs if r[0] == line] if line else []
    if fn is not None and line:
        # 这一行没有写明的调用（只有语法触发的、或者 x.__enter__() / next(g) 这种把生成器跑起来的）
        quiet = all(r[4] == _graph.SYN or (r[2] is None and (r[3] or "") in _STARTERS) for r in here)
        # 生成器 / 协程 / with：写的地方和真正开始跑的地方不是同一行
        later = sorted({r[0] for r in fn if r[2] == callee and (
            any(o[2] != callee and o[0] <= r[0] <= o[1] for o in here)     # 写在这一行那个调用的参数里：await wait_for(self.f(…))
            or quiet)})                                                    # 这一行是 for x in g / with ( / next(g)：写在函数里别处
        if later:
            return "both", {"k": "deferred", "at": later[:3]}
        if quiet:                     # 推导式、with 的开头一行：下面几行里有同名的（for 子句里的 __iter__）
            below = sorted({r[3] for r in fn if line < r[0] <= line + _NEAR and r[2] is None and r[3] in own})
            if below:
                return "trace", {"k": "name", "names": below}
    if prop:
        return "trace", {"k": "getattr"} if last == "__getattr__" else {"k": "prop", "name": last}
    pool = [r for r in (here or recs) if r[4] != _graph.SYN]
    seen = {"c": sorted({r[2] for r in pool if r[2]})[:4],
            "ext": sorted({r[3] or "" for r in pool if r[2] is None and r[4] == _graph.EXT}),
            "names": sorted({r[3] or "" for r in pool if r[2] is None and r[4] != _graph.EXT})}
    seen = {k: v for k, v in seen.items() if v}
    return "trace", {"k": "line", **seen} if seen else {"k": "none"}


def classify(pairs: dict, index: dict) -> tuple[dict, dict]:
    """给 to_package_graph 的函数对填上和 scan 比的结果，返回 (函数对, moved)。每个函数对 {a, b, n, only, lines, guessed}：
      only     其中「只有 trace」的次数（代码里看不出会调到它）
      lines    有调用行时 [{l, n, status, note}]：status 是 both / trace，note 见 judge。l 是 0 的不知道是哪一行
               （录制之后改过的文件，见 remap）：按调用方整个函数比
      guessed  老 run（没有调用行）：在调用方里按名字找到的调用处 [行]；lines 是 null，整个函数对一个 status、note
    调用方自己里面的 lambda、生成器表达式（F → F.<L行>）算两边都有：就写在这儿。
    构造 C(…)（scan 的种类 1）跑的是 C 沿继承找到的 __new__ / __init__ / __post_init__：这些调用从 F→方法 挪到 F→C
    这个函数对上（被调方是类，status both，note {"k": "ctor", "via": [跑到的方法]}），和 scan 的那条记录对上，
    一次构造只算一次：同一行的 __new__ 和 __init__ 取多的那个；一行里几处构造都会跑到这个方法（A(B())，A、B
    继承同一个 __init__）时平分。moved：整个挪到了同一个类上的函数对 → 类"""
    by = scan_by_base(index)
    syms = index.get("symbols") or {}
    out: dict[str, dict] = {}
    built: dict[str, dict] = {}         # "F|C" → {"a", "lines": {行: {方法: 次数}}}；老 run 的行是 None
    moved: dict[str, str] = {}

    def move(caller: str, cs: list, l: int | None, callee: str, n: int, a: str | None) -> None:
        for i, c in enumerate(cs):
            share = n // len(cs) + int(i < n % len(cs))
            if share:
                per = built.setdefault(f"{caller}|{c}", {"a": a, "lines": {}})["lines"].setdefault(l, {})
                per[callee] = per.get(callee, 0) + share

    for pk, x in pairs.items():
        caller, _, callee = pk.partition("|")
        recs = by.get(base_node(caller), [])
        local = ".<L" in callee and base_node(callee) == base_node(caller)
        prop = _last(callee) == "__getattr__" or _is_prop(syms.get(base_node(callee)))
        if x["lines"] is None:
            cs = ctor_classes(index, recs, callee)
            if cs:
                move(caller, cs, None, callee, x["n"], x["a"])
                if len(cs) == 1:
                    moved[pk] = cs[0]
                continue
            st, note = ("both", None) if local else judge(recs, callee, whole=True)
            last = _last(callee)
            guess = sorted({r[0] for r in recs if r[2] == callee or r[3] == last or (r[2] and _last(r[2]) == last)})
            out[pk] = {**x, "status": st, "note": note, "only": x["n"] if st == "trace" else 0, "guessed": guess[:6]}
            continue
        keep, to = [], set()
        for l, n in sorted(x["lines"].items()):
            at = [r for r in recs if r[0] <= l <= r[1]] if l else recs
            cs = ctor_classes(index, at, callee)
            if cs:
                move(caller, cs, l, callee, n, x["a"])
                to.update(cs)
                continue
            st, note = ("both", None) if local else judge(at, callee, whole=not l, fn=recs, line=l, prop=prop)
            keep.append({"l": l, "n": n, "status": st, "note": note})
        if keep:
            out[pk] = {**x, "n": sum(y["n"] for y in keep), "lines": keep,
                       "only": sum(y["n"] for y in keep if y["status"] == "trace"), "guessed": None}
        elif len(to) == 1:
            moved[pk] = to.pop()
    for pk, y in built.items():
        caller, _, c = pk.partition("|")
        b = node_unit(index, c)
        if None in y["lines"]:
            per = y["lines"][None]
            guess = sorted({r[0] for r in by.get(base_node(caller), []) if r[2] == c and r[4] == _graph.NEW})
            out[pk] = {"a": y["a"], "b": b, "n": max(per.values()), "lines": None, "only": 0, "guessed": guess[:6],
                       "status": "both", "note": {"k": "ctor", "via": sorted(per)}}
        else:
            ls = [{"l": l, "n": max(per.values()), "status": "both", "note": {"k": "ctor", "via": sorted(per)}}
                  for l, per in sorted(y["lines"].items())]
            out[pk] = {"a": y["a"], "b": b, "n": sum(z["n"] for z in ls), "lines": ls, "only": 0, "guessed": None}
    return out, moved


def _is_prop(sym: dict | None) -> bool:
    """符号是 property 这类（读、写属性就是调它）：装饰器名以 property 结尾，或者是 setter / deleter"""
    return any(x.endswith("property") or x in ("setter", "deleter") for x in (sym or {}).get("d") or ())


def node_unit(index: dict, key: str) -> str | None:
    """graph 的节点落在哪个单元：符号键看符号表；<文件>#<module>、<外层>.<L行> 看文件"""
    syms = index.get("symbols") or {}
    s = syms.get(base_node(key))
    return (index.get("files") or {}).get(s["f"] if s else key.partition("#")[0])


def scan_edges_on_cut(index: dict, node_of: dict) -> dict[str, int]:
    """切面上节点之间的 scan 边："A|B" → 底下定下了被调方的调用处有几个（graph.json 的 calls）"""
    g = index.get("graph") or {}
    C, units, out = g.get("callees") or [], {}, {}

    def nd(key):
        if key not in units:
            u = node_unit(index, key)
            units[key] = node_of.get(u) if u else None
        return units[key]
    for caller, xs in (g.get("calls") or {}).items():
        a = nd(caller)
        if a is None:
            continue
        for i, _, _, _ in xs:
            b = nd(C[i])
            if b is not None and b != a:
                out[f"{a}|{b}"] = out.get(f"{a}|{b}", 0) + 1
    return out


def hot_on_cut(hot: dict, node_of: dict) -> tuple[dict, dict, dict]:
    """一个 run 按切面汇总：(节点 → 次数, "A|B" 节点间的边 → 调用次数, "A|B" → 其中「只有 trace」的次数)"""
    hp: dict[str, int] = {}
    for u, n in hot["packages"].items():
        if u in node_of:
            hp[node_of[u]] = hp.get(node_of[u], 0) + n
    he: dict[str, int] = {}
    hd: dict[str, int] = {}
    for x in (hot.get("calls") or {}).values():
        a, b = node_of.get(x["a"]), node_of.get(x["b"])
        if a and b and a != b:
            kk = f"{a}|{b}"
            he[kk] = he.get(kk, 0) + x["n"]
            if x["only"]:
                hd[kk] = hd.get(kk, 0) + x["only"]
    return hp, he, hd


# ---------------------------------------------------------------- 3 只有 trace 的调用的线索

def wiring(index: dict, callee: str) -> dict | None:
    """被调的（或者它所在的类）在仓库里哪些字符串里按名字出现过（scan 的 name_refs）——注册表
    {"Arch": ("pkg", "mod", "Cls")}、getattr(mod, "Cls")、插件表里的 "pkg.mod.Cls"：调用方和它之间看不出关系时，
    接线多半就在这几行。{refs: [{f, l, exact}], n, same_name}：带模块的类路径只认模块对得上的（exact）；只有类名的，
    同一个文件里挨着的几行（注册表的键和元组里的类名）只留第一行；same_name > 1 时仓库里有同名类、这些字符串不一定指它。
    没有（老的 index 没有 name_refs、不是类也不在类里、没人提到）是 None"""
    refs_by = index.get("name_refs")
    syms = index.get("symbols") or {}
    path, _, q = base_node(callee).partition("#")
    parts = q.split(".")
    cls_key = next((f"{path}#{'.'.join(parts[:i])}" for i in range(len(parts), 0, -1)
                    if (syms.get(f"{path}#{'.'.join(parts[:i])}") or {}).get("k") == "class"), None)
    if refs_by is None or cls_key is None:
        return None
    name, mod = _last(cls_key), syms[cls_key].get("m")
    same = sum(1 for x in syms.values() if x["k"] == "class" and x["n"].rsplit(".", 1)[-1] == name)
    kept: list[dict] = []
    for ref in sorted(refs_by.get(name) or [], key=lambda r: (r[0], r[1])):   # scan 按 ast.walk 的顺序收的
        f, l, exact = ref[0], ref[1], len(ref) > 2
        if exact and ref[2] != mod:
            continue                                 # 别的模块里的同名类
        if kept and kept[-1]["f"] == f and 0 <= l - kept[-1]["l"] <= 3:
            if exact and not kept[-1]["exact"]:     # 同一处登记：留带模块的那一行
                kept[-1] = {"f": f, "l": l, "exact": True}
            continue
        kept.append({"f": f, "l": l, "exact": exact})
    if not kept:
        return None
    kept.sort(key=lambda r: not r["exact"])          # 带模块的（没有歧义）排前面
    return {"cls": cls_key, "refs": kept[:6], "n": len(kept), "same_name": same}
