"""服务里真正干活的函数：被 trace 记下来的就是它们。"""
import asyncio
import os
import sys


def init_model(n: int = 3) -> int:
    return sum(load_weight(i) for i in range(n))


def load_weight(i: int) -> int:
    return i * i


def compute(x: int) -> int:
    return x * 2 + 1


def worker_loop(q_in, q_out) -> None:
    """multiprocessing 子进程（像 vllm 的 engine core）：从队列取活、算完送回。"""
    while True:
        x = q_in.get()
        if x is None:
            break
        q_out.put(compute(x))


def pre_exec() -> int:
    return compute(7)


def exec_self() -> None:
    """fork 一个子进程，先跑一点仓库代码，再 exec 成另一个程序（测 exec 前的数据不丢）。"""
    pid = os.fork()
    if pid == 0:
        pre_exec()
        os.execv(sys.executable, [sys.executable, "-m", "fakesvc.execd"])
    os.waitpid(pid, 0)


def after_exec() -> int:
    return load_weight(5)


async def tokenize(text: str) -> list[str]:
    await asyncio.sleep(0.01)
    return text.split()


async def handle(text: str, submit) -> str:
    """一个请求：同一线程里的协程交错执行（像 API server）。"""
    toks = await tokenize(text)
    outs = []
    for t in toks:
        outs.append(await submit(len(t)))
        await asyncio.sleep(0.005)
    return " ".join(map(str, outs))


# 示例：env PATH=/usr/bin:/bin python -m fakesvc.server（graph --public 不能改源码里这种写法）
