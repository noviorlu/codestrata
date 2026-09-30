---
written_by: claude-opus-5-5
target: codestrata.runs
kind: package
code_sha: b8297d01ada3dbcf
status: draft
refs: payload.py:61@792c7b2a,runs.py:50@00c33eb4,runs.py:56@67b3e37c,__main__.py:754@d9e158f3,runs.py:165@2caa988e,__main__.py:320@3942e934,runs.py:803@c515376e,runs.py:1@acd28cbf,runs.py:430@73b79d30,runs.py:339@0ac29959,runs.py:349@dcfcecf7,runs.py:366@3be37370,runs.py:871@74b5e2b2,runs.py:586@5aad2956,runs.py:709@2e266090,runs.py:643@9e5a3d78,runs.py:652@9f800a19,runs.py:940@895298bf,runs.py:991@b02040d0,runs.py:804@84b0e0e7,runs.py:783@993ec58b,runs.py:795@d6141a36,runs.py:455@65794504,runs.py:437@749d402b,runs.py:441@f98d9cbc,runs.py:446@1c2edb45,trace.py:1041@fc63f946,trace.py:992@36e85972,runs.py:261@fddbfbb9,runs.py:268@45f781f8,runs.py:202@570c0656,runs.py:257@6209e0a4,runs.py:280@fb2bc1a4,runs.py:223@9b69849a,runs.py:378@5a9894f3,runs.py:402@84b2fc29,runs.py:408@455da9c5,runs.py:398@33e517e7,runs.py:314@060b529e,runs.py:323@e311843b,runs.py:310@287fefa9,runs.py:360@903daee6,runs.py:357@b54abd09,runs.py:411@d5bb93ee,runs.py:413@8e8d8c1a,runs.py:877@4c708cb1,runs.py:881@09ab28d2,runs.py:891@4b07558f,runs.py:898@bcf32585,runs.py:904@b94aaa53,runs.py:906@841ff674,runs.py:908@cd65e4df,trace.py:1089@f13649f2,trace.py:1103@862ce82d,runs.py:910@8224f7cb,runs.py:913@96001191,runs.py:914@e6d02764,runs.py:915@9fc99a86,runs.py:468@40c03a7d,runs.py:474@70cbbd06,runs.py:541@caefdf40,runs.py:550@a3eee4b4,runs.py:560@149a0c4a,runs.py:482@304c7ef9,runs.py:484@1e0f250e,runs.py:499@6e207d1a,runs.py:510@187b238d,runs.py:607@5028c052,runs.py:616@30c67c61,runs.py:602@eee7399e,runs.py:754@2da1635f,runs.py:764@202d8b21,runs.py:771@65890113,runs.py:773@16613a5f,runs.py:785@896ff455,runs.py:786@39489998,runs.py:788@36498fdc,codestrata/web/app.js:744@b9e92f4a,codestrata/web/app.js:747@d997d8bd,payload.py:142@115741f2,payload.py:1193@c79c9f96,runs.py:791@bbf3acab,runs.py:780@e166c143,__main__.py:480@c6d6ff8c,__main__.py:495@db9955bd,runs.py:801@dba2d8d3,payload.py:143@af1a7a55,__main__.py:536@9b7d29d5,codestrata/web/app.js:217@25dc5165,runs.py:806@7664ed49,runs.py:807@9373101f,__main__.py:317@cda3f50d,runs.py:724@c89680b5,runs.py:736@64edc9ec,trace.py:160@c744b643,trace.py:257@12b06831,runs.py:371@2770f6e6,runs.py:497@003ee944,runs.py:666@c84a3c5a,runs.py:672@fa6fb20d,trace.py:1429@754b1b1f,runs.py:686@1fe076b1,scan.py:505@86882a0e,runs.py:690@f22c7dcc,runs.py:693@f22c7dcc,trace.py:1435@8c13640b,trace.py:1492@35b9f6aa,trace.py:1501@2cf2d163,runs.py:684@ed6cc63e,runs.py:700@8c073f56,runs.py:704@8eca2695,runs.py:839@c22fa459,runs.py:848@6b10c511,runs.py:853@21ab656f,runs.py:861@a6506b96,runs.py:866@82399e64,runs.py:868@b4e21cbc,runs.py:924@42395cbd,runs.py:926@ffb247e6,runs.py:930@5782c208,runs.py:936@f41894da,__main__.py:312@e57ae09a,runs.py:1002@d9fbd7f8,runs.py:1016@7e9eb0f8,runs.py:1009@eaf401c1,runs.py:1004@2fd763b4,runs.py:1017@78147f86,runs.py:1018@a2e2b351,runs.py:1020@8c144757,runs.py:1024@af308051,runs.py:1026@0db851a4,runs.py:1023@11e69ebf,runs.py:1032@6677f901,runs.py:1035@f8bd684b,runs.py:1033@8a8c18db,runs.py:1000@729be3c0,runs.py:969@c46549dd,runs.py:1014@18a1ac37,runs.py:964@f71b3f7a,runs.py:975@137d1da1,runs.py:1029@47a2f59a,runs.py:1043@ab3c0b1b,runs.py:952@5c69ed98,scan.py:481@47fa472f,trace.py:1545@fcd3e9f0,__main__.py:761@429cbc42,codestrata/web/app.js:222@3c7898c7,runs.py:533@103751ee
---

## 是什么
run 的存储层。一次 `trace` 录下的全部东西放进 .codestrata/runs/<id>/ 这一个目录，id = 录制时刻 + case 名（比如 20260927-153412-minicpmo-duplex）。静态分析（index / symbols / xref）只有一份，随时能 scan 重建；run 重建不了，一次录制往往要花几分钟 GPU（起服务、加载模型、跑一段对话）。所以这个模块的原则是**录一次，永久复用**：同名 case 重录不会覆盖旧的，今天录 MiniCPM、明天录 Qwen，两份都留着。

它管五件事：
- **录制的两头**：`new_run` 建目录（M8 起连原样的 codestrata 命令 `invocation` 和 `inherited_env` 挑出来的 shell 环境一起记下），`finalize` 收尾（`capture` → `_pack_all` → `_build_events` → `derive`）。中间真正起命令、注入 hook、合并分片、按 --phase 切阶段的是 `trace.run` / `trace.merge`；把时序事件日志整理成 span 的是 `events.build`。
- **读**：`catalog` 列出所有 run，`resolve` 解析 REF，`load` 把一个 run 映射到当前 index 上（录制之后改过的文件，先由 `remap` 按函数名把键挪到函数现在的行号上，M6）。`payload.load_hot` 只是它外面的一层薄包装（payload.py:61）。M4 起 serve 不再启动时加载一次，而是每个请求现调：run 列表每次现调 `catalog`，叠加按请求里的 run= 调 `resolve` / `load`，结果缓存在 `serve.Handler._hot` 里。主菜单的项目卡片（`projects.status`）先用 `has_runs`（runs.py:50）看 .codestrata/runs 在不在（`os.path.lexists`，悬空的软链也算在，盘没挂上由 `catalog` 报出来），在才调 `catalog`；不用 `runs_dir`，因为它发现目录不存在会顺手建一个，只看状态的地方不该往仓库里写东西。
- **管理**：`set_tags` / `set_note` / `remove` / `remove_events` / `merge_run` / `rerun_command`，分别对应 `codestrata runs <repo> …` 的各个动词（`remove_events` 是 rm --events-only，`rerun_command` 是 show 里的「复刻」）。
- **复刻**（M8）：`rerun_command` 给出一条照抄就能再录一次的命令，`load` 把它（隐去密钥的版本）、继承的环境、--phase 的写法和阶段日志放进 meta（case 命令和各进程的命令行也换成隐去过的），网页「这次跑了什么」和导出都读它。命令行里的秒数（--timeout、--stop-grace）统一用 `fmt_seconds`（runs.py:56）写，主菜单拼录制命令（`jobs.TraceSpec`）用的也是它。
- **兼容**：`migrate` 把老格式的 trace-<case>.json 搬进 runs/。

一个 run 目录的布局：
```
runs/                    可以是软链（vllm-omni 的指到 /mnt/data）；scan 不碰它
  .migrate.lock  .tmp-<id>/     迁移用的锁和半成品
  <id>/
    run.json        小：列表页只读它（状态、problems、命令、执行目录 cwd、env、git、driver、阶段、阶段日志、摘要、
                    events 摘要、tags/note；M8 起还有原样的 codestrata 命令 invocation、继承的环境 env_inherited，
                    rec 里多了 roots、phase_at）
    detail.json     原始：录制时才拿得到的（执行时的哈希、安装包映射、Python/包版本、GPU、git 改动、存下的文件）
    parts.tar.gz    原始：各进程写出的计数分片，原样打包（不含 ev-*.log）
    files/          原始：case 脚本、命令行里提到的配置、--attach 的文件，存的是录制时的样子
    legacy/         原始：只有迁移来的 run 才有，是老 json 逐字节压成的 gz
    counts.json.gz  派生：每个阶段的 funcs / func_edges，外加 names（键 → 录制时的 qualname，remap 用）
    events/raw.tar.gz  原始：时序事件日志 ev-<pid>-<t0ns>.log，只有 trace --events 录的 run 才有
    events/spans/   派生：配好对的 span（keys.json、index.json、p<pid>-NNN.jsonl.gz）
    parts/          只在录制期间存在
```

## 为什么这样切
run 是唯一重建不了的数据，所以所有写 run、删 run 的代码都收在这一个模块里。「除了 `remove` 和 `remove_events`，没有代码会删 run 里的东西」这句话只要审这一个文件就能确认。`trace` 只管录（hook、分片、合并）和折算（`trace.to_package_graph`），对 run 目录只知道 parts/ 在哪；`events` 只管把日志变成 span，写到这里给它的目录；`payload`、`serve`、`__main__` 和主菜单（`projects`、`app`）只通过这里读 run；主菜单的录制表单（`jobs`）不碰 run 目录，只借这里的 `CASE_RE` 和 `fmt_seconds`，case 名的规则、秒数的写法都只有一份。这样 CLI、serve、graph、tasks/pack 的 `--hot` 和网页里的 run 下拉都走同一个 `resolve`，一个 REF 在哪儿都解析成同一个 run。

**原始数据和派生数据分开。** 合并逻辑还不成熟、以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，可以用 `runs merge` 重算。时序事件照同一个办法：原始日志（events/raw.tar.gz）永久保留，span（events/spans/）是派生的，finalize 和 `runs merge` 都会重新整理。反过来，录制时才拿得到的东西（执行时的文件哈希、case 脚本和配置的副本、git 改动、GPU）只写一次，重算时不能拿「现在的样子」去盖。所以收尾拆成两步：`capture` 只跑一次，`derive` 可以反复跑。

**事件日志不进 parts.tar.gz，单独一个包**（设计稿 7.1「实现时的调整（M3）」）。模块 docstring 说的是「`runs rm --events-only` 只删这一块」，再加上结构能推出完整的理由：`_pack` 从不拿成员少的包换成员多的包，如果日志混在 parts.tar.gz 里，删事件就只能重写计数的原始包、还是个成员变少的替换；分开之后，删事件就是删掉 events/ 这一个目录，计数的原始数据一个字节都不碰。

**run 只存原始键（文件:首行号）和执行时的文件哈希。** 加载时才现映射到当前 index 上。代码改了以后老 run 照样能用；哪些文件在录制之后改过，由 `file_state` 逐个标出来，不会让整个 run 作废。改过的文件也不只是标一句「可能偏」：录制时每个键还记了函数的 qualname，加载时按名字把键挪到函数现在的行号上（`remap`，见下文）。行号是会随编辑变的位置，名字是只有录制时才拿得到的身份，两样都存，读的一侧才有退路。

**run.json 和 detail.json 分开**：`runs ls` 列 100 个 run 时只读 100 个几 KB 的文件，不用把几十 MB 的 procs 和哈希都读进来。M4 之后这一条更要紧：serve 的 /api/runs 每次打开下拉都现调 `catalog`，不做文件监视，新录的 run 自然出现；要读 detail.json 的「录制后改过几个文件」由 serve 按 detail 的 mtime 另外缓存。事件也只在 run.json 里留一份几个数的摘要，span 本身留在 events/spans/。

**counts.json.gz 只由 `derive` 写。** serve 缓存 `load` 的结果时（`serve.Handler._hot`），拿 counts.json.gz 和 run.json 的 mtime 当缓存键的一部分：计数只在 finalize / `runs merge` 时变，而 `_write` 是先写临时文件再 `os.replace`，每次重写 mtime 都会变；改 tag、备注、rm --events-only 走 `_update`，只动 run.json，但 meta 里带着 tags、note 和（M6 起）events，所以 run.json 变了也要重算一次。

**复刻靠存下原样的命令，而不是事后拼。**（M8，设计稿「M8」一节。）M8 之前的「重录命令」是从 run 里存的参数拼出来的，漏掉什么就少什么：当时在哪个目录跑、相对路径指到哪、codestrata 装在哪、shell 里 export 了什么。现在 `main()` 把原样的 argv 和当前目录记成 `invocation`（__main__.py:754），`new_run` 原样写进 run.json（runs.py:165 的 docstring 说了为什么：命令里的 --env 只是一部分，被 trace 的命令还继承 shell 的环境），所以 `cmd_trace` 另外调 `inherited_env` 记 `env_inherited`（__main__.py:320）。环境只记白名单里的、名字不像密钥的：设计稿第 10 节写明「不抓整份环境变量」，而这些东西最后会进网页和导出的单文件，导出是「会发给别人」的（runs.py:803 的注释）。按参数拼的老办法只留给没有 `invocation` 的老 run。

**执行目录和仓库分开用。** run.json 的 `cwd` 是被 trace 的命令实际执行的目录：默认仓库根目录，`trace --cwd DIR` 可以换（README「三步上手」：`--cwd .` 是当前目录）。以前命令固定在仓库根目录跑，`cwd` 恒等于仓库，这里有的地方用 repo、有的用 `cwd`，结果都一样；有了 `--cwd` 两者分开，每处都得挑对：命令眼里的相对路径是相对执行目录的，所以找 case 脚本、命令行里的配置文件按 `cwd`（`capture`、`load`）；文件哈希、安装包映射、git 改动和复刻命令里的仓库参数按 repo（`rerun_command`）。挑错的后果是静默的：`--cwd .` 录的 `python case.py`，按仓库找脚本就什么都存不下（或者存成仓库里恰好同名的另一个文件），网页帮助里看不到这次跑了什么；按 `cwd` 写复刻命令的仓库参数，照抄时就会拿 case 目录当仓库去录。

## 读法
1. 模块 docstring（runs.py:1）：录一次永久复用、原始和派生、谁能删 run、为什么只存原始键、events/ 的两半各算哪类数据。设计的来龙去脉在 `docs/design/runs.md` 的第 1、3、4 节，尤其是 4.3 末尾「实现时补上的几条」；时序事件看 7.1–7.3，含「实现时的调整（M3）」和「M3 评审后补上的」两串；serve 怎么用这个模块看第 5 节和 M4 的状态说明；按 qualname 挪行号看 3.5 第 3 条和 M6 的状态说明。
2. `new_run`（runs.py:165）→ `finalize`（runs.py:430）。按录制的时间顺序读，`finalize` 里再按 `capture` → `_pack_all`（runs.py:339）→ `_build_events`（runs.py:349）→ `derive`（runs.py:366）的顺序展开。
3. `merge_run`（runs.py:871）：`finalize` 的「事后重做」版本，读它能看清哪些东西会被重算、哪些不会。
4. `has_runs`（runs.py:50，只看不建）和 `catalog` → `resolve` → `load`（runs.py:586 起），也就是读的那一侧，再加上 `file_state`（runs.py:709），以及 `load` 在两者之间调的 `load_counts`（runs.py:643）和 `remap`（runs.py:652）。
5. `remove`、`remove_events`、`live` / `_alive`：都是小函数，规则写在 docstring 里。
6. 复刻（M8）：`inherited_env`（runs.py:940）→ `_q` / `_secret_flag` / `_redact_argv` → `fmt_seconds`（runs.py:56）→ `rerun_command`（runs.py:991），再回到 `load` 里 meta 的复刻那几个键（runs.py:804 起）和隐去过的 `cmd` / `procs`（runs.py:783、runs.py:795）。设计稿看「M8」一节，尤其是「评审后补上的」里复刻命令那一条；验收是 `tests/test_runs.py` 的 test_rerun_command_reproduces（照抄复刻命令在 / 下执行，再录出同样分段的 run）、test_trace_cwd（`--cwd .` 录的 run，复刻命令先 cd 回当时的目录、带着原样的 `--cwd .`，在 / 下照抄再录出执行目录相同的 run）、test_rerun_command_legacy（按参数拼的那条：仓库写成绝对路径、执行目录不是仓库时带 --cwd，末尾测拼出来的那条也隐去）、test_rerun_secrets_and_bytes（后半段测 case 命令和进程命令行里 --api-key、--hf-token= 的值，以及 --no-auth --port 80 不吃掉 --port），phase_log 看 test_phase_log_from_markers 和 test_merge_recovers_sh_phase_times。
7. `migrate` / `_migrate_locked` / `_cleanup_legacy`（runs.py:455 起）放最后读：只为兼容老数据，逻辑最绕。
8. span 的格式和配对规则不在这里，看 `codestrata/events.py` 的 docstring；场景和断言在 `tests/test_runs.py` 的 test_events_* 和 `tests/trace_cases/fake_repo/fakesvc/truth.py`。
9. 按名字挪行号的验收是 `tests/test_runs.py` 的 test_remap_moved_functions，类体那一半在 test_class_body_is_definition_not_call。

## 关键算法
### 收尾：capture 只写一次，derive 可以重做
`finalize` 先把 stop、returncode、时长、阶段日志写进 run.json（runs.py:437），然后只在 detail.json 还不存在时才调 `capture`（runs.py:441），接着把 parts/ 分两个包打好（runs.py:446），再整理事件，最后调 `derive`。

阶段日志 `phase_log` 在 M8 之后每条是 `[名字, t_us, 来源]`，来源是 start / sh（case 脚本写 PHASE 切的）/ hook（--phase 切的）。`finalize` 只是原样存下 `trace.run` 交来的 `phase_times`；那份在交来之前已经和 parts/ 里的 `PHASE-<名字>.fired` 标记合过一次（trace.py:1041，`trace.merge_phase_log`）：hook 切的阶段用标记里的精确时刻，driver 0.1 秒一次的轮询整个错过的也补上。这次合并用的是 `fired_phases` 默认的 sh=False：driver 轮询到 case 脚本切阶段时也会替它建一个 sh 标记（trace.py:992），但这时轮询的记录还在手上，用不着它。这张表只有收尾时才写进 run.json，录制中途 run.json 里没有它；driver 死在收尾之前的 run 要靠 `runs merge` 从标记补（见下文 merge_run）。

`capture` 收集的东西：
- **文件哈希**：优先用 hook 在进程第一次跑到这个文件时算的那份，也就是执行的那份（runs.py:261）；老分片没有这个哈希的，退回收尾时磁盘上的，并记进 `sha_late`。
- **录制中被改过的文件**：hook 的哈希和收尾时磁盘上的不同，记进 `changed_during`。
- **安装包映射**：安装包和仓库不一致的记进 `mapped_mismatch`；仓库里根本没有的（构建时生成的 _version.py）另记 `mapped_only_installed`，不算不一致（runs.py:268）。
- **环境**：Python 和包版本（`_dists` 只看 dist-info 目录名，不 import 任何东西）、`_gpu`、git 改动。
- **文件副本**（`_collect_files`，runs.py:202）：case 脚本；任何进程的 argv 里出现的、200 KB 以内的 .sh/.py/.yaml/.json/.toml（vllm-omni 的 --deploy-config 指向的 yaml 就是这么存下来的）；`--attach` 点名的文件。相对路径一律按 run.json 的 `cwd`（执行目录，runs.py:257）解析：case 脚本由 `trace.case_script(cwd, …)` 找（runs.py:280，以前传的是 repo，`--cwd` 之后就会找错地方），argv 里的相对路径也在 `_collect_files` 里拼到 `cwd` 上；`--attach` 的路径 CLI 已经解析成绝对路径了。argv 里指向安装包（路径里带 /site-packages/ 或 /dist-packages/）的 .py 不存（runs.py:223，只对来自 argv 的生效，case 脚本和 --attach 不受影响；验收是 test_collect_files_skips_installed_py）：那是被当程序起的第三方代码，比如 py-cpuinfo 会用 `python .../site-packages/cpuinfo/cpuinfo.py --json` 自己起自己，版本已经记在 dists 里；安装包里的配置（非 editable 安装时 --deploy-config 指向的 yaml）照存。被 source 的 common.sh 不会出现在命令行里，只能靠 `--attach`，所以点名的文件不受大小和个数限制。副本存成 files/NN-<文件名>，同名的不会互相覆盖。

`derive` 写 counts.json.gz，重算 detail 里唯一的派生字段 `procs`，再定状态：
- **failed**：一个函数都没录到。
- **ok**：没有任何 problem、退出码 0、`stop == "exit"`。
- **partial**：其余情况，原因写进 `problems`：超时、被中断、driver 中途没了、非零退出码、有进程被强杀、有残留进程、有分片读不出来、有文件在录制中被改过。

「被强杀」的判据是：进程最后一次落盘的原因是定时落盘（periodic）或切阶段落盘（phase），说明它没走到正常退出（runs.py:378）。打包失败时状态退回 recording，并提示用 `runs merge` 重来（runs.py:402）。阶段顺序按阶段日志（同名阶段取第一次出现的时刻），日志里没有的阶段排在后面。`derive` 只按下标取每条的前两项（runs.py:408），所以 M8 之前的两项 `[名字, t_us]` 和现在的三项都读得了；时刻不知道的 hook 阶段（标记建了、内容还没写进去进程就死了）t_us 是 null。

**时序事件不进 status**（runs.py:398）：行数到了上限（`truncated`）或整理失败（`error`）都不加 problem。计数是完整的，只有时序缺了一截；要是因此降成 partial，`resolve` 拿 case 名解析时就会跳过这次、落到更早的一次 ok 上。缺了什么由 events 摘要自己说，`runs show` 会打出来。test_events_cap 用 CODESTRATA_EV_MAX=1 录，断言 run 仍是 ok。

### 打包：分两个包，不拿少的盖多的
`_pack`（runs.py:314）只管「把这些成员打成这个包」：先写临时包，重新打开核对成员数，再 `os.replace`；已有的包成员比这次多，就直接放弃（runs.py:323）。`_pack_all` 按 `_is_event_log`（runs.py:310，文件名 ev-*.log）把 parts/ 里的文件分成两堆：计数分片进 parts.tar.gz，事件日志进 events/raw.tar.gz；没有事件日志就不建 events/。两个包有一个没打成就算失败，parts/ 整个留着。收尾时如果包已经替换好、只是 parts/ 没删干净，不算失败。parts/ 里残留的那几个文件，下次 `runs merge` 时会和包合起来。

### 整理事件：原始日志先落包，整理失败不耽误计数
`_build_events` 在打包之后调：原始日志先进了 events/raw.tar.gz，之后整理出任何问题，原始数据都已经安全。它把 src 里的 ev-*.log 和 run.json 的 `clock.mono0_ns` 交给 `events.build`，span 写进 events/spans/，返回给 run.json 的摘要：
- 成功时是 `n_lines`、`n_spans`、`n_calls`（Σrep，和跨文件的 func_edges 之和相等，两个 test_events_* 都断言了这一条）、`truncated`（到了行数上限的 pid 列表，空列表为假）、`n_procs`、`bytes`。
- `n_procs` 数的是不同的 pid，不是日志文件数：一个 pid exec 前后各有一份日志（进程映像），`events.build` 的 procs 里也各占一行，这里按 pid 去重，`runs show` 的「N 个进程」才和实际进程数对得上。
- 抛任何异常都接住（runs.py:360），摘要变成 `error`（截到 300 字）+ `bytes`。span 是派生数据，`runs merge` 能重来，所以不让它把整次收尾拖垮。
- `bytes` 一律是 events/raw.tar.gz 这个压缩包的大小（runs.py:357），不是日志的文本大小，也不含 spans。test_events_fake_service 断言 merge 前后这个数不变、且等于包的实际大小。

`derive` 拿到摘要才覆盖 run.json 的 `events`（runs.py:411），然后 `setdefault` 成 null（runs.py:413）。所以经过 `derive` 的 run.json 一定有 `events` 这个键：没加 --events 录的是 null，被 rm --events-only 过的也是 null，而且之后再 merge 不会把它变回来（事件日志已经删了，`_build_events` 返回 None）。读的一方（`runs show`、serve 的 /api/runs）一律用 get，迁移来的老 run 没经过 `derive`、没有这个键也不出错。

### merge_run：从并集重算
`merge_run` 先按 REF 解析到 run，再从磁盘重读 run.json（runs.py:877）：`catalog` 给的那份字典带着只用来显示的「中断」`status_shown`，写回去会让 merge 成 partial 之后仍显示「中断」（`derive` 写回前也会去掉这个键）。然后拒绝三种情况：录制还活着；`trace.leftovers` 发现还有进程属于这个 run、可能还在往 parts/ 里写（runs.py:881）；迁移来的老 run 没有原始分片。

之后把 parts.tar.gz 和 events/raw.tar.gz 都解到 .merge-<pid>/（runs.py:891），再把散着的 parts/ 盖上去（同名的是同一份或更新的，runs.py:898）。两个包的文件名不重叠，`trace.merge` 只读 part-*.json，混在一起的事件日志不影响计数。
- driver 死在收尾之前的 run，`stop` 补成 driver-lost（runs.py:904）。
- `phase_log` 每次都用 `trace.merge_phase_log` 重建（runs.py:906，M8）：已有的那份（没有就从 `[["start", 0, "start"]]` 起）加上 `trace.fired_phases(…, sh=True)` 从 .merge-<pid>/ 里读出的标记（runs.py:908）。标记有两种：hook 按 --phase 切时建的（内容是「hook pid monotonic_ns」），和 driver 轮询到 case 脚本写 PHASE 时替它建的（「sh pid monotonic_ns」，trace.py:992；用 O_EXCL 建，每个名字只有第一次进入时那一个）。`PHASE-*.fired` 录制时写在 parts/ 里，收尾时跟着分片进 parts.tar.gz（`_pack_all` 只把 ev-*.log 分出去）；.merge-<pid>/ 是包和散着的 parts/ 的并集，所以收没收过尾都读得到标记。合并的规则（trace.py:1089）：已有的 hook 条目以标记为准、不会重复；sh 标记只补已有日志里没有的名字（trace.py:1103）。收过尾的 run 里轮询记下的 sh 条目都在，sh 标记不会再添东西；driver 死在收尾之前、run.json 里根本没有阶段日志的 run（标记还散在 parts/ 里），则能把 --phase 切的阶段（精确时刻）和 case 脚本切的阶段（driver 轮询看到的时刻，每个名字第一次的）都补回来。test_phase_log_from_markers 测 hook 的：删掉 phase_log 再 merge（标记从包里读），断言阶段一个不少；test_merge_recovers_sh_phase_times 测 sh 的：同样删掉再 merge，serving / shutdown 回来了、每条都有时刻、serving 的来源是 sh、`phases` 里每段的 t_us 都不是 null。M8 之前的两项条目在这里被补上来源（第一条叫 start 的算 start，其余算 sh），之后就是三项。
- detail.json 还不存在的，现在补一次 `capture`，并标成 late（runs.py:910）。这时 files/ 和 git 改动是现在的样子，文件哈希仍是 hook 在执行时记下的。
- 只有 parts/ 还在时才重新打包（runs.py:913）。并集的成员数不会少于旧包，所以不会丢分片。
- span 每次都重新整理（runs.py:914），用的是原始包和散着的 ev-*.log 的并集；test_events_fake_service 断言 merge 前后 span 一模一样。parts/ 要等打包成功、事件也整理完才删（runs.py:915）。
- 已有的 detail.json 和 files/ 一律不重写，`tests/test_runs.py` 里有专门的回归测试盯着这一条。

### 迁移老 trace：加锁，先拷、核对，再删
老版本每个 case 只有一份 trace-<case>.json，外加一个 parts-<case>/。`catalog` 在每个进程里第一次碰到某个仓库时（`_MIGRATED`）顺带触发迁移；serve 每次请求都调 `catalog`，靠这个集合才不会每次都去 glob 老文件。设计稿 3.7 原本打算用 rename 认领，实际实现改成了这样：
- **用文件锁串行**（runs.py:468）：同时起的几个 serve / runs ls 排队等，后来的看到 run 已经在了就跳过。锁随进程释放，所以持锁时还看得到的 .tmp-*，一定是上次迁到一半死掉留下的，删掉重来即可（runs.py:474）。
- **只拷不挪**（runs.py:541）：runs/ 常常是指到另一块盘的软链，rename 跨不了文件系统。老文件逐字节 gzip 进 legacy/，parts-<case>/ 打成 parts.tar.gz。整个 .tmp-<id>/ 建好之后 `os.replace` 落位（runs.py:550），最后由 `_cleanup_legacy`（runs.py:560）核对：legacy 里那份解压后和老文件逐字节相同、包的成员名和 parts-<case>/ 一致，两样都对上才删老文件。任何一步不对就保留老数据。
- **id 是确定的**（runs.py:482）：老文件的 mtime + case 名，重复迁移、并发迁移算出来的都一样。`<id>` 已经存在（上次落位之后、删老文件之前死掉了）的，只补做收尾（runs.py:484）。老版本不限制 case 名（中文、+ 都有），所以目录名用清洗过的字符，run.json 里的 `case` 仍是原名，`--hot 原名` 照样找得到。
- **核对计数**（runs.py:499）：写回去再读出来，各阶段之和要等于老文件的 `funcs` / `func_edges`，每个阶段要逐键相等；对不上就保留老文件，打印原因。
- 老进程记录没有 ppid、argv 只存了前 6 个的，标 `argv_cut`（runs.py:510），界面上照旧提示「被截断」。

### 引用一个 run：REF
`resolve`（runs.py:607）接受 `完整 id | case`，后面可以跟 `@阶段`。先当完整 id 查，查不到再当 case 名：取这个 case 最新一次 ok 的；一次 ok 都没有，就取最新的 partial，再不行取最新的任意一个，并提示用的不是完整录完的（runs.py:616）。这样重录中途失败时，case 名不会被失败的那次抢走。不支持 id 前缀，因为前缀和日期会撞。`catalog` 按目录名倒序，id 以时刻开头，所以倒序就是新的在前。录制进程已经死了的 recording run，另加一个 `status_shown`，值为「中断」（runs.py:602），提示可以 merge；网页下拉里显示的状态也优先取它。

`resolve` 和 `load` 找不到东西时抛的是带中文说明的 `SystemExit`，这是给 CLI 直接打印的；serve 在 `serve.Handler._hot` 里把它接住，转成 404 的 JSON。

### 加载：映射到当前 index，老的 meta 键一个不少
`load`（runs.py:754）用 `load_counts` 读 counts.json.gz（某个阶段的，或者用 `_sum` 把各阶段相加，和老 trace 的 `funcs` 同义），M6 起连 names 一起读（runs.py:764）；接着读 detail.json、算 `file_state`，把录制之后改过的文件交给 `remap` 挪行号（runs.py:771），然后才交给 `trace.to_package_graph` 现算 hot，并在 hot 里写明来自哪个 run（runs.py:773），`notes.prompt_pack` 靠这个说明数字的出处。`file_state` 以前在建 hot 之后才算、只用来填 meta，现在挪到了前面：`remap` 要靠它知道哪些文件需要挪。`load` 自己不缓存，缓存在 serve 那边。meta 保留老 payload 的全部键，前端（`codestrata/web/app.js`）认的就是它们：
- `phases` 只有一个阶段时给空字典（runs.py:785），和老 trace 一样，前端据此判断分没分阶段。
- `unmapped` 只数 anon：lambda、闭包、生成器表达式里的调用，算到文件上、没有自己的符号（runs.py:786）。定义时的执行另给一个 `defs` = 模块顶层执行 + 类体执行（runs.py:788）。以前 `unmapped` 直接取 hot 里的同名键（模块顶层 + anon），横幅上那句「未归到命名符号的调用」把 import 时的模块顶层执行也算了进去；现在 `trace.to_package_graph` 把类体（class 语句执行时跑一次的帧）也认成定义（`class_frames`），这两样是「定义、不是调用」，和「调用了但说不出是哪个函数」不是一回事，前端横幅拆成两句（codestrata/web/app.js:744、codestrata/web/app.js:747）。`payload._meta_brief` 两个键都带（payload.py:142），导出里其它 run 的 hotBy 里 `unmapped` 也取 anon（payload.py:1193），口径一致。
- `stale_files` = changed + gone（runs.py:791）。mismatch 另有「安装包和仓库不一致」那句话，所以不算在这里。设计稿 3.5 写的是 changed + mismatch，以代码为准。
- `script` 优先读 files/ 里存下的那份（saved 为真）；老 run 没存脚本的，按 run 的 `cwd`（执行目录）找现在的文件（runs.py:780），并标明不是录制时的内容。
- `cmd`（网页帮助里的「case 命令」）和 `procs` 里每一组的 argv 都先过 `_redact_argv`（runs.py:783、runs.py:795），和复刻命令同一套隐去规则（见下文「复刻命令」）。键名和形状都不变；完整的只在 run.json / detail.json 里，`runs show` 照样不隐去（__main__.py:480 打命令；进程表直接读 detail.json，只是每组截到 110 个字符、只列前 8 组，__main__.py:495）。`procs_grouped` 按原始 argv 分组、之后才隐去，所以只差在密钥值上的两个进程仍是两行、看上去一样。早先的时序图不读这里的 meta，自己把各进程的 argv 过同一个 `_redact_argv` 再显示；时序图去掉之后，页面上的进程命令行只剩这里给的这一份。

在老键之外，meta 再加上 run 的信息：`run_id`、`status`、`problems`、`git`、`tags`、`note`、`created`、`migrated_from`、`file_state`，以及 M6 补上的、设计稿第 5 节列过的两个键（runs.py:801）：
- `unmatched`：`remap` 在改过的文件里按名字对不上的**键的个数**（一个「文件:首行号」算一处，不是调用次数）。前端横幅上它是单独的一句「⚠ N 处按函数名对不上：这些调用只算到文件上，不算到函数上」，只看这个数，不再挂在「录制后有文件改过」那句后面：只有 mismatch 文件的 run，`stale_files` 是空的，也要能看到。相应地，mismatch 那句从「行号不可信」改成了「已按函数名对到仓库里的位置」，「录制后改过」那句也说明改过的已经挪过了。
- `events`：run.json 里的 events 摘要原样透传（没录的、被 rm --events-only 过的是 null，整理失败的带 `error`）。`load` 仍然不读 events/；前端判断「能不能开模块图的「时间顺序」」看的是 serve 的 /api/runs 给的布尔值（整理失败的算没有），不看这个键；用到它的是对比横幅：两边 meta 的 `events` 一真一假时，提示「一个录了时序事件、一个没录」。

M8 再加复刻用的七个键（runs.py:804 起），`payload._meta_brief` 也原样带上（payload.py:143），所以导出里的其它 run、对比时的 B 也带着这些键：
- `rerun`：`rerun_command(…, redact=True)`，隐去密钥的那条（runs.py:804）。网页和导出拿到的都是隐去过的（`rerun_env` 也是），完整的只在 `runs show` 里打（__main__.py:536）。
- `rerun_exact`：run 里有没有存原样的命令（`invocation.argv`）。假的时候前端注明这条是按参数拼的，仓库路径是现在这个仓库的、执行目录不是仓库根目录的写成 --cwd（codestrata/web/app.js:217），和下面 `rerun_command` 的老 run 那条路一致。
- `rerun_redacted`：隐去的版本和完整的不一样，也就是真有东西被隐去了（runs.py:806），前端据此写一句说明。
- `rerun_env`：前面带 `env K=V…` 的那条（`with_env=True`，同样隐去），只有 `env_inherited` 非空时才有，否则是 null（runs.py:807）。
- `env_inherited`：每个值再过一遍 `_scrub`。录制时 `inherited_env` 已经隐去过一次，重复做结果不变。
- `phase_at`：`rec` 里存的 --phase，每项 `{name, func, file, qualname, line}`（__main__.py:317 写入）；`phase_log`：run.json 的阶段日志原样给（三项的；M8 之前录、之后没 merge 过的老 run 是两项的，前端把没有来源的当 case 脚本写的，叫 start 的除外）。前端的阶段表拿两者对照：哪段是第一次进入哪个函数切的、哪段是 case 脚本写的、哪个 --phase 没切到。

### file_state：和 index 比，不和工作区比
叠加用的行号来自 index，所以「这个文件录制之后改过没有」要拿 run 的哈希和 index 的 `file_sha` 比（scan 用的是同一种哈希 `sha16`）。按下面的顺序定状态（runs.py:724 起），只返回不是 same 的文件：
1. **mismatch**：录制时安装包就和仓库不一致，最先判。
2. 不在 index 里的：工作区里有、或者只在安装包里的，算 **outside**（scan 排除的 examples、_version.py），不叠加也不算过期；工作区里也没有的，算 **gone**。
3. **unknown**：run 没存这个文件的哈希。
4. **changed**：和 index 的 `file_sha` 不同。

老 index 没有 `file_sha` 时，退回 `trace.stale_files` 和工作区比（runs.py:736）。

### remap：改过的文件按 qualname 挪行号（M6）
**为什么要挪。** 计数的键是「文件:首行号」（hook 的 `_key`，trace.py:160），`trace.to_package_graph` 拿 (文件, 行号) 去找符号。录制之后文件上方多了几行 import 或注释，下面的函数整体下移，老键要么落空（被算成没有自己符号的调用），要么落到新代码里恰好在那一行的另一个函数上。后一种更糟：数字看起来正常，其实是别的函数的。M6 之前只能在横幅上说「这些文件上的叠加可能偏」，看的人只好重录，而重录往往要几分钟 GPU。录制端从 M1 起就在键第一次出现时记下 `co_qualname`（trace.py:257；Python 3.10 没有这个属性，就不记，见「局限」），`derive` 把它存进 counts.json.gz 的 names（runs.py:371）。这是设计稿原则 5「录制端先行」：名字只有录制时拿得到，先存下来，读的一侧以后再写，M6 就是这个「以后」。

**`load_counts`**（runs.py:643）加了 `with_names`：为真时返回 (计数, names)；没有 names 的（迁移来的老 run 写的是空字典，runs.py:497）给空字典。默认仍只返回计数，老的返回形状不变；眼下树里只有 `load` 调它，传的是真。

**`remap`**（runs.py:652）拿 (计数, names, `file_state` 的结果, index)：
- **只挪 changed 和 mismatch、而且在 index 里的文件**（runs.py:666）。same 的行号本来就准；outside 不叠加；gone 在 index 里没有符号可查；unknown 没存哈希，不知道改没改。mismatch 要挪：录下的是安装包里的行号，按名字查到的是仓库里的行号，正好把两份代码对齐。「在 index 里」这个条件是后补的：`file_state` 先判 mismatch、再判在不在 index 里，scan 排除了的文件（examples 之类）只要录制时安装包和仓库不一致，状态也是 mismatch；这种文件在符号表里一个符号都没有，每个键都会对不上、白白抬高 unmatched，而它们本来就不叠加。一个要挪的文件都没有时原样返回、不建任何表，大多数加载走这条近路。没改过的文件不按名字查还有一个好处：名字层面的歧义（见「局限」里 property 那条）不会波及本来就对的叠加。
- **(文件, 限定名) → 现在的行号**（runs.py:672），只为要挪的文件建。用文件路径而不是模块名当键，包的 __init__.py 就不用把路径换算成模块名（fakesvc/__init__.py 的模块名是 fakesvc），设计稿 1.1 的决策表特意写了「__init__.py 里的函数也能对上」。有 dl 用 dl：装饰过的函数 co_firstlineno 指向第一个装饰器那一行，`trace.sym_locs` 也按 dl 建了索引（trace.py:1429），改写出来的键 `trace.to_package_graph` 才认得。挪到的键形状不变（仍是「文件:行号」），`trace.to_package_graph` 不用改就认得（设计稿 3.5 第 4 条、原则 6）；只有对不上的键要它多认一种行号，见下面第 4 条。
- **去掉 .<locals> 再查**（runs.py:686）：嵌套函数运行时的 qualname 是 outer.<locals>.inner；scan 的 walk 进函数体时前缀是「outer.」（scan.py:505），符号表里记成 outer.inner。去掉 .<locals> 正好一一对应。
- **类体也照这样挪**：类体帧（class 语句执行时跑一次的那一帧）的 co_qualname 就是类的限定名（嵌套类是 Pool.Options，函数里的类是 factory.<locals>.Local），符号表里有同名的类符号，装饰过的类同样用 dl，所以它和函数一样被挪到类现在的行上。挪对了才重要：`trace.to_package_graph` 是按「落在类符号的行上」认出类体、把它当定义（`class_frames`）而不算调用的，挪错了、或改成 -1，类体就会被当成调用算进文件和包。test_class_body_is_definition_not_call 在 lazy.py 顶上插两行、重新 scan，断言叠加结果和插之前一样、unmatched 为 0。
- **对不上的改成「文件:-1」，记进 unmatched**（runs.py:690、runs.py:693）：去掉 .<locals> 之后还带 < 的（<lambda>、<genexpr> 这些没有名字的代码对象）；names 里没有这个键的（迁移来的老 run、Python 3.10 录的 run）；名字在现在的代码里查不到的（改了名、删了）。
  - 为什么不留原键：最初的实现就是留原键，可文件改过之后，老行号可能正好是另一个函数现在的定义行（比如改名时在原处新插了一个函数）。`trace.to_package_graph` 会把次数算到那个函数头上，还可能和挪过来的键撞在一起相加：数字看着正常，其实是别人的，正是 M6 要消灭的那种错。-1 不是任何符号的行号，不会落到任何函数上。
  - 为什么不是 0：第 0 行在 `trace.to_package_graph` 里是模块顶层，算 import 触发的执行、不算「跑到了」，指向它的边也记成 import 而不是调用，这些调用就等于丢了。
  - `trace.to_package_graph` 怎么对待 -1：定义时的执行由模块级的 `defining` 判（trace.py:1435，「时间顺序」的 `seq` 也用同一个），只认第 0 行、没有符号的第 1 行和落在类符号上的行，-1 都不是；-1 也查不到符号，于是走「没有自己符号」那一支（anon，trace.py:1492），照样加到包上，也照样算进 hot 的 files；边上的被调方由 `label` 显示成「文件:<改过、对不上>」（trace.py:1501）。次数留在文件和包上，是因为调用确实发生在这个文件里，只是说不出是哪个函数；扣掉的话，文件和包的次数会凭空变少，只跑过这几个函数的包甚至会变成「没跑到」。
- **模块顶层不动，也不算 unmatched**（runs.py:684）。第 0 行本来就不对应符号。第 1 行而且没有名字的也不动：老格式把模块顶层记在第 1 行，迁移来的 run 又都没有 names，按上一条它们会全被改成 -1，`trace.to_package_graph` 就不再把它们当模块顶层，只被 import 过的包会被算成跑到了，import 触发的执行也变成了调用边。有名字的第 1 行（新 run 里真在第 1 行定义的函数）照常挪。
- **撞键相加**（runs.py:700）：两个老键改写成同一个新键时，次数相加。
- **func_edges 两端都改写**（runs.py:704），和 funcs 共用一个 memo：边的端点和 funcs 的键必须是同一套，否则 `trace.to_package_graph` 按边找被调符号时还拿老行号去查。调用方也可能是 case 自己的代码，键是「<外部代码>/文件名:行」（hook 只让它在栈上当调用方，不计数、不记名字）；它不在任何要挪的文件里，原样留着，`trace.to_package_graph` 按文件找不到它的包，这种边照旧不上图。
- 返回 (新的计数, 排好序的 unmatched 键)；`load` 只把个数放进 meta。

**和设计稿的差别**：设计稿 3.5 第 3 条写的是「带 <locals> 的、<lambda>、查不到的，都保留原行号」。实现差两处。一是嵌套函数也挪：scan 本来就把嵌套函数收成 outer.inner 这样的符号，去掉 .<locals> 就一一对应，没有理由放弃，M6 的状态说明里记了这条差别。二是对不上的不留原行号、改成 -1（理由见上），于是第 4 条「`to_package_graph` 不改」也不再成立，它要把 -1 当成没有符号的调用、在边上写成「改过、对不上」。设计稿「已知风险」说 3.10 和迁移来的 run「只能按行号映射」，实际是它们在改过的文件里的键一律只归到文件上。验收是 test_remap_moved_functions：包 __init__.py 里的函数、装饰过的函数、嵌套函数各下移几行后重新 scan，hot.symbols 里的次数和移动前相同；函数体里的 lambda 算进 unmatched。接着把 load_weight 改名，并在它原来那一行插进一个新函数 other_fn，再 scan：other_fn 在 hot.symbols 里没有次数（没被老键砸中），work.py 在 hot.files 里的次数没有变少（断言留了 1 的余量）。

### 删除和「还活着吗」
`remove`（runs.py:839）只认完整的 run id。case 名会解析到「最新一次录完的」，拿它删东西太容易删错；带 / 或以 . 开头的也不认，免得删到 .tmp-* 或 runs/ 外面。还在录的不删（runs.py:848）。「还在录」由 `live` 判断：状态是 recording，而且 `_alive(driver)` 为真。`_alive` 同时比对 pid 和启动时刻（`_proc_start`，读 /proc/<pid>/stat 的第 22 列），因为 pid 会被复用：driver 早死了、pid 被别的进程占了的 run，不能被当成「还在录」。

`remove_events`（runs.py:853）用同一套守卫（完整 id、不带 / 和开头的 .、不是还在录的），再多一道和 `merge_run` 一样的检查：parts/ 还在、`trace.leftovers` 发现还有进程属于这个 run 的，拒绝（runs.py:861）。driver 死了不等于没人写：setsid 出去的服务还会往 parts/ 写新的 ev-*.log，删完之后下一次 merge 又整理出半截事件。过了这几关，删掉整个 events/（原始日志和 span 一起），录制中断、还没 merge 的 run 连 parts/ 里散着的 ev-*.log 也删（runs.py:866），否则下一次 `runs merge` 会从 parts/ 把事件又整理出来（test_events_rm_unmerged 先 `trace.stop_leftovers` 再删、再 merge）。最后 run.json 的 `events` 置成 null（runs.py:868），计数和 parts.tar.gz 不动。

### 复刻命令：录的时候存原样的，老 run 才按参数拼（M8）
**录的时候记下什么。**
- `invocation` = `{argv, cwd}`：`main()` 在解析参数之前记下原样的 argv（前面是怎么叫起的 codestrata：装好的入口脚本取绝对路径，`python -m codestrata` 记成解释器 + -m）和当前目录（__main__.py:754），`cmd_trace` 交给 `new_run` 原样写进 run.json。注意它的 cwd 是敲命令时 shell 所在的目录，和 run.json 顶层的 `cwd`（命令的执行目录）不是一个东西：没给 `--cwd` 时前者是随便哪里、后者是仓库根目录。
- `env_inherited` = `inherited_env(os.environ, skip=run 的 env)`（runs.py:940）：
  - 白名单：前缀 CUDA_ / VLLM_ / PYTORCH_ / TORCH_ / NCCL_ / HF_ / TRANSFORMERS_ / TOKENIZERS_ / OMP_ / MKL_ / NVIDIA_ / TRITON_ / XLA_（runs.py:924），再加 PATH、PYTHONPATH、LD_LIBRARY_PATH、VIRTUAL_ENV、CONDA_PREFIX、CONDA_DEFAULT_ENV、PYTHONHASHSEED、CODESTRATA_EV_MAX 这几个整名（runs.py:926）。
  - 名字像密钥的一律不记（`_ENV_SECRET`，runs.py:930）：按 `_` 分段匹配 TOKEN(S)、KEY(S)、API_KEY / APIKEY（及复数）、SECRET(S)、PASS / PASSWD / PASSWORD / PASSPHRASE、CRED(S) / CREDENTIAL(S)、AUTH、COOKIE(S)、SESSION、PRIVATE，不分大小写。所以 HF_TOKEN、VLLM_API_KEY 不记，只是含着这几个字母的 TOKENIZERS_PARALLELISM、NCCL_IB_PKEY 照记（test_rerun_secrets_and_bytes 断言了 TOKENIZERS_PARALLELISM 在、VLLM_API_KEY 不在）。
  - 值里 URL 带的账号密码（`://user:pw@`）换成 `<已隐去>`（`_scrub`，runs.py:936）。
  - `--env` 写明的不重复记：skip 传的就是 run 的 env，里面还有 `cmd_trace` 在开了 --events 时从 shell 补进来的 CODESTRATA_EV_MAX（__main__.py:312）。

**`rerun_command`（runs.py:991）分两条路：**
- 有 `invocation.argv` 的（runs.py:1002）：`cd <当时的目录> && <原样的 argv>`（runs.py:1016；当时取不到当前目录的就不带 cd）。相对路径、codestrata 装在哪都和当时一样，`--cwd .` 这种相对的执行目录也因为先 cd 回去而指向原处；test_rerun_command_reproduces 和 test_trace_cwd 都在 / 下用 `bash -c` 照抄这条，再录出同一个 case 的 run（后者断言新 run 的 `cwd` 和原来的相同）。唯一的改动是补 --env：run 的 env 里有、命令行上没写的（实际就是上面说的 CODESTRATA_EV_MAX），补成 `--env=K=V` 插在 `--` 之前（runs.py:1009）。判断「命令行上写没写」时 `--env K=V` 和 `--env=K=V` 两种写法都认（runs.py:1004 起）。
- 没有的（M8 之前录的 run，runs.py:1017）：按参数拼一条 `codestrata trace`。仓库写成调用方传进来的 repo 解析成的绝对路径（runs.py:1018），`runs show .` 的 `.` 也写成绝对的，照抄时不依赖在哪敲。这里以前写的是 run.json 的 `cwd`（那时它恒等于仓库根目录）；有了 `--cwd` 之后它是命令的执行目录，拿来当仓库就会把 case 目录当仓库去录，所以改回 repo，`cwd` 和仓库不同时另写 `--cwd=<绝对路径>`（runs.py:1020）。M8 之前的 run 都是在仓库根目录跑的，真走这条路的不会带 --cwd；test_rerun_command_legacy 两种都断言了（传相对的 repo 也写成绝对路径、不带 --cwd；把 `cwd` 改成仓库下的 fakesvc/ 就带上 --cwd=）。录的时候开了事件就带 --events（runs.py:1024），stop_grace 等于默认的 90 秒时省略（runs.py:1026），--timeout 和 --stop-grace 的秒数走 `fmt_seconds`（runs.py:1023）：整数不带小数点（900 而不是 900.0），其余用 repr 原样写；以前用的 :g 只留 6 位有效数字，1234567 秒会写成 1.23457e+06，0.1234567 会变成 0.123457，照抄就和录的时候不一样了。再加 --env、--attach、`rec` 里有的 --roots（runs.py:1032）和 --phase（runs.py:1035）、--tag、--note。除了 --roots（nargs 的选项，写成 `--roots a b`，runs.py:1033），值一律写成 --x=值，以 - 开头的值不会被当成选项。`runs show` 在这种 run 下面注明是按存下的参数拼的。
- `with_env=True`：前面加 `env K=V …`，带上 `env_inherited`（runs.py:1000），放在 `cd … &&` 之后。docstring 的说法是「同一台机器上照抄就一样」。
- `redact=True`（给网页、导出）：原样的那条整条走 `_redact_argv`（runs.py:969、runs.py:1014），`--` 前后一视同仁，三种东西隐去：`--env K=V` / `--env=K=V` 里 K 像密钥的，值换成 `<已隐去>`；选项名像密钥的，`--api-key X` 隐去下一个参数、`--hf-token=X` 隐去 = 之后的部分；所有参数里 URL 的账号密码。「选项名像密钥」由 `_secret_flag`（runs.py:964）判：以 - 开头，去掉开头的 -、取 = 之前的部分、- 换成 _，再用环境变量那套 `_ENV_SECRET` 按段认，所以 --api-key、--hf-token 算，--tokenizer 不算。选项名像密钥、下一个参数却以 - 开头的，当它是不带值的开关，不把下一个参数当成它的值隐去（runs.py:975）：`--no-auth --port 80` 里的 `--port 80` 原样留着（test_rerun_secrets_and_bytes 断言了这一条），代价见「局限」。拼的那条先对 --env 逐个按名字判（runs.py:1029），最后拼出的 codestrata 部分和被 trace 的命令各自整条过 `_redact_argv`（runs.py:1043），和原样的那条同一套规则，所以老 run 的 case 命令里 `--api-key X` 的值在复刻命令里也隐去（test_rerun_command_legacy 断言了 case 命令里的 --api-key 值和 --env 里 HF_TOKEN 的值都看不到）。
- 引号一律走 `_q`（runs.py:952）：一般的用 shlex.quote；带着不是 UTF-8 的字节的（Python 里是孤立的代理字符，编码成 UTF-8 会抛错）写成 bash / zsh 的 `$'…'`，可打印的 ASCII 原样（反斜杠和单引号除外）、其余逐字节写成 `\xNN`，粘贴进 shell 还原出的是原来的字节（test_rerun_secrets_and_bytes 用 `caf\xe9` 验）。

## 局限
- 判断「还活着」全靠 /proc。没有 /proc 的系统上 `_proc_start` 返回 None，`_alive` 永远为假，`trace.leftovers` 也只会返回空：正在录的 run 在 `catalog` 里会显示「中断」，`remove` 和 `remove_events` 都拦不住。
- `_update`（tags / note / `remove_events`）没有加锁。如果有人在 `finalize` 读完 run.json、`derive` 写回之前改了 tags，改动会被覆盖。
- `remove` 不查 `trace.leftovers`（只有 `remove_events` 和 `merge_run` 查）。这对删整个 run 没有后果：hook 写分片前不建目录，parts/ 没了残留进程也写不进来。
- `_MIGRATED` 让一个进程只检查一次迁移：serve 开着的时候才冒出来的老 trace-*.json，要等重启 serve（或跑一次 `runs ls`）才迁。主菜单的项目卡片只在 runs/ 已经存在时才调 `catalog`（`has_runs`），所以只有老格式 trace-*.json、还没有 runs/ 的仓库，卡片上是 0 个 run，也不会触发迁移，要先跑一次 `runs ls` 或开一次 serve。
- `remap` 按名字查，同名的几个定义分不开。property 的 getter 和 setter 共用一个 qualname：scan 的符号表里它们是同一个符号，行号取最后定义的那个，前面几个的位置记在 `a` 里（scan.py:481）。没改过的文件里两个键分开记、都经 `trace.sym_locs` 对到这个符号；改过的文件里 `remap` 只按最后那个的行号挪（runs.py:672），两个键被合成一个，符号的次数不变，只是分不出 getter、setter 各几次。条件分支里定义两次的同名函数同理。设计稿「已知风险」列过 property 这一条。
- Python 3.10 及更早（走 setprofile 的那条路）没有 `co_qualname`，hook 就不记名字（trace.py:257），和设计稿 4.3「取不到就跳过」一致。以前退回记 `co_name`，方法和嵌套函数只剩裸名字，同一个文件里恰好有同名的顶层函数时会被挪到它身上，这是挪错而不是挪不动，所以宁可不记。代价是这种 run 在改过的文件里一个键都挪不动，全部只归到文件上、算进 unmatched；类体的键也一样被改成 -1，不再被认成定义，次数算到文件和包上。
- `unmatched` 数的是键，不是调用次数：一个 lambda 调了一万次也只算一处。迁移来的老 run 没有 names，改过的文件里除了第 0、1 行，每个键都算一处、都只归到文件上。定义在第 1 行的函数和老格式的模块顶层分不开，只好留在原键不挪：落到现在第 1 行的符号上，那里没有符号就算成模块顶层。
- 同一个键名 `unmapped` 两处口径不同：`trace.to_package_graph` 返回的 hot 里仍是模块顶层 + 类体 + anon（trace.py:1545），meta 里的只有 anon（runs.py:786）。眼下前端只读 meta 的那个，hot 里的没人读，但两个名字一样、意思不一样，以后读 hot 的人容易拿错。
- 按参数拼的复刻命令（老 run）会带上 `rec` 里的 roots 和 phase_at，但这两项和 `invocation` 是同一次（M8）才开始记的：真正走这条路的老 run 两样都没有，录制时手动指定过顶层包的，仍要自己补 --roots。反过来，`rec` 的 roots 只记命令行上给的 `--roots`（`main()` 先用 `scan.clean_roots` 规整过，__main__.py:761）：没给时录制用的是当时 index 里的 roots（`cmd_trace` 的默认），复刻时用的是复刻那一刻 index 里的，中间重新 scan 选了别的目录，两次的安装包映射就不一样。
- `env_inherited` 只是白名单：case 脚本自己读的其它环境变量不记，名字像密钥的也不记，复刻时要自己在 shell 里备好。`rerun_env` 前面的 `env` 带着录制那台机器的 PATH、CONDA_PREFIX 这些，换一台机器照抄未必对。
- 隐去只按名字和 URL 的形状认：`--env` 里名字像密钥的值、名字像密钥的选项的值、`://user:pw@`。`load` 给的 `cmd`、各进程的 argv、`rerun` / `rerun_env`（老 run 按参数拼的那条也一样）都照这套隐去（`_meta_brief` 带的也就是隐去过的）；认不出的照样看得见：位置参数里的密钥、名字不像密钥的选项的值（比如 `--header "Authorization: …"`）、名字不像密钥的 --env 里的值，进程用 setproctitle 改过的标题（meta 里 `procs` 每组的 `title`），还有 meta 的 `script`（case 脚本原文，不隐去）。按名字认也不知道选项带不带值，只能看下一个参数长什么样（runs.py:975）：以 - 开头就当这个选项是开关、不隐去，所以本身以 - 开头的密钥值（`--api-key -abc`）会原样露出来；不以 - 开头就当成值隐去，所以名字像密钥的开关后面紧跟位置参数时（`--no-auth config.yaml`），那个位置参数会被多隐去。存下的数据不受影响，只是网页和导出里看到的（包括复制按钮复制出去的复刻命令）那个参数成了 `<已隐去>`。前端只在 `rerun_redacted` 为真时才写那句「命令里像密钥的值（--env 里的、--api-key 这类选项的）和 URL 里的账号密码已隐去……下面的 case 命令和进程表也一样。完整的命令用 `codestrata runs <repo> show <id>` 看」（codestrata/web/app.js:222）：case 命令本来就包含在复刻命令里，它有东西被隐去时复刻命令也变了，提示会出现；只在进程表里才有的（case 脚本自己起的进程的命令行）被隐去时，复刻命令不一定变，就没有提示。`--env` 写明的密钥和被 trace 的命令在 run.json（`env`、`cmd`、`invocation.argv`）和 detail.json（procs）里一直是原样的，`runs show` 打的也不隐去。
- driver 死在收尾之前的 run，`runs merge` 从标记补回的阶段日志不如收尾时轮询记下的全。sh 标记是 driver 轮询看到时才建的，而且每个名字只建一次（O_EXCL），所以 case 脚本切回已经进过的阶段（A → B → A）时，第二次的 A 补不回来；`derive` 本来就只取每个名字第一次的时刻，阶段顺序和 `phases` 的 t_us 不受影响，少的只是 phase_log（前端阶段表）里那几条。名字不合 `PHASE_NAME_RE` 的阶段 driver 不建标记，driver 死了之后 case 脚本才切的阶段没人轮询、也没有标记，这两种在这种 run 里没有时刻，排到有时刻的阶段后面。
- 迁移时两个老 case 名清洗后相同、mtime 又落在同一秒的，后一个的 id 撞上前一个。`_cleanup_legacy` 看到 `migrated_from` 不同就什么都不做，所以后一个会一直留在原处不迁。不会丢数据，但也不会报错。
- `_write` 的临时文件名只带 pid，不带线程号。同一个进程里两个线程同时写同一个文件会撞。眼下没有多线程写 run 的调用方：serve 和主菜单（app）都是多线程的，但对 runs 只读（`catalog` 触发的迁移有文件锁，而且每个进程只做一次）；主菜单起的录制是子进程，各写各的 run 目录。

## 不确定
- 设计稿「M8」一节复刻命令那条写的是名字含 TOKEN/KEY/SECRET/PASS/CRED/AUTH 的环境变量不记（「评审后补上的」里改成了按 `_` 分段匹配）、meta 带 `rerun / rerun_exact / rerun_env / env_inherited / phase_at / phase_log`；代码的词表更长（还有 COOKIE、SESSION、PRIVATE，PASS 之外另列 PASSWD / PASSWORD / PASSPHRASE，见上），meta 还多一个 `rerun_redacted`。以代码为准。
- 设计稿 3.2 把 `events` 写成 `{n_lines, truncated: [pid…], bytes}`，代码还多了 `n_spans`、`n_calls`、`n_procs`，失败时是 `error` + `bytes`；以代码为准。
- `remap` 的 mismatch 分支没有测试：test_remap_moved_functions 只覆盖 changed（直接改仓库里的文件），scan 排除了的 mismatch 文件不进 unmatched 这一条也没有测试。按名字把安装包的行号对到仓库上，在 vllm-omni 这种装成包跑的仓库上还没验过。
- 事件的实际开销和大小（设计稿 7.3 估原始日志 gzip 后 4–6 MB）还没在 GPU 上实测，M3 标的是「CPU 部分已完成」；事件要不要默认打开要等那次实测。
- 迁移来的 run 的 `cwd` 取老 trace 里记的、没有就是仓库（runs.py:533）。比较前两边都 resolve 过，软链不碍事；可仓库搬过家的话，老 trace 记的是旧路径，按参数拼的复刻命令会多出一个指向旧路径的 --cwd；没见到实例，也没有测试。
