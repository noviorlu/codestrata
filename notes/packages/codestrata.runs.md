---
written_by: claude-opus-5-5
target: codestrata.runs
kind: package
code_sha: f7730e44a370f18e
status: draft
refs: payload.py:44@792c7b2a,runs.py:1@acd28cbf,runs.py:153@2caa988e,runs.py:409@73b79d30,runs.py:318@0ac29959,runs.py:328@dcfcecf7,runs.py:345@3be37370,runs.py:774@74b5e2b2,runs.py:565@5aad2956,runs.py:628@2e266090,runs.py:434@65794504,runs.py:420@f98d9cbc,runs.py:425@1c2edb45,runs.py:240@fddbfbb9,runs.py:247@45f781f8,runs.py:186@570c0656,runs.py:357@5a9894f3,runs.py:381@84b2fc29,runs.py:377@33e517e7,runs.py:293@060b529e,runs.py:302@e311843b,runs.py:289@287fefa9,runs.py:339@903daee6,runs.py:336@b54abd09,runs.py:390@d5bb93ee,runs.py:392@8e8d8c1a,runs.py:780@4c708cb1,runs.py:784@09ab28d2,runs.py:794@4b07558f,runs.py:801@bcf32585,runs.py:807@b94aaa53,runs.py:809@8224f7cb,runs.py:812@96001191,runs.py:813@e6d02764,runs.py:814@9fc99a86,runs.py:447@40c03a7d,runs.py:453@70cbbd06,runs.py:520@caefdf40,runs.py:529@a3eee4b4,runs.py:539@149a0c4a,runs.py:461@304c7ef9,runs.py:463@1e0f250e,runs.py:478@6e207d1a,runs.py:489@187b238d,runs.py:586@5028c052,runs.py:595@30c67c61,runs.py:581@eee7399e,runs.py:673@2da1635f,runs.py:685@16613a5f,runs.py:702@896ff455,runs.py:706@bbf3acab,runs.py:643@c89680b5,runs.py:655@64edc9ec,runs.py:742@c22fa459,runs.py:750@3de1c2b7,runs.py:756@21ab656f,runs.py:764@a6506b96,runs.py:769@82399e64,runs.py:771@b4e21cbc,runs.py:821@e701ab9a,runs.py:829@af308051,runs.py:831@0db851a4
---

## 是什么
run 的存储层。一次 `trace` 录下的全部东西放进 .codestrata/runs/<id>/ 这一个目录，id = 录制时刻 + case 名（比如 20260927-153412-minicpmo-duplex）。静态分析（index / symbols / xref）只有一份，随时能 scan 重建；run 重建不了，一次录制往往要花几分钟 GPU（起服务、加载模型、跑一段对话）。所以这个模块的原则是**录一次，永久复用**：同名 case 重录不会覆盖旧的，今天录 MiniCPM、明天录 Qwen，两份都留着。

它管四件事：
- **录制的两头**：`new_run` 建目录，`finalize` 收尾（`capture` → `_pack_all` → `_build_events` → `derive`）。中间真正起命令、注入 hook、合并分片的是 `trace.run` / `trace.merge`；把时序事件日志整理成 span 的是 `events.build`。
- **读**：`catalog` 列出所有 run，`resolve` 解析 REF，`load` 把一个 run 映射到当前 index 上。`payload.load_hot` 只是它外面的一层薄包装（payload.py:44）。M4 起 serve 不再启动时加载一次，而是每个请求现调：run 列表每次现调 `catalog`，叠加按请求里的 run= 调 `resolve` / `load`，结果缓存在 `serve.Handler._hot` 里。
- **管理**：`set_tags` / `set_note` / `remove` / `remove_events` / `merge_run` / `rerun_command`，分别对应 `codestrata runs <repo> …` 的各个动词（`remove_events` 是 rm --events-only）。
- **兼容**：`migrate` 把老格式的 trace-<case>.json 搬进 runs/。

一个 run 目录的布局：
```
runs/                    可以是软链（vllm-omni 的指到 /mnt/data）；scan 不碰它
  .migrate.lock  .tmp-<id>/     迁移用的锁和半成品
  <id>/
    run.json        小：列表页只读它（状态、problems、命令、env、git、driver、阶段、摘要、events 摘要、tags/note）
    detail.json     原始：录制时才拿得到的（执行时的哈希、安装包映射、Python/包版本、GPU、git 改动、存下的文件）
    parts.tar.gz    原始：各进程写出的计数分片，原样打包（不含 ev-*.log）
    files/          原始：case 脚本、命令行里提到的配置、--attach 的文件，存的是录制时的样子
    legacy/         原始：只有迁移来的 run 才有，是老 json 逐字节压成的 gz
    counts.json.gz  派生：每个阶段的 funcs / func_edges，外加 qualname
    events/raw.tar.gz  原始：时序事件日志 ev-<pid>-<t0ns>.log，只有 trace --events 录的 run 才有
    events/spans/   派生：配好对的 span（keys.json、index.json、p<pid>-NNN.jsonl.gz）
    parts/          只在录制期间存在
```

## 为什么这样切
run 是唯一重建不了的数据，所以所有写 run、删 run 的代码都收在这一个模块里。「除了 `remove` 和 `remove_events`，没有代码会删 run 里的东西」这句话只要审这一个文件就能确认。`trace` 只管录（hook、分片、合并）和折算（`trace.to_package_graph`），对 run 目录只知道 parts/ 在哪；`events` 只管把日志变成 span，写到这里给它的目录；`payload`、`serve`、`__main__` 只通过这里读 run。这样 CLI、serve、graph、tasks/pack 的 `--hot` 和网页里的 run 下拉都走同一个 `resolve`，一个 REF 在哪儿都解析成同一个 run。

**原始数据和派生数据分开。** 合并逻辑还不成熟、以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，可以用 `runs merge` 重算。时序事件照同一个办法：原始日志（events/raw.tar.gz）永久保留，span（events/spans/）是派生的，finalize 和 `runs merge` 都会重新整理。反过来，录制时才拿得到的东西（执行时的文件哈希、case 脚本和配置的副本、git 改动、GPU）只写一次，重算时不能拿「现在的样子」去盖。所以收尾拆成两步：`capture` 只跑一次，`derive` 可以反复跑。

**事件日志不进 parts.tar.gz，单独一个包**（设计稿 7.1「实现时的调整（M3）」）。模块 docstring 说的是「`runs rm --events-only` 只删这一块」，再加上结构能推出完整的理由：`_pack` 从不拿成员少的包换成员多的包，如果日志混在 parts.tar.gz 里，删事件就只能重写计数的原始包、还是个成员变少的替换；分开之后，删事件就是删掉 events/ 这一个目录，计数的原始数据一个字节都不碰。

**run 只存原始键（文件:首行号）和执行时的文件哈希。** 加载时才现映射到当前 index 上。代码改了以后老 run 照样能用；哪些文件在录制之后改过，由 `file_state` 逐个标出来，不会让整个 run 作废。

**run.json 和 detail.json 分开**：`runs ls` 列 100 个 run 时只读 100 个几 KB 的文件，不用把几十 MB 的 procs 和哈希都读进来。M4 之后这一条更要紧：serve 的 /api/runs 每次打开下拉都现调 `catalog`，不做文件监视，新录的 run 自然出现；要读 detail.json 的「录制后改过几个文件」由 serve 按 detail 的 mtime 另外缓存。事件也只在 run.json 里留一份几个数的摘要，span 本身留在 events/spans/。

**counts.json.gz 只由 `derive` 写。** serve 缓存 `load` 的结果时，拿 counts.json.gz 的 mtime 当缓存键的一部分：计数只在 finalize / `runs merge` 时变，而 `_write` 是先写临时文件再 `os.replace`，每次重写 mtime 都会变；改 tag、备注走 `_update`，只动 run.json，不让缓存失效。

## 读法
1. 模块 docstring（runs.py:1）：录一次永久复用、原始和派生、谁能删 run、为什么只存原始键、events/ 的两半各算哪类数据。设计的来龙去脉在 `docs/design/runs.md` 的第 1、3、4 节，尤其是 4.3 末尾「实现时补上的几条」；时序事件看 7.1–7.3，含「实现时的调整（M3）」和「M3 评审后补上的」两串；serve 怎么用这个模块看第 5 节和 M4 的状态说明。
2. `new_run`（runs.py:153）→ `finalize`（runs.py:409）。按录制的时间顺序读，`finalize` 里再按 `capture` → `_pack_all`（runs.py:318）→ `_build_events`（runs.py:328）→ `derive`（runs.py:345）的顺序展开。
3. `merge_run`（runs.py:774）：`finalize` 的「事后重做」版本，读它能看清哪些东西会被重算、哪些不会。
4. `catalog` → `resolve` → `load`（runs.py:565 起），也就是读的那一侧，再加上 `file_state`（runs.py:628）。
5. `remove`、`remove_events`、`live` / `_alive`、`rerun_command`：都是小函数，规则写在 docstring 里。
6. `migrate` / `_migrate_locked` / `_cleanup_legacy`（runs.py:434 起）放最后读：只为兼容老数据，逻辑最绕。
7. span 的格式和配对规则不在这里，看 `codestrata/events.py` 的 docstring；场景和断言在 `tests/test_runs.py` 的 test_events_* 和 `tests/trace_cases/fake_repo/fakesvc/truth.py`。

## 关键算法
### 收尾：capture 只写一次，derive 可以重做
`finalize` 先把 stop、returncode、时长、阶段日志写进 run.json，然后只在 detail.json 还不存在时才调 `capture`（runs.py:420），接着把 parts/ 分两个包打好（runs.py:425），再整理事件，最后调 `derive`。

`capture` 收集的东西：
- **文件哈希**：优先用 hook 在进程第一次跑到这个文件时算的那份，也就是执行的那份（runs.py:240）；老分片没有这个哈希的，退回收尾时磁盘上的，并记进 `sha_late`。
- **录制中被改过的文件**：hook 的哈希和收尾时磁盘上的不同，记进 `changed_during`。
- **安装包映射**：安装包和仓库不一致的记进 `mapped_mismatch`；仓库里根本没有的（构建时生成的 _version.py）另记 `mapped_only_installed`，不算不一致（runs.py:247）。
- **环境**：Python 和包版本（`_dists` 只看 dist-info 目录名，不 import 任何东西）、`_gpu`、git 改动。
- **文件副本**（`_collect_files`，runs.py:186）：case 脚本；任何进程的 argv 里出现的、200 KB 以内的 .sh/.py/.yaml/.json/.toml（vllm-omni 的 --deploy-config 指向的 yaml 就是这么存下来的）；`--attach` 点名的文件。被 source 的 common.sh 不会出现在命令行里，只能靠 `--attach`，所以点名的文件不受大小和个数限制。副本存成 files/NN-<文件名>，同名的不会互相覆盖。

`derive` 写 counts.json.gz，重算 detail 里唯一的派生字段 `procs`，再定状态：
- **failed**：一个函数都没录到。
- **ok**：没有任何 problem、退出码 0、`stop == "exit"`。
- **partial**：其余情况，原因写进 `problems`：超时、被中断、driver 中途没了、非零退出码、有进程被强杀、有残留进程、有分片读不出来、有文件在录制中被改过。

「被强杀」的判据是：进程最后一次落盘的原因是定时落盘（periodic）或切阶段落盘（phase），说明它没走到正常退出（runs.py:357）。打包失败时状态退回 recording，并提示用 `runs merge` 重来（runs.py:381）。阶段顺序按 driver 记下的阶段日志（同名阶段取第一次出现的时刻），日志里没有的阶段排在后面。

**时序事件不进 status**（runs.py:377）：行数到了上限（`truncated`）或整理失败（`error`）都不加 problem。计数是完整的，只有时序缺了一截；要是因此降成 partial，`resolve` 拿 case 名解析时就会跳过这次、落到更早的一次 ok 上。缺了什么由 events 摘要自己说，`runs show` 会打出来。test_events_cap 用 CODESTRATA_EV_MAX=1 录，断言 run 仍是 ok。

### 打包：分两个包，不拿少的盖多的
`_pack`（runs.py:293）只管「把这些成员打成这个包」：先写临时包，重新打开核对成员数，再 `os.replace`；已有的包成员比这次多，就直接放弃（runs.py:302）。`_pack_all` 按 `_is_event_log`（runs.py:289，文件名 ev-*.log）把 parts/ 里的文件分成两堆：计数分片进 parts.tar.gz，事件日志进 events/raw.tar.gz；没有事件日志就不建 events/。两个包有一个没打成就算失败，parts/ 整个留着。收尾时如果包已经替换好、只是 parts/ 没删干净，不算失败。parts/ 里残留的那几个文件，下次 `runs merge` 时会和包合起来。

### 整理事件：原始日志先落包，整理失败不耽误计数
`_build_events` 在打包之后调：原始日志先进了 events/raw.tar.gz，之后整理出任何问题，原始数据都已经安全。它把 src 里的 ev-*.log 和 run.json 的 `clock.mono0_ns` 交给 `events.build`，span 写进 events/spans/，返回给 run.json 的摘要：
- 成功时是 `n_lines`、`n_spans`、`n_calls`（Σrep，和跨文件的 func_edges 之和相等，两个 test_events_* 都断言了这一条）、`truncated`（到了行数上限的 pid 列表，空列表为假）、`n_procs`、`bytes`。
- `n_procs` 数的是不同的 pid，不是日志文件数：一个 pid exec 前后各有一份日志（进程映像），`events.build` 的 procs 里也各占一行，这里按 pid 去重，`runs show` 的「N 个进程」才和实际进程数对得上。
- 抛任何异常都接住（runs.py:339），摘要变成 `error`（截到 300 字）+ `bytes`。span 是派生数据，`runs merge` 能重来，所以不让它把整次收尾拖垮。
- `bytes` 一律是 events/raw.tar.gz 这个压缩包的大小（runs.py:336），不是日志的文本大小，也不含 spans。test_events_fake_service 断言 merge 前后这个数不变、且等于包的实际大小。

`derive` 拿到摘要才覆盖 run.json 的 `events`（runs.py:390），然后 `setdefault` 成 null（runs.py:392）。所以经过 `derive` 的 run.json 一定有 `events` 这个键：没加 --events 录的是 null，被 rm --events-only 过的也是 null，而且之后再 merge 不会把它变回来（事件日志已经删了，`_build_events` 返回 None）。读的一方（`runs show`、serve 的 /api/runs）一律用 get，迁移来的老 run 没经过 `derive`、没有这个键也不出错。

### merge_run：从并集重算
`merge_run` 先按 REF 解析到 run，再从磁盘重读 run.json（runs.py:780）：`catalog` 给的那份字典带着只用来显示的「中断」`status_shown`，写回去会让 merge 成 partial 之后仍显示「中断」（`derive` 写回前也会去掉这个键）。然后拒绝三种情况：录制还活着；`trace.leftovers` 发现还有进程属于这个 run、可能还在往 parts/ 里写（runs.py:784）；迁移来的老 run 没有原始分片。

之后把 parts.tar.gz 和 events/raw.tar.gz 都解到 .merge-<pid>/（runs.py:794），再把散着的 parts/ 盖上去（同名的是同一份或更新的，runs.py:801）。两个包的文件名不重叠，`trace.merge` 只读 part-*.json，混在一起的事件日志不影响计数。
- driver 死在收尾之前的 run，`stop` 补成 driver-lost（runs.py:807）。
- detail.json 还不存在的，现在补一次 `capture`，并标成 late（runs.py:809）。这时 files/ 和 git 改动是现在的样子，文件哈希仍是 hook 在执行时记下的。
- 只有 parts/ 还在时才重新打包（runs.py:812）。并集的成员数不会少于旧包，所以不会丢分片。
- span 每次都重新整理（runs.py:813），用的是原始包和散着的 ev-*.log 的并集；test_events_fake_service 断言 merge 前后 span 一模一样。parts/ 要等打包成功、事件也整理完才删（runs.py:814）。
- 已有的 detail.json 和 files/ 一律不重写，`tests/test_runs.py` 里有专门的回归测试盯着这一条。

### 迁移老 trace：加锁，先拷、核对，再删
老版本每个 case 只有一份 trace-<case>.json，外加一个 parts-<case>/。`catalog` 在每个进程里第一次碰到某个仓库时（`_MIGRATED`）顺带触发迁移；serve 每次请求都调 `catalog`，靠这个集合才不会每次都去 glob 老文件。设计稿 3.7 原本打算用 rename 认领，实际实现改成了这样：
- **用文件锁串行**（runs.py:447）：同时起的几个 serve / runs ls 排队等，后来的看到 run 已经在了就跳过。锁随进程释放，所以持锁时还看得到的 .tmp-*，一定是上次迁到一半死掉留下的，删掉重来即可（runs.py:453）。
- **只拷不挪**（runs.py:520）：runs/ 常常是指到另一块盘的软链，rename 跨不了文件系统。老文件逐字节 gzip 进 legacy/，parts-<case>/ 打成 parts.tar.gz。整个 .tmp-<id>/ 建好之后 `os.replace` 落位（runs.py:529），最后由 `_cleanup_legacy`（runs.py:539）核对：legacy 里那份解压后和老文件逐字节相同、包的成员名和 parts-<case>/ 一致，两样都对上才删老文件。任何一步不对就保留老数据。
- **id 是确定的**（runs.py:461）：老文件的 mtime + case 名，重复迁移、并发迁移算出来的都一样。`<id>` 已经存在（上次落位之后、删老文件之前死掉了）的，只补做收尾（runs.py:463）。老版本不限制 case 名（中文、+ 都有），所以目录名用清洗过的字符，run.json 里的 `case` 仍是原名，`--hot 原名` 照样找得到。
- **核对计数**（runs.py:478）：写回去再读出来，各阶段之和要等于老文件的 `funcs` / `func_edges`，每个阶段要逐键相等；对不上就保留老文件，打印原因。
- 老进程记录没有 ppid、argv 只存了前 6 个的，标 `argv_cut`（runs.py:489），界面上照旧提示「被截断」。

### 引用一个 run：REF
`resolve`（runs.py:586）接受 `完整 id | case`，后面可以跟 `@阶段`。先当完整 id 查，查不到再当 case 名：取这个 case 最新一次 ok 的；一次 ok 都没有，就取最新的 partial，再不行取最新的任意一个，并提示用的不是完整录完的（runs.py:595）。这样重录中途失败时，case 名不会被失败的那次抢走。不支持 id 前缀，因为前缀和日期会撞。`catalog` 按目录名倒序，id 以时刻开头，所以倒序就是新的在前。录制进程已经死了的 recording run，另加一个 `status_shown`，值为「中断」（runs.py:581），提示可以 merge；网页下拉里显示的状态也优先取它。

`resolve` 和 `load` 找不到东西时抛的是带中文说明的 `SystemExit`，这是给 CLI 直接打印的；serve 在 `serve.Handler._hot` 里把它接住，转成 404 的 JSON。

### 加载：映射到当前 index，老的 meta 键一个不少
`load`（runs.py:673）读 counts.json.gz（某个阶段的，或者用 `_sum` 把各阶段相加，和老 trace 的 `funcs` 同义），交给 `trace.to_package_graph` 现算 hot，并在 hot 里写明来自哪个 run（runs.py:685），`notes.prompt_pack` 靠这个说明数字的出处。`load` 自己不缓存，缓存在 serve 那边。meta 保留老 payload 的全部键，前端（`web/app.js`）认的就是它们：
- `phases` 只有一个阶段时给空字典（runs.py:702），和老 trace 一样，前端据此判断分没分阶段。
- `stale_files` = changed + gone（runs.py:706）。mismatch 另有「安装包和仓库不一致」那句话，所以不算在这里。设计稿 3.5 写的是 changed + mismatch，以代码为准。
- `script` 优先读 files/ 里存下的那份（saved 为真）；老 run 没存脚本的，读现在的文件并标明不是录制时的内容。

在老键之外，meta 再加上 run 的信息：`run_id`、`status`、`problems`、`git`、`tags`、`note`、`created`、`migrated_from`，以及 `file_state`。设计稿第 5 节还列了 events 和 unmatched 两个键，代码里都还没有：`load` 不读 events/，「这个 run 有没有时序」目前只由 serve 的 /api/runs 从 run.json 的 events 摘要判断（整理失败的算没有）。

### file_state：和 index 比，不和工作区比
叠加用的行号来自 index，所以「这个文件录制之后改过没有」要拿 run 的哈希和 index 的 `file_sha` 比（scan 用的是同一种哈希 `sha16`）。按下面的顺序定状态（runs.py:643 起），只返回不是 same 的文件：
1. **mismatch**：录制时安装包就和仓库不一致，最先判。
2. 不在 index 里的：工作区里有、或者只在安装包里的，算 **outside**（scan 排除的 examples、_version.py），不叠加也不算过期；工作区里也没有的，算 **gone**。
3. **unknown**：run 没存这个文件的哈希。
4. **changed**：和 index 的 `file_sha` 不同。

老 index 没有 `file_sha` 时，退回 `trace.stale_files` 和工作区比（runs.py:655）。

### 删除和「还活着吗」
`remove`（runs.py:742）只认完整的 run id。case 名会解析到「最新一次录完的」，拿它删东西太容易删错；带 / 或以 . 开头的也不认，免得删到 .tmp-* 或 runs/ 外面。还在录的不删（runs.py:750）。「还在录」由 `live` 判断：状态是 recording，而且 `_alive(driver)` 为真。`_alive` 同时比对 pid 和启动时刻（`_proc_start`，读 /proc/<pid>/stat 的第 22 列），因为 pid 会被复用：driver 早死了、pid 被别的进程占了的 run，不能被当成「还在录」。

`remove_events`（runs.py:756）用同一套守卫（完整 id、不带 / 和开头的 .、不是还在录的），再多一道和 `merge_run` 一样的检查：parts/ 还在、`trace.leftovers` 发现还有进程属于这个 run 的，拒绝（runs.py:764）。driver 死了不等于没人写：setsid 出去的服务还会往 parts/ 写新的 ev-*.log，删完之后下一次 merge 又整理出半截事件。过了这几关，删掉整个 events/（原始日志和 span 一起），录制中断、还没 merge 的 run 连 parts/ 里散着的 ev-*.log 也删（runs.py:769），否则下一次 `runs merge` 会从 parts/ 把事件又整理出来（test_events_rm_unmerged 先 `trace.stop_leftovers` 再删、再 merge）。最后 run.json 的 `events` 置成 null（runs.py:771），计数和 parts.tar.gz 不动。

### 重录命令
`rerun_command`（runs.py:821）从 run 里存的命令、`--env`、tags、note，以及录制参数（timeout、events、stop_grace、attach）拼出一条能直接复制的 `codestrata trace`。录的时候开了事件（`rec` 里 events 为真，由 `cmd_trace` 写入），重录命令就带上 --events（runs.py:829）。值一律写成 --x=值，以 - 开头的值不会被当成选项；stop_grace 等于默认的 90 秒时省略（runs.py:831）。

## 局限
- 判断「还活着」全靠 /proc。没有 /proc 的系统上 `_proc_start` 返回 None，`_alive` 永远为假，`trace.leftovers` 也只会返回空：正在录的 run 在 `catalog` 里会显示「中断」，`remove` 和 `remove_events` 都拦不住。
- `_update`（tags / note / `remove_events`）没有加锁。如果有人在 `finalize` 读完 run.json、`derive` 写回之前改了 tags，改动会被覆盖。
- `remove` 不查 `trace.leftovers`（只有 `remove_events` 和 `merge_run` 查）。这对删整个 run 没有后果：hook 写分片前不建目录，parts/ 没了残留进程也写不进来。
- `_MIGRATED` 让一个进程只检查一次迁移：serve 开着的时候才冒出来的老 trace-*.json，要等重启 serve（或跑一次 `runs ls`）才迁。
- `rerun_command` 不带 `--roots`：录制时手动指定过顶层包的，重录命令里要自己补上。
- 迁移时两个老 case 名清洗后相同、mtime 又落在同一秒的，后一个的 id 撞上前一个。`_cleanup_legacy` 看到 `migrated_from` 不同就什么都不做，所以后一个会一直留在原处不迁。不会丢数据，但也不会报错。
- `_write` 的临时文件名只带 pid，不带线程号。同一个进程里两个线程同时写同一个文件会撞。眼下没有多线程写 run 的调用方：serve 是多线程的，但对 runs 只读（`catalog` 触发的迁移有文件锁，而且每个进程只做一次）。

## 不确定
- 设计稿 3.2 把 `events` 写成 `{n_lines, truncated: [pid…], bytes}`，代码还多了 `n_spans`、`n_calls`、`n_procs`，失败时是 `error` + `bytes`；以代码为准。
- 事件的实际开销和大小（设计稿 7.3 估原始日志 gzip 后 4–6 MB）还没在 GPU 上实测，M3 标的是「CPU 部分已完成」；事件要不要默认打开要等那次实测。
