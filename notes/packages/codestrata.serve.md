---
written_by: claude-opus-5-5
target: codestrata.serve
kind: package
code_sha: e88c168ac22113ec
status: draft
refs: serve.py:129@11ff5f0c,serve.py:155@2486970c,serve.py:160@66db82c5,serve.py:1@48ec2c0a,serve.py:347@ed0daba7,serve.py:377@3885b904,serve.py:332@8775e5c5,serve.py:342@e84bd2dc,serve.py:197@57c6edeb,serve.py:196@dfb1b897,runs.py:586@5028c052,runs.py:59@f0664596,runs.py:673@2da1635f,serve.py:143@1eacf855,serve.py:126@928a6eca,serve.py:203@6956098b,serve.py:202@2d66338f,serve.py:246@68a5b4c7,serve.py:147@354c20e5,serve.py:176@ca5c5410,serve.py:193@753e7dd0,serve.py:355@eae1c1a1,serve.py:356@0d0a1bba,serve.py:177@d664d9ee,serve.py:387@e3d7b1a5,serve.py:391@15bb6b18,serve.py:360@15b8eb16,serve.py:361@96c55968,serve.py:389@b6be9c20,serve.py:372@43062f70,serve.py:215@7f242479,serve.py:223@2b2b2aed,serve.py:261@75ddaff2,serve.py:350@278ad13a,serve.py:210@12773134,serve.py:187@bbaaeff1,serve.py:267@61a4b359,serve.py:273@e66ee7ac,serve.py:235@5e77a01f,serve.py:277@820288c5
---

## 是什么
本地部署：一个只用标准库的 HTTP 服务，同时提供前端静态文件（`codestrata/web/`）和 `/api/*`。人在浏览器里读图、搜名字、看源码、在全文窗口里 Ctrl+点击查引用、写解读、在页面上方的「运行」里切换叠在图上的 run；LLM agent 可以直接调同一套 API 取输入包、写回解读。

## 为什么这样切
它只做「协议 + 安全边界 + 进程内缓存」，内容全部委托出去：图、边、源码、搜索索引、交叉引用来自 `payload`，解读的读写来自 `notes`，「这个名字是不是图上的节点」问 `cut`，run 的列表、解析和映射交给 `runs`（`runs.catalog` / `runs.resolve` / `runs.load` / `runs.file_state`）。所以它依赖这四个模块、只被 `__main__` 的 `serve` 子命令调用。

M4 之前 serve 不直接依赖 runs，只经 `payload.load_hot` 在启动时加载一个 run。现在每个请求都可能换 run，缓存要知道「这个 run 的数据变没变」，serve 就直接读了 runs 目录里的几样东西：`counts.json.gz`、run.json 和 `detail.json` 的 mtime 当缓存键，`detail.json` 用 `runs._read` 读出来交给 `runs.file_state`。这是个取舍：换来的是缓存键简单、不必给 runs 再加一个「版本号」接口；代价是 serve 认得 runs 的三个文件名、还用了 runs 的私有函数，runs 的存储布局一改，serve 这几行（serve.py:129、serve.py:155、serve.py:160）要跟着改。

单文件导出不经过它——同一套前端在导出版里由 `web/ds.js` 改读内嵌数据。这决定了几条路由的形状：搜索索引是「一次给全部名字，前端自己搜」，因为导出版没有服务端，也要能搜；引用列表在导出版里只拼得出一部分；「露出某个模块」和换 run 在导出版里都不可用——导出的是固定切面、固定的那一个 run（或者没有）。

路由表在模块 docstring 里（serve.py:1），是读这个文件的最好入口。

## 读法
1. 模块 docstring —— 路由表
2. `main` —— 加载 index 挂到 `Handler` 的类属性上，清空四份缓存，把 `--hot` 解析成默认 run，数一下 index 落后了几个文件，打印启动横幅（serve.py:347 起）
3. `Handler._hot` / `Handler._runs` —— 请求里的 run 怎么变成 hot 叠加；下拉列表的数据
4. `Handler._in_repo` / `Handler._target` —— 安全边界
5. `Handler.do_GET` —— 按路由顺序往下读；`Handler.do_PUT` —— 写解读
6. `_editor` / `_code_page` —— 两个外围功能

## 关键算法
### 安全边界
- 只监听 127.0.0.1（serve.py:377）。
- 任何文件路径 realpath 之后必须落在仓库内（`Handler._in_repo`），挡住 `../` 和符号链接越界。
- 解读的目标只接受目录树上真实存在的节点名（目录、`目录.*`、文件级模块，由 `cut.is_node` 判断）或总览保留名，防止借 target 写出仓库外的文件；请求体上限 2 MB（serve.py:332），元数据只收 `written_by` / `status` / `confidence` 三个键（serve.py:342）。
- 其余参数都不是路径：`/api/reveal` 的 node 在 `payload.reveal` 里先过 `cut.is_node`，不认识就 404；`/api/refs?t=` 的 t 是交叉引用里的目标键（形如 s:模块:限定名），只拿来查表，查不到（或者还没有 xref.json）就 404；`run=` 只交给 `runs.resolve` 在 run 列表里查，不拼路径。

### 每个请求带自己的 run（M4）
以前 hot 是 `Handler` 上的类属性，一个进程只有一份，换 run 要重启。现在 `/api/graph`、`/api/edge`、`/api/refs`、`/api/pack/<t>` 都接受 `run=`（完整 run id 或 case 名，可加 @阶段；没有或为空 = 只看静态图），在分路由之前统一由 `Handler._hot` 换成 (hot, meta, 缓存键)（serve.py:197）。这三个局部变量在那之前先置成 None（serve.py:196）：不在这张表里的路由读到的是「静态图」，而不是未绑定的变量。前端只维护「当前 run」这一个值，这四类请求都带上它。
- **每次都现解析**：`runs.resolve`（runs.py:586）每个请求都跑一遍（它会把所有 run.json 读一遍）。这样删掉的 run 立刻 404，写 case 名时跟着该 case 最新一次 ok 的 run 走，serve 开着时新录的 run 也用得上。run.json 只有几十个、都很小，这点开销换来不做文件监视。
- **缓存键是 (run id, 阶段, (counts.json.gz 的 mtime, run.json 的 mtime))**（serve.py:129）。counts 是派生数据，只在 `runs merge` 重算时才会被整个替换（先写临时文件再 rename，runs.py:59），mtime 一变就是一份新数据。run.json 进键是后补的：meta 里带着 tags / note，改 tag、备注动的正是 run.json，不进键的话缓存里的 meta 会一直停在加载那一刻。代价是改一次 tag，这个 run 的叠加要重新加载一次，`_graphs` 里这个 run 的图也跟着换一份（它的键里带着这个缓存键）——tag 不常改，换来 meta 永远是新的。命中就直接用，没命中才调 `runs.load`（runs.py:673）现映射到当前 index 上。
- **只留最近加载的 8 个**（serve.py:143）：按插入顺序丢最早的，命中不续命，不是严格 LRU。设计稿估一次加载约 20 ms，浏览器验收时换 run 57 ms、换阶段 109 ms 出图。
- **找不到就 404**：runs 是给命令行写的，出错一律 `SystemExit` 带一句人话（「没有叫 X 的 run 或 case」「没有阶段 Y」）。`_hot` 把它转成 `LookupError`（serve.py:126），`do_GET` 再变成 404 JSON（serve.py:203），请求方拿到的是正常的 404 和那句话。不转的话 `SystemExit` 在处理线程里不会被 socketserver 接住，连接直接断掉，什么也拿不到。counts 还不存在（还在录、或录制中断要 runs merge）也走这条路。
- **输入包的错误是纯文本**：`/api/pack/` 上 run= 不对时给 text/plain 的 404（serve.py:202），和 target 不认识时（serve.py:246）一致。输入包本身是纯文本 Markdown，调它的是 agent 或 curl；页面上取输入包也是不看状态码直接读正文，给 JSON 的话面板里显示的会是一段 {"error": …}，给纯文本就直接是那句话。

### /api/runs：下拉列表
`Handler._runs`（serve.py:147）把 `runs.catalog` 的结果压成下拉列表要的摘要，新的在前，另带 `default`（见下一节）。页面打开下拉时、窗口重新获得焦点时都会请求一次，所以 serve 开着时新录的 run 不用重启就能看到——这是「不做文件监视」的另一半。
- `status` 优先取 `status_shown`：录制进程已经没了但 run.json 还停在 recording 的，显示成「中断」。
- `stale`：录制后改过或删掉的文件数（`changed`）、录制时安装包和仓库不一致的文件数（`mismatch`），由 `runs.file_state` 拿 detail.json 和当前 index 比出来。每个 run 都要读一份 detail.json，所以按 (run id, detail.json 的 mtime) 缓存；index 在进程内不变，不必进键。读不到就是 None（未知），不影响列表其余部分。
- `loadable`：有没有 counts.json.gz（serve.py:176）。没有的行在页面上置灰，免得点了才 404。
- `events`：这个 run 录了时序事件、且整理时没出错（M3），下拉里据此加「时序」标记。
- **runs 目录不在就 503**：`.codestrata/runs` 是软链、指向的盘没挂上时，`runs.runs_dir` 抛 `SystemExit`，`do_GET` 把它变成 503 JSON（serve.py:193）。理由和上面的 404 一样——别让 `SystemExit` 把连接掐断；用 503 是因为这是「暂时不可用、挂上盘就好」，不是「没有这个东西」。页面上这个请求失败时一律当作没有 run、照常显示静态图；页面取数据的小函数（`web/ds.js` 里的 j）会把返回体里的 error 当作错误说明，toast 里看得到是哪个 run 找不到、还是盘没挂上。

### --hot 只决定默认选哪个 run
`--hot REF` 不再是「这个进程叠哪个 run」，只是打开页面、地址里又没记 run 时先选哪个（页面上随时能换）。`main` 仍然先用 `payload.load_hot` 加载一遍（serve.py:355）：写错了 case、阶段不存在、run 还没有计数，都在启动时带着说明退出，而不是开着一个页面才 404。解析出来的「完整 id@阶段」存进 `Handler.default_run`（serve.py:356），经 `/api/runs` 的 `default` 字段交给前端（serve.py:177）。存完整 id 而不是原样的 REF：只写 case 名时，横幅上打印的、页面上选中的是同一次录制，serve 开着时同一个 case 又录了新的也不会悄悄换掉默认。不给 `--hot` 时默认是 None，页面只显示静态图（设计稿的默认做法，不自动选最近的）。

启动横幅多一行 run 总数（serve.py:387）；给了 `--hot` 时再打印默认 run 的 id、阶段、case 和状态（serve.py:391）——partial 说明那次录制不完整，叠上去的计数可能偏少。数 run 时调了 `runs.catalog`（serve.py:360），进程里第一次列 runs 会顺带把老的 trace-*.json 迁进 runs 目录（一次性、幂等），所以现在不带 `--hot` 启动也会迁；runs 目录是断掉的软链时，这里接住 `SystemExit`、打印一行警告、按 0 个 run 接着启动（serve.py:361）——静态图照样能看，请求 run 时再是 503。除此之外 serve 对 runs 只读、不和写的一方加锁：runs 里的文件都是先写临时文件再 rename，读的一方看不到写了一半的。

横幅还会在 index 落后时多一行「scan 之后改过 N 个文件」（serve.py:389）。图和搜索用的是启动时加载的 index，scan 之后改过代码却没重新 scan，页面上的东西就是旧的，而页面本身看不出来——所以在启动时说一声。数法是拿 xref.json 里 scan 记下的每个文件的（大小, mtime_ns）指纹和现在 stat 的结果比（serve.py:372），删掉的也算一个；和 `payload._stale` 判断「这个文件的 Ctrl+点击还能不能用」是同一种比法。只数 scan 见过的文件，之后新加的不算；xref.json 不在或读不出来就不打印——只是提示，算不出来不该拦住启动。

### 状态放在类属性上，四份缓存
`BaseHTTPRequestHandler` 每个请求实例化一次，所以仓库、index、默认 run 这些进程级状态挂在 `Handler` 类上，缓存也是：
- `Handler._graphs`：`/api/graph` 的结果缓存成字节串，键是 (排序后的 open 集合接 `@宽度`, `_hot` 给的缓存键)（serve.py:215）。同一切面换一个 run 叠加就不一样，所以 run 要进键；键里带着 counts 和 run.json 的 mtime，runs merge 或改 tag 之后自然换一份，旧的等着被挤掉。静态图的那一半是 None。超过 32 份就按插入顺序丢最早的（serve.py:223）。
- `Handler._search`：`/api/search-index` 只依赖 index，进程里第一次请求时算一次、存成字节串（serve.py:261）。名字有几万个，所以用紧凑分隔符序列化。
- `Handler._hots`、`Handler._stale`：见上两节。

`ThreadingHTTPServer` 一个请求一个线程。「写入 + 超量就丢最早的」这一步放在 `Handler._lock` 里：两个线程同时 `pop(next(iter(...)))` 可能取到同一个键，后一个会 KeyError。真正的计算（`runs.load`、排版、`runs.file_state`）都在锁外做，两个请求同时没命中时会各算一遍，结果一样，后写的覆盖先写的——宁可偶尔多算一次，也不让一次慢加载堵住别的请求。`main` 里把四份缓存都重置（serve.py:350），免得同一进程里再起一次服务时沿用上一次的结果。

### 按图框宽度排版
`/api/graph` 带 `?w=`：前端把页面上图框的实际宽度带过来，`payload.graph_payload` 按它排版——宽屏上图铺满、少折行，而不是把一张 1180 宽的图放大。宽度按 40px 取整、夹在 700–4000 之间，解析不了就退回 1180（serve.py:210）。取整有两层用处：窗口拖一点点不必重排；宽度是缓存键的一部分，不取整的话每个像素都会占一份缓存。

### 空值有含义
查询串按「保留空值」解析（serve.py:187，`keep_blank_values`）：`?open=` 是「什么都不展开」，和不带 open 的「默认切面」不同（`payload` 里 None 才换成默认切面）。`/api/graph` 和 `/api/reveal` 都靠这个区分：多根仓库里把最后一个根的框也收起时发的就是空的 open；前端调 reveal 时总带着当前切面，当前切面可能是空的——空值若被丢掉，页面会跳回整个默认切面，reveal 也会在默认切面而不是当前切面上算。`run=` 则相反，空值和不带一样，都是静态图。

### 搜索、露出、引用
- `/api/search-index`（serve.py:261）：目录和文件级模块、文件、类 / 函数 / 方法的全部名字，前端自己搜。
- `/api/reveal?node=&open=`（serve.py:267）：搜到的模块可能藏在收起的目录里。它在当前切面上补齐这个节点的全部祖先（节点本身若是目录则保持收起），返回完整的新 open 列表，前端拿它再请求 `/api/graph`。算法在 `cut.open_for`。
- `/api/refs?t=&run=`（serve.py:273）：全文窗口里 Ctrl+点击一个定义，列出引用它的地方——调用在前，其次普通引用、import，每条带那一行原文；方法、类属性另给一组「同名的 .xxx，接收者类型没核实」。带了 run 时把那个 run 的 hot 传进去，给函数附上 runtime 调用次数。反方向（名字 → 定义）不走这里：`/api/file` 返回的全文里已经带着这个文件的全部 xref token。

### 读解读时顺带核对
`GET /api/notes/<target>` 返回解读的同时附上 `notes.verify` 的结果，前端直接显示「引用对不上」的地方。图上的徽标走另一条路：`GET /api/status?ids=`（serve.py:235）一次取回一批节点的状态，不核对内容——展开之后图上有上百个节点，逐个核对太慢。

### 文件树与跳编辑器
`/api/outline`（serve.py:277）只返回一个文件的符号大纲，详情面板的文件树展开某个文件时才请求，不必把整份高亮全文传过去。

`/api/open` 找本机的编辑器 CLI（`code -g`、`cursor` …）并以 `file:line` 打开；找不到返回 501，前端照常可用。

## 局限
- index 只在启动时加载：重新 `scan` 之后，图和搜索索引要重启 serve 才更新（run 不用重启了）。启动时会数一下落后了几个文件并打印（见上），但 serve 开着时再 scan、再改代码，都不会有提示。
- 解读每次请求现读；xref.json 则由 `payload.load_xref` 按修改时间自动换新——所以 scan 过但没重启时，Ctrl+点击和引用用的是新的，图和搜索栏还是旧的。
- 启动时 `--hot` 加载的那一份只用来校验和打印横幅，没有放进 `_hots`：页面第一次请求默认 run 时还会再加载一次。
- 哪些路由要 hot 写在 serve.py:197 那一行里。变量已经先置了 None，以后加一个用叠加的路由而忘了加进这一行，不会再报错，而是悄悄忽略 run=、只给静态图。
- `/code/<path>` 是全文窗口（`web/viewer.js`）出现之前的纯文本全文页，前端已不再链接它；仍可以当一个能直接贴出去的 `file:line` 链接用。

## 不确定
- serve 的 M4 部分没有自动测试（`tests/test_runs.py` 只经 `payload.load_hot` 测加载），靠的是设计稿里记的浏览器验收；后补的 503、输入包的纯文本 404、run.json 进缓存键、启动时的落后提示也都没有测试。
