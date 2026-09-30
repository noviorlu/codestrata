"""录制之外的分析：录之前解析 `--phase` 的函数，录完之后合并各进程的分片、折算到当前的 index。
都是纯数据处理，在任何系统上都能跑（查看在 Linux 上录好的 run 也要用）。

每次录制写进 runs.new_run 建的 run 目录（见 runs.py）。各进程的分片：

    part-<pid>-<t0ns>.json    {pid, ppid, argv, t0, t, why, py, phase,
                               funcs:      {"<relfile>:<firstlineno>": 次数},  # 模块顶层记为 <relfile>:0
                               func_edges: {"<调用方>|<被调方>": 次数},          # 函数粒度，真正的 caller→callee
                               names:      {"<relfile>:<firstlineno>": qualname}, mapped: {...}}
    part-<pid>-<t0ns>@<n>-<阶段>.json    切阶段时的累计快照
merge() 把它们合成各阶段的计数；叠图用的单元（文件）粒度数据由 to_package_graph() 在
加载时现算，因为它依赖当前的 index。
"""
from __future__ import annotations

import json
import re
from pathlib import Path



PHASE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def fired_phases(parts: Path, mono0_ns: int | None, files: dict[str, bytes] | None = None,
                 sh: bool = False) -> list[tuple]:
    """hook 按 --phase 切的阶段：parts/PHASE-<名字>.fired 里的「hook pid monotonic_ns」→
    [(名字, t_us, "hook")]，t_us 相对 mono0_ns。sh=True 时 driver 替 case 脚本建的（「sh pid
    monotonic_ns」，每个名字第一次出现的时刻）也要，来源记 sh——driver 死在收尾之前、run.json 里
    没有轮询记下的 phase_log 时，runs merge 靠它把 case 脚本切的阶段时刻补回来。
    files 给了就从它读（{文件名: 内容}）。"""
    if files is None:
        files = {}
        try:
            for f in parts.iterdir():
                if f.name.startswith("PHASE-") and f.name.endswith(".fired"):
                    try:
                        files[f.name] = f.read_bytes()
                    except OSError:
                        pass
        except OSError:
            return []
    out = []
    for fn, raw in files.items():
        name = fn[len("PHASE-"):-len(".fired")]
        w = raw.decode("utf-8", "replace").split()
        src = w[0] if w and w[0] in ("hook", "sh") else "hook"
        if not PHASE_NAME_RE.match(name) or (w and w[0] not in ("hook", "sh")) or (src == "sh" and not sh):
            continue
        try:
            t = (int(w[2]) - mono0_ns) // 1000 if mono0_ns is not None else None
        except (IndexError, ValueError):
            t = None                                 # 赢家建了标记还没写进内容就死了：时刻不知道
        out.append((name, None if t is None else max(0, t), src))
    return sorted(out, key=lambda x: (x[1] is None, x[1] or 0))


def merge_phase_log(polled: list, fired: list) -> list[list]:
    """driver 轮询到的 [(名字, t_us[, 来源])] 和标记里的阶段合成 phase_log：
    [[名字, t_us, 来源]]，来源 start / sh（case 脚本写的）/ hook（--phase）。hook 的以标记为准
    （时刻精确，轮询漏掉的也补上）；标记里的 sh 只补轮询记录里没有的名字；按时刻排，时刻不知道的排最后。"""
    hook = {n: t for n, t, src in fired if src == "hook"}
    out = []
    for e in polled or []:
        name, t = e[0], e[1]
        src = e[2] if len(e) > 2 else ("start" if not out and name == "start" else "sh")
        if src == "hook" and name in hook:
            continue
        out.append([name, t, src])
    out += [[n, t, "hook"] for n, t in hook.items()]
    have = {e[0] for e in out}
    out += [[n, t, "sh"] for n, t, src in fired if src == "sh" and n not in have]
    return sorted(out, key=lambda e: (e[1] is None, e[1] if e[1] is not None else 0))


def _globals_in(fn) -> set[str]:
    """函数体里 global 声明的名字（不算嵌套的 def / class / lambda 里的）。"""
    import ast
    out: set[str] = set()
    todo = list(fn.body)
    while todo:
        n = todo.pop()
        if isinstance(n, ast.Global):
            out.update(n.names)
        elif not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(n))
    return out


def _qualnames(path: Path) -> dict[str, tuple[int, int]]:
    """一个 .py 文件里所有函数的 co_qualname → (def 行, 第一个装饰器的行)，同名的取最后一个
    （@overload 的空壳在前、真正执行的在后）。和编译器的规则一致：
    函数里定义的东西带 .<locals>.；外层函数里 global 声明过的名字不带前缀；if / for / while / with /
    try / match 这些语句体里的 def 也算（和 scan 下潜的是同一批语句）。"""
    import ast
    from ..scan import STMT_CONTAINERS
    tree = ast.parse(path.read_bytes())
    out: dict[str, tuple[int, int]] = {}

    def walk(body, prefix, globs):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = n.name if n.name in globs else prefix + n.name
                dl = min([d.lineno for d in n.decorator_list] + [n.lineno])
                out[q] = (n.lineno, dl)
                walk(n.body, q + ".<locals>.", _globals_in(n))
            elif isinstance(n, ast.ClassDef):
                walk(n.body, (n.name if n.name in globs else prefix + n.name) + ".", set())
            elif isinstance(n, STMT_CONTAINERS) or type(n).__name__ == "Match":
                for f in ("body", "orelse", "finalbody", "handlers", "cases"):
                    walk(getattr(n, f, None) or [], prefix, globs)
    walk(tree.body, "", set())
    return out


def resolve_phase_at(root: Path, specs: list[str], symbols: dict | None) -> list[dict]:
    """--phase 名字=函数 → [{name, func, file, qualname, line, dl, via}]。函数两种写法：
      模块:qualname         vllm_omni.entrypoints.omni:Omni.generate（查静态索引；类上没有的
                            方法按 MRO 顺着基类找，找到的是 OmniBase.close 就按它认；嵌套函数
                            写 outer.inner 或 outer.<locals>.inner 都行）
      文件路径:qualname      examples/offline_inference/minicpmo/end2end.py:main（不在索引里的
                            文件也行，直接读源码核对；要写定义它的那个类）
    qualname 一律换成解释器里的 co_qualname（hook 按它认）。解析不了就 SystemExit，给出可能想写的。"""
    out: list[dict] = []
    seen: set[str] = set()
    for spec in specs:
        name, sep, func = spec.partition("=")
        name, func = name.strip(), func.strip()
        if not sep or not name or not func:
            raise SystemExit(f"--phase 要写成 名字=函数：{spec!r}")
        if not PHASE_NAME_RE.match(name) or name == "start":
            raise SystemExit(f"--phase 的阶段名只能用字母、数字和 . _ -，也不能叫 start（那是第一段的名字）：{name!r}")
        if name in seen:
            raise SystemExit(f"--phase 的阶段名重复了：{name}")
        seen.add(name)
        where, sep, q = func.rpartition(":")
        if not sep or not where or not q:
            raise SystemExit(f"--phase {name}= 后面要写成 模块:qualname 或 文件路径:qualname：{func!r}")
        via = None
        if where.endswith(".py") or "/" in where:
            p = Path(where) if Path(where).is_absolute() else root / where
            try:
                p = p.resolve()
                rel = str(p.relative_to(root.resolve()))
            except (OSError, ValueError):
                raise SystemExit(f"--phase {name}：{where} 不在仓库 {root} 里")
            if not p.is_file():
                raise SystemExit(f"--phase {name}：没有这个文件 {where}")
            try:
                qs = _qualnames(p)
            except SyntaxError as e:
                raise SystemExit(f"--phase {name}：{where} 解析不了（{e}）")
            if q not in qs:
                near = [x for x in qs if x.rsplit(".", 1)[-1] == q.rsplit(".", 1)[-1]][:5]
                raise SystemExit(f"--phase {name}：{where} 里没有 {q}" + (f"；是不是 {'、'.join(near)}" if near else ""))
            line, dl = qs[q]
        else:
            if symbols is None:
                raise SystemExit(f"--phase {name}：模块:qualname 的写法要查静态索引，先 codestrata scan；"
                                 f"或者写成 文件路径:qualname")
            path = _module_paths(symbols).get(where)            # 命令行写模块名，索引的键是 <路径>#<限定名>
            s = symbols.get(f"{path}#{q.replace('.<locals>', '')}") if path else None   # 索引里嵌套的名字不带 .<locals>
            if s is None or s.get("k") != "func":
                s, via = _inherited(symbols, where, q.replace(".<locals>", ""))
            if s is None:
                last = q.rsplit(".", 1)[-1]
                near = [_human(v) for v in symbols.values() if v.get("k") == "func" and v["n"].rsplit(".", 1)[-1] == last][:6]
                raise SystemExit(f"--phase {name}：静态索引里没有函数 {where}:{q}"
                                 + (f"；同名的有：{'、'.join(near)}" if near else ""))
            if isinstance(s, str):                   # _inherited 说不准（基类不在仓库里）：给出原因
                raise SystemExit(f"--phase {name}：{s}")
            rel, q, line, dl = s["f"], s["n"], s["l"], s.get("dl") or s["l"]
            try:                                     # 换成解释器里的名字：嵌套的要带 .<locals>.
                qs = _qualnames(root / rel)
                cand = [x for x in qs if x.replace(".<locals>", "") == q]
                if cand:                             # 行号用索引的（它指着真正的定义）
                    q = cand[0]
            except (OSError, SyntaxError, ValueError):
                pass
        out.append({"name": name, "func": func, "file": rel, "qualname": q, "line": line, "dl": dl, "via": via})
    by: dict = {}
    for t in out:                                    # hook 按 (文件, qualname) 认：两个阶段指到同一个函数只有一个会切
        other = by.setdefault((t["file"], t["qualname"]), t)
        if other is not t:
            raise SystemExit(f"--phase {other['name']} 和 {t['name']} 指向同一个函数 {t['qualname']}（{t['file']}；"
                             "子类继承来的方法也是同一份代码）——一个函数只能用来切一个阶段")
    return out


def _module_paths(symbols: dict) -> dict[str, str]:
    """点分模块名 → 文件路径（从符号表里来：--phase 写的是模块名）"""
    return {v["m"]: v["f"] for v in symbols.values() if v.get("m")}


def _human(s: dict) -> str:
    """给人看的写法：模块:限定名（和 --phase 的写法一致）"""
    return f"{s['m']}:{s['n']}" if s.get("m") else f"{s['f']}:{s['n']}"


# 基类里这些不会定义仓库里的方法：MRO 里碰到它们可以跳过，不算「不在仓库里、说不准」
_OPAQUE_OK = {"object", "Generic", "ABC", "Protocol"}


def _inherited(symbols: dict, mod: str, q: str) -> tuple[dict | str | None, str | None]:
    """模块:类.方法 在这个类上没定义的，按 C3 MRO 顺着基类（静态索引里记的名字）找。基类先在同一个
    模块里找，再按名字在整个索引里找（唯一才认），Base[T] 去掉下标。MRO 里先碰到仓库外的基类
    （除了 object / Generic / ABC / Protocol）就不猜，返回说明原因的字符串。
    返回 (符号, 实际定义它的类.方法，写成 模块:限定名)；找不到返回 (None, None)。"""
    cls, dot, meth = q.rpartition(".")
    if not dot:
        return None, None
    classes = {k: v for k, v in symbols.items() if v.get("k") == "class"}
    by_name: dict[str, list[str]] = {}
    for k, v in classes.items():
        by_name.setdefault(v["n"].rsplit(".", 1)[-1], []).append(k)

    def base_key(ck: str, b: str) -> str:
        b = re.sub(r"\[.*$", "", b).strip()
        last = b.rsplit(".", 1)[-1]
        same = f"{ck.partition('#')[0]}#{last}"          # 先在同一个文件里找
        if same in classes:
            return same
        cand = by_name.get(last) or []
        return cand[0] if len(cand) == 1 else "?" + last     # ? 开头：仓库外的，或者对不上唯一的

    memo: dict[str, list[str] | None] = {}

    def mro(ck: str, stack: tuple = ()) -> list[str] | None:
        if ck.startswith("?"):
            return [ck]
        if ck in memo:
            return memo[ck]
        if ck in stack:
            return None
        bases = [base_key(ck, b) for b in classes[ck].get("b") or []]
        seqs = []
        for b in bases:
            m = mro(b, stack + (ck,))
            if m is None:
                return None
            seqs.append(list(m))
        seqs.append(list(bases))
        res = [ck]
        while any(seqs):                              # C3 merge
            for sq in seqs:
                if not sq:
                    continue
                h = sq[0]
                if not any(h in other[1:] for other in seqs):
                    break
            else:
                return None                           # 不一致的继承关系（Python 自己也会报错）
            res.append(h)
            for sq in seqs:
                if sq and sq[0] == h:
                    del sq[0]
        memo[ck] = res
        return res

    path = _module_paths(symbols).get(mod)
    start = f"{path}#{cls}"
    if not path or start not in classes:
        return None, None
    order = mro(start)
    if order is None:
        return f"{mod}:{cls} 的继承关系解析不了（有环或者不一致）", None
    for ck in order[1:]:
        if ck.startswith("?"):
            if ck[1:] in _OPAQUE_OK:
                continue
            return (f"{q} 不在 {cls} 上定义，MRO 里先碰到了仓库外（或名字对不上唯一）的基类 {ck[1:]}，"
                    f"说不准实际调的是哪个；写成定义它的那个类的 模块:qualname"), None
        s = symbols.get(f"{ck}.{meth}")
        if s and s.get("k") == "func":
            return s, _human(s)
    return None, None


def case_script(run_dir: Path, cmd: list[str]) -> dict | None:
    """case 命令里的脚本（bash case.sh、python demo.py 里那个文件）：把它的内容一起存下来。
    hot 图的帮助里要能看到「这次到底跑了什么」——光一句 bash ../../trace_case.sh 看不出
    起了什么服务、跑的是哪个 demo / benchmark、带了什么参数。相对路径按命令的执行目录 run_dir 算
    （默认仓库根目录，--cwd 可以换；run.json 里的 cwd）。"""
    for a in cmd:
        if a.startswith("-"):
            continue
        p = Path(a) if Path(a).is_absolute() else run_dir / a
        try:
            if p.is_file() and p.stat().st_size < 200_000 and p.suffix in (".sh", ".bash", ".py", ".zsh", ""):
                text = p.read_text(encoding="utf-8", errors="replace")
                if p.suffix or text.startswith("#!"):
                    return {"path": a, "text": text}
        except OSError:
            continue
    return None


def merge(parts: Path) -> dict:
    """把各进程写的分片合并。两种命名都认：
      part-<pid>-<t0ns>.json、part-<pid>-<t0ns>@<n>-<阶段>.json   （现在的：一个进程映像一份）
      part-<pid>.json、part-<pid>@<n>-<阶段>.json                 （老的）
    阶段总是保留，只有一个阶段时也保留（它的名字也是信息）。

    返回 {phases: {阶段: {funcs, func_edges}}, funcs, func_edges, file_edges, names, mapped,
          shas: {rel: 进程第一次跑到它时的内容哈希}, sha_conflicts: [不同进程看到的内容不一样的文件],
          bad_parts: [读不出来的分片],
          procs: [{pid, ppid, argv, argv_cut, title, n_funcs, t0, t, why, py}]}；
    funcs / func_edges 是各阶段之和。"""
    funcs: dict[str, int] = {}
    fedges: dict[str, int] = {}
    names: dict[str, str] = {}
    mapped: dict[str, str] = {}
    procs: list[dict] = []
    phases: dict[str, dict] = {}
    shas: dict[str, str] = {}
    conflicts: set[str] = set()
    bad: list[str] = []
    for f in sorted(parts.glob("part-*.json")):
        if "@" in f.name:                      # 阶段快照，下面按进程处理
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            bad.append(f.name)
            continue
        # 这个进程的各阶段 = 相邻两次累计快照之差；最后一段到进程退出为止
        stem = f.name[:-len(".json")]
        seq = []
        for sp in sorted(parts.glob(f"{stem}@*.json"),
                         key=lambda p: int(p.name.split("@")[1].split("-")[0])):
            try:
                sd = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                bad.append(sp.name)
                continue
            seq.append((sp.name.split("@", 1)[1][:-5].split("-", 1)[1], sd["funcs"], sd["func_edges"]))
        seq.append((d.get("phase") or "start", d.get("funcs") or {}, d.get("func_edges") or {}))
        pf: dict = {}
        pe: dict = {}
        for name, fu, fe in seq:
            ph = phases.setdefault(name, {"funcs": {}, "func_edges": {}})
            for src, prev, dst in ((fu, pf, ph["funcs"]), (fe, pe, ph["func_edges"])):
                for k, v in src.items():
                    dv = v - prev.get(k, 0)
                    if dv > 0:
                        dst[k] = dst.get(k, 0) + dv
            pf, pe = fu, fe
        procs.append({"pid": d.get("pid"), "ppid": d.get("ppid"), "argv": d.get("argv"),
                      "argv_cut": bool(d.get("argv_cut")), "title": d.get("title"),
                      "n_funcs": len(d.get("funcs") or {}), "t0": d.get("t0"), "t": d.get("t"),
                      "why": d.get("why"), "py": d.get("py")})
        for rel, h in (d.get("shas") or {}).items():
            if h and shas.get(rel) not in (None, h):
                conflicts.add(rel)             # 录制中途文件改了，先后起的进程跑的不是同一份
            elif h:
                shas.setdefault(rel, h)
        for k, v in (d.get("funcs") or {}).items():
            funcs[k] = funcs.get(k, 0) + v
        for k, v in (d.get("func_edges") or {}).items():
            fedges[k] = fedges.get(k, 0) + v
        for k, v in (d.get("names") or {}).items():
            names.setdefault(k, v)
        mapped.update(d.get("mapped") or {})
    phases = phases or {"start": {"funcs": {}, "func_edges": {}}}
    # 文件粒度的边由函数粒度派生（跨文件的才算），只用来打印摘要；调用方是 case 的代码（<外部代码>/…）
    # 的不算——图上没有它，摘要里的条数要和图对得上
    edges: dict[str, int] = {}
    for k, v in fedges.items():
        a, _, b = k.partition("|")
        fa, fb = a.rpartition(":")[0], b.rpartition(":")[0]
        if fa != fb and fa[:1] != "<":
            ek = f"{fa}|{fb}"
            edges[ek] = edges.get(ek, 0) + v
    procs.sort(key=lambda p: (p["t0"] or 0, p["pid"] or 0))
    return {"phases": phases, "funcs": funcs, "func_edges": fedges, "file_edges": edges,
            "names": names, "mapped": mapped, "shas": shas, "sha_conflicts": sorted(conflicts),
            "bad_parts": sorted(bad), "procs": procs, "n_procs": len(procs)}


def file_shas(root: Path, rels) -> dict:
    """runtime 数据会腐烂：trace 以 file:行号 为键，代码一改就对不上。
    录制时记下每个涉及文件的内容哈希，加载时比对，就知道哪些叠加已经不准了。"""
    import hashlib
    out = {}
    for rel in sorted(set(rels)):
        try:
            out[rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()[:16]
        except OSError:
            out[rel] = ""
    return out


def stale_files(root: Path, trace: dict) -> list[str]:
    was = trace.get("file_shas") or {}
    now = file_shas(root, was.keys())
    return sorted(r for r in was if was[r] != now.get(r))


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
    """把函数粒度的 trace 折算到单元（文件）粒度，payload 再按切面汇总叠到图上；同时保留
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

