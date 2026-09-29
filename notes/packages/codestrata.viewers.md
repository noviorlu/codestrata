---
written_by: claude-opus-5-5
target: codestrata.viewers
kind: package
code_sha: dc8e3fb63e0cd02b
status: draft
refs: viewers.py:1@c53f74c7,viewers.py:86@cd75921c,app.py:282@11df063b,app.py:287@4b50b029,viewers.py:96@ea0d3262,app.py:166@89e53fcb,viewers.py:135@eb9d14a6,app.py:103@36d3a057,viewers.py:146@8607e03a,app.py:344@83e7ec95,viewers.py:153@2795fd79,app.py:384@b30225f2,serve.py:467@7bdf2201,serve.py:466@b752e90b,codestrata/__init__.py:5@af14fd0e,__main__.py:734@cf7a88fc,serve.py:484@3885b904,serve.py:129@17dbac72,app.py:171@f4d0423e,viewers.py:51@791b536e,app.py:274@1ebd9410,jobs.py:236@91c1c731,jobs.py:252@d5e30fe0,app.py:353@3d1410f6,viewers.py:27@98973d7f,viewers.py:35@76c64153,viewers.py:44@4599f13f,viewers.py:63@b68552e4,viewers.py:64@b7e6dced,viewers.py:65@b3fc2a63,viewers.py:75@0cb357c7,viewers.py:101@92046fdb,tests/test_app.py:409@0c2623b5,tests/test_app.py:470@0aa432a6,tests/test_app.py:475@ce647ee1,tests/test_app.py:484@445fe6d6,tests/test_app.py:562@9507003b,viewers.py:104@52aa96c5,viewers.py:107@1e10e9df,jobs.py:29@fb4f0ee1,__main__.py:773@99fe19eb,__main__.py:609@2713e82e,viewers.py:106@068c068d,viewers.py:105@e9169d7b,app.py:351@2ef86ba0,viewers.py:108@f1824cee,viewers.py:111@6f08b1e9,viewers.py:112@bd91c017,viewers.py:114@5355e7ac,codestrata/web/home.js:113@73c0e938,codestrata/web/home.js:121@07623c62,payload.py:38@72e7dce2,viewers.py:20@760618fe,viewers.py:117@1a5175a6,viewers.py:155@f2187ef0,viewers.py:156@82588add,viewers.py:78@d0f93957,viewers.py:84@2c395cd7,app.py:382@157a853d,viewers.py:140@c93d65f7,viewers.py:144@be7d565f,viewers.py:92@fa16df6b,viewers.py:143@06799328,app.py:111@015270e5,jobs.py:255@7f8afbed,jobs.py:261@3afb0dc5,app.py:315@4b788ecb,viewers.py:127@13c04823,jobs.py:237@2e5bace7,serve.py:503@c07f92f6,app.py:376@bd2de462,jobs.py:234@e83e00a1,jobs.py:243@f1021f8b
---

## 是什么
主菜单（`codestrata app`）里「打开图」背后的进程管理：每个打开过的仓库一个 `codestrata serve` 子进程（`python -m codestrata serve <repo> --port N --home <主菜单地址>`）。它负责挑端口、起进程、等到能接连接再把端口交出去、扫描完在原端口重启、退出时收掉；主菜单（`--proxy` 时）转发 /v/<端口>/ 之前，也由它确认这个端口是不是自己起的图服务。图页面本身不为它改，还是那个一个进程服务一个仓库的 serve（viewers.py:1 的 docstring）。

对外五个方法，调用方都是 `app`：
- `Viewers.ensure`（viewers.py:86）：POST /api/open（app.py:282）。在跑就复用，没在跑或已经死了就起一个新的。返回的是端口，app 拼成图服务自己的地址（加了 `--proxy` 是 /v/<端口>/）交给页面（app.py:287）。
- `Viewers.serves`（viewers.py:96）：`--proxy` 下主菜单转发 /v/<端口>/… 之前问一句（app.py:166）。只有这里起的、还活着的图服务才转发，别的端口（包括主菜单自己）一律 404，主菜单不会变成一个能打到本机任意端口的跳板。它在 `_lock` 下扫一遍字典，和 `ensure` 的慢启动不冲突：还没登记的那个端口，这时回 404。
- `Viewers.restart`（viewers.py:135）：扫描任务成功结束时的回调 `_restart_after_scan`（app.py:103）。
- `Viewers.stop`（viewers.py:146）：从清单里移除项目（app.py:344）。
- `Viewers.stop_all`（viewers.py:153）：主菜单退出时的 finally（app.py:384）。

名字里的 viewer 指「一个仓库的图服务进程」，和前端的源码浮窗 CS.viewer（codestrata/web/viewer.js）无关。

## 为什么这样切
**为什么是子进程，而不是在主菜单进程里跑 serve。** serve 的状态挂在类属性上：`main` 把 repo、idx、home 直接赋给 `Handler`（serve.py:467），一个进程只能服务一个仓库；index 也只在启动时读一次（serve.py:466），「读到新的 index」就等于重启。与其把 serve 改成多仓库、能热加载，不如原样复用：每个仓库一个进程，重启就是停掉重起。附带的好处是一个图服务崩了不会带倒主菜单，停掉一个仓库时它占的内存（大仓库的 index）随进程一起还掉。

**为什么几乎是叶子。** 它唯一 import 的内部东西是包里的 `self_command`（codestrata/__init__.py:5，只拼一条命令行），不认识 index、run 和项目清单。和 serve 之间的约定只在命令行这一层：`serve <repo> --port N --home URL`（--home 是专门为它加的隐藏选项，__main__.py:734），外加「serve 只监听 127.0.0.1」（serve.py:484）、「只认 Host 为 127.0.0.1:端口 或 localhost:端口」（serve.py:129，防 DNS rebinding），所以主菜单转发时连 127.0.0.1:端口，并把 Host 改写成这个（app.py:171）。`_Viewer.url`（viewers.py:51）是改成交端口之前的遗留，现在没有调用方。哪些仓库能打开，由 `app` 在前面挡掉（`AppHandler._registered`，app.py:274）；图页面拿「回主菜单」的地址走 serve 自己的 /api/app。

**为什么和 jobs 分开。** 两边都起 `python -m codestrata …` 子进程（命令行都来自 `self_command`），生命周期却完全不同。jobs 的任务有始有终，输出要逐行实时给页面看（管道加一个读输出的线程，jobs.py:236、jobs.py:252），一个仓库同时只能有一个。这里的 serve 是常驻的，输出平时没人看，只在起不来时要末尾几行；要管的是端口、「什么时候算起来了」和重启。`app` 只做 HTTP，两者靠 `make_app` 里的一个回调接起来（app.py:353）：扫描成功就 `restart`。录制结束不用重启，因为 serve 每个请求都现调 `runs.catalog`，新录的 run 自己就会出现（见 serve 的解读）。

## 读法
1. 模块 docstring（viewers.py:1）：职责、为什么要重启、日志放在哪。
2. `free_port`、`_listening`（viewers.py:27、viewers.py:35）：两个 socket 小工具，`_start` 的等待循环全靠后者。
3. `_Viewer`（viewers.py:44）：一个子进程的记录。`alive` 用 poll，顺带回收已经退出的子进程。
4. `Viewers.__init__` 里的两层锁（viewers.py:63、viewers.py:64）和 `_closed`（viewers.py:65），然后是 `_repo_lock` / `_get` / `_set`（`_set` 在 `stop_all` 之后把新起好的作废，viewers.py:75）。先弄清哪把锁护着什么，后面四个公开方法才读得懂。
5. `_start`（viewers.py:101）：起进程、等端口、起不来时带着日志末尾报错。这是核心。
6. `ensure` → `restart` → `stop` → `stop_all`：按「打开 → 扫描后重启 → 移除 → 退出」的顺序读，留意每个方法拿的是哪把锁、kill 是在锁里还是锁外。
7. 验收是 `tests/test_app.py` 的 test_app_http：没 scan 过的仓库打开时返回 500（tests/test_app.py:409）；再点一次拿到同一个地址（tests/test_app.py:470）；新加一个文件、重新扫描后，原端口上能看到新模块（tests/test_app.py:475）；移除项目后那个端口不再有人监听（tests/test_app.py:484）。test_cli_app 用 SIGTERM 停掉整个主菜单，再确认它起的图服务也不在了（tests/test_app.py:562）。

## 关键算法
### 起一个 serve：挑端口、写日志、等到能连上
`_start` 的每一步和理由：
- **端口由父进程先挑**（viewers.py:104；`free_port` 绑 127.0.0.1:0 拿到端口后关掉）。这样在起进程之前，地址就定了，不用从子进程的输出里解析端口。代价是先查后用的窗口：挑到之后、serve 绑上之前，端口可能被别人占掉，serve 在建 `ThreadingHTTPServer` 时抛错退出（serve.py:484 没接 OSError），走下面「起不来」那条路。
- **命令行用 `self_command`**（viewers.py:107）：`sys.executable -m codestrata`，和主菜单同一个解释器、同一份 codestrata，不管 PATH 里的 codestrata 是哪个。jobs 的 `_cli`（jobs.py:29）和 `__main__._prog` 的兜底（__main__.py:773）用的是同一个函数，三处不会各写各的。jobs 那边多加一个 -u，是因为输出要实时给页面；这里输出进文件、没人实时看，不加。
- **不设 cwd**：仓库已经作为参数传给 serve（`cmd_serve` 还会 resolve 一次，__main__.py:609），serve 不依赖当前目录。仓库目录没了时，Popen 也就不会在 chdir 那一步抛 OSError（那不是 `ViewerError`，/api/open 接不住），而是 serve 自己报「没有 index.json」，走下面「起不来」那条路。
- **输出写文件，不接管道**（viewers.py:106）：每个仓库一个日志，<logdir>/serve-<仓库路径 sha1 的前 12 位>.log（viewers.py:105），logdir 是配置目录下的 logs（app.py:351）。没人持续读的管道写满之后，serve 再往 stdout / stderr 写就会卡住；写文件不需要一个读输出的线程，起不来时也能读到末尾。按仓库而不是按端口命名、每次启动用 wb 覆盖：不管是在原端口重启还是换了新端口，同一个仓库始终只占一个文件，logs 目录不会随端口越积越多；同一个仓库的启动都在仓库锁里（见下），不会有两个 `_start` 同时截断同一个日志。父进程这边的文件句柄出了 with 块就关了，子进程有自己的一份。stdin 给 DEVNULL（viewers.py:108），serve 不会去读主菜单终端的输入。
- **等到真能连上才返回**（viewers.py:111 起），每 0.2 秒一轮：先看进程还活着没有（viewers.py:112），再试着连端口（viewers.py:114）。为什么非等不可：前端点「打开图」时先同步开一个空白标签（等请求回来再开会被弹窗拦截，codestrata/web/home.js:113），/api/open 一返回就把标签跳过去（codestrata/web/home.js:121）；地址交得太早，标签里就是「连接被拒绝」。而 serve 要先读 index、数 run、算 index 落后多少，然后才绑端口（serve.py:466 到 serve.py:484），大仓库要几秒。拿「连得上」当信号，不去认启动横幅里的某一行字，因为它就是浏览器需要的条件，也不和 serve 打印的文字绑在一起。端口在 `ThreadingHTTPServer` 构造时就已经在 listen，`serve_forever` 之前进来的连接排在 backlog 里，不会丢。探测只建 TCP 连接、不发 HTTP 请求，serve 的 Host 检查管不到它。
- **先判活没活，再判端口**：serve 起不来通常是马上退出，最常见的是没 scan 过（`payload.load_index` 抛 SystemExit，payload.py:38）。这时立刻报出退出码和日志末尾 20 行（`_tail`），不用等满超时。页面上「打开图失败：……先跑 codestrata scan」就是这么来的（tests/test_app.py:409 测的是 500）。
- **超时**：`START_TIMEOUT` 是 120 秒（viewers.py:20），比实际需要宽得多（注释说 1600 个文件的仓库要几秒）。超时先 kill（viewers.py:117）再报错，半起的进程不会留下，也不会被登记进字典。

### 两层锁：不让谁去等别人的慢启动
- `_lock`（viewers.py:63）只护着两个字典和 `_closed`，只在查、改它们时拿，时间很短。`stop_all` 只经过它，所以主菜单退出时不会被一个正在起的 serve（最长 120 秒）卡住；取仓库锁的 `_repo_lock` 也只是在它下面 setdefault 一下。
- 每个仓库一把锁（viewers.py:64，`_repo_lock` 在 `_lock` 下用 setdefault 取出来）。`ensure` 和 `restart` 从头到尾拿着它，包括最长 120 秒的 `_start`：同一个仓库连点两次「打开图」，第二次等第一次起完再复用，不会起两个；扫描后正在重启时点「打开图」，也是等重启完、拿到同一个地址。不同仓库各拿各的锁，起一个大仓库不会挡住小仓库（viewers.py:64 的注释）。
- `stop` 在仓库锁里把记录摘掉，kill（最多等 5 秒）放在锁外做（viewers.py:146）。`stop_all` 只拿 `_lock`，先把 `_closed` 置上（viewers.py:155），再一次把整个字典换成空的（viewers.py:156），然后逐个 kill。
- `stop_all` 不拿仓库锁，所以看不到正在 `_start` 里等端口、还没登记的那个。`_closed` 就是补这个口子的：`_start` 起好之后要经 `_set` 登记，`_set` 在 `_lock` 下看到 `_closed`，就不登记，而是 kill 掉并抛 `ViewerError("主菜单正在退出")`（viewers.py:78 到 viewers.py:84）。检查和登记在同一把锁里，和 `stop_all` 的「置标志 + 清字典」不会交错：要么登记在前、被 `stop_all` 清走停掉，要么在后、被 `_set` 自己停掉。`ensure` 在起之前不查 `_closed`，但主菜单先 server_close 再 `stop_all`（app.py:382），不会再有新的打开请求进来；扫描回调里的 `restart` 在字典清空之后只会看到没有记录，直接返回。

### 重启：沿用原端口，死掉的不沿用
- `restart`（viewers.py:135）只重启**正在跑的**（viewers.py:140）。没开过图、或者图服务已经退出的，什么都不做，下次 `ensure` 起的自然读新 index。
- 正在跑的就停掉，在**原端口**上起新的（viewers.py:144）。浏览器里开着的图标签指的就是这个端口，刷新一下就是新的 index，不用回主菜单重新打开。停掉的端口能马上重新绑上，是因为 http.server 的 HTTPServer 默认开着 allow_reuse_address（SO_REUSEADDR）：serve 的 HTTP/1.0 连接由服务端先关，旧进程在这个端口上留下一批 TIME_WAIT，不开这个选项会被它们挡住一分钟左右。
- 反过来，`ensure` 碰到死掉的记录**不沿用**它的端口，而是重新挑（viewers.py:92 的注释）：不知道它死了多久，端口可能已经被别人占了。`restart` 敢沿用，是因为旧进程是自己刚刚停掉的。
- 重启前先把记录摘掉（viewers.py:143）再起新的：`_start` 抛 `ViewerError` 时，字典里不会留着那个已经停掉的旧记录，下次 `ensure` 从头挑端口。这个错由 `_restart_after_scan` 写进扫描任务自己的输出（app.py:111），页面上的任务日志里看得到；开着的标签会连不上，要回主菜单再点一次「打开图」。
- 重启算在扫描任务里：jobs 先调回调、再把任务标成结束（jobs.py:255 到 jobs.py:261）。页面看到「扫描完成」时，图服务已经在原端口上读好了新的 index，这时刷新标签就是新图；重启的这几秒里任务还算「在跑」，同一个仓库起不了新的扫描、录制（app.py:315），也移除不了。

### 停：先 SIGTERM，5 秒后 SIGKILL
`_kill`（viewers.py:127）先 terminate，等 5 秒，还在就 kill。serve 没有处理 SIGTERM，默认动作就是直接退出，5 秒只是给卡住的情况兜底。

这里的子进程没有像 jobs 那样 start_new_session（对比 jobs.py:237），和主菜单在同一个进程组。在终端里对 `codestrata app` 按 Ctrl+C，SIGINT 同时打到每个 serve，它们自己接住 KeyboardInterrupt 退出（serve.py:503），随后 `stop_all` 发现它们已经不在了，直接跳过。用 kill 发 SIGTERM 停主菜单时，信号只打到主菜单，`app` 把它转成 KeyboardInterrupt（app.py:376），走同一个 finally，由 `stop_all` 逐个停。jobs 需要自己的进程组，是为了让 trace 按三级顺序把 run 收好（jobs.py:234）；serve 没有这种收尾，和主菜单一起吃 Ctrl+C 正合适。

## 局限
- `_listening` 只看「这个端口有没有人在听」，不看是不是自己起的那个 serve。`free_port` 挑到之后，端口要是被别的程序抢先占了，第一轮探测就可能连上那个程序，把它的地址当成图服务交出去；自己的 serve 随后绑不上、退出。再点「打开图」时 `ensure` 看到记录已经死了，会挑新端口重起，只是那一次打开的标签是别人的页面。重启沿用原端口时同理，窗口更小。
- 主菜单被 SIGKILL 或者崩了，就没人调 `stop_all`，也没有 PR_SET_PDEATHSIG 之类的兜底：各个 serve 留在原端口上接着跑。下次启动的主菜单不认得它们（字典是空的），打开图会在新端口上另起一个。
- `_closed` 只在起好、要登记的那一刻生效，`stop_all` 并不等正在起的那个。主菜单退出时，处理请求的线程（ThreadingHTTPServer 的 daemon_threads）和 jobs 读输出、调回调的线程（jobs.py:243）都是守护线程：`stop_all` 返回、进程一退，还卡在 `_start` 等待循环里的那个（`ensure` 起的，或扫描回调里 `restart` 起的）连同线程一起没了，它起的 serve 就成了孤儿。终端 Ctrl+C 不受影响，因为 SIGINT 也打到了它。
- `_locks` 只增不减，移除过的仓库那把锁一直留着；移除项目也不删它的日志，logs 目录里每个打开过的仓库留一个文件。数量都等于打开过的仓库数，可以忽略。
