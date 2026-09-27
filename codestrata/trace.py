"""运行时 hook：跑一个真实 case，记下实际发生的调用。

hot 图和总图共用节点与坐标，差别只在数据来源：总图是 ast，hot 图是这里。

两个必须处理的现实问题：

1. **多进程。** vLLM / vllm-omni 这类框架会 fork 出一堆工作进程（每个 stage 一个
   engine core），只 trace 父进程会丢掉最关键的部分。做法是往 PYTHONPATH 前面插一个
   临时目录、里面放 sitecustomize.py：**每个**新起的 Python 进程都会自动 import 它，
   于是自动挂上 hook，按 pid 各写一份，最后合并。

2. **开销。** sys.setprofile 对每次调用都回调，跑大框架会慢到不可用。Python 3.12+ 的
   sys.monitoring 只订阅 PY_START 事件，开销低一个量级。这里优先用它，老版本退回
   setprofile。

产出 trace-<case>.json：

    {"case": "...", "argv": [...], "pids": [...],
     "funcs":  {"<relfile>:<firstlineno>": count},   # 函数粒度，映射到 symbols
     "edges":  {"<pkgA>|<pkgB>": count}}             # 包粒度，直接叠到总图上
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

# ---------------------------------------------------------------- 被注入的一侧

_SITECUSTOMIZE = '''\
# codestrata 自动注入。每个 Python 进程 import 它来挂上调用 hook。
import os, sys, atexit, json, threading

_root = os.environ.get("CODESTRATA_ROOT")
_out = os.environ.get("CODESTRATA_OUT")
if _root and _out:
    _root = os.path.realpath(_root)
    _funcs = {}
    _edges = {}
    _stack = threading.local()

    def _rel(fn):
        # 只记仓库内的代码；仓库外（stdlib、依赖）一律忽略
        if not fn or fn[0] != "/":
            return None
        try:
            rp = os.path.realpath(fn)
        except OSError:
            return None
        if not rp.startswith(_root + os.sep):
            return None
        return rp[len(_root) + 1:]

    def _record(rel, lineno):
        k = rel + ":" + str(lineno)
        _funcs[k] = _funcs.get(k, 0) + 1
        st = getattr(_stack, "s", None)
        if st is None:
            st = _stack.s = []
        if st:
            a = st[-1]
            if a != rel:
                ek = a + "|" + rel
                _edges[ek] = _edges.get(ek, 0) + 1
        st.append(rel)
        if len(st) > 400:            # 递归/深栈保护
            del st[:200]

    def _dump():
        try:
            os.makedirs(_out, exist_ok=True)
            p = os.path.join(_out, "part-%d.json" % os.getpid())
            with open(p, "w") as f:
                json.dump({"pid": os.getpid(),
                           "argv": sys.argv[:6],
                           "funcs": _funcs, "edges": _edges}, f)
        except Exception:
            pass
    atexit.register(_dump)

    _mon = getattr(sys, "monitoring", None)
    if _mon is not None:
        # Python 3.12+：只订阅 PY_START，开销远低于 setprofile
        _TID = _mon.PROFILER_ID
        try:
            _mon.use_tool_id(_TID, "codestrata")
        except Exception:
            _TID = 3
            try:
                _mon.use_tool_id(_TID, "codestrata")
            except Exception:
                _TID = None
        if _TID is not None:
            def _on_start(code, offset):
                rel = _rel(code.co_filename)
                if rel is not None:
                    _record(rel, code.co_firstlineno)
                return _mon.DISABLE if rel is None else None
            _mon.register_callback(_TID, _mon.events.PY_START, _on_start)
            _mon.set_events(_TID, _mon.events.PY_START)
    else:
        def _prof(frame, event, arg):
            if event == "call":
                c = frame.f_code
                rel = _rel(c.co_filename)
                if rel is not None:
                    _record(rel, c.co_firstlineno)
            elif event == "return":
                st = getattr(_stack, "s", None)
                if st:
                    st.pop()
        sys.setprofile(_prof)
        threading.setprofile(_prof)
'''


def _make_bootstrap(root: Path, outdir: Path) -> Path:
    d = Path(tempfile.mkdtemp(prefix="codestrata-boot-"))
    (d / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return d


# ---------------------------------------------------------------- 驱动的一侧

def run(root: Path, cmd: list[str], case: str,
        outdir: Path | None = None, timeout: float | None = None) -> dict:
    """在 hook 下跑一条命令，返回合并后的 trace。

    cmd 就是你平时怎么跑那个 case，比如
        ["python", "examples/online_serving/minicpmo/realtime_duplex_demo.py", "--input-wav", "..."]
    子进程会一并被 trace。
    """
    root = root.resolve()
    outdir = outdir or (root / ".codestrata")
    parts = outdir / f"parts-{case}"
    if parts.exists():
        for f in parts.glob("part-*.json"):
            f.unlink()
    parts.mkdir(parents=True, exist_ok=True)

    boot = _make_bootstrap(root, parts)
    env = dict(os.environ)
    env[ENV_ROOT] = str(root)
    env[ENV_OUT] = str(parts)
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

    return merge(parts, case=case, cmd=cmd, returncode=rc)


def merge(parts: Path, *, case: str, cmd: list[str] | None = None,
          returncode: int | None = None) -> dict:
    """把各进程写的 part-*.json 合并。"""
    funcs: dict[str, int] = {}
    edges: dict[str, int] = {}
    pids: list[dict] = []
    for f in sorted(parts.glob("part-*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        pids.append({"pid": d.get("pid"), "argv": d.get("argv"),
                     "n_funcs": len(d.get("funcs") or {})})
        for k, v in (d.get("funcs") or {}).items():
            funcs[k] = funcs.get(k, 0) + v
        for k, v in (d.get("edges") or {}).items():
            edges[k] = edges.get(k, 0) + v
    return {"case": case, "cmd": cmd or [], "returncode": returncode,
            "pids": pids, "n_procs": len(pids),
            "funcs": funcs, "file_edges": edges}


def to_package_graph(trace: dict, index: dict) -> dict:
    """把文件粒度的 trace 折算到包粒度，好直接叠在总图上。

    返回 {"packages": {pkg: hits}, "edges": {"a|b": hits},
          "symbols": {symbol_key: hits}, "unmapped": n}
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
    #   module  —— 第 1 行，即 import 时的模块级执行（<module> 帧）
    #   anon    —— lambda、生成器表达式、推导式，本来就没有名字
    module_frames = anon = 0
    for k, n in trace["funcs"].items():
        rel, _, ln = k.rpartition(":")
        try:
            lineno = int(ln)
        except ValueError:
            continue
        pkg = files.get(rel)
        if pkg:
            pkg_hits[pkg] = pkg_hits.get(pkg, 0) + n
        sk = loc2sym.get((rel, lineno))
        if sk:
            sym_hits[sk] = sym_hits.get(sk, 0) + n
        elif lineno <= 1:
            module_frames += n
        else:
            anon += n

    edge_hits: dict[str, int] = {}
    for k, n in trace["file_edges"].items():
        a, _, b = k.partition("|")
        pa, pb = files.get(a), files.get(b)
        if pa and pb and pa != pb:
            ek = f"{pa}|{pb}"
            edge_hits[ek] = edge_hits.get(ek, 0) + n
    return {"packages": pkg_hits, "edges": edge_hits, "symbols": sym_hits,
            "module_frames": module_frames, "anon": anon,
            "unmapped": module_frames + anon}
