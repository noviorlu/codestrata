# 给 agent 的命令行

codestrata 的读命令是给 AI agent（也给人）用的：输入一个 REF，输出先汇总。人看页面，agent 读这几条命令，再把页面地址交给人。

- 以代码为准：`codestrata/ref.py`（REF 的语法，不碰文件）、`locate.py`（对上仓库和 run）、`laneid.py`（列的写法）、
  `errors.py`（错误码）、`cli/`（命令表、信封）。本页和代码对不上时以代码为准，并改本页。

| 命令 | 做什么 |
|---|---|
| `status [REF]` | 仓库、索引、run 的状态、各阶段的时间、这段时间里有哪几列（进程 · 线程）、开着的页面；不给 REF 列最近 5 个 run |
| `links REF [--limit N]` | 列之间谁把数据交给谁，按第一次的先后排，两头的函数和那一行 |
| `links REF --follow 起点 [--link 'A列:FN => B列:FN' …]` | 顺着交接走一条链 |
| `explain 函数 REF` | 一个函数：定义、在哪几列跑过、谁调它、它调了谁（代码里看不出的标出来）、启动了哪些 GPU kernel |
| `path REF [--depth N] [--limit N] [--time] [--unseen]` | 函数级的请求路径：每个进程、每条线程的调用上下文树 |
| `view url / set / get / back / wait` | 拼页面地址；和开着的页面打交道（推视图、读用户在看什么、等用户点） |
| `runs [repo] ls / show RUN` | 列出 run、看一个 run 的详情和复刻命令 |

## REF

```
REF   := 页面地址 | RUN [ "@" 范围 ] [ "/" 列选择器 { "," 列选择器 } ]
RUN   := 完整 run id | case 名
范围  := 阶段名 | "t=" 片 { "," 片 } | 阶段名 "+" 秒 "s-" 秒 "s"
片    := 起 "-" 止
```

- **RUN**：完整 run id，或 case 名（取它最新一次 ok 的；没有就取最新的 partial）。不收 run id 前缀（前 8 位是日期，同一天的会撞），
  写错时以它开头的完整 id 会列进候选。2026-10-01 之前格式的 run 报 `old_run`（`runs show` 还能看它是什么）。
- **范围**：阶段名（按这个 run 里实际有的阶段名做最长匹配）；`t=起-止`（从 run 起点算的整数微秒，也收 `t=78.024s-80.492s`；几片用逗号隔开，
  按先后排好、重叠和挨着的合成一片）；`阶段+起s-止s`（从阶段开头算的秒）。省掉就是整个 run。
  几片的 REF：`status`、`links`、`path` 只算这几片里的调用；`links --follow` 按整段算、给警告 `spanned`。
- **页面地址**：浏览器地址栏里那串，比如 `http://127.0.0.1:8900/#run=<RUN>@<范围>`；主菜单转发的 `/v/<端口>/` 也认。
  老地址里的 `lanes=` 当列选择器，别的键原样留着。地址后面不能再接 `/列`。
- **输出里只给规整过的 REF**：`<完整 id>@<阶段>` 或 `<完整 id>@t=起-止[,起-止…]`，带列时后面是 `/列,…`。
  列对着整个 run 的列核对过；一列都对不上的报 `lane_not_found`（没录时序事件的 run 核对不了，给警告 `lanes_unchecked`）。

### 仓库怎么找

依次是：`-C 目录`（从这个目录往上找最近的 `.codestrata/`，像 `git -C`；往上都没有时 `status` 照样看这个目录，别的命令报 `repo_unknown`）；
页面地址（问那个端口上的 serve 的 `/api/app`；开的是别的仓库给警告 `page_mismatch`，问不到给 `page_unknown`）；完整 run id（在主菜单记得的仓库里唯一找到的）；
从当前目录往上找第一个有 `.codestrata/` 的目录。`repo_unknown` 的候选是主菜单记得的仓库。`-C`、`--json` 写在子命令前面也认。

## 列的写法

- **进程别名**：去掉扩展名和 `-m `，再去掉同一族进程共有的开头和结尾几个词，取能唯一认出它的最短前缀
  （`StageEngineCoreProc_stage1_replica0_DP0` → `stage1`；`end2end.py` → `end2end`）；名字完全一样的按启动先后编号（`server-1`）。
- **列别名**：`进程别名/线程`；线程名先归一（`Thread-3 (save_loop)` → `save_loop`，`worker-0` → `worker`），`[A-Za-z0-9._-]` 以外的字符换成 `_`，撞了加 `-2`。
  按整个 run 算一次，和时间段无关。
- **选择器**：`进程/线程`；`进程`（这个进程的所有列）；`进程/*`、`*/线程`；也认页面内部的列 id `pid:线程`。不分大小写，按整段匹配。

## 输出

- 文字：先汇总，警告在后面（`⚠ …`）；列不全时末尾写「给了 N / 共 M；要更多：…」。
- `--json`：stdout 上只有一个信封 `{v, ok, cmd, repo, ref, data, more, warnings}`；出错时 `{v, ok: false, cmd, error: {code, msg, candidates}, warnings}`。
  意外的异常也是一个信封（`internal`），堆栈在 stderr。信封带版本号 `v`（现在是 1），字段只加不改。

| 退出码 | 错误码 | 什么时候 |
|---|---|---|
| 0 | — | 成功 |
| 1 | `internal` | 意外 |
| 2 | `usage` | 用法错 |
| 3 | `repo_unknown` `run_not_found` `phase_not_found` `bad_window` `window_out_of_range` `lane_not_found` `ambiguous_lane` `item_not_found` `ambiguous_item` | 名字写错，都带候选 |
| 4 | `not_scanned` `index_old` `no_events` `recording` `interrupted_run` `failed_run` `not_loadable` `spans_unreadable` `no_loop` `old_run` `link_mismatch` `need_view` | 没数据，或推断被拒 |
| 5 | `no_live_page` `old_serve` `page_failed` `timeout` `interrupted` `superseded` `refused` | 页面换不了（说明里写怎么用 `view url` 把地址交给用户） |
| 6 | `pending` | `view set`：推过去了、页面还没换 |

## 命令

### `codestrata status [REF]`
- 仓库、索引（什么时候 scan 的、之后改过几个文件）、开着的页面各在看什么。
- 给 REF：run 的状态、问题、有没有时序事件和 GPU；REF 规整成什么；各阶段的窗口；这段时间里的列（和页面的分列同一套）：每列别名、×N（同名线程几条）、
  有调用 / 只做交接 / 这段没调用、调用次数、首末时刻，页面默认收起的写原因（`page_folded`）。`data.page_default`：`{shown, total}`。
  最多列 40 列，REF 里加 `/进程` 只看一个进程。

### `codestrata links REF [--limit N]`
- 交接按（通道, 起列, 终列）合成组、按第一次的先后排；每组写时刻、通道、两头的列、次数，下一行写两头的函数和那一行（一组里两头有几种时写次数最多的那种）。
  放 / 取发生在仓库外的代码里时，写那一刻这条线程栈底的仓库函数。
- `--follow 起点`：顺着交接走一条链。起点写 `FN#k`（这段时间里第 k 次调用 FN）、`列:FN#k`、`列#k`（主循环第 k 轮）；每一跳写录到的还是推出来的。
  走不下去时停下、写原因和候选；`--link 'A列:FN => B列:FN'` 接上一跳没录到的交接（这段时间里 A 边第 k 次调用配 B 边第 k 次，按先后，inferred: order）。
  末尾给在页面上看这条链的 `view set … --chain …`。

### `codestrata explain 函数 REF`
- 函数写 `路径#限定名`、限定名，或唯一的名字；撞名报 `ambiguous_item`（候选带这段时间里各调了几次）。
- 给：定义（签名、docstring 第一行、文件:行）、这段时间里在哪几列跑过（次数、首末时刻）、谁调它、它调了谁（全列，按次数；代码里看不出的标「看不出」和为什么）、
  它启动的 GPU kernel（名字和次数）、代码里写成调它但跑的是同名的别的方法（子类覆盖的或接口的实现）。
- scan 的索引里有、这段时间里没跑过的函数：照样给定义，写「这段时间里没跑过」。

### `codestrata path REF [--depth N] [--limit N] [--time] [--unseen]`
- 函数级的请求路径（每个进程、每条线程的调用上下文树）。每列默认截到 60 行（`--limit N` 改，`--limit 0` 不截；`--depth` 藏掉的不算）。
- 记号：+秒是第一次调用的时刻、×N、「← 文件:行」是调用写在哪一行、（之前）、↻、[看不出]、[GPU]。
- `--time`：先列出「自己的时间」最多的 5 处。`--unseen`：只列代码里看不出会调到它的调用，按次数排，每处写为什么；GPU kernel 不列，末尾单说有几处。
- 节标题是列别名；`--json` 的 `data` 和页面的 `/api/path` 同形。老写法 `path <repo> RUN` 也认。

### `codestrata view url | set | get | back | wait …`

**`view url [REF|'页面地址'] [--fold …] [--mark …] [--expand …] [--focus 东西] [--select 东西] [--chain …] [--order on|off] [--path] [--page 端口]`**
- 拼出一个视图的页面地址，不推。用户粘进浏览器地址栏（同一个标签页也行），页面不刷新就换过去。
- `--focus 东西`：在它跑过的列里把切面展开到它的文件 + 标出它 + 选中它在最早那一列里的那一份。`--mark` 标出这些文件 / 目录 / 函数（最多 20 个）。
- 页面的「默认收起」和「全部显示」不进地址。

**`view set [REF] [和 url 一样的选项] [--note 一句话] [--reset]`**：推给开着的页面——先出「agent 接手」的过渡再换，进浏览器历史（后退就是撤销），
出横幅「agent 换了视图」。用户正在操作时等他松手；「跟随 agent」关着时出提示条；标签页在后台时回来才换。还没换好时退出码 6。

**`view get`**：用户此刻在看的视图、最后是谁改的。**`view back`**：撤销 agent 最近推的那一步。
**`view wait [--for select|range|lanes|any|applied]`**：等用户在页面上改（缺省等选中变化；`lanes` 是收起 / 展开进程）。

### 视图描述（页面地址 # 后面）

`run=RUN@范围 & fold=进程,… & cut=目录,… & lcut=列~目录,目录;列~… & sel=选中 & mark=东西,… & chain=范围~起点~--link… & order=1 & panel=path`

- 页面和命令行同一套（`web/view.js`、`viewspec.py`）。值里 `@ , / ~ | : ; + * =` 不转义；不认识的键原样留着。
- `fold`：收起的进程（别名）；`cut`：共用的切面（和默认一样不写）；`lcut`：各列自己的切面；`sel`：选中的（`n:列|节点`、`f:列|框`、`e:列|a|b`、
  `l:种类|通道|起列|终列`；模块图上 `n:节点`、`e:a|b`）；`mark`：标记；`chain`：高亮的链（链上的连线加粗，推出来的那一跳画紫色虚线，别的线变淡）；
  `order=1`：时间顺序开；`panel=path`：详情栏讲请求路径。

### `codestrata runs [repo] ls | show RUN`
- 文字和 JSON 是同一份数据；RUN 也认页面地址和范围。
- `ls --json`：每个 run 的摘要加 `status_text`、`phases`、`end_us`、`bytes`。
- `show --json`：`run`（run.json 原样）、`status`、`phases`、`end_us`、`procs`、`files`、`file_state`、`rerun`（复刻命令）、`dir`。
