---
written_by: claude-opus-5-5
target: codestrata.seq
kind: package
code_sha: 146870124a93bc3c
status: draft
refs: serve.py:201@cd0d48b0,seq.py:12@259708fd,seq.py:90@1dfe6538,seq.py:104@22e1203c,seq.py:1@e766aab3,seq.py:42@92a52552,seq.py:55@f794f819,seq.py:82@34dd7026,seq.py:116@e173b926,seq.py:124@c2e822c9,seq.py:131@54fbe19d,seq.py:153@38a67f56,seq.py:173@d2d93635,seq.py:210@87dba17c,seq.py:240@1177df8c,seq.py:279@257ad441,seq.py:139@8fca762e,seq.py:168@56ee871a,seq.py:188@ccaf47af,seq.py:59@cee21ddf,seq.py:71@c37e9e0b,seq.py:93@17534da1,seq.py:128@e213fd59,seq.py:135@be0bee30,seq.py:295@1ba510ad,seq.py:158@8ad61907,seq.py:163@4cf82208,seq.py:180@06961400,seq.py:178@7d2ed56a,seq.py:265@4dae730e,seq.py:270@ff74ea61,seq.py:271@a56bb831,seq.py:272@ebe0289a,seq.py:218@f3e0c8b5,seq.py:260@1730468e,seq.py:198@0672036a,seq.py:201@17698fb4,seq.py:233@cf6754bc,seq.py:223@be7ca54a,seq.py:228@f4d455a6,seq.py:307@8467dc20,seq.py:292@832b4604,seq.py:323@132f4cc2,seq.py:322@b5d8b34e,seq.py:236@9094a156
---

## 是什么
模块图「时间顺序」的服务端：把一个 run 录下的 span（`codestrata.events` 整理好、写在 events/spans/ 里的那些）变成「当前切面上每条边在选的阶段里第一次 / 最后一次被调用的时刻、调了几次、算不算反复调用」。页面上的入口是 `edge_times`，经 `Handler._seq`（serve.py:201）对应 /api/seq/edges；前端（graph.js 的 _rankTimes）按 first 排名、上色、标序号。工具栏的阶段按钮换成时间轴（web/timebar.js）之后，`runs` 也 import 这里，用四个小函数：`phase_segments`（时间条上一段段的颜色，`runs.load` 放进 meta 的 timeline）、`run_end`（时间条的终点）、`parse_window`（认 run 引用 @ 后面的「t=起-止」）、`window_counts`（拖出来的那段时间里的调用次数，代替 counts.json.gz 叠到模块图上）；span 文件坏了时给人看的那句话也在这里（`unreadable`），`runs.load` 和 serve 共用。

早先这里是 M5 时序图的服务端（生命线 + 消息，按时间窗分屏、折叠循环、时间刷、「在时序图里看」）。模块图能把先后直接画在边上之后，时序图整个去掉了（模块 docstring 末尾有一句，seq.py:12），/api/seq、/api/seq/overview、/api/seq/find 也跟着没了。留下来的是读 span 的底层（`_index`、`_chunk`）和「键 → 切面节点」的映射（`_map` / `_Map`），新加的是 `phase_intervals`、`_pairs`、`edge_times`，时间轴又加了上面那几个和把折叠行摊开的 `_calls_in`。

时间一律用相对 run 起点的微秒，和阶段的 t_us 在同一根轴上，所以「serving 阶段」直接就是一个（或几个）时间段。时间轴上拖出来的一段也是这根轴上的 [起, 止]，写成 t=起-止，放在和阶段名同一个位置（run 引用的 @ 后面）：`runs.resolve`、serve 的缓存键、页面地址都照走，不另开通道。

## 为什么这样切
**不和 events 放在一起**：events 在录完之后跑一次，把结果写盘，输出和切面无关；这里每次请求按切面算。两边之间只隔着 spans/ 的文件格式（index.json、keys.json、p<pid>-NNN.jsonl.gz）。

**不和 serve 放在一起**：serve 只解析 run 引用和 open，算法都在这里，测试可以直接调 `edge_times`（test_seq_edge_times、test_phase_intervals），只有 test_edge_times_api 走真的 serve。

**「键 → 符号」和模块图共用一份**：键怎么对回符号由 `trace.sym_locs` 给出（seq.py:90），`to_package_graph` 用的是同一个函数；哪些帧是「定义时的执行」、不算调用，也由同一个 `trace.defining` 判（seq.py:104，在 `_Map.of` 里）。所以整个 run 上每条边的次数和 hot 图上的调用次数逐条相等（test_seq_edge_times 断言了这一点）。

**读一遍，按切面归很多次**：解压、读 span 是贵的那一步（158 万条的 run 要两秒多），归到切面的节点很便宜。所以分成两步：`_pairs` 把整个 run 读一遍、按「原始键对」聚合，和切面无关；`edge_times` 再把键对归到当前切面的节点上。展开 / 收起、换阶段都不用再解压。

**时间段的次数也在这里算**：counts.json.gz 是录制时按阶段切的，分不出任意一段时间，带时刻的只有时序事件。`window_counts` 读同一份 spans/（`_index`、`_chunk`），交出 counts.json.gz 那种形状的 {funcs, func_edges}（键都是 文件:首行），`runs.load` 拿它换掉阶段的计数，后面的 `remap`、`trace.to_package_graph` 一步不改。于是时间段的 hot 图和同一段时间的「时间顺序」出自同一批 span、同一个 `_calls_in`，边次数和 `edge_times` 的 n 逐条相等（test_time_window）。`parse_window` 放在这里，是因为 `runs`（resolve / load）和 `edge_times` 认的是同一种写法。

## 读法
1. 模块 docstring（seq.py:1）：两步各做什么、为什么。设计稿 `docs/design/runs.md` 的 7.4 讲的是已经去掉的时序图，只有「键怎么映射到切面」那部分还对得上。
2. `_index`（seq.py:42）、`_chunk`（seq.py:55）：读 span 文件。
3. `_Map`（seq.py:82）：键 → 节点。
4. `_phase_log`（seq.py:116）→ `phase_segments`（seq.py:124）→ `phase_intervals`（seq.py:131）→ `run_end`（seq.py:153）→ `_calls_in`（seq.py:173）→ `_pairs`（seq.py:210）→ `_pairs_scan`（seq.py:240）→ `edge_times`（seq.py:279）。
5. 时间轴用的另外三个：`parse_window`（seq.py:139）、`unreadable`（seq.py:168）、`window_counts`（seq.py:188），调用方是 `runs.resolve` / `runs.load`（`unreadable` 还有 serve）。
6. `tests/test_runs.py` 的 test_seq_edge_times（另写一遍「键 → 单元 → 节点、同一节点 / 定义时的执行 / index 外的不算」，折叠行展开成一次次调用、阶段的段左闭右开，和 `edge_times` 逐条比 first、last、n；整个 run 上再和 hot 图的边次数比）、test_phase_intervals（也测 `phase_segments`）、test_calls_in_and_run_end（`_calls_in` 的边界：闭区间 / 左闭右开、切成几段加起来正好是 rep、没返回的整行算在开始；`run_end` 取三样里最大的、span 坏了不算它；`_pairs` 把一行折叠的调用分到两个阶段）、test_edge_times_api（也走 @t=起-止 和写反了的时间段）、test_time_window（`window_counts` 和从原始 span 展开成一次次调用另数的一份逐条比，窗口对齐一个阶段、不对齐任何东西、有折叠行的都测；加载成 hot 图后边次数和 `edge_times` 的 n 相等；写错的时间段、没录事件的 run 怎么报）。

## 关键算法
### 读 span
index.json 和 keys.json 一起按 (目录, index 的 mtime) 缓存（`_index`，经 `_put` 写入，最多 16 项，满了丢最早放进去的）。每次 merge 重建 spans，index 的 mtime 都会变、多出一项，serve 开得再久也不会一直涨。块本身不缓存：`_chunk` 每次解压，一块一次 json.loads（把各行拼成一个 JSON 数组，seq.py:59）——逐行 loads 慢三倍，读整个 run 的时间几乎都花在这里。早先给时序图用的 16 块 LRU 和按时间窗挑块的 spans_in 都去掉了：现在读块的只有 `_pairs_scan` 和 `window_counts`，读完只留聚合结果。

### _Map：键 → 节点
每个 (index, 切面) 建一张映射表，`_map` 缓存最近的 8 张。缓存键用的是 id(idx)，值里把 idx 本身也存着（seq.py:71）：只要这一项还在缓存里，旧 index 就不会被回收，它的 id 也不会被 serve 新载入的 index 复用，新 index 的请求就不会配到旧表上。

`of` 把 rel:行 解析成 (节点, 是不是定义时的执行)，按键记住（seq.py:93）。节点来自 rel → 单元（index 的 files）→ `cut.view` 的 `node_of`；落在 index 之外的文件（scan 排除掉的 examples、case 自己的代码 <外部代码>/…）和 "?" 都是 None。早先给时序图用的显示名、符号键、包住这一行的最内层符号都去掉了：`edge_times` 只要节点和「是不是定义」。

### phase_segments / phase_intervals：每个阶段是哪几段时间
`_phase_log` 按 phase_log（[名字, t_us, 来源]）排好切阶段的时刻；老 run 没有 phase_log 时退回 phases 的 t_us，没有时刻的阶段不进表。`phase_segments` 从每个条目到下一个条目是一段，最后一段开到传进来的终点（seq.py:128），得到按时间排的 [(名字, 起, 止)]——时间条上的色段就是它。`phase_intervals` 再按名字收起来（seq.py:135），同一个阶段切走又切回来就有几段。None 是整个 run，[(0, 终点)]。请求的阶段不在表里时 `edge_times` 抛 `LookupError`：「不知道它从什么时候开始，没法按时间排」（seq.py:295）——不悄悄退成整个 run，serve 给 404。

### run_end：时间轴的终点
`_pairs` 和 `runs.load` 用的是同一个终点：最后一条 span 的结束、最后一次切阶段、run.json 的 duration_s，三样取最大的（seq.py:158），都没有是 None。只按 span 不够：被 SIGTERM / SIGKILL 停掉的服务，最后的调用没返回，span 停在切到 shutdown 之前，最后一个阶段就成了「止比起早」的倒着的一段（test_calls_in_and_run_end 的 killed 那个例子）。span 的 index 读不出来时只是不算它（seq.py:163）：加载图不该因为 span 坏了失败，真要读 span 的地方（时间段、「时间顺序」）各自报错，说法由 `unreadable` 给（「时序数据读不出来：… 可以 runs merge 重建」）。

### _calls_in：一行 span 里有几次调用落在一段时间里
events 的第一级折叠把 rep 次连续的同级调用合成一行，只记第一次的开始和整行的结束。这里把 rep 次调用均匀摊在 [开始, 结束] 上（第 i 次在 开始 + i·时长/(rep−1)，seq.py:180），数落在 [lo, hi]（open_hi 时 [lo, hi)）里的有几次，同时给出其中第一次和最后一次的开始。没折叠的、没返回的（dur < 0，只知道开始）整行算在开始那一刻（seq.py:178）。为什么要摊：一行能盖住几十秒（docstring 里的例子是 vllm-omni 的轮询，一行 3852 次、从 68 s 到 112 s），整行算在开始那一刻的话，一秒的时间段里会多出几千次、之后几十秒一次都没有，阶段之间也一样。均匀是个近似：只知道总数和首尾，不知道中间每一次的时刻。

### _pairs：整个 run 读一遍
每个阶段（和 None）一张表：(调用方键, 被调方键) → [first, last, n, {pid: [first, last]}]，first / last 是落在这张表里的第一次 / 最后一次调用的开始。每行先按 `_calls_in` 进 None 那张（[0, 终点]，seq.py:265），再从它开始时刻所在的那一段起（二分，seq.py:270），往后把它盖到的每一段都用 `_calls_in` 分一份（seq.py:271）：一行折叠的调用跨了几个阶段就分到几个阶段，不重不漏（test_calls_in_and_run_end 核对了切成几段加起来正好是 rep）。阶段的各段左闭右开——切阶段那一刻的调用归新阶段——只有最后一段闭到终点（seq.py:272）。落在第一个阶段之前的调用只算整个 run。

**时间段**（window）：阶段划分换成只有一段的 {None: [window]}（seq.py:218），`_pairs_scan` 跳过和 [lo, hi] 不重叠的块（seq.py:260），每行只数落在里面的那几次；出来的只有 None 一张表。按块的 t0_us / t1_us 跳不会漏：events 写块前把每个 pid 的行按开始时刻排好，t0_us 是第一行的开始、t1_us 是块里最晚的结束，块里每一次调用的开始都在这两个数之间。按阶段时 [lo, hi] 就是 [0, 终点]，也就是整个 run。`window_counts` 按同样的规则挑块（seq.py:198）、用同一个 `_calls_in` 数（seq.py:201），只数次数，不留时刻。

结果按 (spans 目录, index 的 mtime, 阶段划分) 缓存最近 8 份（`_PAIRS`，seq.py:233）。时间段也是一种「阶段划分」：每拖出一段就是新的一份，要把和它重叠的块再读一遍。同时来的同一个请求只算一次：没命中时在 `_BUSY` 里按键拿一把锁（seq.py:223），拿到锁再查一次缓存（seq.py:228），前一个算完的已经放进去了就直接用——页面刚打开「时间顺序」时、或者连着点了几个切面，不会各自解压一遍。这次改动时记下的数字（我没复测）：158 万条 span 的 sympy run 第一次 2.2 s，之后换阶段 9 ms、每个新切面约 30 ms；vllm-omni 的 run 0.22 s。

### edge_times：归到切面、算「反复调用」
对选中阶段那张表的每个键对，两端经 `_Map.of` 找节点：有一端是 None（index 外、"?"）、两端是同一个节点（节点内部的调用，展开之后才会变成边）、被调方是定义时的执行（模块顶层、类体），都不算（seq.py:307）。其余按「a|b」合并：first 取最小、last 取最大、n 相加，每个进程的 [first, last] 也按进程合并。选的是时间段时（seq.py:292），阶段换成 None、用的是 `_pairs` 按这段时间算的那张表：window 就是这段时间本身，span_us 是它的长度，「反复调用」也按它的一半算。结果按 (_PAIRS 的键, id(idx), 切面, 阶段) 缓存（`_EDGES`，最多 16 份），值里连 idx 一起存、命中时核对是不是同一个 idx——和 `_map` 一样，重新扫出来的 index 不会配到旧结果上。

repeat（前端画 ↻）：n 至少 `REPEAT_MIN`（5）次，而且 spread 超过这个阶段各段加起来总长的一半（seq.py:323）。spread 是同一个进程里第一次到最后一次隔了多久、取各进程里最长的（seq.py:322）：几个 worker 各初始化一次、隔得再远也不算反复；轮询、每个 token 都走一遍的路径才算。它的序号于是只说明「从什么时候开始」。

返回 {window: [第一段的起点, 最后一段的终点], intervals, span_us: 各段加起来多长, edges: {"a|b": {first, last, n, spread, repeat}}, truncated}。truncated 是 index 里到了行数上限的进程，原样交给页面：那之后的调用没有时间，前端照原来的颜色画、图例上加 ⚠。

## 局限
- 阶段按时刻切：fork 出来的子进程是轮询着跟着切阶段的，阶段边界附近的调用可能算进相邻的阶段。只有整个 run 上的次数和 hot 图逐条相等；分阶段时，hot 图上跑到了的边可能在这一段里没有时间（前端悬停说「阶段边界上差一点」）。
- 折叠行按均匀摊开算：真实的调用时刻在首尾之间不一定均匀（先密后疏、中间停过），落在时间段或阶段边界附近的那几次可能分错边。整个 run 上的总数不受影响。
- 第一次请求要解压整个 run（大 run 秒级），这期间页面不上色；缓存只留 8 份聚合结果（一个 run 的阶段划分算一份，每个拖出来的时间段也各算一份），来回换得多了会重新读。`window_counts` 不缓存，每次加载都读一遍重叠的块（serve 另按 run 引用缓存 `runs.load` 的结果）。
- 时间段的次数只有跨文件的调用：时序事件只记跨文件的调用，同一个文件里的调用不在里面，函数、文件、节点上的次数会比按阶段看的少（页面横幅写明）。节点之间的边不受影响：两端在不同文件，一定是跨文件的调用。
- 事件录到上限的进程，之后的调用不在时间段的次数里；页面上只有「时间顺序」的图例会提示 ⚠，时间段的横幅不提。
- 事件录到上限的进程，之后的调用没有时间，也就不参加排名。
- 同一个阶段有几段时，window 是从第一段的起点到最后一段的终点，中间夹着别的阶段；first / last 仍是相对 run 起点的时刻，前端按 window 的起点换成秒。

## 不确定
- 结果算完先放进 `_PAIRS`（seq.py:233），再在 finally 里撤掉 `_BUSY` 的锁（seq.py:236）：中间新来的同一个请求要么命中缓存、要么等在锁上，不会再解压一遍。没有并发测试覆盖这一点。
