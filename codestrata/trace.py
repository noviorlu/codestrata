"""运行时 hook：跑一个真实 case，记下实际发生的调用。

hot 图和总图共用节点与坐标，差别只在数据来源：总图是 ast，hot 图是这里。

四个必须处理的现实问题：

1. **多进程。** vLLM / vllm-omni 这类框架会 fork 出一堆工作进程（每个 stage 一个
   engine core），只 trace 父进程会丢掉最关键的部分。做法是往 PYTHONPATH 前面插一个
   临时目录、里面放 sitecustomize.py：**每个**新起的 Python 进程都会自动 import 它，
   于是自动挂上 hook，按 pid 各写一份，最后合并。子进程不一定跑 atexit
   （multiprocessing 的 fork 子进程以 os._exit 结束），所以另外拦截 os._exit、并每
   10 秒落一次盘；fork 后子进程的计数清零，免得重复计入父进程的调用。

2. **开销。** sys.setprofile 对每次调用都回调，跑大框架会慢到不可用。Python 3.12+ 用
   sys.monitoring：仓库外的代码第一次命中就返回 DISABLE，之后不再回调，开销低一个量级。
   老版本退回 setprofile。

3. **调用者要对。** 要知道「谁调了谁」就得维护调用栈：进（PY_START / PY_RESUME）和出
   （PY_RETURN / PY_YIELD / PY_UNWIND）都要订阅。只订阅 PY_START 的话，调用者会变成
   「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。

4. **启动和请求要分开。** 起一个服务再发请求时，启动阶段的初始化会淹没请求本身。
   case 可以分阶段：往 $CODESTRATA_OUT/PHASE 写阶段名（如服务就绪后写 serving），
   之后用 `--hot 名字@serving` 只看那一段。

产出 trace-<case>.json：

    {"case": "...", "cmd": [...], "pids": [...], "file_shas": {...},
     "funcs":      {"<relfile>:<firstlineno>": 次数},      # 模块顶层记为 <relfile>:0
     "func_edges": {"<调用方>|<被调方>": 次数},              # 函数粒度，真正的 caller→callee
     "file_edges": {"<relfileA>|<relfileB>": 次数}}          # 由 func_edges 派生
叠图用的单元（文件）粒度数据由 to_package_graph() 在加载时现算，因为它依赖当前的 index。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_ROOT = "CODESTRATA_ROOT"
ENV_OUT = "CODESTRATA_OUT"
ENV_PKGS = "CODESTRATA_PKGS"      # "顶层包=仓库内目录;..."，把安装包里的代码映射回仓库

# ---------------------------------------------------------------- 被注入的一侧

_SITECUSTOMIZE = '''\
# codestrata 自动注入。每个 Python 进程 import 它来挂上调用 hook。
import os, sys, atexit, json, threading

_root = os.environ.get("CODESTRATA_ROOT")
_out = os.environ.get("CODESTRATA_OUT")
if _root and _out:
    _root = os.path.realpath(_root)
    _funcs = {}          # "rel:firstlineno" -> 被调次数（模块顶层是 "rel:0"）
    _fedges = {}         # "调用者key|被调者key" -> 次数（函数粒度，真正的 caller→callee）
    _mapped = {}         # 从安装包映射回仓库的文件：rel -> 实际执行的路径
    _tls = threading.local()
    _relc = {}
    # 被 trace 的常常是 pip 装进 site-packages 的那份，而不是仓库里的源码。
    # 顶层包名 → 它在仓库里的目录（src-layout 下是 src/pkg）
    _pkgs = dict(x.split("=", 1) for x in os.environ.get("CODESTRATA_PKGS", "").split(";") if "=" in x)

    def _rel(code):
        # 只记仓库内的代码，仓库外（stdlib、torch…）一律忽略。
        # 缓存必须按文件名、不能按 code 对象：code 对象按内容比较相等且不比 co_filename，
        # 两个空 __init__.py、或不同文件里同名同行同体的小函数会撞成同一个键。
        fn = code.co_filename
        r = _relc.get(fn, 0)
        if r != 0:
            return r
        r = None
        if fn and fn[0] == "/":
            try:
                rp = os.path.realpath(fn)
            except OSError:
                rp = ""
            if rp.startswith(_root + os.sep):
                r = rp[len(_root) + 1:]
            elif _pkgs:
                for sp in ("/site-packages/", "/dist-packages/"):
                    i = rp.find(sp)
                    if i >= 0:
                        tail = rp[i + len(sp):]
                        top = tail.split("/", 1)[0]
                        if top in _pkgs:
                            r = _pkgs[top] + tail[len(top):]
                            _mapped[r] = rp
                        break
        _relc[fn] = r
        return r

    def _stack():
        s = getattr(_tls, "s", None)
        if s is None:
            s = _tls.s = []
        return s

    def _key(code, rel):
        # 模块顶层记成第 0 行：模块 code 的 firstlineno 是 1，会和写在第 1 行的函数撞键
        return rel + ":" + ("0" if code.co_name == "<module>" else str(code.co_firstlineno))

    def _enter(code, count):
        rel = _rel(code)
        if rel is None:
            return False
        k = _key(code, rel)
        st = _stack()
        if count:
            _funcs[k] = _funcs.get(k, 0) + 1
            if st and st[-1] != k:                 # 递归自调用不算边
                ek = st[-1] + "|" + k
                _fedges[ek] = _fedges.get(ek, 0) + 1
        st.append(k)
        if len(st) > 2000:                          # 失配时的兜底
            del st[:1000]
        return True

    def _leave(code):
        rel = _rel(code)
        if rel is None:
            return False
        k = _key(code, rel)
        st = _stack()
        # 正常情况栈顶就是自己；若因仓库外的帧打乱了顺序，就弹到自己为止
        if st and st[-1] == k:
            st.pop()
        elif k in st:
            while st and st.pop() != k:
                pass
        return True

    # 阶段：被 trace 的命令往 $CODESTRATA_OUT/PHASE 写一个名字（比如服务就绪后写 serving），
    # 每个进程在 1 秒内看到它，就给切换前的累计计数拍一张快照。合并时相邻快照相减，
    # 就能把「启动时调了什么」和「处理请求时调了什么」分开。
    _phase_file = os.path.join(_out, "PHASE")
    def _read_phase():
        try:
            with open(_phase_file) as f:
                return f.read().strip() or "start"
        except OSError:
            return "start"
    _phase = [_read_phase()]
    _snaps = []

    def _snapshot(name):
        try:
            p = os.path.join(_out, "part-%d@%d-%s.json" % (os.getpid(), len(_snaps), name))
            with open(p + ".tmp", "w") as f:
                json.dump({"funcs": dict(_funcs), "func_edges": dict(_fedges)}, f)
            os.replace(p + ".tmp", p)
        except Exception:
            pass
        _snaps.append(name)

    def _dump():
        # 先拷贝再写：落盘线程和主线程并发，dict(...) 在 GIL 下是原子的。
        # 写临时文件再 rename，读的一方永远看不到写了一半的 JSON。
        try:
            os.makedirs(_out, exist_ok=True)
            p = os.path.join(_out, "part-%d.json" % os.getpid())
            data = {"pid": os.getpid(), "argv": sys.argv[:6], "funcs": dict(_funcs),
                    "func_edges": dict(_fedges), "mapped": dict(_mapped), "phase": _phase[0]}
            with open(p + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(p + ".tmp", p)
        except Exception:
            pass
    atexit.register(_dump)

    # atexit 不是总会跑：multiprocessing 的 fork 子进程以 os._exit 结束，被 SIGKILL 的
    # 进程什么都不跑。所以 (1) 拦下 os._exit 先落盘；(2) 后台线程每 10 秒落一次盘，
    # 被强杀最多丢最后 10 秒。
    _real_exit = os._exit
    def _exit_hook(code):
        _dump()
        _real_exit(code)
    os._exit = _exit_hook

    def _flusher():
        import time
        n = 0
        while True:
            time.sleep(1)
            ph = _read_phase()
            if ph != _phase[0]:
                _snapshot(_phase[0])
                _phase[0] = ph
                _dump()
            n += 1
            if n % 10 == 0:
                _dump()
    def _start_flusher():
        threading.Thread(target=_flusher, name="codestrata-flush", daemon=True).start()
    _start_flusher()

    # fork 出来的子进程继承父进程的计数，不清零就会把父进程 fork 之前的调用再算一遍；
    # 线程也不会跟着 fork 过来，落盘线程要重启。调用栈保留——子进程还会从这些帧里返回。
    def _after_fork():
        _funcs.clear()
        _fedges.clear()
        del _snaps[:]             # fork 之前的阶段属于父进程
        _start_flusher()
    os.register_at_fork(after_in_child=_after_fork)

    _mon = getattr(sys, "monitoring", None)
    if _mon is not None:
        # Python 3.12+。必须同时订阅进出：只订阅 PY_START 不出栈的话，「调用者」会
        # 变成「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。
        E = _mon.events
        _TID = None
        # 3、4 号没有分配给标准工具；PROFILER_ID 留给 cProfile（3.12 起它也走 sys.monitoring），
        # 占了它，被 trace 的程序里一用 cProfile 就会报「tool id 已被占用」
        for tid in (4, 3, _mon.PROFILER_ID):
            try:
                _mon.use_tool_id(tid, "codestrata")
                _TID = tid
                break
            except Exception:
                continue
        if _TID is not None:
            D = _mon.DISABLE
            def _on_start(code, off):
                return None if _enter(code, True) else D
            def _on_resume(code, off):               # 生成器/协程恢复：入栈但不算一次调用
                return None if _enter(code, False) else D
            def _on_return(code, off, val):          # PY_RETURN / PY_YIELD：出栈
                return None if _leave(code) else D
            def _on_unwind(code, off, exc):          # 异常展开出帧。这个事件不能 DISABLE
                _leave(code)
            _mon.register_callback(_TID, E.PY_START, _on_start)
            _mon.register_callback(_TID, E.PY_RESUME, _on_resume)
            _mon.register_callback(_TID, E.PY_RETURN, _on_return)
            _mon.register_callback(_TID, E.PY_YIELD, _on_return)
            _mon.register_callback(_TID, E.PY_UNWIND, _on_unwind)
            _mon.set_events(_TID, E.PY_START | E.PY_RESUME | E.PY_RETURN
                            | E.PY_YIELD | E.PY_UNWIND)
    else:
        def _prof(frame, event, arg):
            if event == "call":
                _enter(frame.f_code, True)
            elif event == "return":
                _leave(frame.f_code)
        sys.setprofile(_prof)
        threading.setprofile(_prof)
'''


def _make_bootstrap(root: Path, outdir: Path) -> Path:
    d = Path(tempfile.mkdtemp(prefix="codestrata-boot-"))
    (d / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return d


# ---------------------------------------------------------------- 驱动的一侧

def run(root: Path, cmd: list[str], case: str,
        outdir: Path | None = None, timeout: float | None = None,
        pkgs: dict[str, str] | None = None) -> dict:
    """在 hook 下跑一条命令，返回合并后的 trace。

    cmd 就是你平时怎么跑那个 case，比如
        ["python", "examples/online_serving/minicpmo/realtime_duplex_demo.py", "--input-wav", "..."]
    子进程会一并被 trace。

    pkgs 是 {顶层包名: 它在仓库里的目录}。命令跑的若是 pip 装进 site-packages 的那份，
    靠它把执行路径映射回仓库文件；映射过的文件会逐个比对内容，不一致就报出来——
    那时 hot 图的行号不可信。
    """
    root = root.resolve()
    outdir = outdir or (root / ".codestrata")
    parts = outdir / f"parts-{case}"
    if parts.exists():
        for f in list(parts.glob("part-*.json")) + list(parts.glob("part-*.json.tmp")):
            f.unlink()
        (parts / "PHASE").unlink(missing_ok=True)
    parts.mkdir(parents=True, exist_ok=True)

    boot = _make_bootstrap(root, parts)
    env = dict(os.environ)
    env[ENV_ROOT] = str(root)
    env[ENV_OUT] = str(parts)
    if pkgs:
        env[ENV_PKGS] = ";".join(f"{k}={v}" for k, v in pkgs.items())
    env["PYTHONPATH"] = str(boot) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    print(f"[codestrata] 跑 case {case!r}: {' '.join(cmd)}", file=sys.stderr)
    print(f"[codestrata] hook 已注入 PYTHONPATH（子进程一并 trace）", file=sys.stderr)
    rc = -1
    try:
        rc = subprocess.call(cmd, cwd=str(root), env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[codestrata] 超时 {timeout}s，用已收集到的数据", file=sys.stderr)
    except KeyboardInterrupt:
        print("[codestrata] 被中断，用已收集到的数据", file=sys.stderr)

    tr = merge(parts, case=case, cmd=cmd, returncode=rc)
    rels = {k.rpartition(":")[0] for k in tr["funcs"]}
    tr["file_shas"] = file_shas(root, rels)
    if tr["mapped"]:
        # 实际执行的安装包文件 vs 仓库里的同名文件
        import hashlib
        bad, extra = [], []
        for rel, real in tr["mapped"].items():
            if not (root / rel).is_file():
                # 仓库里本来就没有：构建时生成的文件（setuptools_scm 的 _version.py 之类），
                # 不是「不一致」，也不会出现在图上
                extra.append(rel)
                continue
            try:
                a = hashlib.sha256(Path(real).read_bytes()).hexdigest()[:16]
            except OSError:
                a = "?"
            if a != tr["file_shas"].get(rel):
                bad.append(rel)
        tr["mapped_mismatch"] = sorted(bad)
        tr["mapped_only_installed"] = sorted(extra)
        where = os.path.commonpath(list(tr["mapped"].values()))
        tr["mapped_from"] = where
        print(f"[codestrata] 运行的是安装包 {where}，已映射回仓库 {len(tr['mapped'])} 个文件，"
              + (f"其中 {len(bad)} 个和仓库内容不一致——这些文件的行号不可信" if bad
                 else "内容与仓库逐文件一致")
              + (f"（另有 {len(extra)} 个只在安装包里：{', '.join(extra[:3])}）" if extra else ""),
              file=sys.stderr)
    return tr


def merge(parts: Path, *, case: str, cmd: list[str] | None = None,
          returncode: int | None = None) -> dict:
    """把各进程写的 part-*.json 合并。"""
    funcs: dict[str, int] = {}
    fedges: dict[str, int] = {}
    mapped: dict[str, str] = {}
    pids: list[dict] = []
    phases: dict[str, dict] = {}
    for f in sorted(parts.glob("part-*.json")):
        if "@" in f.name:                      # 阶段快照，下面按进程处理
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 这个进程的各阶段 = 相邻两次累计快照之差；最后一段到进程退出为止
        seq = []
        for s in sorted(parts.glob(f"part-{d.get('pid')}@*.json"),
                        key=lambda p: int(p.name.split("@")[1].split("-")[0])):
            try:
                sd = json.loads(s.read_text(encoding="utf-8"))
            except Exception:
                continue
            seq.append((s.name.split("@", 1)[1][:-5].split("-", 1)[1], sd["funcs"], sd["func_edges"]))
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
        pids.append({"pid": d.get("pid"), "argv": d.get("argv"),
                     "n_funcs": len(d.get("funcs") or {})})
        for k, v in (d.get("funcs") or {}).items():
            funcs[k] = funcs.get(k, 0) + v
        for k, v in (d.get("func_edges") or {}).items():
            fedges[k] = fedges.get(k, 0) + v
        mapped.update(d.get("mapped") or {})
    # 文件粒度的边由函数粒度派生（跨文件的才算）
    edges: dict[str, int] = {}
    for k, v in fedges.items():
        a, _, b = k.partition("|")
        fa, fb = a.rpartition(":")[0], b.rpartition(":")[0]
        if fa != fb:
            ek = f"{fa}|{fb}"
            edges[ek] = edges.get(ek, 0) + v
    return {"case": case, "cmd": cmd or [], "returncode": returncode,
            "pids": pids, "n_procs": len(pids),
            "funcs": funcs, "func_edges": fedges, "file_edges": edges, "mapped": mapped,
            # 只有一个阶段时不存：它就等于总数
            "phases": phases if len(phases) > 1 else {}}


def file_shas(root: Path, rels) -> dict:
    """runtime 数据和解读一样会腐烂：trace 以 file:行号 为键，代码一改就对不上。
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


def to_package_graph(trace: dict, index: dict) -> dict:
    """把函数粒度的 trace 折算到单元（文件）粒度，payload 再按切面汇总叠到图上；同时保留
    每条单元间边上「谁调了谁」的明细，给点开箭头时用。

    返回 {"packages": {pkg: hits}, "edges": {"a|b": 调用次数},
          "symbols": {symbol_key: hits},
          "edge_calls": {"a|b": {被调符号: {n, f, l, callers: {调用方: {n, f, l}}}}},
          "edge_import_exec": {"a|b": import 触发的模块执行次数},
          "module_exec": [顶层代码执行过的文件], "unmapped": n}
    """
    files = index.get("files") or {}
    symbols = index.get("symbols") or {}
    # (file, firstlineno) → symbol key。装饰过的函数 co_firstlineno 指向第一个装饰器，
    # 所以 def 行和装饰器行都建索引。
    loc2sym: dict[tuple[str, int], str] = {}
    for key, s in symbols.items():
        loc2sym.setdefault((s["f"], s["l"]), key)
        if "dl" in s:
            loc2sym.setdefault((s["f"], s["dl"]), key)

    pkg_hits: dict[str, int] = {}
    sym_hits: dict[str, int] = {}
    # 映射不到命名符号的调用分两类，都是正常现象、不是丢数据：
    #   module  —— 第 0 行（老 trace 是第 1 行），即 import 时的模块级执行（<module> 帧）
    #   anon    —— 闭包、lambda、生成器表达式，本来就没有自己的符号
    module_frames = anon = 0
    for k, n in trace["funcs"].items():
        rel, _, ln = k.rpartition(":")
        try:
            lineno = int(ln)
        except ValueError:
            continue
        pkg = files.get(rel)
        sk = None if lineno == 0 else loc2sym.get((rel, lineno))
        if sk:
            sym_hits[sk] = sym_hits.get(sk, 0) + n
        elif lineno <= 1:
            module_frames += n
            continue                    # 只被 import 过的包不算「跑到了」
        else:
            anon += n
        if pkg:
            pkg_hits[pkg] = pkg_hits.get(pkg, 0) + n

    # 没有名字的帧（闭包、lambda、生成器表达式）归到包住它的最内层命名符号，
    # 标成 外层符号.<L行号>，这样面板上能说「scan() 里的某个闭包调了它」。
    spans: dict[str, list] = {}
    for key, s in symbols.items():
        if s.get("e"):
            spans.setdefault(s["f"], []).append((s.get("dl", s["l"]), s["e"], key))

    def label(rel: str, ln: int) -> tuple[str, int]:
        sk = None if ln == 0 else loc2sym.get((rel, ln))
        if sk:
            return sk, symbols[sk]["l"]
        if ln <= 1:
            return f"{rel}:<module>", 1
        inner = max((sp for sp in spans.get(rel, ()) if sp[0] <= ln <= sp[1]),
                    key=lambda sp: sp[0], default=None)
        return (f"{inner[2]}.<L{ln}>" if inner else f"{rel}:{ln}"), ln

    # 包间的 runtime 边和函数粒度的明细从同一份 func_edges 算，两边的数字才对得上。
    # 被调方是 <module> 帧的不算调用——那是 import 语句触发的模块顶层执行，
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
        if lb_i == 0 or (lb_i == 1 and (fb, 1) not in loc2sym):
            import_exec[ek] = import_exec.get(ek, 0) + n
            continue
        edge_hits[ek] = edge_hits.get(ek, 0) + n
        (callee, cl), (caller, rl) = label(fb, lb_i), label(fa, la_i)
        slot = edge_calls.setdefault(ek, {}).setdefault(
            callee, {"n": 0, "f": fb, "l": cl, "callers": {}})
        slot["n"] += n
        c = slot["callers"].setdefault(caller, {"n": 0, "f": fa, "l": rl})
        c["n"] += n

    # 哪些模块的顶层代码真的执行过——用来判断「副作用 import」是否在 runtime 生效了
    module_exec = sorted({k.rpartition(":")[0] for k in trace["funcs"]
                          if k.endswith(":0") or (k.endswith(":1")
                              and (k.rpartition(":")[0], 1) not in loc2sym)})
    file_hits: dict[str, int] = {}
    for k, n in trace["funcs"].items():
        rel, _, ln = k.rpartition(":")
        if rel in files and ln not in ("0",) and not (ln == "1" and (rel, 1) not in loc2sym):
            file_hits[rel] = file_hits.get(rel, 0) + n
    return {"packages": pkg_hits, "edges": edge_hits, "symbols": sym_hits, "files": file_hits,
            "edge_calls": edge_calls, "edge_import_exec": import_exec,
            "module_exec": module_exec,
            "module_frames": module_frames, "anon": anon,
            "unmapped": module_frames + anon}
