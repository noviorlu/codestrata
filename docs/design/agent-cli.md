# 给 agent 的命令行（契约）

codestrata 的读命令是给 AI agent（也给人）用的：输入一个 REF，输出先汇总、末尾给能原样粘贴的下一步。
这一页写的是稳定的部分——REF 的写法、列的写法、JSON 信封、错误码和退出码、每个命令的副作用（effect）。
`codestrata guide` 打出的是同一份内容的速查版。

- 以代码为准：`codestrata/ref.py`（REF）、`laneid.py`（列的写法）、`errors.py`（错误码）、`cli/`（命令表、信封、引号）。
  本页和代码对不上时以代码为准，并改本页。
- 信封带版本号 `v`（现在是 1）。字段只加不改；要改含义时升 `v`。

## REF

```
REF   := 页面地址 | RUN [ "@" 范围 ] [ "/" 列选择器 { "," 列选择器 } ]
RUN   := 完整 run id | case 名
范围  := 阶段名 | "t=" 起 "-" 止 | 阶段名 "+" 秒 "s-" 秒 "s"
```

- **RUN**：完整 run id，或 case 名（取它最新一次 ok 的；没有就取最新的 partial，并给警告 `partial`）。不收 run id 前缀（前 8 位是日期，同一天的会撞）。
- **范围**：
  - 阶段名：按这个 run 里实际有的阶段名做最长匹配；
  - `t=起-止`：从 run 起点算的整数微秒，也收 `t=78.024s-80.492s`；
  - `阶段+起s-止s`：从阶段开头算的秒，比如 `serving+0.614s-3.082s`，不能超出这个阶段。
  - 省掉就是整个 run。多片（`t=a-b,c-d`）还不支持。
- **页面地址**：浏览器地址栏里那串，比如 `http://127.0.0.1:8900/#run=<RUN>@<范围>&lanes=stage1`。
  主菜单转发的 `/v/<端口>/` 也认。`lanes=` 是列选择器，别的键原样留着。地址后面不能再接 `/列`。
- **输出里只给规整过的 REF**：`<完整 id>@<阶段>` 或 `<完整 id>@t=起-止`（阶段 + 秒的写法规整成 `t=`），带列时后面是 `/列,…`。

### 仓库怎么找

依次是：
1. `-C 目录`；
2. 页面地址：问那个端口上的 serve（`GET /api/app` 回 `repo`、`pid`、`port`）；
3. 完整 run id：在主菜单记得的仓库（`$XDG_CONFIG_HOME/codestrata/projects.json`）里唯一找到的；
4. 从当前目录往上找第一个有 `.codestrata/` 的目录。

不是从当前目录找到的，输出里的每条下一步都带 `-C <仓库>`。当前目录的仓库里没有这个 run、别的已知仓库里有时，用那个，并给警告 `repo_from_run`。

## 列的写法

- **进程别名**：
  - 先去掉扩展名，再去掉同一族进程（名字第一个词相同）共有的开头和结尾几个词，然后取从左往右最短的、能唯一认出它的前缀。
  - 例：`StageEngineCoreProc_stage1_replica0_DP0` → `stage1`；两个副本时是 `stage1_replica0`、`stage1_replica1`；`end2end.py` → `end2end`。
  - 名字完全一样的几个进程，各加 `-<pid>`。
  - 别名按整个 run 算一次，和时间段无关。
- **列别名**：`进程别名/线程`。
  - 线程名先归一：`Thread-3 (save_loop)` → `save_loop`，`worker-0` → `worker`。
  - GPU 的列写成 `gpu<设备>.<流>`，比如 `stage1/gpu0.7`。
  - `[A-Za-z0-9._-]` 以外的字符换成 `_`，撞了加 `-2`。
- **选择器**：
  - `进程/线程`；`进程`（这个进程的所有列）；`进程/*`、`*/线程`、`*/gpu*`；也认页面内部的列 id `pid:线程`。
  - 不分大小写，按整段匹配：`stage1` 不配 `stage10`，`stage1/Main` 不配 `stage1/MainThread`。

## 输出

- **文字**（默认）：给模型读。先汇总；时刻写成 `+秒`，基准写在第一行。
  - 默认有上限，超了写「给了 N / 共 M」和要更多的命令。
  - 末尾「下一步」每条都是能原样粘贴的命令（每个参数按 shell 规矩加好引号），后面写它的 effect。
  - 警告以 `⚠` 开头。
- **`--json`**：stdout 上只有一个 JSON。

```json
{"v": 1, "ok": true, "cmd": "lanes", "repo": "/path/to/repo",
 "ref": {"text": "<id>@serving/stage1", "slices_us": [[77409947, 81828750]], "lanes": ["stage1"]},
 "data": {}, "more": null, "warnings": [{"code": "…", "msg": "…"}],
 "next": [{"cmd": "codestrata …", "effect": "read", "why": "…"}]}
```

- 出错时 stdout 上仍然只有一个 JSON：`{"v": 1, "ok": false, "cmd": …, "error": {"code", "msg", "candidates"}, "next": […]}`。
  不带 `--json` 时错误写到 stderr。
- JSON 里的时刻一律是从 run 起点算的整数微秒，字段名以 `_us` 结尾。
- argparse 的用法错，带了 `--json` 时 stdout 也给信封（`code` 是 `usage`），退出码 2。

## 错误码和退出码

| 退出码 | 错误码 | 什么时候 |
|---|---|---|
| 0 | — | 成功 |
| 1 | `internal` | 意外（老代码里的错误先落在这里） |
| 2 | `usage` | 用法错 |
| 3 | `repo_unknown` `run_not_found` `phase_not_found` `bad_window` `window_out_of_range` `lane_not_found` `ambiguous_lane` `item_not_found` `ambiguous_item` | 名字写错，都带候选 |
| 4 | `not_scanned` `index_old` `no_events` `recording` `interrupted_run` `failed_run` `not_loadable` `spans_unreadable` `no_loop` `link_mismatch` `need_view` | 没数据，或推断被拒；`next` 给出能补数据的命令（比如 `runs merge`，标着 write） |
| 5 | `no_live_page` `old_serve` `page_failed` `timeout` `interrupted` `superseded` `refused` | 页面换不了（留给推页面的命令） |
| 6 | `pending` | 页面还没换（等用户） |

范围写错或越界时，候选是这个 run 的各阶段和整个 run 的 `t=0-终点`，都是能直接用的 REF。

## effect

| effect | 命令 | 规矩 |
|---|---|---|
| read | `status`、`lanes`、`guide`、`path`、`runs ls / show` | 随便跑 |
| write | `scan`、`runs tag / untag / note / merge` | 先问用户 |
| delete | `runs rm` | 先问用户 |
| start | `serve`、`app` | 先问用户（起常驻进程、占端口） |
| record | `trace` | 先问用户（跑被录的程序，可能占 GPU、跑很久） |

## 命令

### `codestrata status [REF] [-C 目录] [--json]`
- 不给 REF：仓库、索引什么时候 scan 的（之后改过几个文件）、最近 5 个 run 和各自的状态。
- 给 REF：run 的状态（ok / partial / failed / recording / 中断）、问题、有没有时序事件和 GPU、截断的进程；
  REF 规整成什么、落在哪几片微秒；各阶段的窗口。
- `data`：`repo`、`found_by`（`C` / `page` / `run` / `cwd`）、`index`、`runs` 或 `run` + `phases`。

### `codestrata lanes REF [--limit N] [--json]`
- 这段时间里的列，和页面的分列是同一套。每列：别名、进程全名、线程原名、×N、在跑 / 只做交接 / 这段没调用 / GPU、节点数、首末时刻。
- REF 里带了列选择器时只列选中的。默认最多 40 列。
- 要求 run 录了时序事件（`no_events`）、录完了（`recording` / `interrupted_run`）。
- `data.lanes[]`：`lane`、`id`、`pid`、`proc`、`proc_name`、`thread`、`thread_names`、`n_threads`、`kind`（busy / idle / external / gpu）、`n_nodes`、`first_us`、`last_us`。

### `codestrata guide [--skill] [--json]`
- 一页速查（≤ 80 行）。`--skill` 打出 Claude Code skill 文件的内容（带 frontmatter），放不放进 `.claude/skills/` 由用户定。
- `--json`：`data.commands` 是命令表（`name`、`effect`、`does`、`usage`、`example`），`data.errors` 是错误码 → 退出码。
