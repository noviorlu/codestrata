---
written_by: claude-opus-5-5
target: codestrata.projects
kind: package
code_sha: 2c5e9dd5ff475e3c
status: draft
refs: projects.py:1@38f056bb,payload.py:20@d276bb38,payload.py:908@88c111f3,serve.py:455@779db1a4,tests/test_app.py:69@bdf849b5,projects.py:23@9b044349,app.py:350@af06824e,projects.py:19@3c14c236,projects.py:20@a3af1320,projects.py:28@6fdc48c9,app.py:190@8c363376,projects.py:95@2fe2f404,projects.py:88@920051d8,projects.py:116@42b2e8d7,projects.py:144@3ff7798a,projects.py:136@c77e072c,projects.py:179@247c953a,projects.py:176@d20f006d,projects.py:38@f87af20b,projects.py:40@aaaeaa0e,projects.py:44@8e245f5e,projects.py:46@3f0b02a4,projects.py:63@44e9e60e,projects.py:70@44e9e60e,projects.py:79@44e9e60e,projects.py:65@df8306f6,projects.py:75@79f014bf,projects.py:60@230fe1ef,projects.py:61@b67404aa,projects.py:56@5a20a6c8,app.py:91@68282492,projects.py:100@66a0b193,projects.py:103@f1b2145f,codestrata/web/home.js:56@40da42d4,payload.py:893@e4189233,projects.py:112@c65cf436,projects.py:90@67a922ed,runs.py:602@eee7399e,projects.py:91@0a1dde63,runs.py:761@7f761862,codestrata/web/home.js:117@f4257edf,projects.py:105@19f9f31a,runs.py:67@de9c00e5,runs.py:53@78c18e1a,runs.py:66@e777ff95,projects.py:108@e10eddb3,tests/test_app.py:87@66edca7d,projects.py:122@41cf6068,tests/test_app.py:125@1a15d38d,projects.py:123@24d5f633,tests/test_app.py:127@e1782847,projects.py:125@9bc0cafa,projects.py:130@96c44e1e,tests/test_app.py:135@555be14a,tests/test_app.py:138@d199ff19,projects.py:132@6379245b,projects.py:133@660e6221,projects.py:147@f582e988,projects.py:160@95fd2bad,projects.py:165@4e6d523f,projects.py:167@be5cc7c6,projects.py:140@e2f02032,projects.py:172@4f6f24a3,codestrata/web/home.js:206@6e301235,codestrata/web/home.js:353@f1db139b,projects.py:191@bf1c6196,projects.py:197@52e9fea4,projects.py:198@33abe6cd,projects.py:192@745f550e,projects.py:195@ca041ddb,tests/test_app.py:112@e226d3dd,codestrata/web/home.js:351@20c32d44,trace.py:1149@92aab118,projects.py:200@793b8e9e,tests/test_app.py:105@9cdda119,codestrata/web/home.js:376@a88aa765,scan.py:791@2a8f89e3,codestrata/web/home.js:82@750413ce,scan.py:226@71a4a47a,runs.py:592@ec49da18,serve.py:450@15b8eb16
---

## 是什么
主菜单（`codestrata app`）的数据层，管五件事：
- 记住打开过哪些仓库：`Registry`，存在 `$XDG_CONFIG_HOME/codestrata/projects.json`，最近打开的在前；
- 给每个仓库出一张项目卡片要的数据：`status`，包括扫描过没有、扫的是哪些目录、scan 之后改过几个文件、录过哪些 run；
- 给「静态扫描」对话框列能选的目录和上次选的：`scan_choices`；
- 给「打开文件夹」对话框列子目录：`browse`；
- 给「录制运行」表单里 --phase 的函数输入框做补全：`find_symbols`。

模块 docstring（projects.py:1）先把边界说清楚：只管数据，不管 HTTP，也不起进程。

## 为什么这样切
主菜单拆成四块，分法是看每块有没有副作用、有什么副作用：`app` 只做 HTTP（路由、鉴权、JSON），`jobs` 起 scan / trace 子进程，`viewers` 起 serve 子进程，剩下的都是查数据，放在这里。这样 `Registry` 和这几个函数不用起服务就能直接测，`tests/test_app.py` 里的 test_registry、test_status_browse_symbols 和 test_scan_roots 就是直接调的。

.codestrata/ 里的文件和仓库目录怎么看，它一个都不自己定规则，交给已有的模块：
- index 摘要（包括上次扫的是哪些目录）：`payload.index_summary`（payload.py:20）
- scan 之后改过几个文件：`payload.index_lag`（payload.py:908）。这个数原来在 serve.main 里算，现在挪进 payload，卡片上的「之后改过 N 个文件」和图服务启动时的提示（serve.py:455）用的是同一个函数
- 录过没有、run 列表：`runs.has_runs`、`runs.catalog`
- 符号表：`payload.load_index`
- 仓库里哪些目录能拿来扫、怎么数 .py 文件：`scan.candidate_roots`、`scan.iter_py_files`

所以 index.json 里哪个字段是文件数、run.json 放在哪、哪些目录算候选，这类知识还是只在 payload / runs / scan 里各留一份。

清单放在用户的配置目录，不放进哪个仓库。它记的是跨仓库的「最近打开」，把一个仓库加进清单、在卡片上看它的状态，都不应该往这个仓库里写东西（test_registry 末尾先调一次 `status`，再断言两个仓库里都没有 .codestrata/，tests/test_app.py:69）。`config_dir`（projects.py:23）同时也是 app 放口令文件和图服务日志的目录（app.py:350）。

## 读法
1. 模块 docstring，再看两个上限常量 `MAX_DIRS`、`MAX_RUNS`（projects.py:19、projects.py:20）。
2. `Registry`（projects.py:28）：先看 `_load` / `_save` 这一对，再看 `add` / `touch` / `remove`，最后看 `has`。app 用 `has` 当安全闸门（app.py:190），所以它放到最后、要单独想清楚。
3. `status`（projects.py:95）和 `_run_brief`（projects.py:88）：一张卡片的全部数据。读的时候对照 codestrata/web/home.js 里画卡片的 facts 函数，看每个字段在哪儿用上。
4. `scan_choices`（projects.py:116）：扫描对话框的数据，也是 app 检查勾选目录用的白名单。
5. `browse`（projects.py:144）和 `_looks_like_repo`（projects.py:136）。
6. `find_symbols`（projects.py:179），连同它上面那个模块级缓存 `_SYMS`（projects.py:176）。
7. 验收看 `tests/test_app.py` 的 test_registry、test_status_browse_symbols 和 test_scan_roots。

## 关键算法
### 清单：整份读、整份原子写，列表里的位置就是打开的先后
- **每次都现读文件**（`list` → `_load`），内存里不留副本。文件很小，现读不费事；手改了 projects.json 或者别的进程改了，下一个请求就能看到。
- **读坏了当空清单。** 文件读不了、解析不了就返回空列表（projects.py:38），不是 dict 或没有 path 的条目也筛掉（projects.py:40）。这只是一份「最近打开」，坏了不该让主菜单起不来。
- **原子写。** `_save` 先写 projects.tmp（projects.py:44），再 `os.replace` 换上去（projects.py:46）。进程死在写到一半，原文件还是完整的旧版本。
- **读改写整段在锁里。** `add` / `touch` / `remove` 都在同一把锁里完成读、改、写（projects.py:63、projects.py:70、projects.py:79）。app 跑在 ThreadingHTTPServer 上，两个请求同时加项目时，不加锁后写的会盖掉先写的。
- **顺序就是列表里的位置。** `add` 和 `touch` 都把目标挪到最前（projects.py:65、projects.py:75）。每条还记了 `opened` 时间，但目前没有代码读它。

### 路径只在 add 时规范化一次，之后按字符串精确比
`add` 用 `expanduser().resolve()` 转成绝对路径，软链和 `..` 都解开（projects.py:60），不是目录就抛 ValueError（projects.py:61），存下的就是这个字符串。`has` / `touch` / `remove` 不再规范化，直接拿 `str(repo)` 跟存下的比（projects.py:56）。前端后面发的请求带的都是 /api/projects 下发的那个 path，原样传回来，所以一定对得上。

`has` 是 app 的闸门：扫描、录制、打开图、补全、列扫描候选都只认清单里的项目（app.py:190）。精确比较的效果是只有 add 存下的那一种写法能通过，`/x/../repo` 或者经过软链的写法都不行。这一点是从代码推出来的，docstring 没说是有意这么设计。`has` 本身只是一次读：「在清单里 → 起任务」和「没有任务在跑 → 移除」要一口气做完，那把锁放在 app 里（app.py:91），Registry 的锁只管清单文件的读改写。

### status：一张卡片要的全部，只读便宜的那部分
- **目录不在了**（删掉了，或者盘没挂上）就直接返回 `exists: False`（projects.py:100）。卡片照样画出来，用户才有地方点「移除」。
- **index 只读小文件。** `index_summary` 只读 index.json，比它大一两个数量级的 symbols.json 不碰；没扫描过是 None，这时也不算 lag（projects.py:103）。摘要里带着上次扫描的 roots，卡片上写成「目录、目录：N 个文件」（codestrata/web/home.js:56），看得出扫的是哪几个目录。`index_lag` 会按 xref 里记下的 (大小, mtime) 逐个 stat 文件，仓库里有多少文件，每次就 stat 多少次。xref.json 本身不是每次都解析：`index_lag` 按 (路径, mtime) 把指纹表缓存在自己的 `_xref_fp` 里（payload.py:893），不走图服务那个单槽的 `load_xref` 缓存，主菜单一次看好几个仓库也不会互相挤掉；算不出来（没 scan、老格式、文件坏了）一律当 0（payload.py:908）。好在前端只在事件之后才 refresh（任务结束、加减项目、打开图），没有定时轮询，这个开销可以接受。
- **run 只给摘要。** run 列表走 `runs.catalog`，它只读每个 run 的 run.json，再由 `_run_brief` 削成 7 个字段（projects.py:88）。/api/projects 每次把所有项目的卡片一起发下去，run.json 里的命令、环境、problems 卡片上用不上。`MAX_RUNS`（20）只截断发下去的列表（projects.py:112），总数另外放在 `n_runs` 里。
- **显示用的状态和「能不能叠」分开给。** `status` 字段取 `catalog` 给的 `status_shown`（projects.py:90）：录制进程已经死掉的 recording 显示成「中断」（runs.py:602），和 `runs ls` 一致。能不能叠到图上另给一个 `loadable`（projects.py:91），按真实的 status 算，只有 ok / partial 才算（recording 的还没有计数，runs.py:761）。前端「打开图」挑最近一个 loadable 的 run 叠上去（codestrata/web/home.js:117），不用自己去认 status 有哪几种取值，也不会被显示用的「中断」绕进去。
- **先看有没有录过，再读。** 用的是 `runs.has_runs`（projects.py:105），不是 `runs.runs_dir`：后者发现目录不在就顺手 mkdir（runs.py:67），看一眼状态就会在刚加进清单的文件夹里建出 .codestrata/runs/。`has_runs` 用 `os.path.lexists`（runs.py:53），runs/ 是悬空软链（盘没挂上）也算「有」，于是照样去调 `catalog`，由 `runs_dir` 抛 SystemExit（runs.py:66），这里接住，变成卡片上的一行提示 `runs_error`（projects.py:108）。一定要接住：SystemExit 不是 Exception，放出去会从 /api/projects 的处理线程冒出去，socketserver 接不住，整个项目列表都拿不到响应（实测客户端收到 RemoteDisconnected），而不是只有这一张卡片出提示。测试在 tests/test_app.py:87。

### scan_choices：只列不挑，上次的选择不能丢
扫哪些目录由用户在对话框里勾，这里只负责给出能勾的东西（projects.py:116）：
- **候选交给 scan。** `scan.candidate_roots`（projects.py:122）从每个顶层目录往下找，包、src/ 下一层的包、放零散脚本的目录、tests/ 都列出来，嵌套的子工程往里找，虚拟环境和 conda 环境整个跳过，列出的目录互不重叠（规则见 scan 的解读）。它只列、不挑：以前自动探测时会替用户去掉 tests/、examples/ 这类目录，现在要不要扫是用户的决定（tests/test_app.py:125）。
- **上次选的就是 index 里记的 roots**（projects.py:123），重新扫描时对话框预先勾上。没扫描过是空列表，第一次一个都不预先勾（tests/test_app.py:127），不替用户猜。
- **上次选的不在候选里，也并进来，标 previous**（projects.py:125 到 projects.py:130）。命令行 `scan --roots` 可以给任意目录，比如给了 src，而候选里只有 src/pkg（tests/test_app.py:135 到 tests/test_app.py:138）。不并进来的话，对话框里没有这一格，用户什么都不改点「开始扫描」，上次的选择就悄悄丢了。只并还存在、里面有 .py 的目录，文件数照样用 `iter_py_files` 数，和候选的口径一样。app 检查勾选的目录也拿这份 candidates 当白名单，所以并进来的这一项也能通过（见 app 的解读）。
- **每项带 name**（projects.py:132）：路径的最后一段，模块名就是按它起的。最后一段一样的两个目录一起扫，模块会撞成同一批（`scan.root_clashes`）；对话框按 name 分组，撞名时把按钮禁掉。按路径排序后返回（projects.py:133）。

每次调用都现算：`candidate_roots` 要把候选目录底下的 .py 整个数一遍，不缓存。对话框打开一次算一次，提交时 app 做白名单检查再算一次。

### browse：只看一层，最多列 500 个
它服务的是「打开文件夹」对话框，所以处处让位给「快」和「不出错」：
- 不给路径就从家目录开始（projects.py:147）。路径打不开、不是目录、读不了，都变成带原因的 ValueError，app 回 400，对话框把原因显示出来。
- 隐藏目录不列（projects.py:160）。某个条目 `is_dir()` 抛 OSError 就跳过它（projects.py:165），一个坏条目不会毁掉整张列表。
- 子目录最多列 `MAX_DIRS`（500）个，超过就设 `more`（projects.py:167）。常量旁的注释说，多到这个份上的是 node_modules 这类目录，不会是要找的仓库；前端会提示用户直接在输入框里打路径。
- 每个子目录只 stat 顶层的几个标记（projects.py:140）：`.git`；pyproject.toml / setup.py / setup.cfg；.codestrata/index.json。不往下走。`.git` 用的是 `exists()`，所以 git worktree 和 submodule 里 `.git` 是个文件的情况也算。
- 到了根目录，`parent` 是 None（projects.py:172），前端据此把「上一级」按钮禁掉（codestrata/web/home.js:206）。

### find_symbols：按 symbols.json 的 mtime 缓存
补全是边打边查的：前端防抖 200ms，至少打 2 个字才查（codestrata/web/home.js:353）。每查一次都读一遍 symbols.json 太慢，所以按仓库缓存。键是仓库路径，值是 (symbols.json 的 mtime, [(qualname 小写, 键)])（projects.py:176），mtime 变了才重读（projects.py:191）。重新扫描会重写 symbols.json，补全自己就跟上了，不用谁来通知。图服务不一样，scan 之后要由 app 显式重启。缓存里只留函数（`k == "func"`，projects.py:197）的这两列，不留整个 index。

**缓存不加锁。** 每次都是整条替换（projects.py:198），读的人拿到的要么是旧的一整条、要么是新的一整条。两个请求同时发现要重读，就各读一遍，结果一样，后写的覆盖（projects.py:192）。宁可偶尔多读一遍，也不能让一个大仓库第一次补全、正在读十几 MB 的 symbols.json 时（vllm-omni 的是 13 MB），别的仓库的补全跟着一起等。

**读不出来就当没有。** 重新 scan 时 symbols.json 可能正写到一半，JSON 解析错误（连同 index.json 不在时 `load_index` 抛的 SystemExit）都接住，这一次返回空列表（projects.py:195）；缓存不动，下次还会重读（tests/test_app.py:112）。

**只匹配 qualname，不看模块名。** 前端只发输入框里最后一个 `:` 后面的部分（codestrata/web/home.js:351），所以用户选中一个候选 `mod:Cls.f` 以后接着打字，还能继续匹配。返回的是符号表的键 `模块:qualname`，正好是 `trace --phase` 认的第一种写法（trace.py:1149），选中就能直接用。

**排序**（projects.py:200）先看最后一段是不是正好等于 q，是的排前面：搜 generate，名字就叫 generate 的方法排在只是名字里含 generate 的函数前面；测试里第一个返回的是 fakesvc.offline:Engine.generate（tests/test_app.py:105）。其次按 qualname 长短，最后按键，保证结果稳定。

## 不确定 / 局限
- **复刻只能选最新 20 次。** `MAX_RUNS` 同样限制了「录制运行」表单里「照哪次 run 填」的下拉（codestrata/web/home.js:376）。
- **扫描中途补全会落空。** scan 用 `write_text` 直接写 symbols.json，不是原子写（scan.py:791）。补全碰巧落在写到一半的时候，这一次返回空列表，下拉里什么都没有，用户分不出是「没有匹配」还是「正在扫描」。有任务在跑时前端禁用了「录制运行」按钮（codestrata/web/home.js:82），所以只有表单已经开着、又从命令行另跑 scan 才可能碰上。
- **并进来的 previous 可能和候选重叠。** `candidate_roots` 保证候选之间互不重叠，但上次命令行给的 src 并进来之后，和候选里的 src/pkg 是包含关系，两个都勾上时名字不同、`root_clashes` 不拦。同一批文件会不会按两种模块名各扫一遍，没有验证过。上次选的目录如果已经删掉或没有 .py 了，既不在候选里、也不会并进来，对话框里没有它，下次扫描就不再包含它，也没有提示。
- **「最后一段」的算法写了两份。** 这里给 name 用的切法（projects.py:132）和 `scan.root_clashes` 里的（scan.py:226）是同一个表达式，各写一遍；前端按这里给的 name 分组，服务端按 `root_clashes` 拒绝，两份要是改得不一样，按钮能点、提交却被拒。
- **只有老格式录制的仓库，卡片上显示没录过。** 老版本的录制是 .codestrata/trace-<case>.json，要等第一次有人对这个仓库调 `catalog` 才搬进 runs/（runs.py:592）。`status` 先问 `has_runs`，runs/ 还不存在就不调 `catalog`，所以这种仓库在卡片上是 0 次录制；打开一次图（serve 启动时会调 `catalog`，serve.py:450）、录一次或者跑一次 `runs ls` 之后才出现。
- **锁不跨进程。** 两个 `codestrata app`（不同端口）共用一个配置目录时，读改写之间没有跨进程的锁，而且临时文件名固定是 projects.tmp，同时写会互相踩。`runs._write` 的临时文件名带 pid，这里没带。
- **清单坏了会丢条目。** 清单文件坏了（比如手改出语法错误）会被当成空清单，下一次加项目时整份覆盖，原来的条目就没了，也不会有提示。
- **browse 能列本机任意目录。** 它不限于清单里的项目，只要知道路径就能看到目录名和那几个标记，完全靠 app 的鉴权兜底：只监听 127.0.0.1，Host 头要是本机地址加端口，并且要带口令 cookie 和自定义头。
