---
written_by: claude-opus-5-5
target: codestrata.seq
kind: package
code_sha: f43205a6fb510196
status: draft
refs: serve.py:197@cd0d48b0,seq.py:30@d2fe4395,seq.py:31@f165eef3,seq.py:1@304d1b5d,seq.py:85@43f9c39a,seq.py:120@34dd7026,seq.py:167@61ce1067,seq.py:256@fd849997,seq.py:197@611c8331,seq.py:240@a038f312,seq.py:263@68d56e72,seq.py:321@cdc2e97a,seq.py:333@e12f9208,seq.py:458@9d9e6eae,seq.py:479@be801626,seq.py:91@0672036a,seq.py:80@67bd13ba,seq.py:44@1d1d28f5,seq.py:96@1bee3588,seq.py:109@c37e9e0b,seq.py:132@b06c4d35,seq.py:159@39442eb4,seq.py:176@cb1fc72f,seq.py:501@e84b4c7d,seq.py:260@f4212c28,seq.py:207@7e1453a5,seq.py:217@be625d98,codestrata/web/seq.js:248@407f576e,seq.py:247@3830fda0,seq.py:276@fc7d4dd0,seq.py:282@9a554aeb,seq.py:286@8926a1d8,seq.py:324@7d78a787,seq.py:330@ccaa9583,seq.py:328@b47beb03,seq.py:345@a888ad0a,seq.py:356@86170292,seq.py:394@ce625da7,seq.py:36@e9373c14,seq.py:375@511d3e8e,seq.py:377@054bf37f,seq.py:380@5ecfc7ae,seq.py:384@196dce40,seq.py:401@a6ba8106,seq.py:307@ea17d85f,seq.py:317@f3e51ce3,seq.py:426@bfa9e50c,seq.py:437@881709d7,cut.py:171@577ac73b,seq.py:422@4b935c97,seq.py:431@7488f4bc,codestrata/web/seq.js:174@04b2edcd,seq.py:433@14e2e6b6,seq.py:448@79fd9e84,seq.py:473@545713f1,seq.py:462@78c02b35,seq.py:472@03679a05,serve.py:224@6c4aa61f,seq.py:507@93d0dc85,codestrata/web/app.js:571@6a135785,seq.py:396@675c27cf
---

## 是什么
M5 时序图的服务端。它把一个 run 录下的 span（`codestrata.events` 整理好、写在 events/spans/ 里的那些）变成当前切面上的一张时序图。三个入口都经 `Handler._seq`（serve.py:197）进来：`build` 对应 /api/seq，`overview` 对应 /api/seq/overview，`find` 对应 /api/seq/find。前端 `codestrata/web/seq.js` 只管画。

图上有两样东西：
- **生命线** = (进程, 切面节点)。同一个节点在两个进程里各占一条，因为进程之间只画确定的关系（fork/exec 派生），IPC 交接不画（设计稿 7.4）。
- **消息** = 一次两端落在不同节点上的跨文件调用。span 只记了「rel:首行号 → rel:首行号」，要经 rel → 单元 → `node_of` 映射，才知道它从哪条生命线到哪条。

所以这张图和模块图一样**每次请求现算**：切面一变（比如展开一个包），同一个 span 可能从「节点内部」变成一条消息，生命线也会跟着拆开。能缓存的只有两类：和切面无关的东西（解压好的块、index、overview），以及 (index, 切面) → 映射表。

时间一律用相对 run 起点的微秒，和阶段的 t_us 在同一根轴上，所以「serving 阶段」直接就是一个时间窗。

## 为什么这样切
**不和 events 放在一起**：events 在录完之后跑一次，把结果写盘，输出和切面无关；这里每次请求都按切面算一遍。两边之间只隔着 spans/ 的文件格式（index.json、keys.json、p<pid>-NNN.jsonl.gz）。

**不和 serve 放在一起**：serve 只解析参数（run 引用、open、t0/t1/max/fold），再把阶段换算成时间窗；算法都在这里。所以测试可以直接调 `build`，不用起 HTTP（test_seq_build、test_seq_fold_and_budget、test_seq_cuts_and_find、test_seq_estimate_and_fit），只有 test_seq_find_and_api 走真的 serve。

**上限按行数算，不按时间算**：行按先后排，不按时间比例画（设计稿 7.4）。一屏默认 `MAX_ROWS` = 300 行，最多 2000 行（seq.py:30、seq.py:31），所以一屏覆盖多长时间是算出来的：密的地方只有几毫秒，稀的地方有几秒。这个模块大半代码都花在这件事上：不把几十万条一次读进来，也能找到一个放得下的窗口；实在放不下，就明说放不下。

## 读法
1. 模块 docstring（seq.py:1）：六步流水线的总览。对照设计稿 `docs/design/runs.md` 的 7.4 读，再看 M5 状态说明里的「和设计的差别」和「M5 评审后补上的」。画得下就不折、分两步收窄、fold=False、next_t0、import 不画，这些改动都记在那里。
2. `spans_in`（seq.py:85）→ `_Map`（seq.py:120）→ `_messages`（seq.py:167）：从 span 到消息。
3. `_rows`（seq.py:256）、`_fold_loops`（seq.py:197）、`_with_idle`（seq.py:240）、`_fit`（seq.py:263）、`_grow`（seq.py:321）：决定一屏放什么。
4. `build`（seq.py:333）：看三种模式怎么组合上面这些函数。后半段处理生命线和进程。
5. `overview`（seq.py:458）、`find`（seq.py:479）。
6. `tests/test_runs.py` 里的 test_seq_*：test_seq_fold_and_budget 测上限和 too_dense，test_seq_cuts_and_find 测分屏的边界和 find，test_seq_estimate_and_fit 测估算那条路给的建议窗口能画出来、`_fit` 在行数不单调时也不超上限、不折叠的分屏拼起来等于整段。

## 关键算法
### spans_in：按块读，块放进 LRU
`spans_in` 只挑和时间窗重叠的块（seq.py:91；块的 t1_us 是块里最晚的结束时刻，没返回的按开始算），块内再按开始时刻筛，所以取到的是**在窗口里开始**的 span。解压好的块放进一个全局 LRU，按 (块路径, mtime) 认，最多 16 块（seq.py:80）。index.json 和 keys.json 一起按 (目录, index 的 mtime) 缓存。这份缓存和 overview 的缓存都经 `_put`（seq.py:44）写入，最多留 16 项，满了丢最早放进去的（命中时不挪位置）。每次 merge 重建 spans，index 的 mtime 都会变、多出一项，serve 开得再久也不会一直涨。结果按 (开始时刻, depth) 排序（seq.py:96），同一微秒里父亲排在孩子前面，和 events 写出时的顺序一致。

### _Map：键 → 节点和名字
每个 (index, 切面) 建一张映射表，`_map` 缓存最近的 8 张。缓存键用的是 id(idx)，值里把 idx 本身也存着（seq.py:109）。这样只要这一项还在缓存里，旧 index 就不会被回收，它的 id 也不会被 serve 新载入的 index 复用，新 index 的请求就不会配到旧表上。

`of` 把 rel:行 解析成 (节点, 显示名, 符号键, rel, 行)，结果按键记住：
- 行号先和符号的首行对，对不上再和装饰器所在的行对（seq.py:132）。被装饰的函数，code 对象的 firstlineno 是装饰器那一行。
- 两样都对不上时（比如 lambda、生成器表达式这类本身不是符号的 code 对象，或者录制之后代码挪了行），取包住这一行的最内层符号，显示成「外层名.<L行号>」（seq.py:159）。
- 行号 0 是模块顶层，显示成 <module>。

### _messages：哪些调用不画
从 seq.py:176 起按下面的顺序判断：每个 span 要么落进三类不画的之一，要么成为一条消息。
- **unmapped**：有一端落在 index 之外的文件上（比如 scan 排除掉的 examples），或者键是 "?"。
- **imports**：被调方是 rel:0，也就是 import 触发的模块顶层执行。模块图不把它算作调用，时序图也跟着不画；`find` 同样跳过它（seq.py:501），两边口径一致。
- **internal**：两端落在同一个节点。把那个节点展开，它们才会变成消息。

不画的调用不是只累加一个总数，而是逐条记成 (时刻, 原因, rep)。等窗口定下来，`_stat` 只数显示出来的那一段。自动收窄会把窗口往回收，要是先数再收，就会多算。

### _rows：画得下就不折
设计稿原来是一律找周期折叠。实测发现，三次请求被折成「loop ×3」反而看不出结构。现在先按不折的行数算：没超过上限就原样画，超了才把整屏交给 `_fold_loops`（seq.py:260）。fold=False（点开一个 loop 时）一律不折。

### _fold_loops：记号和贪心
按 (pid, tid) 分组，每条消息转成一个记号：(调用方节点, 被调方节点, 被调方文件, 被调方首行号)（seq.py:207）。不用显示名，因为不同文件里的同名函数（run、main 之类）会被当成同一个调用。设计稿写的是「被调符号」，但符号键对不上时（<L行号> 那一类）是 None，用文件加行号更稳。

从左到右贪心：在位置 i，对每个周期 p = 1…8，数 tok[i:i+p] 连续重复了几次（k），要求至少 3 次，取覆盖条数 p×k 最多的；覆盖一样多时取较小的 p（seq.py:217）。选中的这段折成一行 loop，i 跳过被覆盖的部分；一个都找不到就 i+1。loop 行记着重复次数 n、周期 p、Σrep，以及一个周期的 body（画在这一行里）；d 算到被覆盖的消息里最晚结束的那一条。

前端点开 loop 时，请求 [t, t+d] 这一段，带 fold=0，一屏 600 行（codestrata/web/seq.js:248）。这一段里其他线程的消息也会一起出来。

### _with_idle：空闲行
相邻两行间隔超过 `IDLE_US`（50 ms）时，插一行「空闲」。消息按开始时刻算，loop 按结束时刻算（seq.py:247），prev 取的是到目前为止的最大值。所以一个长 loop 后面跟着其他线程在 loop 期间发出的消息时，间隔从 loop 结束算起，而不是从那条更早的消息算起，不会多插一行空闲。

### _fit：二分一屏放多少，退到时刻边界，再核一遍
先二分出一个前缀，使它折叠（fold=False 时不折）并插上空闲行之后不超过上限。然后**退到时刻的边界**上（seq.py:276）：下一屏从这一屏最后一条的时刻 +1 开始，如果同一微秒的调用被拆开，后一半就再也看不到了。

docstring 和设计稿都说行数随前缀单调不减，不折叠时成立，贪心折叠时不成立：记号 AAAB 重复 3 遍，取前 1…12 条，折叠后的行数依次是 1,2,1,2,3,4,3,4,5,6,5,1。二分本身取到的前缀一定放得下（只在放得下时才往右挪），但不一定是最长的；往回退到时刻边界时，行数反而可能变多（上面 11 条是 5 行，10 条是 6 行）。所以退完之后再数一遍，超了就再往前退一个时刻，最多退 64 次（seq.py:282）。一个时刻里的调用本身就多于一屏时，整组都放进来（seq.py:286），这一屏也就会超过上限。test_seq_cuts_and_find 测了时刻边界，test_seq_estimate_and_fit 用 AAAB 测了回退。

### _grow：窗口每次放宽 4 倍
serving 阶段有几十万次跨文件调用，把整个阶段读进来、映射、再折叠，要花好几秒、占几百 MB。`_grow` 从 200 ms 的窗口开始（seq.py:324），每次放宽到 4 倍（seq.py:330），直到这个窗口放不下（按 `_rows` 数，fold=False 时就是不折的行数），或者到了 limit（seq.py:328）；之后 `_fit` 只在最后一轮取到的消息里二分。limit 在自动模式下是阶段的终点，给定窗口时是窗口右端。每一轮都从 t0 重新读，按 4 倍放宽的话，前面各轮加起来不到最后一轮的三分之一；最后一轮的窗口最多比需要的宽 4 倍，多出来的交给二分去收。设计稿记的实测：在合成的 44 万次调用（5 个进程、180 s）上，冷启动 450 ms，热的 20 ms。

### build：三种模式
`max_rows` 先夹到 [20, 2000] 之间（seq.py:345）。没给 t0 时，从阶段起点开始，limit 是下一个阶段的起点（seq.py:356）；给了 t0，limit 就是整个 run 的终点。
- **自动**（没给 t1，用于默认窗口和「在时序图里看」）：先 `_grow` 再 `_fit`，截到放得下的前缀。截过的话记下 more，并把窗口右端收到最后一条消息。
- **给定窗口**（时间刷框选的窗口、too_dense 给的建议窗口）：不截断。原始 span 不多时，整段映射、按需折叠；放不下就返回 too_dense，带折叠后的行数 rows 和一个建议窗口 [t0, 能放下的最后一条]（seq.py:394），rows 为空。原始 span 超过上限的 `ESTIMATE_X` 倍（60，seq.py:36；300 行时是 18000 条）时，不把整段折一遍，而是用 `_grow` 从 t0 放宽到窗口右端（seq.py:375）。一直放宽到右端、真正要画的消息也都放得下，就照常出图（seq.py:377）。只有画不下才返回 too_dense，这时带的是原始 span 条数 calls，不是 rows，外加 estimate 标记（seq.py:380），前端据此显示「里有 N 次跨文件调用」。原先这条路直接按原始 span 数判定画不下：粗的切面上几万个 span 可能只有几条消息，建议窗口还是原来那一段，按它再请求又是 too_dense，原地打转；rows 里放的也是原始 span 数，前端却说成「折叠后还有 N 行」。设计稿记的实测：60 s 的窗口太密时，460 ms 内返回；加了这条估算的路，整个 run 当窗口时从 1.9 s 降到 0.14 s。
- **fold=False**（点开 loop）：不折叠，而且不管原始 span 多少都走 `_grow`。放不下就先给一屏，剩下的靠 next_t0 接着看（seq.py:384）。原先每按一次「下一屏」，都要把 [next_t0, t1] 整段重新读一遍、映射一遍；现在只读到这一屏放不下为止。据这次修改记下的数字（我没有复测），长 loop 里 60 s 窗口的一屏是 39 ms。

next_t0 由服务端给出（seq.py:401）：截过的，是最后一条的时刻 +1；没截过的，是窗口右端 +1；超过 run 的终点就是 None。前端的「下一屏」只认这个值，不按最后一行的结束时刻去猜，因为 loop 的 d 里可能包着挂起的时间，按它猜会跳过一段。

### 生命线和进程
- `_procs`（seq.py:307）把 detail.json 里同一个 pid 的几个映像合成一条：起始时刻和 ppid 取最早的那个（fork 的时刻）；argv、标题、结束时刻取最后一个里不为空的（exec 之后真正在跑的程序，seq.py:317）。这样，fork+exec 出来的子进程，派生行就画在 fork 的时刻，排在它 exec 之前的那些调用前面（test_seq_cuts_and_find 测了这一点）。
- 只给窗口里出现过的 (pid, 节点) 画生命线。进程之间按起始时刻排（seq.py:426）；同一进程内按架构高度从高到低排，高度相同再按节点名排（seq.py:437）。高度来自 `cut.view`，算法是 (出边 − 入边) / 总数（cut.py:171），和模块图从上到下的方向一致：出边多的、偏调用方的节点排在左边。
- 标签：有标题就用标题，否则用 argv 摘要（去掉 python 和 -m，最长 80 个字符）。argv 摘要相同的进程按启动先后加上 #1…#n。编号按整个 run 的全部进程算（seq.py:422），不是只算这一屏的，所以翻屏时同一个进程的编号不会变。
- 隐去密钥：发给页面的 argv 先过一遍 `runs._redact_argv`（seq.py:431），和 `runs.load` 给网页的 case 命令、进程表用的是同一个函数：--env 里名字像密钥的值、--api-key 这类选项的值、URL 里的账号密码都换成 <已隐去>。像密钥的选项后面紧跟着 - 开头的参数时，当它是开关，不隐去下一个（--no-auth --port 80 保留 --port 80）；代价是本身以 - 开头的密钥值不会隐去。进程标签由隐去后的 argv 生成，悬停提示显示的也是它（codestrata/web/seq.js:174），所以按这套规则认得出的密钥不会出现在时序图上。标题不经过这一步，原样显示。编号分组用的仍是原始 argv（seq.py:433），所以两个进程只差在密钥值上时，标签看起来一样，却不会加编号（这一点是按代码推的，没跑过）。test_rerun_secrets_and_bytes 测了 `build` 返回的 procs 里不含 --api-key 的值，还直接调 `_redact_argv` 测了 --no-auth 后面的 --port 80 原样保留。
- 派生：窗口里有子进程起来、而且它的父进程也在图上时，在它的起始时刻插一行 spawn（seq.py:448）。

### overview：时间刷上的密度
把整个 run 分成 400 格，每个进程每格累加 Σrep（seq.py:473）。它不看切面、不分阶段，数的是全部跨文件调用（不画的那三类也算在内），所以按 (spans 目录, index 的 mtime, 格数) 缓存一次就够了（seq.py:462）。设计稿里写的是按 (run, phase) 缓存。它要把所有块扫一遍，所以读块时带 cache=False（seq.py:472），不经过那个 16 块的 LRU：块数超过 16 时，一次概览就会把正在看的那几块全挤出去。

### find：先在当前阶段里找
在切面上找 a → b 这条边在 after 之后第一次出现的时刻。块按时间窗和当前找到的最早结果剪枝；块内有序，一超出范围就停；被调方是 rel:0 的跳过。serve 把 run 引用里的阶段换算成一个窗口（serve.py:224），这里先在这个窗口里找（seq.py:507），找不到再搜整个 run。serve 的注释写了原因：这条边在 serving 里叠成了橙色，就应该跳到 serving 里的那一次，而不是启动时的第一次。前端拿到时刻后，从 t−1 起按自动模式取一屏（codestrata/web/app.js:571），再滚到那条消息。

## 局限
- 只取**在窗口里开始**的 span：窗口开始之前就已经开始、还没返回的调用不画。消息只是某个时刻的一根箭头；async span 没有激活条，dur 和挂起次数只在详情里给（设计稿 7.4 说的第一版就是这样）。
- 折叠行数不单调，在 `_grow` 里还剩一处影响（按代码推的，没有构造数据跑过）：它在中间某一轮放不下就停。比如周期 8 的片段重复 3 遍，整段 24 条折成 1 行，前 23 条却折不起来。估算那条路上，整段其实画得下的窗口也可能被判成 too_dense，不过给的建议窗口更短、能画出来，不会原地打转。
- 给定窗口、原始 span 不多的那个分支里，fold=False 的处理（seq.py:396 起）已经走不到了：fold=False 现在一律走 `_grow`。

## 不确定
- 设计稿 M5a 的验收标准是接口在 300 ms 内返回；记下来的冷启动是 450 ms，热的是 20 ms。这些都是在合成数据上测的，真 GPU 数据还没录（M5 的标题里写着）。
- 贪心每次选覆盖最多的周期，不保证整屏行数最少；`_fit` 的二分也不保证取到最长的前缀。真实数据上折得好不好，要等真的 vllm 录制出来才知道。
