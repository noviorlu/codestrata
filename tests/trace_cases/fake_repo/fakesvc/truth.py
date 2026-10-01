"""时序事件的真值场景：每个场景一个函数，都从这个文件调到 callee.py（跨文件）。
单独跑：python -m fakesvc.truth"""
import asyncio
import os
import queue
import subprocess
import sys
import threading

from fakesvc import callee


def s_nest():                 # 同步嵌套：truth → callee.mid → other.deep
    return callee.mid(1)


def s_seq():                  # 返回后再调用：调用方都是 s_seq，不是 one → two
    return callee.one() + callee.two()


def s_gen():                  # 生成器：挂起 / 恢复 3 次
    return list(callee.gen(3))


def s_exc():                  # 异常展开
    try:
        callee.boom()
    except ValueError:
        return True


async def runner(tag, d):
    return await callee.work(tag, d)


def s_async():                # 同一线程里两个协程交错：先开始的 a 先结束（按栈配对会配错）
    async def main():
        ta = asyncio.ensure_future(runner("a", 0.02))
        await asyncio.sleep(0.005)
        tb = asyncio.ensure_future(runner("b", 0.06))
        return await asyncio.gather(ta, tb)
    return asyncio.run(main())


def in_thread():              # 线程入口在仓库外（Thread.run）：要先进一个仓库里的函数，才有「调用方」
    return callee.slow(0.03)


def s_threads():              # 两个线程同时调
    ts = [threading.Thread(target=in_thread, name=f"worker-{i}") for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def s_fork():                 # fork：子进程写自己的事件文件
    pid = os.fork()
    if pid == 0:
        callee.child_work()
        os._exit(0)
    os.waitpid(pid, 0)


def s_exec():                 # exec：exec 前后各一份
    pid = os.fork()
    if pid == 0:
        callee.pre_exec()
        callee.exec_child()
    os.waitpid(pid, 0)


def s_spawn():                # exec 出来的子进程（subprocess）：父进程里记下是哪个调用起的它
    subprocess.run([sys.executable, "-c", "pass"], check=True)


def in_consumer(q):           # 另一个线程从队列里取：主线程 put 的那个对象交到这里
    return callee.take_job(q)


def s_queue():                # 进程内的队列交接：主线程 put、consumer 线程 get
    q = queue.Queue()
    t = threading.Thread(target=in_consumer, args=(q,), name="consumer")
    t.start()
    callee.put_job(q, {"job": 1})
    t.join()


def s_queue_ext():            # 只跑仓库外代码的线程（Thread(target=q.put)）把对象交给主线程
    q = queue.Queue()
    t = threading.Thread(target=q.put, args=({"job": 2},), name="stdlib-put")
    t.start()
    t.join()
    callee.take_job(q)


def s_zmq():                  # 跨进程的 ZMQ 交接（测试给了假的 zmq 才跑），照 vLLM 的收发方式：
    try:                      # 父进程的 ROUTER 发（第一帧是对方的身份）、子进程的 DEALER 收；子进程先 send 一帧带 SNDMORE、
        import zmq            # 再 send_multipart 其余的回过来，父进程收
    except ImportError:
        return
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    pid = os.fork()
    if pid == 0:
        callee.zmq_recv(zmq.Socket(rfd=r1, type=zmq.DEALER))
        callee.zmq_reply(zmq.Socket(wfd=w2, type=zmq.PUSH), [b"out", b"y" * 50, b"z"], zmq.SNDMORE)
        os._exit(0)
    callee.zmq_send(zmq.Socket(wfd=w1, type=zmq.ROUTER), [b"engine-0", b"req", b"x" * 100])
    callee.zmq_recv(zmq.Socket(rfd=r2, type=zmq.PULL))
    os.waitpid(pid, 0)


def s_loop():                 # 第一级折叠：连续 50 次调同一个叶子 → 一条 rep=50；有子调用的 mid 不合
    for _ in range(50):
        callee.one()
    for i in range(3):
        callee.mid(i)


def local_gen():              # 同文件的生成器：它的挂起 / 恢复不该被记到别的 span 头上
    yield callee.one()
    yield callee.one()


def _started_gen():
    g = callee.gen(10)
    next(g)
    return g


def s_drop():                 # 半路丢掉的生成器（3.12 上关闭时不发事件），之后帧地址被复用
    for _ in range(20):
        g = callee.gen(10)
        next(g)
        del g
    for _ in range(5):
        callee.regen_after(_started_gen())
    return list(local_gen())


def s_close():                # close() / 取消经 throw 恢复：清理代码里的调用，调用方是生成器 / 协程自己
    g = callee.gen_cleanup()
    next(g)
    g.close()

    async def main():
        t = asyncio.ensure_future(callee.serve_cancel())
        await asyncio.sleep(0.01)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    asyncio.run(main())


async def runner2(n):
    return await callee.handle2(n)


def s_async2():               # 两个协程交错，各自的子调用不能合到一起
    async def main():
        await asyncio.gather(runner2(1), runner2(2))
    asyncio.run(main())


def s_threads2():             # 先后起的线程（glibc 会复用 ident）：各有各的号和名字
    for i in range(4):
        t = threading.Thread(target=in_thread, name=f"req-{i}")
        t.start()
        t.join()


def main():
    s_drop()
    s_close()
    s_async2()
    s_threads2()
    s_loop()
    s_nest()
    s_seq()
    s_gen()
    s_exc()
    s_async()
    s_threads()
    s_fork()
    s_exec()
    s_spawn()
    s_queue()
    s_queue_ext()
    s_zmq()


if __name__ == "__main__":
    main()
