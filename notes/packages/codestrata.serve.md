---
written_by: claude-opus-5-5
target: codestrata.serve
kind: package
code_sha: ec065a93e1d95e12
status: draft
refs: serve.py:1@48ec2c0a,serve.py:216@4337f3b1,serve.py:218@3885b904,serve.py:99@5a45895d,serve.py:198@8775e5c5,serve.py:208@e84bd2dc,serve.py:113@2b177846
---

## 是什么
本地部署：一个只用标准库的 HTTP 服务，同时提供前端静态文件（`codestrata/web/`）和 `/api/*`。人在浏览器里读图、看源码、写解读；LLM agent 可以直接调同一套 API 取输入包、写回解读。

## 为什么这样切
它只做「协议 + 安全边界」，内容全部委托出去：图、边、源码来自 `payload`，解读的读写来自 `notes`。所以它依赖这两个模块、只被 `__main__` 的 `serve` 子命令调用。单文件导出不经过它——同一套前端在导出版里由 `web/ds.js` 改读内嵌数据。

路由表在模块 docstring 里（serve.py:1），是读这个文件的最好入口。

## 读法
1. 模块 docstring —— 路由表
2. `main` —— 启动时一次性加载 index 和 trace，挂到 `Handler` 的类属性上（serve.py:216）
3. `Handler._in_repo` / `Handler._target` —— 安全边界
4. `Handler.do_GET` —— 按路由顺序往下读；`Handler.do_PUT` —— 写解读
5. `_editor` / `_code_page` —— 两个外围功能

## 关键算法
### 安全边界
- 只监听 127.0.0.1（serve.py:218）。
- 任何文件路径 realpath 之后必须落在仓库内（serve.py:99），挡住 `../` 和符号链接越界。
- 写解读的目标只接受图上真实存在的包名或总览保留名，防止借 target 写出仓库外的文件；请求体上限 2 MB（serve.py:198），元数据只收 `written_by` / `status` / `confidence` 三个键（serve.py:208）。

### 状态放在类属性上
`BaseHTTPRequestHandler` 每个请求实例化一次，所以仓库、index、trace 这些进程级状态挂在 `Handler` 类上。`/api/graph` 的结果算一次后缓存成字节串（serve.py:113）——布局只依赖 index 和 trace，进程内不会变。

### 读解读时顺带核对
`GET /api/notes/<target>` 返回解读的同时附上 `notes.verify` 的结果，前端直接显示「引用对不上」的地方。

### 跳编辑器
`/api/open` 找本机的编辑器 CLI（`code -g`、`cursor` …）并以 `file:line` 打开；找不到返回 501，前端照常可用。

## 局限
- index 和 trace 只在启动时加载：重新 `scan` 或重录 trace 之后要重启 serve。解读不受影响（每次请求现读）。
- `/code/<path>` 是全文窗口（`web/viewer.js`）出现之前的纯文本全文页，前端已不再链接它；仍可以当一个能直接贴出去的 `file:line` 链接用。
