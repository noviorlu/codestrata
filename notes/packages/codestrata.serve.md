---
written_by: claude-opus-5-5
target: codestrata.serve
kind: package
code_sha: 53cd32f496a33ea2
status: draft
refs: serve.py:1@48ec2c0a,serve.py:257@ed0daba7,serve.py:263@3885b904,serve.py:242@8775e5c5,serve.py:252@e84bd2dc,serve.py:128@125738d2,serve.py:130@fcd0389a,serve.py:171@75ddaff2,serve.py:261@fe8bdeec,serve.py:125@12773134,serve.py:117@bbaaeff1,serve.py:177@61a4b359,serve.py:183@e66ee7ac,serve.py:145@5e77a01f,serve.py:187@820288c5
---

## 是什么
本地部署：一个只用标准库的 HTTP 服务，同时提供前端静态文件（`codestrata/web/`）和 `/api/*`。人在浏览器里读图、搜名字、看源码、在全文窗口里 Ctrl+点击查引用、写解读；LLM agent 可以直接调同一套 API 取输入包、写回解读。

## 为什么这样切
它只做「协议 + 安全边界 + 进程内缓存」，内容全部委托出去：图、边、源码、搜索索引、交叉引用来自 `payload`，解读的读写来自 `notes`，「这个名字是不是图上的节点」问 `cut`。所以它依赖这三个模块、只被 `__main__` 的 `serve` 子命令调用。

单文件导出不经过它——同一套前端在导出版里由 `web/ds.js` 改读内嵌数据。这决定了几条新路由的形状：搜索索引是「一次给全部名字，前端自己搜」，因为导出版没有服务端，也要能搜（导出时把同一份 `payload.search_index` 内嵌进去）；引用列表在导出版里只拼得出一部分；「露出某个模块」在导出版里干脆不可用——导出的是固定切面，展开 / 收起要靠 serve。

路由表在模块 docstring 里（serve.py:1），是读这个文件的最好入口。

## 读法
1. 模块 docstring —— 路由表
2. `main` —— 启动时一次性加载 index 和 trace，挂到 `Handler` 的类属性上，并清空两份缓存（serve.py:257 起）
3. `Handler._in_repo` / `Handler._target` —— 安全边界
4. `Handler.do_GET` —— 按路由顺序往下读；`Handler.do_PUT` —— 写解读
5. `_editor` / `_code_page` —— 两个外围功能

## 关键算法
### 安全边界
- 只监听 127.0.0.1（serve.py:263）。
- 任何文件路径 realpath 之后必须落在仓库内（`Handler._in_repo`），挡住 `../` 和符号链接越界。
- 解读的目标只接受目录树上真实存在的节点名（目录、`目录.*`、文件级模块，由 `cut.is_node` 判断）或总览保留名，防止借 target 写出仓库外的文件；请求体上限 2 MB（serve.py:242），元数据只收 `written_by` / `status` / `confidence` 三个键（serve.py:252）。
- 新路由的参数都不是路径：`/api/reveal` 的 node 在 `payload.reveal` 里先过 `cut.is_node`，不认识就 404；`/api/refs?t=` 的 t 是交叉引用里的目标键（形如 s:模块:限定名），只拿来查表，查不到（或者还没有 xref.json）就 404。引用结果里的文件都来自 scan 时写下的 xref，所以不用再过 `_in_repo`。

### 状态放在类属性上，两份缓存
`BaseHTTPRequestHandler` 每个请求实例化一次，所以仓库、index、trace 这些进程级状态挂在 `Handler` 类上，缓存也是：
- `Handler._graphs`：`/api/graph` 的结果按「切面 + 宽度」缓存成字节串，键是排序后的 open 集合再接 `@宽度`（serve.py:128）。同一切面、同一宽度的布局只依赖 index 和 trace，进程内不会变。切面可以任意组合，超过三十来份就丢掉最早算出来的那份（serve.py:130）——按插入顺序丢，命中不会续命，不是严格的 LRU。
- `Handler._search`：`/api/search-index` 只依赖 index，进程里第一次请求时算一次、存成字节串（serve.py:171）。每个类 / 函数 / 方法一条，名字有几万个，所以用紧凑分隔符序列化，省掉逗号冒号后面的空格。

`main` 里把两份缓存都重置（serve.py:261），免得同一进程里再起一次服务时沿用上一次的结果。

### 按图框宽度排版
`/api/graph` 多了 `?w=`：前端把页面上图框的实际宽度带过来，`payload.graph_payload` 按它排版——宽屏上图铺满、少折行，而不是把一张 1180 宽的图放大。宽度按 40px 取整、夹在 700–4000 之间，解析不了就退回 1180（以前写死的宽度）（serve.py:125）。取整有两层用处：窗口拖一点点不必重排；宽度是缓存键的一部分，不取整的话每个像素都会占一份缓存。

### 空值有含义
查询串按「保留空值」解析（serve.py:117，`keep_blank_values`）：`?open=` 是「什么都不展开」，和不带 open 的「默认切面」不同（`payload` 里 None 才换成默认切面）。`/api/graph` 和 `/api/reveal` 都靠这个区分：多根仓库里把最后一个根的框也收起时发的就是空的 open；前端调 reveal 时总带着当前切面，当前切面可能是空的——空值若被丢掉，页面会跳回整个默认切面，reveal 也会在默认切面而不是当前切面上算。

### 搜索、露出、引用
- `/api/search-index`（serve.py:171）：目录和文件级模块、文件、类 / 函数 / 方法的全部名字，前端自己搜。
- `/api/reveal?node=&open=`（serve.py:177）：搜到的模块可能藏在收起的目录里。它在当前切面上补齐这个节点的全部祖先（节点本身若是目录则保持收起），返回完整的新 open 列表，前端拿它再请求 `/api/graph`。算法在 `cut.open_for`。
- `/api/refs?t=`（serve.py:183）：全文窗口里 Ctrl+点击一个定义，列出引用它的地方——调用在前，其次普通引用、import，每条带那一行原文；方法、类属性另给一组「同名的 .xxx，接收者类型没核实」。顺带把 trace 传进去，给函数附上 runtime 调用次数。反方向（名字 → 定义）不走这里：`/api/file` 返回的全文里已经带着这个文件的全部 xref token。

### 读解读时顺带核对
`GET /api/notes/<target>` 返回解读的同时附上 `notes.verify` 的结果，前端直接显示「引用对不上」的地方。图上的徽标走另一条路：`GET /api/status?ids=`（serve.py:145）一次取回一批节点的状态，不核对内容——展开之后图上有上百个节点，逐个核对太慢。

### 文件树与跳编辑器
`/api/outline`（serve.py:187）只返回一个文件的符号大纲，详情面板的文件树展开某个文件时才请求，不必把整份高亮全文传过去。

`/api/open` 找本机的编辑器 CLI（`code -g`、`cursor` …）并以 `file:line` 打开；找不到返回 501，前端照常可用。

## 局限
- index 和 trace 只在启动时加载：重新 `scan` 或重录 trace 之后，图和搜索索引要重启 serve 才更新。解读每次请求现读；xref.json 则由 `payload.load_xref` 按修改时间自动换新——所以 scan 过但没重启时，Ctrl+点击和引用用的是新的，图和搜索栏还是旧的。
- `/code/<path>` 是全文窗口（`web/viewer.js`）出现之前的纯文本全文页，前端已不再链接它；仍可以当一个能直接贴出去的 `file:line` 链接用。
