---
written_by: claude-opus-5-5
target: codestrata.__main__
kind: package
code_sha: 3aedd60da3fa151d
status: draft
refs: __main__.py:256@b87faf5c,__main__.py:250@8ac31b40,__main__.py:219@30b1fec8,__main__.py:232@c90a9ebb,__main__.py:238@059c6e94,__main__.py:251@6109ee57,__main__.py:307@fea936cf,__main__.py:308@80bacee0,__main__.py:299@80bacee0,__main__.py:240@a241b857,trace.py:745@ea5dcb7a,__main__.py:247@90ff2a42,runs.py:893@af308051,__main__.py:277@a7c090eb,__main__.py:285@f7dc7f40,__main__.py:283@8b67ac5a,runs.py:377@33e517e7,__main__.py:426@dc6fc688,__main__.py:243@e57ae09a,__main__.py:338@b67404aa,__main__.py:340@b09cd715,__main__.py:593@72d37402,__main__.py:356@09bf7a10,__main__.py:375@49ae8d76,serve.py:227@d751bac7,__main__.py:418@c4688ddf,__main__.py:448@8569ebbe,__main__.py:471@b11d1384,__main__.py:489@1d7387f6,__main__.py:611@78ac2d86,__main__.py:474@a52cc99e,__main__.py:483@499fe1b3,__main__.py:492@cab0d66d,__main__.py:497@03b2082a,__main__.py:48@8964b0de,__main__.py:35@22ae2662,__main__.py:539@f63b232a,__main__.py:541@18d874a4,__main__.py:103@c408ea25,__main__.py:104@9b58cee4,__main__.py:106@77bed867,__main__.py:107@c224cee8,__main__.py:112@7fb1a314,__main__.py:119@739253ed,__main__.py:125@5e4008de,__main__.py:132@a647a88e,__main__.py:136@d4def5e0,__main__.py:126@ea1a2f4a,__main__.py:627@9c6178dc,__main__.py:632@ec9fb5ef,__main__.py:521@d41c8ef6,__main__.py:65@04903107,__main__.py:81@d89a80ca,__main__.py:367@9371b1a0,runs.py:768@bbf3acab,__main__.py:86@0c3e9807,__main__.py:514@4c85e081
---

## 是什么
命令行入口：`scan` / `trace` / `runs` / `serve` / `graph` / `tasks` / `pack` / `note` / `check` 九个子命令。大多数只把参数转交给对应模块；M1（`docs/design/runs.md`）之后多了两块真正的 CLI 逻辑：`cmd_trace` 把每次录制存成一个**新的 run**，`cmd_runs` 管理录下的 run（ls / show / tag / untag / note / rm / merge）。M3 在这两块上各加了一点：`trace --events` 顺带录时序事件（时序图的数据），`runs rm --events-only` 只删事件；trace 的输出和 `runs show` 报事件的摘要，`runs ls` 标一个「时序」（整理失败的标「时序!」）。它还管 .codestrata/ 目录本身：`_outdir` 建目录时顺带写一份 .gitignore 和一份 README.txt。`scan` 一次写出 index.json、symbols.json，以及给全文窗口 Ctrl+点击用的交叉引用 xref.json。M7 起 `graph` 也有了一点 CLI 逻辑：`--hot` 可以给多个（第一个是主 run，其余在导出的单文件里可切换），`--compare` 让主 run 和第二个对比。

所有 `--hot` 的参数现在叫 RUN（模块 docstring 末尾）：完整的 run id，或 case 名（取它最新一次录完的），后面可以加 `@阶段`。解析全在 `runs.resolve`，这里不碰：graph（字面去重后，每个 `--hot` 各调一次）/ tasks / pack 透传给 `payload.load_hot`；serve 的 `--hot` 交给 `serve.main`，M4 起它只决定页面打开时先选哪个 run，页面上随时能换，换 run 不用重启 serve。只有 graph 的 `--hot` 能重复：tasks / pack 的仍是单个（`notes.prompt_pack` 只收一个 hot），serve 的也是单个——对比在页面上现选（工具栏「对比」，地址里记 cmp=），不用在命令行上给。

## 为什么这样切
它是唯一的入口层（高度 +1）：出边 9 条，没有人依赖它。原则还是「薄」：`cmd_*` 解析参数、调模块、打印摘要。`cmd_trace` 和 `cmd_runs` 占了文件一半多，但里面放的仍是 CLI 该管的事——参数校验（`--env` 的 K=V、tag 的字符集、`--attach` 的路径）、摘要怎么打印、删之前的交互确认。run 是什么、REF 怎么解析、收尾 / 重算 / 删除的规则、事件怎么整理成 span，都在 `runs`（和 `codestrata/events.py`）里；这里只读 run.json 里现成的 `events` 摘要，不 import `events`。

三条边界值得注意：
- **录制是在这里缝起来的**：`runs.new_run` 建目录 → `trace.run` 跑命令 → 经 `after` 回调调 `runs.finalize`（__main__.py:256）。`runs` 依赖 `trace`，`trace` 不 import `runs`，所以 `trace.run` 只开一个 `after` 口子，由上层把收尾塞进去。
- **事件的开关只是一个环境变量**：hook 在被 trace 的进程里看 `CODESTRATA_EVENTS` 是不是 "1"，CLI 每次都把它明确写给命令——`--events` 时 "1"，否则 "0"（__main__.py:250，理由见下）。录不录、怎么配对、上限，全在 `trace` 的 hook 里。
- **删除的安全规则两层都有**：`cmd_runs` 的 rm 先把每个参数查一遍（完整 id、不在录）再统一确认，一个不对就一个都不删；`runs.remove` / `runs.remove_events` 自己也再挡一次（后者还拒绝删还有进程在往 parts/ 写的 run）。

图上它的出边没有虚线：每条都真的调用了对方的函数（`serve` 是在函数体里 import 的，也算一条边；`xref` 由 `cmd_scan` 直接调 `build` / `write`）。

## 读法
1. 模块 docstring —— 子命令一览（graph 那行写成 [--hot RUN]… [--compare]，和 argparse 一致），以及 RUN 的写法
2. `main` —— argparse 的搭法：`runs` 的两级子命令、trace 的开关（含 `--events`）、rm 的 `--events-only`，最后的 stdout 重配和切 `--`
3. `cmd_trace` —— 一次录制从建 run 到打印结果的全过程，对照设计文档 4.2 读；事件相关的是 `env_run` 和打印里 `ev` 那一段
4. `cmd_runs` —— 按动词分段；ls / show 是纯展示，rm 是唯一不可逆的
5. `_outdir` 和 `_README` —— 很短，但写明了 .codestrata/ 里哪些能删
6. `cmd_graph` —— 多个 `--hot` 的四道检查（三道看字面，一道看解析到的 run）、默认文件名、各部分大小的打印；数据怎么拼在 `payload.export_payload`
7. `cmd_scan` 及其余 `cmd_*` 按需看，都很短

## 关键算法
### trace：每次都是新的 run，收尾在 driver 的信号处理器保护下做
以前 `cmd_trace` 把结果写成 `trace-<case>.json`，同名 case 重录就覆盖——而一次录制可能是几分钟的 GPU。现在的流程：
1. **先校验，再建目录**（__main__.py:219 起）：`--env` 必须是 K=V；`--tag` 只能用 `_TAG_RE` 里的字符；`--attach` 的文件必须存在。case 名在 `runs.new_run` 里校验，也在建目录之前。参数填错不会留下一个空 run。
2. **`--attach` 的相对路径先按仓库根目录找**（命令就是在那里跑的），找不到再按当前目录（__main__.py:232），存成绝对路径。被 case 脚本 source 的 common.sh 不会出现在任何进程的 argv 里，只能靠它存进 run。
3. **`runs.catalog` 先把老格式的 trace 迁进 runs/**（__main__.py:238），再由 `runs.new_run` 建目录、写 `status: recording` 的 run.json。录制开始前就把 run id 和目录打到 stderr（__main__.py:251）。`mono0_ns` 从刚写的 run.json 里读回来交给 `trace.run`，所以各阶段、各进程的时刻（包括事件的时刻）都相对 run.json 里记的同一个零点。
4. **收尾放在 `after` 里**：`trace.run` 的信号处理器一直装到 `after` 返回，打包 parts 的中途按 Ctrl+C 不会把 run 弄成半截（设计文档 4.3「driver 的信号」）。事件日志的打包和整理也在 `runs.finalize` 里，同样受保护。
5. **打印**：状态（`_STATUS` 译成中文，外加 problems）、进程数（单列跑到仓库代码的）、各阶段的函数数、跑的若是安装包就说明映射回仓库后是否逐文件一致（不一致的文件行号不可信）、时序事件的摘要（见下一节）、命令退出后停掉的残留进程、存下的文件、没存下来的 `--attach`。
6. **建议一条叠图命令**（__main__.py:307）：写的是**完整 id**——case 名会解析到该 case 最新一次 ok 的 run，这次若是 partial，用 case 名叠的就不是它；run 里有 serving 阶段就加 `@serving`，因为启动时的初始化会淹没请求本身。
7. **退出码**（__main__.py:308；还没 scan 提前返回的那条在 __main__.py:299，同一个规则）：只有 failed（一个函数都没录到）返回 1，partial 也返回 0。

其余开关：`--stop-grace`（默认 90 秒）是停的时候 SIGINT 之后等多久再发 SIGTERM，留给 case 脚本自己的 trap 收尾；`--env` 只把这些变量加给命令并记进 run，不抓整份环境（设计 1.1：防止把 token 存进去）；`--roots` 或自动探测的包根算出「顶层包 → 仓库内目录」（__main__.py:240），命令跑的若是 pip 安装的那份，trace 靠它映射回仓库。

### --events：以命令行为准，run 里记的是「要了事件」
- **变量只给命令，而且总是写明**：`env_run` = 用户的 `env` 加上 `CODESTRATA_EVENTS`（"1" 或 "0"，__main__.py:250），传给 `trace.run` 的是它，传给 `runs.new_run` 的仍是用户的 `env`。
  - 为什么不记进 run 的 env：那里的语义是「用户给命令加的变量」，重录命令会逐个写成 `--env K=V`；把内部开关混进去，重录命令就会变成 `--env CODESTRATA_EVENTS=1` 而不是 `--events`。
  - 为什么不带 `--events` 也要写 "0"：`trace.run` 给命令的环境是整份 `os.environ` 再叠 `env_extra`（trace.py:745）。shell 里恰好 export 了 `CODESTRATA_EVENTS=1` 的话，不写 0 就会悄悄录事件，而 rec 里记的是没要、重录命令里也没有 `--events`——录出来的 run 和它的重录命令对不上。写明之后开关只有 `--events` 一个：`env_run` 里它写在后面，`--env CODESTRATA_EVENTS=1` 也会被盖掉。
- **意图记在 rec 里**：`"events": bool(a.events)`（__main__.py:247），`runs.rerun_command` 看到它就加 `--events`（runs.py:893）。记的是「要了」，不是「录到了」：录空了、或之后被 rm --events-only 删了，重录命令照样带 `--events`。
- **三种结果三种说法**（__main__.py:277 起），数据都是 `runs.finalize` 写进 run.json 的 `events` 摘要：
  - 有 `error`：整理成 span 失败。原始日志已经先落进 events/raw.tar.gz，所以提示可以 `runs merge` 重来；
  - 正常：事件行数 → span 数（第一级折叠之后，连续的同类叶子调用合成一条，所以不多于调用次数）、跨文件调用次数（各 span 的 rep 之和）、原始日志压缩后的大小；
  - 要了 `--events` 却没有摘要（__main__.py:285）：`runs` 在没有任何事件日志时不写摘要。原因列了三种——命令没起来；被 trace 的 Python 低于 3.12（hook 只在有 `sys.monitoring` 时录）；或者这次根本没有跨文件的调用（缓冲是空的，hook 就不建日志文件）。最后一种是正常结果，不是故障，所以提示里不能只怪 Python 版本。这里明说出来，免得以为录到了。
- **到了行数上限是 ⚠，不是状态**（__main__.py:283）：上限只管新的调用行，计数是完整的；`runs.derive` 故意不把它算进 status（runs.py:377）——算进去 run 会变成 partial，拿 case 名解析时就跳到更早的一次 ok。所以 CLI 这边只在摘要后面挂一句「N 个进程到了行数上限，之后的调用没记时序（计数完整）」；`runs show` 用同样的说法，另把 pid 列出来——多于 8 个只列前 8 个、后面加「…」（__main__.py:426），好让人知道列表不全。
- **行数上限从 shell 继承时，要记进 run 的 env**（__main__.py:243）：hook 同样读 `CODESTRATA_EV_MAX`。带了 `--events`、shell 里 export 了它、`--env` 里又没给时，CLI 把 shell 的值抄进 `env`——意图是让它记进 run、出现在重录命令里（`--env CODESTRATA_EV_MAX=…`），这次录制的上限才复现得出来。和开关的处理正好相反：`CODESTRATA_EVENTS` 以命令行为准、主动盖掉 shell；上限不盖，只把 shell 里悄悄生效的值写明。只在 `--events` 时抄（不录事件时上限没有意义，不该混进 run 的 env）；`--env` 给了的以 `--env` 为准。这一步放在 `runs.new_run` 之前：`new_run` 当场把 `env` 写进 run.json，之后不再改它，放在后面就只给了命令、没记下来（早先就是这样错的，test_events_cap 里有从 shell 继承的用例）。

### runs：只读的动词不建 .codestrata，rm 只认完整 id
- **入口先查仓库目录和 .codestrata/ 都在**（__main__.py:338、__main__.py:340），不调 `_outdir`：路径写错（比如少写了 src/vllm-omni）要报出来，而不是悄悄建一个空的。`runs` 的 repo 是必填位置参数（__main__.py:593），不像别的子命令默认 `.`——设计 1.1：可省略的 repo 会把动词当成自己。
- **ls**：第一行打印 runs/ 的真实路径，是软链时注明（vllm-omni 的 runs 在 /mnt/data 上）。按 case 分组，组的先后按该 case 最新一次 run 的时间（`catalog` 新的在前，__main__.py:356）。每行：id、状态（driver 已经没了的 recording 显示成「中断」，即 `status_shown`）、时长、跑到仓库代码的进程数、git 短哈希、相对当前 index 改过的文件数、大小（`_run_size` 现走目录）、「时序」标记、tag、备注；总量超过 1 GB 时提醒。
  - 「时序」只在 `events` 摘要存在**且没有 `error`** 时标（__main__.py:375）：标记的意思是「有 span、时序图能看」，整理失败的 run 没有 span，标了会误导。整理失败的标「时序!」：它有原始日志、可以 `runs merge` 重来，和没录事件的 run 不是一回事，不该要 show 才看得出。页面上 serve.py:227 对整理失败给 events=false、另给 events_error=true：下拉里不标「时序」，工具栏的「时序图」按钮置灰、提示写的是「整理失败，runs merge 重来」而不是「没录」。没有摘要时留四个空格（和「时序」同宽），后面的 tag 列不错位。
- **show**：解析 REF，打印 run.json 和 detail.json 的摘要；run 有 `events` 摘要时多一行「时序」（__main__.py:418）：span 数、调用次数、进程数、原始日志大小，到了上限的进程或整理失败也在这一行说。文件状态由 `runs.file_state` 相对**当前 index** 算（不是工作区：叠加用的行号来自 index），每种最多列 12 个（`_FS` 是状态的中文名）；最后是 `runs.rerun_command` 拼的重录命令（__main__.py:448），repo 用的是用户敲的原样路径。
- **tag / untag / note 接受 case 名，rm 不接受**：前者改的是该 case 最新一次 ok 的 run，改错了能改回来；rm 删错了没法重建（设计 4.3 末尾）。rm 先把所有参数查完——去重（`dict.fromkeys`，同一个 id 写两遍只删一次）、必须是完整 id（是 case 名时报错里列出这个 case 的所有 run，方便复制）、不能在录（__main__.py:471）——再列出要删的东西和大小。没有 `--yes` 时，终端里要答 y；不是终端就直接拒绝（__main__.py:489），脚本里不会误删。
- **rm --events-only**（参数在 __main__.py:611）：走完全相同的检查；查完先挑出**没有时序事件**的 run——既没有 events/，parts/ 里也没有散着的 ev-*.log（__main__.py:474 起）——各打印一句「没有时序事件」，不问也不删，全都没有就直接返回 0：没东西可删还要答 y/N 只是噪音，之后再打「删了 … 的时序事件」更会让人以为真删了什么。看的是磁盘而不是 run.json 的 `events` 摘要：还没 merge 的中断 run 没有摘要，原始日志却散在 parts/ 里。剩下的照常确认，说的都是事件那一块——列表里的大小是 events/ 加上 parts/ 里散着的 ev-*.log（__main__.py:483，标「（时序事件）」），正好是 `runs.remove_events` 要删的那些：不拿整个 run 的大小，免得看起来能腾出的空间比实际大，也不会让中断 run 显示 0B；确认语是「删掉这 N 个 run 的时序事件？不能重建。」（__main__.py:492），非终端的拒绝语是「删时序事件要确认」；最后调 `runs.remove_events` 而不是 `runs.remove`（__main__.py:497）。它删 events/（原始日志和 span 都删；还没 merge 的中断 run 连 parts/ 里散着的事件日志一起删），计数和其余数据留着，run.json 的 `events` 置空，ls 的「时序」标记随之消失。为什么也要完整 id 和确认：原始事件日志是原始数据，删了不能重建，和删整个 run 同级。用处是事件是 run 里最大的一块（设计 7.3 估算原始日志 gzip 后 4–6 MB），想留着叠图的计数、不要时序时可以只删它。
- **merge**：转给 `runs.merge_run`（从原始分片重算派生数据，M3 起也从 events/raw.tar.gz 重建 span）。

### _outdir：.gitignore 和 README.txt
每次 `_outdir` 被调用（scan、trace、不带 `--out` 的 graph、tasks --write），缺哪个就写哪个（__main__.py:48），已有的不覆盖：
- **.gitignore 内容是 `*`**：整个 .codestrata/ 不进被分析仓库的 git。实测 vllm-omni 的 git status 一直显示 `?? .codestrata/`——被分析的仓库不该因为用了 codestrata 多出未跟踪文件。
- **README.txt（`_README`，__main__.py:35）**：除 runs/ 以外都能删、都能重建；runs/ 是 trace 录下的运行数据，不能重建。老的说法「.codestrata 随时可重建」到 M1 就不对了，以后的会话照着它 `rm -rf` 就会丢掉 GPU 录的数据。它是设计文档「误删 runs/」的四道防线之一（另外三道：runs/ 可以是软链、仓库 README、agent 记忆的修正）；是软链时 `rm -rf .codestrata` 只删链接本身。

### graph：多个 `--hot` 和 `--compare`（M7）
graph 的 `--hot` 改成可重复（__main__.py:539）。第一个是主 run，和以前一样全量嵌入（hot、hotMeta、graphHot，以及每条边带调用明细的边详情）；其余的作为 others 交给 `payload.export_payload`，只带它们在导出切面上的节点次数、边次数和精简过的 meta（EMB.hotBy），页面上能切过去，但边详情的调用明细只有主 run 的（设计第 8 节）。为什么不每个都全量嵌：单文件有 16 MB 的上限，`export_payload` 先把其余部分算好，剩下的额度才给全文，每多全量嵌一个 run，挤掉的就是全文。`--compare`（__main__.py:541）让主 run 和第二个对比：嵌一个 cmp 块，边详情每项带上 B 的次数（`payload.edge_compare`）；第三个起仍然只是可切换。

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
- **stdout / stderr 改成 backslashreplace**（__main__.py:627）：命令行、路径里可能有不是 UTF-8 的字节，Python 把它们解码成孤立的代理字符，一打印就抛 UnicodeEncodeError——而 `cmd_trace` / `runs show` 要把整条命令打出来。改成打印转义。放在 `parse_args` 之前，argparse 自己的报错也受保护；流没有 `reconfigure` 时跳过。`tests/test_runs.py` 里有带 0xff 字节参数的用例。

### 自己按第一个 `--` 切 argv
`trace . --case X -- python demo.py` 里，`--` 之后的整条命令要原样交给被 trace 的进程。argparse 的 REMAINDER 和可选位置参数放在一起时会互相抢参数（会报 `--case` 缺失），所以 `main` 先自己按第一个 `--` 切开（__main__.py:632），前半给 argparse，后半直接当命令。子命令的 dest 也因此不能叫 `cmd`：trace 的位置参数叫 `cmd`，两者会互相覆盖，所以叫 `which`（__main__.py:521）。

### scan：默认切面上的摘要，交叉引用在 scan 里建
`scan --depth` 默认 `auto`（按规模自动拆分），给数字就是固定深度；`--expand DIR`（可重复）在默认切面上额外展开某个目录。两者都只影响**默认切面**，图上随时还能展开 / 收起。`cmd_scan` 打印的节点数、高度列表都是默认切面上的（`cut.visible` 过滤掉只有空 `__init__.py` 的目录，__main__.py:65 起）。写完 index 紧接着用同一份 `idx` 调 `xref.build` / `xref.write`（__main__.py:81）：和符号表是**同一时刻的快照**，行号才对得上。serve 端只读不建（`payload.load_xref` 按修改时间缓存，文件不存在就不给 Ctrl+点击）；代价是 scan 要把全仓再 parse 两遍。

## 局限
- 「只读的动词不建目录」只是不建 .codestrata、不写 .gitignore / README.txt：`runs.runs_dir` 在 .codestrata 存在、runs/ 不在时会建 runs/，`catalog` 第一次调用时会做迁移（搬动老的 trace 文件）。
- ls 为了「改过」一列逐个读 detail.json、为了大小逐个走 run 目录，不像设计 3.2 说的「列表只读 run.json」（run.json 里的 `sizes` 只记顶层文件，不含 files/、events/ 和中断的 run 散着的 parts/）。run 多了 ls 会变慢。
- ls 的「改过」= changed + mismatch（__main__.py:367），而前端 hot 叠加的 `stale_files` = changed + gone（runs.py:768），两处口径不一样。
- ls 的「时序!」比「时序」和空白多一列（多出来的「!」是半角），整理失败的那行 tag 列会错一格。
- 默认文件名会把所有 REF 连起来，而完整 id 是 16 位时间戳加 case 名，可能还带 @阶段。`--hot` 给多了，文件名会超过常见文件系统 255 字节的上限；代码没有截断。另外文件名用的是字面去重后的 REF，不是第 4 道之后的：`--hot demo --hot <demo 最新那次的完整 id>` 只嵌了一个 run，文件名里仍是两个。
- `runs show X@阶段` 会校验阶段存在，但打印的内容不分阶段（`phase` 没用上）。
- 直接用 `runs` 的私有函数 `_read` 读 run.json / detail.json，跨模块依赖了私有名字。
- `cmd_scan` 里 `x` 先绑成 xref 的结果，下面高度列表的循环又把 `x` 当成节点复用（__main__.py:86）；都不出错，但读的时候容易看串。

## 不确定
- `cmd_serve` 在函数体内才 `from . import serve`（__main__.py:514），代码里没写原因；推测是让不启动服务的子命令不必加载 `http.server`。
- `cmd_trace` 在 `runs.new_run` 之前先调 `runs.catalog` 做迁移，注释只说「先把老格式的 trace 迁进 runs/」，没说为什么要赶在录制之前；不迁的话下一次任何命令调 `catalog` 时也会迁。
