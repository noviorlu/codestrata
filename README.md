# codestrata

给一个 Python 仓库画两张图：

- **总图（static）** —— 全仓的模块级架构。层次不是手工标的，而是由 import 出入度算出的
  「架构高度」`(out−in)/(out+in)`：+1 是入口、−1 是纯被依赖的叶子。
- **hot 图（runtime）** —— 跑一个真实 case（仓库自带的 demo / example），
  把实际发生的调用叠在**同一张图的同一套坐标**上。于是「这个 case 走了哪条路」一眼可见。

两张图共用节点与布局，差别只在数据来源：一个是 AST，一个是运行时 hook。

点任意节点可以看到该符号的源码（带真实行号），本地模式下还能一键跳进编辑器。

## 箭头：一条依赖到底承载了什么

import 了不等于用了，用了不等于这次跑到了。每条边都拿「静态引用 × runtime 调用」交叉，
点箭头能看到具体是哪些函数 / 类、在哪一行、被谁调了几次：

| 图上 | 含义 | 来源 |
|---|---|---|
| 灰实线 | import 了，并且代码里真的引用了对方的符号 | ast：绑定名的每一次读取 |
| 灰虚线 | 只 import，一个符号都没引用 | ast，再细分原因（见下） |
| 橙色，粗细 ∝ log(次数) | 这次 case 真的跨这条边调用过 | runtime：函数粒度的 caller→callee |
| 橙虚线 | 只在 runtime 出现，静态 import 图里没有 | 插件 / `importlib` / 注册表——静态分析的盲区 |

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
- **子进程数据不丢。** 拦截 `os._exit`（multiprocessing 的 fork 子进程这样退出）、每 10 秒落盘
  （被 SIGKILL 最多丢 10 秒）、fork 后清零计数（不重复计入父进程）。
- **分阶段。** case 脚本往 `$CODESTRATA_OUT/PHASE` 写一个名字，各进程 1 秒内切换；之后
  `--hot 名字@serving` 只看处理请求的那一段，启动时的初始化不会混进来。

```bash
# case 脚本里（服务就绪后）：
[[ -n "${CODESTRATA_OUT:-}" ]] && { echo serving > "$CODESTRATA_OUT/PHASE"; sleep 2; }
codestrata trace <repo> --case demo -- bash case.sh
codestrata serve <repo> --hot demo@serving       # 勾「只看跑到的」得到单独排版的 hot 图
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
| 运行：哪个 case 实际调到了什么 | `trace`（runtime hook） | `.codestrata/` | 重跑即可 |
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
GET  /api/file?f=             整个文件（高亮）+ 符号大纲
GET  /api/edge?a=&b=          一条边：引用了哪些符号、runtime 调了哪些、哪些只 import
GET  /api/open?f=&l=          让本机编辑器跳到 file:line
```

## 用法

```bash
codestrata scan  <repo> [--depth N] [--expand DIR]   # 静态扫描；默认切面按规模自动拆分
codestrata serve <repo> [--hot CASE[@阶段]]    # 本地部署前端
codestrata trace <repo> --case NAME -- CMD    # 跑一个 case，记录真实调用（子进程一并 trace）
codestrata tasks <repo> [--write]             # 待解读 + 输入包
codestrata note  <repo> <模块> <file.md>       # 写回解读（总览用 _overview）
codestrata check <repo> [模块 ...] [--fix]     # 机器核对解读：过期、引用漂移、名字 / 路径不存在
                                              # --fix 把只是挪了位置的引用改到新行号（不去掉过期标记）
codestrata graph <repo> [--hot CASE]          # 导出单文件
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

一个负面结论值得记下：**SCC 缩点不能用来分层**。Python 的循环 import 会让强连通分量退化——
在 vllm-omni 上 30 个包有 20 个塌进同一个环，分层信息全丢。启发式在这里胜过图论正解。

## License

MIT
