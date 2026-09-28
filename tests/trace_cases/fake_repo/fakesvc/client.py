"""发几个并发请求。"""
import argparse
import asyncio


async def one(port: int, text: str) -> str:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write((text + "\n").encode())
    await w.drain()
    out = (await r.readline()).decode().strip()
    w.close()
    return out


async def main(port: int, n: int) -> None:
    outs = await asyncio.gather(*(one(port, f"hello world {i} abc") for i in range(n)))
    assert all(outs), outs
    print("client:", len(outs), "个请求都有回复")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main(a.port, a.n))
