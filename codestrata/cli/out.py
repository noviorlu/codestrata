"""给 agent 的命令的输出：同一份结果渲染成文字（给模型读）或 JSON 信封（给命令串），错误兜底，命令行引号。

信封：{v, ok, cmd, repo, ref, data, more, warnings, next, algo}；出错时 {v, ok: false, cmd, error: {code, msg, candidates}, next}。
stdout 上只有一个 JSON。文字输出的每条下一步都按 shell 规矩加好引号，原样粘贴就能跑。
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import CodestrataError

V = 1
_REPO_POSITIONAL = {"scan", "runs", "serve", "trace"}


def command(*parts: str, repo: Path | None = None) -> str:
    """一条能原样粘贴的命令：codestrata 子命令 [-C 仓库] 参数…（每个参数按 shell 规矩加引号）"""
    head, rest = list(parts[:1]), list(parts[1:])
    if repo is not None:
        # 老命令的仓库是第一个位置参数（scan / runs / serve），新命令用 -C
        rest = ([str(repo)] if head and head[0] in _REPO_POSITIONAL else ["-C", str(repo)]) + rest
    return shlex.join(["codestrata"] + head + rest)


def step(effect: str, *parts: str, repo: Path | None = None, why: str = "") -> dict:
    """next 里的一条：{cmd, effect, why}"""
    d = {"cmd": command(*parts, repo=repo), "effect": effect}
    if why:
        d["why"] = why
    return d


@dataclass
class Result:
    """一个命令的结果。text 是给模型读的几行（不含 下一步 / 警告，由 emit 统一加）"""
    data: dict
    text: list[str]
    repo: Path | None = None
    ref: dict | None = None            # {text, slices_us, lanes}
    next: list[dict] = field(default_factory=list)
    more: dict | None = None           # {shown, total, how}
    warnings: list[dict] = field(default_factory=list)
    algo: str | None = None


def emit(cmd: str, res: Result, as_json: bool) -> int:
    if as_json:
        env = {"v": V, "ok": True, "cmd": cmd, "repo": str(res.repo) if res.repo else None, "ref": res.ref,
               "data": res.data, "more": res.more, "warnings": res.warnings, "next": res.next}
        if res.algo:
            env["algo"] = res.algo
        _dump(env)
        return 0
    lines = list(res.text)
    for w in res.warnings:
        lines.append(f"⚠ {w['msg']}")
    if res.more:
        lines.append(f"（给了 {res.more['shown']} / 共 {res.more['total']}；要更多：{res.more['how']}）")
    if res.next:
        lines.append("下一步")
        width = max(len(n["cmd"]) for n in res.next)
        for n in res.next:
            lines.append(f"  {n['cmd'].ljust(width)}  （{n['effect']}{'：' + n['why'] if n.get('why') else ''}）")
    print("\n".join(lines))
    return 0


def fail(cmd: str, err: CodestrataError, as_json: bool) -> int:
    if as_json:
        _dump({"v": V, "ok": False, "cmd": cmd,
               "error": {"code": err.code, "msg": err.msg, "candidates": err.candidates}, "next": err.next})
    else:
        lines = [f"codestrata {cmd}: {err.msg}  [{err.code}]"]
        if err.candidates:
            lines.append("候选：")
            lines += [f"  {c}" for c in err.candidates[:20]]
            if len(err.candidates) > 20:
                lines.append(f"  …共 {len(err.candidates)} 个")
        for n in err.next:
            lines.append(f"下一步：{n['cmd']}  （{n['effect']}）")
        print("\n".join(lines), file=sys.stderr)
    return err.exit


def run(cmd: str, fn, a) -> int:
    """跑一个命令：CodestrataError 按码退出；库里老的 SystemExit(字符串) 兜成 internal"""
    as_json = bool(getattr(a, "json", False))
    try:
        res = fn(a)
    except CodestrataError as e:
        return fail(cmd, e, as_json)
    except SystemExit as e:
        if isinstance(e.code, int) or e.code is None:
            raise
        return fail(cmd, CodestrataError("internal", str(e.code)), as_json)
    return emit(cmd, res, as_json)


def _dump(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def secs(us: int | None, base: int) -> str:
    """文字里的时刻：从 base 算的 +秒（三位小数）"""
    if us is None:
        return "?"
    return f"{'+' if us >= base else '-'}{abs(us - base) / 1e6:.3f}"


def dur(us: int) -> str:
    return f"{us / 1e6:.3f} s" if us >= 1_000_000 else f"{us / 1e3:.1f} ms"


class Parser(argparse.ArgumentParser):
    """命令行带了 --json 时，用法错也在 stdout 给一个信封（code=usage），退出码仍是 2"""
    json_errors = False
    json_cmd: str | None = None

    def error(self, message):
        if Parser.json_errors:
            cmd = self.prog.removeprefix("codestrata").strip() or Parser.json_cmd
            _dump({"v": V, "ok": False, "cmd": cmd, "error": {"code": "usage", "msg": message, "candidates": []},
                   "next": []})
            sys.exit(2)
        super().error(message)
