"""时序事件真值测试的被调方（和 truth.py 不在同一个文件：只有跨文件的调用才记事件）。"""
import asyncio
import os
import sys
import time

from fakesvc import other


def mid(x):
    return other.deep(x) + 1


def one():
    return 1


def two():
    return 2


def gen(n):
    for i in range(n):
        yield i


def boom():
    raise ValueError("boom")


async def work(tag, d):
    await asyncio.sleep(d)
    return tag


def slow(d):
    time.sleep(d)
    return d


def child_work():
    return other.deep(5)


def pre_exec():
    return one()


def exec_child():
    os.execv(sys.executable, [sys.executable, "-m", "fakesvc.execd"])


def gen_cleanup():
    try:
        yield 1
        yield 2
    finally:
        other.deep(9)             # 被 close() 时（经 throw 进来）调的：调用方应当是这个生成器


async def serve_cancel():
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        other.deep(7)             # 被取消时（经 throw 进来）调的
        raise


async def handle2(n):
    other.deep(n)
    await asyncio.sleep(0.01)
    other.deep(n)


def regen_after(g):
    # g 是别处跨文件起的、已经挂起的 gen；在这里丢掉它（它的帧对象随之释放），紧接着在同文件里
    # 起一个同一函数的生成器——新帧的对象多半落在刚释放的地址上。它没有调用行，不能接上旧 span
    del g
    return list(gen(3))
