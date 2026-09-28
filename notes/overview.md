---
written_by: claude-opus-5-5
target: _overview
kind: repo
code_sha: a7550a553d8778bc
status: draft
refs: __main__.py:81@d89a80ca,__main__.py:250@8ac31b40,__main__.py:243@e57ae09a,__main__.py:256@b87faf5c,runs.py:425@1c2edb45,runs.py:426@fe850b3d,payload.py:44@792c7b2a,payload.py:67@78863fea,payload.py:283@ef38d1f0,serve.py:123@9e187d68,serve.py:265@b723863d,serve.py:426@eae1c1a1,serve.py:154@cd0d48b0,serve.py:168@4317bbc0,seq.py:124@4430b676,codestrata/web/ds.js:60@454a9417,trace.py:831@6831bb9a,__main__.py:35@22ae2662,scan.py:112@e3529493,events.py:230@e0f60905,seq.py:85@43f9c39a
---

## 这个仓库做什么
codestrata 给一个 Python 仓库（论文代码、vLLM 这类开源框架）画**共用坐标**的图。模块图有两种底：总图来自静态分析（`ast`），hot 图是在它上面叠一个真实 case 跑起来时录下的 runtime 调用。M5 之后多了一张时序图：同一次录制里跨模块的调用按时间先后排开，生命线就是模块图上当前显示的那些节点。三者共用同一个切面（图上显示到目录树的哪一层）和同一份选中，在模块图上展开一个目录，时序图也跟着细到它下面的子模块。图下面接着就能读代码：点节点看文件树和源码，全文窗口里 Ctrl+点击跳到定义、列出引用，搜索栏按名字找模块 / 文件 / 函数。再留出一层给人或 LLM agent 写「为什么这样切、算法为什么这么写、该按什么顺序读」。

两种数据的份数不对称：静态分析只有一份（当前工作区的快照，scan 时整份替换）；runtime 可以有很多份。每次 trace 都存成一个新的 **run**，同名 case 重录也不覆盖：今天录 MiniCPM、明天录 Qwen，两份都留着，录一次就能反复叠到图上，网页上随时在静态图和各个 run 之间切换，不用重启。这样做是因为 run 重建不了，一次录制往往要几分钟 GPU（`docs/design/runs.md` 第 1 节）。留着多份，最直接的用处是比：M7 起可以再挑一个 run（B）和当前叠着的（A）放在同一张模块图上，只有 A 跑到的画橙色、只有 B 跑到的画紫色、两边都跑到的画前景色，节点上写「A/B」两个次数。比如 MiniCPM@serving 对比 Qwen@serving，一眼看出两个模型各走了哪些代码。对比只有两路，而且只在模块图上，时序图仍只画 A。

录的时候还可以顺带记**时序事件**（trace --events）：每一次跨文件调用在什么时刻开始、什么时刻返回、中间挂起过几次。收尾时整理成 span 存进 run，时序图每次打开时再按当前切面现画。

输入是一个仓库目录，加上可选的 case 命令。产出分三类：`.codestrata/` 下可重建的事实（index / symbols / xref），`.codestrata/runs/` 下**不能重建**的录制（原始数据永久保留，计数和 span 是从它们派生、能重算的），仓库 `notes/` 下**不能重建**的解读。此外还有一个本地网页（serve）或一个单文件 HTML（graph）。单文件可以带上几个 run、在它们之间切换，也可以带上导出时定好的一对对比；时序图只在 serve 里有，导出的单文件不带。

## 主干
一次典型使用里，数据这样流过各模块：
1. `scan` 读全仓 .py，写出 index.json（文件级的模块、边、高度、目录树、默认切面）和 symbols.json（符号、边上的引用明细、每个文件的内容哈希）。默认切面就是图上默认显示哪一层，由 `cut` 按规模算出。同一条命令紧接着用同一份 index 调 `xref.build`，写出 xref.json（每个名字指向哪个定义）。这一步由 `cmd_scan` 串起来（__main__.py:81），不放进 `scan`：放在同一条命令里，两份产物才是同一时刻的快照、行号对得上；放在 `scan` 外面，`scan` 就只产出总图事实。
2. （可选）录一次 case，由 `cmd_trace` 缝起来。`runs.new_run` 先建 .codestrata/runs/<id>/（id = 录制时刻 + case 名），`trace.run` 再在 hook 下跑命令：每个 Python 进程（包括子进程和 setsid 出去的服务）往 run 的 parts/ 写分片；停的时候按 SIGINT → SIGTERM → SIGKILL 分三级，再清掉残留进程，最后 `trace.merge` 合并。录不录时序事件只看一个环境变量：CLI 每次都把 CODESTRATA_EVENTS 明确写给命令，--events 时是 1、否则是 0（__main__.py:250）。写 0 是为了 shell 里 export 过的值不会悄悄生效，否则录出来的 run 和它的重录命令对不上。行数上限 CODESTRATA_EV_MAX 的处理正相反：不盖 shell 的值，而是在 `runs.new_run` 写出 run.json **之前**把它抄进 run 的 env（__main__.py:243），run.json 里记着、重录命令里也带着同一个上限（test_events_cap 有从 shell 继承的用例）。hook 看到 1，就给每个有跨文件调用的进程映像另写一份 ev-<pid>-<t0ns>.log，也落在 parts/。收尾经 `after` 回调交给 `runs.finalize`（__main__.py:256）：先存下 case 脚本和配置文件的副本、记下环境和 git，再打包原始数据（分片进 parts.tar.gz，事件日志单独进 events/raw.tar.gz，runs.py:425），然后由 `events.build` 把事件日志配成 span、写进 events/spans/（runs.py:426），最后算出各阶段的计数，定出状态 ok / partial / failed。事后用 runs 子命令（`cmd_runs`）列出、查看、打标签、重算、删除，runs rm --events-only 只删时序事件。
3. `payload` 把这些拼成模块图要的数据。先由 `cut` 把文件级的数据汇总到当前切面的节点上，并给出每个节点直接被哪个展开着的目录套着（展开的目录在图上画成框，前端每次展开 / 收起都会带着新的切面再要一次），再交给 `layout` 算节点和框的坐标。一个 run 的引用（完整 run id 或 case 名，可加 @阶段）由 `runs.resolve` 解析成某一次 run，`runs.load` 用 `trace.to_package_graph` 按**当前** index 现算叠加，并标出录制之后改过的文件（改过的文件先由 `runs.remap` 按录制时记下的函数名把次数挪到函数现在的行号上，M6）；`payload.load_hot` 只是转调它（payload.py:44）。叠加按切面汇总的那一步抽成了 `_hot_on_cut`（payload.py:67）：对比时 A、B 各调一次，`graph_payload` 在返回里多一个 cmp 块（节点、边上各带 [A, B] 两个次数），只在 runtime 出现的边和「只看跑到的」都取两边的并集。源码交给 `highlight`，解读从 `notes` 取；点开一条边时，由 `edge_detail` 把静态引用和 runtime 调用交叉成五类，对比时换成 `edge_compare`（payload.py:283）：两个 run 各算一遍 `edge_detail` 再按符号合，每项多一个 B 的次数，只有 B 调到的符号单独成一组。读代码用的三样也在这里：`search_index`（搜索栏一次拿全的名字索引）、`reveal`（让某个模块在**当前**切面上露出来要展开哪些目录）、`xref_for` / `refs`（Ctrl+点击的链接和引用列表）。
4. 交付二选一：`serve` 按请求提供 /api/* 和前端静态文件。叠哪个 run 随请求带着（run=），`Handler._hot`（serve.py:123）解析后按 (run id, 阶段, 计数文件和 run.json 的修改时间) 缓存最近 8 个：计数只在 runs merge 时变；run.json 进键是后补的，因为叠加带着的 tags / 备注在它里面，改了要跟着换。对比的 B 在图和边详情两种请求里随 cmp= 带着，也由 `Handler._hot` 解析，只是换一个参数名（serve.py:265），缓存、失效规则都和 A 一样。B 找不到、或者和 A 是同一个 run 的同一个阶段时，不让请求失败，只叠 A、在返回里说明原因：A 是这张图的内容，B 只是附加的一层，地址里留着一个删掉的 B 不该让整页出不来。--hot 只决定页面打开时先选哪个，启动时仍先加载一遍（serve.py:426），写错了当场报出来。`render` 把同一套前端和 `export_payload` 给的整份数据（固定为默认切面，控制在体积预算内）内联成一个 HTML。导出时可以给几个 --hot（`cmd_graph`）：第一个是主 run，全量嵌入；其余的只带它们在导出切面上的节点、边次数和简要的 meta（EMB.hotBy），页面上能切过去，但边详情里的调用明细只有主 run 的；加 --compare 时前两个另嵌一份对比。别的 run 不全量嵌是为了体积：整个 HTML 要装进 16 MB，`export_payload` 先算图、边详情、源码片段，剩下的额度才给全文，每多嵌一份完整的 run，能带上全文的文件就少一截。
5. 时序图（M5，只在 serve 里）接在第 2 步写下的 events/spans/ 后面：keys.json（「文件:首行号」键表）、index.json（每块的进程和时间范围）、按进程、按开始时刻分好块的 p<pid>-NNN.jsonl.gz。页面发来的 /api/seq、/api/seq/overview、/api/seq/find 都进 `Handler._seq`（serve.py:154）：它用 `runs.resolve` 找到 run 的目录，切面先过 `payload._norm_open`（serve.py:168），和模块图走的是同一道，两张图的节点才对得上；参数解析好后交给 `seq`。`seq.build` 只读和时间窗重叠的块，把每个 span 两端的「文件:首行号」经 rel → 单元 → 当前切面的节点（`cut.view`，seq.py:124）映射成生命线 (进程, 节点) 之间的消息。两端落在同一节点的、import 触发的模块顶层执行、落在 index 之外的都不画，只计数。画不下时才把重复的片段折成 loop 行，没给窗口时从当前阶段的起点自动收窄到一屏（默认 300 行）。`seq.overview` 给时间刷算每个进程的调用密度；`seq.find` 给模块图抽屉里的「在时序图里看」找一条边第一次被调用的时刻，先在 run 选的阶段里找。最后 `codestrata/web/seq.js` 只管画，并把点击翻译成新的请求。

events/spans/ 只有 `seq` 读（经 serve），`payload` 不读它。导出版也不带：`export_payload` 不算时序，导出版的数据源对时序图请求直接报错（codestrata/web/ds.js:60）。

`__main__` 大体只做分派，自己串的只有两段：scan 之后接着建交叉引用；trace 时把 `runs` 和 `trace` 缝在一起（--events 也只是在这里定一个环境变量，再记进 run 的录制参数，重录命令据此带上它）。`cmd_runs` 里放的是参数校验、删除前确认这类 CLI 的事，run 的规则都在 `runs` 里；`cmd_graph` 同理，只查 --hot 有没有空值（脚本里的变量没设）、去掉写了两遍的、--compare 有没有第二个 run，嵌哪些、怎么嵌都在 `export_payload` 里。时序图这一路是 `serve` 在缝：它经 `runs` 找 run、再把目录交给 `seq`，`seq` 自己不认识 `runs`。

## 为什么分成这几层
依据是真实的 import 图：默认切面上 14 个节点、25 条依赖，空的包初始化文件不画。高度是 `(出 − 入) / (出 + 入)`：
- **入口**（+1）：`__main__`，一层薄 CLI，出边 9 条。
- **中间**（+0.67 / +0.5）：`serve` 和 `payload`。`payload` 是模块图的汇合点，唯一同时认识事实、runtime、坐标、源码、交叉引用、解读的模块，依赖 `cut`、`highlight`、`layout`、`notes`、`runs`、`xref`；它不直接读 `trace` 的产物，runtime 一律经 `runs` 取。两个 run 的对比也算在这里（M7 没有新增模块，也没有新增依赖）。`serve` 管 HTTP 协议、安全边界和进程内缓存，出边 5 条（`cut`、`notes`、`payload`、`runs`、`seq`）。M4（不重启切换 run）之后它直接依赖 `runs`：下拉列表要 `runs.catalog`，每个请求要 `runs.resolve` 和 `runs.load`；M5 又加了 `seq`，所以比 `payload` 更高。
- **中间偏下**：`scan`（0）、`seq`（0）、`runs`（−0.2）、`notes`（−0.5）。`scan`、`seq`、`notes` 各有一条出边，都指向 `cut`：问目录树怎么切。`seq` 要的是某个文件落在切面的哪个节点上，以及节点的架构高度（同一进程的生命线按高度从左往右排，和模块图从上到下一致）。`seq` 只被 `serve` 用。`runs` 依赖 `trace`（合并分片、折算叠加）和 `events`（整理 span），被 `payload`、`serve`、`__main__` 使用。
- **叶子**（−1）：`cut`、`trace`、`events`、`layout`、`highlight`、`render`、`xref`，每个只做一件事，彼此不 import。「叶子」的意思是被依赖、不依赖别人，不是「不重要」：数据的生产者 `trace`、`events`、`xref`，决定图上显示哪一层的 `cut` 都在这一层。`cut` 被 6 个模块依赖，全仓最多。`xref` 是全仓最大的模块（近 1400 行），它只吃 scan 给的 index 这个 dict，不 import `scan`，所以也是叶子；`events` 同理，只吃一串日志文件、run 的起点时刻和一个输出目录，不 import `trace` 也不 import `runs`。

最值得注意的几条边界：
- **录 vs 存。** `trace` 不 import `runs`，所以仍是叶子。`trace.run` 只接收一个 parts 目录和一个 `after` 回调，不知道 run.json 长什么样。之所以用回调，而不是返回之后再收尾，是因为 driver 的信号处理器要一直装到收尾做完：`after` 在 `run` 的 try 里面调用（trace.py:831），打包中途按 Ctrl+C 才不会留下半截的 run。反过来，写 run、删 run 的代码全在 `runs` 里（`events` 只往 `runs` 交给它的 events/spans/ 里写派生的 span）：除了 `runs.remove` 和 `runs.remove_events`，没有代码会删 run 里的原始数据，审这一个文件就能确认。`seq` 只读不写。
- **可重建 vs 不可重建。** 以前整个 `.codestrata/` 都是缓存；M1 之后分成两半，index / symbols / xref 随时删了重建，runs/ 删了就没了。误删有几道防线：`_outdir` 往 .codestrata/ 里写一份 README.txt（`_README`，__main__.py:35），写明除 runs/ 以外都能删；runs/ 可以是指到别的盘的软链，rm -rf .codestrata 只删链接本身；scan 跳过以点开头的目录（scan.py:112），不碰 runs/。解读放在 notes/，进版本库，靠 `code_sha`（整份是否过期）和引用指纹（哪一处 file:line 漂了）和代码绑在一起。
- **原始 vs 派生**（run 内部）。合并逻辑还不成熟，以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，runs merge 能重算。时序事件照同一个办法：原始日志（events/raw.tar.gz）永久保留，span 是派生的。收尾时先落包、再整理（runs.py:425 在 runs.py:426 之前），整理抛了异常只在 run.json 的 events 摘要里记一个 error；事件到了行数上限也只标 truncated。两种情况都不改 status，因为计数是完整的，拿 case 名解析时不该因此跳到更早的一次。录制时才拿得到的东西（执行时的文件哈希、脚本和配置的副本、GPU、git 改动）只写一次，重算时不拿「现在的样子」去盖。
- **录制时只记 → 收尾时整理一次 → 看的时候现算**（时序事件分三段）。hook 跑在被 trace 的程序里，每次跨文件调用都要付它的开销，所以它只做最少的事：调用时给一个 span 号，返回、挂起、恢复时按帧找回同一个号写出去。配对、深度、父子关系、第一级折叠都放在 `events` 里事后做（落盘被打断时 hook 只保证不丢，重试写重的行也由 `events.pair` 跳过），算法改了不用重录，runs merge 从原始日志重建即可（`events.build` 的输出是确定的，重建结果和收尾时一样）。按 span 号而不是按栈配对，是因为同一线程上交错执行的 asyncio 协程，先开始的不一定先结束。这一段的产出和切面无关，所以只做一次、写盘。映射到节点、画不画、折不折循环都和切面有关（展开一个包，同一个 span 可能从「节点内部」变成一条消息），所以放在 `seq` 里每次请求现算、不写盘，只在内存里缓存和切面无关的解压块、概览，以及 (index, 切面) → 映射表。
- **`seq` 和 `events` 之间只隔一个文件格式。** `seq` 不 import `events` 也不 import `runs`：run 的目录、run.json、detail.json 都由 `serve` 经 `runs.resolve` 找好交给它，span 直接从 spans/ 的文件读。这样 `events` 仍是叶子，`seq` 也只依赖 `cut`，测试能直接调 `seq.build`、不用起 HTTP。代价是 spans/ 的格式两边各认一份：`events.read_spans`（events.py:230）一次读回全部块，现在只有测试在用；`seq` 另写了按时间窗挑块、解压过的块进 LRU 的 `spans_in`（seq.py:85）。格式要改时两边都得跟着改，兜底的是 test_seq_* 用真录出来的 span 跑（test_seq_build 还核对「画出的消息 + 三类不画的」次数等于全部 span 的次数）。
- **数据 vs 呈现。** `payload` 和 `seq` 都不知道 HTTP 和 HTML；`serve` 只解析参数、把阶段换算成时间窗。模块图这边，`serve` 和 `render` 共用同一个 `payload`，所以 live 模式和导出版不会各长各的。对比也守这一条：[A, B] 两个次数、边详情里 B 的次数都由 `payload` 算好，serve 和导出版拿到的是同一份，前端只管选 B、上色、写数字。对比时不重新排版，节点还在原来的位置上，眼睛只需要看颜色；「只看跑到的」那张单独排版的图放两边任一跑到的节点。搜索放在前端做、名字索引一次给全，也是为了这一条：导出版没有服务端，照样能搜。时序图是例外：它只在 serve 里有，导出版不嵌时序事件（设计稿第 8 节）。
- **记录的粒度 vs 显示的层级。** `scan` 只记最细的一层（每个文件一个模块），图上显示哪一层由 `cut` 在目录树上取切面决定。所以展开 / 收起不用重扫，解读的过期判定、run 的叠加和时序事件（键是「文件:首行号」）也都和图上怎么切无关。时序图的生命线同样是现映射出来的，所以在时序图的目录生命线上点 ＋，和在模块图上展开是同一个动作，两张图一起细到子模块。展开的目录画成框，但纵轴仍是架构高度，框只能在横向上占一段列（见 `layout` 的解读），不能为了把子模块归到一起让纵轴说谎。
- **快照 vs 现在的文件。** 事实都是某一刻的快照，源码却随时在改，所以每份快照都自带指纹，对不上时宁可少给、不给错。xref 记下每个文件的大小和修改时间，scan 之后改过的文件不给 Ctrl+点击（`payload._stale`）。run 只存原始键（文件:首行号）和 hook 在执行时取的文件哈希，加载时现映射到当前 index；`runs.file_state` 拿哈希和 index 的 `file_sha` 比，不和工作区比，因为叠加用的行号来自 index。它逐个标出改过、删掉、不在 index 里的文件，而不是让整个 run 作废。改过的文件也不只是标一句「可能偏」：hook 录制时还给每个键记了函数的 qualname，加载时 `runs.remap` 按名字把次数挪到函数现在的行号上（M6），对不上名字的只算到文件上、不算到任何函数上，横幅上报个数。行号是会随编辑变的位置，名字是只有录制时才拿得到的身份，两样都存，读的一侧才有退路。解读有 `code_sha` 和引用指纹。时序图是这一条里最弱的一环，见「局限」。

图上看不到的一块是前端，在 `codestrata/web/`（七个 JS 文件，零构建），不是 Python，所以不在图里。整页是一个应用：上面一条标题和开关，图铺满其余空间，搜索栏（右上）和详情栏（下沿）半透明地浮在图上，全文窗口负责 Ctrl+点击。工具栏的「运行」在静态图和录下的各个 run（及其阶段）之间切换，选中的 run 以完整 id 写进地址栏的 #run=，刷新后还是同一次录制；serve 开着时新录的 run，回到页面就在按钮上加个点，不自动切过去。叠了 run 时，统计那一行多一个 hot 标记，点开「?」写明用的是哪个 run，录得不完整时列出原因；工具栏还多一组「模块图 | 时序图」，这个 run 没录事件时「时序图」是灰的；列表里不止一个 run 时还有「对比」，选中的 B 同样以完整 id 写进地址栏的 cmp=。B 的阶段跟着 A 走：A 看某个阶段、B 也有同名阶段就比它，没有就比 B 的全部，否则比出来的差别大半是阶段不同造成的。对比时帮助里多一条横幅说明 A、B 各是哪次录制，边的开关那一行换成三色图例；两个 run 一个录了时序事件、一个没录时提醒一句次数不完全可比（录事件本身有开销）。导出版里「运行」只列导出时带上的那几个，对比是 --compare 定好的，只显示、不能换。两张图共用一个图框、同一时刻只显示一张，时序图不另存状态：切面借模块图的 open，选中借模块图的 sel / selEdge。点生命线头就是选中这个模块，点一条消息就是选中这条边，抽屉、搜索、地址栏（多一个 view=seq）都不用知道有第二张图。结构见 render 的解读。

## 阅读顺序
1. **scan**：先弄清「事实」是什么。读完能回答：图上每个框、每个箭头、每条虚线从哪来。
2. **cut**：文件级的事实怎么变成图上的节点。读完能回答：为什么默认拆开的是这几个目录，点「＋」时发生了什么，一个节点被哪个框套着。
3. **layout**：节点和框怎么变成坐标。读完能回答：为什么这个节点在这条泳道、这个位置，为什么展开一个无关的目录时别的框不会换位置。
4. **payload**，重点看 `edge_detail`：点开一个箭头看到的每一项从哪来；再看 `edge_compare` 和 cmp 块，对比时每个数是哪个 run 的。顺带看搜索索引和交叉引用的缓存。
5. **serve**，以及 render 解读里的前端结构：数据怎么送进浏览器，换 run 时哪些请求带上它、缓存怎么失效，对比的 run 出问题时为什么只叠 A，搜索和「露出某个模块」怎么走，导出版少了什么、多带的几个 run 能切到什么程度。
6. **trace**：runtime 那一半的录制，也是最难的一块（多进程、exec、调用栈、落盘串行、三级停和残留进程，以及时序事件的记录）。读完能回答：橙色是怎么来的，可信到什么程度，哪些情况下会丢数据。行为对照 `tests/test_runs.py` 看，它在 CPU 假服务上跑。
7. **runs**，配合 `__main__` 的 `cmd_trace` 和 `cmd_runs`：录下的东西怎么存、怎么再叠回图上。读完能回答：一个 run 里哪些是原始数据、哪些能重算；--hot 某个case名 解析到哪一次录制；代码改了以后哪些文件上的叠加要按函数名挪（`runs.remap`）、挪不动的算到哪里；老的 trace-<case>.json 怎么迁进来。
8. **events**：时序事件从原始日志到 span，对着 `tests/trace_cases/fake_repo/fakesvc/truth.py` 的场景读。读完能回答：一次跨文件调用在时序数据里是哪一行，交错执行的协程为什么配得对，rep 合并的是什么、为什么按 (父 span, 段) 认兄弟。
9. **seq**，配合 `serve` 的 `Handler._seq` 和 render 解读里「两张图共用一个图框」「时序图的画法」两节：span 怎么变成当前切面上的一屏时序图。读完能回答：一条 span 为什么没画成消息（节点内部 / import / index 之外），切面一变同一段时间的图为什么跟着变，一屏为什么停在那里（300 行、同一微秒不拆到两屏、too_dense 和建议窗口），loop 行是怎么折出来的，「在时序图里看」跳到的是哪一次。对照 test_seq_* 读。
10. **xref**：Ctrl+点击背后的静态解析，包括再导出、作用域、C3 MRO。量最大，但和图本身无关，跳过它不影响读懂图。读完能回答：一个名字为什么能跳或不能跳，「同名的 .xxx」那一组是什么。
11. **notes**：解读层自己怎么运作，包括过期、派活顺序、机器核对。
12. **highlight** 和 `__main__` 的其余部分，需要时再看。

## 局限
- `docs/design/runs.md` 的 M1–M7 都做完了（M2 随 M1 一起），但都是在 CPU 数据上验收的：CPU 假服务、codestrata 自己的 case，M5 另加合成的 vllm 规模数据（44 万次调用、5 个进程、180 s）。要用 GPU 录的几件都还在等用户同意：M1 的 GPU 终验（录一次真的 minicpmo，第一个字段齐全的 run）、M3 的事件开销实测（所以现在默认不录，要加 --events）、M5 在真 vllm 录制上的表现、M7 的 MiniCPM@serving 对比 Qwen@serving（Qwen 还没录）。被 trace 的解释器还得是 3.12+ 才录得到事件（要 `sys.monitoring`）。
- 自动测试只覆盖服务端：test_seq_* 直接调 `seq`，其中 test_seq_find_and_api 走真的 serve；test_remap_moved_functions 测按函数名挪行号；test_compare_and_multi_export 直接调 `graph_payload` 和 `edge_compare` 核对 [A, B] 次数，跑一遍多 run 导出，再经真的 serve 核对对比的 run 找不到、就是 A 自己时只叠 A。前端没有自动测试：M4 的换 run 靠设计稿里记的浏览器验收，M5 的视图切换、两张图之间的选中和切面同步，M7 的对比按钮、三种颜色、地址里的 cmp=、导出版里切换 run，也一样没有测试（M7 的配色是在 codestrata 自己的两次录制上，按明暗两种主题人工核对的）。
- M6 只改了模块图的叠加，时序图没跟着改：录制之后挪过行的函数，时序图里消息落在哪两条生命线上不受影响（那只看文件），但名字仍按旧行号现查（`seq` 不调 `runs.remap`）：旧行号正好是别的函数的首行，就显示成那个函数；否则显示成包住那一行的外层符号「外层名.<L行号>」。时序图自己也不标哪些文件在录制之后改过（`seq` 不看文件哈希），只能靠统计那一行的 hot 标记和运行列表里的提示。
- 对比只有两路（设计稿第 10 节：不做 N 路对比），只在模块图上；时序图、引用列表、输入包都只看 A。
- 导出版（graph）是固定切面，没有时序图。带了几个 run 时能在它们之间切，但只有第一个（主 run）带着边详情里的调用明细，切到别的 run 时边详情只剩静态引用；对比是导出时 --compare 定好的前两个，页面上不能换。serve 的 index 只在启动时读一次，重新 scan 之后图、搜索栏和时序图的映射都要重启才更新（xref 按修改时间自动换新，所以这时 Ctrl+点击已经是新的）；index 落后于代码时只在启动横幅里提示一句，serve 开着时再改就没有提示。新录的 run 则不用重启。

## 不确定
- 设计稿 M5a 的验收是接口在 300 ms 内返回；记下的冷启动是 450 ms、热的 20 ms，都是在合成数据上测的。真 GPU 数据上自动收窄够不够快、贪心折叠折得好不好，要等真的 vllm 录制出来才知道（细节见 seq 的解读）。
- 事件开销没实测，所以还不知道 --events 能不能默认打开（设计稿 M3 的「开销实测」和第 11 节）。
- 三种颜色在两个真模型的 run 上够不够用还不知道：MiniCPM 和 Qwen 共用 vllm 的主干，图上可能大片是前景色、差别只落在少数几个节点上，这时颜色只说明「两边都跑到」，次数差多少要看节点上的「A/B」和边详情。要等 Qwen 录好，按设计稿 M7 的验收实际比一次。
