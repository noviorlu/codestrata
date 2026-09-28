"""并发触发 --phase（测输家跟着切、切的时候别的线程的调用不丢）：
主进程 fork 一个子进程，两边用 Barrier 对齐、同时第一次调 work.compute；
之后主进程里 4 个线程同时第一次调 work.load_weight。"""
import multiprocessing as mp
import threading

from fakesvc import work


def both(bar) -> None:
    bar.wait()
    work.compute(1)


def main() -> None:
    ctx = mp.get_context("fork")
    bar = ctx.Barrier(2)
    p = ctx.Process(target=both, args=(bar,))
    p.start()
    both(bar)
    p.join()
    tb = threading.Barrier(4)

    def go() -> None:
        tb.wait()
        work.load_weight(2)
    ts = [threading.Thread(target=go) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("race: done")


if __name__ == "__main__":
    main()
