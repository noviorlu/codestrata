---
written_by: claude-opus-5-5
target: codestrata.events
kind: package
code_sha: a767f0b4997792d5
status: draft
refs: runs.py:337@dcfcecf7,events.py:1@d55ae9b7,trace.py:181@1d353c75,trace.py:193@b260cb52,runs.py:434@1c2edb45,runs.py:435@fe850b3d,runs.py:877@4b07558f,events.py:212@4a27af2c,events.py:89@d6a1c510,events.py:90@2923c6fd,events.py:46@1e268470,events.py:86@694758bc,events.py:133@4dc922c2,events.py:155@3ffeef37,events.py:230@e0f60905,events.py:59@f481dd39,trace.py:149@3ae807b8,events.py:61@39e08d8e,events.py:98@146cc466,events.py:101@931d6e12,events.py:117@84e62137,events.py:112@6a1a11d0,events.py:114@32f9c7ef,events.py:110@2e733f31,events.py:125@41c69a8a,events.py:129@41c69a8a,trace.py:198@5cea0e5e,events.py:148@11981dd3,events.py:141@a086712f,events.py:171@1cdd9bdf,events.py:189@c28c5074,trace.py:191@d683aaef,events.py:179@ec2a9567,events.py:205@736f971c,events.py:214@8c5549f2,events.py:222@4c177812,events.py:166@9e27b77d
---

## 是什么
时序图的数据层（M3 新加的模块）。`trace --events` 录制时，hook 给每个进程映像（fork 出来的子进程、exec 之后的新程序，各算一个映像）写一份文本日志 ev-<pid>-<t0ns>.log，只记**跨文件**的调用，口径和 func_edges 相同。这个模块把这些原始日志整理成配好对的 span，写进 run 目录的 events/spans/。每个 span 是一行：

```
[t0_us, dur_us, tid, depth, a, b, rep, n_susp]
```
- t0_us 相对整个 run 的 mono0，和 run.json 里各阶段的 t_us 在同一条时间轴上。dur_us 是墙钟时间，挂起过的 span 包含挂起的时间；没返回的是 -1。
- tid 是进程内的线程号，exec 前后接着编。depth 是调用那一刻，这个线程上正在执行（没返回、也没挂起）的 span 数。
- a / b 是调用方 / 被调方在 keys.json 里的下标，键的形式是 rel:firstlineno（模块顶层是 rel:0）；登记行丢了的键指到 "?"。
- rep 是第一级折叠合了几次；n_susp 是挂起了几次，大于 0 就是 async 的 span。

整个模块是一条流水线：`parse`（读一个日志）→ `pair`（配成 span）→ `fold`（第一级折叠）→ `build`（把整个 run 拼起来并写出），`read_spans` 再把写出的 span 读回来。调用方只有 runs：`finalize` 和 `merge_run` 都经 `_build_events`（runs.py:337）进来。

日志的行格式写在模块 docstring 里（events.py:1）。H 是文件头（pid、t0_ns、ppid），N 登记线程，K 登记键，C 是调用，R 是返回或异常展开，Y 是挂起，S 是恢复，T 表示到了行数上限。C/R/Y/S 的时间是相对这个映像 t0 的微秒，第三个数是 span 号。

## 为什么这样切
**录制端只管记，配对放到事后做。** hook 跑在被 trace 的程序里，每一次跨文件调用都要付它的开销，所以它只做最少的事：C 时分配 span 号，按 id(帧) 记进 `_xf`；R / Y / S 时按帧找回同一个 span 号写出去（`_ev_call` 在 trace.py:181，`_ev_mark` 在 trace.py:193）。depth、父子关系、折叠都在这里算，算法以后要改，也不用重录。

**span 是派生数据，原始日志才是原件。** 收尾时 `_pack_all` 先把 ev-*.log 单独打进 events/raw.tar.gz（runs.py:434），不和 parts.tar.gz 混在一起，然后才调这里整理（runs.py:435）。整理抛了异常，只在 run.json 的 events 摘要里记一个 error，计数和 status 都不受影响。`runs merge` 从 raw.tar.gz 和散着的 parts/ev-*.log 的并集重建（runs.py:877）。重建出来的必须和收尾时一样（`tests/test_runs.py` 里的 test_events_fake_service 会比对），所以 `build` 的输出是确定的：文件按名字排序处理，键表按第一次出现的顺序编号，gzip 写 mtime=0（events.py:212）。

**配对按 span 号，不按栈。** 同一线程里两个 asyncio 协程交错执行时，先开始的不一定先结束，按栈顶配会配反（truth.py 的 s_async 就是这个场景）。hook 已经把 R / Y / S 对到了 span 号上，`pair` 里的栈（active）只用来算 depth 和父 span，不参与配对。

**不和 runs 放在一起**：runs 管 run 目录，以及原始数据留不留。这个模块只做「原始日志 → span」这一步纯计算，除了 out_dir 什么都不写。M5 的时序图只需要依赖它和它写出的格式。

## 读法
1. 模块 docstring（events.py:1）：行格式和 span 的字段。和设计稿 `docs/design/runs.md` 的 7.1–7.3 对着读，尤其是 7.1 末尾「实现时的调整（M3）」和「M3 评审后补上的」这两张清单。7.3 正文、清单里讲折叠的那一条、`pair` 的 docstring（events.py:89）现在都是「按 (父 span, 段) 认兄弟」，和 `fold` 一致。落盘重试的去重设计稿里没写，只在 `pair` 的 docstring 末尾（events.py:90）。
2. `parse`（events.py:46）：很短，重点是两条丢行规则。
3. `pair`（events.py:86）→ `fold`（events.py:133）：这是核心，对着 `tests/trace_cases/fake_repo/fakesvc/truth.py` 里的场景读。
4. `build`（events.py:155）：跨进程、跨映像地拼接，然后写出。
5. `read_spans`（events.py:230），再看 `tests/test_runs.py` 里的 test_events_* 怎么用它。

## 关键算法
### parse：只信以换行结尾的行
- 只按 \n 分行（events.py:59）。默认的通用换行会把 \r 也当成行尾，名字里带 \r 的 K/N 行就会被劈开。hook 写之前已经替换掉名字里的换行（trace.py:149 的 `_clean`），这里是再防一层。
- 没有换行结尾的最后一行整行不要（events.py:61）。进程被强杀时，最后一行可能只写了一半：字段数可能正好够，值却是截断的（R 900 1 5 其实是 R 900 1 57）。按字段数来判断行是否完整，就会把返回记到错的 span 上。test_events_parse_partial_line 专门测这个。
- 其余坏行（字段不是整数、个数不够）跳过。没有 H 行时，pid 和 t0 从文件名取，ppid 留 None。

### pair：按 span 号配对，active 栈只算 depth 和父亲
`pair` 一次走完一个映像的全部事件。每个 span 记成 [t0, t1, tid, depth, a, b, n_susp, n_children, 父 span, 段]：
- **C**：先查重，同一个 span 号的 C 行第二次出现就跳过（events.py:98）。落盘中途被打断、重试时整块缓冲再写一遍，前半截就重复了；不跳过的话，这个 span 会被重置成刚开始的样子，输出里还会多出一条。查重放在最前面，重复行就来不及给当时的栈顶加孩子，那个父亲也就不会因此不算叶子、白白少合。然后父 span 取这个线程 active 栈的栈顶（events.py:101），depth 取栈的长度，父亲的 n_children 加一，入栈。span 号从 1 起，所以用 0 表示「没有父亲」。
- **R / Y**：从它**现在所在**的线程的栈里拿掉（线程由 `where` 记着，events.py:117）。通常它就在栈顶，交错时从中间拿。R 填 t1，只填第一次；Y 把 n_susp 加一。
- **S**：压到恢复它的那个线程的栈顶，所以恢复后的子调用挂在它下面，深一层。
- **重复的 Y / S**：`where` 里有的就是正在跑的，没有的是挂起了或已返回的。所以已经挂起的又来一个 Y（events.py:112）、已经在跑的又来一个 S（events.py:114），都是重试写重的行，跳过。不跳过的话，重复的 Y 让 n_susp 多算；重复的 S 把 span 再压一次栈，之后这个线程上的调用深一层，父亲挂到它身上。重复的 R 本来就无害（t1 只填第一次）。`tests/test_runs.py` 的 test_events_pair_duplicates 测这三种重复。
- 找不到 C 的 R / Y / S 直接跳过（events.py:110）。按现在的 hook，上限之后的调用不进 `_xf`，fork 之后 `_xf` 会清空，所以这只在日志坏了一段时发生。

「段」（epoch）按线程计：这个线程上每发生一次挂起或恢复就加一（events.py:125、events.py:129）。每个 span 记下自己开始时所在的段，给 `fold` 判断「是否连续」用。

半路被丢掉的生成器在 3.12 上关闭时不发事件。hook 靠 `_xf` 里一起存的 code 发现帧地址已被复用，于是作废旧账（trace.py:198）。所以这种 span 只有 C 和一次 Y，t1 一直是 None，最后写成 dur -1。它挂起时已经出栈，后面的调用不会挂到它下面（truth.py 的 s_drop / local_gen 场景）。

### fold：按 (父 span, 段) 认兄弟
`fold` 对一个线程上按 t0 排好的 span 做第一级折叠：同一个父 span 下、同一段里紧挨着的、a→b 相同的**同步叶子**（没挂起过、没有跨文件子调用、返回了），合成一条，rep 计数，t1 取最后一个的（events.py:148）。`cand` 按 (父 span, 段)（events.py:141）记着最近的一个孩子，来了一个非叶子、或者一个 a→b 不同的孩子，连续就断了。

为什么按父 span、不按深度（设计稿 7.3 最初写的是同一深度）：同一线程上交错执行的两个协程，各自的子调用深度相同，a→b 也可能相同（比如同一个处理函数在处理两个请求）。按深度，就会把两个请求的调用合成一条。

为什么还要看段，而且对**所有** span 都看：合出来的一条代表 [第一次开始, 最后一次结束] 这一整段时间。中间只要这个线程上有过挂起或恢复，别的协程就可能在这段时间里跑过，合出来的时间窗会盖住它们的调用，读图的人会以为这是一段连续执行。没有父 span 的调用（线程或协程的入口在仓库外，都挂在「父亲 0」下）尤其需要，但有父亲的也一样：父亲在两个孩子之间 await 过，这两个孩子就不连续。代价是 async 代码里少合一些。truth.py 的 s_async2：两个 handle2 各调两次 other.deep，中间隔着一个 await，结果是四条 rep=1，而不是按深度合成的一条 rep=4（测试只要求每条不超过 2、总数是 4）。

同一个父亲、同一段里的两个相邻叶子之间，只可能夹着父亲自己在同文件里的工作，因为任何跨文件调用都会记成兄弟、把连续打断。所以合并不丢跨文件的信息，Σrep 仍然等于跨文件 func_edges 的总数，test_events_truth 和 test_events_fake_service 都核对这个等式。

### build：把各个映像拼到 run 的时间轴上
- **时间**：每个映像的 H 行带着自己的 t0_ns（monotonic 时钟，全机共享），`(t0 - mono0) // 1000` 就是它相对 run 起点的偏移（events.py:171），加到它每个 span 的 t0 上。mono0 缺了就按 0 算，这时各进程之间对不齐。
- **键表**：K 号是进程内的小整数。按键字符串合成一张全局表，a / b 换成全局下标。没登记过的键指到表里的一个 "?"（events.py:189），这一项只在真的缺键时才加。以前写 -1，Python 里 keys[-1] 会静默取到最后一个键，读的一方不注意就指到别的函数上。正常录制里 K 行总在用到它的 C 行之前（trace.py:191 先求值 `_ev_kid`），只有日志坏了才会出现 "?"。
- **线程号**：同一个 pid 的多个映像（exec 前后）线程号都从 1 起，直接合并会互相覆盖名字。所以后一个映像的 tid 要加上前面各映像的最大 tid（events.py:179）。fork 出来的子进程 pid 不同，不受影响。keys.json 的 threads 是 {pid: {tid: 线程名}}，用的是换过之后的号。
- **按线程折叠**：`pair` 的输出按 C 时的 tid 分组，按 t0 排好，再交给 `fold`。
- **procs**：每个映像一条 {pid, ppid, t0_us, n_events, n_spans, truncated}，exec 过的 pid 会出现两次。
- **truncated**：日志里有 T 行的 pid。上限只管 C，R/Y/S 照写，所以上限之前开始的调用照样有返回时刻（test_events_cap）。上限到了 run 的 status 也不变。

### 写出和换上
同一个 pid 的所有 span 按 (t0, depth) 排序（events.py:205），同一微秒里父亲排在孩子前面。每 `CHUNK` 行（10 万）写一块 p<pid>-NNN.jsonl.gz。index.json 给每块记 t0_us（第一行的起点）和 t1_us（块里最晚的结束时刻，没返回的只算起点，events.py:214）。此外还有 procs、truncated、n_lines（解析出的 C/R/Y/S 事件数）、n_spans、n_calls（Σrep），以及一个固定的 pairing: frame。

所有文件先写到 spans.<pid>.tmp，然后把旧目录挪成 .old、把新目录挪进来、删掉 .old（events.py:222 起）。`os.replace` 不能把目录换到非空目录上，所以分两步。两步之间崩了，spans/ 会暂时不存在；但这是派生数据，merge 能重来。

### M5 的时序图会读什么
设计稿 7.4 打算每次请求现算（seq.py 还没写），读的是这些：
- **index.json 的 chunks**：按 [t0_us, t1_us] 挑出和时间窗重叠的块，只解压这些块（设计稿里放进一个 16 块的 LRU）。同一个 pid 的块内、块间都按 t0 有序。
- **index.json 的 procs**：子进程在它的 t0_us 时刻，从 ppid 画一条派生箭头。argv 摘要不在这里，要另从 detail.json 的 procs 拿。
- **keys.json**：keys 用来把 a / b 经 rel → 单元 → `node_of` 映射到切面上的节点，两端落在不同节点的才画；"?" 映射不到，要跳过。threads 给 (pid, tid) 起名；第二级折叠也按 (pid, tid) 分组。
- **行本身**：rep 用来显示 ×n，n_susp 和 dur 放进 async 消息的详情，dur = -1 表示没返回。
- 时间轴和 run.json 里阶段的 t_us 是同一个，「serving 阶段」直接就是一个时间窗（test_events_fake_service 就是这么取的）。

现在的 `read_spans` 一次读回全部块（或某个 pid 的全部块），只够测试用。按时间窗读和缓存要 M5 自己做。

## 局限
- 「段」只在**录下来的** span 挂起或恢复时加一。协程自己不是 span（入口在仓库外，或者调用它的在同一个文件里）时，它们互相切换不留痕迹：挂在同一个父亲（外层的 span，或者 0）下的叶子调用，只要 a→b 相同、中间又没有别的 span 挂起过，照样会合成一条。
- 去重看的是 span 当时的状态，不是行本身。重试时整块重写，重复的是被打断前已经写出的那一截，不是紧挨着的两行：这一截里同一个 span 要是既恢复又挂起了，重放时每一行在当时的状态下都合法，会再算一遍，n_susp 多一、段多加两次（只会少合）。depth 和父子关系不受影响，因为重放段里的 C 都被跳过了。test_events_pair_duplicates 用的是紧挨着的重复行，没覆盖这种情况。
- keys.json 里只有 rel:firstlineno，没有函数名。要显示函数名，得另从 counts.json.gz 的 names 拿（设计稿 7.3 现在也是这么写的）。
- 崩在中途留下的 spans.<pid>.tmp / spans.<pid>.old，只有同一个 pid 再跑 `build` 时才会清掉；换了 pid 就一直留在 events/ 里（`remove_events` 删整个 events/ 时一起删掉）。
- 一个映像的全部事件一次读进内存配对，所有 span 也要在内存里攒齐才写出。设计稿估算原始日志有 20–30 MB 文本，实测要等 GPU 录制。

## 不确定
- 日志文件按名字的字符串顺序处理（events.py:166）。同一 pid 的两个映像，t0_ns 位数不同时顺序会反过来。这只影响哪个映像拿到小的线程号，不影响正确性。
