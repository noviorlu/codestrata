---
written_by: claude-opus-5-5
target: codestrata.runs
kind: package
code_sha: eabc8ed696e30ef7
status: draft
refs: payload.py:44@792c7b2a,runs.py:1@acd28cbf,runs.py:150@2caa988e,runs.py:369@73b79d30,runs.py:715@74b5e2b2,runs.py:524@5aad2956,runs.py:587@2e266090,runs.py:393@65794504,runs.py:379@80246357,runs.py:236@e7ecb7d8,runs.py:244@45f781f8,runs.py:183@570c0656,runs.py:311@f441ebc6,runs.py:322@5a9894f3,runs.py:345@6e691ece,runs.py:286@cc3e1f11,runs.py:295@e311843b,runs.py:726@6f79678c,runs.py:741@bcf32585,runs.py:747@b94aaa53,runs.py:749@8224f7cb,runs.py:406@40c03a7d,runs.py:411@6a330cc0,runs.py:479@caefdf40,runs.py:488@a3eee4b4,runs.py:498@149a0c4a,runs.py:419@1212de71,runs.py:422@1e0f250e,runs.py:436@88b60da3,runs.py:448@187b238d,runs.py:545@5028c052,runs.py:554@30c67c61,runs.py:540@eee7399e,runs.py:632@2da1635f,runs.py:644@16613a5f,runs.py:661@896ff455,runs.py:665@bbf3acab,runs.py:603@a27bb05b,runs.py:614@64edc9ec,runs.py:701@c22fa459,runs.py:708@df154b6a,runs.py:760@e701ab9a,runs.py:768@0db851a4
---

## 是什么
run 的存储层。一次 `trace` 录下的全部东西放进 .codestrata/runs/<id>/ 这一个目录，id = 录制时刻 + case 名（比如 20260927-153412-minicpmo-duplex）。静态分析（index / symbols / xref）只有一份，随时能 scan 重建；run 重建不了，一次录制往往要花几分钟 GPU（起服务、加载模型、跑一段对话）。所以这个模块的原则是**录一次，永久复用**：同名 case 重录不会覆盖旧的，今天录 MiniCPM、明天录 Qwen，两份都留着。

它管四件事：
- **录制的两头**：`new_run` 建目录，`finalize` 收尾（`capture` + `_pack` + `derive`）。中间真正起命令、注入 hook、合并分片的是 `trace.run` / `trace.merge`。
- **读**：`catalog` 列出所有 run，`resolve` 解析 REF，`load` 把一个 run 映射到当前 index 上。`payload.load_hot` 现在只是它外面的一层薄包装（payload.py:44）。
- **管理**：`set_tags` / `set_note` / `remove` / `merge_run` / `rerun_command`，分别对应 `codestrata runs <repo> …` 的各个动词。
- **兼容**：`migrate` 把老格式的 trace-<case>.json 搬进 runs/。

一个 run 目录的布局：
```
runs/                    可以是软链（vllm-omni 的指到 /mnt/data）；scan 不碰它
  .migrate.lock  .tmp-<id>/     迁移用的锁和半成品
  <id>/
    run.json        小：列表页只读它（状态、problems、命令、env、git、driver、阶段、摘要、tags/note）
    detail.json     原始：录制时才拿得到的（执行时的哈希、安装包映射、Python/包版本、GPU、git 改动、存下的文件）
    parts.tar.gz    原始：各进程写出的分片，原样打包
    files/          原始：case 脚本、命令行里提到的配置、--attach 的文件，存的是录制时的样子
    legacy/         原始：只有迁移来的 run 才有，是老 json 逐字节压成的 gz
    counts.json.gz  派生：每个阶段的 funcs / func_edges，外加 qualname
    parts/          只在录制期间存在
```

## 为什么这样切
run 是唯一重建不了的数据，所以所有写 run、删 run 的代码都收在这一个模块里。「除了 `remove`，没有代码会删 run」这句话只要审这一个文件就能确认。`trace` 只管录（hook、分片、合并）和折算（`trace.to_package_graph`），对 run 目录只知道 parts/ 在哪；`payload`、`serve`、`__main__` 只通过这里读 run。这样 CLI、serve、graph、tasks/pack 的 `--hot` 都走同一个 `resolve`，一个 REF 在哪儿都解析成同一个 run。

**原始数据和派生数据分开。** 合并逻辑还不成熟、以后还会改，所以原始分片（parts.tar.gz）永久保留，计数（counts.json.gz）只算派生数据，可以用 `runs merge` 重算。反过来，录制时才拿得到的东西（执行时的文件哈希、case 脚本和配置的副本、git 改动、GPU）只写一次，重算时不能拿「现在的样子」去盖。所以收尾拆成两步：`capture` 只跑一次，`derive` 可以反复跑。

**run 只存原始键（文件:首行号）和执行时的文件哈希。** 加载时才现映射到当前 index 上。代码改了以后老 run 照样能用；哪些文件在录制之后改过，由 `file_state` 逐个标出来，不会让整个 run 作废。

**run.json 和 detail.json 分开**：`runs ls` 列 100 个 run 时只读 100 个几 KB 的文件，不用把几十 MB 的 procs 和哈希都读进来。

## 读法
1. 模块 docstring（runs.py:1）：录一次永久复用、原始和派生、谁能删 run、为什么只存原始键。设计的来龙去脉在 `docs/design/runs.md` 的第 1、3、4 节，尤其是 4.3 末尾「实现时补上的几条」。
2. `new_run`（runs.py:150）→ `finalize`（runs.py:369）。按录制的时间顺序读，`finalize` 里再按 `capture` → `_pack` → `derive` 的顺序展开。
3. `merge_run`（runs.py:715）：`finalize` 的「事后重做」版本，读它能看清哪些东西会被重算、哪些不会。
4. `catalog` → `resolve` → `load`（runs.py:524 起），也就是读的那一侧，再加上 `file_state`（runs.py:587）。
5. `remove`、`live` / `_alive`、`rerun_command`：都是小函数，规则写在 docstring 里。
6. `migrate` / `_migrate_locked` / `_cleanup_legacy`（runs.py:393 起）放最后读：只为兼容老数据，逻辑最绕。

## 关键算法
### 收尾：capture 只写一次，derive 可以重做
`finalize` 先把 stop、returncode、时长、阶段日志写进 run.json，然后只在 detail.json 还不存在时才调 `capture`（runs.py:379），接着打包 parts/，最后调 `derive`。

`capture` 收集的东西：
- **文件哈希**：优先用 hook 在进程第一次跑到这个文件时算的那份，也就是执行的那份（runs.py:236）；老分片没有这个哈希的，退回收尾时磁盘上的，并记进 `sha_late`。
- **录制中被改过的文件**：hook 的哈希和收尾时磁盘上的不同，记进 `changed_during`。
- **安装包映射**：安装包和仓库不一致的记进 `mapped_mismatch`；仓库里根本没有的（构建时生成的 _version.py）另记 `mapped_only_installed`，不算不一致（runs.py:244）。
- **环境**：Python 和包版本（`_dists` 只看 dist-info 目录名，不 import 任何东西）、`_gpu`、git 改动。
- **文件副本**（`_collect_files`，runs.py:183）：case 脚本；任何进程的 argv 里出现的、200 KB 以内的 .sh/.py/.yaml/.json/.toml（vllm-omni 的 --deploy-config 指向的 yaml 就是这么存下来的）；`--attach` 点名的文件。被 source 的 common.sh 不会出现在命令行里，只能靠 `--attach`，所以点名的文件不受大小和个数限制。副本存成 files/NN-<文件名>，同名的不会互相覆盖。

`derive`（runs.py:311）写 counts.json.gz，重算 detail 里唯一的派生字段 `procs`，再定状态：
- **failed**：一个函数都没录到。
- **ok**：没有任何 problem、退出码 0、`stop == "exit"`。
- **partial**：其余情况，原因写进 `problems`：超时、被中断、driver 中途没了、非零退出码、有进程被强杀、有残留进程、有分片读不出来、有文件在录制中被改过。

「被强杀」的判据是：进程最后一次落盘的原因是定时落盘（periodic）或切阶段落盘（phase），说明它没走到正常退出（runs.py:322）。打包失败时状态退回 recording，并提示用 `runs merge` 重来（runs.py:345）。阶段顺序按 driver 记下的阶段日志（同名阶段取第一次出现的时刻），日志里没有的阶段排在后面。

### 打包不拿少的盖多的
`_pack`（runs.py:286）先写临时包，重新打开核对成员数，再 `os.replace`。已有的包成员比这次多，就直接放弃（runs.py:295）。收尾时如果包已经替换好、只是 parts/ 没删干净，不算失败。parts/ 里残留的那几个文件，下次 `runs merge` 时会和包合起来。

### merge_run：从并集重算
`merge_run` 先拒绝三种情况：录制还活着；`trace.leftovers` 发现还有进程属于这个 run、可能还在往 parts/ 里写（runs.py:726）；迁移来的老 run 没有原始分片。然后把 parts.tar.gz 解到 .merge-<pid>/，再把散着的 parts/ 盖上去（同名的是同一份或更新的，runs.py:741），用 `trace.merge` 合并。

- driver 死在收尾之前的 run，`stop` 补成 driver-lost（runs.py:747）。
- detail.json 还不存在的，现在补一次 `capture`，并标成 late（runs.py:749）。这时 files/ 和 git 改动是现在的样子，文件哈希仍是 hook 在执行时记下的。
- 只有 parts/ 还在时才重新打包。并集的成员数不会少于旧包，所以不会丢分片。
- 已有的 detail.json 和 files/ 一律不重写，`tests/test_runs.py` 里有专门的回归测试盯着这一条。

### 迁移老 trace：加锁，先拷、核对，再删
老版本每个 case 只有一份 trace-<case>.json，外加一个 parts-<case>/。`catalog` 在每个进程里第一次碰到某个仓库时（`_MIGRATED`）顺带触发迁移。设计稿 3.7 原本打算用 rename 认领，实际实现改成了这样：
- **用文件锁串行**（runs.py:406）：同时起的几个 serve / runs ls 排队等，后来的看到 run 已经在了就跳过。锁随进程释放，所以持锁时还看得到的 .tmp-*，一定是上次迁到一半死掉留下的，删掉重来即可（runs.py:411）。
- **只拷不挪**（runs.py:479）：runs/ 常常是指到另一块盘的软链，rename 跨不了文件系统。老文件逐字节 gzip 进 legacy/，parts-<case>/ 打成 parts.tar.gz。整个 .tmp-<id>/ 建好之后 `os.replace` 落位（runs.py:488），最后由 `_cleanup_legacy`（runs.py:498）核对：legacy 里那份解压后和老文件逐字节相同、包的成员名和 parts-<case>/ 一致，两样都对上才删老文件。任何一步不对就保留老数据。
- **id 是确定的**（runs.py:419）：老文件的 mtime + case 名，重复迁移、并发迁移算出来的都一样。`<id>` 已经存在（上次落位之后、删老文件之前死掉了）的，只补做收尾（runs.py:422）。老版本不限制 case 名（中文、+ 都有），所以目录名用清洗过的字符，run.json 里的 `case` 仍是原名，`--hot 原名` 照样找得到。
- **核对计数**（runs.py:436）：写回去再读出来，各阶段之和要等于老文件的 `funcs` / `func_edges`，每个阶段要逐键相等；对不上就保留老文件，打印原因。
- 老进程记录没有 ppid、argv 只存了前 6 个的，标 `argv_cut`（runs.py:448），界面上照旧提示「被截断」。

### 引用一个 run：REF
`resolve`（runs.py:545）接受 `完整 id | case`，后面可以跟 `@阶段`。先当完整 id 查，查不到再当 case 名：取这个 case 最新一次 ok 的；一次 ok 都没有，就取最新的 partial，再不行取最新的任意一个，并提示用的不是完整录完的（runs.py:554）。这样重录中途失败时，case 名不会被失败的那次抢走。不支持 id 前缀，因为前缀和日期会撞。`catalog` 按目录名倒序，id 以时刻开头，所以倒序就是新的在前。录制进程已经死了的 recording run，另加一个 `status_shown`，值为「中断」（runs.py:540），提示可以 merge。

### 加载：映射到当前 index，老的 meta 键一个不少
`load`（runs.py:632）读 counts.json.gz（某个阶段的，或者用 `_sum` 把各阶段相加，和老 trace 的 `funcs` 同义），交给 `trace.to_package_graph` 现算 hot，并在 hot 里写明来自哪个 run（runs.py:644），`notes.prompt_pack` 靠这个说明数字的出处。meta 保留老 payload 的全部键，前端（`web/app.js`）认的就是它们：
- `phases` 只有一个阶段时给空字典（runs.py:661），和老 trace 一样，前端据此判断分没分阶段。
- `stale_files` = changed + gone（runs.py:665）。mismatch 另有「安装包和仓库不一致」那句话，所以不算在这里。设计稿 3.5 写的是 changed + mismatch，以代码为准。
- `script` 优先读 files/ 里存下的那份（saved 为真）；老 run 没存脚本的，读现在的文件并标明不是录制时的内容。

在老键之外，meta 再加上 run 的信息：`run_id`、`status`、`problems`、`git`、`tags`、`note`、`created`、`migrated_from`，以及 `file_state`。

### file_state：和 index 比，不和工作区比
叠加用的行号来自 index，所以「这个文件录制之后改过没有」要拿 run 的哈希和 index 的 `file_sha` 比（scan 用的是同一种哈希 `sha16`）。按下面的顺序定状态（runs.py:603 起），只返回不是 same 的文件：
1. **mismatch**：录制时安装包就和仓库不一致，最先判。
2. 不在 index 里的：工作区里有、或者只在安装包里的，算 **outside**（scan 排除的 examples、_version.py），不叠加也不算过期；工作区里也没有的，算 **gone**。
3. **unknown**：run 没存这个文件的哈希。
4. **changed**：和 index 的 `file_sha` 不同。

老 index 没有 `file_sha` 时，退回 `trace.stale_files` 和工作区比（runs.py:614）。

### 删除和「还活着吗」
`remove`（runs.py:701）只认完整的 run id。case 名会解析到「最新一次录完的」，拿它删东西太容易删错；带 / 或以 . 开头的也不认，免得删到 .tmp-* 或 runs/ 外面。还在录的不删（runs.py:708）。「还在录」由 `live` 判断：状态是 recording，而且 `_alive(driver)` 为真。`_alive` 同时比对 pid 和启动时刻（`_proc_start`，读 /proc/<pid>/stat 的第 22 列），因为 pid 会被复用：driver 早死了、pid 被别的进程占了的 run，不能被当成「还在录」。

### 重录命令
`rerun_command`（runs.py:760）从 run 里存的命令、`--env`、tags、note，以及录制参数（timeout、stop_grace、attach）拼出一条能直接复制的 `codestrata trace`。值一律写成 --x=值，以 - 开头的值不会被当成选项；stop_grace 等于默认的 90 秒时省略（runs.py:768）。

## 局限
- 判断「还活着」全靠 /proc。没有 /proc 的系统上 `_proc_start` 返回 None，`_alive` 永远为假：正在录的 run 在 `catalog` 里会显示「中断」，`remove` 也拦不住。
- `_update`（tags / note）没有加锁。如果有人在 `finalize` 读完 run.json、`derive` 写回之前改了 tags，改动会被覆盖。
- `rerun_command` 不带 `--roots`：录制时手动指定过顶层包的，重录命令里要自己补上。
- 迁移时两个老 case 名清洗后相同、mtime 又落在同一秒的，后一个的 id 撞上前一个。`_cleanup_legacy` 看到 `migrated_from` 不同就什么都不做，所以后一个会一直留在原处不迁。不会丢数据，但也不会报错。
- `_write` 的临时文件名只带 pid，不带线程号。同一个进程里两个线程同时写同一个文件会撞。眼下没有多线程写 run 的调用方（serve 对 runs 只读）。

## 不确定
- `merge_run` 先按 REF 解析到 run，再从磁盘重读 run.json，不用 `catalog` 给的那份字典：那份带着只用来显示的「中断」`status_shown`，写回去会让 merge 成 partial 之后仍显示「中断」（`derive` 写回前也会去掉这个键）。`tests/test_runs.py` 里的 test_driver_killed_then_merge 覆盖了 merge 之后 `runs ls` 的显示。
