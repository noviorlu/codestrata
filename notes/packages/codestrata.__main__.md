---
written_by: claude-opus-5-5
target: codestrata.__main__
kind: package
code_sha: 6f33ae54ec303f7f
status: draft
refs: site.py:79@3f17ec9e,__main__.py:593@a879dfa6,__main__.py:712@cf7a88fc,__main__.py:588@2713e82e,codestrata/__init__.py:5@af14fd0e,__main__.py:311@b87faf5c,__main__.py:305@8ac31b40,__main__.py:258@30b1fec8,__main__.py:271@c90a9ebb,__main__.py:289@059c6e94,__main__.py:306@6109ee57,__main__.py:374@fea936cf,__main__.py:375@80bacee0,__main__.py:363@80bacee0,__main__.py:291@a241b857,runs.py:1007@eaf401c1,trace.py:881@ea5dcb7a,__main__.py:298@de24a4b1,runs.py:1019@af308051,__main__.py:341@a7c090eb,__main__.py:349@f7dc7f40,__main__.py:347@8b67ac5a,runs.py:398@33e517e7,__main__.py:493@dc6fc688,__main__.py:294@e57ae09a,__main__.py:302@3942e934,__main__.py:676@a4a06a24,__main__.py:276@1db8c824,__main__.py:281@02bc94e8,trace.py:1088@85234d16,__main__.py:286@96956389,__main__.py:299@cda3f50d,runs.py:1030@f8bd684b,runs.py:1027@6677f901,__main__.py:315@4c3fac98,trace.py:888@1bb58161,__main__.py:326@392b7b8a,__main__.py:329@5ebaa7e0,__main__.py:332@82d17a7b,trace.py:880@494f49a7,__main__.py:729@d9e158f3,__main__.py:735@e2fa7d7f,__main__.py:301@b52cc777,__main__.py:741@b090c917,__main__.py:746@99fe19eb,__main__.py:749@e462ef87,runs.py:922@42395cbd,runs.py:938@895298bf,__main__.py:515@9b7d29d5,runs.py:802@84b0e0e7,runs.py:1014@7e9eb0f8,runs.py:950@5c69ed98,__main__.py:516@593dce02,runs.py:1016@ef9a2d89,__main__.py:518@6a724090,__main__.py:405@b67404aa,__main__.py:407@b09cd715,__main__.py:685@72d37402,__main__.py:423@09bf7a10,__main__.py:442@49ae8d76,serve.py:270@d751bac7,__main__.py:485@c4688ddf,__main__.py:544@b11d1384,__main__.py:562@1d7387f6,__main__.py:703@78ac2d86,__main__.py:547@a52cc99e,__main__.py:556@499fe1b3,__main__.py:565@cab0d66d,__main__.py:570@03b2082a,__main__.py:50@8964b0de,__main__.py:37@22ae2662,__main__.py:617@f63b232a,__main__.py:619@18d874a4,__main__.py:105@c408ea25,__main__.py:106@9b58cee4,__main__.py:108@77bed867,__main__.py:109@c224cee8,__main__.py:114@7fb1a314,__main__.py:121@739253ed,__main__.py:164@5e4008de,__main__.py:171@a647a88e,__main__.py:175@d4def5e0,__main__.py:630@0310ce23,__main__.py:123@259007e1,__main__.py:161@36d9c30d,__main__.py:126@79e985cd,__main__.py:132@df83b690,__main__.py:129@eabc7f21,payload.py:794@0e2e9052,payload.py:812@555f82c9,payload.py:910@072b54b5,__main__.py:622@54a44379,__main__.py:135@0ae6d77a,site.py:209@c798de4b,__main__.py:137@db8b139d,site.py:182@ec53b40f,__main__.py:139@5ad6f5c2,__main__.py:140@fe8fcd71,site.py:242@79b352b0,site.py:340@9f5b5f67,site.py:208@fe22ebba,codestrata/web/ds.js:233@88884c6c,site.py:133@8ae66cc8,site.py:141@2ac699ba,payload.py:973@88770b5b,site.py:337@4765e572,__main__.py:145@6193323c,site.py:347@36252824,site.py:350@71f63d6d,__main__.py:147@acb03821,site.py:238@a313a553,__main__.py:165@ea1a2f4a,__main__.py:725@9c6178dc,__main__.py:731@ec9fb5ef,__main__.py:599@d41c8ef6,__main__.py:67@04903107,__main__.py:83@d89a80ca,__main__.py:715@ff8358be,__main__.py:716@92f385f2,__main__.py:710@21b0dc95,app.py:289@aceccec4,jobs.py:29@fb4f0ee1,viewers.py:102@1e10e9df,jobs.py:219@91c1c731,jobs.py:31@3aacc8bf,tests/test_app.py:386@56639e09,tests/test_app.py:366@45b7db45,__main__.py:409@adddb262,runs.py:50@00c33eb4,__main__.py:434@9371b1a0,runs.py:789@bbf3acab,runs.py:619@8454fe70,site.py:235@cd48e623,site.py:232@6eb7ceae,site.py:142@ca3d9d97,__main__.py:615@4ea61ab1,__main__.py:102@3b3047c6,__main__.py:623@f845d1f2,__main__.py:136@e64c25ca,trace.py:892@6cf25a9e,__main__.py:254@cd279d19,trace.py:944@6d3a8055,__main__.py:88@0c3e9807,serve.py:456@cba6ca45,codestrata/web/app.js:715@8158920f,__main__.py:587@4c85e081,__main__.py:592@aa53e21c
---

## 是什么
命令行入口：`scan` / `app` / `trace` / `runs` / `serve` / `graph` / `tasks` / `pack` / `note` / `check` 十个子命令。大多数只把参数转交给对应模块；M1（`docs/design/runs.md`）之后多了两块真正的 CLI 逻辑：`cmd_trace` 把每次录制存成一个**新的 run**，`cmd_runs` 管理录下的 run（ls / show / tag / untag / note / rm / merge）。M3 在这两块上各加了一点：`trace --events` 顺带录时序事件（时序图的数据），`runs rm --events-only` 只删事件；trace 的输出和 `runs show` 报事件的摘要，`runs ls` 标一个「时序」（整理失败的标「时序!」）。它还管 .codestrata/ 目录本身：`_outdir` 建目录时顺带写一份 .gitignore 和一份 README.txt。`scan` 一次写出 index.json、symbols.json，以及给全文窗口 Ctrl+点击用的交叉引用 xref.json。M7 起 `graph` 也有了一点 CLI 逻辑：`--hot` 可以给多个（第一个是主 run，其余在导出的单文件里可切换），`--compare` 让主 run 和第二个对比。

M8 又加了两样：`trace --phase 名字=函数`——某个进程第一次进入这个函数时切到这个阶段，分段写在 codestrata 的命令上，不用改 case 脚本；以及「复刻」——`main` 把原样的 codestrata 命令和当前目录记下来（`invocation`），`cmd_trace` 另记录制时 shell 里相关的环境变量（`env_inherited`），`runs show` 打印一条能照抄的复刻命令（原来那一行叫「重录」）。

M8.1 给 graph 加了 `--public`：导出的页面要放到公网上（设计 M8.1，用户要放到 GitHub Pages）时，主目录写成 `~`，run 元数据里 PATH 这类目录列表只留仓库和录制目录下面的段。怎么改写全在 `payload.publicize`；`cmd_graph` 只算「要保留哪些目录」交给它（见下面「graph --public」一节）。

M8.2 给 graph 加了 `--link github`（设计 M8.2，README「源码从 GitHub 取」）：不再导出单文件，而是导出一个目录（index.html + data/<版本>/）。页面运行时按**提交号**从 GitHub 取源码（导出时仓库的 HEAD，site.py:79——help 和注释说「扫描时的提交号」，scan 本身并不记提交号；默认 jsDelivr，不行再 raw.githubusercontent.com），在浏览器里高亮；codestrata 自己算的数据放在 data/ 里按需加载，于是没有单文件 16 MB 的上限，放 GitHub Pages 用。配套两个开关：`--code-base URL`（可重复）换掉取源码的地址模板，`--no-remote-check` 导出时不去 GitHub 试取一个文件。怎么导出全在 `codestrata/site.py` 的 `site.export_site`；`cmd_graph` 只校验 `--out`、把命令行参数交过去、把它返回的摘要打印出来（见下面「graph --link github」一节）。

主菜单（README「不想敲命令也行」）加了第十个子命令 `app`：在浏览器里挑文件夹、点按钮扫描 / 录制运行 / 打开图。CLI 这边只有两处：`cmd_app` 把 `--port`（默认 8930）和 `--no-browser` 交给 `app.main`（__main__.py:593）；`serve` 多了一个藏起来的 `--home`（__main__.py:712），由 `cmd_serve` 原样交给 `serve.main`（__main__.py:588）。另外「用当前解释器叫起 codestrata」的那条命令收进了包本身：`_prog` 的退路和主菜单起子进程用的都是 `codestrata.self_command`（codestrata/__init__.py:5），不再各写一份。项目清单、后台的扫描 / 录制任务、每个项目的图服务都在 `app` / `projects` / `jobs` / `viewers` 里，这里不碰（见下面「app 和 serve --home」一节）。

所有 `--hot` 的参数现在叫 RUN（模块 docstring 末尾）：完整的 run id，或 case 名（取它最新一次录完的），后面可以加 `@阶段`。解析全在 `runs.resolve`，这里不碰：graph（字面去重后，每个 `--hot` 各调一次）/ tasks / pack 透传给 `payload.load_hot`；serve 的 `--hot` 交给 `serve.main`，M4 起它只决定页面打开时先选哪个 run，页面上随时能换，换 run 不用重启 serve。只有 graph 的 `--hot` 能重复：tasks / pack 的仍是单个（`notes.prompt_pack` 只收一个 hot），serve 的也是单个——对比在页面上现选（工具栏「对比」，地址里记 cmp=），不用在命令行上给。

## 为什么这样切
它是唯一的入口层（高度 +1）：出边 12 条（M8.2 多了 `site`，主菜单多了 `app`，之后又多了包本身 `codestrata.__init__`：`_prog` 调它的 `self_command`），没有人依赖它。原则还是「薄」：`cmd_*` 解析参数、调模块、打印摘要。`cmd_trace` 和 `cmd_runs` 占了文件一半多，但里面放的仍是 CLI 该管的事——参数校验（`--env` 的 K=V、tag 的字符集、`--attach` 的路径、`--phase` 在建 run 之前先解析）、摘要怎么打印、删之前的交互确认，以及只有入口才拿得到的东西（原样的 argv、启动时的当前目录和环境）。run 是什么、REF 怎么解析、收尾 / 重算 / 删除的规则、事件怎么整理成 span、复刻命令怎么拼、哪些环境变量算「相关」，都在 `runs`（和 `codestrata/events.py`）里；`--phase` 的函数怎么认、阶段怎么切在 `trace` 里；公开导出怎么改写在 `payload.publicize` 里，这里只给它要保留的目录（仓库和各 run 录制时的目录，要解析 REF、读 run.json 才拿得到）；链接模式的目录怎么导出（读 git、判哪些文件要随页面带上本地版本、引用倒排分桶、试取 GitHub、写目录）在 `site.export_site` 里，这里只管 `--out` 给了、不以 .html 结尾，参数原样交过去，摘要怎么打印。这里只读 run.json 里现成的 `events` 摘要和 `phase_log`，不 import `events`。

三条边界值得注意：
- **录制是在这里缝起来的**：`runs.new_run` 建目录 → `trace.run` 跑命令 → 经 `after` 回调调 `runs.finalize`（__main__.py:311）。`runs` 依赖 `trace`，`trace` 不 import `runs`，所以 `trace.run` 只开一个 `after` 口子，由上层把收尾塞进去。
- **事件的开关只是一个环境变量**：hook 在被 trace 的进程里看 `CODESTRATA_EVENTS` 是不是 "1"，CLI 每次都把它明确写给命令——`--events` 时 "1"，否则 "0"（__main__.py:305，理由见下）。录不录、怎么配对、上限，全在 `trace` 的 hook 里。
- **删除的安全规则两层都有**：`cmd_runs` 的 rm 先把每个参数查一遍（完整 id、不在录）再统一确认，一个不对就一个都不删；`runs.remove` / `runs.remove_events` 自己也再挡一次（后者还拒绝删还有进程在往 parts/ 写的 run）。

图上它的出边没有虚线：每条都真的调用了对方的函数（`serve`、`site`、`app` 都是在函数体里 import 的，也各算一条边；`xref` 由 `cmd_scan` 直接调 `build` / `write`；`codestrata.__init__` 由 `_prog` 调 `self_command`）。

## 读法
1. 模块 docstring —— 子命令一览（graph 那行写成 [--hot RUN]… [--compare]，说的还是「导出单文件 HTML」；`--public`、`--link` / `--code-base` / `--no-remote-check` 和 --per-pkg / --fragment / --out 一样没写进这一行，看 graph --help），以及 RUN 的写法
2. `main` —— argparse 的搭法：`runs` 的两级子命令、trace 的开关（含 `--events`、`--phase`）、rm 的 `--events-only`，最后的 stdout 重配、记 `invocation`、切 `--`；紧跟着的 `_prog` / `_cwd` 是记 `invocation` 用的
3. `cmd_trace` —— 一次录制从建 run 到打印结果的全过程，对照设计文档 4.2 读；事件相关的是 `env_run` 和打印里 `ev` 那一段；M8 相关的是开头解析 `--phase` 的一段、`new_run` 的 `invocation` / `env_inherited` 两个参数、打印里 missed / shadow 两句警告
4. `cmd_runs` —— 按动词分段；ls / show 是纯展示（show 的末尾是复刻命令和继承的环境），rm 是唯一不可逆的
5. `_outdir` 和 `_README` —— 很短，但写明了 .codestrata/ 里哪些能删
6. `cmd_graph` —— 按先后：多个 `--hot` 的四道检查（三道看字面，一道看解析到的 run）；`--public` 算 keep 目录的一段（两种导出共用，所以在分叉之前）；`--link` 的分支（校验 `--out`、调 `site.export_site`、打印它的摘要，提前返回）；之后才是单文件那一路——`export_payload`、带 `--public` 时 `payload.publicize`、`render.export`、默认文件名、各部分大小的打印。单文件的数据怎么拼在 `payload.export_payload`，链接模式的目录怎么写在 `site.export_site`
7. `cmd_scan` 及其余 `cmd_*` 按需看，都很短（`cmd_serve` / `cmd_app` 各只有一行调用；`main` 里 serve 的 `--home` 和 `app` 子命令的定义在 __main__.py:712 起）

## 关键算法
### trace：每次都是新的 run，收尾在 driver 的信号处理器保护下做
以前 `cmd_trace` 把结果写成 `trace-<case>.json`，同名 case 重录就覆盖——而一次录制可能是几分钟的 GPU。现在的流程：
1. **先校验，再建目录**（__main__.py:258 起）：`--env` 必须是 K=V；`--tag` 只能用 `_TAG_RE` 里的字符；`--attach` 的文件必须存在；`--phase` 也在这一段解析完（见下面「--phase」一节）。case 名在 `runs.new_run` 里校验，也在建目录之前。参数填错不会留下一个空 run。
2. **`--attach` 的相对路径先按仓库根目录找**（命令就是在那里跑的），找不到再按当前目录（__main__.py:271），存成绝对路径。被 case 脚本 source 的 common.sh 不会出现在任何进程的 argv 里，只能靠它存进 run。
3. **`runs.catalog` 先把老格式的 trace 迁进 runs/**（__main__.py:289），再由 `runs.new_run` 建目录、写 `status: recording` 的 run.json（复刻要用的 `invocation`、`env_inherited` 也在这一步写进去，见下面「复刻」一节）。录制开始前就把 run id 和目录打到 stderr（__main__.py:306）。`mono0_ns` 从刚写的 run.json 里读回来交给 `trace.run`，所以各阶段、各进程的时刻（包括事件的时刻）都相对 run.json 里记的同一个零点。
4. **收尾放在 `after` 里**：`trace.run` 的信号处理器一直装到 `after` 返回，打包 parts 的中途按 Ctrl+C 不会把 run 弄成半截（设计文档 4.3「driver 的信号」）。事件日志的打包和整理也在 `runs.finalize` 里，同样受保护。
5. **打印**：状态（`_STATUS` 译成中文，外加 problems）、进程数（单列跑到仓库代码的）、各阶段的函数数、`--phase` 没切到 / 被 case 脚本同名阶段占掉的警告（见下面「--phase」一节）、跑的若是安装包就说明映射回仓库后是否逐文件一致（不一致的文件行号不可信）、时序事件的摘要（见下一节）、命令退出后停掉的残留进程、存下的文件、没存下来的 `--attach`。
6. **建议一条叠图命令**（__main__.py:374）：写的是**完整 id**——case 名会解析到该 case 最新一次 ok 的 run，这次若是 partial，用 case 名叠的就不是它；run 里有 serving 阶段就加 `@serving`，因为启动时的初始化会淹没请求本身。
7. **退出码**（__main__.py:375；还没 scan 提前返回的那条在 __main__.py:363，同一个规则）：只有 failed（一个函数都没录到）返回 1，partial 也返回 0。

其余开关：`--stop-grace`（默认 90 秒）是停的时候 SIGINT 之后等多久再发 SIGTERM，留给 case 脚本自己的 trap 收尾；`--env` 只把这些变量加给命令并记进 run，不抓整份环境（设计 1.1：防止把 token 存进去；M8 另记的 `env_inherited` 也只取白名单里、名字不像密钥的，见「复刻」一节）；`--roots` 或自动探测的包根算出「顶层包 → 仓库内目录」（__main__.py:291），命令跑的若是 pip 安装的那份，trace 靠它映射回仓库。

### --events：以命令行为准，run 里记的是「要了事件」
- **变量只给命令，而且总是写明**：`env_run` = 用户的 `env` 加上 `CODESTRATA_EVENTS`（"1" 或 "0"，__main__.py:305），传给 `trace.run` 的是它，传给 `runs.new_run` 的仍是用户的 `env`。
  - 为什么不记进 run 的 env：那里的语义是「用户给命令加的变量」，复刻命令里它们都是 `--env`——按参数拼时逐个写；有原样命令时，argv 里没写过的键也会补成 `--env=K=V`（runs.py:1007）。把内部开关混进去，复刻命令里就会多出一个用户没写过的 `--env=CODESTRATA_EVENTS=…`，和 `--events` 重复。
  - 为什么不带 `--events` 也要写 "0"：`trace.run` 给命令的环境是整份 `os.environ` 再叠 `env_extra`（trace.py:881）。shell 里恰好 export 了 `CODESTRATA_EVENTS=1` 的话，不写 0 就会悄悄录事件，而 rec 里记的是没要、复刻命令里也没有 `--events`（`env_inherited` 的白名单里也没有这个变量）——录出来的 run 和它的复刻命令对不上。写明之后开关只有 `--events` 一个：`env_run` 里它写在后面，`--env CODESTRATA_EVENTS=1` 也会被盖掉。
- **意图记在 rec 里**：`"events": bool(a.events)`（__main__.py:298）。有原样命令（`invocation`）的 run，复刻命令就是当时敲的 argv，本来就带着 `--events`；rec 里这一项留给没存原样命令的 run——`runs.rerun_command` 按参数拼时看到它就加 `--events`（runs.py:1019）。记的是「要了」，不是「录到了」：录空了、或之后被 rm --events-only 删了，复刻命令照样带 `--events`。
- **三种结果三种说法**（__main__.py:341 起），数据都是 `runs.finalize` 写进 run.json 的 `events` 摘要：
  - 有 `error`：整理成 span 失败。原始日志已经先落进 events/raw.tar.gz，所以提示可以 `runs merge` 重来；
  - 正常：事件行数 → span 数（第一级折叠之后，连续的同类叶子调用合成一条，所以不多于调用次数）、跨文件调用次数（各 span 的 rep 之和）、原始日志压缩后的大小；
  - 要了 `--events` 却没有摘要（__main__.py:349）：`runs` 在没有任何事件日志时不写摘要。原因列了三种——命令没起来；被 trace 的 Python 低于 3.12（hook 只在有 `sys.monitoring` 时录）；或者这次根本没有跨文件的调用（缓冲是空的，hook 就不建日志文件）。最后一种是正常结果，不是故障，所以提示里不能只怪 Python 版本。这里明说出来，免得以为录到了。
- **到了行数上限是 ⚠，不是状态**（__main__.py:347）：上限只管新的调用行，计数是完整的；`runs.derive` 故意不把它算进 status（runs.py:398）——算进去 run 会变成 partial，拿 case 名解析时就跳到更早的一次 ok。所以 CLI 这边只在摘要后面挂一句「N 个进程到了行数上限，之后的调用没记时序（计数完整）」；`runs show` 用同样的说法，另把 pid 列出来——多于 8 个只列前 8 个、后面加「…」（__main__.py:493），好让人知道列表不全。
- **行数上限从 shell 继承时，要记进 run 的 env**（__main__.py:294）：hook 同样读 `CODESTRATA_EV_MAX`。带了 `--events`、shell 里 export 了它、`--env` 里又没给时，CLI 把 shell 的值抄进 `env`——意图是让它记进 run、出现在复刻命令里：按参数拼时写成 `--env=CODESTRATA_EV_MAX=…`；有原样命令时 argv 里没有它，`runs.rerun_command` 把它补成 `--env=` 插在 `--` 前面（runs.py:1007），这次录制的上限才复现得出来。`env_inherited` 是在这之后算的、`skip=env`（__main__.py:302），所以它不会在继承的环境里再出现一次。和开关的处理正好相反：`CODESTRATA_EVENTS` 以命令行为准、主动盖掉 shell；上限不盖，只把 shell 里悄悄生效的值写明。只在 `--events` 时抄（不录事件时上限没有意义，不该混进 run 的 env）；`--env` 给了的以 `--env` 为准。这一步放在 `runs.new_run` 之前：`new_run` 当场把 `env` 写进 run.json，之后不再改它，放在后面就只给了命令、没记下来（早先就是这样错的，test_events_cap 里有从 shell 继承的用例）。

### --phase：录之前解析，录完报没切到的（M8）
起因（设计 M8）：离线示例是一条阻塞的 python 命令，shell 看不到模型什么时候加载完，没法往 PHASE 里写阶段，启动和推理混成一段。`--phase 名字=函数` 让「第一次有进程进入这个函数」成为阶段的起点，参数可重复（__main__.py:676 起的 argparse 定义）。切阶段本身在 `trace` 的 hook 里（每个阶段整个 run 只切一次，靠 `parts/PHASE-<名字>.fired` 的 O_EXCL 标记），CLI 只管三件事：
1. **解析放在最前面**（__main__.py:276 起）：在 `_outdir`、`catalog` 迁移、`new_run` 之前。函数写错了当场报，不等模型加载完才发现，也不留空 run。`模块:qualname` 的写法要查静态索引：没 scan 过时 `_load_index` 会 SystemExit，这里吞掉、给 `resolve_phase_at` 传 None（__main__.py:281），由它报「模块:qualname 的写法要查静态索引，先 codestrata scan；或者写成 文件路径:qualname」（只在真用到模块写法时才报）。格式、阶段名（不能叫 start、不能重名）、函数在不在、继承来的方法按 MRO 找、两个阶段不能指到同一个函数，都在 `trace.resolve_phase_at` 里查（trace.py:1088）；注意 `文件路径:qualname` 的相对路径只按仓库根目录算、必须在仓库里，不像 `--attach` 还会退回当前目录。
2. **解析结果打到 stderr**（__main__.py:286）：每个阶段一行——阶段名、换成解释器里的 qualname、定义所在的 file:line；继承来的方法另注「是继承来的，定义在 …」（`via`）：写的是子类上的名字，hook 实际认的是基类里那份代码，要让人看见。
3. **存进 run，交给 hook**：rec 的 `phase_at` 只留 name / func / file / qualname / line（__main__.py:299），给网页的阶段表，以及没存原样命令时拼复刻命令（`--phase=名字=函数`，runs.py:1030）；rec 同时记下 `--roots`（__main__.py:298），按参数拼时带上（runs.py:1027）。完整的解析结果交给 `trace.run`（__main__.py:315），由它明确写进 `CODESTRATA_PHASE_AT`（没有就是 []，shell 里的旧值不生效，trace.py:888）。

**录完的两句警告**（__main__.py:326 起）。数据是 run.json 的 `phase_log`，每条 `[名字, t_us, 来源]`，来源 start / sh（case 脚本写 PHASE 切的）/ hook（`--phase` 切的）；收尾时 `trace` 从 `PHASE-*.fired` 标记里补齐 hook 那几条（`trace.merge_phase_log`）。没有 hook 条目的 `--phase` 各报一句：
- **没切到**（__main__.py:329）：连 sh 条目也没有——提示说「对应的函数这次没被调用」。
- **被脚本同名的阶段占了**（__main__.py:332）：有 sh 条目、没有 hook 条目。case 脚本先 echo 了同名阶段，driver 替它建了 sh 标记，之后 `--phase` 的函数再被调用也不会再切，这一段的起点是脚本写的时刻、不是函数被调用的时刻，所以要说「同名的 --phase 没起作用」。

### 复刻：原样的命令 + 在哪跑的 + 继承的环境（M8）
用户要的是照着录下的那次再录一次。只存 `--env` 不够：被 trace 的命令继承 shell 的整份环境（trace.py:880），相对路径又取决于当时在哪个目录。所以分三处记：
- **`main` 记原样的命令**（__main__.py:729）：在按 `--` 切开、`parse_args` 之前取整份 raw（`--` 和后面被 trace 的命令都在里面），前面加上 `_prog` 给出的「怎么叫起的 codestrata」，连同当前目录挂到 namespace 上（__main__.py:735）。每个子命令都挂，只有 trace 用；`cmd_trace` 用 `getattr(a, "invocation", None)` 取（__main__.py:301），不经 `main` 直接调的就存 None，之后按参数拼。
  - `_prog`（__main__.py:741）：装好的入口脚本（比如 .venv/bin/codestrata）记成绝对路径，复刻时叫到的是同一份安装；`sys.argv[0]` 是 …/__main__.py（`python -m codestrata`）或 `-c` 的，记成 `self_command()` 给的 `sys.executable -m codestrata`（codestrata/__init__.py:5，__main__.py:746）；程序里直接调 `main(argv)` 的（测试）也走后一种。主菜单的 jobs / viewers 起子进程用的是同一个函数，这个前缀只写在一处。
  - `_cwd`（__main__.py:749）：当前目录已经被删时 `os.getcwd` 会抛 OSError，这里给 None，不让 CLI 在最前面崩。
- **`cmd_trace` 记继承的环境**（__main__.py:302）：`runs.inherited_env(os.environ, skip=env)`——只取白名单（CUDA_ / VLLM_ / PYTORCH_ / HF_ / NCCL_ 等前缀，PATH / PYTHONPATH / LD_LIBRARY_PATH / VIRTUAL_ENV / CONDA_PREFIX / CODESTRATA_EV_MAX 等，runs.py:922）；名字按 `_` 分段后像密钥的（TOKEN / KEY / SECRET / PASS / AUTH …）不记；值里 URL 的账号密码换成 `<已隐去>`；`--env` 已经写明的不重复（runs.py:938）。取的是 CLI 进程自己的 `os.environ`，正是 `trace.run` 交给命令的那份底子，PYTHONPATH 是注入 hook 之前的样子。
- **`runs show` 打印**（__main__.py:515 起）：
  - 「复刻」一行是 `runs.rerun_command(run, Path(a.repo))`，没传 redact，所以 `--env` 里像密钥的值原样给出——网页和导出（会发给别人）里的那份是 redact=True 的（runs.py:802）；`graph --public` 的导出里再把主目录写成 `~`、PATH 类目录列表里仓库和录制目录以外的段收成 …（见「graph --public」一节），`runs show` 两样都不做。有原样命令时是 `cd <当时的目录> && <原样 argv>`（runs.py:1014），codestrata 自己加进 run env 的（上面说的 CODESTRATA_EV_MAX）补成 `--env=`；不是 UTF-8 的参数写成 `$'…'`（runs.py:950），照抄能还原原来的字节。
  - 老 run（没存 `invocation`）按 run 里存的参数拼，并在下面注一句「这个 run 录的时候还没存原始命令，上面是按 run 里存的参数拼的」（__main__.py:516）。拼出来的仓库路径是 run 里记的 cwd（录制时解析过的绝对路径，runs.py:1016），不是这次 `runs show` 敲的 repo；`Path(a.repo)` 只在 run 里连 cwd 都没有时才用上。
  - 有 `env_inherited` 时在下面逐行列出（__main__.py:518），标题写明「不在命令里，复刻时要一样」；复刻那一行本身不带 `env K=V…` 前缀（没传 with_env）。

### runs：只读的动词不建 .codestrata，rm 只认完整 id
- **入口先查仓库目录和 .codestrata/ 都在**（__main__.py:405、__main__.py:407），不调 `_outdir`：路径写错（比如少写了 src/vllm-omni）要报出来，而不是悄悄建一个空的。`runs` 的 repo 是必填位置参数（__main__.py:685），不像别的子命令默认 `.`——设计 1.1：可省略的 repo 会把动词当成自己。
- **ls**：第一行打印 runs/ 的真实路径，是软链时注明（vllm-omni 的 runs 在 /mnt/data 上）。按 case 分组，组的先后按该 case 最新一次 run 的时间（`catalog` 新的在前，__main__.py:423）。每行：id、状态（driver 已经没了的 recording 显示成「中断」，即 `status_shown`）、时长、跑到仓库代码的进程数、git 短哈希、相对当前 index 改过的文件数、大小（`_run_size` 现走目录）、「时序」标记、tag、备注；总量超过 1 GB 时提醒。
  - 「时序」只在 `events` 摘要存在**且没有 `error`** 时标（__main__.py:442）：标记的意思是「有 span、时序图能看」，整理失败的 run 没有 span，标了会误导。整理失败的标「时序!」：它有原始日志、可以 `runs merge` 重来，和没录事件的 run 不是一回事，不该要 show 才看得出。页面上 serve.py:270 对整理失败给 events=false、另给 events_error=true：下拉里不标「时序」，工具栏的「时序图」按钮置灰、提示写的是「整理失败，runs merge 重来」而不是「没录」。没有摘要时留四个空格（和「时序」同宽），后面的 tag 列不错位。
- **show**：解析 REF，打印 run.json 和 detail.json 的摘要；run 有 `events` 摘要时多一行「时序」（__main__.py:485）：span 数、调用次数、进程数、原始日志大小，到了上限的进程或整理失败也在这一行说。文件状态由 `runs.file_state` 相对**当前 index** 算（不是工作区：叠加用的行号来自 index），每种最多列 12 个（`_FS` 是状态的中文名）；最后是复刻命令和录制时继承的环境（__main__.py:515，见上一节）。
- **tag / untag / note 接受 case 名，rm 不接受**：前者改的是该 case 最新一次 ok 的 run，改错了能改回来；rm 删错了没法重建（设计 4.3 末尾）。rm 先把所有参数查完——去重（`dict.fromkeys`，同一个 id 写两遍只删一次）、必须是完整 id（是 case 名时报错里列出这个 case 的所有 run，方便复制）、不能在录（__main__.py:544）——再列出要删的东西和大小。没有 `--yes` 时，终端里要答 y；不是终端就直接拒绝（__main__.py:562），脚本里不会误删。
- **rm --events-only**（参数在 __main__.py:703）：走完全相同的检查；查完先挑出**没有时序事件**的 run——既没有 events/，parts/ 里也没有散着的 ev-*.log（__main__.py:547 起）——各打印一句「没有时序事件」，不问也不删，全都没有就直接返回 0：没东西可删还要答 y/N 只是噪音，之后再打「删了 … 的时序事件」更会让人以为真删了什么。看的是磁盘而不是 run.json 的 `events` 摘要：还没 merge 的中断 run 没有摘要，原始日志却散在 parts/ 里。剩下的照常确认，说的都是事件那一块——列表里的大小是 events/ 加上 parts/ 里散着的 ev-*.log（__main__.py:556，标「（时序事件）」），正好是 `runs.remove_events` 要删的那些：不拿整个 run 的大小，免得看起来能腾出的空间比实际大，也不会让中断 run 显示 0B；确认语是「删掉这 N 个 run 的时序事件？不能重建。」（__main__.py:565），非终端的拒绝语是「删时序事件要确认」；最后调 `runs.remove_events` 而不是 `runs.remove`（__main__.py:570）。它删 events/（原始日志和 span 都删；还没 merge 的中断 run 连 parts/ 里散着的事件日志一起删），计数和其余数据留着，run.json 的 `events` 置空，ls 的「时序」标记随之消失。为什么也要完整 id 和确认：原始事件日志是原始数据，删了不能重建，和删整个 run 同级。用处是事件是 run 里最大的一块（设计 7.3 估算原始日志 gzip 后 4–6 MB），想留着叠图的计数、不要时序时可以只删它。
- **merge**：转给 `runs.merge_run`（从原始分片重算派生数据，M3 起也从 events/raw.tar.gz 重建 span，M8 起也用 `trace.merge_phase_log` 按包里的 `PHASE-*.fired` 标记重算 `phase_log`——已有的 start / sh 条目保留，`--phase` 切的以标记里的时刻为准、轮询漏掉的补上）。

### _outdir：.gitignore 和 README.txt
每次 `_outdir` 被调用（scan、trace、不带 `--out` 的 graph、tasks --write），缺哪个就写哪个（__main__.py:50），已有的不覆盖：
- **.gitignore 内容是 `*`**：整个 .codestrata/ 不进被分析仓库的 git。实测 vllm-omni 的 git status 一直显示 `?? .codestrata/`——被分析的仓库不该因为用了 codestrata 多出未跟踪文件。
- **README.txt（`_README`，__main__.py:37）**：除 runs/ 以外都能删、都能重建；runs/ 是 trace 录下的运行数据，不能重建。老的说法「.codestrata 随时可重建」到 M1 就不对了，以后的会话照着它 `rm -rf` 就会丢掉 GPU 录的数据。它是设计文档「误删 runs/」的四道防线之一（另外三道：runs/ 可以是软链、仓库 README、agent 记忆的修正）；是软链时 `rm -rf .codestrata` 只删链接本身。

### graph：多个 `--hot` 和 `--compare`（M7）
graph 的 `--hot` 改成可重复（__main__.py:617）。第一个是主 run，和以前一样全量嵌入（hot、hotMeta、graphHot，以及每条边带调用明细的边详情）；其余的作为 others 交给 `payload.export_payload`，只带它们在导出切面上的节点次数、边次数和精简过的 meta（EMB.hotBy），页面上能切过去，但边详情的调用明细只有主 run 的（设计第 8 节）。为什么不每个都全量嵌：单文件有 16 MB 的上限，`export_payload` 先把其余部分算好，剩下的额度才给全文，每多全量嵌一个 run，挤掉的就是全文。`--compare`（__main__.py:619）让主 run 和第二个对比：嵌一个 cmp 块，边详情每项带上 B 的次数（`payload.edge_compare`）；第三个起仍然只是可切换。

调 payload 之前，`cmd_graph` 先做四道检查（__main__.py:105 起），先后顺序是有意的：前三道只看命令行上的字面，第四道要等 `payload.load_hot` 把每个 REF 解析成 run 之后才做得了。
1. **空值直接拒绝**（__main__.py:106，全是空白的也算）：脚本里写 `--hot "$A" --hot "$B"`、变量没设，就是这种情况。`payload.load_hot` 把空的 ref 当成「不叠」，返回 (None, None)。只有一个 `--hot` 的时候，这只会悄悄导出一张没叠加的图；有了多个就不一样了：第一个是空的，主 run 就没了，后面的 run 照样嵌进 hotBy，`--compare` 也悄悄失效；后面某个是空的，取它 meta 的 run_id 时会出错。所以在这里直接报「脚本里的变量没设？」，不往下走。
2. **按字面去重**（__main__.py:108，`dict.fromkeys`，保持先后）：同一个 REF 写两遍只留一份，也就只 `payload.load_hot` 一次（每次都要读 run、往 stderr 打一行解析结果）。放在 `--compare` 的检查前面，这样 `--hot A --hot A --compare` 报的是「要给两个」，而不是拿 A 和它自己比，文件名里也不会出现 A+A。
3. **`--compare` 至少要两个**（__main__.py:109）：不够就报错，而不是悄悄导出一张没有对比的图。
4. **按解析到的 run 再去一遍重**（__main__.py:114 起）：键是 run id 加 `@阶段`，和 `export_payload` 给 hotBy 起名用的是同一个。case 名和它的完整 id 写法不同，却会解析到同一个 run，字面去重拦不住。主 run 的键先放进 seen，所以重复的是主 run 时，丢的是后面那份精简的，留下主 run 那份全量的（test_compare_and_multi_export 里有这个用例）。键里带阶段，是因为 demo 和 demo@serving 是同一个 run 的两份不同数据（全部阶段相加 / 只看 serving），两个都该能切换、能对比。去完还带着 `--compare` 却没剩下别的 run，直接报错（__main__.py:121，「解析到的是同一个 run（同一阶段），没有可以对比的」），理由和第 3 道一样。
   - 为什么不能只靠 `export_payload`：它也按同样的键去一遍重（现在对 `cmd_graph` 传进去的已经是空操作，留着是它自己接口的保证），可它去重的结果 `cmd_graph` 看不到。以前只有它去重时，`--hot demo --hot <demo 最新那次的完整 id> --compare` 能过第 3 道，摘要照写「另带 1 个 run 可切换」「对比前两个」，实际上 hotBy 是空的、也没有 cmp 块。现在摘要里的数就是去重后的 others 的长度，和导出文件里 hotBy 的条数一致；`--compare` 要么真有 cmp 块，要么报错。

**默认文件名**（__main__.py:164）：各个 REF 用 `+` 连起来，`--compare` 时再加 -vs，比如 overview-a+b-vs.html；没给 `--hot` 时仍然是 overview.html。（只有单文件那一路有默认文件名；`--link` 没给 `--out` 直接报错，见「graph --link github」一节。）把所有 REF 都放进名字，是为了让同一对 run 的导出不覆盖单个 run 的导出；加 -vs，是因为带对比的文件内容不一样（多了 cmp 块和 B 的次数），不该和不带对比的共用一个名字。字符白名单见下一节。

**打印**（__main__.py:171 起，单文件那一路；链接模式的摘要形状不同，见「graph --link github」一节）：原来那行摘要后面多了「另带 N 个 run 可切换」「对比前两个」（N 是第 4 道去重之后的数）；下面再打一行各部分的大小（__main__.py:175）：graph、graphHot、edges、sources、files、hotBy、cmp 这几块各自 `json.dumps` 之后的长度。为什么要打：设计第 8 节说大小预算沿用 `export_payload` 的额度、命令最后打印各部分大小。多带一个 run，最后被挤掉的是全文（files 只拿剩下的额度），把这几块打出来，才看得出这 16 MB 花在了哪里。量法和 `export_payload` 算额度的一样（ensure_ascii=False 下的字符数，不是 UTF-8 字节数），所以能直接和预算比。空的块（"null"、"{}"，不超过 4 个字符）不打。带 `--public` 时 `pl` 已经换成 publicize 之后的那份，摘要里的 KB 和各部分量的都是改写后的。

### graph --public：keep 目录在这里算，怎么改写在 payload（M8.1）
导出里到处是本机路径：源码、解读、run 元数据里的命令和 argv 都可能带着主目录；PATH / LD_LIBRARY_PATH / PYTHONPATH 这类目录列表还列出了本机装了哪些工具。`--public`（__main__.py:630）在 `cmd_graph` 里分两处：算 keep 的一段（__main__.py:123 起）在第 4 道检查之后、两种导出分叉之前——链接模式也要它（见下一节），所以 M8.2 把它从 `export_payload` 之后挪到了前面，`keep = []` 先给空的；调 `payload.publicize` 的一行（__main__.py:161）留在单文件那一路，`export_payload` 之后、`render.export` 之前：
1. **keep = 仓库 + 各 run 录制时所在的目录**：先放仓库（resolve 过的绝对路径，__main__.py:126）；再对每个 REF 取录制目录——有 `invocation` 的取它的 cwd（敲 codestrata trace 时 shell 所在的目录），没有的（老 run，或录制时当前目录已被删、cwd 是 None）退回 run 里记的 cwd，也就是录制时的仓库根目录（__main__.py:132）。为什么要录制目录，注释说的是「PATH 里的 venv 往往在那下面」：比如 vllm-omni 是在 duplex-agents/vllm-omni 下敲命令、仓库是它下面的 src/vllm-omni，venv/ 在前者下面（那里录的 run，`--env PATH=` 的第一段就是 duplex-agents/vllm-omni/venv/bin），只留仓库的话它也会被收成 …。
2. **REF 要再解析一遍**（__main__.py:129）：`load_hot` 给的 meta 里只有拼好的复刻命令，没有 run.json 里原始的 `invocation` / cwd，所以这里对每个 REF 调 `runs.resolve` 重读。遍历的是字面去重后的 refs（和文件名用的同一份），第 4 道去掉的「写法不同、同一个 run」只是多算一遍，结果一样。`SystemExit` 吞掉、跳过这个 REF（__main__.py:129）：同一批 REF 刚被 `load_hot` 解析成功过，正常走不到这里。
3. **交给 `payload.publicize(pl, str(Path.home()), keep)`**（__main__.py:161；函数在 payload.py:794）：所有字符串里的主目录写成 `~`（源码行里换了的，这一行上 Ctrl+点击的列号按 UTF-16 挪，跨着主目录的名字去掉）；run 元数据（hotMeta、hotBy 各项的 meta、cmp 的 meta_b）里的复刻命令（先按 shell 规则切开、收完再用 `runs._q` 重新加引号）、cmd、各进程 argv 和 `env_inherited` 里这三种目录列表，只留 keep 下面的段，其余连续几段合成一个 …。命令和 argv 是按参数认的：参数以 `PATH=`（或 `--env=PATH=`）这类开头才收，等号后面整段当目录列表；写在一个参数中间的（比如 `bash -c "export PATH=…"`）不收。别处——case 脚本原文、run 的备注、源码、解读正文——写的 PATH=… 都不收（主目录照样换成 `~`）。keep 里空的、`/`、主目录本身和它的上级，publicize 会剔掉（payload.py:812）——留着的话 PATH 里在它下面的段全都原样留下（`/` 就是整条；主目录的话 ~/.local/bin、conda 这类本机工具目录都会漏出去）。所以直接在主目录下敲的 trace，录制目录这一项等于没给，只剩仓库。
4. **还剩主目录就不写出**：publicize 最后把整个 payload dump 成 JSON 再查一遍主目录，有就 SystemExit（payload.py:910）。这发生在 `render.export` 和 `out.write_text` 之前，拒绝时不会留下半个公开页。（链接模式在 site 里也走这一道，另外还有一道写完之后的检查，见下一节。）
5. **页面上注明**：publicize 置 `pl["public"] = True`，前端（`codestrata/web/ds.js` 里的 CS.ds.public、`codestrata/web/app.js` 的 runHtml）据此在帮助的复刻块里（run 有复刻命令时）加一句「这是公开页」：路径里的主目录写成了 ~、PATH 这类目录列表里项目以外的部分省略成了 …，所以命令不能原样执行，原样的在录制的机器上用 `codestrata runs <repo> show <run id>` 看。不带 `--public` 的导出照旧原样（本机自己看，test_public_export 里两种都导出来比过）。

### graph --link github：在 keep 之后分叉，其余交给 site（M8.2）
单文件导出受 16 MB 所限（vllm-omni 1600 多个文件只装得下两百多个）；扫的仓库在 GitHub 上时，源码可以让页面按提交号现取。`--link`（__main__.py:622，`choices` 只有 github）在 `cmd_graph` 里是一个提前返回的分支（__main__.py:135 起），CLI 这边做的事：
1. **分叉的位置**：四道检查和算 keep 都在分支前面，两种导出共用——链接模式同样拒绝空的 `--hot`、按字面和按解析到的 run 去重、`--compare` 要真有另一个 run，交给 site 的 `others` 是第 4 道去重之后的。链接模式根本不走 `cmd_graph` 里那次 `export_payload`：`site.export_site` 自己以 code=False 调它（site.py:209），不带符号片段、全文和共用的跳转目标表。这就是 keep 要挪到 `export_payload` 之前的原因。
2. **`--out` 必须给、必须是目录**（__main__.py:137）：没给、或以 .html 结尾，都报「--link github 导出的是一个目录（index.html + data/）：--out 给目录」。单文件那一路没给 `--out` 时有默认文件名、写进 .codestrata/；链接模式没有默认目录。以 .html 结尾多半是照单文件的习惯写的，不拦的话会建出一个叫 x.html 的目录（test_site_export 里有这个用例）。目录本身能不能用（存在但不是目录、不是空的又没有 `.codestrata-site` 标记）由 site 的 `_check_out` 在算之前查（site.py:182），这里不管。
3. **`site` 在函数体里 import**（__main__.py:139），和 `serve` 一样。
4. **参数原样交过去**（__main__.py:140）：
   - `--public` 给的是 `public`、`home=str(Path.home())` 和上面算好的 `keep`。site 在 payload 上调的是同一个 `payload.publicize`（site.py:242），另把随页面带上的本地源码里的主目录也换掉；写完之后再把写出的每个文件查一遍，还有主目录就删掉 data/ 和 index.html 再 SystemExit（site.py:340）。
   - `code_bases=a.code_base or None`：给了 `--code-base` 就**整个换掉**默认的两个（jsDelivr、raw，site.py:208），不是插在前面——要保留退路得把默认的也写上。模板在 CLI 和 site 里都不校验，原样写进页面（`EMB.link.code`），取源码时由页面在浏览器里 `replace` 这四个占位符 {owner} {name} {sha} {path}（codestrata/web/ds.js:233）。site 只在导出时试取那一下用 `str.format` 填一次（site.py:133）：占位符写错（比如 {repo}）时这一步抛 KeyError、带着 traceback 退出（`_url` 在 `_reachable` 的 try 外面，site.py:141）；不试取时（`--no-remote-check`，或没有可试的文件）不报，写错的占位符原样留在页面要取的地址里。
   - `check_remote=not a.no_remote_check`。
   - `per_pkg=a.per_pkg` 传了但不起作用：`code=False` 时 `export_payload` 跳过符号片段那一段（payload.py:973），`--per-pkg` 只管那里。`--fragment` 没传：site 调 `render.export` 不带它（site.py:337），链接模式总是完整的 HTML 文档。
   - `title` 和单文件那一路是同一个。

**打印**（__main__.py:145 起），全来自 `export_site` 返回的摘要（site.py:347），和单文件那一路形状不同：
- 第一行：`→ <out>/  页面 N KB + data/<版本>/ M MB：K 个文件的大纲和跳转、引用倒排 B 桶`。量的是写到磁盘上的 UTF-8 字节——页面是 index.html 的字节数，data 是这次写出的所有文件减去 index.html（site.py:350）——不像单文件那一路量的是字符数（整页 `len(html)`、各部分 `json.dumps` 之后的长度）：这里没有 16 MB 的额度要对，量的是要部署多少。单文件摘要里的节点 / 边 / 泳道 / 解读数、hot、「另带 N 个 run 可切换」「对比前两个」、各部分大小，这里都不打；`--hot` / `--compare` 照样生效，只是摘要不提。
- 第二行：源码从哪取——`github.com/<owner>/<name> @ <提交号前 12 位>`；扫的是 git 仓库里的子目录时加「（仓库里的 <prefix>/）」；给了 `--code-base` 也照这样写。后面是导出时试取的结果（__main__.py:147），三种说法：
  - `reach` 为真：「已试取一个文件 ✓」（`urlopen` 没抛错的——带着 `Range: bytes=0-0`，一般回的是 206——和 416 都算取得到，在 site 里判）；
  - `probe` 是 "skipped"：「没去试取（--no-remote-check）」；
  - 其余（`reach` 为 None：没网、5xx 这类拿不准的）：「⚠ 没能确认 GitHub 上有这个提交（…）：页面上取源码要联网」，括号里是 site 给的每个地址的结果，空的时候写「没网？」。只提醒、照样导出、返回 0。全是 404（提交没推上去）走不到这里：site 已经 SystemExit，什么都没写（site.py:238）。
- 第三、四行，有才打：随页面带上的本地版本（GitHub 上那个提交里没有、或内容不一样的），和 `--public` 时被 .gitignore 忽略、没带源码的；各列前 12 个，多了加「…」。前者不含后者（site 只把写了本地源码的算进 `local`），两行不重叠。本地版本的源码是随页面一起发出去的，`--public` 只挡被 .gitignore 忽略的，改了没提交、没进 git 的照样带上——打出来，放上公网之前能看一眼（test_site_export_edges 查了「没带」那一行列出被忽略的文件）。

### 两处编码 / 文件名的小防线
- **graph 的默认文件名**（__main__.py:165）：`--hot` 是 REF，会带 `@阶段`，也可能是迁移来的老 case 名（老版本允许中文、`+`）。只保留 `[A-Za-z0-9@._+-]`，其余换成 `_`，得到 overview-<case>@<phase>.html 这样的名字。M7 起白名单里加了 `+`，因为它是多个 REF 之间的连接符（见上一节）；设计 4.5 的导出文件名一条也已经跟着改了（`+` 连接、`-vs`、白名单带 `+`）。
- **stdout / stderr 改成 backslashreplace**（__main__.py:725）：命令行、路径里可能有不是 UTF-8 的字节，Python 把它们解码成孤立的代理字符，一打印就抛 UnicodeEncodeError——而 `cmd_trace` / `runs show` 要把整条命令打出来。改成打印转义。放在 `parse_args` 之前，argparse 自己的报错也受保护；流没有 `reconfigure` 时跳过。`tests/test_runs.py` 里有带 0xff 字节参数的用例。（`runs show` 的「命令」行靠它打成转义；「复刻」行另由 `runs._q` 写成 `$'…'`，照抄能还原原来的字节。）

### 自己按第一个 `--` 切 argv
`trace . --case X -- python demo.py` 里，`--` 之后的整条命令要原样交给被 trace 的进程。argparse 的 REMAINDER 和可选位置参数放在一起时会互相抢参数（会报 `--case` 缺失），所以 `main` 先自己按第一个 `--` 切开（__main__.py:731），前半给 argparse，后半直接当命令。切之前先把整份 argv 记成 `invocation`（见「复刻」一节），所以复刻命令里 `--` 和后面的命令都在。子命令的 dest 也因此不能叫 `cmd`：trace 的位置参数叫 `cmd`，两者会互相覆盖，所以叫 `which`（__main__.py:599）。

### scan：默认切面上的摘要，交叉引用在 scan 里建
`scan --depth` 默认 `auto`（按规模自动拆分），给数字就是固定深度；`--expand DIR`（可重复）在默认切面上额外展开某个目录。两者都只影响**默认切面**，图上随时还能展开 / 收起。`cmd_scan` 打印的节点数、高度列表都是默认切面上的（`cut.visible` 过滤掉只有空 `__init__.py` 的目录，__main__.py:67 起）。写完 index 紧接着用同一份 `idx` 调 `xref.build` / `xref.write`（__main__.py:83）：和符号表是**同一时刻的快照**，行号才对得上。serve 端只读不建（`payload.load_xref` 按修改时间缓存，文件不存在就不给 Ctrl+点击）；代价是 scan 要把全仓再 parse 两遍。

### app 和 serve --home：主菜单背后跑的还是这个 CLI
- **`app` 不属于任何一个仓库**：它的子命令不调 `common`（__main__.py:715 起），没有 repo 位置参数、也没有 `--roots`；`cmd_app` 也不调 `_outdir`，不往哪个仓库里建 .codestrata/。主菜单管的是一组项目，清单在配置目录的 projects.json 里（`projects` 管）。`cmd_app` 只有一行调用（__main__.py:593）：端口被占时的中文报错、打印带口令的地址、开浏览器、Ctrl+C / SIGTERM 时停掉它起的子进程，都在 `app.main` 里。默认端口 8930（__main__.py:716），和 serve 的 8900（__main__.py:710）错开；这个默认值只写在 CLI 这里：`app.main` 的 `port` 是没有默认值的关键字参数（app.py:289），端口只有命令行这一个来源。
- **按钮背后是同一个 CLI，不是另一条代码路径**：扫描 / 录制是 `jobs` 起的 `<同一个解释器> -u -m codestrata scan|trace …`（`jobs._cli`，jobs.py:29），打开图是 `viewers` 起的 `… -m codestrata serve <repo> --port <空闲端口> --home <主菜单地址>`（viewers.py:102），前缀都来自 `self_command`。扫描 / 录制的工作目录是仓库根目录（jobs.py:219）；图服务不指定工作目录，继承主菜单的。所以从主菜单录的 run 也走 `main` → `cmd_trace`，这一层不用知道是谁叫起的它：`invocation` 照样在 `main` 里记（__main__.py:729）——`sys.argv[0]` 是 …/__main__.py，`_prog` 记成「解释器 -m codestrata」（`-u` 是解释器选项，不在 `sys.argv` 里，记不进去；它只让 codestrata 自己的输出不缓冲，和录到的东西无关），后面是 `jobs.TraceSpec` 拼出的参数（值都写成 `--x=值`，秒数用 `runs.fmt_seconds`；只有 nargs=* 的 `--roots` 是一个个跟在后面，排在 `--` 前的最后；从一个 run 复刻时 tags / roots / stop_grace 也原样带上），cwd 是仓库根目录；`env_inherited` 取的是这个子进程的 `os.environ`，也就是启动 `codestrata app` 的那个 shell 的环境。jobs 不给子进程加环境变量：不缓冲靠 `-u` 而不是 PYTHONUNBUFFERED（jobs.py:31 的注释）——环境变量会经 `trace.run` 的整份 `os.environ`（trace.py:880）一路传给被录的命令，和终端里复刻出来的不一样。复刻命令、`runs show` 的输出和在终端里敲的是同一个形状。
- **`--home` 在帮助里藏起来**（`help=argparse.SUPPRESS`，__main__.py:712）：只有 viewers 会给它，人直接跑 serve 用不上，写进 `serve --help` 只是噪音。`cmd_serve` 不看它、原样交给 `serve.main`（__main__.py:588）；页面怎么拿到它（`/api/app`）、左上角「← 主菜单」怎么放，见 serve 的解读。
- **测试**：test_cli_app（tests/test_app.py:386）用子进程跑 `-m codestrata app --port N --no-browser`，走的是 `main` → `cmd_app` → `app.main` 这一整条：查打印出的带口令地址能登录、能起图服务，SIGTERM 之后退出码 0、它起的图服务也停了。`--home` 的透传也测到了：那里的 viewers 起的就是真的 `-m codestrata serve … --home`；不带 `--home` 直接跑 serve 时 `/api/app` 给 null（test_serve_guard_and_home，tests/test_app.py:366）。

## 局限
- 「只读的动词不建目录」只是不建 .codestrata、不写 .gitignore / README.txt：`runs.runs_dir` 在 .codestrata 存在、runs/ 不在时会建 runs/（__main__.py:409），`catalog` 第一次调用时会做迁移（搬动老的 trace 文件）。只查不建的 `runs.has_runs`（runs.py:50）现在有了，但只有主菜单看项目状态时用它，`cmd_runs` 没用。
- ls 为了「改过」一列逐个读 detail.json、为了大小逐个走 run 目录，不像设计 3.2 说的「列表只读 run.json」（run.json 里的 `sizes` 只记顶层文件，不含 files/、events/ 和中断的 run 散着的 parts/）。run 多了 ls 会变慢。
- ls 的「改过」= changed + mismatch（__main__.py:434），而前端 hot 叠加的 `stale_files` = changed + gone（runs.py:789），两处口径不一样。
- ls 的「时序!」比「时序」和空白多一列（多出来的「!」是半角），整理失败的那行 tag 列会错一格。
- 默认文件名会把所有 REF 连起来，而完整 id 是 16 位时间戳加 case 名，可能还带 @阶段。`--hot` 给多了，文件名会超过常见文件系统 255 字节的上限；代码没有截断。另外文件名用的是字面去重后的 REF，不是第 4 道之后的：`--hot demo --hot <demo 最新那次的完整 id>` 只嵌了一个 run，文件名里仍是两个。
- `--public` 只认导出这台机器、这个用户的主目录（`Path.home()`）。runs/ 若是从别的机器或别的用户那里拷来、软链过来的，run 元数据里另一个主目录不会换成 `~`，最后那道检查也只查这一个主目录，拦不住。
- 默认文件名不区分 `--public`：同一组 `--hot` 的公开导出和本机导出写到同一个 overview-….html，后一次覆盖前一次；两份都要留得用 `--out`。
- `--public` 时每个 REF 被解析两次（`load_hot` 一次、算 keep 一次）。case 名解析到的不是 ok 的 run 时，`runs.resolve` 那句「没有完整录完的 run，用的是 …」（runs.py:619）会在 stderr 上打两遍。
- 链接模式里「没去试取（--no-remote-check）」这句，在没给 `--no-remote-check`、只是找不到可以试的文件时也会打：site 只拿「不是本地版本、非空」的文件去试（site.py:235），一个都没有（比如扫的目录整个还没提交）时 `probe` 保持初值 "skipped"（site.py:232），CLI 分不出是哪种，照样说是 --no-remote-check。
- `--code-base` 全是相对地址（测试时指向站点自己的镜像）时 site 一个都不试（site.py:142），返回的消息是空串，CLI 打成「⚠ 没能确认 GitHub 上有这个提交（没网？）」——其实不是没网，是没法试。
- 只在一种导出里有意义的开关放到另一种里都悄悄不起作用、不报错：不带 `--link` 时的 `--code-base` / `--no-remote-check`，带 `--link` 时的 `--fragment` / `--per-pkg`。
- `--link` 对 `--out` 的检查排在 `load_hot` 和算 keep 之后：忘了给 `--out`，要等每个 REF 都解析完（stderr 上已经打过解析结果）才报。
- 模块 docstring 的 graph 那行、graph 子命令的 help（__main__.py:615）和 `cmd_graph` 的 docstring（__main__.py:102）都还写着「导出单文件 HTML」（两处 docstring 还有「离线」）。`--link` 导出的是一个目录、页面要联网取源码，只有 `--link` 自己的 help（__main__.py:623）说了。这条 help 和分支上的注释（__main__.py:136）又都说按「扫描时的提交号」取，实际钉的是导出时的 HEAD：scan 之后又提交过的话，钉的是新提交。
- `runs show X@阶段` 会校验阶段存在，但打印的内容不分阶段（`phase` 没用上）。
- `runs show` 的「阶段」行只有起始时刻、函数数、调用数：不说这一段是哪个 `--phase` 的函数切的、还是 case 脚本写的，也不报没切到的 `--phase`。这些只在 trace 结束时的两句警告和网页的阶段表里，事后在命令行上只能从复刻命令里的 `--phase` 反推。
- 「没切到」的提示把原因说成「对应的函数这次没被调用」；调用它的进程没被 hook 到（hook 靠 PYTHONPATH 注入，trace.py:892，自己清空环境再起的子进程就没有）也是同样的结果，提示不区分。
- 继承的环境只记白名单里的：case 脚本自己读、又不带那些前缀的变量（比如自定义的模型路径变量）不会记下，复刻时要自己补。
- `_cwd` 只保住了 `main` 本身：当前目录已被删时，`cmd_trace` 对相对的 repo 取 `resolve()`（__main__.py:254）、给相对的 `--attach` 拼 `Path.cwd()`（__main__.py:271）都要读当前目录，会直接抛 FileNotFoundError，不是 SystemExit 那样的中文提示。反过来，这种情况下录得下来的 run（`invocation` 的 cwd 是 None，复刻命令没有 `cd` 那一截），repo 和 `--attach` 必然是绝对路径（`--phase` 的文件路径本来就按仓库根目录算），被 trace 的命令又固定在仓库根目录跑（trace.py:944），少了 `cd` 不影响复刻。
- 直接用 `runs` 的私有函数 `_read` 读 run.json / detail.json，跨模块依赖了私有名字。
- `cmd_scan` 里 `x` 先绑成 xref 的结果，下面高度列表的循环又把 `x` 当成节点复用（__main__.py:88）；都不出错，但读的时候容易看串。
- serve 的默认端口仍写了两处：CLI 的 8900（__main__.py:710）和 `serve.main` 参数的默认值（serve.py:456），改一处要记得另一处（`app` 那边已经只剩 CLI 一处）。
- `--home` 在 CLI 里不校验，任何字符串都原样交给 serve，页面直接当链接的 href（codestrata/web/app.js:715）。正常只有 viewers 会给它、给的是主菜单自己的 `http://127.0.0.1:<端口>/`，所以没拦；手敲时写成什么，页面上就放什么。

## 不确定
- `cmd_serve` 在函数体内才 `from . import serve`（__main__.py:587），代码里没写原因；推测是让不启动服务的子命令不必加载 `http.server`。`cmd_graph` 的 `from . import site`（__main__.py:139）同样没写原因；site 顶层 import 了 subprocess、urllib.request、shutil，推测也是让不走链接模式的导出不必加载它们。`cmd_app` 的 `from . import app`（__main__.py:592）也一样没写原因；app 顶层 import 了 http.server、webbrowser 和 `jobs` / `viewers` / `serve`，理由应该相同。
- 链接模式没有默认输出目录（单文件那一路默认写进 .codestrata/），代码和设计 M8.2 都没说为什么；推测是产物本来就要整个放进站点源码目录（README 的例子是 `--out ../mysite/source/codestrata/myrepo`），默认放进 .codestrata/ 还得再拷一遍。
- `cmd_trace` 在 `runs.new_run` 之前先调 `runs.catalog` 做迁移，注释只说「先把老格式的 trace 迁进 runs/」，没说为什么要赶在录制之前；不迁的话下一次任何命令调 `catalog` 时也会迁。
- `runs show` 把复刻命令和继承的环境分开打（复刻那一行不带 `env K=V…` 前缀，网页上另有一个「连环境变量一起」的复制按钮），代码里没写为什么 CLI 不给带环境的那一版；可能是 PATH 之类的值太长，混进一条命令里难读。
