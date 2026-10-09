"""codestrata guide：给 agent 的一页速查（≤ 80 行）。第一次见 codestrata 的 agent 读这一页就够。
命令那一节从命令表生成，只写已经有的命令。"""
from __future__ import annotations

from ..errors import EXIT
from . import out

NAME = "guide"
EFFECT = "read"
DOES = "给 agent 的一页速查：REF 写法、引号、JSON 信封、错误码、各命令的副作用、常见任务的命令序列"
USAGE = "codestrata guide [--skill] [--json]"
EXAMPLE = "codestrata guide"


def add_args(p) -> None:
    p.add_argument("--skill", action="store_true", help="打出 Claude Code skill 文件（SKILL.md）的内容")


REF_GRAMMAR = """\
REF = '页面地址' | RUN[@范围][/列,…]
  RUN   完整 run id 或 case 名（case 取最新一次录完的）。不收 run id 前缀
  范围  阶段名 | t=起-止（从 run 起点算的微秒；也收 t=78.024s-80.492s）| 阶段+起s-止s（从阶段开头算，如 serving+0.614s-3.082s）
  列    进程别名/线程（stage1/MainThread）；只写进程 = 这个进程的所有列；进程/*、*/线程、*/gpu* 也行；逗号隔开几个
  例    run_single_prompt@serving    20261001-170349-run_single_prompt@t=78024146-80491567/stage1
  页面地址就是用户浏览器地址栏里那串（http://127.0.0.1:端口/#run=…），原样当 REF 用"""

_BODY = """\
# codestrata 速查（给 agent）

codestrata 录一个程序真实跑过的调用（trace），按进程 · 线程分列、按时间排；这些命令把录下的 run 读给你。
先跑 `codestrata status`（不给参数列出最近的 run；给 REF 看它的状态和各阶段的时刻）。

## REF
{ref}

## 引号
命令输出里的每条命令都已经加好引号，原样粘贴就能跑。自己写时：页面地址、带 | 或 # 的、带 * 的列一律加单引号。

## 命令（effect：read 随便跑；write / delete / start / record 先问用户）
{cmds}

## 输出
- 文字给你读：先汇总，末尾「下一步」是能直接粘的命令和它的 effect。默认有上限，超了会写「给了 N / 共 M」和怎么要更多。
- `--json`：stdout 只有一个 JSON：{{v, ok, cmd, repo, ref, data, more, warnings, next, algo}}；出错时 {{v, ok: false, cmd, error: {{code, msg, candidates}}, next}}。
- JSON 里的时刻一律是从 run 起点算的整数微秒（字段名带 _us）；文字里写 +秒，基准写在第一行。
- 仓库：-C 目录 > 页面地址对应的仓库 > 按 run id 在已知仓库里找 > 从当前目录往上找。不是从当前目录找到的，下一步里都带 -C。

## 退出码
{exits}
写错名字（退出码 3）一定带候选：从候选里挑，别猜。

## 常见任务
1. 用户贴来页面地址，问「现在看的是什么」：
   codestrata status '<地址>'   →   codestrata lanes '<地址>'
2. 只看一个进程有哪些线程在干活：codestrata lanes 'RUN@阶段/stage1'
3. 函数级的调用树：codestrata path [仓库] RUN@阶段（输出很长，整棵树）

## 要知道的坑
- 别为了看数据去重录（trace 是 record：可能占 GPU、跑几分钟）。数据不够先问用户。
- `--phase` 切阶段时 codestrata 会停 0.1 s，阶段开头那 0.1 s 不是被录的程序在干活。
- CUDA graph / torch.compile 替掉的模型 Python 代码不进录制；共享内存、deque、SimpleQueue、线程池 submit 的交接没录。
- 轮询的列调用多不代表在干活。
- 录到的和推出来的要分开说；codestrata 不生成解释，解释由你读代码后给。
"""

_SKILL_HEAD = """\
---
name: codestrata
description: 读 codestrata 录下的运行路径（哪个进程、哪条线程、按什么顺序调了仓库里的哪些函数）。用户提到 codestrata、贴来 http://127.0.0.1:<端口>/#run=… 的页面地址、或问一次运行里某段时间 / 某个进程在干什么时用。
---

"""


def text() -> str:
    from . import table
    rows = table()
    w = max(len(r["usage"] or r["name"]) for r in rows)
    cmds = "\n".join(f"  {(r['usage'] or 'codestrata ' + r['name']).ljust(w)}  {r['effect']:6}  {r['does']}" for r in rows)
    by: dict[int, list[str]] = {}
    for code, n in EXIT.items():
        by.setdefault(n, []).append(code)
    what = {1: "意外", 2: "用法错", 3: "名字写错（带候选）", 4: "没数据 / 推断被拒", 5: "页面换不了", 6: "页面还没换（等用户）"}
    exits = "  0 成功\n" + "\n".join(f"  {n} {what[n]}：{' '.join(v)}" for n, v in sorted(by.items()))
    return _BODY.format(ref=REF_GRAMMAR, cmds=cmds, exits=exits)


def run(a) -> out.Result:
    from . import table
    body = text()
    if a.skill:
        body = _SKILL_HEAD + body
    data = {"commands": table(), "ref_grammar": REF_GRAMMAR, "errors": EXIT}
    if a.json:
        data["text"] = body
    return out.Result(data=data, text=body.rstrip("\n").split("\n"))
