---
written_by: claude-opus-5-5
target: codestrata.__main__
kind: package
code_sha: 442733755a6936ac
status: draft
refs: __main__.py:272@b87faf5c,__main__.py:266@8ac31b40,__main__.py:219@30b1fec8,__main__.py:232@c90a9ebb,__main__.py:250@059c6e94,__main__.py:267@6109ee57,__main__.py:332@fea936cf,__main__.py:333@80bacee0,__main__.py:324@80bacee0,__main__.py:252@a241b857,runs.py:995@eaf401c1,trace.py:881@ea5dcb7a,__main__.py:259@de24a4b1,runs.py:1007@af308051,__main__.py:302@a7c090eb,__main__.py:310@f7dc7f40,__main__.py:308@8b67ac5a,runs.py:386@33e517e7,__main__.py:451@dc6fc688,__main__.py:255@e57ae09a,__main__.py:263@3942e934,__main__.py:619@a4a06a24,__main__.py:237@1db8c824,__main__.py:242@02bc94e8,trace.py:1088@85234d16,__main__.py:247@96956389,__main__.py:260@cda3f50d,runs.py:1018@f8bd684b,runs.py:1015@6677f901,__main__.py:276@4c3fac98,trace.py:888@1bb58161,__main__.py:287@392b7b8a,__main__.py:290@5ebaa7e0,__main__.py:293@82d17a7b,trace.py:880@494f49a7,__main__.py:666@d9e158f3,__main__.py:672@e2fa7d7f,__main__.py:262@b52cc777,__main__.py:678@b090c917,__main__.py:686@e462ef87,runs.py:910@42395cbd,runs.py:926@895298bf,__main__.py:473@9b7d29d5,runs.py:790@84b0e0e7,runs.py:1002@7e9eb0f8,runs.py:938@5c69ed98,__main__.py:474@593dce02,runs.py:1004@ef9a2d89,__main__.py:476@6a724090,__main__.py:363@b67404aa,__main__.py:365@b09cd715,__main__.py:628@72d37402,__main__.py:381@09bf7a10,__main__.py:400@49ae8d76,serve.py:227@d751bac7,__main__.py:443@c4688ddf,__main__.py:502@b11d1384,__main__.py:520@1d7387f6,__main__.py:646@78ac2d86,__main__.py:505@a52cc99e,__main__.py:514@499fe1b3,__main__.py:523@cab0d66d,__main__.py:528@03b2082a,__main__.py:48@8964b0de,__main__.py:35@22ae2662,__main__.py:570@f63b232a,__main__.py:572@18d874a4,__main__.py:103@c408ea25,__main__.py:104@9b58cee4,__main__.py:106@77bed867,__main__.py:107@c224cee8,__main__.py:112@7fb1a314,__main__.py:119@739253ed,__main__.py:125@5e4008de,__main__.py:132@a647a88e,__main__.py:136@d4def5e0,__main__.py:126@ea1a2f4a,__main__.py:662@9c6178dc,__main__.py:668@ec9fb5ef,__main__.py:552@d41c8ef6,__main__.py:65@04903107,__main__.py:81@d89a80ca,__main__.py:392@9371b1a0,runs.py:777@bbf3acab,trace.py:892@6cf25a9e,__main__.py:215@cd279d19,trace.py:944@6d3a8055,__main__.py:86@0c3e9807,__main__.py:545@4c85e081
---

## 是什么
命令行入口：`scan` / `trace` / `runs` / `serve` / `graph` / `tasks` / `pack` / `note` / `check` 九个子命令。大多数只把参数转交给对应模块；M1（`docs/design/runs.md`）之后多了两块真正的 CLI 逻辑：`cmd_trace` 把每次录制存成一个**新的 run**，`cmd_runs` 管理录下的 run（ls / show / tag / untag / note / rm / merge）。M3 在这两块上各加了一点：`trace --events` 顺带录时序事件（时序图的数据），`runs rm --events-only` 只删事件；trace 的输出和 `runs show` 报事件的摘要，`runs ls` 标一个「时序」（整理失败的标「时序!」）。它还管 .codestrata/ 目录本身：`_outdir` 建目录时顺带写一份 .gitignore 和一份 README.txt。`scan` 一次写出 index.json、symbols.json，以及给全文窗口 Ctrl+点击用的交叉引用 xref.json。M7 起 `graph` 也有了一点 CLI 逻辑：`--hot` 可以给多个（第一个是主 run，其余在导出的单文件里可切换），`--compare` 让主 run 和第二个对比。

M8 又加了两样：`trace --phase 名字=函数`——某个进程第一次进入这个函数时切到这个阶段，分段写在 codestrata 的命令上，不用改 case 脚本；以及「复刻」——`main` 把原样的 codestrata 命令和当前目录记下来（`invocation`），`cmd_trace` 另记录制时 shell 里相关的环境变量（`env_inherited`），`runs show` 打印一条能照抄的复刻命令（原来那一行叫「重录」）。

所有 `--hot` 的参数现在叫 RUN（模块 docstring 末尾）：完整的 run id，或 case 名（取它最新一次录完的），后面可以加 `@阶段`。解析全在 `runs.resolve`，这里不碰：graph（字面去重后，每个 `--hot` 各调一次）/ tasks / pack 透传给 `payload.load_hot`；serve 的 `--hot` 交给 `serve.main`，M4 起它只决定页面打开时先选哪个 run，页面上随时能换，换 run 不用重启 serve。只有 graph 的 `--hot` 能重复：tasks / pack 的仍是单个（`notes.prompt_pack` 只收一个 hot），serve 的也是单个——对比在页面上现选（工具栏「对比」，地址里记 cmp=），不用在命令行上给。

## 为什么这样切
它是唯一的入口层（高度 +1）：出边 9 条，没有人依赖它。原则还是「薄」：`cmd_*` 解析参数、调模块、打印摘要。`cmd_trace` 和 `cmd_runs` 占了文件一半多，但里面放的仍是 CLI 该管的事——参数校验（`--env` 的 K=V、tag 的字符集、`--attach` 的路径、`--phase` 在建 run 之前先解析）、摘要怎么打印、删之前的交互确认，以及只有入口才拿得到的东西（原样的 argv、启动时的当前目录和环境）。run 是什么、REF 怎么解析、收尾 / 重算 / 删除的规则、事件怎么整理成 span、复刻命令怎么拼、哪些环境变量算「相关」，都在 `runs`（和 `codestrata/events.py`）里；`--phase` 的函数怎么认、阶段怎么切在 `trace` 里。这里只读 run.json 里现成的 `events` 摘要和 `phase_log`，不 import `events`。

三条边界值得注意：
- **录制是在这里缝起来的**：`runs.new_run` 建目录 → `trace.run` 跑命令 → 经 `after` 回调调 `runs.finalize`（__main__.py:272）。`runs` 依赖 `trace`，`trace` 不 import `runs`，所以 `trace.run` 只开一个 `after` 口子，由上层把收尾塞进去。
- **事件的开关只是一个环境变量**：hook 在被 trace 的进程里看 `CODESTRATA_EVENTS` 是不是 "1"，CLI 每次都把它明确写给命令——`--events` 时 "1"，否则 "0"（__main__.py:266，理由见下）。录不录、怎么配对、上限，全在 `trace` 的 hook 里。
- **删除的安全规则两层都有**：`cmd_runs` 的 rm 先把每个参数查一遍（完整 id、不在录）再统一确认，一个不对就一个都不删；`runs.remove` / `runs.remove_events` 自己也再挡一次（后者还拒绝删还有进程在往 parts/ 写的 run）。

图上它的出边没有虚线：每条都真的调用了对方的函数（`serve` 是在函数体里 import 的，也算一条边；`xref` 由 `cmd_scan` 直接调 `build` / `write`）。

## 读法
1. 模块 docstring —— 子命令一览（graph 那行写成 [--hot RUN]… [--compare]，和 argparse 一致），以及 RUN 的写法
2. `main` —— argparse 的搭法：`runs` 的两级子命令、trace 的开关（含 `--events`、`--phase`）、rm 的 `--events-only`，最后的 stdout 重配、记 `invocation`、切 `--`；紧跟着的 `_prog` / `_cwd` 是记 `invocation` 用的
3. `cmd_trace` —— 一次录制从建 run 到打印结果的全过程，对照设计文档 4.2 读；事件相关的是 `env_run` 和打印里 `ev` 那一段；M8 相关的是开头解析 `--phase` 的一段、`new_run` 的 `invocation` / `env_inherited` 两个参数、打印里 missed / shadow 两句警告
4. `cmd_runs` —— 按动词分段；ls / show 是纯展示（show 的末尾是复刻命令和继承的环境），rm 是唯一不可逆的
5. `_outdir` 和 `_README` —— 很短，但写明了 .codestrata/ 里哪些能删
6. `cmd_graph` —— 多个 `--hot` 的四道检查（三道看字面，一道看解析到的 run）、默认文件名、各部分大小的打印；数据怎么拼在 `payload.export_payload`
7. `cmd_scan` 及其余 `cmd_*` 按需看，都很短

## 关键算法
### trace：每次都是新的 run，收尾在 driver 的信号处理器保护下做
以前 `cmd_trace` 把结果写成 `trace-<case>.json`，同名 case 重录就覆盖——而一次录制可能是几分钟的 GPU。现在的流程：
1. **先校验，再建目录**（__main__.py:219 起）：`--env` 必须是 K=V；`--tag` 只能用 `_TAG_RE` 里的字符；`--attach` 的文件必须存在；`--phase` 也在这一段解析完（见下面「--phase」一节）。case 名在 `runs.new_run` 里校验，也在建目录之前。参数填错不会留下一个空 run。
2. **`--attach` 的相对路径先按仓库根目录找**（命令就是在那里跑的），找不到再按当前目录（__main__.py:232），存成绝对路径。被 case 脚本 source 的 common.sh 不会出现在任何进程的 argv 里，只能靠它存进 run。
3. **`runs.catalog` 先把老格式的 trace 迁进 runs/**（__main__.py:250），再由 `runs.new_run` 建目录、写 `status: recording` 的 run.json（复刻要用的 `invocation`、`env_inherited` 也在这一步写进去，见下面「复刻」一节）。录制开始前就把 run id 和目录打到 stderr（__main__.py:267）。`mono0_ns` 从刚写的 run.json 里读回来交给 `trace.run`，所以各阶段、各进程的时刻（包括事件的时刻）都相对 run.json 里记的同一个零点。
4. **收尾放在 `after` 里**：`trace.run` 的信号处理器一直装到 `after` 返回，打包 parts 的中途按 Ctrl+C 不会把 run 弄成半截（设计文档 4.3「driver 的信号」）。事件日志的打包和整理也在 `runs.finalize` 里，同样受保护。
5. **打印**：状态（`_STATUS` 译成中文，外加 problems）、进程数（单列跑到仓库代码的）、各阶段的函数数、`--phase` 没切到 / 被 case 脚本同名阶段占掉的警告（见下面「--phase」一节）、跑的若是安装包就说明映射回仓库后是否逐文件一致（不一致的文件行号不可信）、时序事件的摘要（见下一节）、命令退出后停掉的残留进程、存下的文件、没存下来的 `--attach`。
6. **建议一条叠图命令**（__main__.py:332）：写的是**完整 id**——case 名会解析到该 case 最新一次 ok 的 run，这次若是 partial，用 case 名叠的就不是它；run 里有 serving 阶段就加 `@serving`，因为启动时的初始化会淹没请求本身。
7. **退出码**（__main__.py:333；还没 scan 提前返回的那条在 __main__.py:324，同一个规则）：只有 failed（一个函数都没录到）返回 1，partial 也返回 0。

其余开关：`--stop-grace`（默认 90 秒）是停的时候 SIGINT 之后等多久再发 SIGTERM，留给 case 脚本自己的 trap 收尾；`--env` 只把这些变量加给命令并记进 run，不抓整份环境（设计 1.1：防止把 token 存进去；M8 另记的 `env_inherited` 也只取白名单里、名字不像密钥的，见「复刻」一节）；`--roots` 或自动探测的包根算出「顶层包 → 仓库内目录」（__main__.py:252），命令跑的若是 pip 安装的那份，trace 靠它映射回仓库。

### --events：以命令行为准，run 里记的是「要了事件」
- **变量只给命令，而且总是写明**：`env_run` = 用户的 `env` 加上 `CODESTRATA_EVENTS`（"1" 或 "0"，__main__.py:266），传给 `trace.run` 的是它，传给 `runs.new_run` 的仍是用户的 `env`。
  - 为什么不记进 run 的 env：那里的语义是「用户给命令加的变量」，复刻命令里它们都是 `--env`——按参数拼时逐个写；有原样命令时，argv 里没写过的键也会补成 `--env=K=V`（runs.py:995）。把内部开关混进去，复刻命令里就会多出一个用户没写过的 `--env=CODESTRATA_EVENTS=…`，和 `--events` 重复。
  - 为什么不带 `--events` 也要写 "0"：`trace.run` 给命令的环境是整份 `os.environ` 再叠 `env_extra`（trace.py:881）。shell 里恰好 export 了 `CODESTRATA_EVENTS=1` 的话，不写 0 就会悄悄录事件，而 rec 里记的是没要、复刻命令里也没有 `--events`（`env_inherited` 的白名单里也没有这个变量）——录出来的 run 和它的复刻命令对不上。写明之后开关只有 `--events` 一个：`env_run` 里它写在后面，`--env CODESTRATA_EVENTS=1` 也会被盖掉。
- **意图记在 rec 里**：`"events": bool(a.events)`（__main__.py:259）。有原样命令（`invocation`）的 run，复刻命令就是当时敲的 argv，本来就带着 `--events`；rec 里这一项留给没存原样命令的 run——`runs.rerun_command` 按参数拼时看到它就加 `--events`（runs.py:1007）。记的是「要了」，不是「录到了」：录空了、或之后被 rm --events-only 删了，复刻命令照样带 `--events`。
- **三种结果三种说法**（__main__.py:302 起），数据都是 `runs.finalize` 写进 run.json 的 `events` 摘要：
  - 有 `error`：整理成 span 失败。原始日志已经先落进 events/raw.tar.gz，所以提示可以 `runs merge` 重来；
  - 正常：事件行数 → span 数（第一级折叠之后，连续的同类叶子调用合成一条，所以不多于调用次数）、跨文件调用次数（各 span 的 rep 之和）、原始日志压缩后的大小；
  - 要了 `--events` 却没有摘要（__main__.py:310）：`runs` 在没有任何事件日志时不写摘要。原因列了三种——命令没起来；被 trace 的 Python 低于 3.12（hook 只在有 `sys.monitoring` 时录）；或者这次根本没有跨文件的调用（缓冲是空的，hook 就不建日志文件）。最后一种是正常结果，不是故障，所以提示里不能只怪 Python 版本。这里明说出来，免得以为录到了。
- **到了行数上限是 ⚠，不是状态**（__main__.py:308）：上限只管新的调用行，计数是完整的；`runs.derive` 故意不把它算进 status（runs.py:386）——算进去 run 会变成 partial，拿 case 名解析时就跳到更早的一次 ok。所以 CLI 这边只在摘要后面挂一句「N 个进程到了行数上限，之后的调用没记时序（计数完整）」；`runs show` 用同样的说法，另把 pid 列出来——多于 8 个只列前 8 个、后面加「…」（__main__.py:451），好让人知道列表不全。
- **行数上限从 shell 继承时，要记进 run 的 env**（__main__.py:255）：hook 同样读 `CODESTRATA_EV_MAX`。带了 `--events`、shell 里 export 了它、`--env` 里又没给时，CLI 把 shell 的值抄进 `env`——意图是让它记进 run、出现在复刻命令里：按参数拼时写成 `--env=CODESTRATA_EV_MAX=…`；有原样命令时 argv 里没有它，`runs.rerun_command` 把它补成 `--env=` 插在 `--` 前面（runs.py:995），这次录制的上限才复现得出来。`env_inherited` 是在这之后算的、`skip=env`（__main__.py:263），所以它不会在继承的环境里再出现一次。和开关的处理正好相反：`CODESTRATA_EVENTS` 以命令行为准、主动盖掉 shell；上限不盖，只把 shell 里悄悄生效的值写明。只在 `--events` 时抄（不录事件时上限没有意义，不该混进 run 的 env）；`--env` 给了的以 `--env` 为准。这一步放在 `runs.new_run` 之前：`new_run` 当场把 `env` 写进 run.json，之后不再改它，放在后面就只给了命令、没记下来（早先就是这样错的，test_events_cap 里有从 shell 继承的用例）。

### --phase：录之前解析，录完报没切到的（M8）
起因（设计 M8）：离线示例是一条阻塞的 python 命令，shell 看不到模型什么时候加载完，没法往 PHASE 里写阶段，启动和推理混成一段。`--phase 名字=函数` 让「第一次有进程进入这个函数」成为阶段的起点，参数可重复（__main__.py:619 起的 argparse 定义）。切阶段本身在 `trace` 的 hook 里（每个阶段整个 run 只切一次，靠 `parts/PHASE-<名字>.fired` 的 O_EXCL 标记），CLI 只管三件事：
1. **解析放在最前面**（__main__.py:237 起）：在 `_outdir`、`catalog` 迁移、`new_run` 之前。函数写错了当场报，不等模型加载完才发现，也不留空 run。`模块:qualname` 的写法要查静态索引：没 scan 过时 `_load_index` 会 SystemExit，这里吞掉、给 `resolve_phase_at` 传 None（__main__.py:242），由它报「模块:qualname 的写法要查静态索引，先 codestrata scan；或者写成 文件路径:qualname」（只在真用到模块写法时才报）。格式、阶段名（不能叫 start、不能重名）、函数在不在、继承来的方法按 MRO 找、两个阶段不能指到同一个函数，都在 `trace.resolve_phase_at` 里查（trace.py:1088）；注意 `文件路径:qualname` 的相对路径只按仓库根目录算、必须在仓库里，不像 `--attach` 还会退回当前目录。
2. **解析结果打到 stderr**（__main__.py:247）：每个阶段一行——阶段名、换成解释器里的 qualname、定义所在的 file:line；继承来的方法另注「是继承来的，定义在 …」（`via`）：写的是子类上的名字，hook 实际认的是基类里那份代码，要让人看见。
3. **存进 run，交给 hook**：rec 的 `phase_at` 只留 name / func / file / qualname / line（__main__.py:260），给网页的阶段表，以及没存原样命令时拼复刻命令（`--phase=名字=函数`，runs.py:1018）；rec 同时记下 `--roots`（__main__.py:259），按参数拼时带上（runs.py:1015）。完整的解析结果交给 `trace.run`（__main__.py:276），由它明确写进 `CODESTRATA_PHASE_AT`（没有就是 []，shell 里的旧值不生效，trace.py:888）。

**录完的两句警告**（__main__.py:287 起）。数据是 run.json 的 `phase_log`，每条 `[名字, t_us, 来源]`，来源 start / sh（case 脚本写 PHASE 切的）/ hook（`--phase` 切的）；收尾时 `trace` 从 `PHASE-*.fired` 标记里补齐 hook 那几条（`trace.merge_phase_log`）。没有 hook 条目的 `--phase` 各报一句：
- **没切到**（__main__.py:290）：连 sh 条目也没有——提示说「对应的函数这次没被调用」。
- **被脚本同名的阶段占了**（__main__.py:293）：有 sh 条目、没有 hook 条目。case 脚本先 echo 了同名阶段，driver 替它建了 sh 标记，之后 `--phase` 的函数再被调用也不会再切，这一段的起点是脚本写的时刻、不是函数被调用的时刻，所以要说「同名的 --phase 没起作用」。

### 复刻：原样的命令 + 在哪跑的 + 继承的环境（M8）
用户要的是照着录下的那次再录一次。只存 `--env` 不够：被 trace 的命令继承 shell 的整份环境（trace.py:880），相对路径又取决于当时在哪个目录。所以分三处记：
- **`main` 记原样的命令**（__main__.py:666）：在按 `--` 切开、`parse_args` 之前取整份 raw（`--` 和后面被 trace 的命令都在里面），前面加上 `_prog` 给出的「怎么叫起的 codestrata」，连同当前目录挂到 namespace 上（__main__.py:672）。每个子命令都挂，只有 trace 用；`cmd_trace` 用 `getattr(a, "invocation", None)` 取（__main__.py:262），不经 `main` 直接调的就存 None，之后按参数拼。
  - `_prog`（__main__.py:678）：装好的入口脚本（比如 .venv/bin/codestrata）记成绝对路径，复刻时叫到的是同一份安装；`sys.argv[0]` 是 …/__main__.py（`python -m codestrata`）或 `-c` 的，记成 `sys.executable -m codestrata`；程序里直接调 `main(argv)` 的（测试）也走后一种。
  - `_cwd`（__main__.py:686）：当前目录已经被删时 `os.getcwd` 会抛 OSError，这里给 None，不让 CLI 在最前面崩。
- **`cmd_trace` 记继承的环境**（__main__.py:263）：`runs.inherited_env(os.environ, skip=env)`——只取白名单（CUDA_ / VLLM_ / PYTORCH_ / HF_ / NCCL_ 等前缀，PATH / PYTHONPATH / LD_LIBRARY_PATH / VIRTUAL_ENV / CONDA_PREFIX / CODESTRATA_EV_MAX 等，runs.py:910）；名字按 `_` 分段后像密钥的（TOKEN / KEY / SECRET / PASS / AUTH …）不记；值里 URL 的账号密码换成 `<已隐去>`；`--env` 已经写明的不重复（runs.py:926）。取的是 CLI 进程自己的 `os.environ`，正是 `trace.run` 交给命令的那份底子，PYTHONPATH 是注入 hook 之前的样子。
- **`runs show` 打印**（__main__.py:473 起）：
  - 「复刻」一行是 `runs.rerun_command(run, Path(a.repo))`，没传 redact，所以 `--env` 里像密钥的值原样给出——网页和导出（会发给别人）里的那份是 redact=True 的（runs.py:790）。有原样命令时是 `cd <当时的目录> && <原样 argv>`（runs.py:1002），codestrata 自己加进 run env 的（上面说的 CODESTRATA_EV_MAX）补成 `--env=`；不是 UTF-8 的参数写成 `$'…'`（runs.py:938），照抄能还原原来的字节。
  - 老 run（没存 `invocation`）按 run 里存的参数拼，并在下面注一句「这个 run 录的时候还没存原始命令，上面是按 run 里存的参数拼的」（__main__.py:474）。拼出来的仓库路径是 run 里记的 cwd（录制时解析过的绝对路径，runs.py:1004），不是这次 `runs show` 敲的 repo；`Path(a.repo)` 只在 run 里连 cwd 都没有时才用上。
  - 有 `env_inherited` 时在下面逐行列出（__main__.py:476），标题写明「不在命令里，复刻时要一样」；复刻那一行本身不带 `env K=V…` 前缀（没传 with_env）。

### runs：只读的动词不建 .codestrata，rm 只认完整 id
- **入口先查仓库目录和 .codestrata/ 都在**（__main__.py:363、__main__.py:365），不调 `_outdir`：路径写错（比如少写了 src/vllm-omni）要报出来，而不是悄悄建一个空的。`runs` 的 repo 是必填位置参数（__main__.py:628），不像别的子命令默认 `.`——设计 1.1：可省略的 repo 会把动词当成自己。
- **ls**：第一行打印 runs/ 的真实路径，是软链时注明（vllm-omni 的 runs 在 /mnt/data 上）。按 case 分组，组的先后按该 case 最新一次 run 的时间（`catalog` 新的在前，__main__.py:381）。每行：id、状态（driver 已经没了的 recording 显示成「中断」，即 `status_shown`）、时长、跑到仓库代码的进程数、git 短哈希、相对当前 index 改过的文件数、大小（`_run_size` 现走目录）、「时序」标记、tag、备注；总量超过 1 GB 时提醒。
  - 「时序」只在 `events` 摘要存在**且没有 `error`** 时标（__main__.py:400）：标记的意思是「有 span、时序图能看」，整理失败的 run 没有 span，标了会误导。整理失败的标「时序!」：它有原始日志、可以 `runs merge` 重来，和没录事件的 run 不是一回事，不该要 show 才看得出。页面上 serve.py:227 对整理失败给 events=false、另给 events_error=true：下拉里不标「时序」，工具栏的「时序图」按钮置灰、提示写的是「整理失败，runs merge 重来」而不是「没录」。没有摘要时留四个空格（和「时序」同宽），后面的 tag 列不错位。
- **show**：解析 REF，打印 run.json 和 detail.json 的摘要；run 有 `events` 摘要时多一行「时序」（__main__.py:443）：span 数、调用次数、进程数、原始日志大小，到了上限的进程或整理失败也在这一行说。文件状态由 `runs.file_state` 相对**当前 index** 算（不是工作区：叠加用的行号来自 index），每种最多列 12 个（`_FS` 是状态的中文名）；最后是复刻命令和录制时继承的环境（__main__.py:473，见上一节）。
- **tag / untag / note 接受 case 名，rm 不接受**：前者改的是该 case 最新一次 ok 的 run，改错了能改回来；rm 删错了没法重建（设计 4.3 末尾）。rm 先把所有参数查完——去重（`dict.fromkeys`，同一个 id 写两遍只删一次）、必须是完整 id（是 case 名时报错里列出这个 case 的所有 run，方便复制）、不能在录（__main__.py:502）——再列出要删的东西和大小。没有 `--yes` 时，终端里要答 y；不是终端就直接拒绝（__main__.py:520），脚本里不会误删。
- **rm --events-only**（参数在 __main__.py:646）：走完全相同的检查；查完先挑出**没有时序事件**的 run——既没有 events/，parts/ 里也没有散着的 ev-*.log（__main__.py:505 起）——各打印一句「没有时序事件」，不问也不删，全都没有就直接返回 0：没东西可删还要答 y/N 只是噪音，之后再打「删了 … 的时序事件」更会让人以为真删了什么。看的是磁盘而不是 run.json 的 `events` 摘要：还没 merge 的中断 run 没有摘要，原始日志却散在 parts/ 里。剩下的照常确认，说的都是事件那一块——列表里的大小是 events/ 加上 parts/ 里散着的 ev-*.log（__main__.py:514，标「（时序事件）」），正好是 `runs.remove_events` 要删的那些：不拿整个 run 的大小，免得看起来能腾出的空间比实际大，也不会让中断 run 显示 0B；确认语是「删掉这 N 个 run 的时序事件？不能重建。」（__main__.py:523），非终端的拒绝语是「删时序事件要确认」；最后调 `runs.remove_events` 而不是 `runs.remove`（__main__.py:528）。它删 events/（原始日志和 span 都删；还没 merge 的中断 run 连 parts/ 里散着的事件日志一起删），计数和其余数据留着，run.json 的 `events` 置空，ls 的「时序」标记随之消失。为什么也要完整 id 和确认：原始事件日志是原始数据，删了不能重建，和删整个 run 同级。用处是事件是 run 里最大的一块（设计 7.3 估算原始日志 gzip 后 4–6 MB），想留着叠图的计数、不要时序时可以只删它。
- **merge**：转给 `runs.merge_run`（从原始分片重算派生数据，M3 起也从 events/raw.tar.gz 重建 span，M8 起也用 `trace.merge_phase_log` 按包里的 `PHASE-*.fired` 标记重算 `phase_log`——已有的 start / sh 条目保留，`--phase` 切的以标记里的时刻为准、轮询漏掉的补上）。

### _outdir：.gitignore 和 README.txt
每次 `_outdir` 被调用（scan、trace、不带 `--out` 的 graph、tasks --write），缺哪个就写哪个（__main__.py:48），已有的不覆盖：
- **.gitignore 内容是 `*`**：整个 .codestrata/ 不进被分析仓库的 git。实测 vllm-omni 的 git status 一直显示 `?? .codestrata/`——被分析的仓库不该因为用了 codestrata 多出未跟踪文件。
- **README.txt（`_README`，__main__.py:35）**：除 runs/ 以外都能删、都能重建；runs/ 是 trace 录下的运行数据，不能重建。老的说法「.codestrata 随时可重建」到 M1 就不对了，以后的会话照着它 `rm -rf` 就会丢掉 GPU 录的数据。它是设计文档「误删 runs/」的四道防线之一（另外三道：runs/ 可以是软链、仓库 README、agent 记忆的修正）；是软链时 `rm -rf .codestrata` 只删链接本身。

### graph：多个 `--hot` 和 `--compare`（M7）
graph 的 `--hot` 改成可重复（__main__.py:570）。第一个是主 run，和以前一样全量嵌入（hot、hotMeta、graphHot，以及每条边带调用明细的边详情）；其余的作为 others 交给 `payload.export_payload`，只带它们在导出切面上的节点次数、边次数和精简过的 meta（EMB.hotBy），页面上能切过去，但边详情的调用明细只有主 run 的（设计第 8 节）。为什么不每个都全量嵌：单文件有 16 MB 的上限，`export_payload` 先把其余部分算好，剩下的额度才给全文，每多全量嵌一个 run，挤掉的就是全文。`--compare`（__main__.py:572）让主 run 和第二个对比：嵌一个 cmp 块，边详情每项带上 B 的次数（`payload.edge_compare`）；第三个起仍然只是可切换。

调 payload 之前，`cmd_graph` 先做四道检查（__main__.py:103 起），先后顺序是有意的：前三道只看命令行上的字面，第四道要等 `payload.load_hot` 把每个 REF 解析成 run 之后才做得了。
1. **空值直接拒绝**（__main__.py:104，全是空白的也算）：脚本里写 `--hot "$A" --hot "$B"`、变量没设，就是这种情况。`payload.load_hot` 把空的 ref 当成「不叠」，返回 (None, None)。只有一个 `--hot` 的时候，这只会悄悄导出一张没叠加的图；有了多个就不一样了：第一个是空的，主 run 就没了，后面的 run 照样嵌进 hotBy，`--compare` 也悄悄失效；后面某个是空的，取它 meta 的 run_id 时会出错。所以在这里直接报「脚本里的变量没设？」，不往下走。
2. **按字面去重**（__main__.py:106，`dict.fromkeys`，保持先后）：同一个 REF 写两遍只留一份，也就只 `payload.load_hot` 一次（每次都要读 run、往 stderr 打一行解析结果）。放在 `--compare` 的检查前面，这样 `--hot A --hot A --compare` 报的是「要给两个」，而不是拿 A 和它自己比，文件名里也不会出现 A+A。
3. **`--compare` 至少要两个**（__main__.py:107）：不够就报错，而不是悄悄导出一张没有对比的图。
4. **按解析到的 run 再去一遍重**（__main__.py:112 起）：键是 run id 加 `@阶段`，和 `export_payload` 给 hotBy 起名用的是同一个。case 名和它的完整 id 写法不同，却会解析到同一个 run，字面去重拦不住。主 run 的键先放进 seen，所以重复的是主 run 时，丢的是后面那份精简的，留下主 run 那份全量的（test_compare_and_multi_export 里有这个用例）。键里带阶段，是因为 demo 和 demo@serving 是同一个 run 的两份不同数据（全部阶段相加 / 只看 serving），两个都该能切换、能对比。去完还带着 `--compare` 却没剩下别的 run，直接报错（__main__.py:119，「解析到的是同一个 run（同一阶段），没有可以对比的」），理由和第 3 道一样。
   - 为什么不能只靠 `export_payload`：它也按同样的键去一遍重（现在对 `cmd_graph` 传进去的已经是空操作，留着是它自己接口的保证），可它去重的结果 `cmd_graph` 看不到。以前只有它去重时，`--hot demo --hot <demo 最新那次的完整 id> --compare` 能过第 3 道，摘要照写「另带 1 个 run 可切换」「对比前两个」，实际上 hotBy 是空的、也没有 cmp 块。现在摘要里的数就是去重后的 others 的长度，和导出文件里 hotBy 的条数一致；`--compare` 要么真有 cmp 块，要么报错。

**默认文件名**（__main__.py:125）：各个 REF 用 `+` 连起来，`--compare` 时再加 -vs，比如 overview-a+b-vs.html；没给 `--hot` 时仍然是 overview.html。把所有 REF 都放进名字，是为了让同一对 run 的导出不覆盖单个 run 的导出；加 -vs，是因为带对比的文件内容不一样（多了 cmp 块和 B 的次数），不该和不带对比的共用一个名字。字符白名单见下一节。

**打印**（__main__.py:132 起）：原来那行摘要后面多了「另带 N 个 run 可切换」「对比前两个」（N 是第 4 道去重之后的数）；下面再打一行各部分的大小（__main__.py:136）：graph、graphHot、edges、sources、files、hotBy、cmp 这几块各自 `json.dumps` 之后的长度。为什么要打：设计第 8 节说大小预算沿用 `export_payload` 的额度、命令最后打印各部分大小。多带一个 run，最后被挤掉的是全文（files 只拿剩下的额度），把这几块打出来，才看得出这 16 MB 花在了哪里。量法和 `export_payload` 算额度的一样（ensure_ascii=False 下的字符数，不是 UTF-8 字节数），所以能直接和预算比。空的块（"null"、"{}"，不超过 4 个字符）不打。

### 两处编码 / 文件名的小防线
- **graph 的默认文件名**（__main__.py:126）：`--hot` 是 REF，会带 `@阶段`，也可能是迁移来的老 case 名（老版本允许中文、`+`）。只保留 `[A-Za-z0-9@._+-]`，其余换成 `_`，得到 overview-<case>@<phase>.html 这样的名字。M7 起白名单里加了 `+`，因为它是多个 REF 之间的连接符（见上一节）；设计 4.5 的导出文件名一条也已经跟着改了（`+` 连接、`-vs`、白名单带 `+`）。
- **stdout / stderr 改成 backslashreplace**（__main__.py:662）：命令行、路径里可能有不是 UTF-8 的字节，Python 把它们解码成孤立的代理字符，一打印就抛 UnicodeEncodeError——而 `cmd_trace` / `runs show` 要把整条命令打出来。改成打印转义。放在 `parse_args` 之前，argparse 自己的报错也受保护；流没有 `reconfigure` 时跳过。`tests/test_runs.py` 里有带 0xff 字节参数的用例。（`runs show` 的「命令」行靠它打成转义；「复刻」行另由 `runs._q` 写成 `$'…'`，照抄能还原原来的字节。）

### 自己按第一个 `--` 切 argv
`trace . --case X -- python demo.py` 里，`--` 之后的整条命令要原样交给被 trace 的进程。argparse 的 REMAINDER 和可选位置参数放在一起时会互相抢参数（会报 `--case` 缺失），所以 `main` 先自己按第一个 `--` 切开（__main__.py:668），前半给 argparse，后半直接当命令。切之前先把整份 argv 记成 `invocation`（见「复刻」一节），所以复刻命令里 `--` 和后面的命令都在。子命令的 dest 也因此不能叫 `cmd`：trace 的位置参数叫 `cmd`，两者会互相覆盖，所以叫 `which`（__main__.py:552）。

### scan：默认切面上的摘要，交叉引用在 scan 里建
`scan --depth` 默认 `auto`（按规模自动拆分），给数字就是固定深度；`--expand DIR`（可重复）在默认切面上额外展开某个目录。两者都只影响**默认切面**，图上随时还能展开 / 收起。`cmd_scan` 打印的节点数、高度列表都是默认切面上的（`cut.visible` 过滤掉只有空 `__init__.py` 的目录，__main__.py:65 起）。写完 index 紧接着用同一份 `idx` 调 `xref.build` / `xref.write`（__main__.py:81）：和符号表是**同一时刻的快照**，行号才对得上。serve 端只读不建（`payload.load_xref` 按修改时间缓存，文件不存在就不给 Ctrl+点击）；代价是 scan 要把全仓再 parse 两遍。

## 局限
- 「只读的动词不建目录」只是不建 .codestrata、不写 .gitignore / README.txt：`runs.runs_dir` 在 .codestrata 存在、runs/ 不在时会建 runs/，`catalog` 第一次调用时会做迁移（搬动老的 trace 文件）。
- ls 为了「改过」一列逐个读 detail.json、为了大小逐个走 run 目录，不像设计 3.2 说的「列表只读 run.json」（run.json 里的 `sizes` 只记顶层文件，不含 files/、events/ 和中断的 run 散着的 parts/）。run 多了 ls 会变慢。
- ls 的「改过」= changed + mismatch（__main__.py:392），而前端 hot 叠加的 `stale_files` = changed + gone（runs.py:777），两处口径不一样。
- ls 的「时序!」比「时序」和空白多一列（多出来的「!」是半角），整理失败的那行 tag 列会错一格。
- 默认文件名会把所有 REF 连起来，而完整 id 是 16 位时间戳加 case 名，可能还带 @阶段。`--hot` 给多了，文件名会超过常见文件系统 255 字节的上限；代码没有截断。另外文件名用的是字面去重后的 REF，不是第 4 道之后的：`--hot demo --hot <demo 最新那次的完整 id>` 只嵌了一个 run，文件名里仍是两个。
- `runs show X@阶段` 会校验阶段存在，但打印的内容不分阶段（`phase` 没用上）。
- `runs show` 的「阶段」行只有起始时刻、函数数、调用数：不说这一段是哪个 `--phase` 的函数切的、还是 case 脚本写的，也不报没切到的 `--phase`。这些只在 trace 结束时的两句警告和网页的阶段表里，事后在命令行上只能从复刻命令里的 `--phase` 反推。
- 「没切到」的提示把原因说成「对应的函数这次没被调用」；调用它的进程没被 hook 到（hook 靠 PYTHONPATH 注入，trace.py:892，自己清空环境再起的子进程就没有）也是同样的结果，提示不区分。
- 继承的环境只记白名单里的：case 脚本自己读、又不带那些前缀的变量（比如自定义的模型路径变量）不会记下，复刻时要自己补。
- `_cwd` 只保住了 `main` 本身：当前目录已被删时，`cmd_trace` 对相对的 repo 取 `resolve()`（__main__.py:215）、给相对的 `--attach` 拼 `Path.cwd()`（__main__.py:232）都要读当前目录，会直接抛 FileNotFoundError，不是 SystemExit 那样的中文提示。反过来，这种情况下录得下来的 run（`invocation` 的 cwd 是 None，复刻命令没有 `cd` 那一截），repo 和 `--attach` 必然是绝对路径（`--phase` 的文件路径本来就按仓库根目录算），被 trace 的命令又固定在仓库根目录跑（trace.py:944），少了 `cd` 不影响复刻。
- 直接用 `runs` 的私有函数 `_read` 读 run.json / detail.json，跨模块依赖了私有名字。
- `cmd_scan` 里 `x` 先绑成 xref 的结果，下面高度列表的循环又把 `x` 当成节点复用（__main__.py:86）；都不出错，但读的时候容易看串。

## 不确定
- `cmd_serve` 在函数体内才 `from . import serve`（__main__.py:545），代码里没写原因；推测是让不启动服务的子命令不必加载 `http.server`。
- `cmd_trace` 在 `runs.new_run` 之前先调 `runs.catalog` 做迁移，注释只说「先把老格式的 trace 迁进 runs/」，没说为什么要赶在录制之前；不迁的话下一次任何命令调 `catalog` 时也会迁。
- `runs show` 把复刻命令和继承的环境分开打（复刻那一行不带 `env K=V…` 前缀，网页上另有一个「连环境变量一起」的复制按钮），代码里没写为什么 CLI 不给带环境的那一版；可能是 PATH 之类的值太长，混进一条命令里难读。
