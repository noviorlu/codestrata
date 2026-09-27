---
written_by: claude-opus-5-5
target: codestrata.serve
kind: package
code_sha: 02f0b3faa0bf802b
status: draft
refs: serve.py:1@48ec2c0a,serve.py:231@ed0daba7,serve.py:236@3885b904,serve.py:216@8775e5c5,serve.py:226@e84bd2dc,serve.py:115@5b6d121a,serve.py:120@fcd0389a,serve.py:112@bbaaeff1,serve.py:135@5e77a01f,serve.py:161@820288c5
---

## 是什么
本地部署：一个只用标准库的 HTTP 服务，同时提供前端静态文件（`codestrata/web/`）和 `/api/*`。人在浏览器里读图、看源码、写解读；LLM agent 可以直接调同一套 API 取输入包、写回解读。

## 为什么这样切
它只做「协议 + 安全边界」，内容全部委托出去：图、边、源码来自 `payload`，解读的读写来自 `notes`，「这个名字是不是图上的节点」问 `cut`。所以它依赖这三个模块、只被 `__main__` 的 `serve` 子命令调用。单文件导出不经过它——同一套前端在导出版里由 `web/ds.js` 改读内嵌数据。

路由表在模块 docstring 里（serve.py:1），是读这个文件的最好入口。

## 读法
1. 模块 docstring —— 路由表
2. `main` —— 启动时一次性加载 index 和 trace，挂到 `Handler` 的类属性上（serve.py:231 起）
3. `Handler._in_repo` / `Handler._target` —— 安全边界
4. `Handler.do_GET` —— 按路由顺序往下读；`Handler.do_PUT` —— 写解读
5. `_editor` / `_code_page` —— 两个外围功能

## 关键算法
### 安全边界
- 只监听 127.0.0.1（serve.py:236）。
- 任何文件路径 realpath 之后必须落在仓库内（`Handler._in_repo`），挡住 `../` 和符号链接越界。
- 解读的目标只接受目录树上真实存在的节点名（目录、`目录.*`、文件级模块，由 `cut.is_node` 判断）或总览保留名，防止借 target 写出仓库外的文件；请求体上限 2 MB（serve.py:216），元数据只收 `written_by` / `status` / `confidence` 三个键（serve.py:226）。

### 状态放在类属性上
`BaseHTTPRequestHandler` 每个请求实例化一次，所以仓库、index、trace 这些进程级状态挂在 `Handler` 类上。`/api/graph?open=a,b` 按切面（排序后的 open 集合）缓存成字节串（serve.py:115 起）——同一个切面的布局只依赖 index 和 trace，进程内不会变；切面可以任意组合，所以缓存只留最近的三十来个（serve.py:120）。查询串按「保留空值」解析（serve.py:112）：`?open=` 的意思是「什么都不展开」，和不带 `open` 的「默认切面」不同——多个根的仓库里把最后一个根的框也收起时发的就是它；早先空值被丢掉，页面会跳回整个默认切面。

### 读解读时顺带核对
`GET /api/notes/<target>` 返回解读的同时附上 `notes.verify` 的结果，前端直接显示「引用对不上」的地方。图上的徽标走另一条路：`GET /api/status?ids=`（serve.py:135）一次取回一批节点的状态，不核对内容——展开之后图上有上百个节点，逐个核对太慢。

### 跳编辑器
`/api/outline`（serve.py:161）只返回一个文件的符号大纲，详情面板的文件树展开某个文件时才请求，不必把整份高亮全文传过去。

`/api/open` 找本机的编辑器 CLI（`code -g`、`cursor` …）并以 `file:line` 打开；找不到返回 501，前端照常可用。

## 局限
- index 和 trace 只在启动时加载：重新 `scan` 或重录 trace 之后要重启 serve。解读不受影响（每次请求现读）。
- `/code/<path>` 是全文窗口（`web/viewer.js`）出现之前的纯文本全文页，前端已不再链接它；仍可以当一个能直接贴出去的 `file:line` 链接用。
