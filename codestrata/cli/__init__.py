"""给 agent（和人）用的读命令：一张命令表，argparse 的注册从它来。

每个命令一个模块，模块里有 NAME、EFFECT、DOES、USAGE、EXAMPLE、add_args(p)、run(a) -> out.Result。
老命令（scan / trace / runs / serve / app）还在 __main__.py 里。
"""
from __future__ import annotations

from . import explain, links, out, path, runs, status, view  # noqa: F401  （runs：__main__ 用）

COMMANDS = [status, links, explain, path, view]


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
