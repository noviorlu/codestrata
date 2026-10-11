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
  - 名字完全一样的几个进程，按启动先后编号：`server-1`、`server-2`（换一次录制，同一个位置上的进程名字还一样）。
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
| `page_unknown` / `page_mismatch` | 页面地址（或 view url 的 `--page`）那个端口问不到 / 那边开的不是这个仓库、或者那个仓库里没有这个 run |
| `legacy_runs` | 有老格式的录制还没迁进 runs/（读命令不迁；`serve` 起来或下一次 `trace` 时会迁） |
| `lanes_unchecked` | 没录时序事件的 run，REF 里的列没核对 |
| `lane_idle` | 选的列在这段时间里没有活动 |
| `no_lanes` | find：没录时序事件，次数不分列 |
| `stale` | explain：讲到的文件录制之后改过 |
| `no_page` | view url：没给页面，只打了 # 后面那一段 |
| `not_on_page` | status：开着的页面上看的不是这个 run（要给用户看，用 `view set` 推过去） |
| `many_requests` / `whole_run` / `lanes_ignored` | segments：一段里可能混着几次请求 / 看的是整个 run（下一步给 `@serving`）/ REF 里的列切段时不用 |
| `truncated` | 有进程的时序事件录到了行数上限 |
| `need_view` | 页面地址里没有 run（页面只开着静态图） |
| `handoffs_empty` | 这段时间里一次交接都没录到（单进程的程序）：空转只能按调用和时长判 |
| `link_unused` / `link_recorded` | links --follow：给的 `--link` 没用上（链没走到 A 列，或者走到时没调 A 函数）/ 这一跳其实录到了，可以不给 |

## 错误码和退出码

| 退出码 | 错误码 | 什么时候 |
|---|---|---|
| 0 | — | 成功 |
| 1 | `internal` | 意外（老代码里的错误、codestrata 的 bug） |
| 2 | `usage` | 用法错 |
| 3 | `repo_unknown` `run_not_found` `phase_not_found` `bad_window` `window_out_of_range` `lane_not_found` `ambiguous_lane` `item_not_found` `ambiguous_item` | 名字写错，都带候选 |
| 4 | `not_scanned` `index_old` `no_events` `recording` `interrupted_run` `failed_run` `not_loadable` `spans_unreadable` `no_loop` `no_handoffs` `link_mismatch` `need_view` | 没数据（包括还在录、等录完超时），或推断被拒；`next` 给出能补数据的命令（`runs wait` 是 read，`runs merge`、`scan` 是 write） |
| 5 | `no_live_page` `old_serve` `page_failed` `timeout` `interrupted` `superseded` `refused` | 页面换不了：没有开着的页面 / 老 serve / 页面换不过去 / 被后来的一条顶掉 / 撤不了；`next` 给 `view url`（把地址交给用户） |
| 6 | — | `view set`：推过去了、页面还没换（`data.state` 是 deferred / queued / offered / sent，`ok` 仍是 true）；`next` 给 `view wait --for applied` |

范围写错或越界时，候选是这个 run 的各阶段和整个 run 的 `t=0-终点`，都是能直接用的 REF。

## effect

| effect | 命令 | 规矩 |
|---|---|---|
| read | `status`、`lanes`、`segments`、`steps`、`links`、`find`、`explain`、`view url / get / wait`、`path`、`guide`、`runs ls / show / wait` | 随便跑（真的只读：不迁移老文件、不建目录） |
| page | `view set`、`view back` | 用户这句话本身就是「要看 / 只看 / 标出 / 选中 / 聚焦」时直接推，回复里说怎么撤销（浏览器后退或 `view back`）；其余情况先问 |
| write | `scan`、`runs tag / untag / note / merge` | 先问用户 |
| delete | `runs rm` | 先问用户 |
| start | `serve`、`app` | 先问用户（起常驻进程、占端口） |
| record | `trace` | 先问用户（跑被录的程序，可能占 GPU、跑很久） |

## 命令

### `codestrata status [REF] [-C 目录] [--json]`
- 不给 REF：仓库、索引什么时候 scan 的（`index.scanned` 是带时区的时刻）、最近 5 个 run 和各自的状态（多于 5 个时 `more` 指到 `runs ls`）。
- 给 REF：run 的状态、问题、有没有时序事件和 GPU、时序事件到没到行数上限；REF 规整成什么、落在哪几片微秒；各阶段的窗口。
- 开着的页面（这个仓库能推视图的 serve 的标签页）各在看什么；给的 REF 不是页面上那个 run 时警告 `not_on_page`。
- 下一步：还在录的给 `runs wait`；中断的给 `runs merge`；没给范围、有 `serving` 阶段的，`lanes` 建议看 `@serving`。
- `data`：`repo`、`found_by`（`C` / `page` / `run` / `cwd`）、`index`、`pages`（`port`、`pid`、`tabs`、`default`），以及 `runs`（没给 REF）或 `run` + `phases` + `lanes`。

### `codestrata lanes REF [--limit N] [--json]`
- 这段时间里的列，和页面的分列是同一套。每列：别名、进程全名、线程原名、×N、有调用（轮询也算）/ 只做交接 / 这段没调用 / GPU、调用次数、首末时刻。
- REF 里带了列选择器时只列选中的。默认最多 40 列。
- 要求 run 录了时序事件（`no_events`）、录完了（`recording` / `interrupted_run`）。
- `data.lanes[]`：`lane`、`id`、`pid`、`proc`、`proc_name`、`thread`、`thread_names`、`n_threads`、`activity`（busy / idle / external / gpu）、`n_calls`、`first_us`、`last_us`。
- 下一步给调用最多的那一列的 `path`。

### `codestrata segments REF [--all] [阈值…] [--json]`
- 按功能切段：请求（`--phase` 的那个函数和这段时间相交的每一次调用）、每个进程每一块干活的时间（stage 段，按开始的先后编号，各给一个 REF）、
  段之间录到的跨进程交接（组的写法 `l:handoff|通道|起列|终列`）、缺口、只在轮询的背景列、有调用却没出段的进程。判法见下面「切段」。
- 持有请求的进程不出段（用「请求」那一行代表；`--all` 也出）；只有一个进程在干活的程序（单进程的脚本），段就是这段时间里它主循环的全部轮。
- 每段写最长的那一轮（轮号、时长、占这段多少）；附近只有一轮前景的零星几块记在段上（`stray`），不单出段。
- 警告：这段时间里有几次请求（`many_requests`：一段里可能混着几次请求；阶段函数只调了一次、开头却交出去好几次时也给，标明是按交出去的次数推的）；看的是整个 run、run 又有 `serving` 阶段（`whole_run`，下一步给 `@serving`）；
  REF 里带了列（`lanes_ignored`：切段看所有进程）；一次交接都没录到（`handoffs_empty`）；时序事件录到了上限（`truncated`）。
- `data`：`requests[]`、`segments[]`（`id`、`kind`、`proc`、`main`（主循环那一列）、`lanes`、`busy_lanes`、`slices_us`、`dur_us`、
  `rounds`（`first`、`last`、`n`、`fg`、`out`、`head`、`median_us`、`longest`）、`stray`、`routine_word`、`evidence.own_files`、`gaps`、`truncated`、`ref`）、
  `unsegmented[]`（`proc`、`lanes`、`calls`、`busy_us`、`first_us`、`last_us`）、`handoffs[]`、`handoffs_in_process`、`background`、`basis`（用的阈值）；信封带 `algo`。
- 段的名字（thinker、talker）不给：agent 看 `own_files` 自己叫、说明依据。

### `codestrata steps REF/列 [--head FN] [--with FN] [--round K[-M]] [--list] [--limit N] [--why] [阈值…] [--json]`
- 一列的主循环一轮轮。REF 要正好选中一列（写成进程报 `ambiguous_lane`，候选是这个进程的列）。
- 轮头在 REF 所在的那个阶段上认、轮号在整个 run 上数：REF 是阶段里的一小段时，轮头和轮号不变，REF 只决定列出哪几轮。
  默认按「这一轮多调了什么 + 是不是超长」分组，每组给中位、p90、最长的那一轮、轮号；超长的轮各给 REF。
- `--with FN`：只列调过 FN 的轮（任意深度）。`--list`：逐轮。`--round K-M`：只看这几轮。
- `--why`：选中的那几轮里（一轮一轮算再加起来）每个函数「自己的时间」（时长减去它直接调的仓库函数；挂起过的 async 调用时长含挂起，不算它自己的），
  加上「不在这几轮的任何调用里」的时间（循环本身、仓库外的代码，或者在等）。没录 GPU 的 run 提示 GPU 时间算在发起它的 Python 函数里。
- 下一步：最长那一轮的 `--why` 用原来的 REF 加 `--round K`（拿那一轮的时间段当 REF 会换一个循环）。
- 函数的写法（`--head`、`--with`）：`路径#限定名`、限定名、唯一的名字；对不上 `item_not_found`、对上几个 `ambiguous_item`，都带候选。
- 认不出主循环报 `no_loop`，候选是这一列调得最多的函数（拿来给 `--head`）。

### `codestrata links REF [--kind handoff|spawn|join|launch|all] [--list] [--limit N] [--follow 起点 [--link 'A列:FN => B列:FN' …]] [--json]`
- 列之间的连线（和页面的分列同一套），按（种类, 通道, 起列, 终列）合成组，id 是 `l:种类|通道|起列|终列`（和 `explain` 讲的是同一份组；
  页面上画的一条再加 `|起节点|终节点`，页面的选中和时间顺序编号都这么写，`explain` 也认）；
  每组给次数、首末时刻、两头的（函数, 行）有几种、次数最多的那种；放 / 取在仓库外的代码里时，函数是当时栈底的仓库函数（标出来）。
  `--list` 每组列出各种两头（`#k`，`explain '组#k'` 讲第 k 种）。默认只看 handoff，最多 20 组。
- `data.links[]`：`id`、`kind`、`via`、`from`、`to`、`n`、`first_us`、`last_us`、`cross`、`pairs[]`（`from` / `to`：`fn`、`file`、`line`、`outside`；`n`、`first_us`）、`n_pairs`。

**`--follow 起点 [--link 'A列:FN => B列:FN' …]`：顺着交接走一条链**（`chain.py`，信封带 `algo` `chain/1`）
- 起点：`列#k`（这一列主循环的第 k 轮，轮号同 `steps`）；`FN#k`（这段时间里第 k 次调用 FN，从 1 数；REF 带了列时只数这几列）；`列:FN#k`（只数这一列的）。
- 在一列里走的是「这一份」：从进来（起点：那一轮 / 那次调用开始；之后：收到的那一刻）到同一路的下一份进来之前（起点：这一轮结束 /
  这一列下一次调用 FN；录到的交接：同一组的下一次收到；`--link`：B 边的下一次调用）。这期间：
  1. 有 `--link` 的 A 边是这一列：A 函数这期间第一次调用（正包着收到那一刻的也算）是这一列的第 j 次，就跳到 B 列 B 函数的第 j 次；
  2. 否则跟这一列这期间第一次交出（录到的交接）；
  3. 都没有就停下。
- 每一跳写明依据（`basis`）：录到的是 `recorded`，`--link` 配的是 `order`。在一列里从进来到交出（`stay`）：交出就在起点那次调用 / `--link` 落到的那次调用里面、
  或者 A 函数那次调用包着收到的那一处的是 `ancestor`，其余是 `time`（进来之后、下一份进来之前的第一次）。
- `--link`：没录到的一跳（共享的 dict / deque、管道……）要 agent 读过代码后显式给，可以给几次。这段时间里 A 边第 k 次调用配 B 边第 k 次；
  两边次数不等、或者有一次 B 早于同一次的 A，报 `link_mismatch`（退出码 4），候选是 B 列里配得上的函数。两头要是两列。
  攒批的一跳（25 个 token 攒成一块）配不上，从攒好的那一块起走。
- 停下（`stop.reason`）：`none`（这期间没交出，也没有用得上的 `--link`）、`range`（收到的那一刻出了这段时间）、`hops`（走了 40 跳）。
  `none` 时给这一列下一次交出（时刻、通道、到哪列，`basis` 是 `time`：不一定是同一份数据，不往下走）和 `--link` 的候选：
  A 边是这一列这期间跑的函数（`per_item`：一份一次），B 边是同一个进程里（不够再别的进程）接下来先干活的几列各自先跑的函数（空转、在等的轮里的和常规的不算），
  和挑出来的 A 函数次数一样、每次都不早于它的标 `fits`；有的话拼一条能直接用的 `--link`（下一步给加上它的命令）。
- 走出来的链是一个段（`kind: chain`）：每一列待的那段时间（几片，相隔不到 1 ms 的合起来；最后一列取收到之后 1 ms）× 经过的列，带 `ref`，下一步给 `view set`。
- `data.chain`：`start`（`kind` call / round、`lane`、`fn`、`k`、`n`、`k_lane`、`n_lane`、`t0_us`、`t1_us`）、`hops[]`（`kind` recorded / link、`via`、`group`、`link`、
  `basis`、`stay`、`k`、`n`、`from` / `to`（`lane`、`t_us`、`fn`、`file`、`line`、`outside`）、`recorded_too`）、`stop`（`reason`、`lane`、`t_us`、`until_us`、`next_out`、
  `candidates`（`a`、`b[]`、`link`））、`total_us`、`links[]`（`text`、`a`、`b`、`used`）、`segment`（`kind`、`slices_us`、`lanes`、`ref`）。

### 切段

一列（一个进程里同名的一类线程）的主循环，只用通用的信号认（`steps.py`，`algo` 是 `seg/2`）：
- **轮头**：在 REF 所在的那个阶段里认。在同一个父函数下面（线程根也算一个父函数；同一个函数的几次调用合在一起看），至少调了 `--min-calls`（5）次、
  不是合成一行的连续调用的被调方是候选。先去掉「每轮固定调 2–4 次」的（次数是另一个候选的整数倍，而且相邻两次之间几乎总是正好那么多次），
  再按「同票数 × 次数」挑次数（差不到 10% 算同票），这个次数里第一次最早的是轮头。父函数每次调用里平均调轮头两次以上、父函数的调用又盖不住这段时间一半的，
  是一次调用里面的内层循环，不当主循环。父函数之间取覆盖时间最长的，差不到 10% 取外层的。
- **轮**：第 k 次轮头开始到第 k+1 次开始；最后一轮到最后一次轮头调用结束。一个调用算在哪一轮按它在轮头的父函数下面的那个祖先认（同一条线程上别的 asyncio task 不混进来）；
  交接按它所在的调用归轮。
- **常规**：按一轮调到的函数把轮分类；占够 `--class-share`（5%）的类里，「在仓库函数里的时间」的中位不超过最少那类 `--cheap`（2）倍的是便宜的类，它们调到的函数是常规。
  比的是在调用里的时间、不是墙上时长（定时循环闲着和干活的轮一样长）；不和 run 里别处空闲了多久挂钩。
- **超长**：墙上时长比便宜的那几类轮的中位长 `--long`（5）倍以上。**空转**：只调常规的函数、没有交接、也不超长；一次交接都没录到的 run 叫「常规轮」（分不清空等还是每轮干一样的活）。
  只是长（没多调函数、没交接）、一大半时间不在仓库函数里的轮是**在等**（收数据的线程等超时、阻塞在仓库外取请求）：steps 照样列成超长，切块时不算前景。
- **忙段**：一个进程里几列的前景轮（不空转、也不在等的）合在一起按时刻排，在中间空转超过 REF 所在阶段长度的 `--gap`（0.25）处切开。
- **stage 段**：至少两轮前景、在仓库函数里的时间占这个进程这段前景时间 5% 以上的一块忙段一段（同一个进程可以出几段：先后两次请求、两个进程交替干活）；
  别的（只有一轮、收请求时登记一下的）记成零星的。主循环是这块里前景轮在仓库函数里的时间最多的那一列。
- **缺口**：段开始前后 max(段长 10%, 50 ms) 里没录到别的进程交给它的数据。REF 开始之前它就在忙（范围把开头切掉了）、或者同一个进程之前已经出过段，不报。
- 认不准的形状：每轮都交接一次的循环（心跳、每步上报）不会空转；同名的几条线程合成一列时只认一条线程的主循环；交替得很密的几块会合成一块（调小 `--gap`）。
- 要 2026-10-01 之后录的 run（span 带父亲、录了交接）；老 run 报 `no_handoffs`（退出码 4），下一步给 `lanes`、`path`。
- 阈值都能在命令行上改，用的是哪一套写在 `basis` 里；判法改了时 `algo` 升版本。

### `codestrata find 文字 [REF] [--kind fn|class|file|dir] [--under 目录] [--all] [--limit N] [--json]`
- 按名字找函数、类、文件、目录：不分大小写，`*` 通配（加引号）；顺序是完全一样 > 前缀 > 子串（和页面搜索栏的排序可以不一样）。
- 给了 REF：每个命中给这段时间里被调了几次、在哪几列跑过（各几次、首末时刻；类合它的方法，文件 / 目录合里面的函数），默认只列跑过的（`--all` 全列）。
  没录时序事件的 run 给整个阶段的总数，不分列（警告 `no_lanes`）。
- `data.items[]`：`kind`、`key`（函数 / 类是 `路径#限定名`，文件 / 目录是路径）、`name`、`file`、`line`、`lanes[]`、`n`。

### `codestrata explain 东西 REF [--json]`、`codestrata explain --selected [--page 端口] [--tab ID] [--json]`
- 只给原料，「为什么」由 agent 读代码后说。先写讲什么，再写 REF（也可以 `--in REF`）；只给了 REF 报 `usage`。
- **一组交接** `'l:handoff|通道|起列|终列'`（和 `links` 同一份组；加 `|起节点|终节点` 是页面上画的那一条，`#k` 按这一组 / 这一条编）：这段时间里几次、首末时刻；组里两头的（函数, 行）有哪几种、各几次、第一次在什么时候，
  挑一种讲（默认次数最多的，`'…#k'` 挑第 k 种），从它第一次讲起：两头各写列、函数、那一行的原文、所在分支（按 ast 找：装着它的 if / elif / else 的原文，
  else 时写前面都不成立的那几个条件；中间还套着的 for / with / try 的头；再往外两层分支）、函数的签名和 docstring 第一行；
  放的一头的调用链（span 的父亲，≤ 8 层）；放 / 取在仓库外的代码里时，函数是当时栈底的仓库函数（和页面同一个认法），另给当时这条线程上还没返回的仓库调用
  （有挂起过的 async 调用时标出来：可能是别的 task）；放之前这条线程最近收到的交接（标 `inferred: time`：只是时间上最近）；
  取的一头这段时间里调那个取数函数几次；scan 对「谁调了放 / 取所在的函数」的说法（代码里写明的调用，还是代码里看不出）。现在只讲 handoff。
- **函数**（`路径#限定名`、限定名、唯一的名字）：定义、这段时间里各列的次数、谁调它 / 它调谁（次数、调用行、代码里看不出的标出来）、第一次的调用链和之前最近收到的交接。
  这次没录到的函数退到 scan 的索引：给定义，写「这段时间里没跑过」。
- **类**：定义、它的方法这段时间里合起来在哪几列跑过、各方法的次数、第一次调到它的方法那一刻的调用链、谁构造它。
- **文件 / 目录**（仓库相对路径，目录带结尾的 /）和**页面上的选中写法**（`n:列|节点`、`f:列|框`、`e:列|a|b`，地址栏的 `sel=`）：
  节点 / 文件 / 目录讲这段时间里它里面跑过哪些函数、各几次（写了列只算那一列）；列中的边讲那两个节点之间次数最多的几对函数（按 REF 里页面地址的切面算）。
- **编号**（页面上的 `24`）：按页面地址里的视图算（`explain 24 '<页面地址>'`，地址里要有 `order=1`），和页面上的号牌是同一份（`laneorder.py`）；
  第一行写按哪个视图算、一共几个编号、24 号的稳定写法。只给 RUN 不给地址、或地址里没开时间顺序，报 `need_view`；超出范围报 `item_not_found`。
  编号落在一条交接连线上时只讲页面上画的那一条（那两个节点之间的）；落在列中的一条边上时，讲那一列里这两个节点之间次数最多的几对函数（调用那一行的原文、定义）。
- **`--selected`**：讲用户在开着的页面上选中的那个（`view get` 读出来的 `sel`）：连线组按上面的讲；列中的边讲那两个节点之间的几对函数（按页面的视图算切面）；
  节点 / 框讲这段时间里它里面跑过哪些函数、各几次（给了列只算那一列）。页面上没选中东西报 `need_view`，下一步给 `view wait`。`--page`、`--tab` 同 view。
- 录制之后改过的文件给警告 `stale`（原文可能对不上）。

### `codestrata view url | set | get | back | wait …`
每个动作是一个子命令，`-C`、`--json` 写在动作前后都行。

**`view url [REF|'页面地址'] [--lanes …] [--fold …] [--mark …] [--expand …] [--focus 东西] [--select 东西] [--order on|off] [--hide …] [--path] [--page 端口]`**（read）
- 拼出一个视图的页面地址，不推。用户粘进浏览器地址栏（同一个标签页也行），页面不刷新就换过去；后退回到原来的。地址单独一行、不加引号（原样交给用户）。
- REF 定 run、范围和列；给的是页面地址时在它的视图上改（没给的选项沿用地址里的）。前缀取页面地址的，或 `--page 端口`（核对那个端口上是不是这个仓库的 serve：
  不是给警告 `page_unknown` / `page_mismatch`）；都没有时只打 `#…` 那一段（警告 `no_page`）。`--select 函数` 先在选中的那一列里展开到它的文件。
- 列选择器只认 `*` 通配（页面一样）；地址里只看的列在这一段里一列都对不上时，页面和编号都当没选（画全部列，页面提示一句）。
- `--focus 东西`：只看它跑过的列 + 在这些列里把切面展开到它的文件 + 标出它 + 选中它在最早那一列里的那一份。`--expand` 在它跑过的每一列里展开。
- `--mark`：标出这些文件 / 目录 / 函数所在的节点，只在它这段时间里跑过的列里（最多 20 个，页面工具栏「标记 N 个 · 清掉」）；`+东西` 是追加，`none` 清掉。`--select none` 取消选中。
- `data`：`url`、`fragment`、`view`（各个键）。

**`view set [REF] [和 url 一样的选项] [--note 一句话] [--reset] [--page 端口] [--tab ID] [--timeout 秒]`**（page）
- 推给开着的页面：页面先在图上出一层「agent 接手」的过渡，再按固定顺序套上（同粘地址），进浏览器历史（后退就是撤销；2 s 内连着推的合成一条），
  出横幅「agent 换了视图：<note> · 撤销 · 跟随 agent」，8 s 后缩成小签。
- REF 给了就按它定 run、范围和列；没给沿用页面现在的。REF 以外的键（收起、切面、各列切面、标记、选中、开关、详情栏）没给时沿用页面现在的；换了 run 时选中和各列切面清掉；`--reset` 全部从缺省开始。
- 页面怎么收：用户正在操作（按着鼠标，或 1.2 s 内按过键 / 滚过轮；输入框里打字不算）时等他松手约 1 s 再换，最多等 10 s、之后改成提示条问；
  「跟随 agent」关着（页面上的开关，默认开）时出提示条「agent 想换到：… · 换过去 · 不用」；标签页在后台时回来才换，只换最后一条。
- 等页面回话最多 `--timeout`（缺省 3 s），回当时的状态：`applied`（退出码 0）；`deferred` / `queued` / `offered` / `sent`（退出码 6，`next` 是 `view wait --for applied`）；
  `failed`（`page_failed`）、`superseded`（被后来的一条顶掉）退出码 5。
- 输出：状态、哪个端口哪个标签页（用户正看着 / 看得见没焦点 / 在后台）、这个视图是什么、撤销的办法、地址。`data`：`state`、`v`、`tab`、`url`、`fragment`、`port`。

**`view get [--page 端口] [--tab ID]`**（read）：用户此刻看的标签页（缺省是看得见的里面最近有焦点、或用户动过的那个）——视图描述、最后是谁改的
（`boot` / `user` / `url` / `history` / `agent`）、编号一共几个、agent 最近推的一条和它的状态；同一个 serve 上别的标签页各一行。选中着东西时下一步给 `explain --selected`。

**`view back [--page 端口] [--tab ID] [--timeout 秒]`**（page）：撤销 agent 最近推的那一步（页面后退一条历史）。agent 还没推过、或者那之后用户自己改过视图，报 `refused`（退出码 5）。

**`view wait [--for select|range|lanes|any|applied] [--timeout 60] [--page 端口] [--tab ID]`**（read）：等用户在页面上改。缺省等选中变化（配「点一下你想问的那条线」）；
`applied` 等 agent 最近推的那一条换好。超时不算错：`data.changed` 是 false，退出码 0。等到了选中时下一步给 `explain --selected`。

**找页面**：给了页面地址（REF）或 `--page 端口` 就问那个端口；否则读这个仓库的 serve 登记（配置目录下 `serves/<端口>.json`，serve 起来时写、退出时删，进程不在的查找时删），
再问一次 `/api/app` 核对仓库和 pid。都没有报 `no_live_page`；serve 是能推视图之前的版本（`/api/app` 的 `features` 里没有 `view`）报 `old_serve`；两种的下一步都是 `view url`（把地址交给用户）和起一个 serve（start，先问用户）。

### 视图描述（页面地址 # 后面）

`run=RUN@范围 & lanes=选择器,… & fold=进程,… & cut=目录,… & lcut=列~目录,目录;列~… & sel=选中 & mark=东西,… & order=1 & hide=hot,dyn & panel=path`

- 页面和命令行同一套（`web/view.js`、`viewspec.py`）。值里 `@ , / ~ | : ; + * =` 不转义；不认识的键原样留着。
- `lanes`：只看这几列，没选的列每个进程收成一窄列「其他 N 列」，连线照接；`fold`：收起的进程（别名）；`cut`：共用的切面（和默认一样不写）；
  `lcut`：各列自己的切面（列别名 ~ 展开着的目录）；`sel`：选中的（`n:列|节点`、`f:列|框`、`e:列|a|b`、`l:种类|通道|起列|终列`；模块图上 `n:节点`、`e:a|b`）；
  `mark`：标记；`order=1`：时间顺序开；`hide`：藏起的边；`panel=path`：详情栏讲请求路径。
- 页面上每改一处，地址按规范写法重写（不多出历史记录）；粘进来的地址、后退按固定的顺序套：run 和范围 → 切面 → 各列的切面 → 只看列和收起 → 开关 → 标记 → 选中 → 详情栏。
  地址里阶段写错，退回这个 run 默认的阶段并提示；run 找不到，照旧看现在的并提示。

### `codestrata path REF [--depth N] [--limit N] [--time] [--unseen] [--json]`
- `--time`：先列出这几列里「自己的时间」最多的 5 处（和 `steps --why` 同一个算法，按函数合；`data.self_time`）。
- `--unseen`：只列代码里看不出会调到它的调用，按次数排（`data.unseen`，不打树）；先在整棵树里筛再截，`--limit` 在这里是列几处（默认 40）。
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
