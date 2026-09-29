---
written_by: claude-opus-5-5
target: codestrata.app
kind: package
code_sha: ede060fd60fd557f
status: draft
refs: app.py:1@56b5a99f,app.py:17@976a14d1,jobs.py:138@37cb631e,app.py:19@4c5aef6c,app.py:220@53dc2790,app.py:169@53dc2790,app.py:253@53dc2790,app.py:249@4b788ecb,app.py:255@43741afe,app.py:270@9a34f9b5,app.py:257@ae50ee8f,app.py:254@4de47a02,app.py:256@f000f1fe,app.py:232@ae50ee8f,app.py:195@44758394,app.py:190@9dc096e5,app.py:224@9dc096e5,app.py:247@9dc096e5,codestrata/web/home.js:32@3ba61827,app.py:276@855ea88f,app.py:281@3d1410f6,app.py:94@eda59c8d,app.py:101@015270e5,jobs.py:242@9ad5da4f,app.py:124@8f1115e0,app.py:75@2f487f12,tests/test_app.py:262@246a570a,tests/test_app.py:263@c4eef9da,app.py:83@77dfac83,app.py:87@d2e8ee72,codestrata/web/home.js:116@6090bd46,app.py:89@feb11713,app.py:81@68282492,app.py:245@7277b258,app.py:251@bb0e70ff,app.py:268@7277b258,app.py:271@e16ab0c6,app.py:246@9cc6695a,app.py:222@1ebd9410,viewers.py:126@95b149a8,app.py:272@83e7ec95,jobs.py:96@4096f3a3,app.py:118@79640314,app.py:120@883c685b,payload.py:37@72e7dce2,app.py:239@38157631,serve.py:101@1c146e87,serve.py:90@dd652a40,serve.py:108@17b8be84,app.py:154@91bf0872,serve.py:126@bf8403e9,serve.py:138@1f49836e,app.py:74@e3700653,serve.py:122@17dbac72,app.py:108@aeedd490,app.py:127@64db3519,app.py:130@eaa44015,app.py:140@fe6ee01b,app.py:151@6b7eab76,app.py:159@55d71800,app.py:289@aceccec4,tests/test_app.py:270@e257655f,tests/test_app.py:273@66c33760,tests/test_app.py:274@ec83f3c7,tests/test_app.py:275@76ddc24d,tests/test_app.py:279@ee1b3df9,tests/test_app.py:280@597a3dec,tests/test_app.py:283@464dd46b,tests/test_app.py:286@d5c305b9,tests/test_app.py:294@9286b179,tests/test_app.py:297@04c5ff7e,tests/test_app.py:333@bce53d9f,tests/test_app.py:386@56639e09,serve.py:127@4ebae8bb,app.py:132@892c2fff,app.py:21@a074ba58,app.py:135@6ccaf5ab,serve.py:129@32f7a33f,codestrata/web/home.js:28@84cb1143,app.py:67@48f34bde,app.py:142@8c363376,app.py:218@c1f006a0,projects.py:59@230fe1ef,projects.py:55@5a20a6c8,jobs.py:214@ab8af95a,jobs.py:123@595af36f,app.py:238@b7327b06,app.py:156@efd6c259,codestrata/web/home.js:12@e4b479db,codestrata/web/home.js:74@48e0acda,app.py:57@71b711e9,app.py:58@643f1be6,app.py:66@b6af827e,app.py:295@97ce7ba4,app.py:90@a5f2a7f4,tests/test_app.py:278@90a0a009,app.py:50@c70e7fbe,app.py:209@a345c83f,app.py:202@15a8a37f,app.py:212@daaf759f,app.py:213@07a1ffbf,app.py:216@61bb9a91,app.py:242@e24f3de0,app.py:48@af2a19dd,app.py:176@5eb93d23,app.py:183@916787f2,app.py:172@7360f0ac,codestrata/web/home.js:277@e7dd7de9,app.py:291@a09fbae2,app.py:294@73f1526a,app.py:293@c7915d94,app.py:279@2ef86ba0,__main__.py:716@92f385f2,app.py:301@622849f2,app.py:302@bd2de462,app.py:307@5e26c59c,app.py:309@db2ff329,app.py:310@b30225f2,app.py:306@b4445f1f,app.py:23@f0705afd,projects.py:107@e10eddb3,jobs.py:112@44758394,app.py:267@2173e90f
---

## 是什么
`codestrata app` 的 HTTP 层。浏览器里的主菜单页面（codestrata/web/home.html、home.js）经它调 `/api/*`，它把请求交给三个服务：项目清单和卡片数据交给 `projects`，后台的 scan / trace 任务交给 `jobs`，每个仓库的图服务进程交给 `viewers`，再把结果或错误变成 JSON 和状态码。它自己不存数据、不起进程。只有它能做的是三件事：鉴权；在 `make_app` 里把三个服务装配到一起（「扫描成功 → 重启图服务」这根线也是在这里接的）；用 App.lock 让横跨两个服务的「先查再做」一口气做完。路由表写在模块 docstring 里（app.py:1），职责边界一句话在 app.py:17。

这是整个 codestrata 里唯一一个能在本机执行任意命令的网络入口：`POST /api/trace` 的 command 字段就是一条要在仓库根目录执行的命令，经 `jobs` 放到 trace 命令行 `--` 的后面（jobs.py:138）。所以这个模块有一半的分量在鉴权上，docstring 从 app.py:19 起列了四条。

## 为什么这样切
**HTTP 以外的东西都不放这里。** 主菜单按副作用拆成四块，分法和理由见 projects 的解读。app 这一侧留下的是：
- 路由和取参数。`do_GET` / `do_POST` / `do_DELETE` 按路径分派，每个分支只做「取参数 → 调一个服务方法 → 回 JSON」。
- 状态码翻译。服务层只抛自己的异常，不认识 HTTP，异常变成状态码只在这里做：
  - `ValueError` → 400：加项目时给的不是目录（app.py:220），browse 的路径打不开（app.py:169），录制表单不合法（app.py:253）；
  - 这个仓库已经有任务在跑 → 409：起任务前先查（app.py:249），`jobs.start` 抛的 `Busy` 也接成 409（app.py:255）；有任务在跑时移除项目也回 409（app.py:270）；
  - `JobError` → 500：命令起不来，比如仓库目录已经没了（app.py:257）。`Busy` 是 `JobError` 的子类，所以接 `Busy` 的那一句要排在前面（app.py:254、app.py:256）；
  - `ViewerError` → 500：图服务起不来，比如没 scan 过（app.py:232）；
  - runs/ 的盘没挂上时 `runs.catalog` 抛的 `SystemExit` → 503（app.py:195）；
  - 不在清单里的项目 → 404（app.py:190、app.py:224、app.py:247）。

  错误说明原文放进 {"error": …}，home.js 的 api 函数直接拿它当异常信息显示（codestrata/web/home.js:32）。所以 `TraceSpec.validate` 写给人看的中文（包括阶段名写错时 trace 给的候选）在 HTTP 层不用再转一道。服务层也因此不起服务就能测：test_registry、test_status_browse_symbols、test_trace_spec、test_job_manager 都直接调服务，主菜单的 HTTP 只在 test_app_http（以及起整条命令的 test_cli_app）里走。
- 鉴权，见「关键算法」里的安全模型。
- 装配：`make_app`（app.py:276）。`jobs` 不知道有 `viewers`，`viewers` 也不知道有 `jobs`，「扫描成功就在原端口重启图服务」是这里用 `on_done` 接上的（app.py:281）。回调写成模块级函数 `_restart_after_scan`，只拿 viewers，不做成 `App` 的方法：`JobManager` 要先建好才能放进 `App`，建它的时候 `App` 还不存在，lambda 只能捕获局部变量 `viewers`。回调在 jobs 读输出的线程里跑，时机是命令已经退出、任务还没标成结束（app.py:94，见 jobs 的解读）：重启算在扫描任务里，页面看到「完成」时图服务已经换好了，这期间同一个仓库也起不了新任务。重启失败就用 `job.add` 把原因写进这个扫描任务的输出（app.py:101），页面上看得到；回调里漏出来的其他异常由 jobs 接住，同样写进输出（jobs.py:242）。

**状态收进一个 `App` 对象。** `BaseHTTPRequestHandler` 每个请求实例化一次，进程级状态只能挂在类上。serve 把仓库、index、几份缓存逐个挂成 `Handler` 的类属性（见 serve 的解读「状态放在类属性上」）；这里只挂一个 `app`（app.py:124），Handler 的每个方法都经 `self.app` 找服务（app.py:75）。这样整套状态可以一次换掉：`make_app` 接受一个配置目录参数，测试给临时目录，建好后一句赋值挂上去（tests/test_app.py:262、tests/test_app.py:263），碰不到用户真实的 projects.json 和口令文件。

`App` 上的逻辑只有两样。一是 `card`（app.py:83）：一张项目卡片要同时问 projects（仓库状态）和 jobs（最近一个任务），app 是同时认识两者的地方，所以在这里拼。最近的任务用 `snapshot(since=n)` 只取状态、不取输出（app.py:87，见 jobs 的解读）。卡片里没有图服务地址：页面上「打开图」每次都走 `POST /api/open`（codestrata/web/home.js:116），复用还是重起由 viewers 决定。二是 `token_ok`（app.py:89）：首页的 `?t=` 和 /api/ 的 cookie 共用这一处比较，见「口令」。

**横跨两个服务的检查和动作，用 App.lock 一口气做完**（app.py:81）。projects 和 jobs 各有自己的锁，但有两件事横跨两边：起任务是「还在清单里 → 没有任务在跑 → 起」（app.py:245 到 app.py:251），移除项目是「没有任务在跑 → 从清单里删」（app.py:268 到 app.py:271）。只拿各自服务的锁的话，两个请求交错时会给一个刚被移除的项目起任务：任务照跑，卡片却没了。所以这两段放在同一把锁里，`_start` 在锁里重新过一遍 `_registered`（app.py:246）；do_POST 里那一次（app.py:222）是 `/api/open` 的闸门，对扫描和录制只是提前回 404。这把锁不分仓库，锁里只放快的事：停图服务可能要等 5 秒（viewers.py:126），放在锁外（app.py:272）。例外是设了阶段的录制要在锁里读 index，见「不确定 / 局限」。

**读 index 的活为什么在这里。** `TraceSpec.validate` 把符号表当参数收（jobs.py:96），jobs 自己不读 index，测试里可以直接喂一份。读的活就落到调用方 `_symbols`（app.py:118）。它先用 `index_summary` 判断扫描过没有，没扫过就给 None（app.py:120）：这种情况下 `load_index` 抛的是 SystemExit（payload.py:37），不先判断，它就会从请求线程里冒出去。`_trace_argv` 只在表单设了阶段时才调它（app.py:239）：没有阶段时 `validate` 用不上符号表，而大仓库的 index 有十几 MB。

**底层和 serve 共用。** 发响应、JSON 进出、读请求体、Host 检查、给静态文件，用的是从 serve 里抽出来的 `BaseHandler` 和 `asset`（serve.py:101、serve.py:90），抽取的理由见 serve 的解读。`_send` 的 headers 参数（serve.py:108）就是为这里设 cookie 加的（app.py:154）。`_host_ok` 从 `self.server` 取实际绑定的端口（serve.py:126），所以 `App` 不用存端口；`_body_json` 只放行 JSON 对象（serve.py:138），do_POST 拿到的 body 一定是 dict，直接 `.get`，不用再核一遍。

## 读法
1. 模块 docstring（app.py:1）：路由表、「只做 HTTP」、安全四条。后面的代码基本是这张表的逐条实现。
2. `make_app`（app.py:276）和 `App`（app.py:74）：先知道 Handler 手里有哪几样东西，回调是怎么接的，那把锁护着什么。
3. 鉴权：`BaseHandler._host_ok`（serve.py:122）、`_cookie`（app.py:108）和 `_cookie_ok`（app.py:127）、`App.token_ok`（app.py:89）、`_guard`（app.py:130），再加 `_registered`（app.py:140）。每个 do_* 的第一件事都是 `_guard`，先弄清它放行什么。
4. `do_GET` 开头对 `/` 的处理（app.py:151 到 app.py:159）：口令怎样变成 cookie。
5. 其余路由，按 `do_GET` → `_template` → `do_POST` → `_trace_argv` → `_start` → `do_DELETE` 的顺序。读的时候只看两件事：调了哪个服务，哪种异常变成哪个状态码。
6. `main`（app.py:289）：启动和退出时的清场。
7. 验收看 tests/test_app.py 的 test_app_http：四种 403（tests/test_app.py:270 到 tests/test_app.py:273），非 ASCII 的口令只是不对、不断连接（tests/test_app.py:274、tests/test_app.py:275），别的服务设的古怪 cookie 排在前面照样认得出口令（tests/test_app.py:279），未知的 POST 路径回 not found（tests/test_app.py:280），链接设 cookie 的 303（tests/test_app.py:283），不在清单里的 404（tests/test_app.py:286），同一个仓库第二个任务的 409（tests/test_app.py:294），有任务在跑时先回 409、不去校验表单（tests/test_app.py:297），有任务时不能移除（tests/test_app.py:333）。整条命令的启动、口令文件的权限、SIGTERM 退出看 test_cli_app（tests/test_app.py:386）。

## 关键算法
### 安全模型：三道检查，各挡一类来源
主菜单能执行命令。要防的请求来源有三类，每道检查对着其中一类。

**别的网站借 DNS rebinding 冒充同源。** 攻击者的域名先解析到自己的服务器，页面加载后改解析到 127.0.0.1，页面脚本就能以「同源」身份访问主菜单的端口，自定义头也能随便加。这类请求的 Host 头是攻击者的域名，而 `_host_ok` 只认 `127.0.0.1:端口` 和 `localhost:端口`（serve.py:127，和图服务是同一份检查）。它在 `_guard` 里最先查，对所有路径都查（app.py:132），包括不要 cookie 的首页和静态文件。cookie 按主机名存，这种请求本来也带不上口令 cookie，所以对 /api/ 来说，Host 检查和 cookie 是重叠的两层。

**本机浏览器里的别的网页，包括 127.0.0.1 上其他端口的页面**（别的本地开发服务，还有主菜单自己起的图服务）。SameSite 管的是「站点」，站点不看端口：127.0.0.1 上任意端口的页面和主菜单同站，它们发起的请求，浏览器照样带上口令 cookie。图页面上的「← 主菜单」链接点过去能直接进主菜单，靠的也是这一点（见 serve 的解读）。所以 docstring 说「别的网页带不上」cookie（app.py:21），只对别的主机名成立。对同一台机器其他端口上的页面，真正起作用的是必带的 `X-Codestrata` 头（app.py:135）：
- 跨源请求要带自定义头，浏览器会先发 OPTIONS 预检。`AppHandler` 没有 do_OPTIONS，http.server 回 501（实测），预检不通过，真正的请求根本发不出去。
- 不带这个头的「简单请求」（表单 POST、img、不加头的 fetch）发得出去，也带着 cookie，但在 `_guard` 里被 403。
- POST 的 body 按 JSON 读，不看 Content-Type（serve.py:129）。用 text/plain 表单伪造 JSON body 这条老路，也是靠这个头挡住的。

home.js 的每个请求都带这个头（codestrata/web/home.js:28）。同源请求加自定义头不需要预检。

**本机的其他进程、其他用户。** 它们直接连 127.0.0.1，Host 和 X-Codestrata 想写什么写什么，只有口令拦得住。口令文件用 0600 创建（app.py:67），别的用户读不到。

另外两处是纵深：
- **只接受清单里的项目**（`_registered`，app.py:142）。通过鉴权的客户端可以 `POST /api/projects` 把任意目录加进清单（app.py:218），所以这道挡不住外人，挡外人的是上面三道。它守的是两条不变式：
  - 一个仓库只有一种写法。清单里存的是 `add` 时 resolve 过的绝对路径（projects.py:59），`has` 按字符串精确比（projects.py:55）。jobs 的「一个仓库同时只跑一个任务」按 repo 字符串判断（jobs.py:214），viewers 的字典也用它做键。要是 `/x/repo` 和 `/x/../x/repo` 都放进来，就成了两个仓库，同一份 index 可能被两个扫描同时写。
  - 仓库路径放进 argv 时不会被当成选项。它在 trace 命令里是位置参数（jobs.py:123），没法写成 `--x=值` 的形式，靠「来自清单，一定是绝对路径」保证不以 `-` 开头（见 jobs 的解读）。`POST /api/trace` 还会把 body 里的 repo 换成清单里的那个字符串，再建 `TraceSpec`（app.py:238）。
- **HttpOnly**（app.py:156）。cookie 不分端口，127.0.0.1 上每个端口的服务都会收到这个 cookie；那些页面的脚本要是能读 document.cookie，就能把口令拿走。HttpOnly 让口令只出现在请求头里。主菜单自己这个源上的 XSS 仍然等于能执行命令（同源脚本加得了头），所以 home.js 往 innerHTML 里放的路径、名字都先过一遍 esc 函数（codestrata/web/home.js:12、codestrata/web/home.js:74）。

### 口令：打开一次链接，之后靠 cookie
- `load_token`（app.py:57）：文件里有口令就读，没有就生成、以 0600 写入，之后一直用同一个。重启主菜单后，书签和浏览器里已有的 cookie 都还有效（app.py:58）。`token_urlsafe`（app.py:66）只生成 URL 安全的 base64 字符，放进 `?t=` 和 cookie 值都不用转义。
- 启动时打印、并在浏览器里打开 `/?t=口令`（app.py:295）。`do_GET` 见到对的 `t`，就回 303：用 Set-Cookie 把口令设进 cookie（Path=/、HttpOnly、SameSite=Strict、一年），Location 跳回 `/`（app.py:154）。跳这一下之后，地址栏里只剩 `/`，之后收藏、复制的都是不带口令的地址。
- 比较一律经 `token_ok`，用 `secrets.compare_digest`，比较时间不随匹配了多少位变化，响应时间泄露不出口令的前缀。比较前两边先 encode 成 bytes（app.py:90）：compare_digest 比较含非 ASCII 的 str 会抛 TypeError，没人接的话，一个 `?t=é` 的请求就是 socketserver 打一段 traceback、连接直接断掉；比 bytes 就只是不相等，/api/ 回 403，首页回说明页。
- **Cookie 头手工拆**（`_cookie`，app.py:108），不用标准库 http.cookies。cookie 不分端口，127.0.0.1 上别的服务设的 cookie 也会一起发过来；标准库的解析器遇到一个它不认的 cookie，后面的就全丢了。实测（Python 3.12.3）：值是 {"a":1} 这类带引号的 JSON、名字或值里有空格，都会这样。这样的 cookie 排在口令前面时（浏览器大体按创建先后排），每个 /api/ 请求都会 403，`/` 一直显示说明页，重新点带口令的链接也救不回来。现在按 `;` 切开、每段按第一个 `=` 分出名字和值，只找自己那一个，别的 cookie 长什么样都不影响（tests/test_app.py:278）。
- 没有 cookie 时访问 `/`，给的是一页说明（`_LOGIN_PAGE`，app.py:50），不是 403：这时多半只是换了浏览器或清了 cookie，页面要告诉人怎么进来。这一页不是防线。`/home.html` 作为静态文件，不带 cookie 也取得到（实测 200；`_guard` 只对 /api/ 要口令，app.py:135），但页面里没有秘密，它发的每个 /api/ 请求都会被 403。
- 换口令没有命令：删掉配置目录里的 app-token 再启动，`load_token` 读不到就会重新生成。

### 路由里的几处顺序
- `POST /api/jobs/<id>/stop` 排在读 body 之前（app.py:209），停止不需要 body。其余 POST 先对一张显式的路径表（`_POST`，app.py:202），不在表里就回 not found（app.py:212）：不先对表的话，未知路径会落到后面的 `_registered`，回一句「不是清单里的项目」，调试时很误导。在表里的才读 body，body 必须是 JSON 对象（app.py:213）。`/api/projects` 是加项目，这时还不在清单里，先分出去（app.py:216）；其余三个先过 `_registered`，再按路径分派（app.py:222）。`/api/scan`、`/api/trace`、`/api/open` 因此过的是同一道闸门，不会有哪个分支漏查。
- 起任务的顺序是：拿锁 → 还在清单里 → 没有任务在跑（否则 409）→ 拼命令行 → 起进程（`_start`，app.py:242）。拼命令行是调用方传进来的函数，扫描是 `scan_argv`，录制是 `_trace_argv`：`from_json`（只查类型）→ `validate`（查内容，设了阶段才读 index）→ `argv`，错了抛 ValueError，回 400（app.py:253），不会起一个注定失败的子进程。忙不忙排在最前：这个仓库正在扫描时 index 正被重写，先校验就可能读到写了一半的 symbols.json，以一个莫名其妙的 400 回来，真正的原因（有任务在跑）反倒被盖住，表单也是白查。测试专门在扫描中提交一个阶段写错的表单，要的是 409（tests/test_app.py:297）。
- 一个正则 `_JOB`（app.py:48）同时匹配「查询」和「停止」：GET 只认不带 /stop 的（app.py:176），POST 只认带 /stop 的（app.py:209）。`since` 解析不了就当 0（app.py:183），轮询不会因为一个坏参数中断。
- `/api/symbols` 遇到不在清单里的仓库，回空列表（app.py:172），不回 404：补全是边打边查的，查不到就安静地不提示。`/api/template` 是用户主动点的，所以回 404（app.py:190）。它给的是整份 `TraceSpec`，包括表单上不显示的 tags / roots / stop_grace，页面原样带回 `/api/trace`（codestrata/web/home.js:277），`_trace_argv` 也把 body 整份交给 `from_json`，复刻出来的录制参数才和原来一样。

### 启动与退出
- 先绑端口，再装配（app.py:291、app.py:294）。端口被占时给一句能照做的提示（换 --port，app.py:293），这时配置目录还没碰过。装配里要用到端口的只有图服务的 --home（app.py:279）；Host 检查从 `self.server` 取端口，不经 `App`。`main` 的 port 没有默认值，默认端口 8930 只写在命令行那一处（__main__.py:716）。`AppHandler.app` 在 `serve_forever` 之前就挂上了。端口虽然已经在 listen，进来的连接要等 `serve_forever` 才处理，不会有请求看到还没挂上的 `app`。
- 自动开浏览器放在守护线程里（app.py:301）。`webbrowser` 在没有图形界面、退回终端浏览器（GenericBrowser）时，会 `wait` 到那个浏览器退出；这一步要是放在主线程，就会一直卡在 `serve_forever` 之前。代码里没写这条理由，是从 webbrowser 的实现推出来的。
- SIGTERM 转成 KeyboardInterrupt（app.py:302），Ctrl+C 和 kill 走同一个 finally（app.py:307）：关掉监听，停掉所有任务（app.py:309），停掉所有图服务（app.py:310）。任务先停，录制要把 run 收好，最多等 2 分钟（退出时打印的提示在 app.py:306）。图服务后停；关掉监听时，处理中的请求线程（比如一个正在等图服务起来的 `/api/open`）不会被等，`Viewers.stop_all` 之后才起好的图服务由 viewers 当场杀掉，不会漏在外面。子进程各自怎么停、为什么 jobs 和 viewers 的进程组不一样，见这两个模块的解读。

## 不确定 / 局限
- **口令会出现在启动浏览器的命令行里。** `webbrowser.open` 把带 `?t=口令` 的整个 URL 当参数交给 xdg-open 或浏览器（app.py:301）。如果浏览器之前没开着，这个 URL 会一直留在浏览器主进程的命令行里，同机其他用户能从 /proc 读到（除非开了 hidepid）。docstring 说口令「只有自己能读」（app.py:23），在多用户机器上要打这个折扣；用 `--no-browser` 只打印，就不走这条路。口令从不轮换，漏一次就一直有效，直到删掉文件。
- **Host 检查写死了带端口号的形式**（serve.py:127）。浏览器访问 80 端口时 Host 不带端口号，所以 `--port 80` 下所有请求都是 bad host。localhost 虽然放行，但 cookie 按主机名存，用 localhost 打开时，要把带口令的链接换成 localhost 再打开一次。
- **SystemExit 仍是逐处处理。** 下层有几个函数用 SystemExit 报给用户看的错（CLI 留下的习惯）。SystemExit 不是 Exception，从请求线程冒出去就是断连接。现在走到的几处都接住或躲开了：`_template` 接住 `runs.catalog` 的（app.py:195）；`_symbols` 先判断再调，躲开 `load_index` 的（app.py:120）；`/api/projects` → `card` → `projects.status` 这一路由 projects 自己接（projects.py:107）；阶段写错时 `validate` 把 trace 的 SystemExit 换成 ValueError（jobs.py:112）。但 app 这层没有统一兜底：下层以后再冒出一个 SystemExit，或者任何没想到的异常，这个请求就是断连接，页面上只看到请求失败。
- **设了阶段的录制，每次提交都整份读 index，而且是在锁里读。** `_symbols` 读的是整份 index.json 和 symbols.json，`find_symbols` 的缓存用不上（那份只存了小写的 qualname 和键）。这一步在 App.lock 里（app.py:251），读的这段时间里，别的仓库起任务、移除项目都要排队。另外 409 只认主菜单自己起的任务：终端里另跑着 `codestrata scan` 时提交，仍可能读到写了一半的 symbols.json（scan 不是原子写，见 projects 的解读），JSON 解析错误是 ValueError，会以 400 回来。
- **移除项目只和任务互斥，和打开图不互斥。** `POST /api/open` 不拿 App.lock：它过了 `_registered`（app.py:222）、还没进 `viewers.ensure` 的那一瞬间，要是正好把这个项目移除了，`viewers.stop` 扑空，随后起来的图服务就一直留到主菜单退出。窗口很窄，后果只是多一个进程。`do_DELETE` 也不走 `_registered`，直接拿原样的字符串去查（app.py:267）；字符串对不上时几步都是空操作，回 removed: false。
- **只有 SIGTERM 和 Ctrl+C 会走 finally**（app.py:302）。主菜单被 SIGKILL 或者崩掉时，任务和图服务都会留下来，后果见 jobs、viewers 的解读。
