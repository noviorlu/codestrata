---
written_by: claude-opus-5-5
target: codestrata.payload
kind: package
code_sha: c2bef4114fc24508
status: draft
refs: payload.py:1@eae6f6c4,payload.py:44@792c7b2a,payload.py:67@cdbac5e5,payload.py:258@c36f173a,payload.py:196@dfc3e98b,payload.py:395@939c9802,runs.py:586@5028c052,serve.py:410@eae1c1a1,notes.py:316@a5ce0618,payload.py:45@17be1534,runs.py:661@b2d6757f,runs.py:693@47fcd1f8,payload.py:35@d6513e46,runs.py:650@47887e94,payload.py:131@5b622921,payload.py:154@bf6ecf7f,payload.py:162@b41f714c,payload.py:63@1d41b21d,serve.py:167@4317bbc0,serve.py:265@12773134,payload.py:75@213a94e3,payload.py:88@90fe571f,payload.py:235@b3119dbf,payload.py:357@e6dabe0a,payload.py:374@65f7556a,payload.py:415@539a480b,payload.py:430@5e093a3b,payload.py:441@08d14eee,payload.py:491@8b3d5b0c,payload.py:459@70082336,payload.py:518@5b368878,payload.py:543@52abe3fa,payload.py:612@61e30aeb,serve.py:270@7f242479,serve.py:278@2b2b2aed
---

## 是什么
把各路数据组装成前端要的形状：某个**切面**上的图（`cut` 汇总 + `layout` 排版）、runtime 叠加（某一次 run，由 `runs` 映射到当前 index）、源码（`highlight`）、解读（`notes`）、点开一条边时它到底承载了什么；还有右边搜索栏要的名字索引，和全文窗口 Ctrl+点击要的交叉引用（`xref`）。

## 为什么这样切
serve（live）和 export（单文件）要给前端**完全相同**的数据，否则两种模式会慢慢漂移（payload.py:1）。于是组装逻辑单独成一层，两边都只调它：serve 按请求调单个函数，export 一次性调 `export_payload` 把所有东西内嵌进去。

它在图上处于中间层，正因为它是汇合点：依赖 `cut`、`highlight`、`layout`、`notes`、`runs`、`xref` 六个下层模块，被 `serve` 和 `__main__` 依赖。切面、布局、高亮、引用倒排都委托给下层；run 的存储、解析、映射和过期判断整个交给 `runs`（M1 之前这些散在这里的 `load_hot` 里，直接读 `trace` 的产物）。它自己只做拼接、**按切面汇总**、两类数据的**交叉**，外加 serve 进程里几份按修改时间失效的缓存。

## 读法
1. `load_index` / `load_hot` —— 读 scan 的两个 JSON；把一个 run 叠到当前 index 上。`load_hot` 现在只是 `runs.load` 的薄包装（payload.py:44），见下面「关键算法」第一节
2. `graph_payload`（payload.py:67）—— `/api/graph` 的全部内容。`open_` 是切面（不给就是 scan 算出的默认切面），`width` 是浏览器里图框的宽度
3. `edge_detail`（payload.py:258）和它底下的 `_pair_detail`（payload.py:196）—— 点开箭头看到的东西
4. `file_outline` / `file_view` / `symbol_source` —— 源码；后两个带上 `xref_for` 给的可点击 token
5. `search_index` / `reveal` —— 搜索栏：一次给全的名字索引，和「让某个模块在图上露出来要展开哪些目录」
6. `load_xref` 到 `refs`（payload.py:395 起）—— 交叉引用：缓存、过期判断、谁引用了这个定义
7. `export_payload` —— 把上面全部打包，给单文件导出

## 关键算法
### `load_hot`：一个名字、一行提示，别的都在 `runs`
以前每个 case 只有一份 `trace-<case>.json`，同名重录就覆盖，`load_hot` 自己读文件、切阶段、比过期、合并进程、找脚本。M1 起每次 trace 都是 `.codestrata/runs/` 下一个新目录（录一次、永久复用，见 `docs/design/runs.md` 第 1、3 节），「REF 指的是哪个 run、它的计数和清单怎么读、哪些文件录制后改过」都成了 `runs` 的事，所以这里整个换成一句 `runs.load`（payload.py:44）：
- **ref 语法**（`runs.resolve`，runs.py:586）：完整 run id，或 case 名（取它最新一次 ok 的，没有就退到最新的 partial 并提示），后面可以加 `@阶段`；不写阶段就是各阶段相加——老的 `--hot 名字@阶段` 写法原样能用。第一次解析时 `catalog` 还会顺带把老的 `trace-<case>.json` 迁进 runs/，老 case 名不必手动搬
- **名字和调用方式不变**（第三个参数由 case 改叫 ref，调用方都按位置传）：`__main__` 的 graph / tasks / pack、`tests/test_runs.py` 照旧调 `load_hot`。serve 只在启动时调一次，用来当场校验 `--hot` 写没写错、并把它解析成页面默认选中的完整 id（serve.py:410）；之后每个请求自带 `run=`，由 `serve.Handler._hot` 直接调 `runs.resolve` / `runs.load`，按 run 和计数文件的 mtime 缓存——所以页面上换 run、换阶段不用重启（M4）。`runs.load` 返回的 meta 保留老的全部键（`procs`、`script`、`stale_files`、`phases`……，`web/app.js` 的 hot 横幅和帮助认它们），再加上 `run_id`、`status`、`problems`、`file_state`、`git`、`tags` 等。hot 本身还带上 `run`，`notes.prompt_pack` 的 runtime 那一行据此写明数字来自哪个 run（notes.py:316）
- **打印用了哪个 run**（payload.py:45）：case 名解析到的是「最新一次录完的」，每录一次新的，同一个 `--hot 名字` 指的 run 就变了——不打印出来，用户分不清图上的数字来自哪一次（设计 4.5：每条命令都打印解析到的完整 id）。打到 stderr，因为 `pack` 的 stdout 是整个输入包，常被重定向给 agent。serve 按请求换 run 不经过这里、不打印：页面的 hot 横幅直接显示 meta 里的 `run_id`
- 原先也在这里的两件事一并搬走了。进程按命令合并成了 `runs.procs_grouped`（runs.py:661），「argv 被截断」改读每个进程记下的 `argv_cut`（新 run 由 hook 在 import 时记，迁移来的老 trace 在迁移时按「没有 ppid」补上），不再在读的时候现猜，另外带上被 setproctitle 改过的 `title`。case 脚本改为优先读 run 目录 `files/` 里录制时存下的副本（runs.py:693），老 run 没存才读现在的文件、标 `saved` 为假

### `load_index` 的 `file_sha`：故意留 None
scan 现在往 symbols.json 里写每个 .py 文件的内容哈希 `file_sha`，和录制时记下的哈希同一种。`load_index` 读它时**不给默认值**（payload.py:35）：老的 symbols.json 没有这个键，得到的是 None 而不是空字典。`runs.file_state` 靠这一点分辨「老 index」（`now is not None` 不成立，runs.py:650，退回拿工作区比，即 `trace.stale_files` 的老办法）和「新 index」（直接和 index 比——叠加用的行号来自 index，这才是该比的对象）。若默认成空字典，老 index 上所有文件都会被当成没改过，过期提示悄悄消失。

### 一切都按切面汇总（`graph_payload`）
scan 的数据全在单元（文件）之间；图上的节点是切面上的目录 / 本层文件 / 单个文件。`graph_payload` 先让 `cut.view` 给出节点和节点间的边，把它包成一个和老格式同形的「合成 index」交给 `layout.build`——布局模块完全不知道切面的存在。然后同一个 `node_of` 映射把其余数据也挪到节点上：
- 节点的文件、顶层符号、文档（`pkgFiles` / `pkgSyms` / `pkgDocs`）。C++ 文件和 README 挂在目录上，用 `cut.dir_node` 找到切面上包含那个目录的节点
- 边的种类 `edgeKinds`：用到对方几个**不同的**符号（多个单元对指向同一个符号只算一次，payload.py:131）、几个 import 没被引用，前端据此画灰实线 / 灰虚线
- hot 叠加：节点命中数、节点间调用数都从单元级累加；`runtimeOnlyEdges` 是静态 import 图里根本没有、但 runtime 走过的节点间调用（payload.py:154）——不单独画出来，图就会说谎
- 每个节点带上 `kind`、`expandable`、`parent`、`collapsible`、`fanout`、`units`（payload.py:162），前端据此画「＋」和「收起到上一级」

返回里还有 `open` / `defaultOpen` / `autoSplit`，前端用它们判断当前是不是默认切面；`hotMeta` 原样透传 `runs.load` 给的 meta（CLI 经 `load_hot`，serve 经 `serve.Handler._hot`）。

切面先过一道 `_norm_open`（payload.py:63）：没给就换成 scan 的默认切面，给了就只留 `cut.is_node` 认得的名字（重新 scan 之后 URL 里残留的旧目录名被悄悄丢掉，而不是传给下层）。M5 起 serve 的时序图接口（`serve.Handler._seq`）也调它（serve.py:167），所以时序图的生命线和模块图的节点落在同一个切面上，两张图切换时选中的东西对得上。

### 按图框的宽度排版
`width` 原样交给 `layout.build`，总图和 hot 图都用它：宽屏上图铺满、一行多放几个节点、少折行，而不是把按 1180 排好的图整体放大。serve 把浏览器报来的宽度按 40px 取整、夹在 700–4000 之间，并把它放进缓存键（serve.py:265）：窗口拖一点点不必重排，不同宽度的排版也不会混用。

### 框：谁套着谁
展开着的目录在图上画成一个框。一个节点直接被哪个框套着，就是 `cut.parent_of` 给出的那个展开着的目录（或展开着的本层文件节点）；框的外层框再往上问 `parent_of`，一直到根（payload.py:75 起）。只有一个根时不画根的框——它就是整张图；多个根时每个根一个框，也能收起。`collapsible` 就是「有没有套着它的框」：顶层节点没有，详情面板也就不给「收起到上一级」。

每个框还记下一共框着几个画得出来的节点（payload.py:88）：hot 视图只给跑到的节点排版，框头要写「画出来的 / 一共」，一共有几个只有这里知道。

### 边的五类归并（`_pair_detail`）
两个维度交叉：静态上有没有引用（`scan` 的 `edge_uses` / `edge_dead`），runtime 有没有调用（`trace.to_package_graph` 算出的 `edge_calls`）。
- **confirmed**：引用了，也调到了
- **static**：引用了，这次没走到（或者没有 runtime 数据）
- **dynamic**：调到了，但代码里没有静态引用——插件、`importlib`、注册表
- **import_only**：导入了但从没引用，原因沿用 scan 的分类；有 runtime 时，副作用 import 还会标出对方模块的顶层这次执行了没有

对齐时有一个粒度差：静态上引用的往往是**类**（`Handler(...)`），runtime 调到的是**方法**（`Handler.do_GET`）。`_top` 把 `模块:类.方法` 收到 `模块:类` 再对齐，于是一个类下面能列出「哪个方法被谁调了几次」。排序是 confirmed → dynamic → static（payload.py:235）：真调用和静态盲区最值得先看。

### 节点间的边 = 底下所有单元对的合并（`edge_detail`）
两端都是单个文件时直接走 `_pair_detail`；否则取两端底下所有有依赖（静态的或 runtime 的）单元对，逐对算完再按符号合并。状态要**合并完再定**：同一个符号可能在一对里是静态引用、在另一对里被 runtime 调到，分开看是 static + dynamic，合起来才是 confirmed。

### 源码先整文件高亮再切片
`symbol_source` 取一个符号的前 40 行，但高亮的是整个文件（payload.py:357）：从中间切开再高亮，跨行字符串会被着错色。高亮结果有缓存，所以代价只在第一次。片段的 xref 只取这几行的 token。

### 搜索索引要紧凑（`search_index`）
搜索全在前端做（`web/search.js`），每敲一个字不来回请求，导出版也能用同一套——所以索引一次给全：`mods`（目录树上每个目录、每个单元，带文件数）、`files`（Python 文件和包里的 C++ / CUDA 文件）、和 `files` 对齐的 `units`、`syms`。符号有几万条，存完整键会让模块名重复两万多遍，所以每条只存「限定名、种类首字母、文件下标、行」，键由前端用「文件所属单元去掉 .__init__ + ":" + 限定名」拼回来（payload.py:374）。serve 只序列化一次、缓存住。

点中一个结果要先在图上露出那个模块：`reveal` 在**当前**切面上展开它的所有祖先、把它自己收起（`cut.open_for`），而不是跳回默认切面把用户展开的东西全丢掉。

### 交叉引用的缓存：整份换上去（`load_xref`）
xref.json 读一次、解析一次，缓存在模块级的 `_XREF`，键是（路径, 修改时间）：重新 scan 之后下一次请求自动换成新的。serve 是多线程的，所以换法是「整份建好再一次性赋给全局名」（payload.py:415）：快路径不加锁，先把 `_XREF` 读进局部变量再比键；要换时才拿 `_XREF_LOCK`，锁里再比一次（双重检查）。读的人拿到的要么整份旧的、要么整份新的，不会拿到一半。倒排表（目标 → 引用它的地方）只有 `refs` 要，所以不在加载时建，第一次用到时由 `_inverted` 在这份缓存自己的锁里调 `_xref.invert`。没有 xref.json 时返回 None，前端就不给 Ctrl+点击。

### 改过的文件宁可不给链接（`_stale`）
xref 的 token 是「行 + UTF-16 列」，文件在 scan 之后改过，行列号就对不上了：链接会落在别的字上、跳到不相干的定义。xref.json 记了每个文件构建时的 [字节数, mtime_ns]（`fp`），`_stale` 拿现在的 stat 比（payload.py:430）；老的 xref.json 没有指纹就照旧当没改过，文件没了算改过。`xref_for` 对改过的文件只回 `stale` 和空 token（payload.py:441），形状不变；平时回这个文件（或 lo..hi 行）的 token，外加这些 token **用到的**目标 {目标号: [目标, 定义位置]}，不带全表。

### 谁引用了这个定义（`refs`）
- 同一行的几处合成一条、记 ×N（`n`），种类取最强的：调用 > 普通引用 > import，排序也是调用在前（payload.py:491）。`counts` / `total` 仍按处数计，`lines` 是合并后的条数，最多列 `limit` 条
- 每条带那一行的原文，读的是**现在**的文件：`_line_text` 背后是按（路径, mtime_ns）缓存的 `_lines_of`（payload.py:459）——几百条引用常常落在同几个文件里，不必每条读一遍，文件一改键就变。所在文件 scan 后改过的条目照列、只标 `stale`（行号可能已经不对）——和全文窗口里整份不给链接不同，这里只提示
- 定义本身作为 `def` 放最上面：跳到某个引用之后，点它就回到定义。函数 / 类还带上这次 runtime 调了几次（`calls`）
- 「同名的 .xxx」（`maybe`，payload.py:518）：方法、类属性常常通过别的对象调用（engine.generate()），静态分析不知道接收者是什么类型，确认不了是不是它。xref 把这种解析不了的「表达式.名字」按名字存在 `attrs` 里；这里按名字列出、同一行合并、调用在前，标明没确认，并附上仓库里一共有几个同名成员（`same`）——只有它一个时基本就是它。同名成员超过 3 个的名字（get、to……）xref 压根不记（`ATTRS_MAX_SAME`），列出来一大半都不是它

### 导出有体积预算
`export_payload` 只导出默认切面，把整个导出控制在 14 MB（payload.py:543，单文件宿主上限 16 MB）：先把图、边详情、解读、符号片段、搜索索引放进去，剩下的额度给全文。全文按「这次 run 跑到过的 + 解读里引用过的」优先、再按体积从小到大挑；先用原始字节数估算，明显放不下的不去高亮——vllm-omni 上导出从 32 秒降到 10 秒。

xref 的目标全导出共用一张表 `xrefTargets`：片段和文件只带 token，目标挪进共用表（`share`），前端取出时再补回（`web/ds.js`）。早先每个文件各带一份，同一个目标重复几百遍，占掉的额度够再内嵌一两百个文件。挑全文时一个文件的代价 = 它自己 + 它带来的**新**目标的字节数，放得下才把新目标并进表（payload.py:612）。

## 局限
- 导出的页面是固定切面：不能展开（其他切面的边详情没有预先算）、没有 `reveal`；不传 `width`，按默认 1180 排版；引用列表只能在内嵌了全文的文件里找，也没有「同名的 .xxx」。导出里只有一个 run（多 run 导出排在 M7），也不带时序图：`export_payload` 不算时序，`web/ds.js` 的导出版对时序图请求直接报「请用 codestrata serve」（设计 M5 状态里记为 §8 / M7 再说）。
- ref 找不到、阶段不存在、run 还没有计数（还在录，或录制中断、要先 `runs merge`）时，`runs` 直接以 `SystemExit` 报错，这里不兜底——CLI（和 serve 启动时校验 `--hot`）上退出并给出下一步该跑的命令；serve 按请求解析时由 `serve.Handler._hot` 转成 `LookupError`，回 404 并带上这句提示，页面照常可用。
- 每个切面的 payload 都带全部顶层符号，vllm-omni 上一份约 2.5 MB；serve 的缓存键是（切面, 宽度, run）（serve.py:270），只留最近的 32 份（serve.py:278）——换着看几个 run 时，同一个切面会各存一份。
- `_XREF` 是进程级的单槽缓存：同一进程里交替查两个仓库会互相顶掉，每次重新解析整份 xref.json（serve 一个进程只服务一个仓库，所以实际碰不到）。
