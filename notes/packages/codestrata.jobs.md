---
written_by: claude-opus-5-5
target: codestrata.jobs
kind: package
code_sha: 03491342c7973a2d
status: draft
refs: jobs.py:3@4a7c4fa2,trace.py:909@eee4333d,__main__.py:729@d9e158f3,__main__.py:746@99fe19eb,codestrata/__init__.py:5@af14fd0e,jobs.py:32@12205928,jobs.py:33@ec2b5dc5,__main__.py:743@871e51d3,codestrata/__init__.py:8@c12cdd30,app.py:254@4de47a02,app.py:257@ae50ee8f,app.py:93@36d3a057,jobs.py:5@f299d85d,scan.py:616@bc9d0fcd,app.py:239@38157631,app.py:248@94033a78,jobs.py:214@ab8af95a,jobs.py:29@fb4f0ee1,jobs.py:36@48c56204,jobs.py:41@56c7f5e4,jobs.py:44@f355386a,app.py:238@b7327b06,app.py:240@fbfd50f9,jobs.py:153@3e6da35f,jobs.py:165@e60ad74e,jobs.py:111@a24b9b0f,jobs.py:112@44758394,__main__.py:284@6868d375,app.py:120@883c685b,jobs.py:116@af5fee1d,jobs.py:121@c901c15d,tests/test_app.py:144@a9908c62,jobs.py:138@37cb631e,__main__.py:731@ec9fb5ef,projects.py:59@230fe1ef,jobs.py:137@16ae4072,jobs.py:127@aad347aa,tests/test_app.py:163@2dfff4ba,runs.py:1018@11e69ebf,jobs.py:59@77ab137b,jobs.py:80@4dc0941c,jobs.py:87@02be8f93,jobs.py:90@ca096e94,jobs.py:91@e0e0c9a0,jobs.py:93@4868b502,jobs.py:94@2e2d38d6,codestrata/web/home.js:277@e7dd7de9,tests/test_app.py:152@285387ef,tests/test_app.py:160@5fb585a4,jobs.py:235@d5e30fe0,jobs.py:237@bc8c68c4,jobs.py:160@4849d444,jobs.py:161@e13a4439,jobs.py:180@e63f0eee,tests/test_app.py:213@a4027cc0,codestrata/web/home.js:162@083b4c5e,app.py:87@d2e8ee72,jobs.py:171@0b37e3ed,jobs.py:178@44e9e60e,jobs.py:26@c0782afd,app.py:86@cddf0800,jobs.py:224@293af48e,tests/test_app.py:218@4d67590c,trace.py:880@494f49a7,runs.py:924@ffb247e6,jobs.py:225@57b7ebd8,jobs.py:222@68c6b901,tests/test_app.py:204@3be05dbd,jobs.py:148@6b3bdb4b,jobs.py:220@2e5bace7,jobs.py:253@f376bdd9,trace.py:865@f0c26bf5,app.py:309@db2ff329,trace.py:912@6ae4a835,codestrata/web/home.js:153@aa473aad,jobs.py:239@4f642e89,jobs.py:244@3afb0dc5,app.py:101@015270e5,jobs.py:242@9ad5da4f,tests/test_app.py:183@8adcb99d,jobs.py:268@b28b7e8f,viewers.py:78@d0f93957,jobs.py:258@c198ca89,__main__.py:666@29766054,jobs.py:270@c45b3ae7,trace.py:944@6d3a8055,app.py:302@bd2de462,jobs.py:219@91c1c731,app.py:271@e16ab0c6
---

## 是什么
主菜单（`codestrata app`）的后台任务层。页面上的「扫描」「录制运行」两个按钮，在这里各变成一条 `python -u -m codestrata scan|trace …` 子进程；这一层把子进程的输出逐行收进内存供页面轮询，负责停止任务、主菜单退出时清场。`TraceSpec` 是「录制运行」表单的数据：检查内容、拼成 trace 的命令行、从一个已有的 run 还原（复刻）。

## 为什么这样切
**任务就是命令行本身，不在进程里调 scan / trace 的函数**（jobs.py:3）。有三个原因：
- trace 的 driver 要自己装信号处理器（trace.py:909），`signal.signal` 只能在主线程调；主菜单是 ThreadingHTTPServer，请求都在工作线程里处理，没法在进程内直接跑录制。
- 复刻命令一致：trace 会把自己被叫起时的原样 argv 存进 run（__main__.py:729），`python -m codestrata` 这种叫法记成「解释器 + -m」（__main__.py:746）。这里拼命令用的是同一个函数 `self_command`（codestrata/__init__.py:5、jobs.py:32），图服务子进程和 `_prog` 的这一支也用它，叫法只在一处定义。唯一的差别是这里多插了一个 `-u`（jobs.py:33，原因见下面「输出」一节）。`-u` 不会进 run：用 `python -u -m codestrata` 叫起时，argv 的第一项是 __main__.py 的路径，`_prog` 照样记成 `self_command()` 的形状（__main__.py:743 到 __main__.py:746）。所以页面上显示的任务命令和在终端里敲的命令只差一个 `-u`，run 里记的复刻命令就是终端里那条。
- 用 `sys.executable`：codestrata 装在哪个环境里，任务就在哪个环境里跑（codestrata/__init__.py:8），不依赖 PATH 上碰巧有哪个 `codestrata`。

**边界**：这个模块只负责起任务、收输出、停任务，不涉及 HTTP。鉴权、只许对清单里的项目起任务、`Busy` 变成 409 / `JobError` 变成 500（app.py:254 到 app.py:257），这些都在 app 里。「扫描成功后重启图服务」是 app 通过 `on_done` 回调挂上来的（app.py:93），jobs 自己不知道有 viewers。对内部模块的依赖都是借规则：case 名的规则用 `runs.CASE_RE`，秒数怎么写进命令行用 `runs.fmt_seconds`，阶段的规则用 `trace.resolve_phase_at`，命令的叫法用包里的 `self_command`。表单检查不另写一套规则。

**一个仓库同时只跑一个任务**（jobs.py:5）：扫描会重写 index，录制开始前要读 index 来解析 `--phase`。index 是直接 `write_text` 覆盖的（scan.py:616），不是先写临时文件再改名，两个任务交错时，读的一方可能读到写了一半的 JSON。这条规则只按仓库判断，不管任务种类，所以同一个仓库上的两次录制也互斥。两次录制各写各的 run 目录，互斥是否必要没有验证过。表单校验阶段时主菜单进程自己也要读 index（app.py:239），所以 app 先查这个仓库有没有任务在跑，有就直接 409（app.py:248），不去读一份可能正被扫描重写的 index；`start` 里在自己的锁下还会再查一次（jobs.py:214）。

## 读法
1. 模块 docstring 和 `_cli` / `scan_argv`（jobs.py:29、jobs.py:36）——先建立「任务 = 一条 CLI 命令」这个前提。
2. `TraceSpec`（jobs.py:41）：先看字段，它们和 trace 的命令行选项一一对应；最后三个（tag、roots、stop_grace）表单上不显示，只在复刻时原样带过去（jobs.py:44）。然后按 `from_json` → `validate` → `argv` 的顺序读，app 处理 `POST /api/trace` 时就是按这个顺序调用的（app.py:238、app.py:240）。最后读 `from_run`，它给「复刻」预填表单。
3. `Job`（jobs.py:153）：看 `lines` 和 `n` 两个字段、护着它们的 `_lock`（jobs.py:165），再看 `add` 和 `snapshot`。输出轮询的协议全在这里。
4. `JobManager`：`start` → `_pump` → `stop` / `stop_all`，是一个任务从起到停的完整过程；`_prune` 管结束的任务留多少。`Busy` 和 `JobError` 只是 `start` 抛给 app 的信号。

## 关键算法
### 表单 → 命令行：阶段规则只在 trace 里写一处
`validate` 检查阶段时直接调 trace 的 `resolve_phase_at`（jobs.py:111），把它抛出的 SystemExit 换成 ValueError（jobs.py:112），报错原文给页面显示。命令行的 `--phase` 走的是同一个函数（__main__.py:284），所以页面和终端给出的报错、候选提示（「是不是 Engine.generate」）完全一样，阶段名的规则只要改一处。代价是同一组阶段解析两次：这里检查一次，子进程里的 trace 再解析一次，真正生效的是子进程里那一次。这里检查只是为了早点报错，免得模型都加载完了才发现函数名写错。`symbols` 由 app 从静态索引里取（app.py:120），只在表单里设了阶段时才去读（app.py:239）。仓库没扫描过时它是 None，这时只能写 `文件路径:qualname` 的形式。超时和停止宽限要大于 0 也在这里查（jobs.py:116）。

`argv`（jobs.py:121）拼命令时，值一律写成 `--x=值`。比如备注是 `-n`：写成 `--note -n`，argparse 会把 `-n` 当成另一个选项；写成 `--note=-n` 就没问题（tests/test_app.py:144 测的就是这个）。被录的命令放在 `--` 后面（jobs.py:138）。CLI 自己先按第一个 `--` 把参数切开，再把前半段交给 argparse（__main__.py:731），所以被录命令的参数不会被 codestrata 当成自己的选项，哪怕里面还有 `--`。仓库路径是位置参数，没法写成 `--x=` 的形式，但它来自项目清单，登记时已经 resolve 成绝对路径（projects.py:59），不会以 `-` 开头。`--roots` 也是例外（jobs.py:137）：它是 `nargs=*`，`--roots=a` 只能带一个目录，只能一个个跟在后面，代码假定目录名不以 `-` 开头。

秒数用 `runs.fmt_seconds` 写（jobs.py:127）：整数不带 `.0`，别的用 repr。以前的 `:g` 只留 6 位有效数字，1234567 秒会写成 `1.23457e+06`（tests/test_app.py:163）。`runs.rerun_command` 给老 run 拼复刻命令时用的是同一个函数（runs.py:1018），两边写出来的秒数一样。

`from_json`（jobs.py:59）只检查类型。表单里的空行（阶段名和函数两格都空的行、变量名为空的行、空的附件行）在这一步丢掉（jobs.py:80），内容对不对留给 `validate`。`from_run`（jobs.py:87）从 run.json 还原表单：
- 命令用 `shlex.join(run["cmd"])` 拼回一行（jobs.py:90），`argv` 里的 `shlex.split` 能把它原样切回去。
- 阶段取的是当时写的 `func`（jobs.py:91），不是当时解析出的 qualname，重录时按现在的代码重新解析。
- 备注不带过来（jobs.py:93），新 run 的备注应该描述新 run。
- tag、`--roots`、`--stop-grace` 表单上不显示，也原样带过来（jobs.py:94）。页面提交时把模板里的这三项原样送回（codestrata/web/home.js:277），所以从菜单复刻出来的 run，录制参数和原来的一样。

tests/test_app.py:152 固定了 `from_json(to_json())` 能原样还原；tests/test_app.py:160 把复刻录出来的 run 和原来的 run 逐项比了录制参数。

### 输出：有界缓冲 + 全局行号
`_pump`（jobs.py:235）在单独的线程里一行一行读子进程的 stdout（stderr 已经合并进来），每一行单独按 UTF-8 解码，坏字节替换掉（jobs.py:237）。因为先按行切再解码，多字节字符不会从中间截断。行存进 `deque(maxlen=MAX_LINES)`（jobs.py:160），另外记一个只增不减的 `n`（jobs.py:161）。大仓库的扫描、长时间的录制可能输出几十万行，内存里只留最后 4000 行，但行号一直往上数。

`snapshot(since)` 用的是全局行号。内存里最早一行的行号是 `n - len(lines)`（jobs.py:180）。since 比这还早时，就从最早一行开始给。返回的 `from` 是实际起点，`from > since` 就说明中间有行被挤掉了（tests/test_app.py:213）。页面每次收到结果后把 since 设成 `n`（codestrata/web/home.js:162），下次只取新行。项目卡片只要任务状态、不要输出，就用 `snapshot(since=n)`（app.py:87），拿到的 lines 是空的。

`add`（jobs.py:171）和 `snapshot`（jobs.py:178）拿的是同一把锁，每个 Job 一把，和 JobManager 的锁无关：`n` 和 `lines` 得一起改、一起读。缓冲区满了以后，如果在读 `n` 和复制 `lines` 之间正好进来一行，这次返回的那一段就会整体错开一行。

结束的任务每个仓库只留最近 `KEEP_DONE` 个（jobs.py:26）。页面只看最近一个（app.py:86），更早的只是占内存，每个最多 4000 行。清理在 `start` 里顺手做（jobs.py:224），这时本来就拿着 JobManager 的锁，不用另起定时器（tests/test_app.py:218）。

`-u`（jobs.py:33）：子进程的 stdout 接的是管道，Python 默认会按块缓冲。不加它，页面要等攒够一整块才看到输出，扫描进度会一下子全冒出来。不用 `PYTHONUNBUFFERED` 环境变量：trace 会把自己的整个环境传给被录的命令（trace.py:880），这个变量就会一路传进去，而 run 记录继承的环境变量时不记它（runs.py:924 的名单里没有）。那样从菜单录的 run 和在终端照抄复刻命令录的 run，输出缓冲就不一样。`-u` 只管 codestrata 这一个进程，不进环境，也不进 run 记下的命令。

### 并发和停止
`start` 在锁里一次做完三件事：查这个仓库有没有正在跑的任务、Popen、登记（jobs.py:214 到 jobs.py:225）。连点两下「扫描」，会有两个 HTTP 线程同时进来；如果检查和登记分开做，两个请求都能通过检查。Popen 失败（比如登记过的仓库目录被删了，cwd 不存在）换成 `JobError`（jobs.py:222），说明直接给页面看（tests/test_app.py:204）。`Busy` 是它的子类（jobs.py:148），app 先接 `Busy` 回 409，其余的 `JobError` 回 500。

子进程开在自己的会话里（jobs.py:220），stdin 接 /dev/null（页面没法往里输入，要读输入的命令会立刻读到 EOF，而不是一直卡着）。停止时只给 codestrata 这一个进程发 SIGINT（jobs.py:253），由 trace 的 driver 按 SIGINT → SIGTERM → SIGKILL 三级停掉被录命令的整个进程组，并把 run 收好（trace.py:865）。

单独开会话，是为了不让终端的 Ctrl+C 直接打到任务上。在起 `codestrata app` 的终端里按 Ctrl+C，信号只到主菜单，主菜单退出前用 `stop_all` 逐个给任务发 SIGINT（app.py:309）。如果任务和主菜单在同一个前台进程组里，trace 会先收到终端的那一下，再收到 `stop_all` 的那一下。trace 会把停止过程中收到的又一个信号当作「升一级」（trace.py:912），被录的命令就可能拿不到 SIGINT 那一级的宽限时间。反过来，同一条规则也让页面上的「停止」按钮在任务结束前一直可以点（codestrata/web/home.js:153）：点第二下就升一级，和在终端里按两次 Ctrl+C 一样。

`on_done` 在读输出的线程里、命令退出之后调用，调用完才设 `ended`（jobs.py:239 到 jobs.py:244）。回调做的事（扫描完重启图服务）算在任务里：页面看到「完成」时图服务已经重启好；重启期间 `active` 仍然认为这个仓库有任务在跑，同一个仓库起不了新任务。回调可以用 `add` 往输出里写一行说明，app 就是这样把「图服务没能重启」写进任务输出的（app.py:101）。回调抛的异常在这里接住、也写进输出（jobs.py:242）：`ended` 设在它后面，异常要是漏出去，读输出的线程就死在半路，这个任务会一直「在跑」，这个仓库再也起不了任务。tests/test_app.py:183 固定了回调被调用时任务还算在跑。`stop_all` 只等命令退出（jobs.py:268），不等回调；主菜单退出时回调如果正在重启图服务，由 viewers 那边兜住：`stop_all` 之后才起好的图服务会被杀掉（viewers.py:78）。

## 不确定 / 局限
- `stop_all` 先发 SIGINT，再给 120 秒（jobs.py:258），够 trace 默认的 SIGINT 宽限 90 秒（__main__.py:666）加上收尾，过了才 SIGKILL（jobs.py:270）。SIGKILL 只打到 codestrata 进程本身，被录的命令在 trace 另开的会话里（trace.py:944），不会跟着死。所以录制设了更长的 `--stop-grace`（复刻会原样带过来），或者收尾（打包、写 run.json）特别慢时，主菜单退出仍可能留下还在跑的服务和一个不完整的 run。
- 主菜单自己被 SIGKILL 时 `stop_all` 根本不会跑：只有 SIGTERM 被改成走 finally（app.py:302）。任务都在自己的会话里，终端关掉也不会替它们收场，扫描、录制和被录的命令都会留下来。它们之后再往 stdout 写，碰到的是没有读端的管道，会怎样没有验证过。
- 任务继承的是起 `codestrata app` 的那个 shell 的环境（jobs.py:219 的 Popen 没传 env），trace 又把它原样传给被录的命令（trace.py:880）。想用别的 venv 跑，只能在命令里写解释器的完整路径，或者用 `--env` 改 PATH。
- 被录的命令的 stdout 直接继承 trace 的（trace.py:944 没重定向），从菜单录时就是这里的管道。命令本身是 Python 的话，它的 print 按块缓冲，页面上会一段一段地出现，不像在终端里一行一行地出。`-u` 只管得了 codestrata 自己；想实时看，可以在表单的环境变量里加 `PYTHONUNBUFFERED=1`，它会记进 run，复刻时也带着。
- 从清单里移除项目时只改清单（app.py:271），这个项目结束的任务还留在 `_jobs` 里，到主菜单退出才释放；重新加回来，卡片上显示的还是那个旧任务。
- 只有遇到 `\n` 才算一行。只用 `\r` 刷新的进度条，要等下一个换行才会出现在页面上。
