---
written_by: claude-opus-5-5
target: codestrata.payload
kind: package
code_sha: e8d689ac7a587ab1
status: draft
refs: payload.py:1@eae6f6c4,payload.py:171@b3119dbf,payload.py:234@e6dabe0a,payload.py:245@146226c2,payload.py:50@e14d0fb2
---

## 是什么
把各路数据组装成前端要的形状：图（`layout`）、runtime 叠加（`trace`）、源码（`highlight`）、解读（`notes`），以及点开一条边时它到底承载了什么。

## 为什么这样切
serve（live）和 export（单文件）要给前端**完全相同**的数据，否则两种模式会慢慢漂移（payload.py:1）。于是组装逻辑单独成一层，两边都只调它：serve 按请求调单个函数，export 一次性调 `export_payload` 把所有东西内嵌进去。

它在图上处于中间层，正因为它是汇合点：依赖 `highlight`、`layout`、`notes`、`trace` 四个叶子，被 `serve` 和 `__main__` 依赖。它自己不做 I/O 以外的算法——布局、高亮、trace 折算都委托给叶子，它只做拼接和两类数据的**交叉**。

## 读法
1. `load_index` / `load_hot` —— 读 scan 的两个 JSON；读 trace 并现场折算到当前 index。`load_hot` 接受 `名字@阶段`，只取那个阶段的调用
2. `graph_payload` —— `/api/graph` 的全部内容：总图布局、hot 视图的单独布局（`graphHot`）、每条边的种类、只在 runtime 出现的边、每个包挂的文档
3. `edge_detail` —— 点开箭头看到的东西，本模块最有意思的函数
4. `file_view` / `symbol_source` —— 源码
5. `export_payload` —— 把上面全部打包，给单文件导出

## 关键算法
### 边的五类归并（`edge_detail`）
两个维度交叉：静态上有没有引用（`scan` 的 `edge_uses` / `edge_dead`），runtime 有没有调用（`trace` 的 `edge_calls`）。
- **confirmed**：引用了，也调到了
- **static**：引用了，这次没走到（或者没有 runtime 数据）
- **dynamic**：调到了，但代码里没有静态引用——插件、`importlib`、注册表
- **import_only**：导入了但从没引用，原因沿用 scan 的分类；有 runtime 时，副作用 import 还会标出对方模块的顶层这次执行了没有

对齐时有一个粒度差：静态上引用的往往是**类**（`Handler(...)`），runtime 调到的是**方法**（`Handler.do_GET`）。`_top` 把 `模块:类.方法` 收到 `模块:类` 再对齐，于是一个类下面能列出「哪个方法被谁调了几次」。排序是 confirmed → dynamic → static（payload.py:171）：真调用和静态盲区最值得先看。

### 边的种类在画图时就给出（`graph_payload`）
`edgeKinds` 给每条边「用到对方几个符号、几个 import 没被引用」，前端据此画灰实线 / 灰虚线；`runtimeOnlyEdges` 列出静态 import 图里根本没有、但 runtime 走过的包间调用——不单独画出来，图就会说谎。

### 源码先整文件高亮再切片
`symbol_source` 取一个符号的前 40 行，但高亮的是整个文件（payload.py:234）：从中间切开再高亮，跨行字符串会被着错色。高亮结果有缓存，所以代价只在第一次。

### 导出有体积预算
`export_payload` 把整文件内容按 8 MB 预算内嵌（payload.py:245）：小仓库全带上，大仓库（vllm-omni 约 57 万行）只带一部分，超出的文件在导出版里只能看符号片段。

## 局限
- `load_hot` 的过期检查只对存了文件哈希的新 trace 生效；老 trace 不报，而不是误报全部过期（payload.py:50）。
