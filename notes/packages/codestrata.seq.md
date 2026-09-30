---
written_by: claude-opus-5-5
target: codestrata.seq
kind: package
code_sha: b598a15052c5eaa3
status: draft
refs: serve.py:201@cd0d48b0,seq.py:12@259708fd,seq.py:89@1dfe6538,seq.py:103@22e1203c,seq.py:1@e766aab3,seq.py:41@92a52552,seq.py:54@f794f819,seq.py:81@34dd7026,seq.py:115@54fbe19d,seq.py:128@a5d4736d,seq.py:158@d90059f9,seq.py:187@257ad441,seq.py:58@cee21ddf,seq.py:70@c37e9e0b,seq.py:92@17534da1,seq.py:135@0170bed5,seq.py:124@42053520,seq.py:200@1ba510ad,seq.py:181@4d50f98b,seq.py:179@2c3f82a8,seq.py:183@f6333c4c,seq.py:141@be7ca54a,seq.py:146@f4d455a6,seq.py:212@8467dc20,seq.py:228@132f4cc2,seq.py:227@b5d8b34e,seq.py:151@0d3b6b04,seq.py:154@9094a156
---

## 是什么
模块图「时间顺序」的服务端：把一个 run 录下的 span（`codestrata.events` 整理好、写在 events/spans/ 里的那些）变成「当前切面上每条边在选的阶段里第一次 / 最后一次被调用的时刻、调了几次、算不算反复调用」。唯一的入口是 `edge_times`，经 `Handler._seq`（serve.py:201）对应 /api/seq/edges；前端（graph.js 的 _rankTimes）按 first 排名、上色、标序号。

早先这里是 M5 时序图的服务端（生命线 + 消息，按时间窗分屏、折叠循环、时间刷、「在时序图里看」）。模块图能把先后直接画在边上之后，时序图整个去掉了（模块 docstring 末尾有一句，seq.py:12），/api/seq、/api/seq/overview、/api/seq/find 也跟着没了。留下来的是读 span 的底层（`_index`、`_chunk`）和「键 → 切面节点」的映射（`_map` / `_Map`），新加的是 `phase_intervals`、`_pairs`、`edge_times`。

时间一律用相对 run 起点的微秒，和阶段的 t_us 在同一根轴上，所以「serving 阶段」直接就是一个（或几个）时间段。

## 为什么这样切
**不和 events 放在一起**：events 在录完之后跑一次，把结果写盘，输出和切面无关；这里每次请求按切面算。两边之间只隔着 spans/ 的文件格式（index.json、keys.json、p<pid>-NNN.jsonl.gz）。

**不和 serve 放在一起**：serve 只解析 run 引用和 open，算法都在这里，测试可以直接调 `edge_times`（test_seq_edge_times、test_phase_intervals），只有 test_edge_times_api 走真的 serve。

**「键 → 符号」和模块图共用一份**：键怎么对回符号由 `trace.sym_locs` 给出（seq.py:89），`to_package_graph` 用的是同一个函数；哪些帧是「定义时的执行」、不算调用，也由同一个 `trace.defining` 判（seq.py:103，在 `_Map.of` 里）。所以整个 run 上每条边的次数和 hot 图上的调用次数逐条相等（test_seq_edge_times 断言了这一点）。

**读一遍，按切面归很多次**：解压、读 span 是贵的那一步（158 万条的 run 要两秒多），归到切面的节点很便宜。所以分成两步：`_pairs` 把整个 run 读一遍、按「原始键对」聚合，和切面无关；`edge_times` 再把键对归到当前切面的节点上。展开 / 收起、换阶段都不用再解压。

## 读法
1. 模块 docstring（seq.py:1）：两步各做什么、为什么。设计稿 `docs/design/runs.md` 的 7.4 讲的是已经去掉的时序图，只有「键怎么映射到切面」那部分还对得上。
2. `_index`（seq.py:41）、`_chunk`（seq.py:54）：读 span 文件。
3. `_Map`（seq.py:81）：键 → 节点。
4. `phase_intervals`（seq.py:115）→ `_pairs`（seq.py:128）→ `_pairs_scan`（seq.py:158）→ `edge_times`（seq.py:187）。
5. `tests/test_runs.py` 的 test_seq_edge_times（另写一遍「键 → 单元 → 节点、同一节点 / 定义时的执行 / index 外的不算」，和 `edge_times` 逐条比 first、last、n；整个 run 上再和 hot 图的边次数比）、test_phase_intervals、test_edge_times_api。

## 关键算法
### 读 span
index.json 和 keys.json 一起按 (目录, index 的 mtime) 缓存（`_index`，经 `_put` 写入，最多 16 项，满了丢最早放进去的）。每次 merge 重建 spans，index 的 mtime 都会变、多出一项，serve 开得再久也不会一直涨。块本身不缓存：`_chunk` 每次解压，一块一次 json.loads（把各行拼成一个 JSON 数组，seq.py:58）——逐行 loads 慢三倍，读整个 run 的时间几乎都花在这里。早先给时序图用的 16 块 LRU 和按时间窗挑块的 spans_in 都去掉了：现在只有 `_pairs` 读块，而它总是读全部、读完就只留聚合结果。

### _Map：键 → 节点
每个 (index, 切面) 建一张映射表，`_map` 缓存最近的 8 张。缓存键用的是 id(idx)，值里把 idx 本身也存着（seq.py:70）：只要这一项还在缓存里，旧 index 就不会被回收，它的 id 也不会被 serve 新载入的 index 复用，新 index 的请求就不会配到旧表上。

`of` 把 rel:行 解析成 (节点, 是不是定义时的执行)，按键记住（seq.py:92）。节点来自 rel → 单元（index 的 files）→ `cut.view` 的 `node_of`；落在 index 之外的文件（scan 排除掉的 examples、case 自己的代码 <外部代码>/…）和 "?" 都是 None。早先给时序图用的显示名、符号键、包住这一行的最内层符号都去掉了：`edge_times` 只要节点和「是不是定义」。

### phase_intervals：每个阶段是哪几段时间
按 phase_log（[名字, t_us, 来源]）排序，每个条目到下一个条目是一段，最后一段开到 run 的终点（各块 t1_us 里最大的，seq.py:135）；同一个阶段切走又切回来就有几段（seq.py:124）。老 run 没有 phase_log 时退回 phases 的 t_us，没有时刻的阶段不进表。None 是整个 run，[(0, 终点)]。请求的阶段不在表里时 `edge_times` 抛 `LookupError`：「不知道它从什么时候开始，没法按时间排」（seq.py:200）——不悄悄退成整个 run，serve 给 404。

### _pairs：整个 run 读一遍
每个阶段（和 None）一张表：(调用方键, 被调方键) → [first, last, n, {pid: [first, last]}]。每条 span 先进 None 那张，再按开始时刻二分找到它落在哪个阶段的哪一段（seq.py:181），进那个阶段的表；落在第一个阶段之前的只算整个 run。折叠过的 span（rep 次连续的同级调用合成一行）：first 是这一行的开始，last 取这一行的结束——最后一次调用的开始不会晚于它——但不超过所在那一段的终点（seq.py:179、seq.py:183）；没折叠的 last 就是开始时刻。

结果按 (spans 目录, index 的 mtime, 阶段划分) 缓存最近 4 份（`_PAIRS`）。同时来的同一个请求只算一次：没命中时在 `_BUSY` 里按键拿一把锁（seq.py:141），拿到锁再查一次缓存（seq.py:146），前一个算完的已经放进去了就直接用——页面刚打开「时间顺序」时、或者连着点了几个切面，不会各自解压一遍。这次改动时记下的数字（我没复测）：158 万条 span 的 sympy run 第一次 2.2 s，之后换阶段 9 ms、每个新切面约 30 ms；vllm-omni 的 run 0.22 s。

### edge_times：归到切面、算「反复调用」
对选中阶段那张表的每个键对，两端经 `_Map.of` 找节点：有一端是 None（index 外、"?"）、两端是同一个节点（节点内部的调用，展开之后才会变成边）、被调方是定义时的执行（模块顶层、类体），都不算（seq.py:212）。其余按「a|b」合并：first 取最小、last 取最大、n 相加，每个进程的 [first, last] 也按进程合并。结果按 (_PAIRS 的键, id(idx), 切面, 阶段) 缓存（`_EDGES`，最多 16 份），值里连 idx 一起存、命中时核对是不是同一个 idx——和 `_map` 一样，重新扫出来的 index 不会配到旧结果上。

repeat（前端画 ↻）：n 至少 `REPEAT_MIN`（5）次，而且 spread 超过这个阶段各段加起来总长的一半（seq.py:228）。spread 是同一个进程里第一次到最后一次隔了多久、取各进程里最长的（seq.py:227）：几个 worker 各初始化一次、隔得再远也不算反复；轮询、每个 token 都走一遍的路径才算。它的序号于是只说明「从什么时候开始」。

返回 {window: [第一段的起点, 最后一段的终点], intervals, span_us: 各段加起来多长, edges: {"a|b": {first, last, n, spread, repeat}}, truncated}。truncated 是 index 里到了行数上限的进程，原样交给页面：那之后的调用没有时间，前端照原来的颜色画、图例上加 ⚠。

## 局限
- 阶段按时刻切：fork 出来的子进程是轮询着跟着切阶段的，阶段边界附近的调用可能算进相邻的阶段。只有整个 run 上的次数和 hot 图逐条相等；分阶段时，hot 图上跑到了的边可能在这一段里没有时间（前端悬停说「阶段边界上差一点」）。
- 第一次请求要解压整个 run（大 run 秒级），这期间页面不上色；缓存只留 4 个 run 的聚合结果，来回换第五个 run 会重新读。
- 事件录到上限的进程，之后的调用没有时间，也就不参加排名。
- 同一个阶段有几段时，window 是从第一段的起点到最后一段的终点，中间夹着别的阶段；first / last 仍是相对 run 起点的时刻，前端按 window 的起点换成秒。

## 不确定
- 结果算完先放进 `_PAIRS`（seq.py:151），再在 finally 里撤掉 `_BUSY` 的锁（seq.py:154）：中间新来的同一个请求要么命中缓存、要么等在锁上，不会再解压一遍。没有并发测试覆盖这一点。
