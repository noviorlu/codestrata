---
written_by: claude-opus-5-5
target: _overview
kind: repo
code_sha: 279b345d149311d4
status: draft
refs: __main__.py:80@d89a80ca,__main__.py:224@8f8c092f,payload.py:44@792c7b2a,trace.py:698@6831bb9a,__main__.py:34@22ae2662,scan.py:112@e3529493
---

## 这个仓库做什么
codestrata 给一个 Python 仓库（论文代码、vLLM 这类开源框架）画两张**共用坐标**的图：总图来自静态分析（`ast`），hot 图来自跑一个真实 case 时录下的 runtime 调用。图下面接着就能读代码：点节点看文件树和源码，全文窗口里 Ctrl+点击跳到定义、列出引用，搜索栏按名字找模块 / 文件 / 函数。再留出一层给人或 LLM agent 写「为什么这样切、算法为什么这么写、该按什么顺序读」。

两种数据的份数不对称：静态分析只有一份（当前工作区的快照，scan 时整份替换）；runtime 可以有很多份。每次 `trace` 都存成一个新的 **run**，同名 case 重录也不覆盖：今天录 MiniCPM、明天录 Qwen，两份都留着，录一次就能反复叠到图上。这样做是因为 run 重建不了，一次录制往往要几分钟 GPU（`docs/design/runs.md` 第 1 节）。

输入是一个仓库目录，加上可选的 case 命令。产出分三类：`.codestrata/` 下可重建的事实（index / symbols / xref），`.codestrata/runs/` 下**不能重建**的录制，仓库 `notes/` 下**不能重建**的解读。此外还有一个本地网页（`serve`）或一个单文件 HTML（`graph`）。

## 主干
一次典型使用里，数据这样流过各模块：
1. `scan` 读全仓 `.py`，写出 `index.json`（文件级的模块、边、高度、目录树、默认切面）和 `symbols.json`（符号、边上的引用明细、每个文件的内容哈希）。默认切面就是图上默认显示哪一层，由 `cut` 按规模算出。同一条命令紧接着用同一份 index 调 `xref.build`，写出 `xref.json`（每个名字指向哪个定义）。这一步由 `cmd_scan` 串起来（__main__.py:80），不放进 `scan`：放在同一条命令里，两份产物才是同一时刻的快照、行号对得上；放在 `scan` 外面，`scan` 就只产出总图事实。
2. （可选）录一次 case，由 `cmd_trace` 缝起来。`runs.new_run` 先建 .codestrata/runs/<id>/（id = 录制时刻 + case 名），`trace.run` 再在 hook 下跑命令：每个 Python 进程（包括子进程和 setsid 出去的服务）往 run 的 parts/ 写分片；停的时候按 SIGINT → SIGTERM → SIGKILL 分三级，再清掉残留进程，最后 `trace.merge` 合并。收尾经 `after` 回调交给 `runs.finalize`（__main__.py:224）：打包原始分片，存下 case 脚本和配置文件的副本，记下环境和 git，算出各阶段的计数，定出状态 ok / partial / failed。事后用 `runs` 子命令（`cmd_runs`）列出、查看、打标签、重算、删除。
3. `payload` 把这些拼成前端要的数据。先由 `cut` 把文件级的数据汇总到当前切面的节点上，并给出每个节点直接被哪个展开着的目录套着（展开的目录在图上画成框，前端每次展开 / 收起都会带着新的切面再要一次），再交给 `layout` 算节点和框的坐标。`--hot` 给的 REF（完整 run id 或 case 名，可加 `@阶段`）由 `runs.resolve` 解析成某一次 run，`runs.load` 用 `trace.to_package_graph` 按**当前** index 现算叠加，并标出录制之后改过的文件；`payload.load_hot` 只是转调它（payload.py:44）。源码交给 `highlight`，解读从 `notes` 取；点开一条边时，由 `edge_detail` 把静态引用和 runtime 调用交叉成五类。读代码用的三样也在这里：`search_index`（搜索栏一次拿全的名字索引）、`reveal`（让某个模块在**当前**切面上露出来要展开哪些目录）、`xref_for` / `refs`（Ctrl+点击的链接和引用列表）。
4. 交付二选一：`serve` 按请求提供 `/api/*` 和前端静态文件；`render` 把同一套前端和 `export_payload` 给的整份数据（固定为默认切面，控制在体积预算内）内联成一个 HTML。

`__main__` 大体只做分派，自己串的只有两段：scan 之后接着建交叉引用；trace 时把 `runs` 和 `trace` 缝在一起。`cmd_runs` 里放的是参数校验、删除前确认这类 CLI 的事，run 的规则都在 `runs` 里。

## 为什么分成这几层
依据是真实的 import 图：默认切面上 12 个节点、21 条依赖，空的包初始化文件不画。高度是 `(出 − 入) / (出 + 入)`：
- **入口**（+1）：`__main__`，一层薄 CLI，出边 9 条。
- **中间**（+0.5）：`payload` 和 `serve`。`payload` 是汇合点，唯一同时认识事实、runtime、坐标、源码、交叉引用、解读的模块，依赖 `cut`、`highlight`、`layout`、`notes`、`runs`、`xref`。它不再直接读 `trace` 的产物，runtime 一律经 `runs` 取。`serve` 管的是 HTTP 协议、安全边界和进程内缓存。
- **中间偏下**：`scan`（0）、`runs`（−0.33）、`notes`（−0.5）。三个都只有一条出边，被上面一两个模块使用。`scan` 和 `notes` 要问 `cut` 目录树怎么切；`runs` 只依赖 `trace`（合并分片、折算叠加都调它），被 `payload` 和 `__main__` 使用。
- **叶子**（−1）：`cut`、`trace`、`layout`、`highlight`、`render`、`xref`，每个只做一件事，彼此不 import。「叶子」的意思是被依赖、不依赖别人，不是「不重要」：数据的生产者 `trace` 和 `xref`、决定图上显示哪一层的 `cut` 都在这一层。`xref` 是全仓最大的模块（近 1400 行），它只吃 scan 给的 index 这个 dict，不 import `scan`，所以也是叶子。

最值得注意的几条边界：
- **录 vs 存。** `trace` 不 import `runs`，所以仍是叶子。`trace.run` 只接收一个 parts 目录和一个 `after` 回调，不知道 run.json 长什么样。之所以用回调，而不是返回之后再收尾，是因为 driver 的信号处理器要一直装到收尾做完：`after` 在 `run` 的 try 里面调用（trace.py:698），打包中途按 Ctrl+C 才不会留下半截的 run。反过来，写 run、删 run 的代码全在 `runs` 里，「除了 `runs.remove`，没有代码会删 run」审这一个文件就能确认。
- **可重建 vs 不可重建。** 以前整个 `.codestrata/` 都是缓存；M1 之后分成两半，index / symbols / xref 随时删了重建，runs/ 删了就没了。误删有几道防线：`_outdir` 往 .codestrata/ 里写一份 README.txt（`_README`，__main__.py:34），写明除 runs/ 以外都能删；runs/ 可以是指到别的盘的软链，`rm -rf .codestrata` 只删链接本身；scan 跳过以点开头的目录（scan.py:112），不碰 runs/。解读放在 notes/，进版本库，靠 `code_sha`（整份是否过期）和引用指纹（哪一处 `file:line` 漂了）和代码绑在一起。
- **原始 vs 派生**（run 内部）。合并逻辑还不成熟，以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，`runs merge` 能重算。录制时才拿得到的东西（执行时的文件哈希、脚本和配置的副本、GPU、git 改动）只写一次，重算时不拿「现在的样子」去盖。
- **数据 vs 呈现。** `payload` 及其以下不知道 HTTP 和 HTML；`serve` 和 `render` 共用同一个 `payload`，所以 live 模式和导出版不会各长各的。搜索放在前端做、名字索引一次给全，也是为了这一条：导出版没有服务端，照样能搜。
- **记录的粒度 vs 显示的层级。** `scan` 只记最细的一层（每个文件一个模块），图上显示哪一层由 `cut` 在目录树上取切面决定。所以展开 / 收起不用重扫，解读的过期判定和 run 的叠加也都和图上怎么切无关。展开的目录画成框，但纵轴仍是架构高度，框只能在横向上占一段列（见 `layout` 的解读），不能为了把子模块归到一起让纵轴说谎。
- **快照 vs 现在的文件。** 事实都是某一刻的快照，源码却随时在改，所以每份快照都自带指纹，对不上时宁可少给、不给错。xref 记下每个文件的大小和修改时间，scan 之后改过的文件不给 Ctrl+点击（`payload._stale`）。run 只存原始键（文件:首行号）和 hook 在执行时取的文件哈希，加载时现映射到当前 index；`runs.file_state` 拿哈希和 index 的 `file_sha` 比，不和工作区比，因为叠加用的行号来自 index。它逐个标出改过、删掉、不在 index 里的文件，而不是让整个 run 作废。解读有 `code_sha` 和引用指纹。

图上看不到的一块是前端，在 `codestrata/web/`（六个 JS 文件，零构建），不是 Python，所以不在图里。整页是一个应用：上面一条标题和开关，图铺满其余空间，搜索栏（右上）和详情栏（下沿）半透明地浮在图上，全文窗口负责 Ctrl+点击。叠了 hot 图时，顶部横幅写明用的是哪个 run，录得不完整时列出原因。结构见 render 的解读。

## 阅读顺序
1. **scan**：先弄清「事实」是什么。读完能回答：图上每个框、每个箭头、每条虚线从哪来。
2. **cut**：文件级的事实怎么变成图上的节点。读完能回答：为什么默认拆开的是这几个目录，点「＋」时发生了什么，一个节点被哪个框套着。
3. **layout**：节点和框怎么变成坐标。读完能回答：为什么这个节点在这条泳道、这个位置，为什么展开一个无关的目录时别的框不会换位置。
4. **payload**，重点看 `edge_detail`：点开一个箭头看到的每一项从哪来。顺带看搜索索引和交叉引用的缓存。
5. **serve**，以及 render 解读里的前端结构：数据怎么送进浏览器，搜索和「露出某个模块」怎么走，导出版少了什么。
6. **trace**：runtime 那一半的录制，也是最难的一块（多进程、exec、调用栈、落盘串行、三级停和残留进程）。读完能回答：橙色是怎么来的，可信到什么程度，哪些情况下会丢数据。行为对照 `tests/test_runs.py` 看，它在 CPU 假服务上跑。
7. **runs**，配合 `__main__` 的 `cmd_trace` 和 `cmd_runs`：录下的东西怎么存、怎么再叠回图上。读完能回答：一个 run 里哪些是原始数据、哪些能重算；`--hot 某个case名` 解析到哪一次录制；代码改了以后哪些文件上的叠加不可信；老的 trace-<case>.json 怎么迁进来。
8. **xref**：Ctrl+点击背后的静态解析，包括再导出、作用域、C3 MRO。量最大，但和图本身无关，跳过它不影响读懂图。读完能回答：一个名字为什么能跳或不能跳，「同名的 .xxx」那一组是什么。
9. **notes**：解读层自己怎么运作，包括过期、派活顺序、机器核对。
10. **highlight** 和 `__main__` 的其余部分，需要时再看。

## 局限
- 目前只做完了 `docs/design/runs.md` 的 M1（M2 随它一起做了）。serve 仍然只在启动时选一个 run（`Handler.hot` 是类属性），换 run 要重启；时序图、run 之间的对比、多 run 导出都还没有（M3–M7）。
