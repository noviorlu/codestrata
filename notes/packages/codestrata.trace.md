---
written_by: claude-opus-5-5
target: codestrata.trace
kind: package
code_sha: 6ba1e0796b40f177
status: draft
refs: trace.py:829@6831bb9a,codestrata/__main__.py:227@8ac31b40,runs.py:684@78a2e8e3,runs.py:338@8d66640b,runs.py:259@778d297d,runs.py:697@ece09fcf,runs.py:655@64edc9ec,trace.py:1@65dc008a,trace.py:60@971f709d,trace.py:718@20786417,trace.py:854@1f43d98c,trace.py:954@e7a4b650,trace.py:751@6cf25a9e,trace.py:492@8ace5770,trace.py:477@9f99ba56,trace.py:484@c90d778b,trace.py:464@fba4f0d9,trace.py:95@cf21a031,trace.py:81@da61d85c,trace.py:122@5bfbcb9a,trace.py:212@597f4a20,trace.py:105@72e10d0e,trace.py:910@20790262,trace.py:262@b43f49ab,trace.py:294@14d5a48e,trace.py:387@9d535d5a,trace.py:392@9b702982,trace.py:407@24564364,trace.py:405@62fa08da,trace.py:297@87d0d39a,runs.py:357@5a9894f3,trace.py:291@564418ee,trace.py:300@9b604e17,trace.py:364@4c4aab25,trace.py:369@2cf6eb5f,trace.py:445@bc7dfb22,trace.py:128@9a6e154c,trace.py:217@4a8962bd,trace.py:190@b260cb52,trace.py:183@84cde789,trace.py:220@5e0ba9c7,trace.py:195@5cea0e5e,trace.py:219@e639438f,trace.py:181@d85d1ecf,trace.py:224@e639438f,trace.py:235@501260b7,trace.py:144@33af8d6b,trace.py:156@1e545ae9,trace.py:167@8e25951c,trace.py:132@7b10e135,trace.py:335@13bfbdc0,trace.py:372@93c99397,trace.py:423@17f4f8a6,trace.py:352@defa1ca1,trace.py:447@030ac9e4,trace.py:531@e12699cd,trace.py:422@bacab3ad,trace.py:274@5b351bb3,trace.py:283@aa655f15,trace.py:285@064ec00e,trace.py:329@2d4399fe,trace.py:277@1e06682a,trace.py:836@3f6f18ad,trace.py:790@6d3a8055,trace.py:847@a3749529,trace.py:766@388b6aa5,trace.py:767@0af6bd15,trace.py:798@6cf5cfc5,trace.py:546@234bc8d8,trace.py:528@5924625e,trace.py:811@2f85b1c6,trace.py:640@2950f14e,trace.py:680@bfdd8428,trace.py:748@118373b6,trace.py:587@2db73e6f,trace.py:593@a74413d4,trace.py:574@22fe0e39,trace.py:821@d86adca2,trace.py:685@d55671fd,trace.py:417@25f1fd48,trace.py:415@655d71fa,trace.py:885@edc64c7c,trace.py:920@eb84f5a4,trace.py:880@333403db,trace.py:929@2a37debf,trace.py:1048@c2bc7095,trace.py:227@158ddf0b
---

## 是什么
runtime 一侧：在 hook 下跑一个真实 case（仓库自带的 demo / example，或者起一个服务再发请求），记录**函数粒度**的 caller→callee。分两半：一半是注入到每个 Python 进程里的 hook（`_SITECUSTOMIZE`），每个进程映像往本次 run 的 `parts` 目录写一份分片；另一半是 driver（`run`），负责起命令、按三级信号停、清掉残留进程，最后 `merge` 成各阶段的计数。叠图用的单元（文件）级数据由 `to_package_graph` 在加载时现算，边上「谁调了谁几次」的明细也在这里出。

打开 `CODESTRATA_EVENTS=1`（`trace --events`）时，hook 还会给每次**跨文件**调用记下起止时刻（调用、返回、挂起、恢复），每个进程映像写一份 `ev-<pid>-<t0ns>.log`，这是时序图的原始数据。

run 目录怎么建、detail.json 里存什么、case 脚本和配置文件的副本、过期判断，以及事件日志的打包和配成 span，都在 `runs` / `events`。这里只剩「录」和「合计数」。

## 为什么这样切
和 `scan` 对称：`scan` 回答「代码里写了什么」，它回答「这次真的跑了什么」。两者都只产出数据、都是叶子。trace 不 import 仓库里的任何模块，是 `runs` 调它，不是反过来。

`run` 只接收一个 `parts` 目录和一个 `after` 回调，不知道 run.json 长什么样：id、打包、状态这些存储上的事归 `runs`。之所以用回调、而不是返回之后再由调用方收尾，是为了信号：driver 的信号处理器要一直装到收尾（打包、写 run.json）做完，收尾中途按 Ctrl+C 才不会留下半截的 run。所以收尾必须在 `run` 的 try/finally 里面跑（trace.py:829）。`run` 也不知道有没有开事件：`cmd_trace` 把 `CODESTRATA_EVENTS` 塞进 `env_extra`（codestrata/__main__.py:227），hook 自己看环境变量。

录制（`run` / `merge`）和解读录制结果（`to_package_graph`）分开：后者由 `runs.load` 每次加载时现算（runs.py:684）。折算要用**当前**的 index，scan 重跑后老 run 也能重新映射；图上展开 / 收起也不用重新折算。`merge` 的输入只有分片本身，不带 case、命令和退出码（这些在 run.json 里），因为 `runs merge` 要能拿 parts.tar.gz 重算。同样的道理，事件在 hook 里只写原始行，配对和折叠放在 `events`（由 `runs._build_events` 调，runs.py:338）：span 是派生数据，收尾和 `runs merge` 都要能从永久保留的原始日志重做。`merge` 只 glob `part-*.json`，不碰 `ev-*.log`。

`case_script`、`file_shas`、`stale_files` 还留在这个模块，调用方却都在 `runs`。`runs.capture` 用 `case_script` 把脚本存进 run 的 `files` 目录（runs.py:259）；老 run 没存脚本时，`runs.load` 读现在的文件，并标明「不是录制时的内容」（runs.py:697）。`stale_files` 只剩一个用途：老 index 没有 `file_sha` 时，`runs.file_state` 退回去和工作区比（runs.py:655）。

## 读法
1. 模块 docstring（trace.py:1）。先看五个现实问题：多进程（含 exec）、开销、调用者要对、启动和请求分开、停要停干净。末尾是分片的文件名和字段。事件日志的行格式（H / N / K / C / R / Y / S / T）不在这里，在 `codestrata/events.py` 的模块说明里
2. `_SITECUSTOMIZE`（trace.py:60），被注入到每个 Python 进程里的那段代码。按这个顺序读：`_rel`（含取哈希）→ `_key` → 事件的几个小函数（`_ev_kid` / `_ev_tid` / `_ev_room` / `_ev_call` / `_ev_mark`）→ `_enter` / `_leave` → PHASE / STOP 文件、`_t0`、`_starttime`、`_cmdline` → 落盘（`_lock` / `_final`、`_write`、`_payload`、`_ev_flush`、`_dump`）→ `_exit_hook`、`_wrap_exec` → `_flusher` → `_after_fork` → 回调注册
3. 停止用的几个函数：`_stop` 停进程组，`stop_pids` 停一组散着的 pid，两者都在发 SIGTERM 前调 `_before_term`。再看 `leftovers` 怎么认出「还属于本 run 的进程」，`stop_leftovers` 怎么反复找
4. `run`（trace.py:718）：注入、接管信号、100 ms 一轮的主循环、停、清残留、合并、`after`
5. `merge`（trace.py:854）：两种命名、阶段相减、`bad_parts` / `sha_conflicts`
6. `to_package_graph`（trace.py:954）：把函数粒度折算成单元（文件）粒度，并附上边的调用明细
7. 行为对照 `tests/test_runs.py`。它在 CPU 上跑一个假服务（`tests/trace_cases/fake_repo`），评审发现的每个问题都有一条回归测试（test_dump_race、test_program_semantics、test_nohup、test_sigquit、test_leftover_by_part_file 等）。事件的真值场景在 `tests/trace_cases/fake_repo/fakesvc/truth.py`，一个场景一个函数，由 test_events_truth 逐项断言；test_events_cap、test_events_fake_service 管上限和真服务形状

## 关键算法
### 用 sitecustomize 覆盖子进程
vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。`run` 把一个临时目录插到 `PYTHONPATH` 最前面（trace.py:751），里面放 `sitecustomize.py`。**每个**新起的 Python 进程都会自动 import 它，于是自动挂上 hook、各写各的分片。环境变量会一路继承下去，setsid 出去的服务也带着，`CODESTRATA_EVENTS` 也一样。这一点后面认残留进程时还要用。

### 调用栈要进出都订阅
只订阅 `PY_START` 的话，调用者会变成「上一个开始执行的函数」：A 调 B、B 返回、A 再调 C，会被记成 B→C。所以要订阅 `PY_START`/`PY_RESUME`/`PY_THROW` 入栈、`PY_RETURN`/`PY_YIELD`/`PY_UNWIND` 出栈（trace.py:492）。`PY_RESUME` 和 `PY_THROW` 入栈但不计数。`PY_THROW` 是 M3 评审后补的：`throw()` / `close()` / asyncio 取消经它、不经 `PY_RESUME` 恢复帧，不订阅的话生成器 / 协程的帧不入栈，它清理代码里的调用会记到当时栈顶的别的帧头上（比如调 close() 的那一帧），计数和时序都错。`PY_UNWIND` 和 `PY_THROW` 都不能返回 DISABLE（trace.py:477、trace.py:484），返回了会在被 trace 的程序里抛 ValueError，测试里 asyncio 取消就这样崩过；代价是仓库外的代码每次 throw 都回调一次。其余事件在仓库外的代码第一次命中就返回 DISABLE，之后不再回调，这是开销低的原因。工具号先取 4、3，最后才用 `PROFILER_ID`（trace.py:464）：3.12 起 cProfile 也走 sys.monitoring，占了这个号，被 trace 的程序一用 cProfile 就报错。

**「调用方」是最近的仓库内的帧。** 仓库外的帧不记录，所以 A → 仓库外的框架 → B 会记成 A → B。在 vllm-omni 上，调度器被调用时中间隔着 vLLM 的 busy loop，hot 图上显示成 stage 进程的入口函数直接调了它。

### 跑的是安装包也能映射回来
被 trace 的往往是 pip 装进 site-packages 的那份。`_rel` 发现路径落在仓库外时，看它是不是 `site-packages/<顶层包>/…`。是的话，按 `CODESTRATA_PKGS`（顶层包 → 仓库内目录）映射回仓库路径，并在 `mapped` 里记下实际执行的路径（trace.py:95 起）。安装包和仓库是否一致，由 `runs.capture` 用下一节的执行时哈希来核对，结果写进 `mapped_mismatch`。

缓存按文件名、不按 code 对象（trace.py:81）：code 对象按**内容**比较相等且不比文件名，几个空 `__init__.py` 会被认成同一个。模块顶层记成第 0 行（trace.py:122），否则会和写在第 1 行的函数撞键。键第一次出现时顺手记下 `co_qualname`（trace.py:212；3.10 没有它，退回 `co_name`），存进 `names`，给设计里的 M6 qualname 回退用。

### 哈希在第一次执行时取
每个进程第一次把某个文件认作仓库内的文件时，读出内容、取 sha256 的前 16 位存进 `_shas`（trace.py:105）。理由是 run 要「录一次、永久复用」：加载时得知道录制时**实际执行**的是哪一版。要是等到收尾才去磁盘上取，录制中途改过的文件就会被当成没改。`merge` 对同一个文件取第一个进程报的哈希，不同进程报的不一样就记进 `sha_conflicts`（trace.py:910）。`runs.capture` 再拿哈希和收尾时的磁盘内容比，得出 `changed_during`。两种情况都会让 run 标成 partial。

### 一个进程映像一份分片
分片名是 `part-<pid>-<t0ns>.json`，其中 `t0ns` 是 hook 在 import 时记下的 `time.monotonic_ns()`（trace.py:262；拼名字在 `_base`，trace.py:294）。只用 pid 不够：exec 之后 pid 不变，新程序写的 `part-<pid>.json` 会把 exec 之前的数据冲掉。fork 出的子进程在 `_after_fork` 里重记 `_t0` 和 `_st`，自然写一份新分片。阶段快照用同一个前缀，后面加 `@<n>-<阶段>`；事件日志也按同一个映像命名。

分片里还有这些字段：`t0` 和最后一次落盘的 `t`（进程起止）；`why`（最后一次落盘的原因）；`py`（解释器版本、路径、site 目录，`runs` 靠它列出包版本）；`st`（见「残留进程」）。

### 子进程的数据不能丢
atexit 不是总会跑：multiprocessing 的 fork 子进程以 `os._exit` 结束，exec 换程序时不跑，被 SIGKILL 的进程什么都不跑。所以：
- 拦下 `os._exit`（trace.py:387）：先落盘，再**无论如何**调真正的 `os._exit`（trace.py:392），落盘时抛出的任何异常都吞掉。如果异常从包装里冒出去，fork 出的子进程会逃进父进程的代码里接着跑。参数原样转发，按关键字传 status 的写法也照常工作。
- 包一层 `os.execv` / `os.execve`（trace.py:407）：`os.exec*` 全家在 os.py 里按模块全局名字调用这两个，替换它们就全覆盖了。exec 成功就不会返回；返回了说明 exec 失败、进程还要接着跑，这时把 `_final` 复位（trace.py:405）。
- 落盘线程 `_flusher` 每 10 秒落一次盘，进程被强杀最多丢最后 10 秒。
- 分片目录不在就不写，不 makedirs（`_write`，trace.py:297）：录制收尾、parts 目录已经打包删掉之后，还活着的孤儿进程不能把它重新建出来。

`why` 记下的就是走了哪条路。`atexit` / `_exit` / `exec` 是主线程的最后一次落盘。最后一次是 `periodic` 或 `phase` 的进程是被强杀的，`runs` 把它们算作 unclean（runs.py:357）。`stop` 见后文。

### 落盘要串行
早先落盘线程和主线程都往同一个 `part-<pid>.json.tmp` 写。进程退出时恰好撞上定时落盘，JSON 就会被写坏，`merge` 读不出来，悄悄丢掉整个进程。回归测试 test_dump_race 让 8 个进程恰好在第 10 秒前后退出。现在：
- 所有写都在一把 `RLock` 下进行（trace.py:291），临时文件名带上线程号（trace.py:300）。
- 最后一次落盘（atexit / _exit / exec）先置 `_final`，再阻塞地拿锁。落盘线程只做非阻塞的尝试，拿不到锁或 `_final` 已置就放弃（trace.py:364）。否则一份更早拷贝的计数可能最后才 rename，把最终那份盖掉。
- 写的过程中，被 trace 的程序自己的信号处理器可能抛出 `KeyboardInterrupt` / `SystemExit`。这时吞掉重来，最多 3 次（trace.py:369）。
- fork 后在子进程里重建锁（trace.py:445）：fork 那一刻，锁可能正被父进程的落盘线程拿着，而那个线程不会跟到子进程里。

### 时序事件（`CODESTRATA_EVENTS=1`，只在 sys.monitoring 下）
计数只说「谁调了谁几次」，时序图还要每次调用的起止。`_EV` 在 import 时定下（trace.py:128），setprofile 回退路径不录。
- **只记跨文件的调用**（trace.py:217）：口径和 `func_edges` 相同（调用方是栈顶的仓库帧），再加「和被调方不在同一个文件」。量因此小得多，而且能对账：test_events_truth 和 test_events_fake_service 断言 span 的 Σrep 等于计数里跨文件的 func_edges。线程入口在仓库外，线程里第一个仓库函数没有调用方，同样不记。
- **按帧配对，不按栈**：调用时分配 span 号，`_xf` 记 `id(帧) → (span 号, code)`；返回 / 挂起 / 恢复由 `_ev_mark`（trace.py:190）按帧找回 span 号再写。同一线程上交错的 asyncio 协程，先开始的不一定先结束，按栈的顺序配会配反。被监控的帧在 `_ev_call` / `_ev_mark` 里往上数三层（trace.py:183），在 `_enter` 里数两层（trace.py:220），所以依赖这几个函数固定的调用深度。
- **连 code 一起存**（trace.py:195）：半路被丢掉的生成器在 3.12 上关闭时不发任何事件，旧账留在 `_xf` 里，帧地址之后会被别的帧复用。code 对不上就作废，这种 span 整理后显示为没返回。
- **同文件里新起的帧顺手清旧账**（trace.py:219）：code 核对拦不住**同一个函数**的新帧。丢掉一个跨文件起的生成器后，紧接着在同文件里（或没有调用方、递归自调用时）再起同一函数的生成器，新帧多半落在刚释放的地址上；它没有调用行，却会通过 code 核对，挂起 / 恢复 / 返回全记到旧 span 头上。所以 PY_START 不走 `_ev_call` 时，只要这个 code 当过跨文件被调方，就把自己帧地址上的旧账 pop 掉。跨文件调起的新帧由 `_ev_call` 管：平时直接覆盖；到了行数上限、不再写调用行时，也先把这个帧地址上的旧账 pop 掉（trace.py:181），否则上限之后同一函数的新帧落在旧地址上，会通过 code 核对、接着旧 span 记挂起 / 恢复 / 返回。场景是 `tests/trace_cases/fake_repo/fakesvc/callee.py` 里的 regen_after，test_events_truth 断言那 25 个丢掉的 span 都只挂起一次、没返回。
- **`_xc` 过滤**（trace.py:224、trace.py:235）：取帧、查字典对每个仓库函数都做太贵，只有当过跨文件被调方的 code 才可能在 `_xf` 里，别的直接跳过（上一条清旧账也只对它们做）。它只是过滤，fork 后也不清。
- **编号用 `itertools.count`**（trace.py:144）：span、键、线程三套号，`next()` 在 CPython 里是原子的，多线程同时取不会重号。
- **线程号存在线程局部变量里**（`_ev_tid`，trace.py:156），带 fork 代数 `_gen`。不按 `get_ident()` 缓存：glibc 会把退出线程的 ident 分给下一个新线程，后起的线程会顶着前一个的号和名字（truth.py 里先后起四个线程验证）。
- **上限只管调用**（`_ev_room`，trace.py:167）：`CODESTRATA_EV_MAX`（默认 300 万，可写成 3e6；写错了，比如 abc 或 inf，退回默认，trace.py:132）只限制调用行，到了写一行 T。已在 `_xf` 里的 span 照写返回 / 挂起 / 恢复，否则上限前开始、上限后返回的调用会显示成到进程结束都没返回。到上限后 `_ev_call` 不再分配 span，但仍替这一帧作废地址上的旧账（见上）。计数不受影响，`runs` 也不因此改 status。
- **落盘**（`_ev_flush`，trace.py:335）：`_dump` 每次先刷一次（trace.py:372），落盘线程每秒非阻塞地拿锁刷一次（trace.py:423），第一次写时先写 H 行。**写成功才从缓冲里删**：被程序的信号处理器打断时 `_dump` 重试，这些行还在；只有 OSError（目录已被收尾删掉）才丢（trace.py:352）。按 UTF-8 + backslashreplace 写，换行在 `_clean` 里换成空格：一个不是 UTF-8 的文件名不会让整块写不进去，线程名里的换行也劈不开一行。只有这个函数删缓冲、别的线程只往尾巴上加，所以「拷前 n 个、删前 n 个」不丢行。
- **fork**（trace.py:447）：子进程清空缓冲、键表、`_xf` 和上限计数，编号从 1 重来，`_gen` 加一让线程号缓存作废。fork 之前没返回的帧不归子进程；子进程的 t0 变了，自然写一份新日志。

### 不装信号处理器，用 STOP 文件换最后一次落盘
被 SIGTERM 停掉的进程不跑 atexit。最直接的补法是给 SIGTERM 装一个「先落盘再退出」的处理器。这个办法试过，评审证明它会改变被 trace 的程序的行为：Python 层的处理器要等主线程回到解释器才会跑，卡在 C 里的进程收到 SIGTERM 就不再立刻死，multiprocessing 的退出会挂住；链式调用旧处理器的程序则会被直接杀掉。hook 的底线是不改程序的语义，test_program_semantics 就断言 SIGTERM 的处理仍是 `signal.SIG_DFL`。

所以改成用文件通知。driver 升级到 SIGTERM 之前，`_before_term`（trace.py:531）往 `$CODESTRATA_OUT/STOP` 写一行，最多等 1.5 秒（进程都退了就不等）再发信号。各进程的落盘线程每秒看一次这个文件，看到就落一次盘，`why=stop`（trace.py:422）。落盘线程是独立的线程，主线程卡在 C 里也照样能写。代价是这份数据截止到发信号前一秒左右。

### 命令行在 import 时读一次
帮助面板要列出每个进程是什么命令。sys.argv 缺东西：没有解释器，`python -c` 的代码也不在里面，而 multiprocessing spawn 出的子进程正是这样起的。所以读 /proc/self/cmdline（`_cmdline`，trace.py:274），读不到（非 Linux）时才退回解释器路径加 sys.argv。

只在 import 时读一次（trace.py:283）：vLLM 的 engine core 之后会用 setproctitle 把 cmdline 改成「VLLM::EngineCore_0」这样的标题。每个参数截到 400 字符、最多 60 个，截过就记 `argv_cut`（trace.py:285），`runs.procs_grouped` 据此标「被截断」。落盘时再读一次 cmdline，第一项变了就把新的记成 `title`（trace.py:329）。

**模板里的转义要写两层。** `_SITECUSTOMIZE` 是普通（非 raw）的三引号字符串，所以源码里写的是 `split(b"\\0")`（trace.py:277），写进 `sitecustomize.py` 后才变成 `b"\0"`。只写一个反斜杠的话，模板里就是一个真的 NUL 字节，每个进程的 sitecustomize 都导入失败，整次 trace 什么都录不到。事件代码里的 `"\\n"` 同理。

### case 脚本的认法
光一句 `bash ../../trace_case.sh` 看不出起了什么服务、跑的是哪个 demo，所以要把脚本原文存下来（由 `runs.capture` 存进 run 的 `files` 目录）。`case_script`（trace.py:836）依次看命令里的每个参数，跳过以 `-` 开头的选项。相对路径按仓库根解析，因为 `run` 就是在仓库根下起的命令（trace.py:790）。只有满足这些条件的才算：是文件、小于 200 KB、后缀是 .sh / .bash / .py / .zsh 或者没有后缀；没后缀的还得以 `#!` 开头（trace.py:847）。取第一个命中的。

### driver：命令放进自己的会话，分三级停
老做法是 `subprocess.call` 加超时：超时或 Ctrl+C 时直接 SIGKILL 掉 bash，case 脚本的 `trap … EXIT` 来不及跑；setsid 出去的服务成了孤儿、一直占着显存；这些进程最后 10 秒以内的数据也丢了。现在：
- `Popen` 带 `start_new_session`（trace.py:790）：终端的 Ctrl+C 只到 driver，由 driver 决定怎么转发。
- driver 接管 SIGINT / SIGTERM / SIGHUP / SIGQUIT（trace.py:766），处理器只把信号记下来。SIGHUP 和 Ctrl+C 一样处理，因为 driver 一死命令就没人管了。已经被忽略的信号保持忽略（trace.py:767），比如 nohup 下的 SIGHUP，否则关掉终端就会打断 nohup 下的录制（test_nohup）。
- 主循环每 100 ms `wait` 一次（trace.py:798），顺带读一次 PHASE，记下阶段切换的时刻（相对 run 时钟的 `mono0_ns`）。
- 超时或收到信号时，`_stop`（trace.py:546）对整个进程组按 `_LEVELS`（trace.py:528）走：SIGINT → 等 `stop_grace`（默认 90 秒）→ `_before_term` → SIGTERM → 等 15 秒 → SIGKILL。SIGINT 放在最前，是因为 Python 进程收到它会抛 KeyboardInterrupt、正常走 atexit，数据完整；case 脚本的 trap 也有机会停掉它 setsid 出去的服务。等待期间又来一个信号（`poke`）就直接升一级。SIGQUIT 表示「别等了」，跳过 SIGINT 这一级（trace.py:811）。
- driver 自己的提示走 `_say`：终端关掉后写 stderr 会报 EIO，不能因此丢掉收尾。

### 残留进程
命令退出，不等于本 run 的进程都退出了。`leftovers`（trace.py:640）用两种办法认它们：
- 扫 /proc/*/environ，找 `CODESTRATA_OUT` 等于本 run `parts` 目录的进程。
- 看分片文件名里的 pid：进程还活着，而且 /proc/<pid>/stat 里的启动时刻等于分片里记的 `st`（trace.py:680）。

第二条是给 setproctitle 兜底的：它默认借用 environ 那块内存写标题，会把 /proc/<pid>/environ 清空。driver 还另外设了 `SPT_NOENV`（trace.py:748），让它只用 argv 那块。两道防线，任何一道生效都能认出来。

`stop_pids`（trace.py:587）逐个按三级停，每一步都用 (pid, 启动时刻) 核对还是不是当初那个进程（`mine`，trace.py:593），防止 pid 被复用后误杀。已经忽略 SIGINT 的进程直接从 SIGTERM 开始：`_ignores`（trace.py:574）读 SigIgn 位图，非交互 bash 用 & 起的后台进程天生忽略 SIGINT。`_alive` 把僵尸进程算作已死。非 Linux 没有 /proc，只能停进程组（trace.py:821）。这些都包在 `stop_leftovers`（trace.py:685）里：停完一轮再找一遍，最多三轮，因为残留的 bash 在 EXIT trap 里还会起新的子进程（kill、sleep），它们同样带着本 run 的环境，只停第一次看到的那批会漏掉。残留进程都停完才 `merge`，这样每个进程的最后一次落盘都在结果里。`runs merge` 也调 `leftovers`：还有进程在往 parts 目录写时，拒绝重算。

### 分阶段
被 trace 的命令往 `$CODESTRATA_OUT/PHASE` 写一个名字，比如服务就绪后写 `serving`。每个进程的落盘线程 1 秒内看到，就在锁内给切换前的累计计数拍一张快照（trace.py:417），再落一次盘（`why=phase`）。最后一次落盘已经开始后就不再切（trace.py:415）。`merge` 按进程把相邻快照相减，得到每个阶段的调用，于是 `--hot case@serving` 能只看处理请求的那一段。事件不分阶段：span 带的是时刻，按阶段看要拿 driver 记的阶段时刻去切（设计 7.2）。

### 合并
`merge`（trace.py:854）几处值得注意的地方：
- 两种命名都认。按主分片去掉 `.json` 后的前缀去找它的快照（trace.py:885），`part-<pid>` 和 `part-<pid>-<t0ns>` 同样处理，这样 `runs merge` 也能重算迁移前录的老分片。
- 阶段总是保留，只有一个阶段时也保留（trace.py:920）。名字本身也是信息。
- 读不出来的分片记进 `bad_parts`（trace.py:880），不再悄悄跳过。`runs` 会因此把 run 标成 partial。
- `names` 取第一个出现的值。`procs` 带上 `t0` / `t` / `why` / `py` / `argv_cut` / `title`，按起始时刻排序（trace.py:929）。`file_edges` 只用来打印摘要，不存。

### 折算时分开「调用」和「import 触发的执行」
被调方是模块帧的边不算调用，单独记进 `edge_import_exec`，否则每条 import 边都会因为「导入过」被染成橙色。没有自己符号的帧（闭包、lambda、生成器表达式）按符号的起止行归到最内层的外层符号，标成 `外层.<L行号>`。`to_package_graph` 还按文件汇总调用次数（trace.py:1048，同样不算 import 触发的模块执行），详情面板的文件树据此标出这次 case 走过哪里。

## 局限
- 栈深超过 2000 时砍掉一半兜底（trace.py:227），极深递归下调用者可能不准。
- 阶段切换和 STOP 最多都有 1 秒延迟：case 脚本写完 PHASE 后应该等一两秒再开始下一段。被 SIGTERM 停掉的进程，数据截止到发信号前 1 秒左右；被 SIGKILL 的，或者 driver 自己被 kill -9、没来得及写 STOP 的，计数最多丢 10 秒、事件最多丢 1 秒。`_final` 置上之后（atexit 那次落盘开始后）发生的调用两边都不记。
- 事件要 Python 3.12+；被 trace 的解释器更老时 `--events` 录不到东西，只有 driver 的提示。
- 半路被丢掉的生成器，时序上显示为没返回：3.12 关闭它时不发任何事件，hook 不知道它什么时候结束。
- fork 出的子进程继承父进程 import 时读到的命令行，只能靠 `pid` / `ppid` 区分。`title` 只在命令行第一项变了时才记。
- 只包了 `os.execv` / `os.execve`，绕过 os 模块直接调 posix 那一层的 exec 不会先落盘。
- 残留进程的两种认法都依赖 /proc，只有 Linux 能用。
- `case_script` 是启发式：虚拟环境 bin 目录下的 console-script 入口会被当成 case 脚本；`python -m pkg.mod`、`bash -c "…"` 认不出脚本。

## 不确定
- `_lock` 为什么用 `RLock` 而不是普通锁，代码里没说。说得通的场景：主线程正在 `_dump` 里持锁，被 trace 程序的信号处理器调了 `os._exit`，`_exit_hook` 在同一个线程里再拿一次锁，普通锁就会自己锁死。
- `why=stop` 的进程在 `runs` 那边不算 unclean（runs.py:357 只认 periodic / phase），虽然它最后约 1 秒的数据也没了。看起来是有意把「按流程停掉」和「被强杀」分开。
- `_ev_flush` 只保证「不丢」，没说「不重」：主线程的最后一次落盘若在「行已写进文件」和「删缓冲」之间被信号处理器打断，`_dump` 重试会把同一批行再写一遍，同一个 span 号的调用行重复，整理时会多出一条。窗口很小，是否值得处理不清楚。开销在 GPU 上带不带事件的实测还没做（设计 M3 的待办）。
