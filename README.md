# codestrata

给一个 Python 仓库画两张图：

- **总图（static）** —— 全仓的包级架构。层次不是手工标的，而是由 import 出入度算出的
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

## 前端：一套代码，两种模式

前端在 `codestrata/web/`，普通 HTML/CSS/JS，零构建、不要 npm。`web/ds.js` 一层决定数据从哪来：

```bash
codestrata serve .              # 本地部署：fetch /api/*，能写解读、能跳编辑器
codestrata graph .              # 单文件导出：数据内嵌，只读、离线、可以直接发给别人
```

serve 提供的 API（agent 也可以直接调）：

```
GET  /api/graph               静态图 + hot 叠加
GET  /api/tasks               待解读清单（自底向上）
GET  /api/pack/<模块>          给 agent 的输入包
GET  /api/notes/<模块>         解读 + 是否过期
PUT  /api/notes/<模块>         写回解读        ← agent 从这里介入
GET  /api/symbol/<key>        符号源码
GET  /api/file?f=             整个文件（高亮）+ 符号大纲
GET  /api/edge?a=&b=          一条边：引用了哪些符号、runtime 调了哪些、哪些只 import
GET  /api/open?f=&l=          让本机编辑器跳到 file:line
```

## 用法

```bash
codestrata scan  <repo>                       # 静态扫描
codestrata serve <repo> [--hot CASE]          # 本地部署前端
codestrata trace <repo> --case NAME -- CMD    # 跑一个 case，记录真实调用（子进程一并 trace）
codestrata tasks <repo> [--write]             # 待解读 + 输入包
codestrata note  <repo> <模块> <file.md>       # 写回解读
codestrata graph <repo> [--hot CASE]          # 导出单文件
```

## 状态

早期。已验证：AST 扫描（vllm-omni 1608 文件 / 4.5s / 0 失败）、高度分层（排序符合架构直觉）、
runtime trace（真值测试：返回后再调用、生成器恢复、异常展开三种情况下调用者都正确；
动态分派被正确识别为静态盲区）、边的五类归并、解读的写回与过期检测、serve 的路径越权防护。

trace 踩过的两个坑，写在这里免得重犯：
- 只订阅 `PY_START` 不订阅返回/展开，调用者会变成「上一个开始执行的函数」。
- 按 code 对象做缓存键是错的：code 对象**按内容**比较相等且不比 `co_filename`，
  几个空 `__init__.py`、或不同文件里同名同行同体的函数会被当成同一个。按文件名缓存。

一个负面结论值得记下：**SCC 缩点不能用来分层**。Python 的循环 import 会让强连通分量退化——
在 vllm-omni 上 30 个包有 20 个塌进同一个环，分层信息全丢。启发式在这里胜过图论正解。

## License

MIT
