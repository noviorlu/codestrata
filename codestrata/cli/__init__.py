"""给 agent（和人）用的读命令：一张命令表，argparse 的注册、`guide` 的速查、`guide --json` 都从它来。

每个命令一个模块，模块里有 NAME、EFFECT、DOES、USAGE、EXAMPLE、add_args(p)、run(a) -> out.Result。
老命令（scan / trace / runs / serve / app）还在 __main__.py 里，表里只登记它们的 effect，供 guide 用。
"""
from __future__ import annotations

from . import explain, find, guide, lanes, links, out, path, runs, segments, status, steps, trace  # noqa: F401  （runs、trace：__main__ 用）

COMMANDS = [status, lanes, segments, steps, links, find, explain, path, guide]

# 老命令的 effect（§ 契约「effect」）：guide 和 --help 用
OLD = [
    {"name": "runs ls / show / wait", "effect": "read", "does": "列出 run、看一个 run 的详情和复刻命令（--json 带各阶段的微秒窗口）；等还在录的 run 录完"},
    {"name": "runs tag / untag / note / merge", "effect": "write", "does": "改 run 的标签、备注；从原始数据重算"},
    {"name": "runs rm", "effect": "delete", "does": "删 run（不能重建）"},
    {"name": "scan", "effect": "write", "does": "静态扫描，重写索引"},
    {"name": "trace", "effect": "record", "does": "跑被录的程序（可能占 GPU、跑很久）"},
    {"name": "serve / app", "effect": "start", "does": "起常驻的本地服务、占端口"},
]


def register(sub) -> None:
    """把表里的命令注册进 argparse 的 subparsers"""
    for m in COMMANDS:
        p = sub.add_parser(m.NAME, help=f"{m.DOES}（{m.EFFECT}）", description=f"{m.DOES}\n\n用法：{m.USAGE}\n例：{m.EXAMPLE}",
                           formatter_class=_raw())
        p.add_argument("-C", dest="C", default=None, metavar="目录", help="仓库目录（省掉时按 REF 里的页面地址、run id 找，再从当前目录往上找）")
        p.add_argument("--json", action="store_true", help="打印 JSON 信封")
        m.add_args(p)
        p.set_defaults(fn=lambda a, m=m: out.run(m.NAME, m.run, a))


def _raw():
    import argparse
    return argparse.RawDescriptionHelpFormatter


def table() -> list[dict]:
    """命令表（guide --json、以后的 MCP）"""
    rows = [{"name": m.NAME, "effect": m.EFFECT, "does": m.DOES, "usage": m.USAGE, "example": m.EXAMPLE} for m in COMMANDS]
    return rows + [dict(r, usage=None, example=None) for r in OLD]
