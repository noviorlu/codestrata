"""运行时 hook：跑一个真实 case，记下实际发生的调用。

hot 图和总图共用节点与坐标，差别只在数据来源：总图是 ast，hot 图是这里。

五个必须处理的现实问题：

1. **多进程。** vLLM / vllm-omni 这类框架会 fork 出一堆工作进程（每个 stage 一个
   engine core），只 trace 父进程会丢掉最关键的部分。做法是往 PYTHONPATH 前面插一个
   临时目录、里面放 sitecustomize.py：**每个**新起的 Python 进程都会自动 import 它，
   于是自动挂上 hook，每个进程映像（pid + 起始时刻）各写一份，最后合并。子进程不一定
   跑 atexit（multiprocessing 的 fork 子进程以 os._exit 结束，exec 换程序时也不跑），
   所以另外拦截 os._exit 和 os.exec*、并每 10 秒落一次盘；fork 后子进程的计数清零，
   免得重复计入父进程的调用。

2. **开销。** sys.setprofile 对每次调用都回调，跑大框架会慢到不可用。Python 3.12+ 用
   sys.monitoring：仓库外的代码第一次命中就返回 DISABLE，之后不再回调，开销低一个量级。
   老版本退回 setprofile。

3. **调用者要对。** 要知道「谁调了谁」就得维护调用栈：进（PY_START / PY_RESUME / PY_THROW）和出
   （PY_RETURN / PY_YIELD / PY_UNWIND）都要订阅。只订阅 PY_START 的话，调用者会变成
   「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。

4. **启动和请求要分开。** 起一个服务再发请求时，启动阶段的初始化会淹没请求本身。
   两种分阶段的办法，可以一起用：case 脚本往 $CODESTRATA_OUT/PHASE 写阶段名（如服务就绪后
   写 serving）；或者 `trace --phase 名字=函数`，哪个进程第一次进入这个函数就在那一刻切过去
   （离线脚本只有一条阻塞的 python 命令，shell 看不到加载什么时候完，只能这样切）。
   之后用 `--hot 名字@serving` 只看那一段。

5. **停要停干净。** 服务类的 case 会 setsid 起服务；超时或 Ctrl+C 时直接 SIGKILL 命令，
   服务就成了孤儿、一直占着显存，最后几秒的数据也丢了。所以命令放在自己的会话里，由
   driver 按 SIGINT → SIGTERM → SIGKILL 三级停，再扫 /proc 找出还带着本次录制环境变量的
   残留进程同样停掉，最后才合并。

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
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENV_ROOT = "CODESTRATA_ROOT"
ENV_OUT = "CODESTRATA_OUT"
ENV_PKGS = "CODESTRATA_PKGS"      # "顶层包=仓库内目录;..."，把安装包里的代码映射回仓库

# ---------------------------------------------------------------- 被注入的一侧

_SITECUSTOMIZE = '''\
# codestrata 自动注入。每个 Python 进程 import 它来挂上调用 hook。
import os, sys, atexit, json, threading, time, hashlib, itertools

_root = os.environ.get("CODESTRATA_ROOT")
_out = os.environ.get("CODESTRATA_OUT")
if _root and _out:
    _root = os.path.realpath(_root)
    _funcs = {}          # "rel:firstlineno" -> 被调次数（模块顶层是 "rel:0"）
    _fedges = {}         # "调用者key|被调者key" -> 次数（函数粒度，真正的 caller→callee）
    _mapped = {}         # 从安装包映射回仓库的文件：rel -> 实际执行的路径
    _names = {}          # "rel:firstlineno" -> co_qualname（代码改了行号之后按名字找回符号用）
    _shas = {}           # rel -> 实际执行的那个文件的内容哈希（第一次跑到它时取；录制中途改了文件也认得出）
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
            if r is not None and r not in _shas:
                try:
                    with open(rp, "rb") as f:
                        _shas[r] = hashlib.sha256(f.read()).hexdigest()[:16]
                except Exception:
                    _shas[r] = ""
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

    # ---- 时序事件（CODESTRATA_EVENTS=1，只有 sys.monitoring 才有）：只记跨文件的调用，
    # 口径和 func_edges 相同（调用方是栈顶的仓库帧、和被调方不在同一个文件）。每次调用给一个
    # span 号，返回 / 挂起 / 恢复按帧（id(帧)）找回 span 号——不按栈的顺序配，所以同一线程里
    # asyncio 协程交错也配得对。日志的行格式见 events.py 开头的说明。
    _EV = os.environ.get("CODESTRATA_EVENTS") == "1" and getattr(sys, "monitoring", None) is not None
    _ev_max = 3000000
    if _EV:
        try:
            _ev_max = int(float(os.environ.get("CODESTRATA_EV_MAX") or 3000000))
        except (ValueError, OverflowError):      # 写错了（abc、inf）不能让 hook 整个失效
            pass
    _ev = []                 # 待写的事件行（落盘线程每秒写出去）
    _ev_n = [0]              # 已记的调用行数，到上限就不再记新的调用（计数不受影响）
    _ev_keys = {}            # "rel:firstlineno" -> 进程内的小整数
    # id(帧) -> (span 号, code)：跨文件进来的、还没返回的帧。连 code 一起存：半路被丢掉的生成器
    # 在 3.12 上关闭时不发任何事件，它的帧地址之后会被别的帧复用，code 对不上就知道是旧账
    _xf = {}
    _xc = set()              # 当过跨文件被调方的 code（的 id）：只有它们的返回 / 挂起 / 恢复才要查帧
    _gen = [0]               # fork 代数：线程号缓存在线程局部变量里，fork 之后要作废
    # 编号用 itertools.count：next() 在 CPython 里是原子的，多个线程同时调用不会拿到同一个号
    _ids = [itertools.count(1), itertools.count(1), itertools.count(1)]    # span、键、线程

    def _clean(x):
        return x.replace("\\n", " ").replace("\\r", " ")

    def _ev_kid(k):
        i = _ev_keys.get(k)
        if i is None:
            i = _ev_keys[k] = next(_ids[1])
            _ev.append("K %d %s" % (i, _clean(k)))
        return i

    def _ev_tid():
        # 线程号缓存在线程局部变量里（随线程一起没），不按 get_ident()：glibc 会把退出线程的
        # ident 分给下一个新线程，按它缓存的话后来的线程会顶着前一个线程的号和名字
        c = getattr(_tls, "ev", None)
        if c is not None and c[0] == _gen[0]:
            return c[1]
        i = next(_ids[2])
        _tls.ev = (_gen[0], i)
        _ev.append("N %d %s" % (i, _clean(threading.current_thread().name)))
        return i

    def _ev_room():
        # 上限只管调用（C）；返回 / 挂起 / 恢复只写已经在 _xf 里的 span，数量有界，照写——
        # 否则到上限之前开始、之后才返回的调用会显示成「到进程结束都没返回」
        if _ev_n[0] < _ev_max:
            _ev_n[0] += 1
            return True
        if _ev_n[0] == _ev_max:
            _ev_n[0] += 1
            _ev.append("T")
        return False

    def _ev_call(a, b, code):
        if not _ev_room():
            if _xf:                                    # 到了上限不再记新的调用，但这一帧的地址上的旧账还是要作废
                _xf.pop(id(sys._getframe(3)), None)
            return
        fr = id(sys._getframe(3))                      # _ev_call ← _enter ← 回调 ← 被监控的帧
        sp = next(_ids[0])
        _xf[fr] = (sp, code)                          # 同一地址已有旧账：那一帧被丢掉了，覆盖
        _xc.add(id(code))
        _ev.append("C %d %d %d %d %d" % ((time.monotonic_ns() - _t0[0]) // 1000, _ev_tid(), sp,
                                         _ev_kid(a), _ev_kid(b)))

    def _ev_mark(tag, code, end):
        fr = id(sys._getframe(3))                      # _ev_mark ← _enter / _leave ← 回调 ← 被监控的帧
        x = _xf.get(fr)
        if x is None:
            return
        if x[1] is not code:                           # 地址被别的帧复用了：旧账作废
            del _xf[fr]
            return
        if end:
            del _xf[fr]
        _ev.append("%s %d %d %d" % (tag, (time.monotonic_ns() - _t0[0]) // 1000, _ev_tid(), x[0]))

    def _enter(code, count):
        rel = _rel(code)
        if rel is None:
            return False
        k = _key(code, rel)
        st = _stack()
        if count:
            n = _funcs.get(k)
            if n is None:
                n = 0
                q = getattr(code, "co_qualname", None)      # 3.10 没有：不记（拿短名字去对会对到同名的别的函数上）
                if q:
                    _names[k] = q
                if _trig_q:                                 # 在计数之前切：触发的这次调用算进新阶段
                    n = _trig_check(code, rel, q, k, n)
            elif _trig_watch and k in _trig_watch:
                n = _trig_check(code, rel, getattr(code, "co_qualname", None), k, n)
            _funcs[k] = n + 1
            if st and st[-1] != k:                 # 递归自调用不算边
                ek = st[-1] + "|" + k
                _fedges[ek] = _fedges.get(ek, 0) + 1
                if _EV and st[-1].rpartition(":")[0] != rel:
                    _ev_call(st[-1], k, code)
                elif _EV and id(code) in _xc:
                    _xf.pop(id(sys._getframe(2)), None)   # 同文件里新起的一帧，地址上若有旧账（被丢掉的
                                                          # 同一个函数的生成器）就作废，免得它的事件记到旧 span 上
            elif _EV and id(code) in _xc:
                _xf.pop(id(sys._getframe(2)), None)
        elif _EV and id(code) in _xc:
            _ev_mark("S", code, False)                          # 生成器 / 协程恢复（含 throw 进来的）
        st.append(k)
        if len(st) > 2000:                          # 失配时的兜底
            del st[:1000]
        return True

    def _trig_check(code, rel, q, k, n):
        # 是不是 --phase 的函数：是就切阶段，返回切完之后的计数（停顿的那 0.1 s 里别的线程可能也调过
        # 它，不能拿旧值盖掉）。键是「文件:首行」，同一行上别的代码对象（默认参数里的生成器表达式、
        # 装饰器参数里的 lambda）可能先占了这个键——那之后这个键每次调用都再认一下（_trig_watch；
        # 平常是空的，热路径上只多一次空集合的判断）
        if q:
            t = _trig_q.get((rel, q))
        else:
            t = _trig_l.get((rel, code.co_firstlineno))
            t = t[0] if t and code.co_name == t[1] else None
        if t is None:
            if (rel, code.co_firstlineno) in _trig_l:
                _trig_watch.add(k)
            return n
        _trig_watch.discard(k)
        _fire(t)
        return _funcs.get(k, 0)

    def _leave(code, tag="R"):
        rel = _rel(code)
        if rel is None:
            return False
        if _EV and id(code) in _xc:
            _ev_mark(tag, code, tag == "R")                      # R：返回或异常展开；Y：挂起
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
    # 每个进程在 50 ms 内看到它，就给切换前的累计计数拍一张快照。合并时相邻快照相减，
    # 就能把「启动时调了什么」和「处理请求时调了什么」分开。文件只认第一行；hook 自己切的
    # （--phase）第二行是切换那一刻的 monotonic_ns，driver 拿它记阶段的时刻
    _phase_file = os.path.join(_out, "PHASE")
    _stop_file = os.path.join(_out, "STOP")
    def _read_phase():
        try:
            with open(_phase_file) as f:
                return f.readline().strip() or "start"
        except OSError:
            return "start"
    _phase = [_read_phase()]
    _POLL = 0.05             # 落盘线程多久看一次 PHASE
    _PAUSE = 0.1             # --phase 切换之后触发的线程停这么久：别的进程（每 _POLL 看一次）先切过去

    # --phase 名字=函数：[[名字, rel, qualname, 行号, 装饰器行号], ...]。某个进程第一次进入这个
    # 函数时切到这个阶段。按 qualname 认（录制时的安装包和仓库行号对不上也认得出）；没有
    # co_qualname 的 3.10 退回按 co_firstlineno——它是第一个装饰器的行（没装饰器就是 def 行），
    # 只登记这一行，并且短名字要对得上：同一行上默认参数里的生成器表达式、第 1 行的模块代码
    # （co_firstlineno 也是 1）都不算
    _trig_q, _trig_l, _trig_watch = {}, {}, set()
    try:
        for _t in json.loads(os.environ.get("CODESTRATA_PHASE_AT") or "[]"):
            _trig_q[(_t[1], _t[2])] = _t[0]
            _trig_l[(_t[1], _t[4] or _t[3])] = (_t[0], _t[2].rsplit(".", 1)[-1])
    except (ValueError, TypeError, IndexError, AttributeError):
        _trig_q, _trig_l = {}, {}
    _snaps = []
    # 进程（准确说是这个进程映像）起始的时刻。分片按 pid + 它命名：exec 之后同一个 pid 换了
    # 程序，新程序写新文件，不会覆盖 exec 之前的数据
    _t0 = [time.monotonic_ns()]

    def _starttime():
        # /proc/<pid>/stat 的启动时刻：driver 靠 (pid, 它) 认出还活着的本 run 进程——
        # 光看 /proc/<pid>/environ 不够，setproctitle（vLLM 的 engine core 在用）会把它清空
        try:
            with open("/proc/self/stat") as f:
                return int(f.read().rsplit(")", 1)[1].split()[19])
        except Exception:
            return None
    _st = [_starttime()]

    def _cmdline():
        try:
            with open("/proc/self/cmdline", "rb") as f:
                raw = [a.decode("utf-8", "replace") for a in f.read().split(b"\\0") if a]
        except OSError:
            raw = [sys.executable] + sys.argv
        return raw
    # 完整的命令行（解释器 + 参数；python -c 的代码也在里面），启动时读一次：之后
    # setproctitle 会把 /proc/self/cmdline 改成「VLLM::EngineCore_0」这样的标题
    _argv0 = _cmdline()
    _argv = [a[:400] for a in _argv0][:60]
    _argv_cut = len(_argv0) > 60 or any(len(a) > 400 for a in _argv0)

    # 所有落盘串行：落盘线程（periodic / phase / stop）和主线程（atexit / _exit / exec）
    # 同时写同一个文件会把 JSON 写坏。临时文件名也带上线程，互不覆盖。
    # 主线程的最后一次落盘开始后（_final），落盘线程不再写——否则一份更早拷贝的计数
    # 可能最后 rename、盖掉最终的那份
    _lock = [threading.RLock()]
    _final = [False]

    def _base():
        return os.path.join(_out, "part-%d-%d" % (os.getpid(), _t0[0]))

    def _write(p, data):
        # 目录不在就不写（不 makedirs）：录制已经收尾、parts/ 已经打包删掉之后，
        # 还活着的残留进程不能把它重新建出来
        tmp = "%s.%d.tmp" % (p, threading.get_ident())
        try:
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # 切阶段时拍下、还没写出去的快照 [(文件名, 数据)]：_fire 在被 trace 的线程里只拍（dict 拷贝，
    # 不跑 Python 字节码），写文件交给落盘线程——被 trace 的程序的信号处理器可能在 json.dump 中途
    # 抛 KeyboardInterrupt，不能在它的线程里写（更不能像 _dump 那样吞掉重来）
    _pending = []
    _want_dump = [False]

    def _flush_pending():
        # 调用方拿着 _lock
        while _pending:
            _write(*_pending[0])
            del _pending[0]

    def _snapshot(name, defer=False):
        d = ("%s@%d-%s.json" % (_base(), len(_snaps), name), {"funcs": dict(_funcs), "func_edges": dict(_fedges)})
        _snaps.append(name)
        if defer:
            _pending.append(d)
        else:
            _flush_pending()
            _write(*d)

    def _fire(name):
        # 每个阶段整个 run 只切一次。先把新的 PHASE 写进临时文件，再 O_EXCL 建标记：建成的（赢家）
        # 把 PHASE 换过去；建不成的是别的进程 / 线程刚切了这个阶段（或 case 脚本写过同名的阶段，
        # driver 替它建了标记）——PHASE 已经是它就跟着切，自己这次触发的调用也算进新阶段；已经切到
        # 后面去了的不跟，不会被切回去。只在内存里拍快照，落盘交给落盘线程（见 _pending）
        t = time.monotonic_ns()
        tmp = "%s.%d.%d.tmp" % (_phase_file, os.getpid(), threading.get_ident())
        try:
            with open(tmp, "w") as f:
                f.write("%s\\n%d\\n" % (name, t))
        except OSError:
            return                                   # parts/ 没了：录制已经收尾
        try:
            fd = os.open(os.path.join(_out, "PHASE-%s.fired" % name), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            won = True
        except FileExistsError:
            won = False
        except OSError:
            fd, won = None, None
        if won:
            try:
                os.replace(tmp, _phase_file)
            except OSError:
                pass
            try:
                os.write(fd, ("hook %d %d\\n" % (os.getpid(), t)).encode())
                os.close(fd)
            except OSError:
                pass
        else:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if won is None:
                return
            for _ in range(20):                      # 赢家在「建标记」和「换 PHASE」之间：最多等它约 2 ms
                if _read_phase() == name:
                    break
                time.sleep(0.0001)
            else:
                return
        switched = False
        with _lock[0]:
            if not _final[0] and _phase[0] != name:
                _snapshot(_phase[0], defer=True)
                _phase[0] = name
                switched = True
        if switched:
            _want_dump[0] = True
        if won:
            time.sleep(_PAUSE)

    _py = []
    def _pyinfo():
        if not _py:
            _py.append({"version": sys.version.split()[0], "executable": sys.executable,
                        "site": [p for p in sys.path if p.endswith(("site-packages", "dist-packages"))]})
        return _py[0]

    def _payload(why):
        d = {"pid": os.getpid(), "ppid": os.getppid(), "st": _st[0], "argv": _argv, "argv_cut": _argv_cut,
             "t0": _t0[0], "t": time.monotonic_ns(), "why": why, "py": _pyinfo(), "phase": _phase[0],
             "funcs": dict(_funcs), "func_edges": dict(_fedges), "names": dict(_names),
             "mapped": dict(_mapped), "shas": dict(_shas)}
        now = _cmdline()
        if now and now[0] != _argv0[0]:
            d["title"] = " ".join(now)[:200]          # setproctitle 改过的标题
        return d

    _ev_file = []

    def _ev_flush():
        # 调用方拿着 _lock。只有这个函数从 _ev 里删东西、别的线程只往尾巴上加，所以
        # 「拷前 n 个、删前 n 个」不会丢行
        n = len(_ev)
        if not n:
            return
        data = "\\n".join(_ev[:n]) + "\\n"
        name = os.path.join(_out, "ev-%d-%d.log" % (os.getpid(), _t0[0]))
        try:
            # 写成功才从缓冲里删：落盘中途被程序自己的信号处理器打断（KeyboardInterrupt），
            # _dump 重试时这些行还在。utf-8 + backslashreplace：文件名不是 UTF-8 也不丢整块
            with open(name, "a", encoding="utf-8", errors="backslashreplace") as f:
                if name not in _ev_file:
                    f.write("H %d %d %d\\n" % (os.getpid(), _t0[0], os.getppid()))
                    _ev_file.append(name)
                f.write(data)
        except OSError:
            del _ev[:n]                      # 目录没了（录制已收尾）：写不进去，丢掉
            return
        del _ev[:n]

    def _dump(why):
        # why：atexit / _exit / exec 是这个进程映像的最后一次（主线程）；periodic / phase / stop
        # 是落盘线程的。最后一次是 periodic 或 phase 的进程是被强杀的，最后几秒的数据没了；
        # stop 是 driver 升级到 SIGTERM 之前通知的那次（之后被信号停掉，数据到停之前 1 秒）
        final = why in ("atexit", "_exit", "exec")
        if final:
            _final[0] = True
            _lock[0].acquire()
        elif _final[0] or not _lock[0].acquire(blocking=False):
            return False
        try:
            # 被 trace 的程序自己的信号处理器可能在落盘中途抛 KeyboardInterrupt / SystemExit：
            # 吞掉重来，不能让它把最后一次落盘打断，更不能让它从 os._exit 里逃出去。
            # 非最后一次的落盘只在落盘线程上跑（信号处理器只在主线程跑），吞不到程序的信号
            for _ in range(3):
                try:
                    _flush_pending()
                    if _EV:
                        _ev_flush()
                    _write(_base() + ".json", _payload(why))
                    break
                except BaseException:
                    continue
        finally:
            _lock[0].release()
        return True
    atexit.register(_dump, "atexit")

    # atexit 不是总会跑：multiprocessing 的 fork 子进程以 os._exit 结束，被 SIGKILL 的
    # 进程什么都不跑，exec 换程序时也不跑。所以 (1) 拦下 os._exit 和 exec 先落盘；
    # (2) 后台线程每 10 秒落一次盘，被强杀最多丢最后 10 秒；driver 升级到 SIGTERM 之前
    # 会写 STOP 文件，落盘线程看到就立刻落一次。不装 SIGTERM 处理器：Python 层的处理器
    # 要等主线程回到解释器才跑，会让卡在 C 里的进程收到 SIGTERM 也不死（改变被 trace 的程序的行为）
    _real_exit = os._exit
    def _exit_hook(*a, **k):
        try:
            _dump("_exit")
        except BaseException:
            pass
        _real_exit(*a, **k)
    os._exit = _exit_hook

    # os.exec* 全家最后都走 execv / execve（os.py 里按模块全局名字查找，所以替换得到）
    def _wrap_exec(real):
        def _exec(*a, **k):
            try:
                _dump("exec")
            except BaseException:
                pass
            try:
                return real(*a, **k)
            finally:
                _final[0] = False             # 只有 exec 失败才会走到这里：进程接着跑
        return _exec
    os.execv = _wrap_exec(os.execv)
    os.execve = _wrap_exec(os.execve)

    def _flusher():
        # 每 _POLL 看一次 PHASE（只 stat；变了才读，另外每秒兜底读一次——同一个 inode 上
        # 同样长度的改写可能 mtime 没变），别的事照旧按秒：STOP、事件落盘，每 10 秒整份落盘
        tick, stopped, last = 0, False, None
        per_s = max(1, int(round(1 / _POLL)))
        while True:
            time.sleep(_POLL)
            tick += 1
            try:
                st = os.stat(_phase_file)
                sig = (st.st_ino, st.st_mtime_ns, st.st_size)
            except OSError:
                sig = None
            if _want_dump[0] and not _final[0]:
                _want_dump[0] = not _dump("phase")    # 锁被占着就下一轮再来
            if sig != last or tick % per_s == 0:
                last = sig
                ph = _read_phase()
                if ph != _phase[0] and not _final[0]:
                    with _lock[0]:
                        switched = ph != _phase[0] and not _final[0]   # _fire 可能刚在别的线程切过
                        if switched:
                            _snapshot(_phase[0])
                            _phase[0] = ph
                    if switched:
                        _dump("phase")
            if tick % per_s:
                continue
            if not stopped and os.path.exists(_stop_file):
                stopped = True
                _dump("stop")
            if _EV and _ev and not _final[0] and _lock[0].acquire(blocking=False):
                try:
                    _ev_flush()
                finally:
                    _lock[0].release()
            if tick % (10 * per_s) == 0:
                _dump("periodic")
    def _start_flusher():
        threading.Thread(target=_flusher, name="codestrata-flush", daemon=True).start()
    _start_flusher()

    # fork 出来的子进程继承父进程的计数，不清零就会把父进程 fork 之前的调用再算一遍；
    # 线程也不会跟着 fork 过来，落盘线程要重启；锁可能正被 fork 前的落盘线程拿着，要重建。
    # 调用栈保留——子进程还会从这些帧里返回。
    def _after_fork():
        _funcs.clear()
        _fedges.clear()
        _names.clear()
        del _snaps[:]             # fork 之前的阶段属于父进程
        del _pending[:]
        _want_dump[0] = False
        _trig_watch.clear()
        _t0[0] = time.monotonic_ns()
        _st[0] = _starttime()
        _lock[0] = threading.RLock()
        _final[0] = False
        del _ev[:]                # 事件：子进程写自己的文件，fork 之前没返回的帧不归它
        _ev_keys.clear()
        _xf.clear()
        _gen[0] += 1
        _ev_n[0] = 0
        _ids[:] = [itertools.count(1), itertools.count(1), itertools.count(1)]
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
            def _on_throw(code, off, exc):           # throw() / close() / asyncio 取消：也是恢复。
                _enter(code, False)                   # 和 PY_UNWIND 一样不能 DISABLE（会在被 trace
                                                      # 的程序里抛 ValueError），仓库外的代码每次都回调
            def _on_return(code, off, val):          # PY_RETURN：出栈
                return None if _leave(code) else D
            def _on_yield(code, off, val):           # PY_YIELD：出栈（挂起）
                return None if _leave(code, "Y") else D
            def _on_unwind(code, off, exc):          # 异常展开出帧。这个事件不能 DISABLE
                _leave(code)
            _mon.register_callback(_TID, E.PY_START, _on_start)
            _mon.register_callback(_TID, E.PY_RESUME, _on_resume)
            _mon.register_callback(_TID, E.PY_THROW, _on_throw)
            _mon.register_callback(_TID, E.PY_RETURN, _on_return)
            _mon.register_callback(_TID, E.PY_YIELD, _on_yield)
            _mon.register_callback(_TID, E.PY_UNWIND, _on_unwind)
            _mon.set_events(_TID, E.PY_START | E.PY_RESUME | E.PY_THROW | E.PY_RETURN
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

def _say(msg: str) -> None:
    """driver 的提示。终端关掉之后写 stderr 会报 EIO：不能因此丢掉整个录制的收尾。"""
    try:
        print(msg, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


_LEVELS = ((signal.SIGINT, None), (signal.SIGTERM, 15.0), (signal.SIGKILL, 5.0))


def _before_term(parts: Path | None, alive) -> None:
    """升级到 SIGTERM 之前：写 STOP，各进程的落盘线程 1 秒内看到就落一次盘（主线程卡在
    C 里也行），等它们写完再发信号。hook 里不装 SIGTERM 处理器，这是被强停的进程
    最后一份数据的来源。"""
    if parts is None or not parts.is_dir():
        return
    try:
        (parts / "STOP").write_text("stop\n")
    except OSError:
        return
    end = time.monotonic() + 1.5
    while time.monotonic() < end and alive():
        time.sleep(0.1)


def _stop(alive, send, grace: float, poke=None, parts: Path | None = None,
          skip_int=lambda: False) -> str | None:
    """三级停止：SIGINT → 等 grace 秒 → SIGTERM → 等 15 秒 → SIGKILL。
    SIGINT 在先：Python 进程收到它会抛 KeyboardInterrupt、正常走 atexit，数据完整落盘；
    case 脚本的 trap 也有机会收尾（停掉它 setsid 出去的服务）。返回最后发出的信号名。
    poke() 返回 True 表示用户又按了一次 Ctrl+C（或按了 Ctrl+\\）：直接升级一级。
    skip_int() 为真时跳过 SIGINT 这一级。"""
    last = None
    for sig, wait in _LEVELS:
        if not alive():
            break
        if sig == signal.SIGINT and skip_int():
            continue
        if sig == signal.SIGTERM:
            _before_term(parts, alive)
            if not alive():
                break
        send(sig)
        last = sig.name
        end = time.monotonic() + (grace if wait is None else wait)
        while time.monotonic() < end and alive():
            if poke and poke():
                _say("[codestrata] 再次中断：不等了，升级")
                break
            time.sleep(0.1)
    return last


def _ignores(pid: int, sig: int) -> bool:
    """这个进程是不是忽略了 sig（/proc/<pid>/status 的 SigIgn 位图）。非交互 bash 用 & 起的
    后台进程天生忽略 SIGINT：Python 程序若不自己装处理器（uvicorn 装了，asyncio.run 不装），
    对它发 SIGINT 等多久都没用，直接跳到 SIGTERM。"""
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            if ln.startswith("SigIgn:"):
                return bool(int(ln.split()[1], 16) >> (sig - 1) & 1)
    except (OSError, ValueError, IndexError):
        pass
    return False


def stop_pids(pids: list[int], grace: float, poke=None, parts: Path | None = None) -> dict[int, str]:
    """按三级顺序停一组不在同一进程组里的进程（残留进程）；返回 {pid: 最后发出的信号名}。
    忽略 SIGINT 的进程直接从 SIGTERM 开始。"""
    sent: dict[int, str] = {}
    starts = {p: _proc_start(p) for p in pids}

    def mine(p):                               # 还是当初那个进程（pid 没被复用）
        return _alive(p) and _proc_start(p) == starts[p]

    for sig, wait in _LEVELS:
        alive = [p for p in pids if mine(p)]
        if not alive:
            break
        if sig == signal.SIGTERM:
            _before_term(parts, lambda: any(mine(p) for p in alive))
        targets = [p for p in alive if mine(p) and not (sig == signal.SIGINT and _ignores(p, sig))]
        for p in targets:
            try:
                os.kill(p, sig)
                sent[p] = sig.name
            except (ProcessLookupError, PermissionError):
                pass
        end = time.monotonic() + (grace if wait is None else wait)
        while targets and time.monotonic() < end and any(mine(p) for p in targets):
            if poke and poke():
                _say("[codestrata] 再次中断：不等了，升级")
                break
            time.sleep(0.1)
    return sent


def _proc_start(pid: int) -> int | None:
    """/proc/<pid>/stat 的第 22 列（开机以来的启动时刻）：和 pid 一起才能认出同一个进程。"""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _alive(pid: int) -> bool:
    try:
        st = Path(f"/proc/{pid}/stat").read_text()
        return st.rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
    except IndexError:
        return False


def leftovers(parts: Path) -> list[int]:
    """还属于这个 run 的活进程：命令退出后 setsid 出去、没被 case 脚本停掉的服务，或者被
    遗弃的子进程。两种认法（只有 Linux）：
      - /proc/<pid>/environ 里有本 run 的 CODESTRATA_OUT（环境变量一路继承下去）；
      - 分片文件名里的 pid 还活着、启动时刻和分片里记的一样——setproctitle（vLLM 的
        engine core 在用）会清空 environ，靠这一条兜底。"""
    want = os.fsencode(f"{ENV_OUT}={parts}")
    out: set[int] = set()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    me = os.getpid()
    for d in entries:
        if not d.isdigit() or int(d) == me:
            continue
        try:
            with open(f"/proc/{d}/environ", "rb") as f:
                env = f.read()
        except OSError:
            continue
        if want in env.split(b"\0") and _alive(int(d)):
            out.add(int(d))
    try:
        names = os.listdir(parts)
    except OSError:
        names = []
    for n in names:
        if not (n.startswith("part-") and n.endswith(".json")) or "@" in n:
            continue
        try:
            pid = int(n[len("part-"):].split("-")[0].split(".")[0])
        except ValueError:
            continue
        if pid in out or pid == me or not _alive(pid):
            continue
        try:
            st = json.loads((parts / n).read_text(encoding="utf-8")).get("st")
        except (OSError, ValueError):
            continue
        if st is not None and st == _proc_start(pid):
            out.add(pid)
    return sorted(out)


def stop_leftovers(parts: Path, grace: float, poke=None) -> list[dict]:
    """找出并停掉属于这个 run 的残留进程，停完再找一遍：残留的 bash 在 EXIT trap 里还会起
    新的子进程（kill、sleep），它们同样带着本 run 的环境。最多三轮。返回 [{pid, argv, signal}]。"""
    out: list[dict] = []
    done: set[int] = set()
    for _ in range(3):
        pids = [p for p in leftovers(parts) if p not in done]
        if not pids:
            break
        argvs = {p: _argv_of(p) for p in pids}
        _say(f"[codestrata] 还有 {len(pids)} 个进程属于本次录制：{pids}，按三级停掉")
        sent = stop_pids(pids, grace, poke, parts)
        out += [{"pid": p, "argv": argvs[p], "signal": sent.get(p)} for p in pids]
        done.update(pids)
    return out


def _argv_of(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode("utf-8", "replace")[:400] for a in f.read().split(b"\0") if a][:60]
    except OSError:
        return []


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def run(root: Path, cmd: list[str], parts: Path, *, mono0_ns: int,
        timeout: float | None = None, pkgs: dict[str, str] | None = None,
        env_extra: dict[str, str] | None = None, stop_grace: float = 90.0, after=None,
        phase_at: list[dict] | None = None):
    """在 hook 下跑一条命令，合并各进程的分片。返回 after(trace, 录制信息) 的结果
    （没给 after 就返回 (trace, 录制信息)）。

    cmd 就是你平时怎么跑那个 case，比如
        ["python", "examples/online_serving/minicpmo/realtime_duplex_demo.py", "--input-wav", "..."]
    子进程会一并被 trace。各进程往 parts/ 里写分片（parts 是 runs.new_run 建的 run 目录下的
    parts/），这里不删任何旧数据——每次录制都有自己的目录。

    停止：命令放在自己的会话里（start_new_session），终端的 Ctrl+C 只到 driver，由 driver
    按三级顺序转发给整个进程组；超时同理。命令退出后再把还属于本 run 的残留进程也按三级
    停掉，最后才合并——这样每个进程的最后一次落盘都在结果里。driver 自己的信号处理器
    一直装到 after（收尾：打包、写 run.json）做完，收尾中途按 Ctrl+C 不会把 run 弄成半截。

    pkgs 是 {顶层包名: 它在仓库里的目录}。命令跑的若是 pip 装进 site-packages 的那份，
    靠它把执行路径映射回仓库文件。

    phase_at 是 resolve_phase_at 解析好的 --phase：[{name, file, qualname, line, dl}]。

    录制信息：{stop: exit|timeout|interrupt, returncode, phase_times: [(阶段, t_us)],
              duration_s, leftovers: [{pid, argv, signal}]}，t_us 相对 mono0_ns。
    """
    root = root.resolve()
    boot = _make_bootstrap(root, parts)
    env = dict(os.environ)
    env.update(env_extra or {})
    env[ENV_ROOT] = str(root)
    env[ENV_OUT] = str(parts)
    # setproctitle 默认会借用 environ 的内存写进程标题、把 /proc/<pid>/environ 清空，
    # 残留进程就认不出来了；这个变量让它只用 argv 那块
    env["SPT_NOENV"] = "1"
    # 明确写上（没有就是 []）：shell 里继承来的旧值不能生效
    env["CODESTRATA_PHASE_AT"] = json.dumps([[t["name"], t["file"], t["qualname"], t.get("line"), t.get("dl")]
                                             for t in phase_at or []])
    if pkgs:
        env[ENV_PKGS] = ";".join(f"{k}={v}" for k, v in pkgs.items())
    env["PYTHONPATH"] = str(boot) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    _say(f"[codestrata] 跑: {' '.join(cmd)}")
    _say(f"[codestrata] hook 已注入 PYTHONPATH（子进程一并 trace），分片写到 {parts}")
    us = lambda: (time.monotonic_ns() - mono0_ns) // 1000
    phase_file = parts / "PHASE"
    phase_times: list = [("start", us(), "start")]
    hits: list[int] = []                         # driver 收到的信号

    def on_sig(signum, frame):
        hits.append(signum)
    # 终端关掉（SIGHUP）和 Ctrl+C 一样处理：命令在自己的会话里，driver 一死它就没人管了。
    # Ctrl+\（SIGQUIT）是「别等了」：跳过 SIGINT 那一级。已经被忽略的信号（nohup 下的 SIGHUP、
    # 脚本里 & 起的 driver 的 SIGINT）保持忽略
    old = {}
    for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
        if signal.getsignal(sg) is not signal.SIG_IGN:
            old[sg] = signal.signal(sg, on_sig)
    seen = [0]

    def poke():                                  # 停的过程中又来了一个信号：升级一级
        if len(hits) > seen[0]:
            seen[0] = len(hits)
            return True
        return False

    def poll_phase():
        # 第一行是阶段名；hook 按 --phase 切的有第二行（切换那一刻的 monotonic_ns），准确的时刻
        # 收尾时从 PHASE-<名字>.fired 标记里拿（这里 0.1 秒一次的轮询可能整个错过一段）。
        # case 脚本 echo 进来的只有一行，按看到的时刻记，并替它建标记：之后同名的 --phase
        # 不会再把各进程切回这一段
        try:
            lines = phase_file.read_text().splitlines()
        except OSError:
            return
        ph = (lines[0].strip() if lines else "") or "start"
        if ph != phase_times[-1][0]:
            src = "hook" if len(lines) > 1 else "sh"
            phase_times.append((ph, us(), src))
            if src == "sh" and PHASE_NAME_RE.match(ph):
                try:
                    fd = os.open(parts / f"PHASE-{ph}.fired", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, f"sh {os.getpid()} {time.monotonic_ns()}\n".encode())
                    os.close(fd)
                except OSError:
                    pass
            _say(f"[codestrata] 阶段 → {ph}")

    try:
        stop, rc, t_start = "exit", None, time.monotonic()
        left: list[dict] = []
        try:
            proc = subprocess.Popen(cmd, cwd=str(root), env=env, start_new_session=True)
        except OSError as e:
            _say(f"[codestrata] 命令起不来：{e}")
            proc = None
            rc = 127
        deadline = t_start + timeout if timeout else None
        while proc is not None:
            try:
                rc = proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
            poll_phase()
            why = ("interrupt" if hits else
                   "timeout" if deadline and time.monotonic() > deadline else None)
            if why:
                stop = why
                _say(f"[codestrata] {'被中断' if why == 'interrupt' else f'超时 {timeout}s'}："
                     f"SIGINT → {stop_grace:.0f}s → SIGTERM → 15s → SIGKILL，停整个进程组")
                seen[0] = len(hits)
                _stop(lambda: proc.poll() is None, lambda sg: _killpg(proc.pid, sg), stop_grace, poke,
                      parts, skip_int=lambda: signal.SIGQUIT in hits)
                try:
                    rc = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    rc = None
                break
        poll_phase()
        duration = time.monotonic() - t_start
        # 残留：命令的进程组里被遗弃的成员，和 setsid 出去（不在这个组里）的服务。
        # Linux 上扫 /proc 全能找出来；别的系统只能停进程组
        if proc is not None and not os.path.isdir("/proc") and _group_alive(proc.pid):
            _stop(lambda: _group_alive(proc.pid), lambda sg: _killpg(proc.pid, sg), stop_grace, poke, parts)
        seen[0] = len(hits)
        left = stop_leftovers(parts, stop_grace, poke)
        poll_phase()
        # hook 切的阶段用标记里的精确时刻：轮询可能整个错过一段（两个阶段隔了不到 0.1 秒、
        # 或者残留进程在被停的路上才切）
        phase_times = merge_phase_log(phase_times, fired_phases(parts, mono0_ns))
        shutil.rmtree(boot, ignore_errors=True)
        tr = merge(parts)
        info = {"stop": stop, "returncode": rc, "phase_times": phase_times,
                "duration_s": duration, "leftovers": left}
        return after(tr, info) if after else (tr, info)
    finally:
        for sg, h in old.items():
            signal.signal(sg, h)
        shutil.rmtree(boot, ignore_errors=True)


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
    from .scan import _STMT_CONTAINERS
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
            elif isinstance(n, _STMT_CONTAINERS) or type(n).__name__ == "Match":
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
            key = f"{where}:{q.replace('.<locals>', '')}"     # 索引里嵌套的名字不带 .<locals>
            s = symbols.get(key)
            if s is None or s.get("k") != "func":
                s, via = _inherited(symbols, where, q.replace(".<locals>", ""))
            if s is None:
                last = q.rsplit(".", 1)[-1]
                near = [k for k, v in symbols.items() if v.get("k") == "func"
                        and k.split(":", 1)[1].rsplit(".", 1)[-1] == last][:6]
                raise SystemExit(f"--phase {name}：静态索引里没有函数 {key}"
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


# 基类里这些不会定义仓库里的方法：MRO 里碰到它们可以跳过，不算「不在仓库里、说不准」
_OPAQUE_OK = {"object", "Generic", "ABC", "Protocol"}


def _inherited(symbols: dict, mod: str, q: str) -> tuple[dict | str | None, str | None]:
    """模块:类.方法 在这个类上没定义的，按 C3 MRO 顺着基类（静态索引里记的名字）找。基类先在同一个
    模块里找，再按名字在整个索引里找（唯一才认），Base[T] 去掉下标。MRO 里先碰到仓库外的基类
    （除了 object / Generic / ABC / Protocol）就不猜，返回说明原因的字符串。
    返回 (符号, 实际定义它的键)；找不到返回 (None, None)。"""
    cls, dot, meth = q.rpartition(".")
    if not dot:
        return None, None
    classes = {k: v for k, v in symbols.items() if v.get("k") == "class"}
    by_name: dict[str, list[str]] = {}
    for k in classes:
        by_name.setdefault(k.split(":", 1)[1].rsplit(".", 1)[-1], []).append(k)

    def base_key(ck: str, b: str) -> str:
        b = re.sub(r"\[.*$", "", b).strip()
        last = b.rsplit(".", 1)[-1]
        same = f"{ck.split(':', 1)[0]}:{last}"
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

    start = f"{mod}:{cls}"
    if start not in classes:
        return None, None
    order = mro(start)
    if order is None:
        return f"{start} 的继承关系解析不了（有环或者不一致）", None
    for ck in order[1:]:
        if ck.startswith("?"):
            if ck[1:] in _OPAQUE_OK:
                continue
            return (f"{q} 不在 {cls} 上定义，MRO 里先碰到了仓库外（或名字对不上唯一）的基类 {ck[1:]}，"
                    f"说不准实际调的是哪个；写成定义它的那个类的 模块:qualname"), None
        s = symbols.get(f"{ck}.{meth}")
        if s and s.get("k") == "func":
            return s, f"{ck}.{meth}"
    return None, None


def case_script(root: Path, cmd: list[str]) -> dict | None:
    """case 命令里的脚本（bash case.sh、python demo.py 里那个文件）：把它的内容一起存下来。
    hot 图的帮助里要能看到「这次到底跑了什么」——光一句 bash ../../trace_case.sh 看不出
    起了什么服务、跑的是哪个 demo / benchmark、带了什么参数。命令从仓库根目录开始跑。"""
    for a in cmd:
        if a.startswith("-"):
            continue
        p = Path(a) if Path(a).is_absolute() else root / a
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
    # 文件粒度的边由函数粒度派生（跨文件的才算），只用来打印摘要
    edges: dict[str, int] = {}
    for k, v in fedges.items():
        a, _, b = k.partition("|")
        fa, fb = a.rpartition(":")[0], b.rpartition(":")[0]
        if fa != fb:
            ek = f"{fa}|{fb}"
            edges[ek] = edges.get(ek, 0) + v
    procs.sort(key=lambda p: (p["t0"] or 0, p["pid"] or 0))
    return {"phases": phases, "funcs": funcs, "func_edges": fedges, "file_edges": edges,
            "names": names, "mapped": mapped, "shas": shas, "sha_conflicts": sorted(conflicts),
            "bad_parts": sorted(bad), "procs": procs, "n_procs": len(procs)}


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
        sk = None if lineno <= 0 else loc2sym.get((rel, lineno))
        if sk:
            sym_hits[sk] = sym_hits.get(sk, 0) + n
        elif 0 <= lineno <= 1:
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
