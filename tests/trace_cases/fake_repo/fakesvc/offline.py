"""离线 case（形状照着 vllm-omni 的 examples/offline_inference/minicpmo/end2end.py）：
Engine() 加载并 fork 一个工作进程 → generate() 把活交给工作进程 → close()。
一条阻塞的 python 命令，shell 看不到什么时候加载完——测 trace --phase 按函数切阶段。

  OFFLINE_LATE=1   close 之后主进程再调一次 work.compute（主进程第一次进它；测已经切过的阶段
                   不会被后来才第一次进这个函数的进程切回去）
"""
import multiprocessing as mp
import os

from fakesvc import work


class BaseEngine:
    def close(self) -> None:
        """继承来的方法：--phase 写 Engine.close 也要认得出是这个。"""
        self.q_in.put(None)
        self.proc.join(timeout=5)


class Engine(BaseEngine):
    def __init__(self) -> None:
        work.init_model()
        ctx = mp.get_context("fork")
        self.q_in, self.q_out = ctx.Queue(), ctx.Queue()
        self.proc = ctx.Process(target=work.worker_loop, args=(self.q_in, self.q_out), daemon=True)
        self.proc.start()

    def generate(self, xs: list[int]) -> list[int]:
        out = []
        for x in xs:
            self.q_in.put(x)
            out.append(self.q_out.get())
        return out


def make_hook():
    """嵌套函数：--phase 写 模块:make_hook.hooked（索引里的名字）也要认成 make_hook.<locals>.hooked。"""
    def hooked() -> int:
        return 1
    return hooked


def main() -> None:
    e = Engine()
    print("offline:", e.generate([1, 2, 3]))
    e.close()
    make_hook()()
    if os.environ.get("OFFLINE_LATE") == "1":
        print("offline:", work.compute(9))


if __name__ == "__main__":
    main()
