---
written_by: claude-opus-5-5
target: _overview
kind: repo
code_sha: 00e51feb70a17255
status: draft
refs: __main__.py:80@d89a80ca,__main__.py:227@8ac31b40,__main__.py:233@b87faf5c,runs.py:425@1c2edb45,runs.py:426@fe850b3d,payload.py:44@792c7b2a,serve.py:116@fed8d85f,serve.py:355@eae1c1a1,trace.py:829@6831bb9a,__main__.py:34@22ae2662,scan.py:112@e3529493
---

## 这个仓库做什么
codestrata 给一个 Python 仓库（论文代码、vLLM 这类开源框架）画两张**共用坐标**的图：总图来自静态分析（`ast`），hot 图来自跑一个真实 case 时录下的 runtime 调用。图下面接着就能读代码：点节点看文件树和源码，全文窗口里 Ctrl+点击跳到定义、列出引用，搜索栏按名字找模块 / 文件 / 函数。再留出一层给人或 LLM agent 写「为什么这样切、算法为什么这么写、该按什么顺序读」。

两种数据的份数不对称：静态分析只有一份（当前工作区的快照，scan 时整份替换）；runtime 可以有很多份。每次 `trace` 都存成一个新的 **run**，同名 case 重录也不覆盖：今天录 MiniCPM、明天录 Qwen，两份都留着，录一次就能反复叠到图上，网页上随时在静态图和各个 run 之间切换，不用重启。这样做是因为 run 重建不了，一次录制往往要几分钟 GPU（`docs/design/runs.md` 第 1 节）。

录的时候还可以顺带记**时序事件**（`trace --events`）：每一次跨文件调用在什么时刻开始、什么时刻返回、中间挂起过几次。这是下一步时序图（M5）的数据，现在只录、只整理成 span，还没有页面去画。

输入是一个仓库目录，加上可选的 case 命令。产出分三类：`.codestrata/` 下可重建的事实（index / symbols / xref），`.codestrata/runs/` 下**不能重建**的录制（原始数据永久保留，计数和 span 是从它们派生、能重算的），仓库 `notes/` 下**不能重建**的解读。此外还有一个本地网页（`serve`）或一个单文件 HTML（`graph`）。

## 主干
一次典型使用里，数据这样流过各模块：
1. `scan` 读全仓 `.py`，写出 `index.json`（文件级的模块、边、高度、目录树、默认切面）和 `symbols.json`（符号、边上的引用明细、每个文件的内容哈希）。默认切面就是图上默认显示哪一层，由 `cut` 按规模算出。同一条命令紧接着用同一份 index 调 `xref.build`，写出 `xref.json`（每个名字指向哪个定义）。这一步由 `cmd_scan` 串起来（__main__.py:80），不放进 `scan`：放在同一条命令里，两份产物才是同一时刻的快照、行号对得上；放在 `scan` 外面，`scan` 就只产出总图事实。
2. （可选）录一次 case，由 `cmd_trace` 缝起来。`runs.new_run` 先建 .codestrata/runs/<id>/（id = 录制时刻 + case 名），`trace.run` 再在 hook 下跑命令：每个 Python 进程（包括子进程和 setsid 出去的服务）往 run 的 parts/ 写分片；停的时候按 SIGINT → SIGTERM → SIGKILL 分三级，再清掉残留进程，最后 `trace.merge` 合并。录不录时序事件只看一个环境变量：CLI 每次都把 `CODESTRATA_EVENTS` 明确写给命令，`--events` 时是 1、否则是 0（__main__.py:227）。写 0 是为了 shell 里 export 过的值不会悄悄生效，否则录出来的 run 和它的重录命令对不上。行数上限 `CODESTRATA_EV_MAX` 的处理正相反：不盖 shell 的值，而是想把它抄进 run 的 env，让重录命令复现同一个上限（后补的，但眼下没真记下，见「局限」）。hook 看到 1，就给每个有跨文件调用的进程映像另写一份 ev-<pid>-<t0ns>.log，也落在 parts/。收尾经 `after` 回调交给 `runs.finalize`（__main__.py:233）：先存下 case 脚本和配置文件的副本、记下环境和 git，再打包原始数据（分片进 parts.tar.gz，事件日志单独进 events/raw.tar.gz，runs.py:425），然后由 `events.build` 把事件日志配成 span、写进 events/spans/（runs.py:426），最后算出各阶段的计数，定出状态 ok / partial / failed。事后用 `runs` 子命令（`cmd_runs`）列出、查看、打标签、重算、删除，`runs rm --events-only` 只删时序事件。
3. `payload` 把这些拼成前端要的数据。先由 `cut` 把文件级的数据汇总到当前切面的节点上，并给出每个节点直接被哪个展开着的目录套着（展开的目录在图上画成框，前端每次展开 / 收起都会带着新的切面再要一次），再交给 `layout` 算节点和框的坐标。一个 run 的引用（完整 run id 或 case 名，可加 `@阶段`）由 `runs.resolve` 解析成某一次 run，`runs.load` 用 `trace.to_package_graph` 按**当前** index 现算叠加，并标出录制之后改过的文件；`payload.load_hot` 只是转调它（payload.py:44）。源码交给 `highlight`，解读从 `notes` 取；点开一条边时，由 `edge_detail` 把静态引用和 runtime 调用交叉成五类。读代码用的三样也在这里：`search_index`（搜索栏一次拿全的名字索引）、`reveal`（让某个模块在**当前**切面上露出来要展开哪些目录）、`xref_for` / `refs`（Ctrl+点击的链接和引用列表）。
4. 交付二选一：`serve` 按请求提供 `/api/*` 和前端静态文件。叠哪个 run 随请求带着（`run=`），`Handler._hot`（serve.py:116）解析后按 (run id, 阶段, 计数文件和 run.json 的修改时间) 缓存最近 8 个：计数只在 `runs merge` 时变；run.json 进键是后补的，因为叠加带着的 tags / 备注在它里面，改了要跟着换。`--hot` 只决定页面打开时先选哪个，启动时仍先加载一遍（serve.py:355），写错了当场报出来。`render` 把同一套前端和 `export_payload` 给的整份数据（固定为默认切面、只带一个 run，控制在体积预算内）内联成一个 HTML。

events/spans/ 目前没有读者：`payload` 和 `serve` 都还不读它，要等 M5 的时序图。

`__main__` 大体只做分派，自己串的只有两段：scan 之后接着建交叉引用；trace 时把 `runs` 和 `trace` 缝在一起（`--events` 也只是在这里定一个环境变量，再记进 run 的录制参数，重录命令据此带上它）。`cmd_runs` 里放的是参数校验、删除前确认这类 CLI 的事，run 的规则都在 `runs` 里。

## 为什么分成这几层
依据是真实的 import 图：默认切面上 13 个节点、23 条依赖，空的包初始化文件不画。高度是 `(出 − 入) / (出 + 入)`：
- **入口**（+1）：`__main__`，一层薄 CLI，出边 9 条。
- **中间**（+0.6 / +0.5）：`serve` 和 `payload`。`payload` 是汇合点，唯一同时认识事实、runtime、坐标、源码、交叉引用、解读的模块，依赖 `cut`、`highlight`、`layout`、`notes`、`runs`、`xref`；它不直接读 `trace` 的产物，runtime 一律经 `runs` 取。`serve` 管 HTTP 协议、安全边界和进程内缓存。M4（不重启切换 run）之后它直接依赖 `runs`：下拉列表要 `runs.catalog`，每个请求要 `runs.resolve` 和 `runs.load`，所以比 `payload` 还高一点。
- **中间偏下**：`scan`（0）、`runs`（−0.2）、`notes`（−0.5）。`scan` 和 `notes` 各有一条出边，都是问 `cut` 目录树怎么切。`runs` 依赖 `trace`（合并分片、折算叠加）和 `events`（整理 span），被 `payload`、`serve`、`__main__` 使用。
- **叶子**（−1）：`cut`、`trace`、`events`、`layout`、`highlight`、`render`、`xref`，每个只做一件事，彼此不 import。「叶子」的意思是被依赖、不依赖别人，不是「不重要」：数据的生产者 `trace`、`events`、`xref`，决定图上显示哪一层的 `cut` 都在这一层。`xref` 是全仓最大的模块（近 1400 行），它只吃 scan 给的 index 这个 dict，不 import `scan`，所以也是叶子；`events` 同理，只吃一串日志文件、run 的起点时刻和一个输出目录，不 import `trace` 也不 import `runs`。

最值得注意的几条边界：
- **录 vs 存。** `trace` 不 import `runs`，所以仍是叶子。`trace.run` 只接收一个 parts 目录和一个 `after` 回调，不知道 run.json 长什么样。之所以用回调，而不是返回之后再收尾，是因为 driver 的信号处理器要一直装到收尾做完：`after` 在 `run` 的 try 里面调用（trace.py:829），打包中途按 Ctrl+C 才不会留下半截的 run。反过来，写 run、删 run 的代码全在 `runs` 里（`events` 只往 `runs` 交给它的 events/spans/ 里写派生的 span）：除了 `runs.remove` 和 `runs.remove_events`，没有代码会删 run 里的原始数据，审这一个文件就能确认。
- **可重建 vs 不可重建。** 以前整个 `.codestrata/` 都是缓存；M1 之后分成两半，index / symbols / xref 随时删了重建，runs/ 删了就没了。误删有几道防线：`_outdir` 往 .codestrata/ 里写一份 README.txt（`_README`，__main__.py:34），写明除 runs/ 以外都能删；runs/ 可以是指到别的盘的软链，`rm -rf .codestrata` 只删链接本身；scan 跳过以点开头的目录（scan.py:112），不碰 runs/。解读放在 notes/，进版本库，靠 `code_sha`（整份是否过期）和引用指纹（哪一处 `file:line` 漂了）和代码绑在一起。
- **原始 vs 派生**（run 内部）。合并逻辑还不成熟，以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，`runs merge` 能重算。时序事件照同一个办法：原始日志（events/raw.tar.gz）永久保留，span 是派生的。收尾时先落包、再整理（runs.py:425 在 runs.py:426 之前），整理抛了异常只在 run.json 的 events 摘要里记一个 error；事件到了行数上限也只标 truncated。两种情况都不改 status，因为计数是完整的，拿 case 名解析时不该因此跳到更早的一次。录制时才拿得到的东西（执行时的文件哈希、脚本和配置的副本、GPU、git 改动）只写一次，重算时不拿「现在的样子」去盖。
- **录制时只记 vs 事后整理**（时序事件）。hook 跑在被 trace 的程序里，每次跨文件调用都要付它的开销，所以它只做最少的事：调用时给一个 span 号，返回、挂起、恢复时按帧找回同一个号写出去。配对、深度、父子关系、第一级折叠都放在 `events` 里事后做（落盘被打断时 hook 只保证不丢，重试写重的行也由 `events.pair` 跳过），算法改了不用重录，`runs merge` 从原始日志重建即可（`events.build` 的输出是确定的，重建结果和收尾时一样）。按 span 号而不是按栈配对，是因为同一线程上交错执行的 asyncio 协程，先开始的不一定先结束。
- **数据 vs 呈现。** `payload` 及其以下不知道 HTTP 和 HTML；`serve` 和 `render` 共用同一个 `payload`，所以 live 模式和导出版不会各长各的。搜索放在前端做、名字索引一次给全，也是为了这一条：导出版没有服务端，照样能搜。
- **记录的粒度 vs 显示的层级。** `scan` 只记最细的一层（每个文件一个模块），图上显示哪一层由 `cut` 在目录树上取切面决定。所以展开 / 收起不用重扫，解读的过期判定、run 的叠加和时序事件（键是「文件:首行号」）也都和图上怎么切无关。展开的目录画成框，但纵轴仍是架构高度，框只能在横向上占一段列（见 `layout` 的解读），不能为了把子模块归到一起让纵轴说谎。
- **快照 vs 现在的文件。** 事实都是某一刻的快照，源码却随时在改，所以每份快照都自带指纹，对不上时宁可少给、不给错。xref 记下每个文件的大小和修改时间，scan 之后改过的文件不给 Ctrl+点击（`payload._stale`）。run 只存原始键（文件:首行号）和 hook 在执行时取的文件哈希，加载时现映射到当前 index；`runs.file_state` 拿哈希和 index 的 `file_sha` 比，不和工作区比，因为叠加用的行号来自 index。它逐个标出改过、删掉、不在 index 里的文件，而不是让整个 run 作废。解读有 `code_sha` 和引用指纹。

图上看不到的一块是前端，在 `codestrata/web/`（六个 JS 文件，零构建），不是 Python，所以不在图里。整页是一个应用：上面一条标题和开关，图铺满其余空间，搜索栏（右上）和详情栏（下沿）半透明地浮在图上，全文窗口负责 Ctrl+点击。工具栏的「运行」在静态图和录下的各个 run（及其阶段）之间切换，选中的 run 以完整 id 写进地址栏的 #run=，刷新后还是同一次录制；serve 开着时新录的 run，回到页面就在按钮上加个点，不自动切过去。叠了 run 时，统计那一行多一个 hot 标记，点开「?」写明用的是哪个 run，录得不完整时列出原因。结构见 render 的解读。

## 阅读顺序
1. **scan**：先弄清「事实」是什么。读完能回答：图上每个框、每个箭头、每条虚线从哪来。
2. **cut**：文件级的事实怎么变成图上的节点。读完能回答：为什么默认拆开的是这几个目录，点「＋」时发生了什么，一个节点被哪个框套着。
3. **layout**：节点和框怎么变成坐标。读完能回答：为什么这个节点在这条泳道、这个位置，为什么展开一个无关的目录时别的框不会换位置。
4. **payload**，重点看 `edge_detail`：点开一个箭头看到的每一项从哪来。顺带看搜索索引和交叉引用的缓存。
5. **serve**，以及 render 解读里的前端结构：数据怎么送进浏览器，换 run 时哪些请求带上它、缓存怎么失效，搜索和「露出某个模块」怎么走，导出版少了什么。
6. **trace**：runtime 那一半的录制，也是最难的一块（多进程、exec、调用栈、落盘串行、三级停和残留进程，以及时序事件的记录）。读完能回答：橙色是怎么来的，可信到什么程度，哪些情况下会丢数据。行为对照 `tests/test_runs.py` 看，它在 CPU 假服务上跑。
7. **runs**，配合 `__main__` 的 `cmd_trace` 和 `cmd_runs`：录下的东西怎么存、怎么再叠回图上。读完能回答：一个 run 里哪些是原始数据、哪些能重算；`--hot 某个case名` 解析到哪一次录制；代码改了以后哪些文件上的叠加不可信；老的 trace-<case>.json 怎么迁进来。
8. **events**：时序事件从原始日志到 span，对着 `tests/trace_cases/fake_repo/fakesvc/truth.py` 的场景读。读完能回答：一次跨文件调用在时序数据里是哪一行，交错执行的协程为什么配得对，rep 合并的是什么、为什么按 (父 span, 段) 认兄弟。M5 之前它只有测试在读，跳过不影响读懂现在的图。
9. **xref**：Ctrl+点击背后的静态解析，包括再导出、作用域、C3 MRO。量最大，但和图本身无关，跳过它不影响读懂图。读完能回答：一个名字为什么能跳或不能跳，「同名的 .xxx」那一组是什么。
10. **notes**：解读层自己怎么运作，包括过期、派活顺序、机器核对。
11. **highlight** 和 `__main__` 的其余部分，需要时再看。

## 局限
- `docs/design/runs.md` 的 M1–M4 做完了（M2 随 M1 一起）。M4 靠的是设计稿里记的浏览器验收，serve 换 run 的那部分没有自动测试。M3 只做完 CPU 部分：事件在 GPU 录制上的开销还没实测，所以默认不录，要加 `--events`；被 trace 的解释器还得是 3.12+（要 `sys.monitoring`），更老的录不到事件。从 shell 继承的 `CODESTRATA_EV_MAX` 是在 `runs.new_run` 写出 run.json 之后才抄进 env 的，所以只给了命令，run.json 和重录命令里都没有（见 `__main__` 的解读）；经 `--env` 给的不受影响。
- 时序图（M5）、qualname 回退（M6）、run 之间的对比和多 run 导出（M7）都还没有。`events.read_spans` 一次读回全部块，只够测试用，按时间窗读、缓存都要 M5 自己做。
- 导出版（`graph`）只带导出时叠的那一个 run，不能换。serve 的 index 只在启动时读一次，重新 scan 之后图和搜索栏要重启才更新（xref 按修改时间自动换新，所以这时 Ctrl+点击已经是新的）；index 落后于代码时只在启动横幅里提示一句，serve 开着时再改就没有提示。新录的 run 则不用重启。
