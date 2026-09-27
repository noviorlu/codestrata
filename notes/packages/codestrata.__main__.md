---
written_by: claude-opus-5-5
target: codestrata.__main__
kind: package
code_sha: f65e0f2472690658
status: draft
refs: __main__.py:266@ec9fb5ef,__main__.py:199@d41c8ef6,__main__.py:48@551969ee,__main__.py:192@4c85e081
---

## 是什么
命令行入口：`scan` / `trace` / `serve` / `graph` / `tasks` / `pack` / `note` / `check` 八个子命令，每个都是一两行把参数转交给对应模块。

## 为什么这样切
它是唯一的入口层（高度 +1）：依赖几乎所有模块、没有人依赖它。它刻意保持薄——每个 `cmd_*` 只负责解析路径、调一个模块函数、打印摘要，逻辑都在下面。这也是为什么图上它的出边多、而且没有一条是虚线：每条都真的引用了对方的函数。

## 读法
1. 模块 docstring —— 子命令一览
2. `main` —— argparse 的搭法，重点看最后切 `--` 那段
3. `cmd_scan` + `_resolve_depth` —— 最常用的子命令
4. 其余 `cmd_*` 按需看，都很短

## 关键算法
### 自己按第一个 `--` 切 argv
`trace . --case X -- python demo.py` 里，`--` 之后的整条命令要原样交给被 trace 的进程。argparse 的 REMAINDER 和可选位置参数放在一起时会互相抢参数（会报 `--case` 缺失），所以 `main` 先自己按第一个 `--` 切开（__main__.py:266），前半给 argparse，后半直接当命令。

### 子命令的 dest 不能叫 `cmd`
`trace` 的位置参数叫 `cmd`，subparsers 的 dest 也叫 `cmd` 的话两者会互相覆盖，所以叫 `which`（__main__.py:199）。

### scan 和 trace 的两个开关
`scan --expand PKG`（可重复）把大包按子目录拆开；`trace` 会从 `--roots` 或自动探测的包根算出「顶层包 → 仓库内目录」交给 `trace.run`，被 trace 的命令跑的若是 pip 安装的那份，就靠它映射回仓库。

### depth 自动加深
`_resolve_depth` 从 depth=2 开始试，包数不到 4 就加深到 3、4（__main__.py:48）。所有代码都在一个子包里的仓库在 depth=2 下只有一个节点，没有图可看。

## 不确定
- `cmd_serve` 在函数体内才 `from . import serve`（__main__.py:192），代码里没写原因；推测是让不启动服务的子命令不必加载 `http.server`，但不能确认。静态扫描照样把它算成一条边。
