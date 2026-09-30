---
written_by: claude-opus-5-5
target: codestrata.serve
kind: package
code_sha: 8cd0fdbd71f08b68
status: draft
refs: serve.py:108@17b8be84,serve.py:130@bf8403e9,serve.py:133@32f7a33f,serve.py:425@07a1ffbf,serve.py:142@1f49836e,serve.py:93@b7d00f95,serve.py:147@8f5f8514,serve.py:54@861dd35b,serve.py:122@2d80dad5,viewers.py:107@1e10e9df,serve.py:183@11ff5f0c,serve.py:229@2486970c,serve.py:234@66db82c5,serve.py:1@48ec2c0a,serve.py:437@cba6ca45,serve.py:456@3885b904,serve.py:131@4ebae8bb,serve.py:262@1e726d3d,serve.py:418@1e726d3d,serve.py:388@5dce1214,serve.py:52@c13e2650,codestrata/web/ds.js:140@3bcd3b76,serve.py:85@7cb2e565,serve.py:432@e84bd2dc,serve.py:282@57c6edeb,serve.py:279@dfb1b897,runs.py:608@5028c052,runs.py:72@f0664596,runs.py:759@2da1635f,serve.py:197@1eacf855,serve.py:180@928a6eca,serve.py:288@6956098b,serve.py:287@2d66338f,serve.py:344@68a5b4c7,serve.py:292@b723863d,serve.py:290@5c628b9b,serve.py:289@a8241095,serve.py:296@6cabbe6e,serve.py:293@e61f5a8a,serve.py:311@02c5082f,serve.py:309@afccde76,serve.py:357@7bd2304b,serve.py:276@bb5904d6,serve.py:201@cd0d48b0,serve.py:205@d861ac2f,serve.py:207@2ecfbe21,serve.py:209@6956098b,serve.py:212@4317bbc0,payload.py:153@75936ad2,seq.py:68@bac322fd,serve.py:215@d4c4c86b,seq.py:289@8b63ad18,serve.py:217@73ed4590,serve.py:218@f34a57b6,serve.py:219@518a7dc2,serve.py:221@354c20e5,serve.py:251@ca5c5410,serve.py:249@d751bac7,serve.py:274@f2624b9e,serve.py:445@eae1c1a1,serve.py:446@0d0a1bba,serve.py:252@d664d9ee,serve.py:466@e3d7b1a5,serve.py:470@15bb6b18,serve.py:450@15b8eb16,serve.py:451@96c55968,serve.py:468@b6be9c20,serve.py:455@779db1a4,payload.py:905@5e093a3b,payload.py:904@37992c22,projects.py:104@7a8295ff,payload.py:914@73bb24c9,payload.py:893@e4189233,viewers.py:105@e9169d7b,__main__.py:734@cf7a88fc,serve.py:439@7bdf2201,serve.py:267@28d54b14,codestrata/web/ds.js:105@5430c123,codestrata/web/app.js:685@d0df177e,codestrata/web/ds.js:85@88168368,app.py:155@bfaeb318,codestrata/web/ds.js:2@9113cd27,app.py:171@f4d0423e,app.py:172@aed86b94,app.py:351@2ef86ba0,app.py:103@36d3a057,app.py:111@015270e5,serve.py:321@2b2b2aed,serve.py:359@75ddaff2,serve.py:440@278ad13a,serve.py:304@12773134,serve.py:264@bbaaeff1,serve.py:365@61a4b359,serve.py:371@e66ee7ac,serve.py:333@5e77a01f,serve.py:375@820288c5,serve.py:86@c46bfaf5,tests/test_app.py:465@3f052736
---

## 是什么
本地部署：一个只用标准库的 HTTP 服务，同时提供前端静态文件（`codestrata/web/`）和 `/api/*`。人在浏览器里读图、搜名字、看源码、在全文窗口里 Ctrl+点击查引用、写解读、在页面上方的「运行」里切换叠在图上的 run、再选一个 run 和它对比（M7），对录了时序事件的 run 还能在模块图上按第一次被调用的先后给边上色（「时间顺序」）；LLM agent 可以直接调同一套 API 取输入包、写回解读。也可以由主菜单（`codestrata app`）替你起，这时页面标题前多一个「← 主菜单」链接；发响应、JSON 进出、Host 头检查、「请求是不是我们自己的页面发的」（X-Codestrata 头）、前端静态文件这几样底层（`BaseHandler`、`HEADER`、`asset`）和主菜单共用。

## 为什么这样切
它只做「协议 + 安全边界 + 进程内缓存」，内容全部委托出去：图、边、源码、搜索索引、交叉引用来自 `payload`，解读的读写来自 `notes`，「这个名字是不是图上的节点」问 `cut`，run 的列表、解析和映射交给 `runs`（`runs.catalog` / `runs.resolve` / `runs.load` / `runs.file_state`），「时间顺序」的数据（span 按阶段聚合、按切面映射）交给 `seq`。所以它依赖这五个模块；被 `__main__` 的 `serve` 子命令调用，另外 `app` 从这里 import `BaseHandler`。

`BaseHandler` 和 `asset` 是主菜单（`app.AppHandler`）出现时从 `Handler` 里抽出来的：两个本地服务都要发响应、发 JSON、按 JSON 读请求体、挡 DNS rebinding、给 web/ 下的静态文件，抽出来之后这几样只有一份，尤其是「静态文件只能出自 web/」「Host 头必须是本机这个端口」这两道检查不会各写一遍、各漏一处。它们留在 serve 里、没有另开模块：目前只有这两个用户，依赖方向是 app → serve，serve 不认识 app。几处形状是为了两边都能用：`_send` 多了一个 headers 参数（serve.py:108），serve 自己不用，是主菜单把口令设进 cookie 时回 Location / Set-Cookie 用的；`_host_ok` 要的端口从 `self.server`（绑定的地址）上取（serve.py:130），不另存——两个服务各开在自己的端口上，这道检查不用知道自己在哪个服务里；`_body_json` 不自己回响应，而是返回 (对象, 错误说明)（serve.py:133），怎么回由调用方定——serve 的 PUT（serve.py:425）和主菜单的 POST 都是拿到说明就回 400。「是合法 JSON 但不是对象」也在 `_body_json` 里算错（serve.py:142），调用方拿到的一定是 dict，不用各自再核一遍（抽出来之前 serve 的 PUT 就漏了这一条：body 是 [1] 这种时会在 `body.get` 上抛 AttributeError、连接直接断）；`asset` 只管「这个名字对应哪份内容、什么 Content-Type」，不存在或越出 web/ 就给 None（serve.py:93），`_asset` 再把 None 变成 404（serve.py:147），主菜单直接拿 `_asset("home.html")` 当自己的首页。`HEADER`（X-Codestrata，serve.py:54）和查它的 `_from_page`（serve.py:122）是后来挪进来的：这个头原本是主菜单自己的常量、只护着主菜单的 /api/；serve 的 `/api/open` 也要认它之后，常量和检查都放到了这里，主菜单的 `AppHandler._guard` 改调 `_from_page`（测试也改用 serve 的 `HEADER`），两边认的是同一个名字、同一个值，不会一边改了另一边没跟上。

主菜单打开的图还是这个一个进程服务一个仓库的 serve，由 `viewers` 起成子进程、带上 `--home`（viewers.py:107），serve 不用为此改结构：`Handler` 的状态都在类属性上（见下面「状态放在类属性上」），一个进程本来就只服务一个仓库，index 也只在启动时读，重新扫描之后由主菜单重启它。serve 这边只多了一个字符串：`--home` 给的地址存进 `Handler.home`，页面经 `/api/app` 取回去（见下面「从主菜单打开」）。

M4 之前 serve 不直接依赖 runs，只经 `payload.load_hot` 在启动时加载一个 run。现在每个请求都可能换 run，缓存要知道「这个 run 的数据变没变」，serve 就直接读了 runs 目录里的几样东西：`counts.json.gz`、run.json 和 `detail.json` 的 mtime 当缓存键，`detail.json` 用 `runs._read` 读出来交给 `runs.file_state`。这是个取舍：换来的是缓存键简单、不必给 runs 再加一个「版本号」接口；代价是 serve 认得 runs 的三个文件名、还用了 runs 的私有函数，runs 的存储布局一改，serve 这几行（serve.py:183、serve.py:229、serve.py:234）要跟着改。

单文件导出不经过它——同一套前端在导出版里由 `web/ds.js` 改读内嵌数据。这决定了几条路由的形状：搜索索引是「一次给全部名字，前端自己搜」，因为导出版没有服务端，也要能搜；引用列表在导出版里只拼得出一部分；「露出某个模块」、「时间顺序」在导出版里都不可用——导出的是固定切面，导出版的 ds.js 里取时序数据的 seqEdges 直接拒绝。换 run 和对比在导出版里只剩导出时定下的那些（M7）：graph --hot A --hot B 带上的几个 run 之间能切换，但别的 run 只带了切面上的节点、边次数，边详情的调用明细只有主 run 的；对比是 --compare 定好的那一对，不能换。serve 这边没有这些限制，因为它每个请求现解析、现算。

路由表在模块 docstring 里（serve.py:1），是读这个文件的最好入口；`/api/seq/edges` 也在里面。早先 M5 时序图的三条接口（/api/seq、/api/seq/overview、/api/seq/find）已随时序图去掉，请求它们现在一路落到最后的静态文件、给 404。

## 读法
1. 模块 docstring —— 路由表
2. `main` —— 加载 index 挂到 `Handler` 的类属性上（`--home` 也挂在这里），清空四份缓存，把 `--hot` 解析成默认 run，用 `payload.index_lag` 数一下 index 落后了几个文件，打印启动横幅（serve.py:437 起）
3. `Handler._hot` / `Handler._runs` —— 请求里的 run（和对比用的 cmp，同一个函数换一个参数名）怎么变成 hot 叠加；下拉列表的数据
4. `Handler._seq` —— /api/seq/edges（模块图的「时间顺序」）。和 `_hot` 对照着读：同样每次现解析 run、同样把 `SystemExit` 变成 404，但不经过 hot 叠加
5. `Handler._in_repo` / `Handler._target` —— 安全边界
6. `Handler.do_GET` —— 按路由顺序往下读；`Handler.do_PUT` —— 写解读
7. `asset` / `BaseHandler` —— `do_GET` / `do_PUT` 第一步的 Host 检查、`/api/open` 的 X-Codestrata 检查、`do_GET` 最后一行给静态文件、`do_PUT` 读请求体用到的底层，和主菜单共用；改这里要连 `app` 一起看
8. `_editor` / `_code_page` —— 两个外围功能

## 关键算法
### 安全边界
- 只监听 127.0.0.1（serve.py:456）。
- Host 头必须是 `127.0.0.1:端口` 或 `localhost:端口`（`BaseHandler._host_ok`，serve.py:131），`do_GET`、`do_PUT` 第一步就查，不对给 403 bad host（serve.py:262、serve.py:418）。防的是 DNS rebinding：别的网站把自己的域名解析到 127.0.0.1，浏览器就会把那个网页的请求发到这里，而且按同源算——能读返回（仓库源码）、能 PUT 写解读、能调 `/api/open` 开编辑器。这时 Host 头还是那个域名，一比就露了。浏览器、curl、agent 按 `127.0.0.1:端口` 访问时带的就是这个 Host，不受影响。这道检查主菜单也走（`AppHandler._guard`）。
- **会在本机做事的 GET 要带 `X-Codestrata: 1`**：目前只有 `/api/open`（它会起一个编辑器进程），不带就 403（serve.py:388）。Host 检查挡不住的是「普通的别的网页」：它的 Host 是对的，用 `<img src="http://127.0.0.1:8900/api/open?f=…">` 就能发出一个 GET，读不到返回也无所谓，副作用已经发生了。自定义请求头跨源设不了——要先过 CORS 预检，serve 不回 CORS 头、也没有 do_OPTIONS——所以带着这个头的请求一定出自我们自己的页面（`HEADER` 旁的注释，serve.py:52）。检查排在解析参数、找文件、找编辑器之前：缺头的请求什么都不碰。其余 GET 只读，别的网页读不到返回，不必加；PUT 跨源本来就要预检，也不必加。页面这边有两处发这个请求，都带上了头：ds.js 的 openEditor（codestrata/web/ds.js:140），和 `_code_page` 里「在编辑器打开」的 onclick（serve.py:85，把 `HEADER` 拼进 fetch 的 headers）——后者原来是裸的 `fetch(this.href)`，加了检查之后不跟着改就永远 403，测试专门断言代码页里有这个头。
- 任何文件路径 realpath 之后必须落在仓库内（`Handler._in_repo`），挡住 `../` 和符号链接越界。前端静态文件同理，resolve 之后必须落在 web/ 下（serve.py:93）；这道检查在 `asset` 里，主菜单也走它。
- 解读的目标只接受目录树上真实存在的节点名（目录、`目录.*`、文件级模块，由 `cut.is_node` 判断）或总览保留名，防止借 target 写出仓库外的文件；请求体上限 2 MB（`BaseHandler._body_json` 的默认值，serve.py:133），元数据只收 `written_by` / `status` / `confidence` 三个键（serve.py:432）。
- 其余参数都不是路径：`/api/reveal` 的 node 在 `payload.reveal` 里先过 `cut.is_node`，不认识就 404；`/api/refs?t=` 的 t 是交叉引用里的目标键（形如 s:模块:限定名），只拿来查表，查不到（或者还没有 xref.json）就 404；run= 和 cmp= 都只交给 `runs.resolve` 在 run 列表里查，不拼路径。`/api/seq/edges` 的 open 经 `payload._norm_open` 只留 `cut.is_node` 认得的名字。

### 每个请求带自己的 run（M4）
以前 hot 是 `Handler` 上的类属性，一个进程只有一份，换 run 要重启。现在 `/api/graph`、`/api/edge`、`/api/refs`、`/api/pack/<t>` 都接受 `run=`（完整 run id 或 case 名，可加 @阶段，或 @t=起-止——时间轴上拖出来的一段时间，缓存键里「阶段」那一项就是这个字符串，每个时间段各占一格；没有或为空 = 只看静态图），在分路由之前统一由 `Handler._hot` 换成 (hot, meta, 缓存键)（serve.py:282）。这三个局部变量在那之前先置成 None（serve.py:279；对比用的 B 那几个在下一行，同理）：不在这张表里的路由读到的是「静态图」，而不是未绑定的变量。前端只维护「当前 run」这一个值，这四类请求都带上它（/api/seq/edges 也带，但在这一段之前就分走了，见下面「时间顺序的接口」）。
- **每次都现解析**：`runs.resolve`（runs.py:608）每个请求都跑一遍（它会把所有 run.json 读一遍）。这样删掉的 run 立刻 404，写 case 名时跟着该 case 最新一次 ok 的 run 走，serve 开着时新录的 run 也用得上。run.json 只有几十个、都很小，这点开销换来不做文件监视。
- **缓存键是 (run id, 阶段, (counts.json.gz 的 mtime, run.json 的 mtime))**（serve.py:183）。counts 是派生数据，只在 `runs merge` 重算时才会被整个替换（先写临时文件再 rename，runs.py:72），mtime 一变就是一份新数据。run.json 进键是后补的：meta 里带着 tags / note，改 tag、备注动的正是 run.json，不进键的话缓存里的 meta 会一直停在加载那一刻。代价是改一次 tag，这个 run 的叠加要重新加载一次，`_graphs` 里这个 run 的图也跟着换一份（它的键里带着这个缓存键）——tag 不常改，换来 meta 永远是新的。命中就直接用，没命中才调 `runs.load`（runs.py:759）现映射到当前 index 上。
- **只留最近加载的 8 个**（serve.py:197）：按插入顺序丢最早的，命中不续命，不是严格 LRU。设计稿估一次加载约 20 ms，浏览器验收时换 run 57 ms、换阶段 109 ms 出图。
- **找不到就 404**：runs 是给命令行写的，出错一律 `SystemExit` 带一句人话（「没有叫 X 的 run 或 case」「没有阶段 Y」）。`_hot` 把它转成 `LookupError`（serve.py:180），`do_GET` 再变成 404 JSON（serve.py:288），请求方拿到的是正常的 404 和那句话。不转的话 `SystemExit` 在处理线程里不会被 socketserver 接住，连接直接断掉，什么也拿不到。counts 还不存在（还在录、或录制中断要 runs merge）也走这条路。
- **输入包的错误是纯文本**：`/api/pack/` 上 run= 不对时给 text/plain 的 404（serve.py:287），和 target 不认识时（serve.py:344）一致。输入包本身是纯文本 Markdown，调它的是 agent 或 curl；页面上取输入包也是不看状态码直接读正文，给 JSON 的话面板里显示的会是一段 {"error": …}，给纯文本就直接是那句话。

### 对比的另一个 run：cmp=（M7）
`/api/graph` 和 `/api/edge` 另接受 cmp=（写法和 run= 一样），解析它的还是 `Handler._hot`：函数多了一个参数，说读哪个查询参数，解析 B 时传的是 "cmp"（serve.py:292）。所以 B 和 A 走同一套：每次现解析、同一份 `_hots` 缓存（对比时一张图占两格）、缓存键同样带 counts 和 run.json 的 mtime，不必为 B 另写一遍。只有 A 解析出东西时才看 cmp（serve.py:290）：没有 A 就谈不上对比，run= 为空时带着的 cmp= 不报错也不提示；空的 cmp= 和不带一样，是「不对比」；refs 和输入包不看 cmp。
- **B 出问题不让请求失败**（serve.py:289 的注释）：B 找不到（删了、名字写错、还没有计数，都是 `_hot` 抛的 `LookupError`，serve.py:296），或者解析出来和 A 是同一个 run 的同一个阶段（serve.py:293，比的是两个缓存键的前两项：run id 和阶段），都只叠 A，图上多一个 cmpError 字段说明原因。A 找不到仍是 404——A 是这张图的内容，B 只是附加的一层。给 404 的话整张图都出不来，前端会把它当作这次换切面失败。前端从地址里读 cmp 时已经按 `/api/runs` 核过一遍（app.js 里找不到、没计数、和 A 是同一个的都不带上），serve 这边是第二道：列表取回之后 run 被删了、case 名在列表里认的和解析出来的不是同一次录制（重录之后 case 名跟着最新的走，也可能正好解析成 A 自己），还有 agent / curl 手写的请求。前端收到 cmpError 就把地址里的 cmp 清掉、弹一条提示，照常显示 A。同一个 run 同一个阶段也拦下，是因为自己和自己比，每个节点、每条边都是「两边都有」，看上去比过了，其实什么也没比。同一个 run 的两个阶段（比如 startup 对 serving）不算同一个，照常比。
- **带 cmpError 的图不进缓存**（serve.py:311）：这时 B 的缓存键是 None，缓存键和「只叠 A、不对比」的请求一模一样，存进去的话之后正常请求 A 的图会拿到带着 cmpError 的旧字节，页面每次都再弹一次提示。所以这一支每次现算、不写缓存；前端收到后就清掉了 cmp，同一个错误一般只算一次。
- **图的缓存键多一项 B 的缓存键**（serve.py:309），不对比时是 None。和 A 一样，B 的 counts 重算、改了 tag 都会自然换一份。返回的 cmp 块（节点、边上的 [A, B] 次数，B 的 ref_b 和精简的 meta）由 `payload.graph_payload` 的 hot_b 参数算，serve 只负责传进去。
- **边详情一律走 `payload.edge_compare`**（serve.py:357）：没有 B 时它原样返回 `payload.edge_detail` 的结果，形状和以前一样，serve 这边不用分支；有 B 时两个 run 各算一遍再按符号合，每项带 calls_b，只有 B 调到的补在后面。/api/edge 上 B 出问题同样只给 A 的明细，但不带 cmpError——提示在图那边给过了，前端那时已经把 cmp 清掉，之后取边详情不会再带它。

### 时间顺序的接口：/api/seq/edges
`/api/seq/edges` 在 `do_GET` 里排在上面那段 hot 之前（serve.py:276），整个交给 `Handler._seq`（serve.py:201），它只调 `seq.edge_times`。不走 `_hot`，是因为它不用计数叠加：要的是 run 目录（span 在 run 的 events/spans/ 下）和 run.json 里的阶段表，也不要求 counts.json.gz 已经在。结果不进 `_hots` / `_graphs`，缓存在 `seq` 模块里（整个 run 按阶段聚合的结果、每个切面 + 阶段的结果、按 (index, 切面) 的映射）。早先这里是 M5 时序图的三个接口（取一屏、时间刷、「在时序图里看」），带着 t0 / t1 / max / fold / after 几个数字参数，还读 detail.json 画进程；随时序图一起去掉了。
- **run 必填，缺了 400**（serve.py:205）。模块图上 run= 为空是「只看静态图」，边的时间没有静态版本，空值没有可退回的意思，所以算请求错了，而不是「没有这个东西」的 404。
- **解析失败 404**：和 `_hot` 一样每次现调 `runs.resolve`（serve.py:207），写错 run / 阶段时的 `SystemExit` 就地变成 404 JSON（serve.py:209），不绕 `LookupError`。runs 目录是断掉的软链时也落在这里，给的是 404 而不是 `/api/runs` 那样的 503——和 `_hot` 一致。@t=起-止 写错（写不成两个整数、终点不大于起点）也是 `runs.resolve` 的 `SystemExit`，同样 404，说明里写着该怎么写。阶段在、但 run.json 里没有它的时刻（老 run）时，`edge_times` 抛 `LookupError`，同样 404 并说明「不知道它从什么时候开始」。
- **切面规范化**：open 的解析和 `/api/graph` 一样（没带 = 默认切面，空值 = 什么都不展开），之后再过一遍 `payload._norm_open` 并排序（serve.py:212）：没带时换成 scan 算的默认切面，带了就丢掉 `cut.is_node` 不认的名字。`payload.graph_payload` 里用的是同一个函数（payload.py:153），所以同一组 open 上按时间排的边和模块图上的边落在同一套节点上——前端按边的 a|b 对颜色靠的就是这个。排好序还让 `seq` 里按切面缓存的映射（seq.py:68）和结果对「没带 open」和「把默认切面逐个列出来」命中同一份。
- **没录事件 → 404**（serve.py:215）：`edge_times` 发现没有 span 的 index 时抛 `LookupError`，文字带着怎么录——「这个 run 没有录时序事件（codestrata trace --events）」（seq.py:289），serve 原样返回。index 在而 key 表或某个块不在是 `FileNotFoundError`，serve 分不清是哪一种，所以换成的固定文字两种都说：「这个 run 没有录时序事件（codestrata trace --events），或者 span 没整理好（runs merge 重来）」（serve.py:217）——只说「没录」的话，对录了、只是 span 缺块的 run 是错的指点。页面上「时间顺序」开关只在 `/api/runs` 说这个 run 有事件时才出，所以这条 404 主要是给在地址里手写 run 的人和 agent 看的。
- **span 文件坏了 → 500**（serve.py:218）：块不是合法 gzip（头不对、CRC 不对）、解压后不是合法 JSON / UTF-8，是 `OSError` / `ValueError`，给 500 JSON，文字由 `seq.unreadable` 拼（serve.py:219）：异常类型和原话，加上 codestrata runs <repo> merge <run id> 重建的提示——span 是从原始事件日志派生的，merge 能重来。`runs.load` 按时间段数次数时读不出 span，用的也是这一句，只是那边是 `SystemExit`，经 `_hot` 在图、边详情这些接口上成了 404。不接的话异常漏进处理线程，连接直接断，页面上只看得到「请求失败」。用 500 而不是 404：run 在、事件也录了，坏的是服务端的数据。这一支排在上一支后面是必须的：`FileNotFoundError` 也是 `OSError`，顺序反过来缺文件就都成了 500。

### /api/runs：下拉列表
`Handler._runs`（serve.py:221）把 `runs.catalog` 的结果压成下拉列表要的摘要，新的在前，另带 `default`（见下一节）。页面打开下拉时、窗口重新获得焦点时都会请求一次，所以 serve 开着时新录的 run 不用重启就能看到——这是「不做文件监视」的另一半。
- `status` 优先取 `status_shown`：录制进程已经没了但 run.json 还停在 recording 的，显示成「中断」。
- `stale`：录制后改过或删掉的文件数（`changed`）、录制时安装包和仓库不一致的文件数（`mismatch`），由 `runs.file_state` 拿 detail.json 和当前 index 比出来。每个 run 都要读一份 detail.json，所以按 (run id, detail.json 的 mtime) 缓存；index 在进程内不变，不必进键。读不到就是 None（未知），不影响列表其余部分。
- `loadable`：有没有 counts.json.gz（serve.py:251）。没有的行在页面上置灰，免得点了才 404。
- `events`：这个 run 录了时序事件、且整理时没出错（M3），下拉里据此加「时序」标记；它还决定模块图上出不出「时间顺序」开关（早先决定的是「时序图」按钮和「在时序图里看」）。
- `events_error`：录了时序事件、但整理成 span 时失败了（run.json 的 events 里带着 error）。这种 run 的 `events` 是 false，只有这一个字段时页面分不出「没录」和「录了没整理好」，按钮的提示只能说「录的时候加 --events」——对它是错的指点。多给的这个布尔值（serve.py:249）原本让「时序图」按钮的提示改说「整理失败了：codestrata runs <repo> merge <id> 重来」；时序图去掉之后页面上没人读它了（「时间顺序」开关对这种 run 直接不出、不说原因），字段还留着。
- **runs 目录不在就 503**：`.codestrata/runs` 是软链、指向的盘没挂上时，`runs.runs_dir` 抛 `SystemExit`，`do_GET` 把它变成 503 JSON（serve.py:274）。理由和上面的 404 一样——别让 `SystemExit` 把连接掐断；用 503 是因为这是「暂时不可用、挂上盘就好」，不是「没有这个东西」。页面上这个请求失败时一律当作没有 run、照常显示静态图；页面取数据的小函数（`web/ds.js` 里的 j）会把返回体里的 error 当作错误说明，toast 里看得到是哪个 run 找不到、还是盘没挂上。

### --hot 只决定默认选哪个 run
`--hot REF` 不再是「这个进程叠哪个 run」，只是打开页面、地址里又没记 run 时先选哪个（页面上随时能换）。`main` 仍然先用 `payload.load_hot` 加载一遍（serve.py:445）：写错了 case、阶段不存在、run 还没有计数，都在启动时带着说明退出，而不是开着一个页面才 404。解析出来的「完整 id@阶段」存进 `Handler.default_run`（serve.py:446），经 `/api/runs` 的 `default` 字段交给前端（serve.py:252）。存完整 id 而不是原样的 REF：只写 case 名时，横幅上打印的、页面上选中的是同一次录制，serve 开着时同一个 case 又录了新的也不会悄悄换掉默认。不给 `--hot` 时默认是 None，页面只显示静态图（设计稿的默认做法，不自动选最近的）。

启动横幅多一行 run 总数（serve.py:466）；给了 `--hot` 时再打印默认 run 的 id、阶段、case 和状态（serve.py:470）——partial 说明那次录制不完整，叠上去的计数可能偏少。数 run 时调了 `runs.catalog`（serve.py:450），进程里第一次列 runs 会顺带把老的 trace-*.json 迁进 runs 目录（一次性、幂等），所以现在不带 `--hot` 启动也会迁；runs 目录是断掉的软链时，这里接住 `SystemExit`、打印一行警告、按 0 个 run 接着启动（serve.py:451）——静态图照样能看，请求 run 时再是 503。除此之外 serve 对 runs 只读、不和写的一方加锁：runs 里的文件都是先写临时文件再 rename，读的一方看不到写了一半的。

横幅还会在 index 落后时多一行「scan 之后改过 N 个文件」（serve.py:468）。图和搜索用的是启动时加载的 index，scan 之后改过代码却没重新 scan，页面上的东西就是旧的，而页面本身看不出来——所以在启动时说一声。数这个数的是 `payload.index_lag`（serve.py:455）：拿 xref.json 里 scan 记下的每个文件的（大小, mtime_ns）指纹和现在 stat 的结果比（payload.py:905），删掉的也算一个（payload.py:904）；逐个文件比的是 `payload._changed`，`payload._stale` 判断「这个文件的 Ctrl+点击还能不能用」调的也是它，两处是同一份比法，不会各写一遍。它原来是写在 `main` 里的一段，挪进 `payload` 是因为主菜单的项目卡片也要显示同一个数（projects.py:104），两处不该各数各的。只数 scan 见过的文件，之后新加的不算；整个计算都在一个 try 里，出任何异常都当 0（payload.py:914）：xref.json 不在、读不出来、格式不对，都是不打印这一行——只是提示，算不出来不该拦住启动。指纹表走 `payload._xref_fp` 自己按（路径, mtime）缓存的一小份（payload.py:893），不占 `load_xref` 那一个槽：主菜单一次要数好几个仓库，共用单槽会互相挤掉。

### 从主菜单打开：--home 和 /api/app
主菜单为每个打开的项目起一个 `codestrata serve <repo> --port <空闲端口> --home <主菜单地址>`（viewers.py:107）。命令行由 `self_command` 拼：当前这个 Python 的 `-m codestrata`，codestrata 装在哪个环境里，serve 就在哪个环境里跑。serve 打印的启动横幅和启动时的报错（比如没 scan 过时的「先跑 codestrata scan」）进的是主菜单给这个仓库的日志（viewers.py:105），起不来时主菜单把末尾给页面看——serve 的启动报错本来就是给人看的一句话，经这条路照样能用，serve 不用为主菜单另报一遍。`--home` 在命令行帮助里是藏起来的（__main__.py:734）：它只给主菜单用，人直接跑 serve 不带它。
- `main` 把它存进 `Handler.home`（serve.py:439），`/api/app` 原样返回 {home}（serve.py:267），排在所有路由最前面，不看 run、不碰 index。页面第一次画标题时经 ds.js 里的 home() 去取（codestrata/web/ds.js:105），不是 null 就在标题前放「← 主菜单」；只问这一次（codestrata/web/app.js:685）——标题每换一次切面都会重画，直接 serve 的 home 是 null、链接永远放不上，要是按「链接放上了就不再取」来判断，每换一次切面都白请求一次。直接 serve 的页面和以前一样。导出版的 ds.js 直接给 null（codestrata/web/ds.js:85），和导出版里其他取不到的东西一个做法。
- 页面可能不在根上。主菜单把自己起的图服务转发到 /v/<端口>/ 下（`AppHandler._view`，app.py:155），远程时 ssh 只转主菜单一个端口就够。为此 ds.js 的 live 模式一律用相对地址 `api/…`（codestrata/web/ds.js:2 的注释）：直接 serve 时页面在 `/`，经主菜单时在 /v/<端口>/，同一份前端都对。serve 自己不知道被转发：主菜单连 127.0.0.1:端口，把 Host 改写成这个（app.py:171），Content-Type 和 `HEADER` 原样带过去（app.py:172），所以 Host 检查和 `/api/open` 的头检查照旧在这边做，主菜单那边另外要口令 cookie。
- 地址放在接口里而不是写进 index.html：静态文件是原样给出的（`asset` 不改写内容），页面要的数据都经 ds.js 取，回主菜单的链接也走这条路。
- 返回的只是主菜单的首页地址（`http://127.0.0.1:端口/`，app.py:351），不带主菜单的口令：serve 本身没有鉴权，本机的进程谁都能读这个接口。点过去能直接进主菜单，靠的是这个浏览器里主菜单自己设好的 cookie；没有的话主菜单给的是「请用启动时打印的链接打开」那一页。
- 主菜单扫描成功后会在原端口重启这个 serve（app.py:103），让它读到新的 index；开着的标签刷新一下就是新的。重启算在扫描任务里（任务标成结束之前做），页面上看到扫描结束时 serve 已经换好了；重启不成，原因写进这个扫描任务的输出（app.py:111）。对 serve 来说这就是一次普通的重新启动，四份缓存本来就是随进程清空的。

### 状态放在类属性上，四份缓存
`BaseHTTPRequestHandler` 每个请求实例化一次，所以仓库、index、默认 run、主菜单地址这些进程级状态挂在 `Handler` 类上，缓存也是：
- `Handler._graphs`：`/api/graph` 的结果缓存成字节串，键是 (排序后的 open 集合接 `@宽度`, A 的缓存键, B 的缓存键)（serve.py:309）。同一切面换一个 run 叠加、换一个对比的 run 就不一样，所以两个 run 都要进键；键里带着 counts 和 run.json 的 mtime，runs merge 或改 tag 之后自然换一份，旧的等着被挤掉。静态图的 A 那一项是 None，不对比时 B 那一项是 None；带 cmpError 的图不进来（见上）。超过 32 份就按插入顺序丢最早的（serve.py:321）。
- `Handler._search`：`/api/search-index` 只依赖 index，进程里第一次请求时算一次、存成字节串（serve.py:359）。名字有几万个，所以用紧凑分隔符序列化。
- `Handler._hots`、`Handler._stale`：见上面 run 和 /api/runs 两节；对比的 B 也存在 `_hots` 里。

「时间顺序」的缓存不在这四份里：`seq` 的几份是模块级的，`main` 不重置它们；它们的键里带着 span index 的 mtime，映射的缓存连 idx 对象一起存、取的时候核对是不是同一个。但每个切面 + 阶段的结果那一份（`seq` 的 `_EDGES`）键里没有 scan 的 index（见「不确定」）。

`ThreadingHTTPServer` 一个请求一个线程。「写入 + 超量就丢最早的」这一步放在 `Handler._lock` 里：两个线程同时 `pop(next(iter(...)))` 可能取到同一个键，后一个会 KeyError。真正的计算（`runs.load`、排版、`runs.file_state`）都在锁外做，两个请求同时没命中时会各算一遍，结果一样，后写的覆盖先写的——宁可偶尔多算一次，也不让一次慢加载堵住别的请求。`main` 里把四份缓存都重置（serve.py:440），免得同一进程里再起一次服务时沿用上一次的结果。

### 按图框宽度排版
`/api/graph` 带 `?w=`：前端把页面上图框的实际宽度带过来，`payload.graph_payload` 按它排版——宽屏上图铺满、少折行，而不是把一张 1180 宽的图放大。宽度按 40px 取整、夹在 700–4000 之间，解析不了就退回 1180（serve.py:304）。取整有两层用处：窗口拖一点点不必重排；宽度是缓存键的一部分，不取整的话每个像素都会占一份缓存。

### 空值有含义
查询串按「保留空值」解析（serve.py:264，`keep_blank_values`）：`?open=` 是「什么都不展开」，和不带 open 的「默认切面」不同（`payload` 里 None 才换成默认切面）。`/api/graph`、`/api/reveal` 和 `/api/seq/edges` 都靠这个区分：多根仓库里把最后一个根的框也收起时发的就是空的 open；前端调 reveal、取边的时间时总带着当前切面，当前切面可能是空的——空值若被丢掉，页面会跳回整个默认切面，reveal 也会在默认切面而不是当前切面上算，按时间排的边也会和图上的对不上。`run=` 则相反，空值和不带一样：模块图上是静态图，/api/seq/edges 上是 400；cmp= 也是空值和不带一样，都是不对比。

### 搜索、露出、引用
- `/api/search-index`（serve.py:359）：目录和文件级模块、文件、类 / 函数 / 方法的全部名字，前端自己搜。
- `/api/reveal?node=&open=`（serve.py:365）：搜到的模块可能藏在收起的目录里。它在当前切面上补齐这个节点的全部祖先（节点本身若是目录则保持收起），返回完整的新 open 列表，前端拿它再请求 `/api/graph`。算法在 `cut.open_for`。
- `/api/refs?t=&run=`（serve.py:371）：全文窗口里 Ctrl+点击一个定义，列出引用它的地方——调用在前，其次普通引用、import，每条带那一行原文；方法、类属性另给一组「同名的 .xxx，接收者类型没核实」。带了 run 时把那个 run 的 hot 传进去，给函数附上 runtime 调用次数。反方向（名字 → 定义）不走这里：`/api/file` 返回的全文里已经带着这个文件的全部 xref token。

### 读解读时顺带核对
`GET /api/notes/<target>` 返回解读的同时附上 `notes.verify` 的结果，前端直接显示「引用对不上」的地方。图上的徽标走另一条路：`GET /api/status?ids=`（serve.py:333）一次取回一批节点的状态，不核对内容——展开之后图上有上百个节点，逐个核对太慢。

### 文件树与跳编辑器
`/api/outline`（serve.py:375）只返回一个文件的符号大纲，详情面板的文件树展开某个文件时才请求，不必把整份高亮全文传过去。

`/api/open` 先认 X-Codestrata 头（见「安全边界」，缺了 403），再找本机的编辑器 CLI（`code -g`、`cursor` …）并以 `file:line` 打开；找不到返回 501，前端照常可用。

## 局限
- index 只在启动时加载：重新 `scan` 之后，图和搜索索引要重启 serve 才更新（run 不用重启了）。启动时会数一下落后了几个文件并打印（见上），但 serve 开着时再 scan、再改代码，都不会有提示。从主菜单扫描的，主菜单会替你重启（见「从主菜单打开」）；命令行上自己 scan 的仍要自己重启。
- Host 检查、X-Codestrata 头两边共用；口令 cookie 只有主菜单有。serve 不管是主菜单起的还是命令行起的都没有鉴权：本机的任何进程都能读源码、`PUT /api/notes` 写解读、自己带上头调 `/api/open` 开编辑器——这个头挡的是浏览器里的别的网页，不是本机进程。别的网页（不走 DNS rebinding）发来的请求 Host 是对的：它读不到返回（serve 不回 CORS 头），发不出 PUT（跨源 PUT 要先 OPTIONS 预检，serve 没有 do_OPTIONS，预检拿到 501），`/api/open` 缺头给 403；剩下能送到的只有只读的 GET。
- Host 检查按「主机:端口」整串比：`serve --port 80` 时浏览器发的 Host 不带端口（只有 127.0.0.1），会被当成不对的 Host 挡成 403；用 127.0.0.1 / localhost 以外的本机名访问也一样。80 一般要 root 才开得了，实际不大会碰到。
- 启动时数落后文件要把 xref.json 整个解析一遍、只留下指纹表，不顺带填 `load_xref` 的缓存：进程里第一次 Ctrl+点击、查引用时还要再解析一遍。
- 解读每次请求现读；xref.json 则由 `payload.load_xref` 按修改时间自动换新——所以 scan 过但没重启时，Ctrl+点击和引用用的是新的，图和搜索栏还是旧的。
- 启动时 `--hot` 加载的那一份只用来校验和打印横幅，没有放进 `_hots`：页面第一次请求默认 run 时还会再加载一次。
- 哪些路由要 hot 写在 serve.py:282 那一行里，哪些还看 cmp 写在 serve.py:290。变量已经先置了 None，以后加一个用叠加的路由而忘了加进这一行，不会再报错，而是悄悄忽略 run=（或 cmp=）、只给静态图（或不对比）。
- 带 cmpError 的图每次整张现算，没有先去 `_graphs` 里拿同一个键下现成的「只叠 A」的字节再补上这个字段。前端收到一次就清掉 cmp，所以只在手写请求反复带错 cmp 时才多算。
- B 还没有计数时，说明是「对比的 run 找不到了：run … 还没有计数（…）」：前半句是 serve 固定加的前缀，对这种情况不准，后半句才说清原因。
- 一个 run 第一次取边的时间时，`seq` 要把整个 run 的 span 解压、读一遍（大 run 两秒多），这个请求的处理线程一直占着；同一个 run 同时来的请求等同一份结果，不重复解压。
- span 块坏法里还有两种漏网：截断的 gzip 抛 EOFError、中间字节坏了可能抛 `zlib.error`，都不是 `OSError` / `ValueError`，仍是处理线程里未处理的异常、连接直接断（用 `gzip.decompress` 对截断、翻转字节的数据试过）。keys.json 缺字段的 KeyError 是 `LookupError`，会走 404、说明只有一个键名。runs 里的文件都是原子写的，正常不会遇到。
- 导出的单文件没有「时间顺序」：设计稿 §8 定了事件一律不嵌入导出文件，边的时间要 serve 现算。
- `/code/<path>` 是全文窗口（`web/viewer.js`）出现之前的纯文本全文页，前端已不再链接它；仍可以当一个能直接贴出去的 `file:line` 链接用。它里面的「在编辑器打开」「← 回到图」是绝对地址（serve.py:85、serve.py:86），经主菜单的 /v/<端口>/ 打开时会指到主菜单上，点了不对。

## 不确定
- 「时间顺序」的接口有一个经真 serve 进程的测试（`tests/test_runs.py` 的 test_edge_times_api）：录了事件的 run 给出每条边的时间且 first 不晚于 last、没录事件的 run 404 且说明里有 --events、@不存在的阶段 404、@t=0-总长 给的边和整个 run 的一样、写反了的时间段（@t=9-3）404 且说明里有「起点」、`/api/graph` 叠时间段时 hotMeta 的 window 就是那一段、不带 run 400、去掉的三条 /api/seq* 都是 404，以及 `/api/runs` 的 `events` 字段。没测到的：open 的规范化、span 坏了的 500、`events_error` 字段。
- `seq` 里每个切面 + 阶段的结果按 (span 的键, 切面, 阶段) 缓存，键里没有 scan 的 index：同一进程里换一份 index 再起服务，同一个 run 和切面会拿到按旧 index 归出来的结果。主菜单重启 serve 是新进程，碰不到；只有测试这种在一个进程里多次调 `main` 的会。
- 对比有一个经真 serve 进程的测试（`tests/test_runs.py` 的 test_compare_and_multi_export 末尾）：`/api/graph?run=a` 带三种 cmp——找不到的名字给 200、cmp 块为空、cmpError 里有「找不到」；cmp 就是 a 自己给「同一个」；另一个 case 给出 cmp 块、没有 cmpError。`payload.edge_compare` 在同一个测试里是直接调的。没测到：/api/edge 带 cmp、同一个 run 的两个阶段照常对比、缓存键里的 B（换一个 B 不会拿到旧图）、带 cmpError 的图不进缓存（之后不带 cmp 的正常请求不会再带着 cmpError）。
- M4 部分仍然没有专门的自动测试：`tests/test_runs.py` 大多经 `payload.load_hot` 测加载，上面那个对比测试顺带经真 serve 走了 `/api/graph` 上 run= 按 case 名解析这一条；其余靠的是设计稿里记的浏览器验收。run= 找不到时的 404、后补的 503、输入包的纯文本 404、run.json 进缓存键、启动时的落后提示都没有测试（`payload.index_lag` 本身在 `tests/test_app.py` 的 test_status_browse_symbols 里经项目卡片测到了：没改过是 0、改一个文件是 1）。
- `--home` 和 Host 检查有经真 serve 进程的测试（`tests/test_app.py`）：test_app_http 里，主菜单起的 serve 在 `/api/app` 上给的是主菜单的地址、Host 不对给 403，扫描之后在原端口重启、读到新 index 也在这里测到；test_serve_guard_and_home 直接起 serve：`/api/app` 给 null、Host 不对 403、PUT 的 body 是合法 JSON 但不是对象时 400、`/api/open` 不带头 403（请求的是一个不存在的文件：万一守卫失效拿到的是 400，也不会真在桌面上开编辑器）、`/code/` 页面里拼进了这个头。没测到：页面上的链接本身（包括只问一次）、PUT 上 Host 不对（只测了 GET）；写解读的成功路径现在经主菜单转发测到了一次（PUT 进 /v/<端口>/api/notes/_overview，tests/test_app.py:465），直接对 serve 的没有；带了头的 `/api/open` 真去开编辑器这一支、ds.js 的 openEditor 真带上了头，也都没有自动测试。
- 「时间顺序」接口的耗时（158 万条 span 的 run 第一次 2.2 s、之后换阶段 9 ms、每个新切面约 30 ms）是这次改动时记下的，我没复测。
