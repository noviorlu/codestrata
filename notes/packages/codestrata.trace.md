---
written_by: claude-opus-5-5
target: codestrata.trace
kind: package
code_sha: 236a421ddd669411
status: draft
refs: trace.py:698@6831bb9a,runs.py:643@78a2e8e3,runs.py:256@778d297d,runs.py:656@ece09fcf,runs.py:614@64edc9ec,trace.py:1@65dc008a,trace.py:60@971f709d,trace.py:587@20786417,trace.py:723@1f43d98c,trace.py:823@e7a4b650,trace.py:620@6cf25a9e,trace.py:361@064c41d5,trace.py:354@c90d778b,trace.py:339@fba4f0d9,trace.py:95@cf21a031,trace.py:81@da61d85c,trace.py:122@5bfbcb9a,trace.py:134@597f4a20,trace.py:105@72e10d0e,trace.py:779@20790262,trace.py:173@b43f49ab,trace.py:205@14d5a48e,trace.py:273@9d535d5a,trace.py:278@9b702982,trace.py:293@24564364,trace.py:291@62fa08da,trace.py:208@87d0d39a,runs.py:322@5a9894f3,trace.py:202@564418ee,trace.py:211@9b604e17,trace.py:252@4c4aab25,trace.py:257@2cf6eb5f,trace.py:326@bc7dfb22,trace.py:400@e12699cd,trace.py:306@c5cc3283,trace.py:185@5b351bb3,trace.py:194@aa655f15,trace.py:196@064ec00e,trace.py:240@2d4399fe,trace.py:188@1e06682a,trace.py:705@3f6f18ad,trace.py:659@6d3a8055,trace.py:716@a3749529,trace.py:635@388b6aa5,trace.py:636@0af6bd15,trace.py:667@6cf5cfc5,trace.py:415@234bc8d8,trace.py:397@5924625e,trace.py:680@2f85b1c6,trace.py:509@2950f14e,trace.py:549@bfdd8428,trace.py:617@118373b6,trace.py:456@2db73e6f,trace.py:462@a74413d4,trace.py:443@22fe0e39,trace.py:690@d86adca2,trace.py:554@d55671fd,trace.py:302@6e8853e4,trace.py:301@655d71fa,trace.py:754@edc64c7c,trace.py:789@eb84f5a4,trace.py:749@333403db,trace.py:798@2a37debf,trace.py:917@c2bc7095,trace.py:140@158ddf0b
---

## 是什么
runtime 一侧：在 hook 下跑一个真实 case（仓库自带的 demo / example，或者起一个服务再发请求），记录**函数粒度**的 caller→callee。分两半：一半是注入到每个 Python 进程里的 hook（`_SITECUSTOMIZE`），每个进程映像往本次 run 的 `parts` 目录写一份分片；另一半是 driver（`run`），负责起命令、按三级信号停、清掉残留进程，最后 `merge` 成各阶段的计数。叠图用的单元（文件）级数据由 `to_package_graph` 在加载时现算，边上「谁调了谁几次」的明细也在这里出。

run 目录怎么建、detail.json 里存什么、case 脚本和配置文件的副本、过期判断，都已经挪到 `runs`。这里只剩「录」和「合」。

## 为什么这样切
和 `scan` 对称：`scan` 回答「代码里写了什么」，它回答「这次真的跑了什么」。两者都只产出数据、都是叶子。trace 不 import 仓库里的任何模块，是 `runs` 调它，不是反过来。

`run` 只接收一个 `parts` 目录和一个 `after` 回调，不知道 run.json 长什么样：id、打包、状态这些存储上的事归 `runs`。之所以用回调、而不是返回之后再由调用方收尾，是为了信号：driver 的信号处理器要一直装到收尾（打包、写 run.json）做完，收尾中途按 Ctrl+C 才不会留下半截的 run。所以收尾必须在 `run` 的 try/finally 里面跑（trace.py:698）。

录制（`run` / `merge`）和解读录制结果（`to_package_graph`）分开：后者由 `runs.load` 每次加载时现算（runs.py:643；`payload.load_hot` 现在只是转调它）。折算要用**当前**的 index，scan 重跑后老 run 也能重新映射；图上展开 / 收起也不用重新折算。`merge` 的输入只有分片本身，不带 case、命令和退出码（这些在 run.json 里），因为 `runs merge` 要能拿 parts.tar.gz 重算。

`case_script`、`file_shas`、`stale_files` 还留在这个模块，调用方却都在 `runs`。`runs.capture` 用 `case_script` 把脚本存进 run 的 `files` 目录（runs.py:256）；老 run 没存脚本时，`runs.load` 读现在的文件，并标明「不是录制时的内容」（runs.py:656）。`stale_files` 只剩一个用途：老 index 没有 `file_sha` 时，`runs.file_state` 退回去和工作区比（runs.py:614）。

## 读法
1. 模块 docstring（trace.py:1）。先看五个现实问题：多进程（含 exec）、开销、调用者要对、启动和请求分开、停要停干净。末尾是分片的文件名和字段
2. `_SITECUSTOMIZE`（trace.py:60），被注入到每个 Python 进程里的那段代码。按这个顺序读：`_rel`（含取哈希）→ `_key` → `_enter` / `_leave` → PHASE / STOP 文件、`_t0`、`_starttime`、`_cmdline` → 落盘（`_lock` / `_final`、`_write`、`_payload`、`_dump`）→ `_exit_hook`、`_wrap_exec` → `_flusher` → `_after_fork` → 回调注册
3. 停止用的几个函数：`_stop` 停进程组，`stop_pids` 停一组散着的 pid，两者都在发 SIGTERM 前调 `_before_term`。再看 `leftovers` 怎么认出「还属于本 run 的进程」
4. `run`（trace.py:587）：注入、接管信号、100 ms 一轮的主循环、停、清残留、合并、`after`
5. `merge`（trace.py:723）：两种命名、阶段相减、`bad_parts` / `sha_conflicts`
6. `to_package_graph`（trace.py:823）：这次没改。把函数粒度折算成单元（文件）粒度，并附上边的调用明细
7. 行为对照 `tests/test_runs.py`。它在 CPU 上跑一个假服务（`tests/trace_cases/fake_repo`），评审发现的每个问题都有一条回归测试（test_dump_race、test_program_semantics、test_nohup、test_sigquit、test_leftover_by_part_file 等）

## 关键算法
### 用 sitecustomize 覆盖子进程
vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。`run` 把一个临时目录插到 `PYTHONPATH` 最前面（trace.py:620），里面放 `sitecustomize.py`。**每个**新起的 Python 进程都会自动 import 它，于是自动挂上 hook、各写各的分片。环境变量会一路继承下去，setsid 出去的服务也带着。这一点后面认残留进程时还要用。

### 调用栈要进出都订阅
只订阅 `PY_START` 的话，调用者会变成「上一个开始执行的函数」：A 调 B、B 返回、A 再调 C，会被记成 B→C。所以要订阅 `PY_START`/`PY_RESUME` 入栈、`PY_RETURN`/`PY_YIELD`/`PY_UNWIND` 出栈（trace.py:361）。`PY_RESUME` 入栈但不计数；`PY_UNWIND` 不能返回 DISABLE（trace.py:354）。仓库外的代码第一次命中就返回 DISABLE，之后不再回调，这是开销低的原因。工具号先取 4、3，最后才用 `PROFILER_ID`（trace.py:339）：3.12 起 cProfile 也走 sys.monitoring，占了这个号，被 trace 的程序一用 cProfile 就报错。

**「调用方」是最近的仓库内的帧。** 仓库外的帧不记录，所以 A → 仓库外的框架 → B 会记成 A → B。在 vllm-omni 上，调度器被调用时中间隔着 vLLM 的 busy loop，hot 图上显示成 stage 进程的入口函数直接调了它。

### 跑的是安装包也能映射回来
被 trace 的往往是 pip 装进 site-packages 的那份。`_rel` 发现路径落在仓库外时，看它是不是 `site-packages/<顶层包>/…`。是的话，按 `CODESTRATA_PKGS`（顶层包 → 仓库内目录）映射回仓库路径，并在 `mapped` 里记下实际执行的路径（trace.py:95 起）。安装包和仓库是否一致，现在由 `runs.capture` 用下一节的执行时哈希来核对，结果写进 `mapped_mismatch`。

缓存按文件名、不按 code 对象（trace.py:81）：code 对象按**内容**比较相等且不比文件名，几个空 `__init__.py` 会被认成同一个。模块顶层记成第 0 行（trace.py:122），否则会和写在第 1 行的函数撞键。键第一次出现时顺手记下 `co_qualname`（trace.py:134；3.10 没有它，退回 `co_name`），存进 `names`。代码改了行号之后，可以按「文件 + qualname」找回符号（设计里的 M6 qualname 回退）。

### 哈希在第一次执行时取
每个进程第一次把某个文件认作仓库内的文件时，读出内容、取 sha256 的前 16 位存进 `_shas`（trace.py:105）。理由是 run 要「录一次、永久复用」：加载时得知道录制时**实际执行**的是哪一版。要是等到收尾才去磁盘上取，录制中途改过的文件就会被当成没改。`merge` 对同一个文件取第一个进程报的哈希，不同进程报的不一样就记进 `sha_conflicts`（trace.py:779）。`runs.capture` 再拿哈希和收尾时的磁盘内容比，得出 `changed_during`。两种情况都会让 run 标成 partial。

### 一个进程映像一份分片
分片名是 `part-<pid>-<t0ns>.json`，其中 `t0ns` 是 hook 在 import 时记下的 `time.monotonic_ns()`（trace.py:173；拼名字在 `_base`，trace.py:205）。只用 pid 不够：exec 之后 pid 不变，新程序写的 `part-<pid>.json` 会把 exec 之前的数据冲掉。fork 出的子进程在 `_after_fork` 里重记 `_t0` 和 `_st`，自然写一份新分片。阶段快照用同一个前缀，后面加 `@<n>-<阶段>`。

分片里还有这些字段：`t0` 和最后一次落盘的 `t`（进程起止）；`why`（最后一次落盘的原因）；`py`（解释器版本、路径、site 目录，`runs` 靠它列出包版本）；`st`（见「残留进程」）。

### 子进程的数据不能丢
atexit 不是总会跑：multiprocessing 的 fork 子进程以 `os._exit` 结束，exec 换程序时不跑，被 SIGKILL 的进程什么都不跑。所以：
- 拦下 `os._exit`（trace.py:273）：先落盘，再**无论如何**调真正的 `os._exit`，落盘时抛出的任何异常都吞掉（trace.py:278）。如果异常从包装里冒出去，fork 出的子进程会逃进父进程的代码里接着跑。参数原样转发，所以按关键字传 status 的写法也照常工作。
- 包一层 `os.execv` / `os.execve`（trace.py:293）：`os.exec*` 全家在 os.py 里按模块全局名字调用这两个，替换它们就全覆盖了。exec 成功就不会返回；返回了说明 exec 失败、进程还要接着跑，这时把 `_final` 复位（trace.py:291）。
- 落盘线程 `_flusher` 每 10 秒落一次盘，进程被强杀最多丢最后 10 秒。
- 分片目录不在就不写，不再 makedirs（trace.py:208）：录制收尾、parts 目录已经打包删掉之后，还活着的孤儿进程不能把它重新建出来、接着往里写。

`why` 记下的就是走了哪条路。`atexit` / `_exit` / `exec` 是主线程的最后一次落盘。最后一次是 `periodic` 或 `phase` 的进程是被强杀的，`runs` 把它们算作 unclean（runs.py:322）。`stop` 见后文。

### 落盘要串行
早先落盘线程和主线程都往同一个 `part-<pid>.json.tmp` 写。进程退出时恰好撞上定时落盘，JSON 就会被写坏，`merge` 读不出来，悄悄丢掉整个进程。这是实测到的，回归测试 test_dump_race 让 8 个进程恰好在第 10 秒前后退出。现在：
- 所有写都在一把 `RLock` 下进行（trace.py:202），临时文件名带上线程号（trace.py:211）。
- 最后一次落盘（atexit / _exit / exec）先置 `_final`，再阻塞地拿锁。落盘线程只做非阻塞的尝试，拿不到锁或 `_final` 已置就放弃（trace.py:252）。否则一份更早拷贝的计数可能最后才 rename，把最终那份盖掉。
- 写的过程中，被 trace 的程序自己的信号处理器可能抛出 `KeyboardInterrupt` / `SystemExit`。这时吞掉重来，最多 3 次（trace.py:257）。
- fork 后在子进程里重建锁（trace.py:326）：fork 那一刻，锁可能正被父进程的落盘线程拿着，而那个线程不会跟到子进程里。

### 不装信号处理器，用 STOP 文件换最后一次落盘
被 SIGTERM 停掉的进程不跑 atexit。最直接的补法是给 SIGTERM 装一个「先落盘再退出」的处理器。这个办法试过，评审证明它会改变被 trace 的程序的行为：Python 层的处理器要等主线程回到解释器才会跑，卡在 C 里的进程收到 SIGTERM 就不再立刻死，multiprocessing 的退出会挂住；链式调用旧处理器的程序则会被直接杀掉。hook 的底线是不改程序的语义，test_program_semantics 就断言 SIGTERM 的处理仍是 `signal.SIG_DFL`。

所以改成用文件通知。driver 升级到 SIGTERM 之前，`_before_term`（trace.py:400）往 `$CODESTRATA_OUT/STOP` 写一行，最多等 1.5 秒（进程都退了就不等）再发信号。各进程的落盘线程每秒看一次这个文件，看到就落一次盘，`why=stop`（trace.py:306）。落盘线程是独立的线程，主线程卡在 C 里也照样能写。代价是这份数据截止到发信号前一秒左右。

### 命令行在 import 时读一次
帮助面板要列出每个进程是什么命令。sys.argv 缺东西：没有解释器，`python -c` 的代码也不在里面，而 multiprocessing spawn 出的子进程正是这样起的。所以读 /proc/self/cmdline（`_cmdline`，trace.py:185），读不到（非 Linux）时才退回解释器路径加 sys.argv。

现在只在 import 时读一次（trace.py:194）。原因是 vLLM 的 engine core 之后会用 setproctitle 把 cmdline 改成「VLLM::EngineCore_0」这样的标题，每次落盘时现读就拿不到真正的命令了。每个参数截到 400 字符、最多 60 个，截过就记 `argv_cut`（trace.py:196）。`runs.procs_grouped` 据此在界面上标「被截断」，取代了早先靠「有没有 ppid」来猜。落盘时再读一次 cmdline，第一项变了就把新的记成 `title`（trace.py:240）。

**模板里的 NUL 要双重转义。** `_SITECUSTOMIZE` 是普通（非 raw）的三引号字符串，所以源码里写的是 `split(b"\\0")`（trace.py:188），写进 `sitecustomize.py` 后才变成 `b"\0"`。要是只写一个反斜杠，模板里就是一个真的 NUL 字节，生成的文件编译时报「source code cannot contain null bytes」，每个进程的 sitecustomize 都导入失败，整次 trace 什么都录不到。改这段模板时，凡是反斜杠转义都要这样多写一层。

### case 脚本的认法
光一句 `bash ../../trace_case.sh` 看不出起了什么服务、跑的是哪个 demo、带了什么参数，所以要把脚本原文存下来（现在由 `runs.capture` 存进 run 的 `files` 目录）。`case_script`（trace.py:705）依次看命令里的每个参数，跳过以 `-` 开头的选项。相对路径按仓库根解析，因为 `run` 就是在仓库根下起的命令（trace.py:659）。只有满足这些条件的才算：是文件、小于 200 KB、后缀是 .sh / .bash / .py / .zsh 或者没有后缀；没后缀的还得以 `#!` 开头（trace.py:716）。这样 `bash`、`python` 这类解释器名和二进制文件都会被跳过。取第一个命中的。

### driver：命令放进自己的会话，分三级停
老做法是 `subprocess.call` 加超时，问题有三个：超时或 Ctrl+C 时直接 SIGKILL 掉 bash，case 脚本的 `trap … EXIT` 来不及跑；setsid 出去的 API server 和 engine core 成了孤儿，一直占着显存；merge 又立刻执行，这些进程最后 10 秒以内的数据也丢了。现在是这样：
- `Popen` 带 `start_new_session`（trace.py:659）：命令在自己的会话里，终端的 Ctrl+C 只到 driver，由 driver 决定怎么转发。
- driver 接管 SIGINT / SIGTERM / SIGHUP / SIGQUIT（trace.py:635），处理器只把信号记下来。SIGHUP（终端关掉）和 Ctrl+C 一样处理，因为命令在自己的会话里，driver 一死就没人管它了。已经被忽略的信号保持忽略（trace.py:636），比如 nohup 下的 SIGHUP、脚本里用 & 起的 driver 的 SIGINT，否则关掉终端就会打断 nohup 下的录制（test_nohup）。
- 主循环每 100 ms `wait` 一次（trace.py:667），顺带读一次 PHASE，记下阶段切换的时刻。时刻相对 run 时钟的 `mono0_ns`，最后写进 run.json 的阶段列表。
- 超时或收到信号时，`_stop`（trace.py:415）对整个进程组按 `_LEVELS`（trace.py:397）走：SIGINT → 等 `stop_grace`（默认 90 秒）→ `_before_term` → SIGTERM → 等 15 秒 → SIGKILL。SIGINT 放在最前，是因为 Python 进程收到它会抛 KeyboardInterrupt、正常走 atexit，数据是完整的；case 脚本的 trap 也有机会停掉它 setsid 出去的服务。等待期间又来一个信号（`poke`）就直接升一级。SIGQUIT（Ctrl+\）表示「别等了」，跳过 SIGINT 这一级（trace.py:680）。
- driver 自己的提示走 `_say`：终端关掉后写 stderr 会报 EIO，不能因此丢掉收尾。

### 残留进程
命令退出，不等于本 run 的进程都退出了：可能还有 setsid 出去、没被 case 脚本停掉的服务，以及被遗弃的子进程。`leftovers`（trace.py:509）用两种办法认它们：
- 扫 /proc/*/environ，找 `CODESTRATA_OUT` 等于本 run `parts` 目录的进程。
- 看分片文件名里的 pid：进程还活着，而且 /proc/<pid>/stat 里的启动时刻等于分片里记的 `st`（trace.py:549）。

第二条是给 setproctitle 兜底的。它默认借用 environ 那块内存写标题，会把 /proc/<pid>/environ 清空，第一条就认不出来了。driver 还另外设了 `SPT_NOENV`（trace.py:617），让它只用 argv 那块。两道防线，任何一道生效都能认出来。

`stop_pids`（trace.py:456）逐个按三级停。每一步都用 (pid, 启动时刻) 核对还是不是当初那个进程（`mine`，trace.py:462），防止 pid 被复用后误杀。已经忽略 SIGINT 的进程直接从 SIGTERM 开始：`_ignores`（trace.py:443）读 SigIgn 位图。非交互 bash 用 & 起的后台进程天生忽略 SIGINT，Python 程序若不自己装处理器（uvicorn 装了，asyncio.run 不装），对它发 SIGINT 等多久都没用。`_alive` 把僵尸进程算作已死。非 Linux 没有 /proc，只能停进程组（trace.py:690）。这些都包在 `stop_leftovers`（trace.py:554）里：停完一轮再找一遍，最多三轮——残留的 bash 在 EXIT trap 里还会起新的子进程（kill、sleep），它们同样带着本 run 的环境，只停第一次看到的那批会漏掉它们。残留进程都停完才 `merge`，这样每个进程的最后一次落盘都在结果里。`runs merge` 也调 `leftovers`：还有进程在往 parts 目录写时，拒绝重算。

### 分阶段
被 trace 的命令往 `$CODESTRATA_OUT/PHASE` 写一个名字，比如服务就绪后写 `serving`。每个进程的落盘线程 1 秒内看到，就在锁内给切换前的累计计数拍一张快照（trace.py:302），再落一次盘（`why=phase`）。最后一次落盘已经开始后就不再切（trace.py:301）。`merge` 按进程把相邻快照相减，得到每个阶段的调用。于是 `--hot case@serving` 能只看处理请求的那一段，启动时的初始化（注册表探测、模型加载、CUDA graph 捕获）不会混进「请求走了哪条路」。

### 合并
`merge`（trace.py:723）几处值得注意的地方：
- 两种命名都认。按主分片去掉 `.json` 后的前缀去找它的快照（trace.py:754），`part-<pid>` 和 `part-<pid>-<t0ns>` 同样处理，这样 `runs merge` 也能重算迁移前录的老分片。
- 阶段总是保留，只有一个阶段时也保留（trace.py:789）。老版本在这种情况下会丢掉阶段名，而名字本身也是信息。
- 读不出来的分片记进 `bad_parts`（trace.py:749），不再悄悄跳过。`runs` 会因此把 run 标成 partial，并写明缺了几个分片。
- `names` 取第一个出现的值。`procs` 带上 `t0` / `t` / `why` / `py` / `argv_cut` / `title`，按起始时刻排序（trace.py:798）。`file_edges` 只用来打印摘要，不存。

### 折算时分开「调用」和「import 触发的执行」
被调方是模块帧的边不算调用，单独记进 `edge_import_exec`，否则每条 import 边都会因为「导入过」被染成橙色。没有自己符号的帧（闭包、lambda、生成器表达式）按符号的起止行归到最内层的外层符号，标成 `外层.<L行号>`。`to_package_graph` 还按文件汇总调用次数（trace.py:917，同样不算 import 触发的模块执行），详情面板的文件树据此在目录和文件上标出这次 case 走过哪里。

## 局限
- 栈深超过 2000 时砍掉一半兜底（trace.py:140），极深递归下调用者可能不准。
- 阶段切换和 STOP 最多都有 1 秒延迟：case 脚本写完 PHASE 后应该等一两秒再开始下一段。计数按各进程的落盘线程划分阶段，driver 记的阶段时刻按它自己的轮询，两者可能差出不到 1 秒。被 SIGTERM 停掉的进程，数据截止到发信号前 1 秒左右；被 SIGKILL 的，或者 driver 自己被 kill -9、没来得及写 STOP 的，最多丢 10 秒。
- fork 出的子进程继承父进程 import 时读到的命令行，只能靠 `pid` / `ppid` 区分。`title` 只在命令行第一项变了时才记。
- 只包了 `os.execv` / `os.execve`，绕过 os 模块直接调 posix 那一层的 exec 不会先落盘。
- 残留进程的两种认法都依赖 /proc，只有 Linux 能用。
- `case_script` 是启发式：虚拟环境 bin 目录下的 console-script 入口（没后缀、有 shebang）会被当成 case 脚本，存下的只是几行包装；`python -m pkg.mod`、`bash -c "…"` 认不出脚本，也就不存。

## 不确定
- `_lock` 为什么用 `RLock` 而不是普通锁，代码里没说。有一个说得通的场景：主线程正在 `_dump` 里持锁，被 trace 程序的信号处理器调了 `os._exit`，`_exit_hook` 在同一个线程里再拿一次锁，普通锁就会自己锁死。
- `why=stop` 的进程在 `runs` 那边不算 unclean（runs.py:322 只认 periodic / phase），虽然它最后约 1 秒的数据也没了。看起来是有意把「按流程停掉」和「被强杀」分开。
- `ppid` 录下了，但还没用来画进程树（设计里说「只画确定的 ppid 派生」，属于以后的事）。`names` 也只存进了 counts.json.gz，qualname 回退（M6）还没做。
