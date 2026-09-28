"""假服务：起一个 multiprocessing 工作进程，exec 一次，监听端口处理请求，Ctrl+C（SIGINT）优雅退出。

FAKE_IGNORE_INT=1 时忽略 SIGINT（测 driver 升级到 SIGTERM）。
"""
import argparse
import asyncio
import multiprocessing as mp
import os
import signal
import sys

from fakesvc import work


async def serve(port: int, ready: str) -> None:
    ctx = mp.get_context("fork")
    q_in, q_out = ctx.Queue(), ctx.Queue()
    proc = ctx.Process(target=work.worker_loop, args=(q_in, q_out), daemon=True)
    proc.start()
    lock = asyncio.Lock()
    loop = asyncio.get_running_loop()

    async def submit(x: int) -> int:
        async with lock:
            q_in.put(x)
            return await loop.run_in_executor(None, q_out.get)

    async def on_conn(reader, writer):
        line = (await reader.readline()).decode().strip()
        writer.write((await work.handle(line, submit) + "\n").encode())
        await writer.drain()
        writer.close()

    srv = await asyncio.start_server(on_conn, "127.0.0.1", port)
    with open(ready, "w") as f:
        f.write(str(os.getpid()))
    try:
        async with srv:
            await srv.serve_forever()
    finally:
        q_in.put(None)
        proc.join(timeout=5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--ready", required=True)
    a = ap.parse_args()
    # 非交互 bash 用 & 起的进程天生忽略 SIGINT；真服务（uvicorn）会自己装处理器，这里照做
    signal.signal(signal.SIGINT, signal.SIG_IGN if os.environ.get("FAKE_IGNORE_INT") == "1"
                  else signal.default_int_handler)
    work.init_model()
    work.exec_self()
    try:
        asyncio.run(serve(a.port, a.ready))
    except KeyboardInterrupt:
        print("server: 收到 SIGINT，退出", file=sys.stderr)


if __name__ == "__main__":
    main()
