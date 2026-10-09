"""能原样粘贴的 codestrata 命令（输出里的「下一步」、候选）：每个参数按 shell 规矩加引号，带上仓库。"""
from __future__ import annotations

import shlex
from pathlib import Path

_REPO_POSITIONAL = {"scan", "serve", "trace"}     # 这几个老命令的仓库是第一个位置参数


def command(*parts: str, repo: Path | None = None) -> str:
    """codestrata 子命令 [-C 仓库] 参数…；scan / serve / trace 的仓库写成位置参数，runs 的 -C 跟在动作后面"""
    head, rest = list(parts[:1]), [str(x) for x in parts[1:]]
    if repo is not None:
        if head and head[0] in _REPO_POSITIONAL:
            rest = [str(repo)] + rest
        elif head == ["runs"]:
            rest = rest[:1] + ["-C", str(repo)] + rest[1:]
        else:
            rest = ["-C", str(repo)] + rest
    return shlex.join(["codestrata"] + head + rest)


def step(effect: str, *parts: str, repo: Path | None = None, why: str = "") -> dict:
    """下一步的一条：{cmd, effect, why}。effect 是 read / page / write / delete / start / record"""
    d = {"cmd": command(*parts, repo=repo), "effect": effect}
    if why:
        d["why"] = why
    return d
