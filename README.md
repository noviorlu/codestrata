# codestrata

给一个 Python 仓库画两张图：

- **总图（static）** —— 全仓的模块级架构。层次不是手工标的，而是由 import 出入度算出的
  「架构高度」`(out−in)/(out+in)`：+1 是入口、−1 是纯被依赖的叶子。
- **hot 图（runtime）** —— 跑一个真实 case（仓库自带的 demo / example），
  把实际发生的调用叠在**同一张图的同一套坐标**上。于是「这个 case 走了哪条路」一眼可见。

两张图共用节点与布局，差别只在数据来源：一个是 AST，一个是运行时 hook。

点任意节点可以看到该符号的源码（带真实行号），本地模式下还能一键跳进编辑器。

## 安装

要 Python ≥ 3.10，只用标准库（Pygments 可选，用来给源码上色）：

```bash
git clone https://github.com/noviorlu/codestrata && cd codestrata
python3 -m venv .venv && .venv/bin/pip install -e '.[highlight]'
# 系统 Python 缺 venv 模块（Debian / Ubuntu 没装 python3-venv）时用 uv：
#   uv venv .venv && VIRTUAL_ENV=.venv uv pip install -e '.[highlight]'
```

也可以不 clone：`pip install 'git+https://github.com/noviorlu/codestrata'`。
**别 `pip install codestrata`**——PyPI 上的同名包是别人的，不是这个工具。

## 三步上手

```bash
codestrata scan  /path/to/repo                    # 静态扫描：小仓库不到 1 秒，1600 个文件约 13 秒
codestrata serve /path/to/repo --port 8930        # 浏览器打开 http://127.0.0.1:8930/ 看总图
codestrata trace /path/to/repo --case demo -- python your_script.py   # 录一次真实运行
codestrata serve /path/to/repo --port 8930 --hot demo                 # 同一张图上叠这次跑到的调用
```

`--` 后面是你平时跑它的命令（脚本、pytest、起服务的 sh 都行）。想按阶段看（启动 / 处理请求 / 退出），
加 `--phase serving=模块:函数`：这个函数第一次被调到时切到新阶段，不用改脚本。
录下的 run 存在目标仓库的 `.codestrata/runs/`，**只有这一份**；`.codestrata/` 里别的东西都能随时重建。

## 箭头：一条依赖到底承载了什么

import 了不等于用了，用了不等于这次跑到了。每条边都拿「静态引用 × runtime 调用」交叉，
点箭头能看到具体是哪些函数 / 类、在哪一行、被谁调了几次：

| 图上 | 含义 | 来源 |
|---|---|---|
| 灰实线 | import 了，并且代码里真的引用了对方的符号 | ast：绑定名的每一次读取 |
| 灰虚线 | 只 import，一个符号都没引用 | ast，再细分原因（见下） |
| 橙色，粗细 ∝ log(次数) | 这次 case 真的跨这条边调用过 | runtime：函数粒度的 caller→callee |
| 橙虚线 | 动态分派：跑到的调用在代码里找不到对应的引用（两端之间没有 import，或者有 import 但 import 的东西一次都没跑到） | 插件 / `importlib` / 注册表 / `self.model` 这类接口——静态分析的盲区 |

「确认调用 / 动态分派」按被调的符号判：方法归到它的类，这个类在这条边的静态引用里就算确认，否则算动态分派。图上的边和点开边看到的明细用的是同一个口径，而且按当前切面算——收起时的一条边如果跑到的调用全是动态分派，也画成橙虚线，不会因为两端之间碰巧有别的 import 就画成实线（那样展开之后实线会「消失」）。

「只 import」的原因分五种，面板上逐条列出：`unused`（死 import）、`reexport`（`__init__.py`
里给包外用的）、`type`（只在 `TYPE_CHECKING` 下）、`sideeffect`（`import a.b.c` 要的是模块顶层
执行，比如注册解析器）、`intentional`（标了 `noqa: F401`）。有 runtime 数据时，副作用 import
还会标出对方模块的顶层代码这次到底执行了没有。

**import 触发的模块执行不算调用。** 否则每条 import 边都会因为「导入过」被染成橙色，
只被 import、一个函数都没被调过的包也会显示成「跑到了」。

选中用蓝色光晕，不改边本身的颜色——选中一个节点时，最想看的恰恰是它的边里哪些是真调用。

## trace 真实部署

hot 图的 case 往往是「起一个服务、发一次请求」，被 trace 的是 pip 装好的包、拆成好几个进程。
codestrata 为此处理了几件事：

- **跑的是安装包也能叠图。** 执行路径落在 `site-packages/<顶层包>/` 下时映射回仓库文件，
  并逐文件比对内容；不一致会警告行号不可信。
- **子进程数据不丢。** 拦截 `os._exit`（multiprocessing 的 fork 子进程这样退出）和 `os.exec*`
  （换程序之前先落盘）、每 10 秒落盘（被 SIGKILL 最多丢 10 秒）、fork 后清零计数（不重复计入
  父进程）。落盘全部串行，写坏的分片会记成问题，不会悄悄丢掉一个进程。hook 不装信号处理器——
  那会改变被 trace 的程序的行为；要升级到 SIGTERM 之前，driver 写一个 STOP 文件，各进程的
  落盘线程看到就先落一次。
- **停要停干净。** 命令放在自己的会话里；超时、Ctrl+C、终端关掉时按 SIGINT → SIGTERM → SIGKILL
  三级停整个进程组（`--stop-grace` 秒后才升级，默认 90；再按一次 Ctrl+C 或按 Ctrl+\ 直接升级）。
  命令退出后再找出还属于本次录制的残留进程（比如 setsid 出去、case 脚本没停掉的服务）同样停掉，
  记进 run 里：靠 `/proc/<pid>/environ` 里的 `CODESTRATA_OUT`，加上分片里记的 (pid, 启动时刻)——
  vLLM 用 setproctitle 改进程标题，会清空 environ。
- **哈希取执行时的。** 每个进程第一次跑到一个文件时就记下它的内容哈希；录制中途改了文件，
  run 会标出来，之后叠图时这个文件也算「改过」。
- **分阶段。** 两种办法，可以一起用。① 按函数切：`--phase 名字=函数`，哪个进程第一次进入这个
  函数，就在那一刻切过去（每个阶段整个 run 只切一次，别的进程 50 ms 内跟上）——不用改被 trace
  的脚本，离线示例那种「一条阻塞的 python 命令」也能分出加载 / 推理 / 关闭。函数写成
  `模块:qualname`（查静态索引，继承来的方法也认，`Omni.close` 会认成 `OmniBase.close`）或
  `文件路径:qualname`（不在索引里的文件也行，比如 examples/ 下的入口）。② case 脚本往
  `$CODESTRATA_OUT/PHASE` 写一个名字（服务类的 case：健康检查通过后写 serving）。之后
  `--hot 名字@serving` 只看那一段，启动时的初始化不会混进来。

```bash
# 离线脚本：不改脚本，按函数切
codestrata trace <repo> --case offline \
    --phase generate=vllm_omni.entrypoints.omni:Omni.generate \
    --phase shutdown=vllm_omni.entrypoints.omni:Omni.close -- bash run_single_prompt.sh
# 服务：case 脚本里（服务就绪后）写 PHASE
[[ -n "${CODESTRATA_OUT:-}" ]] && { echo serving > "$CODESTRATA_OUT/PHASE"; sleep 2; }
codestrata trace <repo> --case demo -- bash case.sh
codestrata serve <repo> --hot demo@serving       # 勾「只看跑到的」得到单独排版的 hot 图
```

### 录一次，一直用：run

静态分析只有一份，随时 `scan` 重建；runtime 不能重建——一次录制往往是几分钟 GPU。所以每次
`trace` 都存成一个新的 **run**（`.codestrata/runs/<时刻>-<case>/`），同名 case 重录也不覆盖：
今天录 MiniCPM、明天录 Qwen，两份都留着，随时叠到图上。

- run 里存原始数据（各进程的分片、case 脚本和命令里提到的配置文件、Python / 包版本、GPU、git）
  和由它算出的计数。计数按 `文件:首行号` 存，加载时现映射到当前的 index 上——代码改了之后老 run
  照样能用，哪些文件在录制之后改过会逐个标出来，而不是整个 run 作废；改过的文件里按录制时记下的
  函数名（qualname）把次数挪到函数现在的行号上，挪下去几行、加了注释都对得上。
- `--hot` 接受完整的 run id，或 case 名（取它最新一次录完的），都可以加 `@阶段`。`serve` 的 `--hot`
  只决定页面打开时先叠哪个；页面上方「运行」随时换（静态图 / 任何一个 run，分了阶段的再选阶段），
  不用重启，serve 开着时新录的也看得到。选的 run 记在地址里（`#run=<id>@<阶段>`），刷新、分享链接都还是它。
- `runs/` 可以是软链（比如指到大盘）。**`.codestrata/` 里除 `runs/` 外都能删**；`runs/` 删了就没了。
- 老版本的 `trace-<case>.json` 第一次被读到时自动迁成 run（原文件逐字节留在 run 的 `legacy/` 里）。
- **时序图**：录了事件的 run，工具栏上「图」可以在模块图和时序图之间切换。时序图的生命线是
  (进程, 当前切面上的节点)，消息是节点之间的一次调用——和模块图共用切面（在模块图上展开一个目录，
  时序图就细到它下面的子模块）和选中（点生命线头 = 选中模块，点消息 = 选中边，详情照旧在抽屉里）。
  默认从当前阶段的起点开始，自动收窄到一屏 300 行；画得下就不折，画不下才把重复的片段折成
  「↻ ×N」（点开看那一段）；顶上的时间刷是每个进程的调用密度，拖一段就看那一段。模块图上选中
  一条边，抽屉里有「在时序图里看」，跳到这条边第一次被调用的时刻。
- **对比两个 run**：选了一个 run 之后，工具栏上「对比」再选一个（有同名阶段就比同名阶段）：模块图上
  只有 A 跑到的橙色、只有 B 跑到的紫色、两边都跑到的前景色，节点上的数是「A/B」，边详情里每个函数
  都带 B 的次数。比如 MiniCPM@serving 对比 Qwen@serving，一眼看出两个模型各走了哪些代码。
- **导出带多个 run**：`graph <repo> --hot A --hot B [--compare]`——单文件里能在这几个 run 之间切换
  （别的 run 只带图上的次数，调用明细只有第一个的），`--compare` 带上 A、B 的对比。
- **放到公网上**：`graph … --public`——主目录写成 `~`（源码行里的也换，Ctrl+点击的列号跟着挪）；
  run 元数据里 PATH / LD_LIBRARY_PATH / PYTHONPATH 这种目录列表，仓库和录制目录以外的部分省略成 `…`
  （那些只是本机装了哪些工具）；还剩主目录就拒绝写出。页面上注明命令因此不能原样执行，原样的在录制的
  机器上 `runs show` 里。导出的单文件没有时序图（它要 serve 现算）。
- **源码从 GitHub 取、没有体积上限**：`graph … --link github --out 目录`。单文件导出要把源码塞进 HTML，
  受单文件宿主 16 MB 的上限（vllm-omni 1600 多个文件只装得下两百多个）；扫的仓库在 GitHub 上时，页面按
  **扫描时的提交号**从 jsDelivr（不行再 raw.githubusercontent.com）取源码、在浏览器里高亮（`web/hl.js`，
  和服务端 Pygments 逐字符一致），codestrata 自己算的放在旁边的 `data/<版本>/` 里按需取——所有文件都能看、
  都能 Ctrl+点击、看全仓的引用，每个文件带「GitHub ↗」。取回来的行数和扫描时对不上就不给跳转并说明；
  GitHub 上那个提交里没有或不一样的文件（改了没提交、没进 git、skip-worktree、软链接）随页面带上，
  `--public` 时被 .gitignore 忽略的不带。导出时会试取一个文件，提交没推上去就不导出。

```bash
codestrata graph . --link github --public --hot qwen-chat@serving --out ../mysite/source/codestrata/myrepo
```
- **复刻**：每个 run 存下录制时原样的 codestrata 命令和所在目录（`cd <目录> && <命令>`，照抄就能再录一次），
  以及 shell 里和跑模型有关的环境变量（CUDA_* / VLLM_* / HF_* / PATH…，名字像密钥的不存）——命令会继承它们，
  光看命令复刻不出来。网页上 run 按钮旁边的「复刻」、或「?」帮助里「这次跑了什么」都能一键复制；
  `runs show` 也打印。老 run 没存原始命令的，按 run 里存的参数拼一条并注明。
- `trace --events` 同时记时序事件（时序图的数据，要 Python 3.12+）：每次跨文件调用的起止时刻，
  返回 / 挂起 / 恢复按帧配对，同一线程里交错的 asyncio 协程也配得对。原始日志永久留在
  `events/raw.tar.gz`，整理好的 span 在 `events/spans/`（`runs merge` 可重建）；
  不要了用 `runs <repo> rm <id> --events-only`。

```bash
codestrata trace <repo> --case qwen-chat --env MODEL_NAME=Qwen2.5-Omni-7B --tag model=qwen \
    --attach ../common.sh -- bash case.sh     # --env 传给命令、--attach 把被 source 的文件一起存下
codestrata runs <repo> ls                     # 按 case 分组列出，状态、时长、git、录制后改过几个文件
codestrata runs <repo> show qwen-chat         # 详情 + 文件相对当前代码的状态 + 复刻命令
codestrata runs <repo> tag|untag|note|merge …
codestrata runs <repo> rm <run id>… [--yes]   # 只认完整的 run id；还在录的不删
```

读 hot 图要知道两件事：「调用方」是最近的仓库内的帧，穿过仓库外代码（如 vLLM 内部）的调用
会显示成直接调用；调用次数高的多半是轮询，不等于重要。

## 大仓库：图是目录树的一个切面，节点能就地展开 / 收起

scan 记的是最细的粒度——每个 `.py` 文件一个模块，依赖、符号、调用明细都在文件之间。
图上显示的是目录树的一个**切面**：收起的目录是一个节点（名字带 `/`），展开的目录换成它的
子目录和文件；直接放在一个目录里的文件多了（> 12 个）会合成一个「本层」节点，也能再展开。

- **默认切面按规模自动算**：从根开始，反复把代码量超过全仓 10%、拆开后不超过 20 个节点的
  最大节点拆开，直到拆不动或图上到了 80 个节点。宽而平的目录（几十个同类实现，比如 vllm-omni 的 43 个模型族）
  留成一个节点。vllm-omni 上是 diffusion（41%）拆成 19 块、model_executor（29%）拆成 7 块，
  58 个节点；scan 会打印拆了哪些。
- **点节点左上角的 ＋** 就在当前图上把它换成子模块（重新汇总边和高度、重新排版，新出来的节点闪一下）。
  **展开的目录画成一个框**，把它的子模块框在一起，框头的 **−** 把它收回一个节点；框可以嵌套。
  纵轴仍然是架构高度，所以框不能在纵向上把子模块挪到一起——每个展开的目录在横向上占一段
  自己的列，框从它最高的子模块画到最低的子模块。只跨一两条泳道的小框不占满整列：别的泳道里
  那段宽度让给散放的节点，泳道跨度不重叠的框还可以上下叠在同一列。框的左右顺序只取决于框本身，
  展开一个无关的目录不会让别的框换位置。
- 展开多了画布会变宽：图框撑宽到窗口，字最多缩到 0.88 倍，再宽就在图框里横向滚动（按住空白处拖动），
  边缘有渐隐提示那边还有东西。
- 展开 / 收起不会取消选中：选中的节点还在就还选着它，被收进了框就选中收回来的节点，自己被展开成框
  就选中那个框。再点一次选中的节点、点空白处或按 Esc 才取消选中。
  详情面板里也有「展开」和「收起到上一级」，工具栏的「恢复默认层级」回到 scan 算出的切面。
  切面只是一组展开着的目录（`/api/graph?open=a,b`），不改任何数据。
- `scan --depth N` 改成固定深度（2 = 老的「二级包」），`scan --expand DIR` 在默认切面上额外展开某个目录。
- 解读、派活（`tasks`）都按默认切面上的节点；展开出来的节点也能单独写解读，target 就是节点名
  （目录 `vllm_omni.engine`、本层 `vllm_omni.engine.*`、文件 `vllm_omni.engine.async_omni`）。
- 导出的单文件是固定切面（框照样画），不能展开 / 收起；要交互用 `serve`。
- 泳道放不下时折行，框永远装得下标签；hot 视图单独排版，只放跑到的节点。
- 作者写的文档自动挂到包上：包内 README、frontmatter 用 `primary_code_paths` 声明了代码路径的
  设计文档、开头用反引号写出仓库路径的文档。它们出现在详情面板和给 agent 的输入包里——
  「为什么这样切」往往作者已经写过。

## 为什么不用 OpenGrok / Sourcetrail

- OpenGrok 要 Java + Tomcat + universal-ctags，为读代码架一套太重，而且它给的是**搜索与交叉引用**，
  不给「架构分层」这件事。
- Sourcetrail 2021 已归档；活着的 fork NumbatUI 明确禁用了 Python 索引。
- Hound / Zoekt 是搜索引擎，没有可供图链接的 per-symbol URL。

codestrata 只用标准库（Pygments 可选，用于高亮），`pip install` 之后一条命令出图。

## 分工：结构交给自动化，理解留给 agent

| 层 | 谁产出 | 放哪 | 能否重建 |
|---|---|---|---|
| 结构：包、import 边、架构高度、符号位置 | `scan`（ast） | `.codestrata/` | 随时 |
| 运行：哪个 case 实际调到了什么 | `trace`（runtime hook） | `.codestrata/runs/` | **不能**（要重新跑一遍） |
| **理解：为什么这样切、算法为什么这么写、按什么顺序读** | **人 / LLM agent** | **`notes/`，进版本库** | **不能** |

机器能给出结构，给不出理解。codestrata 把理解那一层**留空**，并告诉 agent 该填什么：

```bash
codestrata tasks . --write     # 待解读的模块，自底向上排好序，每个一份输入包
# 把 .codestrata/tasks/01-xxx.md 交给 agent，它读真源码后产出 Markdown
codestrata note . <模块> out.md # 写回（自动补 frontmatter 和 code_sha）
```

**派活顺序按架构高度自底向上**：叶子没有内部依赖，可以孤立读懂；写到上层时下层的解读
已经存在，输入包会把它们一并带上，于是上层能引用下层而不是各说各话。

**解读会腐烂。** 每份解读的 frontmatter 里存 `code_sha`——它所描述的那些源文件的内容哈希。
代码一改，前端立刻把它标成「可能过期」。只看所描述的文件：改别的模块不会误报。

**LLM 写的解读要机器核对。** `codestrata check` 核对解读里能核对的部分：
- `file:line` 引用：文件在不在、行号越没越界；保存时给每处引用记下那一行的内容指纹，
  代码改了之后能精确指出「`render.py:17` 引用的那一行已经移到第 18 行」；
- 反引号里的名字（`build`、`Handler.do_GET`、`os._exit`）：代码里（或标准库里）是否真有。

它核对不了「为什么这么写」对不对，但编出来的函数名、写错的行号、引用了已删掉的代码都能抓住。
前端在每份解读顶上显示核对结果。

除了每个模块一份，还有一份**仓库总览**（target 名 `_overview`，存在 `notes/overview.md`）：
这个仓库做什么、主干数据流、为什么这样分层、阅读顺序。它最后写（输入包会带上所有模块解读），
只在架构骨架（包和依赖）变了时才过期；没选中任何节点时，右侧面板显示的就是它。

## 前端：一套代码，两种模式

前端在 `codestrata/web/`，普通 HTML/CSS/JS，零构建、不要 npm。`web/ds.js` 一层决定数据从哪来：

```bash
codestrata serve .              # 本地部署：fetch /api/*，能写解读、能跳编辑器
codestrata graph .              # 单文件导出：数据内嵌，只读、离线、可以直接发给别人
```

serve 提供的 API（agent 也可以直接调）：

```
GET  /api/graph?open=a,b      一个切面上的静态图 + hot 叠加（不给 open 是默认切面）
GET  /api/tasks               待解读清单（自底向上）
GET  /api/pack/<模块>          给 agent 的输入包
GET  /api/notes/<模块>         解读 + 是否过期
GET  /api/status?ids=a,b      一批节点的解读状态（noted / stale / todo）
PUT  /api/notes/<模块>         写回解读        ← agent 从这里介入
GET  /api/symbol/<key>        符号源码
GET  /api/file?f=             整个文件（高亮）+ 符号大纲 + 能 Ctrl+点击的名字
GET  /api/outline?f=          一个文件的符号大纲（含方法），文件树按需展开
GET  /api/edge?a=&b=          一条边：引用了哪些符号、runtime 调了哪些、哪些只 import
GET  /api/refs?t=             一个定义被哪些地方引用（Ctrl+点击定义时的列表）
GET  /api/search-index        搜索栏要的全部名字（模块、文件、类 / 函数）
GET  /api/reveal?node=&open=  让一个模块在图上露出来要展开哪些目录
GET  /api/open?f=&l=          让本机编辑器跳到 file:line
```

## 读代码：Ctrl+点击、搜索栏、缩放

- **Ctrl（Mac 上 ⌘）+ 点击**：全文窗口和详情面板的源码片段里，按住 Ctrl 能点的名字会带下划线。
  点一个名字跳到它的定义（「← 返回」回到点的地方）；点一个定义，旁边一栏列出所有引用它的地方
  （调用在前，同一行的几处合成一条），点哪条跳哪条。名字指向哪由 scan 时写下的
  `.codestrata/xref.json` 给出：import（包括经 `__init__.py` 再导出的）、`模块.函数`、`类.方法`、
  `self.` / `cls.` / `super()`（按 MRO 在仓库里的基类里找）、`self.x = …` 定义的实例属性；
  局部变量会遮住同名的全局名字。确定不了的不给链接——宁可不跳，也不跳错。通过别的对象调用的方法
  （`engine.generate()`）不知道对象类型，引用列表里单列一组「同名的 `.generate`（没确认对象类型）」。
  文件在 scan 之后改过，行列号就对不上了：那个文件不给 Ctrl+点击，重新 scan 即可。
- **搜索栏**（右边一栏，`/` 或 Ctrl+K 跳过去）：按名字找模块、文件、类 / 函数。函数看它自己的名字
  （方法也看类名），文件看文件名，模块看最后一段；词里写了 `.` 或 `/` 才按路径找（`entrypoints/`、
  `engine.async`）。点结果先回到图上，展开到它所在的模块并选中，再在下面的详情里展开到它；
  「代码」按钮直接开全文窗口。图上包含命中项的节点会高亮。
- **缩放**：图框右上角有放大、缩小、移动三个按钮；按住 Ctrl 滚滚轮以鼠标为中心缩放（不按 Ctrl
  的滚轮照常滚页面）；移动模式下按住任意位置拖动图。

## 用法

```bash
codestrata scan  <repo> [--depth N] [--expand DIR]   # 静态扫描 + 交叉引用；默认切面按规模自动拆分
codestrata serve <repo> [--hot RUN[@阶段]]     # 本地部署前端；--hot 只是打开时先选哪个 run，页面上随时换
codestrata trace <repo> --case NAME [--events] [--timeout S] [--tag T] [--note TXT] [--env K=V] [--attach F] -- CMD
                                              # 跑一个 case，记录真实调用（子进程一并 trace），存成新的 run
codestrata runs  <repo> ls|show|tag|untag|note|rm|merge   # 管理录下的 run
codestrata tasks <repo> [--write]             # 待解读 + 输入包
codestrata note  <repo> <模块> <file.md>       # 写回解读（总览用 _overview）
codestrata check <repo> [模块 ...] [--fix]     # 机器核对解读：过期、引用漂移、名字 / 路径不存在
                                              # --fix 把只是挪了位置的引用改到新行号（不去掉过期标记）
codestrata graph <repo> [--hot RUN[@阶段]]… [--compare]   # 导出单文件；多个 --hot 可在页面上切换
```

## 状态

早期。已验证：AST 扫描（vllm-omni 1608 文件 / 4.5s / 0 失败）、高度分层（排序符合架构直觉）、
runtime trace（真值测试：返回后再调用、生成器恢复、异常展开三种情况下调用者都正确；
动态分派被正确识别为静态盲区）、边的五类归并、解读的写回与过期检测、serve 的路径越权防护。

src-layout（`src/mypkg/...`）的模块名相对 `src/` 算，而不是相对仓库根——否则模块名带上 `src.`
前缀、和代码里的 `import mypkg.x` 对不上，所有边都会指向不存在的包。

trace 踩过的两个坑，写在这里免得重犯：
- 只订阅 `PY_START` 不订阅返回/展开，调用者会变成「上一个开始执行的函数」。
- 按 code 对象做缓存键是错的：code 对象**按内容**比较相等且不比 `co_filename`，
  几个空 `__init__.py`、或不同文件里同名同行同体的函数会被当成同一个。按文件名缓存。
- 非交互 bash 用 `&` 起的后台进程天生忽略 SIGINT；Python 程序若不自己装处理器（uvicorn 装了，
  `asyncio.run` 不装），发 SIGINT 等多久都没用。停残留进程时看 `/proc/<pid>/status` 的 SigIgn，
  忽略 SIGINT 的直接发 SIGTERM。

录制端的测试在 CPU 假服务上跑（setsid 的服务、multiprocessing、exec、asyncio、分阶段）：
`.venv/bin/python tests/test_runs.py`。

一个负面结论值得记下：**SCC 缩点不能用来分层**。Python 的循环 import 会让强连通分量退化——
在 vllm-omni 上 30 个包有 20 个塌进同一个环，分层信息全丢。启发式在这里胜过图论正解。

## License

MIT
