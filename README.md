# codestrata

**仓库的运行路径工具：跑一次，看清这次运行在一个陌生的大仓库里走了哪条路、按什么顺序。**

codestrata 先静态扫描出一张按依赖分层的模块图，再把一次真实运行（脚本、pytest、起服务的 sh 都行）录下来的调用叠到同一张图上，在本机浏览器里看。每次录制都永久保存，可以随时叠上去。适合接手一个大仓库、想知道「一次请求 / 一次推理到底经过了哪些模块、按什么顺序」的时候用。

![按依赖分层的 vllm-omni 模块图，叠上一次真实运行的调用](docs/images/hero.png)

<sub>vllm-omni 的模块图：调用方在上、被依赖的在下，灰线是静态依赖。图里开着「时间顺序」：serving 阶段走过的边按第一次被调用的先后编号，从蓝经紫到橙红上色。</sub>

> [!IMPORTANT]
> 早期版本（0.1.0）。目前只支持 **Python** 仓库；运行记录的格式和叠加与语言无关，其他语言在计划中。
> **录制只支持 Linux**（别的系统上 `trace` 会直接说明并退出）；扫描、看图、查看别处录好的 run 在其他系统上也能用，但只在 Linux 上测过。
> 要 Python ≥ 3.10，没有必需的第三方依赖；`trace --events`（时间轴上的任意一段、「时间顺序」要用它）要求**被录的程序**跑在 Python 3.12+ 上。
> 所有服务只监听 `127.0.0.1`，在远程机器上用要走 `ssh -L`。

## 亮点

- **静态和运行时在同一张图上。** 每条边都分得清「只 import」「引用了」「这次真调到了」；代码里找不到引用的调用（插件、注册表、`importlib`）单独标成「动态分派」，正好照出静态分析的盲区。
- **录一次，一直用。** 每次录制存成一个 **run**，不覆盖旧的；代码改了，老 run 照样能叠。子进程、`setsid` 出去的服务、site-packages 里的代码都能录。
- **能看先后。** 按阶段（加载 / 处理请求 / 退出）或任意一段时间只看那一段；边按第一次被调用的先后编号。
- **层次是算出来的。** 按依赖自动分层，调用方在上、被依赖的在下；大仓库先显示到目录树的某一层，能就地展开、收起。

## 快速上手

要 Python ≥ 3.10 和 git。下面拿 [flask](https://github.com/pallets/flask) 当例子，扫描和录制加起来不到 1 秒。录服务、分阶段、主菜单、完整的命令参考见 **[docs/usage.md](docs/usage.md)**。

```bash
# 1. 安装。别用 pip install codestrata：PyPI 上同名的包是别人的
#    [highlight] 带上 Pygments，代码才有颜色
python3 -m venv .venv && source .venv/bin/activate
pip install 'codestrata[highlight] @ git+https://github.com/noviorlu/codestrata'

# 2. 拿一个仓库，静态扫描。pip install -e . 是给第 3 步用的：录的命令得能 import 这个仓库
git clone --depth 1 https://github.com/pallets/flask && cd flask
pip install -e .
codestrata scan

# 3. 录一次真实运行：-- 后面是你平时跑它的命令，在仓库根目录执行
#    --case 给这次录制起个名字；--events 多录调用的先后（被录的 Python 要 3.12+）
codestrata trace --case hello --events -- python -c "
from flask import Flask, jsonify
app = Flask('demo')
@app.route('/hi/<name>')
def hi(name): return jsonify(msg='hi ' + name)
c = app.test_client()
for n in ('a','b','c'): print(c.get('/hi/'+n).json)
"

# 4. 打开图，叠上这次运行。--hot 后面写 case 名，取它最近一次录完的（8900 端口被占就加 --port N）
codestrata serve --hot hello      # 浏览器打开 http://127.0.0.1:8900/
```

打开页面会看到 22 个节点按依赖分成几层，这次请求走过的边是橙色；点一条橙色的边，再点页面底部的「详情」栏，能看到这条边上调了对方哪些函数、各几次。
serve 开着时再录的 run，页面上方「运行」菜单里直接能选。不想敲命令，可以用 `codestrata app` 在浏览器里点按钮完成扫描、录制和打开图。
scan 和 trace 的产物都写在被分析仓库的 `.codestrata/` 里（自带 `.gitignore`）。

## 读图须知

运行时的图会误导人，看之前先知道这几条：

- **「调用方」是最近的一个仓库内的函数。** 穿过框架、事件循环、库里回调的调用，会显示成仓库内两个函数之间的直接调用。
- **次数高的多半是轮询**，不等于重要；一直在反复调用的边在「时间顺序」里带 ↻。
- **import 时执行模块顶层代码不算调用**，只被 import、一个函数都没被调过的模块不算「跑到了」。
- **动态分派有假阳性。** 经 `__init__.py` 再导出、`from x import *`、模块级 `__getattr__` 调到的函数，代码里找不到对应的引用，也会画成动态分派（flask 里橙虚线比实线还多，多数是这个原因）。

## 重点功能

### 一张图，两层数据

页首那张图就是主界面。**底下一层是静态依赖**：每个节点是一个模块或目录，纵向按依赖分成一条条横带（**泳道**）。仓库大时图上只画目录树的一个**切面**，默认最多 80 个节点；点节点左上角的 ＋ 就地展开成框，框头的 − 收回去。**上面一层是某次运行**：

| 图上 | 意思 |
|---|---|
| 灰实线 | import 了，并且引用了对方 |
| 灰虚线 | 只 import，一个符号都没用 |
| 橙实线 | 这次真的调用过，越粗次数越多 |
| 橙虚线 | 动态分派：跑到了，但代码里找不到对应的引用 |

叠了运行之后，分层按这次实际的调用重排，「这次走了哪条路」从上往下读就是。

### 点一条边：这条依赖到底承载了什么

![点开 entrypoints → engine 这条边，详情栏列出实际调用的函数、次数、调用处和定义处](docs/images/edge.png)

底部的详情栏列出这条边实际用到了对方的哪些函数和类、各被调了几次，并给出调用处和定义处的代码。上图里 `entrypoints → engine` 这次被调了 4383 次，其中 4371 次是 `try_get_output`——一个轮询。只 import 的边会说明原因（死 import、再导出、只用于类型注解……），见[边的种类](docs/usage.md#边的种类)。

### 时间轴：只看某一段时间

![在时间条上拖出一段，图上只剩这段时间里跑到的模块和边，并按先后编号](docs/images/timebar.png)

- **阶段**：`--phase serving=模块:函数` 表示这个函数第一次被调到时进入 serving 阶段，不用改被录的脚本；页面「时间」一行点一下只看那一段。
- **时间段**：录了 `--events` 的 run，还能在时间条上拖出任意一段。
- **时间顺序**：「边」一行里的开关，跑到的边按第一次被调用的先后编号 1…N。

### 其他功能

- **读代码**：从图上点进任意文件打开全文窗口，符号大纲、语法高亮、Ctrl+点击跳定义 / 列引用、Ctrl+F 查找，也能一键在本机编辑器打开（截图见 [读代码](docs/usage.md#读代码)）。
- **复刻**：每个 run 存下原样的命令、所在目录和相关环境变量，一键复制就能再录一次。见[管理 run](docs/usage.md#管理-run)。
- **主菜单**：`codestrata app` 在浏览器里选文件夹、点按钮扫描、录制、打开图。见[主菜单](docs/usage.md#主菜单-codestrata-app)。

## 它是怎么做到的

静态和运行时两份数据分开存、显示时才合并：静态分析随时能重做，运行记录只有一份、永久保留。

```mermaid
flowchart LR
  S["scan<br/>静态分析"] --> I[("index / symbols / xref")]
  T["trace<br/>运行时 hook"] --> R[("runs/")]
  I --> P["切面 + 分层 + 叠加"]
  R --> P
  P --> V["serve：本地网页"]
```

1. **静态分析。** 用标准库的 `ast` 解析每个 `.py`，记下谁 import 谁、实际用了对方哪些名字、类和函数在哪。
2. **分层。** 先去掉循环依赖里最轻的边，再按最长依赖链排层（Eades–Lin–Smyth 贪心去环 + 最长路分层）；叠了运行时，按这次的调用重排。
3. **录制。** 往 `PYTHONPATH` 塞一个 `sitecustomize.py`，命令起的**每个** Python 进程都自动挂上 hook。3.12+ 用 `sys.monitoring`，仓库外的代码第一次命中就关掉回调；只记仓库内函数之间的调用。
4. **叠加。** 打开时才按「文件:行号 + 函数名」把次数对回**当前**代码，函数挪了几行也对得上；被调的函数不在这条边的静态引用里，就算动态分派。

代码结构和数据格式见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/design/run-format.md](docs/design/run-format.md)。

## 实测

Intel Core i9-14900KF、Ubuntu 24.04、Python 3.12.3；scan 只用一个核。

| 仓库 | 扫描的 `.py` 文件 / 行数 | `scan` 用时 | 默认切面 |
|---|---|---|---|
| flask | 24 / 9.5k | 0.17 s | 22 个节点 |
| gsplat | 125 / 40.7k | 0.64 s | 53 个节点 |
| nerfstudio | 203 / 47.6k | 1.00 s | 35 个节点 |
| vllm-omni（`vllm_omni/` 包） | 1,648 / 590k | 12.8 s | 60 个节点 |

`trace` 每次仓库内调用约多花 1 µs：flask 测试客户端发 9000 个请求（65 万次仓库内调用）慢 1.36 倍，仓库外的代码几乎不花成本。`--events` 录完要整理事件，调用密的程序整理时间可能比程序本身还长。测法和完整数字见 [docs/usage.md](docs/usage.md#实测数字)。

## 已知限制

- **只支持 Python**：pybind、`torch.ops` 这类跨语言的调用看不到。
- **录制只支持 Linux**：它靠 `/proc` 认进程、找出 setsid 出去的服务并停干净。3.10 / 3.11 能录但没有 `--events`，仓库外的代码也要付回调的开销。
- **跳转保守、没有类型推断**：`x = Foo(); x.bar()` 不给跳。
- **重新 scan 之后要重启 serve**（新录的 run 不用重启）。
- **trace 注入的 `sitecustomize.py` 会遮住环境里原有的 `sitecustomize`**，依赖它的程序在录制时行为可能不同。
- **run 不能重建**：`.codestrata/runs/` 是唯一一份，删了就没了。
- **自动测试都在 CPU 上的假服务上跑**，没在 GPU 录制上验收过。

完整列表见 [docs/usage.md](docs/usage.md#已知限制)。

## 和其他工具的区别

- **OpenGrok / Sourcegraph / Hound / Zoekt** 给的是搜索和交叉引用，不知道一次运行实际走了哪条路。
- **Sourcetrail** 2021 年已归档；还在维护的 fork NumbatUI 明确禁用了 Python 索引。
- **profiler（cProfile、py-spy）** 告诉你时间花在哪，但不把调用放回仓库的架构里，也看不出调用的先后。

## 致谢

分层用的是 Eades、Lin、Smyth 的贪心去环启发式；源码高亮用 [Pygments](https://pygments.org/)。

## License

MIT，见 [LICENSE](LICENSE)。
