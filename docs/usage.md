# codestrata 使用手册

README 讲 codestrata 是什么、怎么几分钟内跑起来；这份手册讲其余的一切：每个功能怎么用、界面上在哪、背后的规则、完整的命令参考、已知限制和实测数字。

命令里写 `<repo>` 的是被分析的仓库目录；写 `[repo]` 的可以省略，默认是当前目录。

## 目录

- **上手**：[安装](#安装) · [第一次用](#第一次用)
- **用功能**：[扫描](#扫描) · [看图](#看图) · [边的种类](#边的种类) · [录一次运行](#录一次运行) · [分阶段](#分阶段) · [管理 run](#管理-run) · [时间轴和时间顺序](#时间轴和时间顺序) · [读代码](#读代码) · [主菜单 codestrata app](#主菜单-codestrata-app)
- **参考**：[命令参考](#命令参考) · [输出文件](#输出文件) · [常见问题](#常见问题) · [实测数字](#实测数字) · [已知限制](#已知限制)
- **给开发者**：[前端和 API](#前端和-api) · [给开发者](#给开发者)（测试、设计决策、状态各在哪）

---

## 安装

### 要求

- **Python ≥ 3.10**（`pyproject.toml` 的 `requires-python`）。在 3.10 和 3.13 上装过、扫过、录过。
- **没有必需的第三方依赖**，只用标准库。可选的 `[highlight]` 装上 Pygments ≥ 2.17，用来给源码上色；不装的话，本地网页里的代码是纯文本。
- **`trace --events` 要求被录的那个 Python 是 3.12+**（它要用 `sys.monitoring`），和 codestrata 自己装在哪个 Python 里无关：codestrata 装在 3.10 的 venv 里、去录一个 3.13 的程序，照样录得到事件。被录的 Python 低于 3.12 时，run 照样录完，但会打印 `⚠ 要了 --events 但没有录到事件：…`。
- **操作系统**：录制（`trace`）只支持 Linux，别的系统上会直接说明并退出——它靠 `/proc` 认进程、找出 setsid 出去的服务，靠进程组和 SIGKILL 停干净。scan / serve / runs 在其他系统上也能 import、能用（测试里模拟过没有 `fcntl`、没有 SIGKILL 的环境），但只在 Linux 上实际跑过。
- **编辑器跳转**要 PATH 上有 `code`、`cursor`、`codium`、`code-insiders` 或 `subl` 之一（按这个顺序找）；都没有时 serve 会打印「没找到」，跳转按钮返回 501。

### 从 GitHub 装

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install 'git+https://github.com/noviorlu/codestrata'                 # 不带高亮
pip install 'codestrata[highlight] @ git+https://github.com/noviorlu/codestrata'   # 带高亮
```

**别 `pip install codestrata`**：PyPI 上同名的包（0.2.1，「CodeStrata Engine」，来自 github.com/CodeStrata/codestrata-engine）是别人的，不是这个工具。

codestrata 可以装在自己单独的环境里，不用和被分析的仓库装在一起：`trace` 是把 hook 注入到你命令里的那个 `python` 上的。

### 从源码装（想改 codestrata 时）

```bash
git clone https://github.com/noviorlu/codestrata && cd codestrata
python3 -m venv .venv && .venv/bin/pip install -e '.[highlight]'
```

Ubuntu / Debian 的系统 Python 可能缺 venv 模块（报 `ensurepip is not available… apt install python3.12-venv`）。装上那个 apt 包，或者改用 uv：

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[highlight]'
```

---

## 第一次用

四步，顺序有讲究：

```bash
cd <repo>
codestrata scan                                      # 1. 静态扫描，写出 .codestrata/index.json 等
codestrata serve                                     # 2. 浏览器打开 http://127.0.0.1:8900/ 看静态图
codestrata trace --case demo -- python your_script.py   # 3. 录一次真实运行，存成一个新的 run
codestrata serve --hot demo                          # 4. 同一张图上叠这次跑到的调用
```

- **先 scan 再 serve。** 没 scan 过就 serve，会提示 `没有 …/.codestrata/index.json；先跑 codestrata scan …`。trace 可以在 scan 之前跑，只会打印一句提示；但叠图要用 scan 的结果。
- **serve 开着也能录。** 新录的 run 不用重启 serve，页面上方「运行」菜单里就有，还会亮一个小点提示。所以「serve 一次，然后反复 trace、在菜单里挑」也行。
- **想要时间轴和「时间顺序」**，第 3 步加 `--events`（被录的 Python 要 3.12+），见[时间轴和时间顺序](#时间轴和时间顺序)。
- **`--hot` 只决定页面打开时先叠哪个 run**，页面上随时能换。它接受 case 名（取这个 case 最新一次录完的）或完整的 run id，写法见[管理 run](#管理-run)。

### 输出里的几个说法

- scan 最后打印每个节点的「架构高度」：+1 是入口（只依赖别人），−1 是叶子（只被别人依赖）。
- scan 的 `按规模自动拆开：*（占 66%，拆成 18 块）` 里，`*` 指扫描的根包本身。
- trace 的 `（21 次 import 时的模块顶层执行，41 次类体执行…：是定义、不算调用）`：import 一个模块时执行它顶层的代码、执行 `class` 语句定义类，这些都不算函数调用，不会让边变橙色。
- trace 和 serve 说的「N 个包」和图上橙色节点的个数可能不一样：图上按当前切面汇总，收起的目录（比如 flask 的 `json/`）里的几个模块算一个节点。
- 所有终端输出都是中文。

---

## 扫描

`codestrata scan [repo]` 用 `ast` 逐个解析 `.py` 文件，写出 `.codestrata/index.json`（模块、import 边、切面）、`symbols.json`（类和函数的位置）、`xref.json`（交叉引用，Ctrl+点击用）和 `graph.json`（函数之间的调用，格式见 [run-format §9.3](design/run-format.md#93-扫描端要产出的静态索引)），并打印扫了哪些目录。

### 扫哪些目录

- **不给 `--roots` 时自动探测**，按顺序试：仓库根目录下带 `__init__.py` 的库包（跳过 tests、examples、docs、scripts、benchmarks、tools、ci 这类）→ 没有的话取 `src/` 下的包 → 再没有就收只有测试之类的包 → 最后退到含 `.py` 最多的那个顶层目录。所以没有 `__init__.py` 的目录（比如很多研究代码的 `utils/`）和根目录直接放着的脚本通常不会被挑中。
- **给了 `--roots` 就照单全收**。仓库根目录直接放着的脚本（`train.py` 这类入口）用 `--roots .` 选，只取这一层，图上装在以仓库名命名的节点里。比如 gaussian-splatting：自动探测只扫到 34 个 `.py` 里的 12 个，`--roots . arguments gaussian_renderer lpipsPyTorch scene utils` 扫到 26 个。
- 最后一段同名的、或者一个在另一个里面的目录不能一起扫：模块名会撞。
- **src 布局**（`src/mypkg/...`）的模块名相对 `src/` 算，和代码里的 `import mypkg.x` 对得上。
- `trace` 默认用上次 scan 选的目录；没 scan 过才自动探测。

### 切面参数

- `--depth auto|N`：默认切面怎么定。`auto`（默认）按规模自动拆，规则见[看图](#看图)；`N` 表示展开所有深度小于 N 的目录（2 就是老的「二级包」）。
- `--expand DIR`：在默认切面上额外展开某个目录，可重复。目录写路径（`vllm_omni/diffusion`）或点分名（`vllm_omni.diffusion`）都行。

### 什么时候要重新 scan

- 改了代码之后。scan 之后改过的文件，Ctrl+点击的行列号就对不上了：那个文件不给 Ctrl+点击，重新 scan 即可。
- **重新 scan 之后要重启 serve**，图和搜索才会更新（Ctrl+点击会自动换新；从主菜单扫描的，主菜单会替你重启）。
- **升级 codestrata 之后**：索引的格式变了的话，serve 会提示「旧版本的格式，重新 scan」，主菜单的项目卡片上也会标出来。run 不受影响，重新 scan 之后照样叠。
- `serve` 也接受 `--roots`，但目前**不起作用**，扫哪些目录只由 scan 决定。

### 自动挂上的作者文档

包内的 README、frontmatter 用 `primary_code_paths` 声明了代码路径的设计文档、开头用反引号写出仓库路径的文档，会自动挂到对应的包上，出现在详情面板和给 agent 的输入包里——「为什么这样切」往往作者已经写过。

---

## 看图

### 分层

纵轴是依赖的层次：import 别人的在上，被 import 的在下，箭头尽量都从上指向下；只有循环依赖里被打断的少数边往上指。最上一层标「入口」，最下一层标「叶子」。每一层是图上的一条横带，叫**泳道**，最多 16 条（层太多时按比例压）。

叠了一个 run 之后，分层按**这次实际的调用**重排（调用方在上），运行时的边权重是静态边的 10 倍。所以回调、按注册表分派这类和 import 方向相反的调用照样往下走，「这个 case 走了哪条路」从上往下读就是。代价是换 run 时节点会上下挪。叠了 run 的图在页面上叫 **hot 图**（参数 `--hot` 由此得名），不叠 run 的是静态图；「视图 → 只看跑到的」给出单独排版的 hot 图。

### 切面：大仓库怎么显示

scan 记的是最细的粒度：每个 `.py` 文件一个模块，依赖、符号、调用明细都在文件之间。图上显示的是目录树的一个**切面**：收起的目录是一个节点（名字带 `/`），展开的目录换成它的子目录和文件；一个目录里直接放着的文件超过 12 个，合成一个「本层」节点，也能再展开。

- **默认切面按规模自动算**：从根开始，反复把代码量超过全仓 10%、拆开后不超过 30 个子节点的最大节点拆开，直到拆不动或图上到了 80 个节点。宽而平的目录（几十个同类实现，比如 vllm-omni 的几十个模型族）留成一个节点。vllm-omni 的 `vllm_omni/` 包上，diffusion 拆成 19 块、model_executor 拆成 8 块，共 60 个节点；scan 会打印拆了哪些。
- **展开**：点节点左上角的 **＋**，就在当前图上把它换成子模块（重新汇总边和高度、重新排版，新出来的节点闪一下）。详情里也有「展开（N 个子模块）」。
- **展开的目录画成一个框**，框头的 **−** 把它收回一个节点；框可以嵌套。纵轴仍然是依赖的层次，所以框不能在纵向上把子模块挪到一起：每个展开的目录在横向上占一段自己的列，框从它最高的子模块画到最低的。只跨一两条泳道的小框不占满整列，别的泳道里那段宽度让给散放的节点；泳道跨度不重叠的框可以上下叠在同一列。框的左右顺序只取决于框本身，展开一个无关的目录不会让别的框换位置。
- **收起**：框头的 −，或详情里的「收起到 …」。工具栏的「恢复默认层级」回到 scan 算出的切面。
- **展开多了画布会变宽**：图框撑宽到窗口，字最多缩到 0.88 倍，再宽就在图框里横向滚动（按住空白处拖），边缘有渐隐提示那边还有东西。泳道放不下时折行，框永远装得下标签。
- **展开 / 收起不会取消选中**：选中的节点还在就还选着它；被收进了框就选中收回来的节点；自己被展开成框就选中那个框。
- 切面只是一组展开着的目录（`/api/graph?open=a,b`），不改任何数据。

### 点节点、点边

- **详情栏第一次是收着的**：点了节点或边之后，再点页面底部的「详情」栏（或它左边的 ▴）展开，之后记住开合状态。
- **点节点**：下面的详情抽屉里是它的依赖、文件树、类和函数、源码片段（带真实行号）。选中的节点用蓝色光晕标出，不改边本身的颜色——选中一个节点时，最想看的恰恰是它的边里哪些是真调用。再点一次、点空白处或按 Esc 取消选中。
- **点边**：这条依赖具体用了对方哪些符号、在哪一行、谁调了几次，每个调用给出调用处和定义处的代码。折叠栏：「引用了，这次没跑到」「按名字登记」（动态分派的接线点，比如 `registry.py:3` 的 `"toy.plugins.double:Double"`）「只 import、没引用」「全部 import 语句」。规则见[边的种类](#边的种类)。

### 工具栏和缩放

- 「边」一行是开关兼图例，每种边后面带条数：引用 / 只 import / 仅类型 / runtime / 动态分派，以及时间顺序。
- 「视图」：**只看跑到的**（只放这次跑到的节点，单独排版，得到一张单独的运行时图）；「重置」。
- 「?」打开帮助；帮助里「这次跑了什么」列出这个 run 的命令。
- **缩放**：图的**左上角**有 ＋ / － / ✥ / 100% 四个按钮：放大、缩小、移动模式（按住任意位置拖动图，按在节点上也不会选中它）、回到适应宽度。Ctrl（Mac 上 ⌘）+ 滚轮以鼠标为中心缩放，不按 Ctrl 的滚轮照常滚页面；触控板双指捏合也行。图比框宽时按住空白处拖动。

---

## 边的种类

import 了不等于用了，用了不等于这次跑到了。每条边都拿「静态引用 × 运行时调用」交叉：

| 图上 | 含义 | 来源 |
|---|---|---|
| 灰实线（引用） | import 了，并且代码里真的引用了对方的符号 | ast：绑定名的每一次读取 |
| 灰虚线（只 import） | 只 import，一个符号都没引用 | ast，再细分原因（见下） |
| 点线（仅类型） | 只在 `if TYPE_CHECKING:` 里 import | ast |
| 橙色（runtime），粗细 ∝ log(次数) | 这次运行真的跨这条边调用过 | 运行时：函数粒度的 caller → callee |
| 橙虚线（动态分派） | 跑到的调用在代码里找不到对应的引用：两端之间没有 import，或者有 import 但 import 的东西一次都没跑到 | 插件、`importlib`、注册表、`self.model` 这类接口——静态分析的盲区 |

- **「确认调用」还是「动态分派」按被调的符号判**：方法归到它的类，这个类在这条边的静态引用里就算确认，否则算动态分派。图上的边和点开边看到的明细用同一个口径，而且按当前切面算：收起时的一条边如果跑到的调用全是动态分派，也画成橙虚线，不会因为两端之间碰巧有别的 import 就画成实线（那样展开之后实线会「消失」）。
- **「只 import」的原因分五种**，面板上逐条列出：`unused`（死 import）、`reexport`（`__init__.py` 里给包外用的）、`type`（只在 `TYPE_CHECKING` 下）、`sideeffect`（`import a.b.c` 要的是模块顶层执行，比如注册解析器）、`intentional`（标了 `noqa: F401`）。有运行时数据时，副作用 import 还会标出对方模块的顶层代码这次到底执行了没有。
- **动态分派有假阳性。** 经 `__init__.py` 再导出的名字，静态边指向 `pkg/__init__.py`，而运行时调用落在真正定义它的文件上；`from x import *` 有 import 边，但不知道它带进了哪些名字。这两种情况下，展开到文件时经它们调到的函数都显示成动态分派。模块级的 `__getattr__`（PEP 562）也一样：代码里不会写出对它的引用。
- **import 触发的模块执行不算调用。** 否则每条 import 边都会因为「导入过」被染成橙色，只被 import、一个函数都没被调过的包也会显示成「跑到了」。

一个具体例子：一个玩具仓库里，`engine.py` 通过 `registry.load("double")` 用 importlib 按字符串加载插件。静态图上 engine 和 `plugins.double` 之间没有 import 边；录一次之后出现一条橙虚线，调用 20 次；点开它，看到 `Engine.step → Double.run`，「按名字登记」一栏指到 `toy/registry.py:3` 的 `_REG = {"double": "toy.plugins.double:Double"}`。

---

## 录一次运行

### 基本用法

```bash
codestrata trace [repo] --case NAME [选项…] -- 你平时跑它的命令
```

- **`--` 不能省。** 它后面的一切都是要跑的命令（脚本、pytest、起服务的 sh 都行）。
- **命令默认在仓库根目录执行**，相对路径按仓库根目录算；要在别的目录执行就加 `--cwd DIR`（`--cwd .` 是当前目录）。命令里的相对路径在仓库根目录下没有、在当前目录下有时，trace 开录之前就会停下来说明并建议 `--cwd .`，不会留下一个失败的 run。
- **命令用的是 PATH 上的那个 `python`**，被分析的仓库和它的依赖得在那里 import 得到（通常是 `pip install -e .`）。
- `--case` 只能用字母、数字和 `._-`。同名 case 重录不覆盖，每次都是一个新的 **run**。
- `--timeout S`：超过这么多秒就按三级顺序停掉命令。
- `--env K=V`（可重复）：给命令加环境变量，会记进 run、复刻命令里也有。
- `--attach FILE`：把这个文件一起存进 run，比如被 case 脚本 `source` 的 `common.sh`。
- `--tag T`、`--note TEXT`：给 run 打标签（比如 `model=Qwen2.5-Omni-7B`）、写一句备注。
- `--roots DIR…`：仓库代码在哪些目录（把安装包映射回仓库时用）；默认用 scan 时选的。
- `--events`：同时记时序事件，见[时间轴和时间顺序](#时间轴和时间顺序)。
- `--phase NAME=FUNC`：切阶段，见[分阶段](#分阶段)。

```bash
codestrata trace <repo> --case qwen-chat --env MODEL_NAME=Qwen2.5-Omni-7B --tag model=qwen \
    --attach ../common.sh -- bash case.sh
```

录完会打印进程数、被调到的函数数、文件间调用边数、退出码、用时，以及映射到了多少个包和符号、调用最多的包，最后给出叠图的命令。

### 录真实部署：服务、多进程、安装包

运行时图的 case 往往是「起一个服务、发一次请求」，被录的是 pip 装好的包、拆成好几个进程。codestrata 为此处理了这几件事：

- **子进程一起录。** hook 通过 `PYTHONPATH` 上的 `sitecustomize.py` 注入，fork、spawn、exec 出来的每个 Python 进程都会挂上。
- **跑的是安装包也能叠图。** 执行路径落在 `site-packages/<顶层包>/` 下时映射回仓库文件，并逐文件比对内容；不一致会警告行号不可信。
- **子进程数据不丢。** 拦截 `os._exit`（multiprocessing 的 fork 子进程这样退出）和 `os.exec*`（换程序之前先落盘）、每 10 秒落盘（被 SIGKILL 最多丢 10 秒）、fork 后清零计数（不重复计入父进程）。落盘全部串行，写坏的分片会记成问题，不会悄悄丢掉一个进程。hook 不装信号处理器——那会改变被录的程序的行为；要升级到 SIGTERM 之前，codestrata 写一个 `STOP` 文件，各进程的落盘线程看到就先落一次。
- **停要停干净。** 命令放在自己的会话里；超时、Ctrl+C、终端关掉时按 SIGINT → SIGTERM → SIGKILL 三级停整个进程组（`--stop-grace` 秒后才升级，默认 90；再按一次 Ctrl+C 或按 Ctrl+\ 直接升级）。命令退出后再找出还属于这次录制的残留进程（比如 setsid 出去、case 脚本没停掉的服务），同样停掉并记进 run：靠 `/proc/<pid>/environ` 里的 `CODESTRATA_OUT`，加上分片里记的（pid, 启动时刻）——vLLM 用 setproctitle 改进程标题，会清空 environ。忽略 SIGINT 的进程（看 `/proc/<pid>/status` 的 SigIgn）直接发 SIGTERM。
- **哈希取执行时的。** 每个进程第一次跑到一个文件时就记下它的内容哈希；录制中途改了文件，run 会标出来，之后叠图时这个文件也算「改过」。

### 读运行时图要知道的

- **「调用方」是最近的一个仓库内的帧。** 穿过仓库外代码（框架的事件循环、库里的回调）的调用会显示成直接调用。
- **调用次数高的多半是轮询**，不等于重要。
- **case 自己的代码例外**：入口脚本那一层目录里的 `.py` 在栈上当调用方。case 里定义、被仓库回调的函数（Flask 的视图）再调仓库函数时，调用方记成 `<外部代码>/脚本名`，和 scan 不扫的 examples/ 一样不上图，不会画成 `dispatch_request → jsonify` 这种并不存在的动态分派边。
- 栈深超过 2000 时砍半，极深递归下调用方可能不准。

---

## 分阶段

一次运行往往是「加载 → 处理请求 → 退出」。切成**阶段**之后可以只看其中一段，启动时的初始化不会混进来。两种办法，可以一起用：

1. **按函数切**：`--phase 名字=函数`。哪个进程第一次进入这个函数，就在那一刻切到这个阶段；别的进程 50 ms 内跟上，触发的线程停 0.1 s 等它们。不用改被录的脚本，「一条阻塞的 python 命令」也能分出加载 / 推理 / 关闭。函数写成 `模块:qualname`（查静态索引，继承来的方法也认，`Omni.close` 会认成 `OmniBase.close`），或 `文件路径:qualname`（不在索引里的文件也行，比如 examples/ 下的入口）。
2. **在 case 脚本里写**：往 `$CODESTRATA_OUT/PHASE` 写一个阶段名。适合服务类的 case：健康检查通过后写 `serving`。

第一次切之前的那段叫 `start`。用 `--phase` 切时，每个阶段整个 run 只切一次：同一个函数不能反复切，也切不回早先的阶段；case 脚本写 PHASE 可以切回早先的阶段（时间条上这个阶段就有几段）。

```bash
# 离线脚本：不改脚本，按函数切
codestrata trace <repo> --case offline \
    --phase generate=vllm_omni.entrypoints.omni:Omni.generate \
    --phase shutdown=vllm_omni.entrypoints.omni:Omni.close -- bash run_single_prompt.sh

# 服务：case 脚本里（服务就绪后）写 PHASE
[[ -n "${CODESTRATA_OUT:-}" ]] && { echo serving > "$CODESTRATA_OUT/PHASE"; sleep 2; }
codestrata trace <repo> --case demo -- bash case.sh
codestrata serve <repo> --hot demo@serving       # 再勾「只看跑到的」，得到单独排版的运行时图
```

页面上「时间」一行列出各阶段的按钮；图上用绿色 ▶ 和红色 ■ 标出阶段的起点和终点（`--phase` 的触发函数所在的节点）。

---

## 管理 run

静态分析只有一份，随时 `scan` 重建；运行记录不能重建——一次录制往往是几分钟 GPU。所以每次 `trace` 都存成一个新的 **run**（`.codestrata/runs/<时刻>-<case>/`），同名 case 重录也不覆盖：今天录 MiniCPM、明天录 Qwen，两份都留着，随时叠到图上。数据格式见 [design/run-format.md](design/run-format.md)，设计决策见 [design/decisions.md](design/decisions.md)。

### run 里有什么

- **原始数据，永久保留**：各进程的分片（`parts.tar.gz`）、case 脚本和命令里提到的配置文件（`files/`）、`run.json` 和 `detail.json`（git、Python 和包的版本、GPU、原样命令、环境变量）、时序事件的原始日志（`events/raw.tar.gz`）。
- **派生数据，可以用 `runs merge` 从原始数据重算**：计数（`counts.json.gz`）、整理好的时序（`events/spans/`）。

### 代码改了，老 run 照样能用

计数按 `文件:首行号` 存，打开时才映射到当前的索引上：哪些文件在录制之后改过会逐个标出来（页面顶部的横幅），而不是整个 run 作废；改过的文件里，按录制时记下的函数名（qualname）把次数挪到函数现在的行号上，挪下去几行、加了注释都对得上。（被录的 Python 是 3.10 时没有 `co_qualname`，改过的文件里的次数挪不回去。）

### 怎么指定一个 run（RUN 的写法）

- 完整的 run id，比如 `20260929-221354-hello`；
- 或 case 名：取它最新一次完整录完的；没有的话取最新一次录了一部分的，并打印提示；
- 后面可以加 `@阶段`（`demo@serving`），或 `@t=起-止`（单位微秒，要求这个 run 录了事件）。

`serve --hot`、`runs show` 都认这个写法。页面上选的 run 记在地址里（`#run=<id>@<阶段>`），刷新、复制地址再打开都还是它。

### runs 命令

```bash
codestrata runs <repo> ls [--case C]          # 按 case 分组：状态、时长、进程数、git、录制后改过几个文件、大小、有没有时序、标签、备注
codestrata runs <repo> show RUN               # 详情：阶段、进程、Python 和包的版本、GPU、存下的文件、文件相对当前代码的状态、复刻命令、继承的环境变量
codestrata runs <repo> tag RUN T…             # 加标签；untag 去标签
codestrata runs <repo> note RUN TEXT          # 写备注（覆盖原来的）
codestrata runs <repo> rm RUN_ID… [--yes]     # 删 run：只认完整的 run id；还在录的删不了；不在终端里运行时必须加 --yes
codestrata runs <repo> rm RUN_ID --events-only  # 只删时序事件
codestrata runs <repo> merge RUN              # 从原始数据重算计数和时序；录制中断时用它把散着的分片合起来
```

### 存储

- `runs/` 可以是软链（比如指到大盘）。**`.codestrata/` 里除了 `runs/` 都能随时删掉重建**；`runs/` 删了就没了。
- 老版本的 `trace-<case>.json` 第一次被读到时自动迁成 run（原文件逐字节留在 run 的 `legacy/` 里）。

### 复刻

每个 run 存下录制时原样的 codestrata 命令和所在目录（`cd <目录> && codestrata trace …`，照抄就能再录一次），以及 shell 里和跑模型、找解释器有关的环境变量——命令会继承它们，光看命令复刻不出来：

- 前缀是 `CUDA_`、`VLLM_`、`PYTORCH_`、`TORCH_`、`NCCL_`、`HF_`、`TRANSFORMERS_`、`TOKENIZERS_`、`OMP_`、`MKL_`、`NVIDIA_`、`TRITON_`、`XLA_` 的；
- 以及 `PATH`、`PYTHONPATH`、`LD_LIBRARY_PATH`、`VIRTUAL_ENV`、`CONDA_PREFIX`、`CONDA_DEFAULT_ENV`、`PYTHONHASHSEED`。

名字像密钥的（`HF_TOKEN`、`VLLM_API_KEY` 这类）一律不记；值里 URL 带的账号密码、命令里 `--api-key X` 这类选项的值，在网页上显示时隐去。

在哪复制：网页上 run 按钮旁边的「复刻」、「?」帮助里「这次跑了什么 → 复制」，或者 `runs show`。老 run 没存原始命令的，按 run 里存的参数拼一条并注明。复刻不是万能的：只记白名单里的环境变量，换一台机器照抄不一定能跑。

---

## 时间轴和时间顺序

这两样都要 run 录了时序事件：`trace` 加 `--events`，被录的 Python 是 3.12+。事件只记**跨文件**的调用：每次调用的起止时刻，返回 / 挂起 / 恢复按帧配对，同一线程里交错的 asyncio 协程也配得对。原始日志永久留在 `events/raw.tar.gz`，整理好的在 `events/spans/`（`runs merge` 可重建）；不要了用 `runs <repo> rm <id> --events-only`。

CLI 的 `trace` 默认**不**录事件；主菜单的录制表单里「录时序事件」默认勾上。

### 时间轴（工具栏「时间」）

- 阶段按钮 + 一条从 run 开头到结尾的时间条，阶段是条上的色段（切走又切回来的阶段有几段）。点按钮或色段 = 只看这个阶段。没录事件的 run 只能选阶段。
- 录了事件的 run 还能看**任意一段时间**：拖两头的把手、拖中间平移、在空白处拖出一段；方向键挪把手。拖到和一个阶段对得上就当成那个阶段。地址里写成 `@t=起-止`（微秒），`--hot` 也认。
- 条可以缩放：滚轮以鼠标处为中心缩放、Shift+滚轮平移，点阶段按钮自动放大到它，「全程」回到整个 run。
- 一段时间里的次数按这段时间里的事件现算，所以**只含跨文件的调用**（横幅上写明）；录制时合成一行的连续调用（轮询这种，一行能盖几十秒）按次数均匀摊在它盖住的时间上，是近似；阶段边界附近的调用可能算进相邻的阶段。

### 时间顺序（「边」一行里的开关）

- 这次跑到的边按**第一次被调用**的先后上色（早 → 晚，蓝 → 紫 → 橙），边上标序号 1…N：控制流第一次走到这条边的先后，就是讲这条调用链时的顺序。
- 按名次上色而不是按时刻：模型加载这种长时段会把按时刻插值的颜色都挤到一头。
- 同一个进程里从头到尾一直在反复调用的（轮询、每个 token 都走一遍的），序号后面带 ↻，它的序号只说明从什么时候开始。
- 跟着阶段、时间段、切面和其他开关变。
- 只在叠了一个录了事件的 run 时出现。

---

## 读代码

![全文窗口里 Ctrl+点击 AsyncOmniEngine，跳到它的定义，旁边一栏按文件列出所有引用](images/viewer.png)

### 全文窗口

从文件树的「全文」、源码片段的「整个文件」或搜索结果的「代码」打开：整个文件带左侧符号大纲，能高亮 Python、Triton、C/C++、CUDA（serve 里要装 `[highlight]`）。serve 模式下头上有「编辑器打开」，让本机编辑器跳到这一行。

### Ctrl（Mac 上 ⌘）+ 点击

全文窗口和详情面板的源码片段里，按住 Ctrl 能点的名字会带下划线。

- 点一个名字跳到它的定义，「← 返回」回到点的地方。
- 点一个定义，旁边一栏列出所有引用它的地方（调用在前，同一行的几处合成一条，按文件分组），点哪条跳哪条。
- 名字指向哪由 scan 时写下的 `.codestrata/xref.json` 给出：import（包括经 `__init__.py` 再导出的，追到真正定义的地方）、`模块.函数`、`类.方法`、`self.` / `cls.` / `super()`（按 C3 MRO 在仓库里的基类里找）、`self.x = …` 定义的实例属性；局部变量会遮住同名的全局名字。
- **确定不了的不给链接——宁可不跳，也不跳错。** 通过别的对象调用的方法（`engine.generate()`）不知道对象类型，引用列表里单列一组「同名的 `.generate`（没确认对象类型）」。`x = Foo(); x.bar` 这种也不跳；继承了仓库外类（如 torch）的，`self.xxx` 走到那个基类就放弃。
- 文件在 scan 之后改过，行列号就对不上了：那个文件不给 Ctrl+点击，重新 scan 即可。

### 文件内查找

全文窗口里 Ctrl / ⌘+F，或头上的「查找」。和 VS Code 一样：区分大小写（Aa，Alt+C）、全字匹配（ab，Alt+W，按 VS Code 的分隔符算词）、正则（.*，Alt+R）三个开关；Enter / Shift+Enter（F3 / Shift+F3）在匹配之间跳，右边是「第几个 / 共几个」，Esc 关掉。选中一段字再 Ctrl+F 就拿它当词。转到定义、返回换了文件时查找栏留着、按新文件重找。标记用浏览器的 CSS Custom Highlight，不改代码的 DOM，Ctrl+点击照常能用。

### 搜索栏

页面右边一栏，按 `/` 或 Ctrl / ⌘+K 跳过去；筛选：全部、模块、文件、类 / 函数。

- 按名字找：函数看它自己的名字（方法也看类名），文件看文件名，模块看最后一段；词里写了 `.` 或 `/` 才按路径找（`entrypoints/`、`engine.async`）。
- 点结果先回到图上，展开到它所在的模块并选中，再在下面的详情里展开到它；「代码」按钮直接开全文窗口。图上包含命中项的节点会高亮。

---

---

## 主菜单 codestrata app

不想敲命令，`codestrata app` 在浏览器里打开一个主菜单：

- **「打开文件夹…」** 挑仓库加进清单。每个项目一张卡片、三个按钮：
  - **静态扫描 / 重新扫描**：先在对话框里勾要扫的目录（仓库里的包、`src/` 下的包、tests/、examples/ 都列出来，扫哪些你自己选，有全选 / 全不选；重新扫描时按上次的选择勾好）。
  - **录制运行…**：填命令、执行目录、case 名、超时、阶段（阶段的函数名能补全）、环境变量；「更多」里有备注、附带存下的文件、录时序事件（默认勾上）。录过的默认照最近一次填好，也可以从最近 20 个 run 里另选一个，或者从空白开始。
  - **打开图**：替你起一个 `codestrata serve`（自动挑端口），页面左上角有「← 主菜单」。
- 扫描和录制的输出实时显示，能中途「停止」。代码落后于索引时卡片上提示「之后改过 N 个文件，建议重新扫描」。从主菜单重新扫描后，它会替你重启图服务。
- 「移除」只改清单，不动仓库。

**口令和安全**：主菜单能在本机执行命令，所以只监听 127.0.0.1、要带口令。第一次用终端里打印的链接打开（带 `?t=…`），浏览器记住之后直接访问 `http://127.0.0.1:8930/` 就行；不带口令访问只会看到一页「请用终端里的链接」。主菜单的接口要同时带口令 cookie 和 `X-Codestrata` 头，缺一样就是 403。口令存在 `~/.config/codestrata/app-token`，项目清单在 `~/.config/codestrata/projects.json`（跟 `$XDG_CONFIG_HOME` 走）。

**在另一台机器上用**（`ssh -L 8930:127.0.0.1:8930 …`）时加 `--proxy`：「打开图」也经 8930 转发，只要这一条隧道。代价是图页面和主菜单同源，少了一层隔离（图页面里要是有 XSS，就能调主菜单的接口），所以默认不开。

Ctrl+C 停主菜单时，会等还在跑的扫描、录制收尾，并一起停掉由它起的图服务。主菜单被 SIGKILL 时，这些进程会留下来，没人收。

其他参数：`--port`（默认 8930）、`--no-browser`（只打印带口令的链接，不自动开浏览器）。

---

## 命令参考

每个子命令都有 `--help`。

| 命令 | 做什么 | 参数 |
|---|---|---|
| `scan [repo]` | 静态扫描 + 交叉引用，打印默认切面上每个节点的架构高度 | `--roots DIR…` 扫哪些目录（不给就自动探测；`--roots .` 取根目录直接放着的脚本）<br>`--depth auto\|N` 默认切面<br>`--expand DIR` 在默认切面上额外展开，可重复 |
| `app` | 浏览器主菜单 | `--port`（默认 8930）<br>`--no-browser`<br>`--proxy` |
| `serve [repo]` | 本地网页 | `--port`（默认 8900）<br>`--hot RUN` 页面打开时先叠哪个 run<br>`--roots`（收但不起作用）<br>隐藏参数 `--home` 给主菜单用 |
| `trace [repo] --case NAME [...] -- CMD` | 跑一次命令、录下真实调用（子进程一起录），存成新的 run | `--case`（必填）<br>`--cwd DIR`<br>`--timeout S`<br>`--stop-grace S`（默认 90）<br>`--tag T`、`--note TEXT`<br>`--env K=V`（可重复）<br>`--attach FILE`<br>`--events`<br>`--phase NAME=FUNC`（可重复）<br>`--roots` |
| `runs <repo> ls [--case C]` | 按 case 分组列出 run | |
| `runs <repo> show RUN` | 一个 run 的详情和复刻命令 | |
| `runs <repo> tag\|untag RUN T…` | 加 / 去标签 | |
| `runs <repo> note RUN TEXT` | 写备注（覆盖） | |
| `runs <repo> rm RUN_ID…` | 删 run（只认完整 id） | `--yes`、`--events-only` |
| `runs <repo> merge RUN` | 从原始数据重算计数和时序 | |

RUN 的写法见[管理 run](#管理-run)。

---

## 输出文件

| 位置 | 内容 | 谁写 | 能否重建 |
|---|---|---|---|
| `<repo>/.codestrata/index.json`、`symbols.json`、`xref.json`、`graph.json` | 静态分析结果 | `scan` | 随时 |
| `<repo>/.codestrata/runs/<YYYYmmdd-HHMMSS>-<case>/` | 一次录制 | `trace` | **不能** |
| `<repo>/.codestrata/.gitignore`、`README.txt` | 自动生成：`.gitignore` 里是 `*`，让被分析仓库的 `git status` 保持干净；README.txt 提醒 `runs/` 不能重建 | 自动 | – |
| `~/.config/codestrata/`（跟 `$XDG_CONFIG_HOME` 走） | 主菜单的项目清单、口令 | `app` | – |

scan、serve、trace 不往 `~/.config` 写东西。

---

## 常见问题

- **`pip install codestrata` 装上的东西不对。** PyPI 上的同名包是别人的，要从 git 装，见[安装](#安装)。
- **trace 报 `ModuleNotFoundError`，run 显示 `失败（一个函数都没录到）`。** 命令用的是 PATH 上的 `python`，被分析的仓库得在那里 import 得到：先 `pip install -e .`。注意这时 trace 最后仍会打印「叠到图上：codestrata serve . --hot …」，别被误导。失败的 run 会留在 `runs ls` 里，用 `codestrata runs . rm <完整 run id> --yes` 删掉。
- **`codestrata trace --case x python demo.py` 报 `--cwd 不是一个目录：None`。** 忘了 `--`：没有它，`python` 被当成了仓库参数。写成 `codestrata trace --case x -- python demo.py`。（报错信息本身有误导，是个小 bug。）
- **命令里的相对路径找不到。** 命令在仓库根目录执行，不在当前目录；脚本在当前目录就加 `--cwd .`。
- **serve 报 `OSError: [Errno 98] Address already in use`。** 8900 被占了，加 `--port N` 换一个。别用 `--port 0`：它会打印 `http://127.0.0.1:0/`，而不是实际拿到的端口。（app 遇到同样的情况会好好提示换端口。）
- **serve 说没有 index.json。** 先 `codestrata scan`。
- **重新 scan 了，页面没变。** 重启 serve。
- **页面上没有「时间顺序」、时间条拖不动。** 这个 run 没录事件：重录时加 `--events`，并确认被录的 Python 是 3.12+。
- **主菜单打开是一页「请用终端里的链接」。** 第一次要用终端打印的带 `?t=…` 的链接打开。
- **在远程机器上用。** serve 和 app 只监听 127.0.0.1，用 `ssh -L` 转发端口；app 加 `--proxy` 就只要转一个端口。

---

## 实测数字

测于 2026-09-29。机器：Intel Core i9-14900KF（24 核 32 线程）、125 GiB 内存、NVMe SSD、Ubuntu 24.04、Python 3.12.3。scan 只用一个核（用户态时间 ≈ 墙钟时间）。

### scan

每个仓库复制一份（不含 `.git`）再扫；第二次运行的时间，重复运行差在 ±0.08 s 以内。清掉页缓存后冷启动几乎一样（vllm-omni 多 0.6 s），时间基本都花在 CPU 上。

| 仓库 | 自动探测挑的目录 | `.py` 文件 | 行数 | 模块 / import 边 | 符号 | 默认切面：节点 / 边 | 用时 | 峰值内存 |
|---|---|---|---|---|---|---|---|---|
| gaussian-splatting | `arguments gaussian_renderer lpipsPyTorch scene` | 12（仓库共 34） | 1,802 | 12 / 11 | 102 | 10 / 8 | 0.09 s | 27 MB |
| 同上，`--roots . arguments gaussian_renderer lpipsPyTorch scene utils` | （指定） | 26 | 3,760 | 26 / 38 | 171 | 22 / 35 | 0.14 s | 28 MB |
| flask | `src/flask` | 24 | 9,513 | 24 / 71 | 416 | 22 / 69 | 0.17 s | 29 MB |
| codestrata 自己 | `codestrata` | 20 | 11,022 | 20 / 48 | 495 | 20 / 48 | 0.41 s | 35 MB |
| gsplat | `gsplat` | 125 | 40,696 | 125 / 233 | 1,125 | 53 / 113 | 0.64 s | 41 MB |
| nerfstudio | `nerfstudio` | 203 | 47,643 | 203 / 727 | 1,824 | 35 / 145 | 1.00 s | 39 MB |
| vllm-omni | `vllm_omni` | 1,648 | 589,746 | 1,648 / 4,439 | 23,730 | 60 / 343 | 12.81 s | 167 MB |

- 吞吐：vllm-omni 每秒 4.6 万行，nerfstudio 4.8 万，gsplat 6.4 万，flask 5.6 万，codestrata 自己 2.7 万；用时大致随代码量线性增长。`codestrata --help` 本身 0.03–0.04 s。
- 时间花在哪（vllm-omni）：解析 8.24 s，交叉引用 4.06 s，写 JSON 0.20 s。
- vllm-omni 的输出：`index.json` 0.97 MB，`symbols.json` 13.4 MB，`xref.json` 16.1 MB（31 万处能 Ctrl+点击的名字）。
- 加上 `graph.json` 之后（2026-09-30，vllm-omni 的 `examples tools vllm_omni`，1,799 个文件，同一份拷贝前后各跑两次）：用时 13.9 s → 16.9 s，峰值内存 189 MB → 288 MB；`graph.json` 12.5 MB（2.9 万处定下了被调方的调用、34 万处定不下的，其中 18.7 万处是语法触发的特殊方法），读进来 0.1–0.2 s。
- vllm-omni 仓库共有 3,260 个 `.py`，tests、examples、benchmarks 这些被有意跳过。
- nerfstudio 扫描时 stderr 上会出现 3 次 `SyntaxWarning: invalid escape sequence '\,'`，来自它自己的源码，不影响结果（解析失败仍是 0）。

### trace 开销

纯 Python 的 CPU 负载，5 次交替运行取中位数（取最小值得到的倍数基本一样）。「循环」是负载自己计时的那一段，「整条命令」是 `/usr/bin/time` 量的全程。

| 负载 | 仓库内调用 | 跨文件调用 | 不录：循环 / 整条命令 | `trace` | `trace --events` |
|---|---|---|---|---|---|
| A：flask 测试客户端发 9000 个请求 | 648,200 | 405,121 | 2.446 s / 2.52 s | 3.319 s（**1.36×**）/ 3.49 s | 4.077 s（**1.67×**）/ 9.39 s（**3.73×**） |
| B：codestrata 扫描 nerfstudio | 527,059 | 211 | 0.965 s / 0.99 s | 1.470 s（**1.52×**）/ 1.58 s | 1.544 s（1.60×）/ 1.67 s |
| A，但录的是一个无关的仓库 | 0 | 0 | 2.444 s | 2.520 s（**1.03×**） | – |

- `trace` 每次仓库内调用约多花 1–1.4 µs，所以调用越密倍数越大；仓库外的代码几乎不花成本（1.03×），和 `sys.monitoring` 的 DISABLE 设计相符。
- **`--events` 的整理可能比程序本身还久**：A 的命令 4.2 s 跑完后，trace 又花了约 5.2 s 把 81 万行事件整理成 40.5 万段（压缩后 4.3 MB）。单独用 `runs merge` 重做要 3.11 s、357 MB 内存。这个成本随跨文件调用的次数增长：B 只有 211 次跨文件调用，`--events` 几乎不加时间。
- 开发时测过、这次没有复测：「时间顺序」第一次加载一个 run，sympy 158 万段用 2.2 s；之后换阶段 9 ms。
- 2026-09-30 起 trace 还记每次调用写在调用方的哪一行（`func_lines`），上表是加之前测的。加了之后：全是跨函数调用的极端负载（300 万次，函数体一两行），3.12 上 3.4 s → 4.0 s（+19%）、3.10 上 4.3 s → 4.85 s（+11%）；vllm-omni MiniCPM 的启动阶段（约 2 万次仓库内调用、70 s，主要在加载模型）前后都是 70.9 s 左右，看不出差别。

---

## 已知限制

严重度站在新用户角度估：**高** = 第一天就可能碰到；**中** = 用深了会碰到；**低** = 边角情况。

| 严重度 | 局限 |
|---|---|
| 高 | **只看 Python。** 静态图只收 `.py`；C/C++/CUDA 只能浏览，不进 import 图（pybind、`torch.ops` 这类跨语言的边没有）；运行时只 hook Python 函数。 |
| 高 | **录制只支持 Linux**，别的系统上 `trace` 直接拒绝。其余命令在别的系统上能用但只在 Linux 上跑过；「还在录吗」的判断靠 `/proc`，没有 `/proc` 的系统上看别处正在录的 run 会显示成「中断」。 |
| 高 | **`--events`、时间顺序、任意时间段都要被录的 Python 是 3.12+**（`sys.monitoring`）。3.10 和 3.11 退回 `sys.setprofile`：仓库内的调用开销差不多，但仓库外的代码也要付回调的开销（3.12+ 上几乎为 0；3.10 上一个只调标准库的循环慢了约 8 倍）；3.10 还没有 `co_qualname`，录完一改代码，这个文件里的次数就挪不回函数上。 |
| 高 | **serve 只在启动时读索引。** 重新 scan 之后，图和搜索要重启 serve 才更新（Ctrl+点击会自动换新；新录的 run 不用重启）。 |
| 高 | **读运行时图要知道：** 「调用方」是最近的仓库内的帧，穿过框架、事件循环的调用会显示成直接调用；调用次数高的多半是轮询，不等于重要；import 触发的模块顶层执行不算调用。 |
| 高 | **自动探测优先挑带 `__init__.py` 的顶层包（或 `src/` 下的包）**，根目录的脚本、没有 `__init__.py` 的目录通常挑不中，要用 `--roots` 加。 |
| 中 | **跳转很保守，没有类型推断。** `x = Foo(); x.bar` 不给跳；继承了仓库外类的，`self.xxx` 走到那个基类就放弃。 |
| 中 | **时间段的次数只算跨文件的调用**；合成一行的连续调用按次数均匀摊开，是近似；阶段边界附近的调用可能算进相邻的阶段。 |
| 中 | **`--events` 的整理成本随跨文件调用次数增长**，调用密集的负载上可能比程序本身还久（见[实测数字](#实测数字)）。 |
| 中 | **`--phase` 每个阶段整个 run 只切一次**，同一个函数不能反复切，也切不回早先的阶段（case 脚本写 PHASE 可以）；每切一次让触发的线程停 0.1 s。 |
| 中 | **节点会挪位置。** 分层跟着叠的 run 变，换 run 时节点会上下挪；同一个切面在不同窗口宽度下排版也不同。 |
| 中 | **scan 的几个盲点：** `from x import *` 有 import 边，但不知道带进了哪些名字；从 `__init__` 再导出的名字，import 边指向 `pkg.__init__` 而不是真正定义它的文件——这两种情况下，经它们调到的函数在展开到文件时显示成动态分派（假阳性）；只认 `if TYPE_CHECKING:` 的 if 分支。 |
| 中 | **默认切面的阈值**（10% / 30 / 80 / 12）只在少数几个仓库上调过；自动拆分只看代码行数，不看依赖结构。 |
| 中 | **trace 注入的 `sitecustomize.py` 会遮住环境里原有的 `sitecustomize`**（不会接着调用它），依赖它的程序（有些 conda / HPC 环境）录制时行为可能不同。 |
| 中 | **复刻不是万能的**：环境变量只记白名单里的；密钥只按名字的形状认；换一台机器照抄不一定能跑。 |
| 中 | **run 不能重建。** `.codestrata/runs/` 是唯一一份（可以软链到大盘）。 |
| 中 | **还没在 GPU 录制上验收过。** 自动测试都在 CPU 上的假服务上跑；事件的开销没在真模型上测过。 |
| 中 | **安全模型：** serve 没有鉴权，自定义头只挡浏览器里别的网页，挡不住本机进程；app 有口令；`--proxy` 让图页面和主菜单同源，少了一层隔离。 |
| 中 | **`serve` 的 `--roots` 不起作用。** |
| 低 | 端口被占时 serve 直接抛异常；`serve --port 0` 打印的不是实际端口；忘了 `--` 时报错有误导。 |
| 低 | Host 检查要求带端口号，所以 `--port 80` 用不了。 |
| 低 | 主菜单被 SIGKILL 时，它起的任务和 serve 会留下来，没人收。 |
| 低 | 栈深超过 2000 时砍半，极深递归下调用方可能不准；只包了 `os.execv` / `os.execve`。 |

---

## 前端和 API

前端在 `codestrata/web/`，普通 HTML / CSS / JS，零构建、不要 npm。数据全部经 `web/ds.js` 从 serve 的 `/api/*` 取。

serve 提供的 API（agent 也可以直接调）：

```
GET  /api/graph?open=a,b&w=&run=   一个切面上的静态图 + 某个 run 的叠加（open 缺省是默认切面；w 是图框宽度；
                                   run 是 run id 或 case 名，可加 @阶段或 @t=起-止）
GET  /api/runs                录下的所有 run（新的在前）+ 打开页面时默认选哪个
GET  /api/seq/edges?run=&open=  每条边在 run 选的阶段里第一次 / 最后一次被调用的时刻和次数（「时间顺序」用）
GET  /api/edge?a=&b=          一条边：用到了对方哪些符号、runtime 调了哪些、哪些只 import（也接受 run=）
GET  /api/refs?t=             一个定义被哪些地方引用（Ctrl+点击定义时的列表）
GET  /api/symbol/<key>        符号源码
GET  /api/file?f=             整个文件（高亮）+ 符号大纲 + 能 Ctrl+点击的名字
GET  /api/outline?f=          一个文件的符号大纲（含方法），文件树按需展开
GET  /api/search-index        搜索栏要的全部名字（模块、文件、类 / 函数）
GET  /api/reveal?node=&open=  让一个模块在图上露出来要展开哪些目录
GET  /api/app                 从主菜单打开时主菜单的地址
GET  /api/open?f=&l=          让本机编辑器跳到 file:line（要带 X-Codestrata 头）
GET  /code/<path>?l=N         整个文件，带行号锚点
```

安全：只监听 127.0.0.1；Host 头必须是本机这个端口（防 DNS rebinding，所以 `--port 80` 用不了）；所有路径 realpath 后必须落在仓库内。serve 本身没有鉴权：`X-Codestrata` 头只挡浏览器里别的网页，挡不住本机进程。

---

## 给开发者

这份手册只讲怎么用。开发相关的内容各有一处：

- 测试怎么跑、各自覆盖什么、代码怎么组织：[ARCHITECTURE.md](ARCHITECTURE.md)。
- 设计决策和理由，包括踩过的坑（调用栈进出都要订阅、按文件名缓存、忽略 SIGINT 的进程）和负面结论（SCC 缩点不能用来分层）：
  [design/decisions.md](design/decisions.md)。
- run 目录的格式（接别的语言、别的录制端用）：[design/run-format.md](design/run-format.md)。
