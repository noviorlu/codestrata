---
written_by: claude-opus-5-5
target: codestrata.trace
kind: package
code_sha: 90b7ff0901547027
status: draft
refs: trace.py:1@65dc008a,trace.py:49@971f709d,trace.py:287@6cf25a9e,trace.py:238@064c41d5,trace.py:231@c90d778b,trace.py:214@f1b535c0,trace.py:82@cf21a031,trace.py:68@da61d85c,trace.py:101@c744b643,trace.py:173@380940f5,trace.py:199@39c6dbe6,trace.py:135@1d891628,trace.py:117@158ddf0b
---

## 是什么
runtime 一侧：在 hook 下跑一个真实 case（仓库自带的 demo / example，或者起一个服务再发请求），记录**函数粒度**的 caller→callee，再折算成能叠在总图同一套坐标上的包级数据，以及每条包间边上「谁调了谁几次」的明细。

## 为什么这样切
和 `scan` 对称：`scan` 回答「代码里写了什么」，它回答「这次真的跑了什么」。两者都只产出数据、互不依赖（都是叶子）。录制（`run` / `merge`）和解读录制结果（`to_package_graph`）分开：前者只在 `trace` 子命令时跑，后者由 `payload.load_hot` 在每次加载时现算——因为折算要用**当前**的 index，scan 重跑（比如换了 `--expand`）后旧 trace 也能重新映射。

## 读法
1. 模块 docstring（trace.py:1）——三个必须处理的现实问题：多进程（含子进程落盘和分阶段）、开销、调用者要对
2. `_SITECUSTOMIZE`（trace.py:49）——被注入到每个 Python 子进程里的那段代码。按 `_rel` → `_key` → `_enter` / `_leave` → 落盘（`_dump`、拦截 `os._exit`、后台线程、fork 后清零）→ 阶段快照 → 回调注册 的顺序读
3. `run` —— 怎么注入、怎么收、怎么核对安装包
4. `merge` —— 多进程、多阶段的合并
5. `to_package_graph` —— 函数粒度 → 包粒度 + 边的调用明细
6. `file_shas` / `stale_files` —— trace 的过期检测

## 关键算法
### 用 sitecustomize 覆盖子进程
vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。`run` 把一个临时目录插到 `PYTHONPATH` 最前面（trace.py:287），里面放 `sitecustomize.py`：**每个**新起的 Python 进程都会自动 import 它，于是自动挂 hook、按 pid 写一份 part，最后 `merge` 合并。

### 调用栈要进出都订阅
只订阅 `PY_START` 的话，调用者会变成「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。所以订阅 `PY_START`/`PY_RESUME` 入栈、`PY_RETURN`/`PY_YIELD`/`PY_UNWIND` 出栈（trace.py:238）；`PY_RESUME` 入栈但不计数；`PY_UNWIND` 不能返回 DISABLE（trace.py:231）。仓库外的代码第一次命中就返回 DISABLE，之后不再回调，这是开销低的原因。工具号先取 4、3，最后才用 `PROFILER_ID`——3.12 起 cProfile 也走 sys.monitoring，占了它，被 trace 的程序一用 cProfile 就报错（trace.py:214）。

**「调用方」是最近的仓库内的帧。** 仓库外的帧不记录，所以 A → 仓库外的框架 → B 会记成 A → B。在 vllm-omni 上，调度器被调用时中间隔着 vLLM 的 busy loop，hot 图上显示成被 stage 进程的入口函数直接调用。

### 跑的是安装包也能映射回来
被 trace 的往往是 pip 装进 site-packages 的那份。`_rel` 在路径落在仓库外时，看它是不是 `site-packages/<顶层包>/…`，是就按 `CODESTRATA_PKGS`（顶层包 → 仓库内目录）映射回仓库路径（trace.py:82 起）。`run` 结束后逐个比对映射过的文件和仓库里同名文件的内容：不一致的报「行号不可信」，仓库里根本没有的（构建时生成的 `_version.py` 之类）单独列出，不算不一致。

缓存按文件名、不按 code 对象（trace.py:68）：code 对象按**内容**比较相等且不比文件名，几个空 `__init__.py` 会被认成同一个。模块顶层记成第 0 行（trace.py:101），否则和写在第 1 行的函数撞键。

### 子进程的数据不能丢
atexit 不是总会跑：multiprocessing 的 fork 子进程以 `os._exit` 结束，被 SIGKILL 的进程什么都不跑。所以拦下 `os._exit` 先落盘，后台线程每 10 秒原子地落一次盘（先写临时文件再 rename），强杀最多丢最后 10 秒（trace.py:173 起）。fork 出的子进程继承父进程的计数，不清零就会把父进程 fork 前的调用再算一遍，所以 fork 后清零、重启落盘线程（trace.py:199 起）。

### 分阶段
被 trace 的命令往 `$CODESTRATA_OUT/PHASE` 写一个名字（比如服务就绪后写 `serving`），每个进程 1 秒内看到，就给切换前的累计计数拍一张快照（trace.py:135 起）。`merge` 按进程把相邻快照相减得到每个阶段的调用，于是 `--hot case@serving` 能只看处理请求的那一段，启动时的初始化（注册表探测、模型加载、CUDA graph 捕获）不会混进「请求走了哪条路」。

### 折算时分开「调用」和「import 触发的执行」
被调方是模块帧的边不算调用，单独记进 `edge_import_exec`；否则每条 import 边都会因为「导入过」被染成橙色。没有自己符号的帧（闭包、lambda、生成器表达式）按符号的起止行归到最内层的外层符号，标成 `外层.<L行号>`。

## 已知限制
- 栈深超过 2000 时砍掉一半兜底（trace.py:117），极深递归下调用者可能不准。
- 阶段切换最多有 1 秒的延迟：case 脚本写完 `PHASE` 后应等一两秒再开始下一段。
