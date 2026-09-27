---
written_by: claude-opus-5-5
target: codestrata.trace
kind: package
code_sha: 897f9f7ce69b0979
status: draft
refs: trace.py:1@65dc008a,trace.py:42@971f709d,trace.py:194@6cf25a9e,trace.py:153@064c41d5,trace.py:146@c90d778b,trace.py:55@a4a1339f,trace.py:80@c744b643,trace.py:123@3c8a7439,trace.py:96@158ddf0b
---

## 是什么
runtime 一侧：在 hook 下跑一个真实 case（仓库自带的 demo / example），记录**函数粒度**的 caller→callee，再折算成能叠在总图同一套坐标上的包级数据，以及每条包间边上「谁调了谁几次」的明细。

## 为什么这样切
和 `scan` 对称：`scan` 回答「代码里写了什么」，它回答「这次真的跑了什么」。两者都只产出数据、互不依赖（都是叶子）。录制（`run` / `merge`）和解读录制结果（`to_package_graph`）分开：前者只在 `trace` 子命令时跑，后者由 `payload.load_hot` 在每次加载时现算——因为折算要用**当前**的 index，scan 重跑后旧 trace 也能重新映射。

## 读法
1. 模块 docstring（trace.py:1）——三个必须处理的问题：多进程、开销、调用者要对
2. `_SITECUSTOMIZE`（trace.py:42）——被注入到每个子进程里的那段代码，按 `_rel` → `_key` → `_enter` / `_leave` → 回调注册 的顺序读
3. `run` —— 怎么注入、怎么收
4. `merge` —— 多进程的 part 文件合并
5. `to_package_graph` —— 函数粒度 → 包粒度 + 边的调用明细
6. `file_shas` / `stale_files` —— trace 的过期检测

## 关键算法
### 用 sitecustomize 覆盖子进程
vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。`run` 把一个临时目录插到 `PYTHONPATH` 最前面（trace.py:194），里面放 `sitecustomize.py`：**每个**新起的 Python 进程都会自动 import 它，于是自动挂 hook、按 pid 写一份 part，最后 `merge` 合并。

### 调用栈要进出都订阅
只订阅 `PY_START` 的话，调用者会变成「上一个开始执行的函数」——A 调 B、B 返回、A 再调 C 会被记成 B→C。所以订阅 `PY_START`/`PY_RESUME` 入栈、`PY_RETURN`/`PY_YIELD`/`PY_UNWIND` 出栈（trace.py:153）；`PY_RESUME` 入栈但不计数（生成器恢复不是一次新调用）；`PY_UNWIND` 不能返回 DISABLE（trace.py:146）。仓库外的代码第一次命中就返回 DISABLE，之后不再回调，这是开销低的原因。

### 缓存按文件名，不按 code 对象
`_rel` 的缓存键是 `co_filename`（trace.py:55）。code 对象按**内容**比较相等且不比文件名，按 code 对象缓存会把几个空 `__init__.py`、或不同文件里同名同行同体的函数认成同一个。

### 模块顶层记成第 0 行
模块 code 的 firstlineno 是 1，会和写在第 1 行的函数撞键（trace.py:80）。解析端对老 trace 保留兼容：第 1 行且那里没有符号才当模块。

### 折算时分开「调用」和「import 触发的执行」
被调方是模块帧的边不算调用，单独记进 `edge_import_exec`；否则每条 import 边都会因为「导入过」被染成橙色，只被 import 过的包也会显示成「跑到了」。没有自己符号的帧（闭包、lambda、生成器表达式）用符号的起止行归到最内层的外层符号，标成 `外层.<L行号>`（`to_package_graph` 里的 `label`）。装饰过的函数 firstlineno 指向第一个装饰器，所以 def 行和装饰器行都建了索引。

### trace 也会过期
trace 以 `文件:行号` 为键，代码一改就对不上。录制时存每个涉及文件的哈希（`file_shas`），加载时比对，前端据此提示「录制后有 N 个文件改动过」。

## 已知限制
- 数据在进程退出时由 `atexit` 写盘（trace.py:123）。被 SIGKILL、或调用 `os._exit` 退出的进程**不会**跑 atexit，它的调用就丢了——多进程框架常这样结束工作进程，trace 它们时要留意 part 文件数是否等于进程数。
- 栈深超过 2000 时砍掉一半兜底（trace.py:96），极深递归下调用者可能不准。
