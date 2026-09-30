"""平台差异集中在这里：录制只支持 Linux，其余（scan / serve / graph / runs 的查看）在任何系统上都要能 import、能用。

录制依赖 Linux 才有的东西：`/proc` 认进程、找 setsid 出去的残留服务，进程组和 SIGKILL 停干净。
别的系统上也能勉强跑起来，但会悄悄漏掉残留进程、留下没停的服务，所以直接拒绝，而不是录出一份不完整的 run。
只在 Unix 上有的模块和常量（fcntl、signal.SIGKILL）不在模块顶层取，否则 Windows 上整个命令行都起不来。
"""
from __future__ import annotations

import contextlib
import sys


def can_trace() -> bool:
    """这个系统能不能录制"""
    return sys.platform.startswith("linux")


def require_trace() -> None:
    """不能录制就说清楚并退出（在建 run 目录之前调，不留下一个失败的 run）"""
    if not can_trace():
        raise SystemExit(f"录制（trace）目前只支持 Linux，这台机器是 {sys.platform}：它要靠 /proc 认进程、"
                         "找出 setsid 出去的服务并停干净。\n"
                         "scan / serve / graph / runs 照常可用，可以查看在 Linux 上录好的 run。")


@contextlib.contextmanager
def file_lock(f):
    """对一个打开的文件加独占锁，离开时释放（进程死了也会释放）。Unix 用 fcntl.flock，Windows 用 msvcrt.locking，
    两样都没有就不加锁（只是失去并发保护，不影响单个进程）"""
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
        return
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return
    yield
