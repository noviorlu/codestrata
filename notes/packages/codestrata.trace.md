---
written_by: claude-opus-5-5
target: codestrata.trace
kind: package
code_sha: 46c626ea19f6a2c6
status: draft
refs: trace.py:1@65dc008a,trace.py:49@971f709d,trace.py:307@90909198,trace.py:341@3f6f18ad,trace.py:294@6cf25a9e,trace.py:245@064c41d5,trace.py:238@c90d778b,trace.py:221@f1b535c0,trace.py:82@cf21a031,trace.py:68@da61d85c,trace.py:101@c744b643,trace.py:180@380940f5,trace.py:206@39c6dbe6,trace.py:167@6d98bc0c,trace.py:170@623c53f0,trace.py:171@d3b0df7e,trace.py:394@878b0b35,trace.py:168@8cbf49a2,trace.py:345@4602cd25,trace.py:352@a3749529,trace.py:135@1d891628,trace.py:532@560c650b,trace.py:117@158ddf0b
---

## 是什么
runtime 一侧：在 hook 下跑一个真实 case（仓库自带的 demo / example，或者起一个服务再发请求），记录**函数粒度**的 caller→callee，再折算成单元（文件）级的数据——图上当前切面的节点由 `payload` 再汇总——以及每条单元间边上「谁调了谁几次」的明细。同时记下「这次到底跑了什么」：每个进程的完整命令行和父进程、case 在哪个目录跑、case 脚本的原文，供 hot 图的帮助面板列出来。

## 为什么这样切
和 `scan` 对称：`scan` 回答「代码里写了什么」，它回答「这次真的跑了什么」。两者都只产出数据、互不依赖（都是叶子）。录制（`run` / `merge`）和解读录制结果（`to_package_graph`）分开：前者只在 `trace` 子命令时跑，后者由 `payload.load_hot` 在每次加载时现算——因为折算要用**当前**的 index，scan 重跑后旧 trace 也能重新映射；图上展开 / 收起也不用重新折算。

`case_script` 单独成一个函数、不埋在 `run` 里，是因为 `payload._script` 也要调它：老 trace 录制时没存脚本，加载时就读现在的文件顶上（并标明「不是录制时的内容」）。

## 读法
1. 模块 docstring（trace.py:1）——四个必须处理的现实问题：多进程（含子进程落盘）、开销、调用者要对、启动和请求分开。docstring 里的产出格式只列了主干字段，`cwd`、`script`、每个进程的 `ppid` 等是后加的，以 `run` / `merge` 的代码为准
2. `_SITECUSTOMIZE`（trace.py:49）——被注入到每个 Python 子进程里的那段代码。按 `_rel` → `_key` → `_enter` / `_leave` → 阶段快照 → 落盘（`_dump`、拦截 `os._exit`、后台线程、fork 后清零）→ 回调注册 的顺序读
3. `run` —— 怎么注入、怎么收、怎么核对安装包，以及录完补上 `cwd` 和 case 脚本（trace.py:307）
4. `case_script`（trace.py:341）—— 从命令里认出脚本文件
5. `merge` —— 多进程、多阶段的合并
6. `to_package_graph` —— 函数粒度 → 单元（文件）粒度 + 边的调用明细
7. `file_shas` / `stale_files` —— trace 的过期检测

## 关键算法
### 用 sitecustomize 覆盖子进程
vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。`run` 把一个临时目录插到 `PYTHONPATH` 最前面（trace.py:294），里面放 `sitecustomize.py`：**每个**新起的 Python 进程都会自动 import 它，于是自动挂 hook、按 pid 写一份 part，最后 `merge` 合并。

### 调用栈要进出都订阅
只订阅 `PY_START` 的话，调用者会变成「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。所以订阅 `PY_START`/`PY_RESUME` 入栈、`PY_RETURN`/`PY_YIELD`/`PY_UNWIND` 出栈（trace.py:245）；`PY_RESUME` 入栈但不计数；`PY_UNWIND` 不能返回 DISABLE（trace.py:238）。仓库外的代码第一次命中就返回 DISABLE，之后不再回调，这是开销低的原因。工具号先取 4、3，最后才用 `PROFILER_ID`——3.12 起 cProfile 也走 sys.monitoring，占了它，被 trace 的程序一用 cProfile 就报错（trace.py:221）。

**「调用方」是最近的仓库内的帧。** 仓库外的帧不记录，所以 A → 仓库外的框架 → B 会记成 A → B。在 vllm-omni 上，调度器被调用时中间隔着 vLLM 的 busy loop，hot 图上显示成被 stage 进程的入口函数直接调用。

### 跑的是安装包也能映射回来
被 trace 的往往是 pip 装进 site-packages 的那份。`_rel` 在路径落在仓库外时，看它是不是 `site-packages/<顶层包>/…`，是就按 `CODESTRATA_PKGS`（顶层包 → 仓库内目录）映射回仓库路径（trace.py:82 起）。`run` 结束后逐个比对映射过的文件和仓库里同名文件的内容：不一致的报「行号不可信」，仓库里根本没有的（构建时生成的 `_version.py` 之类）单独列出，不算不一致。

缓存按文件名、不按 code 对象（trace.py:68）：code 对象按**内容**比较相等且不比文件名，几个空 `__init__.py` 会被认成同一个。模块顶层记成第 0 行（trace.py:101），否则和写在第 1 行的函数撞键。

### 子进程的数据不能丢
atexit 不是总会跑：multiprocessing 的 fork 子进程以 `os._exit` 结束，被 SIGKILL 的进程什么都不跑。所以拦下 `os._exit` 先落盘，后台线程每 10 秒原子地落一次盘（先写临时文件再 rename），强杀最多丢最后 10 秒（trace.py:180 起）。fork 出的子进程继承父进程的计数，不清零就会把父进程 fork 前的调用再算一遍，所以 fork 后清零、重启落盘线程（trace.py:206 起）。

### 每个进程记完整命令行和父进程
帮助面板要列出「被 trace 的进程各是什么命令」。早先 part 里只存 sys.argv 的前 6 个，参数一长就看不全；而且 sys.argv 本身就缺东西——没有解释器，`python -c` 时代码也不在里面（multiprocessing spawn 出的子进程正是这样起的）。现在 `_dump` 读 /proc/self/cmdline（trace.py:167），按 NUL 切开，每个参数截到 400 字符、最多 60 个；读不到（非 Linux）就退回解释器路径加 sys.argv（trace.py:170）。同时存 `ppid`（trace.py:171），`merge` 原样带进 `pids`（trace.py:394）。

**模板里的 NUL 要双重转义。** `_SITECUSTOMIZE` 是普通（非 raw）的三引号字符串，所以源码里写的是 `split(b"\\0")`（trace.py:168），写进 `sitecustomize.py` 后才是 `b"\0"`。要是只写一个反斜杠，模板里就是一个真的 NUL 字节，生成的文件编译时报「source code cannot contain null bytes」，每个进程的 sitecustomize 都导入失败——整次 trace 什么都录不到。改这段模板时凡是反斜杠转义都要这样多写一层。

`ppid` 眼下在加载侧只有一个用途：`payload._procs` 靠「part 里有没有 `ppid`」判断这是不是新版录的 trace，老版的命令只有前 6 个参数，界面上会标出「被截断」，免得读者以为命令就这么长。

### 存下 case 脚本
光一句 `bash ../../trace_case.sh` 看不出起了什么服务、跑的是哪个 demo / benchmark、带了什么参数，所以 `run` 录完把脚本原文一并存进 trace 的 `script`（`path` 是命令里的原样写法，`text` 是内容）。存原文而不是只存路径：脚本之后会改，存下来的才是这次真正跑的。

`case_script` 的认法（trace.py:345 起）：依次看命令里的每个参数，跳过以 `-` 开头的选项；相对路径按仓库根解析——`run` 就是在仓库根下起的命令，所以 trace 里也记下 `cwd`（trace.py:307）；是文件、小于 200 KB、后缀是 .sh / .bash / .py / .zsh 或没有后缀的才算，没后缀的还得以 `#!` 开头（trace.py:352），这样 `bash`、`python` 这类解释器名和二进制都会被跳过。取第一个命中的。

### 分阶段
被 trace 的命令往 `$CODESTRATA_OUT/PHASE` 写一个名字（比如服务就绪后写 `serving`），每个进程 1 秒内看到，就给切换前的累计计数拍一张快照（trace.py:135 起）。`merge` 按进程把相邻快照相减得到每个阶段的调用，于是 `--hot case@serving` 能只看处理请求的那一段，启动时的初始化（注册表探测、模型加载、CUDA graph 捕获）不会混进「请求走了哪条路」。

### 按文件汇总
`to_package_graph` 还按文件汇总调用次数（trace.py:532，同样不算 import 触发的模块执行），详情面板的文件树据此在目录、文件上标出这次 case 走了哪里。

### 折算时分开「调用」和「import 触发的执行」
被调方是模块帧的边不算调用，单独记进 `edge_import_exec`；否则每条 import 边都会因为「导入过」被染成橙色。没有自己符号的帧（闭包、lambda、生成器表达式）按符号的起止行归到最内层的外层符号，标成 `外层.<L行号>`。

## 已知限制
- 栈深超过 2000 时砍掉一半兜底（trace.py:117），极深递归下调用者可能不准。
- 阶段切换最多有 1 秒的延迟：case 脚本写完 `PHASE` 后应等一两秒再开始下一段。
- fork 出的子进程没有自己的命令行，读到的和父进程一样，只能靠 `pid` / `ppid` 区分。命令行是每次落盘时现读的，进程若改过自己的标题（setproctitle 一类），记下的是改后的标题。
- `case_script` 是启发式：虚拟环境 bin 目录下的 console-script 入口（没后缀、有 shebang）会被当成 case 脚本，存下的只是几行包装；`python -m pkg.mod`、`bash -c "…"` 认不出脚本，就不存。

## 不确定
- `cwd` 和 `ppid` 已经录下，但目前加载侧没用 `cwd` 展示，`ppid` 也还没被用来画进程树——看起来是先把数据留住，展示以后再做。
