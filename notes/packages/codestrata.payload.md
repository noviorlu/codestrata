---
written_by: claude-opus-5-5
target: codestrata.payload
kind: package
code_sha: 50f1f8ca57dfcd5d
status: draft
refs: payload.py:1@eae6f6c4,payload.py:103@cdbac5e5,payload.py:294@c36f173a,payload.py:232@dfc3e98b,payload.py:431@939c9802,payload.py:167@5b622921,payload.py:190@bf6ecf7f,payload.py:199@8b13c83f,serve.py:125@12773134,payload.py:111@213a94e3,payload.py:124@90fe571f,payload.py:271@b3119dbf,payload.py:393@e6dabe0a,payload.py:404@4f3fc7fd,payload.py:451@539a480b,payload.py:466@5e093a3b,payload.py:477@08d14eee,payload.py:526@e880dbe8,payload.py:495@70082336,payload.py:554@5b368878,payload.py:579@52abe3fa,payload.py:648@61e30aeb,payload.py:56@44d2f0ee
---

## 是什么
把各路数据组装成前端要的形状：某个**切面**上的图（`cut` 汇总 + `layout` 排版）、runtime 叠加（`trace`）、源码（`highlight`）、解读（`notes`）、点开一条边时它到底承载了什么；还有右边搜索栏要的名字索引，和全文窗口 Ctrl+点击要的交叉引用（`xref`）。

## 为什么这样切
serve（live）和 export（单文件）要给前端**完全相同**的数据，否则两种模式会慢慢漂移（payload.py:1）。于是组装逻辑单独成一层，两边都只调它：serve 按请求调单个函数，export 一次性调 `export_payload` 把所有东西内嵌进去。

它在图上处于中间层，正因为它是汇合点：依赖 `cut`、`highlight`、`layout`、`notes`、`trace`、`xref` 六个叶子，被 `serve` 和 `__main__` 依赖。切面、布局、高亮、trace 折算、引用倒排都委托给叶子，它只做拼接、**按切面汇总**、两类数据的**交叉**，外加 serve 进程里几份按修改时间失效的缓存。

## 读法
1. `load_index` / `load_hot` —— 读 scan 的两个 JSON；读 trace 并现场折算到当前 index（单元粒度）。`load_hot` 接受 `名字@阶段`，只取那个阶段的调用；还把被 trace 的进程按命令合并（`_procs`）、带上 case 脚本的内容（`_script`），hot 图的帮助里据此说清「这次到底跑了什么」
2. `graph_payload`（payload.py:103）—— `/api/graph` 的全部内容。`open_` 是切面（不给就是 scan 算出的默认切面），`width` 是浏览器里图框的宽度
3. `edge_detail`（payload.py:294）和它底下的 `_pair_detail`（payload.py:232）—— 点开箭头看到的东西
4. `file_outline` / `file_view` / `symbol_source` —— 源码；后两个带上 `xref_for` 给的可点击 token
5. `search_index` / `reveal` —— 搜索栏：一次给全的名字索引，和「让某个模块在图上露出来要展开哪些目录」
6. `load_xref` 到 `refs`（payload.py:431 起）—— 交叉引用：缓存、过期判断、谁引用了这个定义
7. `export_payload` —— 把上面全部打包，给单文件导出

## 关键算法
### 一切都按切面汇总（`graph_payload`）
scan 的数据全在单元（文件）之间；图上的节点是切面上的目录 / 本层文件 / 单个文件。`graph_payload` 先让 `cut.view` 给出节点和节点间的边，把它包成一个和老格式同形的「合成 index」交给 `layout.build`——布局模块完全不知道切面的存在。然后同一个 `node_of` 映射把其余数据也挪到节点上：
- 节点的文件、顶层符号、文档（`pkgFiles` / `pkgSyms` / `pkgDocs`）。C++ 文件和 README 挂在目录上，用 `cut.dir_node` 找到切面上包含那个目录的节点
- 边的种类 `edgeKinds`：用到对方几个**不同的**符号（多个单元对指向同一个符号只算一次，payload.py:167）、几个 import 没被引用，前端据此画灰实线 / 灰虚线
- hot 叠加：节点命中数、节点间调用数都从单元级累加；`runtimeOnlyEdges` 是静态 import 图里根本没有、但 runtime 走过的节点间调用（payload.py:190）——不单独画出来，图就会说谎
- 每个节点带上 `kind`、`expandable`、`parent`、`collapsible`、`fanout`、`units`（payload.py:199），前端据此画「＋」和「收起到上一级」

返回里还有 `open` / `defaultOpen` / `autoSplit`，前端用它们判断当前是不是默认切面。

### 按图框的宽度排版
`width` 原样交给 `layout.build`，总图和 hot 图都用它：宽屏上图铺满、一行多放几个节点、少折行，而不是把按 1180 排好的图整体放大。serve 把浏览器报来的宽度按 40px 取整、夹在 700–4000 之间，并把它放进缓存键（serve.py:125）：窗口拖一点点不必重排，不同宽度的排版也不会混用。

### 框：谁套着谁
展开着的目录在图上画成一个框。一个节点直接被哪个框套着，就是 `cut.parent_of` 给出的那个展开着的目录（或展开着的本层文件节点）；框的外层框再往上问 `parent_of`，一直到根（payload.py:111 起）。只有一个根时不画根的框——它就是整张图；多个根时每个根一个框，也能收起。`collapsible` 就是「有没有套着它的框」：顶层节点没有，详情面板也就不给「收起到上一级」。

每个框还记下一共框着几个画得出来的节点（payload.py:124）：hot 视图只给跑到的节点排版，框头要写「画出来的 / 一共」，一共有几个只有这里知道。

### 边的五类归并（`_pair_detail`）
两个维度交叉：静态上有没有引用（`scan` 的 `edge_uses` / `edge_dead`），runtime 有没有调用（`trace` 的 `edge_calls`）。
- **confirmed**：引用了，也调到了
- **static**：引用了，这次没走到（或者没有 runtime 数据）
- **dynamic**：调到了，但代码里没有静态引用——插件、`importlib`、注册表
- **import_only**：导入了但从没引用，原因沿用 scan 的分类；有 runtime 时，副作用 import 还会标出对方模块的顶层这次执行了没有

对齐时有一个粒度差：静态上引用的往往是**类**（`Handler(...)`），runtime 调到的是**方法**（`Handler.do_GET`）。`_top` 把 `模块:类.方法` 收到 `模块:类` 再对齐，于是一个类下面能列出「哪个方法被谁调了几次」。排序是 confirmed → dynamic → static（payload.py:271）：真调用和静态盲区最值得先看。

### 节点间的边 = 底下所有单元对的合并（`edge_detail`）
两端都是单个文件时直接走 `_pair_detail`；否则取两端底下所有有依赖（静态的或 runtime 的）单元对，逐对算完再按符号合并。状态要**合并完再定**：同一个符号可能在一对里是静态引用、在另一对里被 runtime 调到，分开看是 static + dynamic，合起来才是 confirmed。

### 源码先整文件高亮再切片
`symbol_source` 取一个符号的前 40 行，但高亮的是整个文件（payload.py:393）：从中间切开再高亮，跨行字符串会被着错色。高亮结果有缓存，所以代价只在第一次。片段的 xref 只取这几行的 token。

### 搜索索引要紧凑（`search_index`）
搜索全在前端做（`web/search.js`），每敲一个字不来回请求，导出版也能用同一套——所以索引一次给全：`mods`（目录树上每个目录、每个单元，带文件数）、`files`（Python 文件和包里的 C++ / CUDA 文件）、和 `files` 对齐的 `units`、`syms`。符号有几万条，存完整键会让模块名重复两万多遍，所以每条只存「限定名、种类首字母、文件下标、行」，键由前端用「文件所属单元去掉 .__init__ + ":" + 限定名」拼回来（payload.py:404）。serve 只序列化一次、缓存住。

点中一个结果要先在图上露出那个模块：`reveal` 在**当前**切面上展开它的所有祖先、把它自己收起（`cut.open_for`），而不是跳回默认切面把用户展开的东西全丢掉。

### 交叉引用的缓存：整份换上去（`load_xref`）
xref.json 读一次、解析一次，缓存在模块级的 `_XREF`，键是（路径, 修改时间）：重新 scan 之后下一次请求自动换成新的。serve 是多线程的，所以换法是「整份建好再一次性赋给全局名」（payload.py:451）：快路径不加锁，先把 `_XREF` 读进局部变量再比键；要换时才拿 `_XREF_LOCK`，锁里再比一次（双重检查）。读的人拿到的要么整份旧的、要么整份新的，不会拿到一半。倒排表（目标 → 引用它的地方）只有 `refs` 要，所以不在加载时建，第一次用到时由 `_inverted` 在这份缓存自己的锁里调 `_xref.invert`。没有 xref.json 时返回 None，前端就不给 Ctrl+点击。

### 改过的文件宁可不给链接（`_stale`）
xref 的 token 是「行 + UTF-16 列」，文件在 scan 之后改过，行列号就对不上了：链接会落在别的字上、跳到不相干的定义。xref.json 记了每个文件构建时的 [字节数, mtime_ns]（`fp`），`_stale` 拿现在的 stat 比（payload.py:466）；老的 xref.json 没有指纹就照旧当没改过，文件没了算改过。`xref_for` 对改过的文件只回 `stale` 和空 token（payload.py:477），形状不变；平时回这个文件（或 lo..hi 行）的 token，外加这些 token **用到的**目标 {目标号: [目标, 定义位置]}，不带全表。

### 谁引用了这个定义（`refs`）
- 同一行的几处合成一条、记 ×N（`n`），种类取最强的：调用 > 普通引用 > import，排序也是调用在前（payload.py:526）。`counts` / `total` 仍按处数计，`lines` 是合并后的条数，最多列 `limit` 条
- 每条带那一行的原文，读的是**现在**的文件：`_line_text` 背后是按（路径, mtime_ns）缓存的 `_lines_of`（payload.py:495）——几百条引用常常落在同几个文件里，不必每条读一遍，文件一改键就变。所在文件 scan 后改过的条目照列、只标 `stale`（行号可能已经不对）——和全文窗口里整份不给链接不同，这里只提示
- 定义本身作为 `def` 放最上面：跳到某个引用之后，点它就回到定义。函数 / 类还带上这次 runtime 调了几次（`calls`）
- 「同名的 .xxx」（`maybe`，payload.py:554）：方法、类属性常常通过别的对象调用（engine.generate()），静态分析不知道接收者是什么类型，确认不了是不是它。xref 把这种解析不了的「表达式.名字」按名字存在 `attrs` 里；这里按名字列出、同一行合并、调用在前，标明没确认，并附上仓库里一共有几个同名成员（`same`）——只有它一个时基本就是它。同名成员超过 3 个的名字（get、to……）xref 压根不记（`ATTRS_MAX_SAME`），列出来一大半都不是它

### 导出有体积预算
`export_payload` 只导出默认切面，把整个导出控制在 14 MB（payload.py:579，单文件宿主上限 16 MB）：先把图、边详情、解读、符号片段、搜索索引放进去，剩下的额度给全文。全文按「这次 case 跑到过的 + 解读里引用过的」优先、再按体积从小到大挑；先用原始字节数估算，明显放不下的不去高亮——vllm-omni 上导出从 32 秒降到 10 秒。

xref 的目标全导出共用一张表 `xrefTargets`：片段和文件只带 token，目标挪进共用表（`share`），前端取出时再补回（`web/ds.js`）。早先每个文件各带一份，同一个目标重复几百遍，占掉的额度够再内嵌一两百个文件。挑全文时一个文件的代价 = 它自己 + 它带来的**新**目标的字节数，放得下才把新目标并进表（payload.py:648）。

## 局限
- 导出的页面是固定切面：不能展开（其他切面的边详情没有预先算）、没有 `reveal`；不传 `width`，按默认 1180 排版；引用列表只能在内嵌了全文的文件里找，也没有「同名的 .xxx」。
- `load_hot` 的过期检查只对存了文件哈希的新 trace 生效；老 trace 不报，而不是误报全部过期（payload.py:56）。`_procs` 对老 trace（没有 ppid 那版只存了 argv 前 6 个）标 `cut`，免得以为命令就这么长；`_script` 对老 trace 读的是现在的脚本文件，标 `saved` 为假——可能已经不是当时跑的那份。
- 每个切面的 payload 都带全部顶层符号，vllm-omni 上一份约 2.5 MB；serve 的缓存键是（切面, 宽度），只留最近的一批。
- `_XREF` 是进程级的单槽缓存：同一进程里交替查两个仓库会互相顶掉，每次重新解析整份 xref.json（serve 一个进程只服务一个仓库，所以实际碰不到）。
