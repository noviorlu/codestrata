"""驱动的一侧：在被测进程外面跑命令、管进程、收尾。

1. **停要停干净。** 服务类的 case 会 setsid 起服务；超时或 Ctrl+C 时直接 SIGKILL 命令，
   服务就成了孤儿、一直占着显存，最后几秒的数据也丢了。所以命令放在自己的会话里，由
   driver 按 SIGINT → SIGTERM → SIGKILL 三级停，再扫 /proc 找出还带着本次录制环境变量的
   残留进程同样停掉，最后才合并。

2. **分阶段（这一侧）。** 录制中每 50 ms 看一次 PHASE，记下切换的时刻；`--phase` 的函数在开录前由
   `analysis.resolve_phase_at` 解析好，经环境变量交给 hook。

只在 Linux 上能用（`/proc`、进程组、SIGKILL），见 compat.py。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .analysis import PHASE_NAME_RE, clean_phase, fired_phases, merge, merge_phase_log
from .hook import ENV_CASE_DIRS, ENV_OUT, ENV_PKGS, ENV_ROOT, make_bootstrap

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


def _levels():
    """停进程的三级：(信号, 升级到它之前等几秒)。用到时才取——SIGKILL 只有 Unix 有，放在模块顶层会让
    Windows 上连 scan / serve 都 import 不了（录制本身只支持 Linux，见 compat.py）"""
    return ((signal.SIGINT, None), (signal.SIGTERM, 15.0), (signal.SIGKILL, 5.0))


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
    for sig, wait in _levels():
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
    starts = {p: proc_start(p) for p in pids}

    def mine(p):                               # 还是当初那个进程（pid 没被复用）
        return _alive(p) and proc_start(p) == starts[p]

    for sig, wait in _levels():
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


def proc_start(pid: int) -> int | None:
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
        if st is not None and st == proc_start(pid):
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


def misplaced_paths(cmd: list[str], run_dir: Path, here: Path) -> list[str]:
    """命令里的相对路径（带 / 的，或 .py / .sh 结尾的参数）在命令的执行目录下没有、在 here（敲命令时的
    当前目录）下有：多半是以为命令在当前目录跑。trace 默认在仓库根目录跑命令，开录之前就指出来，
    不要等命令起不来、留下一个失败的 run。只按「这个路径在哪边存在」判断，不猜意图"""
    out = []
    for a in cmd:
        if a.startswith("-") or os.path.isabs(a) or not ("/" in a or a.endswith((".py", ".sh", ".bash"))):
            continue
        if not (run_dir / a).exists() and (here / a).exists():
            out.append(a)
    return out


def run(root: Path, cmd: list[str], parts: Path, *, mono0_ns: int,
        timeout: float | None = None, pkgs: dict[str, str] | None = None,
        env_extra: dict[str, str] | None = None, stop_grace: float = 90.0, after=None,
        phase_at: list[dict] | None = None, cwd: Path | None = None, stdout=None):
    """在 hook 下跑一条命令，合并各进程的分片。返回 after(trace, 录制信息) 的结果
    （没给 after 就返回 (trace, 录制信息)）。cwd 是命令的执行目录，默认仓库根目录 root。
    stdout 是命令的标准输出接到哪（Popen 的 stdout；trace --json 时接到 stderr，stdout 只留结果）。

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

    录制信息：{stop: exit|timeout|interrupt, returncode, phase_times: [(阶段, t_us, 来源)],
              duration_s, leftovers: [{pid, argv, signal}]}，t_us 相对 mono0_ns。
    """
    root = root.resolve()
    boot = make_bootstrap(root, parts)
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
    run_dir = (cwd or root).resolve()
    # 明确写上（仓库里执行就是空的）：shell 里继承来的旧值不能生效
    env[ENV_CASE_DIRS] = "" if run_dir == root or root in run_dir.parents else str(run_dir)
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
        # 阶段名会出现在 REF 和地址栏里：case 脚本写来的名字里 [A-Za-z0-9._-] 以外的字符换成 _（hook 记计数时同样换）
        ph = clean_phase(lines[0].strip()) if lines and lines[0].strip() else "start"
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
            proc = subprocess.Popen(cmd, cwd=str(cwd or root), env=env, start_new_session=True, stdout=stdout)
        except OSError as e:
            _say(f"[codestrata] 命令起不来（在 {cwd or root} 执行）：{e}")
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
