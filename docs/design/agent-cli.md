# 给 agent 的命令行（契约）

codestrata 的读命令是给 AI agent（也给人）用的：输入一个 REF，输出先汇总、末尾给能原样粘贴的下一步。
这一页写的是稳定的部分——REF 的写法、列的写法、JSON 信封、错误码和退出码、每个命令的副作用（effect）。
`codestrata guide` 打出的是同一份内容的速查版。

- 以代码为准：`codestrata/ref.py`（REF 的语法，不碰文件）、`locate.py`（对上仓库和 run）、`laneid.py`（列的写法）、
  `errors.py`（错误码）、`cmdline.py`（下一步的命令怎么拼）、`cli/`（命令表、信封）。本页和代码对不上时以代码为准，并改本页。
- 信封带版本号 `v`（现在是 1）。字段只加不改；要改含义时升 `v`。

## REF

```
REF   := 页面地址 | RUN [ "@" 范围 ] [ "/" 列选择器 { "," 列选择器 } ]
RUN   := 完整 run id | case 名
范围  := 阶段名 | "t=" 起 "-" 止 | 阶段名 "+" 秒 "s-" 秒 "s"
```

- **RUN**：完整 run id，或 case 名（取它最新一次 ok 的；没有就取最新的 partial）。不收 run id 前缀（前 8 位是日期，同一天的会撞），
  写错时以它开头的完整 id 会列进候选。
- **范围**：
  - 阶段名：按这个 run 里实际有的阶段名做最长匹配；
  - `t=起-止`：从 run 起点算的整数微秒，也收 `t=78.024s-80.492s`；
  - `阶段+起s-止s`：从阶段开头算的秒，比如 `serving+0.614s-3.082s`，不能超出这个阶段。
  - 省掉就是整个 run。多片（`t=a-b,c-d`）还不支持。
  - 页面、`serve --hot`、老命令（`runs.resolve`）认同一套范围写法；页面收超出 run 终点的时间段（时间条放长、照样画选中框），不报越界。
- **页面地址**：浏览器地址栏里那串，比如 `http://127.0.0.1:8900/#run=<RUN>@<范围>&lanes=stage1`。
  主菜单转发的 `/v/<端口>/` 也认。`lanes=` 是列选择器，别的键原样留着。地址后面不能再接 `/列`。
- **输出里只给规整过的 REF**：`<完整 id>@<阶段>` 或 `<完整 id>@t=起-止`（阶段 + 秒的写法规整成 `t=`），带列时后面是 `/列,…`。
  列对着整个 run 的列核对过：大小写不同、写重了的合成一个标准写法；一列都对不上的报 `lane_not_found`（没录时序事件的 run 核对不了，给警告 `lanes_unchecked`）。

### 仓库怎么找

依次是：
1. `-C 目录`：从这个目录往上找最近的 `.codestrata/`（像 `git -C`）；往上都没有时，`status` 照样看这个目录（还没 scan），别的命令报 `repo_unknown`；
2. 页面地址：问那个端口上的 serve（`GET /api/app` 回 `repo`、`pid`、`port`）；它开的仓库里要真有这个 run，否则给警告 `page_mismatch`、按下面的办法找；问不到给警告 `page_unknown`；
3. 完整 run id：在主菜单记得的仓库（`$XDG_CONFIG_HOME/codestrata/projects.json`）里唯一找到的；
4. 从当前目录往上找第一个有 `.codestrata/` 的目录。

- 不是从当前目录找到的，输出里的每条下一步都带 `-C <仓库>`。
- 当前目录的仓库里没有这个 run、别的已知仓库里有时：完整 run id 就用那个，并给警告 `repo_from_run`；case 名不自动换仓库，
  `run_not_found` 的说明里写哪个仓库有、下一步给 `status -C <那个仓库> <原来的 REF>`。
- `repo_unknown` 的候选是主菜单记得的仓库，下一步每个给一条 `status -C …`（带着原来的 REF）。
- `-C`、`--json` 写在子命令前面也认（`codestrata -C 仓库 --json status`）；`runs` 的 `-C` 也可以写在动作后面。

## 列的写法

- **进程别名**：
  - 先去掉扩展名和 `-m `，再去掉同一族进程（名字第一个词相同）共有的开头和结尾几个词，然后取从左往右最短的、能唯一认出它的前缀。
  - 例：`StageEngineCoreProc_stage1_replica0_DP0` → `stage1`；两个副本时是 `stage1_replica0`、`stage1_replica1`；`end2end.py` → `end2end`。
  - 名字完全一样的几个进程，各加 `-<pid>`。
- **列别名**：`进程别名/线程`。
  - 线程名先归一：`Thread-3 (save_loop)` → `save_loop`，`worker-0` → `worker`。
  - GPU 的列写成 `gpu<设备>.<流>`，比如 `stage1/gpu0.7`。
  - `[A-Za-z0-9._-]` 以外的字符换成 `_`，撞了加 `-2`。
  - 按整个 run 登记过的全部线程算一次（`lanes.run_aliases`），和时间段无关：同一个 run 里同一列的写法处处一样。
- **选择器**：
  - `进程/线程`；`进程`（这个进程的所有列）；`进程/*`、`*/线程`、`*/gpu*`；也认页面内部的列 id `pid:线程`。
  - 不分大小写，按整段匹配：`stage1` 不配 `stage10`，`stage1/Main` 不配 `stage1/MainThread`。

## 输出

- **文字**（默认）：给模型读。先汇总；时刻写成 `+秒`，基准写在第一行。
  - 默认有上限，超了写「给了 N / 共 M」和要更多的命令。
  - 末尾「下一步」每条都是能原样粘贴的命令（每个参数按 shell 规矩加好引号），后面写它的 effect。
  - 警告以 `⚠` 开头，有下一步的写在后面。
- **`--json`**：stdout 上只有一个 JSON。

```json
{"v": 1, "ok": true, "cmd": "lanes", "repo": "/path/to/repo",
 "ref": {"text": "<id>@serving/stage1", "slices_us": [[77409947, 81828750]], "lanes": ["stage1"]},
 "data": {}, "more": null, "warnings": [{"code": "…", "msg": "…", "next": {"cmd": "…", "effect": "read"}}],
 "next": [{"cmd": "codestrata …", "effect": "read", "why": "…"}]}
```

- 按规则推算的命令（以后的切段）另有 `algo`（算法版本）。
- 出错时 stdout 上仍然只有一个 JSON：`{"v": 1, "ok": false, "cmd": …, "error": {"code", "msg", "candidates"}, "warnings": […], "next": […]}`。
  `warnings` 是出错之前已经有的（比如页面地址问不到）。不带 `--json` 时错误写到 stderr。
- 意外的异常（codestrata 的 bug）带 `--json` 时也只在 stdout 给一个信封（`internal`，退出码 1），堆栈写到 stderr。
- argparse 的用法错，带了 `--json` 时 stdout 也给信封（`code` 是 `usage`，`cmd` 是敲的命令，比如 `runs show`），退出码 2。
- **时刻**：JSON 里一律是从 run 起点算的整数微秒，字段名以 `_us` 结尾。例外：`path` 的 `data` 和页面的 `/api/path` 同形，
  那里的 `window`、`t`、`first` 也是从 run 起点算的微秒，只是没带 `_us`。
- **run 的状态**（`status` 字段）：`ok` / `partial` / `failed` / `recording`（还在录）/ `interrupted`（录制的进程没了，要 `runs merge`）。
  `runs ls` 每行另有 `status_text`（中文，给人看）。
- **阶段**（`phases` 字段）：`[{name, t0_us, t1_us}]`，同一个阶段切走又切回来就有几段；`runs ls / show` 每段多一个 `n_funcs`。

### 警告码

| 警告码 | 什么时候 |
|---|---|
| `partial` | run 只录了一部分（带 `problems`） |
| `interrupted` | 录制中断了，下一步 `runs merge`（write） |
| `recording` | run 还在录，下一步 `runs wait` |
| `newer_recording` | 按 case 名挑到的是录完的那次，同一个 case 有一次更新的正在录 |
| `repo_from_run` | 当前目录的仓库里没有这个 run，用的是别的已知仓库 |
| `page_unknown` / `page_mismatch` | 页面地址那个端口问不到 / 那边开的仓库里没有这个 run |
| `legacy_runs` | 有老格式的录制还没迁进 runs/（读命令不迁；`serve` 起来或下一次 `trace` 时会迁） |
| `lanes_unchecked` | 没录时序事件的 run，REF 里的列没核对 |
| `lane_idle` | 选的列在这段时间里没有活动 |
| `truncated` | 有进程的时序事件录到了行数上限 |
| `need_view` | 页面地址里没有 run（页面只开着静态图） |

## 错误码和退出码

| 退出码 | 错误码 | 什么时候 |
|---|---|---|
| 0 | — | 成功 |
| 1 | `internal` | 意外（老代码里的错误、codestrata 的 bug） |
| 2 | `usage` | 用法错 |
| 3 | `repo_unknown` `run_not_found` `phase_not_found` `bad_window` `window_out_of_range` `lane_not_found` `ambiguous_lane` `item_not_found` `ambiguous_item` | 名字写错，都带候选 |
| 4 | `not_scanned` `index_old` `no_events` `recording` `interrupted_run` `failed_run` `not_loadable` `spans_unreadable` `no_loop` `link_mismatch` `need_view` | 没数据（包括还在录、等录完超时），或推断被拒；`next` 给出能补数据的命令（`runs wait` 是 read，`runs merge`、`scan` 是 write） |
| 5 | `no_live_page` `old_serve` `page_failed` `timeout` `interrupted` `superseded` `refused` | 页面换不了（留给推页面的命令） |
| 6 | `pending` | 页面还没换（等用户） |

范围写错或越界时，候选是这个 run 的各阶段和整个 run 的 `t=0-终点`，都是能直接用的 REF。

## effect

| effect | 命令 | 规矩 |
|---|---|---|
| read | `status`、`lanes`、`path`、`guide`、`runs ls / show / wait` | 随便跑（真的只读：不迁移老文件、不建目录） |
| write | `scan`、`runs tag / untag / note / merge` | 先问用户 |
| delete | `runs rm` | 先问用户 |
| start | `serve`、`app` | 先问用户（起常驻进程、占端口） |
| record | `trace` | 先问用户（跑被录的程序，可能占 GPU、跑很久） |

## 命令

### `codestrata status [REF] [-C 目录] [--json]`
- 不给 REF：仓库、索引什么时候 scan 的（`index.scanned` 是带时区的时刻）、最近 5 个 run 和各自的状态（多于 5 个时 `more` 指到 `runs ls`）。
- 给 REF：run 的状态、问题、有没有时序事件和 GPU、时序事件到没到行数上限；REF 规整成什么、落在哪几片微秒；各阶段的窗口。
- 下一步：还在录的给 `runs wait`；中断的给 `runs merge`；没给范围、有 `serving` 阶段的，`lanes` 建议看 `@serving`。
- `data`：`repo`、`found_by`（`C` / `page` / `run` / `cwd`）、`index`，以及 `runs`（没给 REF）或 `run` + `phases` + `lanes`。

### `codestrata lanes REF [--limit N] [--json]`
- 这段时间里的列，和页面的分列是同一套。每列：别名、进程全名、线程原名、×N、有调用（轮询也算）/ 只做交接 / 这段没调用 / GPU、调用次数、首末时刻。
- REF 里带了列选择器时只列选中的。默认最多 40 列。
- 要求 run 录了时序事件（`no_events`）、录完了（`recording` / `interrupted_run`）。
- `data.lanes[]`：`lane`、`id`、`pid`、`proc`、`proc_name`、`thread`、`thread_names`、`n_threads`、`activity`（busy / idle / external / gpu）、`n_calls`、`first_us`、`last_us`。
- 下一步给调用最多的那一列的 `path`。

### `codestrata path REF [--depth N] [--limit N] [--json]`
- 函数级的请求路径（每个进程、每条线程的调用上下文树）。默认打整棵树；REF 带了列、给了 `--limit` 或 `--json` 时每列截到 60 行（`--limit` 是每列几行，`--depth` 藏掉的不算），截过的列末尾写还有几行，`more` 写一共几行。
- 第一行写这一段的 `t=`，并说明记号：+秒是第一次调用的时刻（从这一段开头算）、×N、「← 文件:行」是调用写在哪一行（经仓库外的代码调进来的是最近的仓库内那一行）、（之前）、↻、[看不出]。
- 节标题是列别名；`--json` 的 `data` 和页面的 `/api/path` 同形，每节多一个 `lane`。老写法 `path <repo> RUN` 也认。

### `codestrata runs [repo] ls | show RUN | wait RUN`
- 文字和 JSON 是同一份数据；RUN 也认页面地址和范围（`show` 会核对）。
- `ls --json`：每个 run 的摘要（和页面的 `/api/runs` 同形）加 `status_text`、`phases`、`end_us`、`bytes`。
- `show --json`：`run`（run.json 原样）、`status`、`phases`、`end_us`、`procs`、`files`、`file_state`、`rerun`（复刻命令）、`dir`。
- `wait RUN [--timeout 600]`：等 run 录完；给 case 名时等这个 case 最新的那一次（正在录的也算）。超时报 `recording`（退出码 4），
  下一步给加倍的 `--timeout`。录制中断的，下一步给 `runs merge`（write）。

### `codestrata trace … --json`
- 被录程序的输出和录制摘要都转到 stderr，stdout 上只有一个信封：`data` 是 `id`、`status`、`problems`、`returncode`、`duration_s`、`phases`、`events`、`gpu`、`summary`、`dir`。
- 录完了但一个函数都没录到：`failed_run`（退出码 4），下一步给 `runs show`。
- trace 是 record：可能占 GPU、跑很久。agent 要先问用户。
- case 脚本写进 `PHASE` 的阶段名里 `[A-Za-z0-9._-]` 以外的字符换成 `_`（阶段名会出现在 REF 和地址栏里；计数和时刻用同一个名字）。

### `codestrata guide [--skill] [--json]`
- 一页速查（≤ 80 行）。`--skill` 打出 Claude Code skill 文件的内容（带 frontmatter），放不放进 `.claude/skills/` 由用户定。
- `--json`：`data.commands` 是命令表（`name`、`effect`、`does`、`usage`、`example`），`data.errors` 是错误码 → 退出码。
