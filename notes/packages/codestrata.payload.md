---
written_by: claude-opus-5-5
target: codestrata.payload
kind: package
code_sha: d7274d2ca943ebe3
status: draft
refs: payload.py:1@eae6f6c4,payload.py:77@cdbac5e5,payload.py:248@c36f173a,payload.py:186@dfc3e98b,payload.py:125@4bf974c3,payload.py:145@6b576190,payload.py:150@61dea98d,payload.py:225@b3119dbf,payload.py:347@e6dabe0a,payload.py:358@52abe3fa,payload.py:52@e14d0fb2
---

## 是什么
把各路数据组装成前端要的形状：某个**切面**上的图（`cut` 汇总 + `layout` 排版）、runtime 叠加（`trace`）、源码（`highlight`）、解读（`notes`），以及点开一条边时它到底承载了什么。

## 为什么这样切
serve（live）和 export（单文件）要给前端**完全相同**的数据，否则两种模式会慢慢漂移（payload.py:1）。于是组装逻辑单独成一层，两边都只调它：serve 按请求调单个函数，export 一次性调 `export_payload` 把所有东西内嵌进去。

它在图上处于中间层，正因为它是汇合点：依赖 `cut`、`highlight`、`layout`、`notes`、`trace` 五个叶子，被 `serve` 和 `__main__` 依赖。它自己不做 I/O 以外的算法——切面、布局、高亮、trace 折算都委托给叶子，它只做拼接、**按切面汇总**和两类数据的**交叉**。

## 读法
1. `load_index` / `load_hot` —— 读 scan 的两个 JSON；读 trace 并现场折算到当前 index（单元粒度）。`load_hot` 接受 `名字@阶段`，只取那个阶段的调用
2. `graph_payload`（payload.py:77）—— `/api/graph` 的全部内容，参数 `open_` 是切面（展开着的目录；不给就是 scan 算出的默认切面）
3. `edge_detail`（payload.py:248）和它底下的 `_pair_detail`（payload.py:186）—— 点开箭头看到的东西，本模块最有意思的部分
4. `file_outline` / `file_view` / `symbol_source` —— 源码
5. `export_payload` —— 把上面全部打包，给单文件导出

## 关键算法
### 一切都按切面汇总（`graph_payload`）
scan 的数据全在单元（文件）之间；图上的节点是切面上的目录 / 本层文件 / 单个文件。`graph_payload` 先让 `cut.view` 给出节点和节点间的边，把它包成一个和老格式同形的「合成 index」交给 `layout.build`——布局模块完全不知道切面的存在。然后同一个 `node_of` 映射把其余数据也挪到节点上：
- 节点的文件、顶层符号、文档（`pkgFiles` / `pkgSyms` / `pkgDocs`）。C++ 文件和 README 挂在目录上，用 `cut.dir_node` 找到切面上包含那个目录的节点
- 边的种类 `edgeKinds`：用到对方几个**不同的**符号（多个单元对指向同一个符号只算一次，payload.py:125）、几个 import 没被引用，前端据此画灰实线 / 灰虚线
- hot 叠加：节点命中数、节点间调用数都从单元级累加；`runtimeOnlyEdges` 是静态 import 图里根本没有、但 runtime 走过的节点间调用（payload.py:145）——不单独画出来，图就会说谎
- 每个节点带上 `kind`、`expandable`、`parent`、`fanout`（payload.py:150），前端据此画「＋」和「收起到上一级」

返回里还有 `open` / `defaultOpen` / `autoSplit`，前端用它们判断当前是不是默认切面。

### 边的五类归并（`_pair_detail`）
两个维度交叉：静态上有没有引用（`scan` 的 `edge_uses` / `edge_dead`），runtime 有没有调用（`trace` 的 `edge_calls`）。
- **confirmed**：引用了，也调到了
- **static**：引用了，这次没走到（或者没有 runtime 数据）
- **dynamic**：调到了，但代码里没有静态引用——插件、`importlib`、注册表
- **import_only**：导入了但从没引用，原因沿用 scan 的分类；有 runtime 时，副作用 import 还会标出对方模块的顶层这次执行了没有

对齐时有一个粒度差：静态上引用的往往是**类**（`Handler(...)`），runtime 调到的是**方法**（`Handler.do_GET`）。`_top` 把 `模块:类.方法` 收到 `模块:类` 再对齐，于是一个类下面能列出「哪个方法被谁调了几次」。排序是 confirmed → dynamic → static（payload.py:225）：真调用和静态盲区最值得先看。

### 节点间的边 = 底下所有单元对的合并（`edge_detail`）
两端都是单个文件时直接走 `_pair_detail`；否则取两端底下所有有依赖（静态的或 runtime 的）单元对，逐对算完再按符号合并。状态要**合并完再定**：同一个符号可能在一对里是静态引用、在另一对里被 runtime 调到，分开看是 static + dynamic，合起来才是 confirmed。

### 源码先整文件高亮再切片
`symbol_source` 取一个符号的前 40 行，但高亮的是整个文件（payload.py:347）：从中间切开再高亮，跨行字符串会被着错色。高亮结果有缓存，所以代价只在第一次。

### 导出有体积预算
`export_payload` 只导出默认切面，把整个导出控制在 14 MB（payload.py:358，单文件宿主上限 16 MB）：先把图、边详情、解读、符号片段放进去，剩下的额度给全文。全文按「这次 case 跑到过的 + 解读里引用过的」优先、再按体积从小到大挑；先用原始字节数估算，明显放不下的不去高亮——vllm-omni 上导出从 32 秒降到 10 秒。导出的页面是固定切面，不能展开（其他切面的边详情没有预先算）。

## 局限
- `load_hot` 的过期检查只对存了文件哈希的新 trace 生效；老 trace 不报，而不是误报全部过期（payload.py:52）。
- 每个切面的 payload 都带全部符号列表，vllm-omni 上一份约 2.5 MB；serve 只缓存最近的一批切面。
