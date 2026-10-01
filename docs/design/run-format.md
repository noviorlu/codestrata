# run 的数据格式

一次录制（run）落在磁盘上长什么样、每个字段谁写谁读、怎么和静态索引对上。这是接其他语言的契约：
别的语言只要加一套扫描器和录制端，产出本页描述的数据，叠加、阶段、时间轴、时间顺序就都能用。

- 以代码为准：`codestrata/runs.py`（目录、run.json、detail.json、counts.json.gz、引用、对上 index）、
  `trace/`（`hook.py` 写的分片、`analysis.py` 的合并、阶段标记、叠加到单元）、`events.py`（事件日志 → span）、
  `seq.py`（span 的读法、时间段、时间顺序）、`scan.py` / `cut.py` / `ui/` / `layout.py`（静态索引和它的读法）。
  本页和代码对不上时以代码为准，并改本页。
- 本页每个字段名都对过代码和真实的 run（vllm-omni 上的一次 GPU 录制、测试用的假仓库）。
  拿不准的地方标了「未核实」。

## 0 通用约定

| 约定 | 内容 |
|---|---|
| 函数键 | `"<rel>:<行号>"`。`rel` 是相对仓库根的 POSIX 路径；行号是函数定义的**首行**（Python 是 `co_firstlineno`：有装饰器时是第一个装饰器那一行，等于 scan 的 `dl`）。模块顶层记成 `:0`。解析一律用 `rpartition(":")`，所以 `rel` 里可以有冒号、行号必须是整数。`:-1` 只由加载时的 remap 产生（见 §8），不会写进磁盘 |
| 仓库外的调用方 | `"<外部代码>/<文件名>:<行>"`：case 自己的脚本（入口脚本同目录的 .py）。只会出现在 `func_edges` 的调用方一侧，不计数、不上图 |
| 调用边键 | `"<调用方键>\|<被调方键>"`，用 `partition("\|")` 拆开，所以键里不能有 `\|` |
| 时间 | 磁盘上的时刻都是**相对 run 起点的微秒**（字段名以 `_us` 结尾），起点是 run.json 的 `clock.mono0_ns`（Linux 的 `CLOCK_MONOTONIC`，全机共享，不同进程可以直接比；换机器、重启后不可比）。原始分片和日志里的 `t0` / `t` 是绝对的 monotonic 纳秒 |
| 内容哈希 | `sha16` = `sha256(文件字节).hexdigest()[:16]`。录制端的 `file_shas`、scan 的 `file_sha`、存下文件的 `sha` 都是它，三边直接比 |
| 写法 | JSON 一律 UTF-8。run.json、detail.json、counts.json.gz 先写 `<名字>.<pid>.tmp` 再 `os.replace`（`runs._write`），读的一方看不到写了一半的文件：`.json` 是缩进 1 的 JSON，`.json.gz` 是紧凑 JSON 再 gzip（mtime=0），命令行里不是 UTF-8 的字节写成 `\udcXX` 转义。`events/spans/` 是整个目录先写到临时目录再换上 |
| 阶段名、case 名 | 都只能用 `[A-Za-z0-9._-]`（`runs.CASE_RE`、`trace.PHASE_NAME_RE`） |

## 1 目录布局

```
<repo>/.codestrata/
  .gitignore                 内容 "*"
  README.txt
  index.json  symbols.json   静态索引（scan 覆盖写，见 §9.3）
  xref.json                  交叉引用（冻结区，和 run 无关）
  graph.json                 函数之间的调用：graph 的 scan 记录（和 run 无关，见 §9.3）
  runs/                      可以是软链（比如指到 /mnt/data）；scan 不碰它
    .migrate.lock            迁移老格式时的文件锁
    <id>/                    一个 run，id = YYYYMMDD-HHMMSS-<case>[-k]（同一秒撞名加 -2、-3…）
      run.json
      detail.json
      counts.json.gz
      parts.tar.gz
      files/NN-<文件名>
      events/raw.tar.gz
      events/spans/index.json
      events/spans/keys.json
      events/spans/p<pid>-NNN.jsonl.gz
      legacy/trace-<case>.json.gz
      parts/                 只在录制中、或录制中断还没 merge 时存在
```

| 路径 | 类别 | 谁写 | 谁读 | 说明 |
|---|---|---|---|---|
| `run.json` | 原始 + 派生 + 可改 | `runs.new_run`（开录）、`runs.finalize` / `runs.merge_run`（收尾）、`runs.derive`、`runs set_tags` / `set_note` | 一切：列表、解析引用、加载 | 列表页只读它。录制时写下的字段不再变；`status`、`problems`、`phases`、`summary`、`sizes`、`events` 由 derive 重算；`tags`、`note` 可以随时改。见 §2 |
| `detail.json` | 原始（`procs` 除外） | `runs.capture`（只写一次）；`runs.derive` 只重写 `procs` | `runs.file_state`、`runs.load`、`runs show` | 加载某个 run 时才读。可以没有（加载时当 `{}`）。见 §3 |
| `counts.json.gz` | 派生 | `runs.derive`；迁移 | `runs.load_counts` | 叠加的主数据。见 §4。**没有它 run 不能加载**（`runs.load` 报「还没有计数」，`/api/runs` 的 `loadable` 为 false） |
| `parts.tar.gz` | 原始 | `runs._pack_all` | `runs.merge_run` | 录制端写出的全部分片（`part-*.json`、`PHASE`、`PHASE-*.fired`），见 §5。成员是平铺的文件名 |
| `parts/` | 临时的原始数据 | 各进程的 hook、driver | `analysis.merge`、`runs.merge_run` | 录制中各进程往这里写。收尾时打包成 `parts.tar.gz` 和 `events/raw.tar.gz`，打包核对成功才删 |
| `files/NN-<文件名>` | 原始 | `runs.capture` | `runs.load`（case 脚本给页面看） | 录制时的 case 脚本、进程命令行里出现的小配置文件、`--attach` 点名的文件。`NN` 是两位序号 |
| `events/raw.tar.gz` | 原始 | `runs._pack_all` | `runs.merge_run` | 各进程的时序事件日志 `ev-<pid>-<t0ns>.log`，见 §6.1。只有录了事件的 run 有（`trace` 默认录，被录的 Python 要 3.12+） |
| `events/spans/` | 派生 | `events.build`（finalize、merge 都会重建） | `seq.py` | 配好对、折叠过的 span，见 §6.2 |
| `legacy/trace-<case>.json.gz` | 原始 | `runs.migrate` | 没人读（留档） | 只有从老的 `.codestrata/trace-<case>.json` 迁移来的 run 有；逐字节压进来 |
| `<id>/.merge-<pid>/`、`*.tmp`、`spans.<pid>.tmp` / `.old` | 临时 | merge、原子写、`events.build` | — | 进程死在中途时可能留下，可以删 |
| `runs/.tmp-<id>/` | 临时 | 迁移 | — | 迁移中途死掉留下的，下次迁移时删掉重来 |

**原始 vs 派生。** 原始数据只在录制时拿得到（一次录制往往要几分钟 GPU），录完就不再改：`parts.tar.gz`、
`events/raw.tar.gz`、`files/`、`legacy/`、`detail.json`（`procs` 除外）、run.json 里开录和收尾时写下的字段。
派生数据可以用 `codestrata runs <repo> merge <id|case>` 从原始数据重算：它把 `parts.tar.gz`、`events/raw.tar.gz`
和散着的 `parts/` 解到一个临时目录（散着的同名文件覆盖包里的），重新合并，重写 `counts.json.gz`、`events/spans/`、
`detail.json` 的 `procs`、run.json 的派生字段；`detail.json` 已经有的不重写，没有的（driver 死在收尾之前）现在补，标 `captured: "late"`。
迁移来的老 run 没有分片，不能 merge。

除了 `runs rm`（整个 run）和 `runs rm --events-only`（只删 `events/`，run.json 的 `events` 置 null），没有代码会删 run 里的东西。

## 2 run.json

真实例子（vllm-omni 上的一次 GPU 录制，节选；`…` 是删掉的部分）：

```json
{
 "schema": 2,
 "id": "20260929-180408-run_single_prompt",
 "case": "run_single_prompt",
 "status": "ok",
 "problems": [],
 "driver": {"pid": 1380483, "start": 19450751},
 "created": "2026-09-29T18:04:08-0400",
 "host": "yc-Legion-T7",
 "cmd": ["bash", "examples/offline_inference/minicpmo/run_single_prompt.sh", "--model", "…"],
 "cwd": "/home/yc/projects/vllm-omni",
 "env": {"CUDA_VISIBLE_DEVICES": "0", "PYTHONPATH": "/home/yc/projects/vllm-omni", "…": "…"},
 "git": {"commit": "8ad6e801f5f4f5bad43c539d8cc80f8062ce9b35", "branch": "main", "n_dirty": 2},
 "clock": {"mono0_ns": 194507618705678, "wall0": 1790719448.9819646},
 "rec": {"timeout": 900.0, "stop_grace": 90.0, "attach": [], "events": true, "roots": null,
         "phase_at": [{"name": "serving", "func": "vllm_omni.entrypoints.omni:Omni.generate",
                       "file": "vllm_omni/entrypoints/omni.py", "qualname": "Omni.generate", "line": 78}, "…"]},
 "tags": [], "note": "",
 "invocation": {"argv": ["/home/yc/projects/codestrata/.venv/bin/codestrata", "trace", ".", "--case", "run_single_prompt", "…"],
                "cwd": "/home/yc/projects/vllm-omni"},
 "env_inherited": {"CONDA_DEFAULT_ENV": "base", "CONDA_PREFIX": "/home/yc/miniconda3"},
 "stop": "exit", "returncode": 0, "duration_s": 117.2,
 "phase_log": [["start", 494, "start"], ["serving", 103715942, "hook"], ["shutdown", 108681679, "hook"]],
 "events": {"n_lines": 238784, "n_spans": 102634, "n_calls": 114546, "truncated": [], "n_procs": 4, "bytes": 1415239},
 "phases": [{"name": "start", "t_us": 494, "n_funcs": 1997, "n_calls": 33018},
            {"name": "serving", "t_us": 103715942, "n_funcs": 744, "n_calls": 256744},
            {"name": "shutdown", "t_us": 108681679, "n_funcs": 36, "n_calls": 2437}],
 "summary": {"n_funcs": 2687, "n_func_edges": 3184, "n_files": 486, "n_procs": 19, "n_procs_active": 4,
             "n_mapped": 0, "n_leftovers": 0, "n_unclean": 0},
 "sizes": {"detail.json": 53332, "counts.json.gz": 70160, "run.json": 4158, "parts.tar.gz": 372410}
}
```

「必」列：**L** = run 要出现在列表里、能被解析，**H** = 要能叠加，**—** = 可以没有（读的地方都有兜底）。

| 字段 | 类型 | 含义 | 必 | 谁写 | 谁读 |
|---|---|---|---|---|---|
| `schema` | int | 现在是 `3`（3 起 counts.json.gz 带调用行 `func_lines`，§4；迁移来的老 run 没有） | — | `new_run`、迁移 | 没有代码读 |
| `id` | str | 等于目录名 | L | `new_run` | `catalog`、`resolve`、`load`、`/api/runs` |
| `case` | str | case 名；同一 case 可以录很多次 | L | `new_run` | `resolve`（按 case 找）、`runs ls`（分组，缺了会 KeyError）、复刻命令（老 run 没存 `invocation` 时拼命令，缺了会 KeyError） |
| `status` | str | `recording` / `ok` / `partial` / `failed`，规则见下 | L | `new_run`、`derive` | `resolve`（case 名优先取最新的 ok，其次 partial）、`live`、列表 |
| `problems` | [str] | 给人看的问题，如「超时」「2 个进程被强杀（最后几秒的数据可能缺）」 | — | `derive` | 列表、页面横幅 |
| `driver` | {pid, start} \| 无 | 录制的 driver 进程；`start` 是 `/proc/<pid>/stat` 的启动时刻（防 pid 复用） | — | `new_run` | `live` / `_alive`：还在录的 run 不能 merge、rm；status 是 recording 而 driver 已经没了的，列表显示「中断」（`status_shown`，只在内存里，不落盘） |
| `created` | str | 开录的本地时间，`%Y-%m-%dT%H:%M:%S%z` | — | `new_run` | 列表、页面 |
| `host` | str | 主机名 | — | `new_run` | `runs show` |
| `cmd` | [str] | 被录的命令（原样） | — | `new_run` | 页面（隐去密钥后）、`runs show`、找 case 脚本 |
| `cwd` | str | 命令实际执行的目录（绝对路径） | — | `new_run` | 找 case 脚本、复刻命令 |
| `env` | {str: str} | `--env` 设的变量（再加从 shell 继承、录事件时要带上的 `CODESTRATA_EV_MAX`） | — | `new_run` | 复刻命令、`runs show` |
| `git` | {commit, branch, n_dirty} \| null | 开录时的 git 状态；`branch` 分离头时 null；不是 git 仓库时整个 null。改动的文件列表在 detail.json | — | `new_run` | 列表、页面 |
| `clock` | {mono0_ns, wall0} \| null | run 的时间零点：driver 开录时的 `time.monotonic_ns()` 和同一刻的 `time.time()`。所有 `_us` 都相对 `mono0_ns` | 时序要 | `new_run` | `events.build`（把各进程的时刻换到 run 的轴上）、`merge_run`（算阶段标记的时刻） |
| `rec` | object | 录制参数，见下表 | — | `new_run` | 复刻命令、`merge_run`（`attach`）、页面（`phase_at`） |
| `tags` / `note` | [str] / str | 标签、备注；run 录完之后只有这两个还会被改 | — | `new_run`、`runs tag/untag/note` | 列表、页面 |
| `invocation` | {argv, cwd} \| null | 原样的 codestrata 命令和敲命令的目录，复刻用 | — | `new_run` | 复刻命令（没有时按 `rec`、`env`、`cmd` 拼） |
| `env_inherited` | {str: str} | 录制时 shell 里和复刻有关的环境变量（`CUDA_*`、`VLLM_*`、`PATH`…，名字像密钥的不记） | — | `new_run` | 复刻命令（「带环境」那一版）、页面 |
| `stop` | str | 怎么停的：`exit` / `timeout` / `interrupt` / `driver-lost`（driver 死在收尾之前、由 merge 补上） | — | `finalize`、`merge_run` | `derive` 定状态 |
| `returncode` | int \| null | 命令的退出码；命令没起来是 127 | — | `finalize` | `derive` |
| `duration_s` | float \| null | 命令从起到停的秒数（1 位小数） | — | `finalize` | 列表；`seq.run_end`（时间轴终点的候选之一） |
| `phase_log` | [[name, t_us, source]] | 切阶段的时刻，按时间排。`source`：`start`（开头）/ `sh`（case 脚本写 PHASE 文件切的，driver 每 0.1 秒轮询到的时刻）/ `hook`（`--phase` 切的，取阶段标记里的精确时刻）。同一个名字可以出现多次（切走又切回来）。`t_us` 不知道时是 null | 阶段 / 时间轴要 | `finalize`、`merge_run`（`analysis.merge_phase_log`） | `derive`（阶段的 `t_us`）、`seq.phase_segments`（时间轴）、页面（`hook` 来源的阶段提示「从第一次进入某函数开始」） |
| `phases` | [{name, t_us, n_funcs, n_calls}] | 各阶段：顺序按 `phase_log` 里第一次出现的先后，再补上只在 counts 里有的；只列 counts.json.gz 里有的阶段。`t_us` 取这个名字在 `phase_log` 里第一次出现的时刻；`n_funcs` 是这一阶段被调到的函数键数，`n_calls` 是次数之和 | H（阶段名要能解析） | `derive`；迁移 | `resolve`（`@阶段` 必须在这里）、`/api/runs`、页面（阶段按钮：两个以上才显示）、`seq._phase_log`（老 run 没有 `phase_log` 时用它的 `t_us`） |
| `summary` | object | `n_funcs`（全部阶段里不同的函数键数）、`n_func_edges`、`n_files`（`detail.file_shas` 的文件数）、`n_procs`（进程映像数）、`n_procs_active`（跑到仓库代码的）、`n_mapped`、`n_leftovers`、`n_unclean`（最后一次落盘是定时或切阶段的——被强杀了） | — | `derive` | 列表、`/api/runs`、页面 |
| `sizes` | {文件名: 字节} | run 目录下各文件的大小。在最后一次写 run.json **之前**取的，所以 `run.json` 自己的数不准 | — | `derive` | 没有代码读（`runs ls` 的大小是现走目录算的） |
| `events` | object \| null | 时序事件的摘要：`{n_lines, n_spans, n_calls, scope, truncated: [pid], n_procs, bytes}`（`scope` 同 span 的 index.json，2026-10-01 之前的 run 没有）；整理 span 失败时是 `{error, bytes}`；没录事件是 null。`bytes` 是 `events/raw.tar.gz` 的大小 | 时序要 | `derive`（`runs._build_events` 的结果）、`remove_events` | `/api/runs`（`events` 为真且没有 `error` 时，页面才开放「时间顺序」和在时间条上拖时间段）、`runs ls/show` |
| `migrated_from` | str | 只有迁移来的 run 有：老文件名 `trace-<case>.json` | — | 迁移 | 页面、`/api/runs` |

`rec` 的字段（`__main__.cmd_trace` 写）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `timeout` | float \| null | `--timeout` 秒数 |
| `stop_grace` | float | SIGINT 之后等多久再 SIGTERM（默认 90） |
| `attach` | [str] | `--attach` 的文件（解析成绝对路径） |
| `events` | bool | 是否录时序事件（2026-10-01 起默认是；`--no-events` 为否） |
| `roots` | [str] \| null | `--roots`；null 表示用 scan 时选的目录 |
| `phase_at` | [{name, func, file, qualname, line}] | `--phase 名字=函数` 解析的结果：命令行上的写法 `func`、落到的文件、qualname、def 行。页面用它标阶段的起点 / 终点节点 |

**status 的规则**（`runs.derive`）：一个函数都没录到是 `failed`；`problems` 为空、`returncode == 0`、`stop == "exit"` 是 `ok`；
其余 `partial`；分片没打包成功时留在 `recording`（可以再 merge）。时序事件到了行数上限、整理失败都**不**影响 status
（计数是完整的），只记在 `events` 里。

## 3 detail.json

录制时才拿得到的环境和文件信息。例子（测试用假仓库上的一次录制，节选）：

```json
{"sha_of": "executed",
 "file_shas": {"fakesvc/server.py": "573f3ae2ea1cd170", "fakesvc/work.py": "1356a9a64f579782"},
 "sha_late": [], "changed_during": [], "sha_conflicts": [],
 "mapped_from": null, "mapped": {}, "mapped_mismatch": [], "mapped_only_installed": [],
 "procs": [{"pid": 1633886, "ppid": 1633882,
            "argv": ["/home/yc/projects/codestrata/.venv/bin/python", "-m", "fakesvc.execd"],
            "argv_cut": false, "title": null, "n_funcs": 5, "t0_us": 55261, "t1_us": 73328,
            "why": "atexit", "py": "/home/yc/projects/codestrata/.venv/bin/python"}],
 "leftovers": [],
 "pythons": {"/home/yc/projects/codestrata/.venv/bin/python": {"version": "3.12.3", "dists": {"…": "…"}}},
 "gpu": [{"index": 0, "name": "NVIDIA GeForce RTX 5090", "driver": "595.84", "mem_mib": 32607}],
 "git": {"dirty": []},
 "script": {"path": "fake_service.sh", "stored": "files/00-fake_service.sh"},
 "files": [{"path": "fake_service.sh", "sha": "caec214994229a47", "stored": "files/00-fake_service.sh", "why": "script"}],
 "attach_missing": [], "captured": "finalize"}
```

| 字段 | 类型 | 含义 | 谁读 |
|---|---|---|---|
| `sha_of` | str | `executed`：哈希的是实际执行的那份文件（安装包里的也算）；迁移来的 run 是 `repo` | 没有代码读 |
| `file_shas` | {rel: sha16} | 这次跑到的每个仓库文件的内容哈希。优先取进程第一次跑到它时算的（录制中途改了文件也认得出），老分片没有时退回收尾时磁盘上的 | `file_state`（和当前 index 比，§8）；`summary.n_files` |
| `sha_late` | [rel] | 哈希是收尾时才取的文件 | 没有代码读 |
| `changed_during` | [rel] | 录制过程中被改过的文件（进程看到的和收尾时的不一样） | `derive` → problems |
| `sha_conflicts` | [rel] | 不同进程看到的内容不一样的文件 | `derive` → problems |
| `mapped_from` | str \| null | 跑的是安装包时，安装包的公共前缀路径 | 页面 |
| `mapped` | {rel: 实际执行的路径} | 从 site-packages 映射回仓库的文件 | 页面（`n_mapped`）、`summary.n_mapped` |
| `mapped_mismatch` | [rel] | 安装包里那份和仓库里的内容不一致（行号不可信） | `file_state`（`mismatch`）、页面 |
| `mapped_only_installed` | [rel] | 只在安装包里有的文件（构建时生成的 `_version.py`） | `file_state`（`outside`） |
| `procs` | [object] | 每个**进程映像**一条（exec 前后是两条），字段见下；按 `t0` 排 | `derive`（`n_unclean`、`summary`）、页面、`runs show` |
| `leftovers` | [{pid, argv, signal}] | 命令退出后还属于这个 run、被 driver 停掉的进程；`signal` 是最后发的信号名（`SIGINT` / `SIGTERM` / `SIGKILL`） | `derive` → problems、`runs show` |
| `pythons` | {解释器路径: {version, dists: {包名: 版本}}} | 各进程用的 Python 和装了哪些包（看 `*.dist-info` 目录名） | `runs show` |
| `gpu` | [{index, name, driver, mem_mib}] \| null | `nvidia-smi` 的结果，失败是 null | `runs show` |
| `git` | {dirty: [path]} | 开录时 `git status --porcelain` 里的文件（最多 200 个） | 没有代码读 |
| `script` | {path, stored} \| null | case 脚本：命令里的路径、存在 run 里的哪个文件 | `runs.load`（页面上给看「这次到底跑了什么」） |
| `files` | [{path, sha, stored, why}] | 存下的文件：`path` 是命令里的写法，`stored` 是 run 里的相对路径，`why` 是 `script` / `argv` / `attach` | `runs show` |
| `attach_missing` | [str] | `--attach` 了但没存下来的 | trace 结束时的提示 |
| `captured` | str | `finalize`（正常收尾时写的）或 `late`（merge 时才补的，环境信息是补的那一刻的） | 没有代码读 |

`procs` 的一条：

| 字段 | 类型 | 含义 |
|---|---|---|
| `pid` / `ppid` | int | |
| `argv` | [str] | 进程启动时的完整命令行（每个参数最多 400 字符、最多 60 个） |
| `argv_cut` | bool | argv 被截过 |
| `title` | str \| null | setproctitle 改过的进程标题（如 `VLLM::EngineCore_0`） |
| `n_funcs` | int | 这个进程映像跑到的不同函数键数（0 = 没跑到仓库代码） |
| `t0_us` / `t1_us` | int \| null | 进程映像开始 / 最后一次落盘的时刻 |
| `why` | str \| null | 最后一次落盘的原因：`atexit` / `_exit` / `exec`（正常结束）；`periodic` / `phase`（定时或切阶段时落的——之后被强杀了）；`stop`（driver 升级到 SIGTERM 之前通知的那次） |
| `py` | str \| null | 解释器路径 |

## 4 counts.json.gz

叠加用的主数据：按阶段分开的调用次数和调用边。例子（假仓库上 `--phase generate=… --phase shutdown=…` 的一次录制，节选）：

```json
{"phases": {
   "start":    {"funcs": {"fakesvc/offline.py:0": 1, "fakesvc/offline.py:14": 1, "fakesvc/offline.py:44": 1,
                          "fakesvc/work.py:7": 1, "fakesvc/work.py:11": 3},
                "func_edges": {"fakesvc/offline.py:0|fakesvc/offline.py:44": 1,
                               "fakesvc/offline.py:22|fakesvc/work.py:7": 1, "fakesvc/work.py:8|fakesvc/work.py:11": 3}},
   "generate": {"funcs": {"fakesvc/offline.py:29": 1, "fakesvc/work.py:15": 3},
                "func_edges": {"fakesvc/offline.py:44|fakesvc/offline.py:29": 1, "fakesvc/work.py:19|fakesvc/work.py:15": 3}},
   "shutdown": {"funcs": {"fakesvc/offline.py:15": 1}, "func_edges": {"fakesvc/offline.py:44|fakesvc/offline.py:15": 1}}},
 "names": {"fakesvc/offline.py:0": "<module>", "fakesvc/offline.py:14": "BaseEngine", "fakesvc/offline.py:44": "main",
           "fakesvc/work.py:8": "init_model.<locals>.<genexpr>", "fakesvc/offline.py:29": "Engine.generate"}}
```

| 字段 | 类型 | 含义 | 必 |
|---|---|---|---|
| `phases` | {阶段名: {funcs, func_edges, func_lines?}} | 至少一个阶段；只有一个时也保留名字（通常是 `start`）。每个阶段**`funcs`、`func_edges` 都要有**（可以是空对象） | H |
| `phases.<名>.funcs` | {函数键: int} | 这一阶段里这个函数被**进入**的次数（生成器 / 协程恢复不算）。只有仓库代码，case 脚本的代码不计数。模块顶层（`:0`）和类体（键的行号落在类的定义行上）也在里面——它们是定义时的执行，加载时被分出来，不算调用 | H |
| `phases.<名>.func_edges` | {调用边键: int} | 调用方是**栈上最近的仓库帧**（穿过标准库、第三方库的调用记到最近的仓库函数头上），被调方是这个函数。递归自调用不记；同文件内的调用也记 | H（没有它就只有节点、没有边） |
| `phases.<名>.func_lines` | {"<调用边键>\|<行>": int} | 同 `func_edges`，按**调用写在调用方的哪一行**分开：调用方那一帧当时执行到的行（hook 记指令偏移，写分片时换成行号）。跨行的调用是 CPython 给那条调用指令的行（在调用表达式占的行里）；拿不到是 0。同一条边各行相加等于 `func_edges`。2026-09-30 之后录的才有（`schema` 3），之前的 run 没有这一项（不是「没有调用」） | — |
| `names` | {函数键: qualname} | 录制时的限定名（Python 的 `co_qualname`：嵌套函数是 `outer.<locals>.inner`，模块顶层是 `<module>`）。只用于录制后改过的文件把键挪到函数现在的行号上（§8）；没有它这些文件的次数只算到文件上 | — |

- 阶段的次数是**每个进程**里「切阶段时的累计快照」相邻相减、负数丢掉，再把所有进程加起来（`analysis.merge`）。
  所以阶段归属是按各进程看到阶段切换的那一刻：各进程每 0.05 秒看一次 `PHASE`（另外每秒兜底读一次）；`--phase` 切的，
  触发的那个线程当场切、再停 0.1 秒等别的进程跟上。计数的阶段边界和 `phase_log` 的时刻因此可能差几十毫秒。
- 不带阶段加载（`<id>` 不带 `@`）= 各阶段逐键相加（`runs._sum`）。
- 加载时从这里算出的东西（`module_frames`、`class_frames`、`anon`、函数对和它们和 scan 比的结果 `calls`、`redirect`…）
  **不存盘**，每次按当前的 index 现算（`align.to_package_graph`），见 §8。

## 5 原始分片（parts/，打包后在 parts.tar.gz）

录制端的输出。收尾时 `analysis.merge` 把它们合成 §4 的计数。文件都平铺在 `parts/` 里：

| 文件 | 谁写 | 内容 |
|---|---|---|
| `part-<pid>-<t0ns>.json` | 每个进程映像的 hook | 这个进程映像的**累计**计数和元数据，见下表。每次落盘整份覆盖。`t0ns` 是进程映像开始时的 monotonic 纳秒：exec 之后同一个 pid 写新文件 |
| `part-<pid>-<t0ns>@<n>-<阶段>.json` | hook，切阶段时 | 切换那一刻的累计快照 `{funcs, func_edges, func_lines}`；`<n>` 从 0 递增，`<阶段>` 是**刚结束**的那个阶段 |
| `PHASE` | case 脚本或 hook | 当前阶段。第一行是阶段名；hook 切的有第二行（切换那一刻的 monotonic 纳秒）。case 脚本 `echo serving > $CODESTRATA_OUT/PHASE` 就切过去 |
| `PHASE-<阶段>.fired` | hook（`--phase`）或 driver（替 case 脚本建） | 这个阶段被切过的标记，内容一行 `hook <pid> <monotonic_ns>` 或 `sh <pid> <monotonic_ns>`。`O_EXCL` 建：每个阶段整个 run 只切一次。收尾和 merge 从它取阶段的精确时刻（`analysis.fired_phases`） |
| `ev-<pid>-<t0ns>.log` | hook（录时序事件时） | 时序事件日志，收尾时打包进 `events/raw.tar.gz`（不进 parts.tar.gz），见 §6.1 |
| `STOP` | driver | 升级到 SIGTERM 之前建（内容 `stop`）：各进程看到就立刻落一次盘。建过的话也会打进 parts.tar.gz，merge 不读它 |

也认老的命名 `part-<pid>.json`、`part-<pid>@<n>-<阶段>.json`。

`part-<pid>-<t0ns>.json` 的字段（真实分片里的样子：`{"pid": 1634027, "ppid": 1634024, "st": 21140358, "argv": […], "argv_cut": false, "t0": 211403605542436, "t": 211403833271307, "why": "atexit", "py": {…}, "phase": "shutdown", "funcs": {…}, "func_edges": {…}, "names": {…}, "mapped": {}, "shas": {…}}`）：

| 字段 | 类型 | 含义 | merge 缺了会怎样 |
|---|---|---|---|
| `pid` / `ppid` | int | | detail.procs 里是 null |
| `st` | int | `/proc/self/stat` 的启动时刻 | 只用来认残留进程（`driver.leftovers`） |
| `argv` / `argv_cut` / `title` | | 同 detail.procs | null |
| `t0` / `t` | int | 进程映像开始 / 这次落盘的 monotonic 纳秒 | procs 的 `t0_us` / `t1_us` 是 null |
| `why` | str | 这次落盘的原因（同 detail.procs） | null；不算强杀 |
| `py` | {version, executable, site} | 解释器信息；`site` 是 site-packages 目录（用来列包版本） | `pythons` 为空 |
| `phase` | str | 落盘时所处的阶段（最后一段的名字） | 当成 `start` |
| `funcs` / `func_edges` / `func_lines` | 同 §4 | **累计**值 | 当成空（`func_lines` 缺了：这个 run 没有调用行） |
| `names` | 同 §4 | | remap 不了 |
| `mapped` | {rel: 实际路径} | 从安装包映射回仓库的文件 | 当成没映射 |
| `shas` | {rel: sha16} | 进程第一次跑到这个文件时算的内容哈希 | 退回收尾时磁盘上的哈希（记进 `sha_late`） |

## 6 时序事件

录时序事件（`trace` 默认录，`--no-events` 不录；需要 Python 3.12 的 `sys.monitoring`）才有。记每一次调用，口径和 `func_edges` 相同
（调用方是栈上最近的仓库帧，递归自调用不算）。2026-10-01 之前录的只记了**跨文件**的调用（调用方和被调方不在同一个文件），
同文件的只在计数里有：日志里没有 `M` 行，index.json 的 `scope` 是 `"cross"`。

### 6.1 原始日志 ev-<pid>-<t0ns>.log

一个进程映像一份文本，一行一个事件，空格分隔（`events.parse`）：

```
H <pid> <t0_ns> <ppid>                      文件头（没有时从文件名取 pid 和 t0）
M all                                       同文件的调用也记了（2026-10-01 起，紧跟在 H 后面；没有这一行的只记了跨文件的）
N <tid> <线程名>                             线程登记：进程内的小整数 → 线程名
K <id> <函数键>                              键登记：进程内的小整数 → rel:首行
C <t_us> <tid> <span> <调用方 id> <被调方 id>   调用
R <t_us> <tid> <span>                       返回，或异常展开
Y <t_us> <tid> <span>                       挂起（yield、await）
S <t_us> <tid> <span>                       恢复
T                                           达到行数上限，之后不再记调用（计数不受影响）
F <tid> <起它的 tid> <span> <t_us>           谁起的这个线程：在哪个线程的哪个 span 里 Thread.start（span 0：不在任何 span 里）。新线程第一次登记（N）时写
P <t_us> <tid> <span> <子进程 pid>           在这个 span 里 exec 出一个子进程（subprocess、multiprocessing 的 spawn、os.posix_spawn）
B <父进程映像的 t0_ns> <tid> <span>          这个进程映像是从父进程的哪个线程、哪个 span 里 fork 出来的（os.fork、multiprocessing 的 fork）
Q <t_us> <tid> <span> <种类> <队列 id> <对象 id>  往进程内的队列里放了一个对象（种类 q：queue.Queue 及子类，a：asyncio.Queue 及子类，j：janus）
G <t_us> <tid> <span> <种类> <队列 id> <对象 id>  从队列里取出一个对象
O <t_us> <tid> <span> <指纹>                  ZMQ 发出一条消息（按帧记，带 SNDMORE 的攒到最后一帧；指纹是数据帧的长度 + 首尾 32 字节的 blake2b，ROUTER 的身份帧不算）
I <t_us> <tid> <span> <指纹>                  ZMQ 收到一条消息（recv_multipart；asyncio 版的 span 是等它的那个协程）
```

F / P / B / Q / G / O / I 是 2026-10-01 起才有的，和 C 一样算进行数上限（F、B 除外）。

真实片段（vllm-omni 的一个 engine core 进程）：

```
H 1380721 194513971758917 1380497
N 1 MainThread
K 1 examples/offline_inference/minicpmo/end2end.py:0
K 2 vllm_omni/__init__.py:0
C 3783842 1 1 1 2
K 3 vllm_omni/version.py:0
C 3784003 1 2 2 3
R 3784145 1 2
```

- `t_us` 是相对**这个进程映像的 t0**（H 行的 `t0_ns`）的微秒；整理时加上 `(t0_ns − mono0_ns) // 1000` 换到 run 的轴上。
- `span` 号在进程映像内唯一；R / Y / S 用 span 号找回是哪次调用，不靠栈的顺序（同一线程里交错的协程也配得对）。
- `K`、`N` 要出现在用到它的那一行之前或之后都行（整理时整份读完再换算）；丢了登记行的键在 span 里指向 `"?"`。
- 名字里的换行替换成空格；文件按 UTF-8 + backslashreplace 写；只按 `\n` 分行，没有换行结尾的最后一行（写到一半被杀）整行丢掉；坏行跳过。
- 落盘重试可能把一批行写两遍：重复的 C、已经挂起又挂起、已经在跑又恢复，整理时都不算。
- 上限：每个进程映像最多 `CODESTRATA_EV_MAX` 条 C（默认 3,000,000）；到了写一行 `T`。之前开始的调用的 R / Y / S 照写。

### 6.2 整理好的 span：events/spans/

`events.build` 写（finalize 和 merge 都会整个重建，先写临时目录再换上）。

**index.json**（真实例子，节选）：

```json
{"pairing": "frame", "scope": "all",
 "chunks": [{"pid": 1380721, "chunk": "p1380721-000.jsonl.gz", "t0_us": 10136895, "t1_us": 109501360, "n": 2939}, "…"],
 "procs": [{"pid": 1380721, "ppid": 1380497, "t0_us": 6353053, "n_events": 10726, "n_spans": 2939, "truncated": false}, "…"],
 "truncated": [], "n_lines": 238784, "n_spans": 102634, "n_calls": 114546}
```

| 字段 | 类型 | 含义 | 谁读 |
|---|---|---|---|
| `pairing` | str | 固定 `"frame"`（按帧配对） | 没有代码读 |
| `scope` | str | `"all"`：每次调用都有 span；`"cross"`：只有跨文件的（老 run，没有这个字段也是）；`"mixed"`：几个进程不一样（录到一半换了 codestrata） | `seq.phase_calls` → `path`（老 run 才按计数补同文件的那一跳） |
| `chunks` | [{pid, chunk, t0_us, t1_us, n}] | 每块 span 文件：属于哪个 pid、文件名、块里最早的开始、最晚的结束（`max(t0 + max(dur, 0))`）、行数。**块上没有 truncated 字段** | `seq`：按 `t0_us` / `t1_us` 跳过和时间段不重叠的块；`seq.run_end` 取所有块的 `t1_us` 最大值当时间轴终点的候选 |
| `procs` | [{pid, ppid, t0_us, n_events, n_spans, truncated}] | 每个进程映像一条（同一 pid exec 前后是两条）；`n_events` 是 C/R/Y/S 行数；`truncated` 是这个映像到了行数上限 | `runs._build_events`（数进程） |
| `truncated` | [pid] | 到了行数上限的进程 | run.json 的 `events.truncated`、`seq.edge_times` 原样带出 |
| `thread_from` | {"\<pid\>": {"\<tid\>": [起它的 tid, span 下标]}} | 线程是谁起的（F 行）：在同一个进程的哪个线程、哪个 span 里 `Thread.start`；span 下标是 `-1` 时不在任何 span 里（模块顶层、线程的入口函数）。没记到的线程（2026-10-01 之前的 run、主线程）没有 | （P0 的运行时模型） |
| `handoffs` | [{via, from, to}] | 谁把数据交给谁：`from` / `to` 是 `[pid, tid, span 下标, t_us]`，`via` 是 `queue` / `asyncio` / `janus` / `zmq`。队列在同一个进程映像里按（队列 id, 对象 id）先进先出地配；ZMQ 跨进程按指纹先发先收地配（发的时刻不晚于收的）；同一个线程里自己放自己取的不算。没盯的通道（`queue.SimpleQueue`、线程池的 submit、共享内存、管道、socket）没有 | （P0 的运行时模型） |
| `spawns` | [{pid, tid, row, child, how, t_us}] | 子进程是谁起的：`pid` / `tid` / `row` 是起它的那一边（`row` 是 span 下标，-1 是不在任何 span 里），`child` 是子进程 pid，`how` 是 `exec`（P 行，带 `t_us`）或 `fork`（B 行）。exec 出来的子进程不一定是 Python、也不一定跑到仓库代码 | （P0 的运行时模型） |
| `n_lines` | int | 所有日志的 C/R/Y/S 行数 | run.json 的 `events` |
| `n_spans` | int | span 行数（折叠后） | 同上 |
| `n_calls` | int | 调用次数（`Σ rep`） | 同上 |

**keys.json**：`{"keys": [函数键…], "threads": {"<pid>": {"<tid>": 线程名}}}`。`keys` 是整个 run 的全局键表，span 里的
`a` / `b` 是它的下标；键的登记行丢了的指向 `"?"` 这一项（不会静默指到别的函数上）。同一个 pid 的多个映像，线程号接着编（exec 之后的
线程号加上之前映像的最大线程号）。例：`{"keys": ["fakesvc/server.py:0", "fakesvc/work.py:0", "fakesvc/server.py:45", …], "threads": {"1633882": {"1": "MainThread"}}}`。

**p\<pid\>-NNN.jsonl.gz**：gzip 的 JSON 行，每行一条 span；每个 pid 一组文件，按 `(t0, depth)` 排好，每块最多 100,000 行，`NNN` 从 000 开始。
一个 pid 的几块连起来数下标（`parent` 用的就是这个下标）。

### 6.3 一行 span

```
[t0, dur, tid, depth, a, b, rep, n_susp, parent]
```

| 下标 | 字段 | 含义 |
|---|---|---|
| 0 | `t0` | 调用开始的时刻（µs，相对 run 起点） |
| 1 | `dur` | 墙钟时长（µs）。挂起过的（async）包含挂起的时间。**到进程结束都没返回的是 `-1`**（被杀的服务、半路被丢掉的生成器）。折叠行是第一次开始到最后一次**结束** |
| 2 | `tid` | 线程号（keys.json 的 `threads[pid]` 里查名字） |
| 3 | `depth` | 调用那一刻这个线程上正在执行（没返回、也没挂起）的 span 数 |
| 4 / 5 | `a` / `b` | 调用方 / 被调方在 keys.json `keys` 里的下标 |
| 6 | `rep` | 这一行合了几次调用（≥1） |
| 7 | `n_susp` | 挂起了几次；>0 就是 async 的 span（折叠行一定是 0） |
| 8 | `parent` | 父 span 在这个 pid 的 span 里的下标，没有（线程的根、父亲在行数上限之后）是 `-1`。父 span 是调用那一刻这个线程上最里层正在执行的 span（挂起的不算），按原始日志重放得到，async 的也准。`scope` 是 `"all"` 时父 span 的被调方就是这一行的调用方。2026-10-01 之前整理的 span 没有这一列，`runs merge` 从原始日志重建就有 |

真实的行（vllm-omni）：`[89391161, 25097353, 2, 0, 994, 995, 2268, 0]` 是一个轮询：同一对函数连续调了 2268 次、
从 89.4 秒到 114.5 秒；`[6338823, 4321, 2, 1, 572, 574, 1, 1]` 是一次挂起过一次的 async 调用（这两行是加 `parent` 之前的）。

**第一级折叠**（`events.fold`）：同一个线程上、同一个**父 span** 下、中间这个线程没有挂起 / 恢复、同一对 `a → b`、
自己没挂起过、没有记下的子调用、已经返回的连续调用，合成一行，`rep` 是次数，`dur` 从第一次开始到最后一次结束。
按父 span 而不按深度认兄弟：同一线程上交错的两个协程，子调用深度相同但不是兄弟。

**怎么读 rep > 1 的行**（`seq._calls_in`，时间段和时间顺序都这样算）：把 `rep` 次调用**均匀摊在 `[t0, t0 + dur]` 上**，
第 i 次（i = 0 … rep−1）在 `t0 + i·dur/(rep−1)`。`rep ≤ 1` 或 `dur ≤ 0`（含没返回的 −1）时，整行的次数都算在 `t0` 那一刻。
这是近似：只记了第一次的开始和最后一次的结束。

**时钟**：所有 `t0` 都相对 run.json 的 `clock.mono0_ns`，和 `phase_log`、`phases[].t_us`、`detail.procs[].t0_us` 是同一根轴。
`clock` 为 null 时（迁移来的老 run）各进程的偏移按 0 算，时刻不可信。

### 6.4 从 span 算出来的东西（不存盘）

- **时间段的次数**（`seq.window_counts`，`@t=起-止`）：落在 `[起, 止]` 里的调用 → 和 counts 同形状的 `{funcs, func_edges, func_lines}`
  （被调方算一次进入）。老 run 只有跨文件的调用，比按阶段看的次数少（页面上注明）。span 不记调用行：每一对的次数按它在整个 run 的
  `func_lines` 里各行的比例摊到行上（`seq.spread_lines`，最大余数法，每对加起来正好是它的次数；整个 run 里没有这一对的记在第 0 行），
  和 scan 比的结果和按阶段看的一样；每行的次数是约数（`hot.lines_approx`，页面上注明）。老 run 没有 `func_lines` 就不给。
- **请求路径**（`seq.phase_calls` → `path.request_path`，`/api/path`、`codestrata path`）：一个阶段（或时间段）里每个（进程, 线程, 调用方键, 被调方键）
  的首末时刻和次数，落到 graph 的节点上排成调用树（见 decisions「请求路径」）。线程名来自 keys.json 的 `threads`，进程名来自 detail.json 的 `procs`（`title`、`argv`）。
- **时间顺序**（`seq.edge_times`，`/api/seq/edges`）：一个阶段（或时间段）里，切面上每条节点间的边
  `{first, last, n, spread, repeat}`。阶段的时间段来自 `phase_log`：各段左闭右开，最后一段闭到 run 的终点；
  终点 = max(`duration_s`、最后一次切阶段、所有块的 `t1_us`)（`seq.run_end`）。`repeat` = 至少 5 次，且同一进程里第一次到最后一次
  隔了这段时间的一半以上。两端落在同一个节点的、被调方是定义时的执行（模块顶层、类体）的、落不到 index 里的都不算。

## 7 run 的引用

```
REF := (<完整 run id> | <case 名>) [ "@" <阶段名> | "@t=" <起 µs> "-" <止 µs> ]
```

`runs.resolve` 解析，命令行（`--hot`、`runs show/merge/tag/note`）和页面（`/api/graph?run=`、`/api/seq/edges?run=`）通用：

- 先当完整 id 找，找不到再当 case 名：取这个 case 最新一次 `ok` 的；没有就取最新的 `partial`（打印提示）；再没有就取最新的一次（不论状态）。
  「最新」按目录名倒序（id 以时间戳开头）。`runs rm` 只认完整 id。
- `@阶段名`：必须在 run.json 的 `phases` 里；只看 counts.json.gz 里这一阶段的数。
- `@t=起-止`：时间段（页面上时间条拖出来的），微秒、相对 run 起点，要求 `0 ≤ 起 < 止`；要有 `events/spans/`，次数只有跨文件的调用（§6.4）。
- 不带 `@`：全部阶段相加。

例：`20260929-180408-run_single_prompt`、`run_single_prompt@serving`、`run_single_prompt@t=103715942-108681679`。

## 8 run 怎么对上当前的 index

run 只存原始键（`文件:首行号`）和录制时的文件哈希，加载时现映射到当前的 index 上（`runs.load`），所以代码改了之后老 run 照样能叠：

1. **读计数**：`counts.json.gz` 的一个阶段、全部阶段之和，或时间段（§6.4）；连同 `names`。
2. **定每个文件的状态**（`runs.file_state(repo, idx, detail)`），只列不是「没变」的：

   | 状态 | 条件（按顺序判） | 叠加时 |
   |---|---|---|
   | `mismatch` | 在 `detail.mapped_mismatch` 里：录制时跑的安装包就和仓库不一致 | 按 qualname 挪键 |
   | `outside` | 不在 index 的 `files` 里，但在 `mapped_only_installed` 里或工作区里还有（scan 排除了的 examples、只在安装包里的） | 不叠加、不算过期 |
   | `gone` | 不在 index 里，工作区里也没有 | 不叠加，算过期 |
   | `unknown` | 这个 run 没存这个文件的哈希（空串） | 照叠 |
   | `changed` | `detail.file_shas[rel]` ≠ index 的 `file_sha[rel]`（index 没有 `file_sha` 时退回和工作区比） | 按 qualname 挪键 |

   没有 detail.json 时所有文件都当「没变」。页面的「⚠ 录制后有文件改过」= `changed` + `gone`（`hotMeta.stale_files`）。
3. **按 qualname 挪键**（`align.remap`）：只对 `changed` / `mismatch` 且在 index 里的文件。用 index 的符号表建
   `(文件, 限定名) → 现在的行号`（有 `dl` 用 `dl`，否则 `l`）；录制时的 qualname 去掉 `.<locals>` 再查。
   查到的把键改成 `rel:现在的行号`；查不到的、名字里有 `<` 的（lambda、生成器表达式）、没存 qualname 的，键改成 `rel:-1`
   ——次数还算在这个文件和它的单元上，但不算到任何函数上。模块顶层（`:0`）不动。改写后撞到同一个键的相加。
   对不上的键数给页面（`unmatched`）。`func_lines` 的调用行跟着调用方挪：函数整个挪了几行，行也挪几行（函数体里面改过的，行就可能偏）；
   调用方是模块顶层（`rel:0`，没有可以对的定义行）或者改成了 `rel:-1` 的，行记成 0（不知道是哪一行）。
4. **落到 graph 的节点上**（`align.to_package_graph(counts, idx)`）：
   - `rel` → 单元：`idx.files[rel]`；不在里面的键整个不叠。
   - `(rel, 行)` → 符号：index 符号的 `(f, l)`、`(f, dl)` 和同名的另几个 def（`a`）都能对上；对不上的是 `anon`
     （闭包、lambda：算到文件和单元上，节点写成 `外层符号.<L行号>`）；模块顶层是 `<rel>#<module>`。和 graph.json 同一种写法。
   - **定义时的执行不算调用**（`align.defining`）：行号 0 → 模块顶层（`module_frames`）；行号正好是某个 `class` 符号的
     `l` / `dl` → 类体（`class_frames`）；行号 1 又对不上任何符号 → 当模块顶层（老格式）。被调方是定义的边（import 触发的
     模块顶层执行、class 语句）不算调用。
   - 函数对（`calls`）：`func_edges` 落到节点上，`func_lines` 给出每个函数对的调用行；同一个文件里的也留着（代码窗口要）。
5. **和 scan 记录比**（`align.classify`）：每个函数对的每个调用行，看 graph.json 里调用方在那一行记的调用：定下的被调方就是它，
   两边都有；否则只有 trace，记下 scan 在那一行看到的是什么（`align.judge`）。行是 0 的（不知道是哪一行）在调用方整个函数里比。
   **构造**：那一行写的构造 `C(…)`（种类 1）会跑到这个方法的（graph.json 的 `ctors`）——这些调用从 F→方法挪到 F→C 这个函数对上
   （被调方是类，两边都有），和 scan 的记录对上，一次构造只算一次（同一行的 `__new__`、`__init__` 取多的那个；一行里几处构造都会跑到
   这个方法时平分）。整个挪过去了的函数对记进 `redirect`（trace 的键对 → C 的文件），「时间顺序」也照这个算到 C 上。
   调用方自己里面的 lambda、生成器表达式（F → F.<L行>）算两边都有。没有 `func_lines` 的老 run 在整个函数里比，调用处按名字猜。
6. **折到切面**（`align.hot_on_cut`）：单元 → 当前切面上的节点（`cut.view` 的 `node_of`），节点、节点间的调用次数、其中只有 trace 的次数分别相加。

## 9 给其他语言的录制端

核心不认语言：上面的格式里只有「文件:首行号」、进程、时刻。另一种语言要做的是：扫描端产出 §9.3 的静态索引，录制端产出
§9.2 的 run 数据。

### 9.1 三种接法

| 接法 | 录制端要做的 | codestrata 替你做的 | 已验证 |
|---|---|---|---|
| **A. 复用 `codestrata trace` 的 driver** | 被录的进程里读环境变量 `CODESTRATA_ROOT`（仓库根，realpath）、`CODESTRATA_OUT`（`parts/` 的路径）、`CODESTRATA_EVENTS`（`1` 才记事件），往 `$CODESTRATA_OUT` 写 §5 的 `part-*.json`（和 `ev-*.log`）；时刻用 `CLOCK_MONOTONIC` 纳秒；每隔几秒整份落一次盘，退出前再落一次，看到 `$CODESTRATA_OUT/STOP` 时也落一次（之后可能被 SIGTERM / SIGKILL）；`$CODESTRATA_OUT` 不存在时什么都别写（录制已经收尾） | 起命令、停进程（三级信号、残留进程）、case 脚本写 PHASE 的阶段、run.json 全部、收尾（合并、打包、detail、span） | 是：一个 bash 脚本冒充录制端写分片，`trace` 出来 `ok`、两个阶段、叠加正常。`--phase 名字=函数` 的解析和注入的 `sitecustomize.py` 是 Python 专用的；别的语言要按函数切阶段，自己在 hook 里做（写 `PHASE` 和 `PHASE-<名>.fired`，格式见 §5），`CODESTRATA_PHASE_AT` 可以不管 |
| **B. 自己的 driver，写分片再 merge** | 建 `runs/<id>/`，写一个骨架 run.json（`id`、`case`、`status: "recording"`、`clock.mono0_ns`、`cmd`、`cwd`，正常结束的再写 `stop: "exit"`、`returncode: 0`、`duration_s`），`parts/` 里放分片、事件日志、阶段标记；然后跑 `codestrata runs <repo> merge <id>` | 合并、打包、detail.json（标 `captured: "late"`）、counts、span、run.json 的派生字段 | 是：手写一个进程映像的分片 + 快照 + `PHASE-serving.fired` + 事件日志，merge 后 `ok`，按阶段、按时间段叠加和时间顺序都对。不写 `stop` 的会被当成 `driver-lost`（`partial`）；不写 `driver` 就当 driver 已经不在了 |
| **C. 直接写成品** | 按 §2–§4、§6.2 写 run.json、counts.json.gz（和 detail.json、`events/spans/`） | 只负责读 | 是（最小集）：只有 `{"id", "case", "status": "ok"}` 的 run.json 加一个 counts.json.gz，就能列出、`runs show`、叠加。但这样没有原始数据，以后格式或合并逻辑变了没法 merge 重算；**推荐 A 或 B** |

### 9.2 各级功能要的最小集（接法 C 的视角；A / B 由 codestrata 补齐）

| 要的功能 | 必须有 | 建议有 |
|---|---|---|
| **不需要 scan 就能用的**：run 出现在列表里（`runs ls`、页面下拉）、`runs show`、按 case 名解析 | `runs/<id>/run.json` 含 `id`（= 目录名）、`case`、`status`（`ok` / `partial` 才会被 case 名优先选中） | `created`、`duration_s`、`summary`、`problems`、`cmd`、`cwd`、`git` |
| **叠加到图上**（节点、边上的次数、只看跑到的、边的明细） | 上一行 + `counts.json.gz` 至少一个阶段，每个阶段有 `funcs` 和 `func_edges`；键的 `rel` 在 index 的 `files` 里。**叠加一定要 index**：没有 scan 过的仓库只能看列表 | `func_lines`（没有它就不知道调用写在哪一行：和 scan 只能按整个函数比、调用处按名字猜，代码窗口里也标不出运行时调到了谁）；`detail.json` 的 `file_shas`（没有它就判断不了录制后哪些文件改过，改过的文件会叠到错的函数上）、`names`（改过的文件按名字挪键） |
| **阶段**（阶段按钮、`@阶段`） | counts.json.gz 里两个以上阶段；run.json 的 `phases` 列出同样的名字（`resolve` 查它、页面按它出按钮） | `phases[].n_funcs`、`n_calls` |
| **时间条**（阶段按时间画成一段段） | 阶段的时刻：run.json 的 `phase_log`（`[名字, t_us, 来源]`，来源用 `start` / `sh` / `hook`），或者至少 `phases[].t_us`；时间轴终点：`duration_s` 或 span | `clock` |
| **时间顺序**、在时间条上拖时间段（`@t=`） | `events/spans/` 的 index.json（`chunks`）、keys.json（`keys`）、`p*.jsonl.gz`；run.json 的 `events` 不为 null 且没有 `error`（页面按它决定开不开放）；按阶段看时间顺序还要这个阶段在 `phase_log` 里有时刻 | index.json 的 `truncated`、`procs`；keys.json 的 `threads` |

写键时要注意（叠加的正确性全靠它）：

- **行号必须和扫描端的符号对得上**：等于符号的 `l` 或 `dl`（或 `a` 里的另几个 def），否则次数只落到文件和单元上、不落到函数上（`anon`）。
- **行号 0 专留给「模块 / 文件顶层的执行」**，行号等于扫描端标了 `defexec` 的符号（Python 的类）的定义行会被当成类体执行：这两种都**不算调用**，
  指向它们的边不画成调用边。一种语言里如果「构造」就发生在类定义那一行（比如构造函数没有自己的定义行），录制端要把键记到构造函数自己的行上，
  否则所有实例化都会被当成定义丢掉（未核实：目前没有别的语言，这条是按 `analysis.defining` 的规则推出来的）。
- `rel` 是相对 `CODESTRATA_ROOT` 的路径，和扫描端 `files` 的键逐字一致（大小写、`/`）。
- 调用方取「栈上最近的仓库帧」：穿过标准库 / 第三方库 / 框架事件循环的调用，要记到最近的仓库函数头上。这决定了图上的边是不是真的。
- `file_shas` 用 §0 的 `sha16`，和扫描端的 `file_sha` 同一种算法。

### 9.3 扫描端要产出的静态索引

scan 写 index.json 和 symbols.json，加载时（`ui.load.load_index`）合成一个 index；另有 xref.json（跳转）和 graph.json（调用）。下表是叠加、图、切面实际读到的字段
（`ui/`、`align.py`、`layout.py`、`cut.py`、`seq.py`、`runs.py`、`trace/` 里查过）；其余的只给冻结区（代码窗口、交叉引用）用。

**index.json**

| 字段 | 形状 | 谁读 | 用途 | 必 |
|---|---|---|---|---|
| `format` | int | `ui.load.load_index`、`ui.load.index_summary` | 索引的格式版本（`cut.INDEX_FORMAT`，现在是 5：id 按路径、符号键 `<路径>#<限定名>`、有 graph.json，graph.json 有 `ctors`）；不一样的旧索引要重新 scan | 是 |
| `repo` | {root, name, roots, n_files, n_parse_errors, unresolved_imports, n_aux, auto_split} | `ui.graphview.graph_payload`（整个传给前端：页头用 `name`，页脚用 `roots`、`n_files`、`n_parse_errors`）、`ui.load.index_summary`（主菜单卡片、trace 的默认 roots）、`auto_split` 给前端 | 仓库信息 | 是（至少 `name`、`roots`、`n_files`、`n_parse_errors`） |
| `packages` | {单元: {files, loc, classes, funcs, out, in, alt, label?, sep?}} | `cut.view`（按切面相加 `files`、`loc`、`classes`、`funcs`）、`cut.default_open`（`loc`）、`layout.build`（过滤掉 `files` < min_files 的、既没符号也没边的空单元）、`cut.members`；`label` / `sep` 给 `cut.label`（显示名） | 单元（节点的最小粒度）。**id 是文件相对仓库根的路径**（`fakesvc/offline.py`）。`label` 是显示名、`sep` 是它的分隔符：Python 是点分的模块名（`fakesvc.offline`，包的 `__init__.py` 是 `<包>.__init__`）和 `.`；不给就按路径切 | 是（`label` / `sep` 否） |
| `edges` | [[单元a, 单元b, 权重]] | `cut.view`（出入度）、`layout.build`（分层、横向排序、画不画） | import 关系（Python 是 import 条数） | 是（可以是空列表） |
| `dirs` | {目录: {parent, dirs, units, label?, sep?}} | `cut` 几乎所有函数（节点归属、展开、框） | 目录树。**目录 id 是路径加 `/`**（`fakesvc/`），仓库根目录直接放着的脚本在 `./` 里；「本层文件」节点是 `<目录>*`。可以直接用 `cut.dir_tree(packages, roots)` 生成：单元所在目录 = 去掉文件名；目录的显示名从单元的推（单元显示名去掉最后一段）。每个单元的目录都必须在树里 | 是 |
| `default_open` | [目录] | `cut.norm_open`、`seq._Map`、`serve` | 默认切面（展开哪些目录和本层文件节点）。可以用 `cut.default_open(index)[0]` 算 | 是 |
| `n_symbols` | int | `ui.load.index_summary` | 主菜单显示 | 否 |

**symbols.json**（index 里的大块，按需加载）

| 字段 | 形状 | 谁读 | 用途 | 必 |
|---|---|---|---|---|
| `files` | {rel: 单元} | `align.to_package_graph` / `remap`、`runs.file_state`、`seq._Map`、`ui.graphview`（每个节点的文件列表） | **叠加的枢纽**：录制端的 `rel` 靠它落到单元上 | 是 |
| `symbols` | {符号键: {n, s, k, f, l, lang, m?, p, dl?, e?, b?, d?, a?, x?}} | `align.sym_locs` / `defining`（`f`、`l`、`dl`、`e`、`a`、`x`）、`align.remap`（`f`、`n`、`l`、`dl`）、`ui.graphview`（`n` 不含点的顶层符号：`n`、`k`、`f`、`l`、`b`、`p`）、`--phase` 的解析（`m`） | **符号键是 `<文件路径>#<限定名>`**（`fakesvc/offline.py#Engine.generate`；不拿冒号分，C++ / Rust 的限定名里有 `::`）。`n` 限定名、`s` 它的最后一段、`k` 是 `class` / `func`、`f` 文件、`l` 定义行、`lang` 语言、`dl` 第一个装饰器行（和 `l` 不同时才有）、`e` 末行（闭包归到外层符号用）、`m` 点分模块名（Python）、`p` 所属单元、`b` 基类、`d` 装饰器名、`a` 同名的另几个 def `[[行, 装饰器行, 末行]]`、`x` 标记（`defexec`：落在它定义行上的帧是定义时的执行，Python 的类体） | 是（没有它只能叠到单元，函数级明细和类体判断都没了） |
| `file_sha` | {rel: sha16} | `runs.file_state` | 录制后哪些文件改过 | 强烈建议（没有时退回和工作区比） |
| `name_refs`、`docs`、`aux`、`file_loc` | | 按名字接线的地方（`align.wiring`）、文档、非 Python 源文件、行数 | 面板和冻结区 | 否 |

**graph.json**（graph 的 scan 记录：函数之间的调用。由 `graph.Builder` 在 `xref.build` 的同一遍里产出；`ui.load.load_index` 读进 `idx["graph"]`，图上的边和 scan-trace alignment 都靠它。
**必需**：没有它图上一条边都没有，trace 到的调用全算成只有 trace）

| 字段 | 形状 | 用途 | 必 |
|---|---|---|---|
| `format` | int | 同 index.json | 是 |
| `callees` | [符号键] | 被调方，`calls` 里按下标引用 | 是 |
| `calls` | {调用方: [[被调方下标, 行, 末行, 种类]]} | 定下了被调方的调用 | 是 |
| `sites` | {调用方: [[名字, 行, 末行, 种类]]} | 定不下被调方的调用处：名字是写的那个（`x.m(…)` 的 `m`；语法触发的是特殊方法名；`f()()` 这种没有名字的是 null） | 是 |
| `ctors` | {类: [方法符号键]} | 构造过的类（种类 1 的被调方）构造时跑到的仓库里的方法：Python 是沿 MRO 各取第一个 `__new__` / `__init__` / `__post_init__`（dataclass 生成的 `__init__` 不在仓库里）。`[]`：构造时跑的代码都不在仓库里，trace 看不到（边详情里标出来，不说「没录到」） | 是 |

调用方是符号键，另有三种符号表里没有的：`<文件路径>#<module>`（模块顶层的代码）、`<外层>.<L行>`（lambda、生成器表达式：运行时是单独的帧）；
类体里的代码记在类自己身上，列表 / 集合 / 字典推导式算外层（3.12 起它们不是单独的帧）。行、末行是调用那个表达式占的行。
种类：0 调用、1 构造（被调方是类）、2 装饰器（`@x` 在定义时调 `x`）、3 用 property（读、赋值、`del` 调 getter、setter、deleter）、4 语法触发的特殊方法（`with`、`for`、`[]`、运算符、`len()` 这类，
只记仓库里有类定义过的）、5 `getattr(…, "名字")`、6 调的是仓库外的。

`layout.build` 读的 `frames`、`alias` 不是扫描端的：是 `ui.graphview.graph_payload` 按切面现算、塞进给 layout 的那个字典里的。

## 附：本页核对过的真实数据

- `vllm-omni/.codestrata/runs/20260929-180408-run_single_prompt/`：run.json、detail.json、counts.json.gz、`parts.tar.gz`
  （32 个成员：`PHASE`、两个 `.fired`、`part-*` 和它们的 `@n-阶段` 快照）、`events/raw.tar.gz`（4 个 `ev-*.log`）、`events/spans/`（4 块）。
- 测试用的假仓库（`tests/trace_cases/fake_repo`）上的 `fake_service.sh`（case 脚本切阶段）和 `fakesvc.offline`（`--phase` 切阶段）两次录制，
  以及 §9.1 里接法 A、B、C 的三个模拟 run（在临时目录里做的，没有进仓库）。
