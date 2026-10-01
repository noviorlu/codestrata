"""被注入到被测进程里的一侧：`_SITECUSTOMIZE` 是一段独立的源码，`make_bootstrap` 把它写成临时目录里的
sitecustomize.py，driver 把这个目录插到 PYTHONPATH 最前面。这段源码不 import codestrata 的任何东西——
它跑在被测程序的 Python 里，可能是另一个版本、另一个环境。和 driver 之间只靠下面几个环境变量和 parts/ 下的文件。

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
   「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。栈上只有仓库帧和 case 自己的
   代码（见 _case_rel）：穿过库的调用记到最近的仓库帧上，case 里被回调的函数调的记到 case 头上。

4. **分阶段（这一侧）。** 每个进程看 $CODESTRATA_OUT/PHASE（case 脚本写的，或者别的进程切的）；
   `--phase 名字=函数` 时，第一次进入那个函数的进程在那一刻切过去，并停 0.1 s 让别的进程跟上。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

ENV_ROOT = "CODESTRATA_ROOT"
ENV_OUT = "CODESTRATA_OUT"
ENV_PKGS = "CODESTRATA_PKGS"      # "顶层包=仓库内目录;..."，把安装包里的代码映射回仓库
ENV_CASE_DIRS = "CODESTRATA_CASE_DIRS"   # 仓库外的执行目录（--cwd）：直接放在里面的 .py 也算 case 的代码


_SITECUSTOMIZE = '''\
# codestrata 自动注入。每个 Python 进程 import 它来挂上调用 hook。
import os, sys, atexit, json, threading, time, hashlib, itertools

_root = os.environ.get("CODESTRATA_ROOT")
_out = os.environ.get("CODESTRATA_OUT")
if _root and _out:
    _root = os.path.realpath(_root)
    _funcs = {}          # "rel:firstlineno" -> 被调次数（模块顶层是 "rel:0"）
    # (调用者key, 被调者key, 调用者当时执行到的指令偏移) -> 次数（函数粒度，真正的 caller→callee）。
    # 热路径上只用元组做键、不拼字符串，记指令偏移（f_lasti）不记行号：3.12 上 f_lineno 要从函数头一路
    # 解码行号表，函数越长越慢（200 行的函数尾部近 1 μs），f_lasti 是现成的。写文件时（_write）才按调用者的
    # code（_fcode，每个调用处第一次见到时记下）换成行号，拆成 func_edges「a|b」和 func_lines「a|b|行」
    _fcalls = {}
    _fcode = {}
    _ltab = {}               # id(code) -> [(起, 止, 行)]：指令偏移 -> 行号
    _mapped = {}         # 从安装包映射回仓库的文件：rel -> 实际执行的路径
    _names = {}          # "rel:firstlineno" -> co_qualname（代码改了行号之后按名字找回符号用）
    _shas = {}           # rel -> 实际执行的那个文件的内容哈希（第一次跑到它时取；录制中途改了文件也认得出）
    _tls = threading.local()
    _relc = {}
    # 被 trace 的常常是 pip 装进 site-packages 的那份，而不是仓库里的源码。
    # 顶层包名 → 它在仓库里的目录（src-layout 下是 src/pkg）
    _pkgs = dict(x.split("=", 1) for x in os.environ.get("CODESTRATA_PKGS", "").split(";") if "=" in x)

    # case 自己的代码：入口脚本（__main__；spawn 的子进程里重新执行的那份叫 __mp_main__）同一层目录里的
    # .py。它不在仓库里，但要在栈上当调用方：case 里定义、被仓库代码回调的函数（Flask 的视图）再调仓库
    # 函数时，调用方是它，不是最近的仓库帧（dispatch_request）——否则会画出并不存在的动态分派边。
    # 键是 "<外部代码>/文件名:行"，不在 index 里，和仓库里 scan 不扫的 examples/ 一样不上图；不计数
    # （funcs 里只有仓库代码）。别的仓库外代码——标准库、site-packages、~/.cache 里的 trust_remote_code
    # 和编译缓存、可编辑安装的依赖——照旧透明：穿过它们的调用记到最近的仓库帧上
    _EXT = "<外部代码>/"
    _std = os.path.dirname(os.path.realpath(os.__file__)) + os.sep
    _mains = [None, ()]
    # 执行目录在仓库外时（--cwd），driver 把它传进来：入口是库的时候（python -m pytest / -m unittest，
    # __main__ 在 site-packages 里）靠它认 case 的代码。只认直接放在里面的，不往子目录找——执行目录
    # 可能是个大目录，下面有可编辑安装的依赖
    _casedirs = tuple(os.path.realpath(d) for d in os.environ.get("CODESTRATA_CASE_DIRS", "").split(os.pathsep) if d)
    _later = {}                                # 文件名 → realpath：当时还不能算 case 的（见 _case_rel）

    def _case_rel(rp, fn):
        if rp.startswith(_std) or "/site-packages/" in rp or "/dist-packages/" in rp:
            return None                        # python -m pytest / -m unittest：入口本身是库
        fs = tuple(getattr(sys.modules.get(m), "__file__", None) for m in ("__main__", "__mp_main__"))
        if fs != _mains[0]:
            _mains[:] = [fs, tuple({os.path.dirname(os.path.realpath(f)) for f in fs if f})]
            # __main__ 换了（python -m 包.模块：包的 __init__.py 在 __main__ 有 __file__ 之前就跑了）：
            # 之前判成「不是 case」的文件，按新的入口目录再认一次
            for f, r in list(_later.items()):
                if os.path.dirname(r) in _mains[1]:
                    _relc[f] = _EXT + os.path.basename(r)
                    del _later[f]
        d = os.path.dirname(rp)
        if d in _mains[1] or d in _casedirs:
            return _EXT + os.path.basename(rp)
        _later[fn] = rp
        return None

    def _rel(code):
        # 只记仓库内的代码（和 case 自己的代码，见 _case_rel），仓库外（stdlib、torch…）一律忽略。
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
            if r is None:
                r = _case_rel(rp, fn)
            elif r not in _shas:
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
        # 模块顶层记成第 0 行：模块 code 的 firstlineno 是 1，会和写在第 1 行的函数撞键。
        # 3.12 泛型（def f[T]、class C[T]）定义时跑一次的「<generic parameters of f>」帧，首行和 f 自己
        # 一样，会和 f 的真调用撞键：它也是定义、不是调用，一样记成第 0 行
        n = code.co_name
        return rel + ":" + ("0" if n[0] == "<" and (n == "<module>" or n.startswith("<generic parameters of "))
                            else str(code.co_firstlineno))

    # ---- 时序事件（CODESTRATA_EVENTS=1，只有 sys.monitoring 才有）：记每一次调用（同文件的也记，2026-10-01 起），
    # 口径和 func_edges 相同（调用方是栈顶的仓库帧，递归自调用不算）。每次调用给一个
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
    _xc = set()              # 当过被调方的 code（的 id）：只有它们的返回 / 挂起 / 恢复才要查帧
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
        th = threading.current_thread()
        _ev.append("N %d %s" % (i, _clean(th.name)))
        try:
            th._codestrata_tid = (_gen[0], i)            # join 它的那一方（_join）按这个认出是哪条线程
        except Exception:
            pass
        fr = getattr(th, "_codestrata_from", None)      # 谁起的这个线程（_th_start 记的）；fork 之前起的不算
        if fr is not None and fr[0] == _gen[0]:
            _ev.append("F %d %d %d %d %d %d" % (i, fr[1], fr[2][0], fr[2][1], fr[3], 1 if th.daemon else 0))
        return i

    def _ev_here():
        # (span 号, 行号)：当前线程上最里层正在执行的 span（没有是 0），和它正执行到的那一行（起线程、放 / 取、发 / 收的
        # 那一行代码；经仓库外的代码转了一道的，是调进仓库外代码的那一行）。从调用者的调用者往外找第一个记过账的帧
        f = sys._getframe(2)
        while f is not None:
            x = _xf.get(id(f))
            if x is not None and x[1] is f.f_code:
                return x[0], f.f_lineno or 0
            f = f.f_back
        return 0, 0

    def _ev_t():
        return (time.monotonic_ns() - _t0[0]) // 1000

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

    def _enter(code, count, fr=None):
        # fr：被调方的帧（setprofile 给的）；sys.monitoring 的回调只给 code，要时再取（_enter ← 回调 ← 被调方的帧）
        rel = _rel(code)
        if rel is None:
            return False
        k = _key(code, rel)
        st = _stack()
        if count:
            if rel[0] != "<":                           # case 的代码（<外部代码>/…）只当调用方，不计数
                n = _funcs.get(k)
                if n is None:
                    n = 0
                    q = getattr(code, "co_qualname", None)  # 3.10 没有：不记（拿短名字去对会对到同名的别的函数上）
                    if q:
                        _names[k] = q
                    if _trig_q:                             # 在计数之前切：触发的这次调用算进新阶段
                        n = _trig_check(code, rel, q, k, n)
                elif _trig_watch and k in _trig_watch:
                    n = _trig_check(code, rel, getattr(code, "co_qualname", None), k, n)
                _funcs[k] = n + 1
            if st and st[-1] != k and rel[0] != "<":   # 递归自调用不算边；被调的是 case 的代码也不记
                                                       # （不上图，只在栈上当调用方；它自己调来调去不能耗掉事件额度）
                # 调用写在哪一行：从被调方的帧往外找最近的仓库帧（中间隔着仓库外的帧——框架的 __call__、
                # map 这类——就跳过），就是栈顶的调用方，它这时停在哪一行，调用就写在哪一行
                f = (fr if fr is not None else sys._getframe(2)).f_back
                while f is not None:
                    c = f.f_code
                    r = _relc.get(c.co_filename, 0)       # _rel 的缓存，热路径上省一次函数调用
                    if r == 0:
                        r = _rel(c)
                    if r is not None:
                        break
                    f = f.f_back
                ck = (st[-1], k, f.f_lasti if f is not None else -1)
                n = _fcalls.get(ck)
                if n is None:
                    _fcalls[ck] = 1
                    _fcode[ck] = f.f_code if f is not None else None
                else:
                    _fcalls[ck] = n + 1
                if _EV:
                    _ev_call(st[-1], k, code)
            elif _EV and id(code) in _xc:                 # 递归自调用 / 没有调用方：新起的一帧不记，地址上若有旧账
                                                          # （被丢掉的同一个函数的生成器）就作废，免得它的事件记到旧 span 上
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

    def _line_at(code, off):
        # 指令偏移 -> 行号（和 f_lineno 一样的结果）；拿不到是 0
        if code is None or off < 0:
            return 0
        t = _ltab.get(id(code))                      # code 被 _fcode 留着，id 不会被别的对象复用
        if t is None:
            t = _ltab[id(code)] = [x for x in code.co_lines() if x[2] is not None]
        for a, b, l in t:
            if a <= off < b:
                return l
        return 0

    def _write(p, data):
        # 目录不在就不写（不 makedirs）：录制已经收尾、parts/ 已经打包删掉之后，
        # 还活着的残留进程不能把它重新建出来
        tmp = "%s.%d.tmp" % (p, threading.get_ident())
        try:
            fc = data.get("func_calls")
            if fc is not None:                        # 元组键这时才拆成字符串键、指令偏移换成行号（见 _fcalls）
                fe, fl = {}, {}
                for ck, n in fc.items():
                    e = ck[0] + "|" + ck[1]
                    fe[e] = fe.get(e, 0) + n
                    lk = "%s|%d" % (e, _line_at(_fcode.get(ck), ck[2]))
                    fl[lk] = fl.get(lk, 0) + n
                data = {**data, "func_edges": fe, "func_lines": fl}
                del data["func_calls"]
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
        d = ("%s@%d-%s.json" % (_base(), len(_snaps), name), {"funcs": dict(_funcs), "func_calls": dict(_fcalls)})
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
             "funcs": dict(_funcs), "func_calls": dict(_fcalls), "names": dict(_names),
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
                    f.write("H %d %d %d\\nM all\\n" % (os.getpid(), _t0[0], os.getppid()))   # M all：同文件的调用也记了
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
        _fcalls.clear()
        _fcode.clear()
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

    # ---- 谁起了谁、谁回收了谁（时序事件开着时）。线程：Thread.start 时记下在哪个线程的哪个 span 里（新线程第一次登记时写 F 行）；
    # 线程的 run 跑完时它自己写一行 X（只记登记过的、也就是碰过仓库代码或交接的线程）；join 返回、被等的线程已经结束时，
    # 在等的那个线程里写一行 J（在哪个 span 里等到的哪条线程）。线程池的 shutdown(wait=True) 也是逐个 join。
    # 子进程：exec 出来的（subprocess、multiprocessing 的 spawn 都经 _posixsubprocess.fork_exec；还有 os.posix_spawn）
    # 起完才知道 pid，在父进程里写 P 行；fork 出来的（os.fork、multiprocessing 的 fork）fork 之前记下，子进程里写 B 行。
    # 只包一层、照原样调，出错不影响被 trace 的程序
    _fork_from = [None]
    if _EV:
        _th_start = threading.Thread.start
        def _start(self, *a, **kw):
            try:
                self._codestrata_from = (_gen[0], _ev_tid(), _ev_here(), _ev_t())
                run0 = self.run
                def run(*a2, **kw2):
                    try:
                        return run0(*a2, **kw2)
                    finally:
                        try:
                            c = getattr(_tls, "ev", None)
                            if c is not None and c[0] == _gen[0]:
                                _ev.append("X %d %d" % (c[1], _ev_t()))
                        except Exception:
                            pass
                self.run = run
            except Exception:
                pass
            return _th_start(self, *a, **kw)
        threading.Thread.start = _start

        _th_join = threading.Thread.join
        def _join(self, *a, **kw):
            r = _th_join(self, *a, **kw)
            try:
                tt = getattr(self, "_codestrata_tid", None)
                if tt is not None and tt[0] == _gen[0] and not self.is_alive() and not getattr(self, "_codestrata_joined", False):
                    self._codestrata_joined = True        # 只记第一次等到它的那一处（之后再 join 立刻返回）
                    sp, ln = _ev_here()
                    _ev.append("J %d %d %d %d %d" % (_ev_t(), _ev_tid(), sp, ln, tt[1]))
            except Exception:
                pass
            return r
        threading.Thread.join = _join

        def _spawned(fn):
            def wrap(*a, **kw):
                pid = fn(*a, **kw)
                try:
                    sp, ln = _ev_here()
                    _ev.append("P %d %d %d %d %d" % (_ev_t(), _ev_tid(), sp, ln, pid))
                except Exception:
                    pass
                return pid
            return wrap
        try:
            import _posixsubprocess
            _posixsubprocess.fork_exec = _spawned(_posixsubprocess.fork_exec)
            if "subprocess" in sys.modules:           # 已经 import 过的 subprocess 自己存了一份
                sys.modules["subprocess"]._fork_exec = _posixsubprocess.fork_exec
        except Exception:
            pass
        for _n in ("posix_spawn", "posix_spawnp"):
            if hasattr(os, _n):
                setattr(os, _n, _spawned(getattr(os, _n)))

        _waitpid0 = os.waitpid
        def _waitpid(pid, options, *a, **kw):
            r = _waitpid0(pid, options, *a, **kw)
            try:
                if r[0] > 0 and (os.WIFEXITED(r[1]) or os.WIFSIGNALED(r[1])):
                    sp, ln = _ev_here()
                    _ev.append("W %d %d %d %d %d" % (_ev_t(), _ev_tid(), sp, ln, r[0]))
            except Exception:
                pass
            return r
        os.waitpid = _waitpid

        def _before_fork():
            try:
                _fork_from[0] = (_t0[0], _ev_tid()) + _ev_here()
            except Exception:
                _fork_from[0] = None
        def _after_fork_ev():                         # 在 _after_fork 之后跑（按注册的先后）
            fr = _fork_from[0]
            if fr is not None:
                _ev.append("B %d %d %d %d" % fr)
        os.register_at_fork(before=_before_fork, after_in_child=_after_fork_ev)

    # ---- 谁把数据交给谁（时序事件开着时）。进程内的队列：put 时、get 时各写一行（Q / G），带队列和对象的 id——
    # 对象在队列里的时候一直活着，整理时同一个队列里同一个对象的 put 和 get 配成一对。ZMQ：发、收各写一行（O / I），
    # 带消息的指纹（每一段的长度 + 首尾 32 字节的哈希），整理时按指纹、先发先收配对（跨进程）。都算进行数上限。
    # 这些模块不为了打补丁主动 import：第一次 import 完的时候打（_OnImport），已经 import 过的马上打
    def _ev_put(tag, kind, q, item):
        if _ev_room():
            sp, ln = _ev_here()
            _ev.append("%s %d %d %d %d %s %d %d" % (tag, _ev_t(), _ev_tid(), sp, ln, kind, id(q), id(item)))

    def _queue_patch(cls, kind, put_name, get_name):
        put0, get0 = cls.__dict__.get(put_name), cls.__dict__.get(get_name)
        if put0 is not None:
            def put(self, item, *a, **kw):
                r = put0(self, item, *a, **kw)
                try:
                    _ev_put("Q", kind, self, item)
                except Exception:
                    pass
                return r
            setattr(cls, put_name, put)
        if get0 is not None:
            def get(self, *a, **kw):
                item = get0(self, *a, **kw)
                try:
                    _ev_put("G", kind, self, item)
                except Exception:
                    pass
                return item
            setattr(cls, get_name, get)

    def _fp(parts):
        h = hashlib.blake2b(digest_size=8)
        if isinstance(parts, (bytes, bytearray, memoryview)):
            parts = (parts,)
        for x in parts:
            if isinstance(x, str):
                x = x.encode("utf-8", "replace")
            try:
                m = memoryview(getattr(x, "buffer", x))
                if m.ndim != 1 or m.format != "B":
                    m = m.cast("B")
            except (TypeError, ValueError):
                continue
            h.update(m.nbytes.to_bytes(8, "little"))
            h.update(m[:32])
            h.update(m[-32:])
        return h.hexdigest()

    def _ev_msg(tag, here, parts):
        if _ev_room():
            _ev.append("%s %d %d %d %d %s" % (tag, _ev_t(), _ev_tid(), here[0], here[1], _fp(parts)))

    import weakref
    _zshadow = weakref.WeakSet()  # asyncio 版 socket 背后真正收发的同步 socket：它们的收发由 asyncio 版那一层记
    _zmore = {}                   # id(socket) → 带 SNDMORE 发出去、这条消息还没发完的帧
    _ZROUTER, _ZSNDMORE = 6, 2    # libzmq 的 ZMQ_ROUTER、ZMQ_SNDMORE

    def _zdata(sock, parts):
        # ROUTER 发的时候第一帧是对方的身份（不发出去），收的时候第一帧是对方的身份（对方没发）：去掉，两头算的是同样的数据帧
        parts = list(parts)
        try:
            if parts and sock.type == _ZROUTER:
                parts = parts[1:]
        except Exception:
            pass
        return parts

    def _zsend(sock, data, flags):
        # 按帧记：带 SNDMORE 的帧攒着，一条消息的最后一帧发出去时整条算一次（send_multipart 也是逐帧调 send）
        k = id(sock)
        frames = _zmore.get(k)
        if frames is None:
            frames = _zmore[k] = []
        frames.append(data)
        if not (flags or 0) & _ZSNDMORE:
            del _zmore[k]
            _ev_msg("O", _ev_here(), _zdata(sock, frames))

    def _zmq_sync(mod):
        S = mod.Socket
        send0, recv0 = S.__dict__.get("send"), S.__dict__.get("recv_multipart")
        if send0 is not None:
            def send(self, data, flags=0, *a, **kw):
                try:
                    if self not in _zshadow:
                        _zsend(self, data, flags)
                except Exception:
                    pass
                return send0(self, data, flags, *a, **kw)
            S.send = send
        if recv0 is not None:
            def recv_multipart(self, *a, **kw):
                parts = recv0(self, *a, **kw)
                try:
                    if self not in _zshadow:
                        _ev_msg("I", _ev_here(), _zdata(self, parts))
                except Exception:
                    pass
                return parts
            S.recv_multipart = recv_multipart

    def _zmq_async(mod):
        S = getattr(mod, "_AsyncSocket", None)
        if S is None:
            return
        init0 = S.__dict__.get("__init__")
        if init0 is not None:
            def __init__(self, *a, **kw):
                init0(self, *a, **kw)
                try:
                    _zshadow.add(self._shadow_sock)
                except Exception:
                    pass
            S.__init__ = __init__
        sendm0, send0 = S.__dict__.get("send_multipart"), S.__dict__.get("send")
        recv0 = S.__dict__.get("recv_multipart")
        if sendm0 is not None:
            def send_multipart(self, msg_parts, *a, **kw):
                try:
                    _ev_msg("O", _ev_here(), _zdata(self, msg_parts))
                except Exception:
                    pass
                return sendm0(self, msg_parts, *a, **kw)
            S.send_multipart = send_multipart
        if send0 is not None:
            def send(self, data, flags=0, *a, **kw):
                try:
                    _zsend(self, data, flags)
                except Exception:
                    pass
                return send0(self, data, flags, *a, **kw)
            S.send = send
        if recv0 is not None:
            def recv_multipart(self, *a, **kw):
                fut = recv0(self, *a, **kw)
                try:
                    sp = _ev_here()                   # 等它的协程（和 await 的那一行）；收到的时候（回调里）已经不在它的帧上了
                    def done(f, sp=sp, sock=self):
                        try:
                            if not f.cancelled() and f.exception() is None:
                                _ev_msg("I", sp, _zdata(sock, f.result()))
                        except Exception:
                            pass
                    fut.add_done_callback(done)
                except Exception:
                    pass
                return fut
            S.recv_multipart = recv_multipart

    _patches = {}
    if _EV:
        _patches = {
            "queue": lambda m: [_queue_patch(c, "q", "_put", "_get") for c in (m.Queue, m.PriorityQueue, m.LifoQueue)],
            "asyncio.queues": lambda m: [_queue_patch(c, "a", "_put", "_get")
                                         for c in (m.Queue, m.PriorityQueue, m.LifoQueue)],
            "janus": lambda m: _queue_patch(m.Queue, "j", "_put_internal", "_get"),
            "zmq.sugar.socket": _zmq_sync,
            "zmq._future": _zmq_async,
        }

    class _OnImport:
        # 这几个模块第一次 import 完的时候打补丁：找 spec 交给后面的 finder，只把 loader 的 exec_module 包一层
        def find_spec(self, name, path=None, target=None):
            fn = _patches.pop(name, None)
            if fn is None:
                return None
            try:
                spec = None
                for f in sys.meta_path:
                    if f is self or not hasattr(f, "find_spec"):
                        continue
                    spec = f.find_spec(name, path, target)
                    if spec is not None:
                        break
                ld = getattr(spec, "loader", None)
                ex = getattr(ld, "exec_module", None)
                if ex is None:
                    return spec
                def exec_module(module):
                    ex(module)
                    try:
                        fn(module)
                    except Exception:
                        pass
                ld.exec_module = exec_module
                return spec
            except Exception:
                return None
    for _n in list(_patches):                         # 已经 import 过的马上打
        if _n in sys.modules:
            try:
                _patches.pop(_n)(sys.modules[_n])
            except Exception:
                pass
    if _patches:
        sys.meta_path.insert(0, _OnImport())

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
                _enter(frame.f_code, True, frame)
            elif event == "return":
                _leave(frame.f_code)
        sys.setprofile(_prof)
        threading.setprofile(_prof)
'''


def make_bootstrap(root: Path, outdir: Path) -> Path:
    d = Path(tempfile.mkdtemp(prefix="codestrata-boot-"))
    (d / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return d
