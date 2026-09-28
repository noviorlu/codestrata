---
written_by: claude-opus-5-5
target: codestrata.__main__
kind: package
code_sha: 4e5d0c077c283fd0
status: draft
refs: __main__.py:271@ec9fb5ef,__main__.py:203@d41c8ef6,__main__.py:48@e2f11b2b,__main__.py:60@d89a80ca,__main__.py:65@0c3e9807,__main__.py:196@4c85e081
---

## 是什么
命令行入口：`scan` / `trace` / `serve` / `graph` / `tasks` / `pack` / `note` / `check` 八个子命令，每个都是一两行把参数转交给对应模块。`scan` 一次写出三份产物：index.json、symbols.json，以及给全文窗口 Ctrl+点击用的交叉引用 xref.json。

## 为什么这样切
它是唯一的入口层（高度 +1）：依赖几乎所有模块、没有人依赖它。它刻意保持薄——每个 `cmd_*` 只负责解析路径、调一个模块函数、打印摘要，逻辑都在下面。这也是为什么图上它的出边多、而且没有一条是虚线：每条都真的引用了对方的函数（新加的 `xref` 也一样，`cmd_scan` 直接调它的 `build` / `write`）。

## 读法
1. 模块 docstring —— 子命令一览
2. `main` —— argparse 的搭法，重点看最后切 `--` 那段
3. `cmd_scan` —— 最常用的子命令，也是看「默认切面拆了什么」、各份产物在哪一步写出的地方
4. 其余 `cmd_*` 按需看，都很短

## 关键算法
### 自己按第一个 `--` 切 argv
`trace . --case X -- python demo.py` 里，`--` 之后的整条命令要原样交给被 trace 的进程。argparse 的 REMAINDER 和可选位置参数放在一起时会互相抢参数（会报 `--case` 缺失），所以 `main` 先自己按第一个 `--` 切开（__main__.py:271），前半给 argparse，后半直接当命令。

### 子命令的 dest 不能叫 `cmd`
`trace` 的位置参数叫 `cmd`，subparsers 的 dest 也叫 `cmd` 的话两者会互相覆盖，所以叫 `which`（__main__.py:203）。

### scan 和 trace 的两个开关
`scan --depth` 默认是 `auto`（按规模自动拆分），给数字就是固定深度；`scan --expand DIR`（可重复）在默认切面上额外展开某个目录。两者都只影响**默认切面**，不影响扫描出来的数据——图上随时还能展开 / 收起。`trace` 会从 `--roots` 或自动探测的包根算出「顶层包 → 仓库内目录」交给 `trace.run`，被 trace 的命令跑的若是 pip 安装的那份，就靠它映射回仓库。

### scan 的摘要按默认切面打印
`cmd_scan` 打印的节点数、高度列表都是默认切面上的（`cut.visible` 过滤掉只有空 `__init__.py` 的目录），并列出自动拆开了哪些目录、各占全仓多少代码（__main__.py:48 起）。早先「包太少就把 depth 加深」的做法被 `cut.default_open` 的 `MIN_NODES` 取代：小仓库先不看比例把最大的拆开。`tasks` 的分母同样是默认切面上的节点加总览，不是文件数。

### 交叉引用在 scan 里建，不在 serve 里建
写完 index 之后，`cmd_scan` 紧接着用同一份 `idx` 调 `xref.build`、再 `xref.write` 到同一个 .codestrata 目录（__main__.py:60），并打印能解析的名字总数。放在 scan 而不是 serve 启动时算，理由写在注释里：它和符号表是**同一时刻的快照**，行号才对得上——xref 里的定义位置、token 的行列号要和 index / symbols 指向同一版源码。serve 端只读不建：`payload.load_xref` 按修改时间缓存，文件不存在就返回 None（前端不给 Ctrl+点击），所以没重新 scan 的老仓库照样能打开，只是少了跳转；重新 scan 之后下一次请求自动换成新的。scan 之后又改过的单个文件，由 xref 里记的指纹（`payload._stale`）认出来、不给链接。代价是 scan 变慢：`xref.build` 要把全仓再 parse 两遍。

## 局限
- `cmd_scan` 里 `x` 先绑成 xref 的结果，下面高度列表的循环又把 `x` 当成节点复用（__main__.py:65）；打印计数时生成器里的 `v` 也和外面的切面 `v` 同名。都不出错（xref 在循环前已经用完，生成器有自己的作用域），但读的时候容易看串。

## 不确定
- `cmd_serve` 在函数体内才 `from . import serve`（__main__.py:196），代码里没写原因；推测是让不启动服务的子命令不必加载 `http.server`，但不能确认。静态扫描照样把它算成一条边。
