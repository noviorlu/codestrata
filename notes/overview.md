---
written_by: claude-opus-5-5
target: _overview
kind: repo
code_sha: af9ffb5e80fb2086
status: draft
---

## 这个仓库做什么
codestrata 给一个 Python 仓库（论文代码、vLLM 这类开源框架）画两张**共用坐标**的图：总图来自静态分析（`ast`），hot 图来自跑一个真实 case 时的 runtime 记录。再留出一层给人或 LLM agent 写「为什么这样切、算法为什么这么写、该按什么顺序读」。

输入是一个仓库目录，加上可选的一条 case 命令；产出是 `.codestrata/` 下可重建的事实数据、仓库 `notes/` 目录下不可重建的解读，以及一个本地网页（`serve`）或一个单文件 HTML（`graph`）。

## 主干
一次典型使用里数据这样流过各模块：
1. `scan` 读全仓 `.py`，写出 `index.json`（包、边、高度）和 `symbols.json`（符号、边上的引用明细）。
2. （可选）`trace` 在 hook 下跑一条命令，写出函数粒度的 `trace-<case>.json`；子进程一并记录。
3. `payload` 把它们拼成前端要的数据：index 交给 `layout` 算坐标，trace 经 `trace.to_package_graph` 按当前 index 现算，源码交给 `highlight`，解读从 `notes` 取；点开一条边时由 `edge_detail` 把静态引用和 runtime 调用交叉成五类。
4. 交付二选一：`serve` 按请求提供 `/api/*` 和前端静态文件；`render` 把同一套前端和整份数据内联成一个 HTML。

`__main__` 只负责把子命令分派到上面这些步骤。

## 为什么分成这几层
- **入口**（+1）：`__main__`，一层很薄的 CLI。
- **中间**：`payload`（汇合点，唯一同时认识事实、runtime、坐标、源码、解读的模块）和 `serve`（HTTP 协议 + 安全边界）。
- **叶子**（−1）：`scan`、`trace`、`layout`、`highlight`、`notes`、`render`，每个只做一件事、彼此不 import。注意「叶子」的意思是被依赖、不依赖别人，不是「不重要」：数据的两个生产者 `scan` 和 `trace` 都在这一层。

最值得注意的两条边界：
- **事实 vs 解读。** `scan` / `trace` 的产出是缓存，随时删了重建；解读进版本库，不能重建。两者靠 `code_sha`（整份解读是否过期）和引用指纹（哪一处 `file:line` 漂了）绑在一起。
- **数据 vs 呈现。** `payload` 及其以下不知道 HTTP 和 HTML；`serve` 和 `render` 共用同一个 `payload`，所以 live 模式和导出版不会各长各的。

图上看不到的一块：前端在 `codestrata/web/`（五个 JS 文件，零构建），它不是 Python，所以不在图里。结构见 render 的解读。

## 阅读顺序
1. **scan** —— 先弄清「事实」是什么。读完能回答：图上每个框、每个箭头、每条虚线从哪来。
2. **layout** —— 事实怎么变成坐标。读完能回答：为什么这个包在这条泳道、这个位置。
3. **payload**，重点看 `edge_detail` —— 点开一个箭头看到的每一项从哪来。
4. **serve**，以及 render 解读里的前端结构 —— 数据怎么送进浏览器。
5. **trace** —— runtime 那一半，也是最难的一块（多进程、调用栈、帧的归属）。读完能回答：橙色是怎么来的、可信到什么程度、在哪些情况下会丢数据。
6. **notes** —— 解读层自己怎么运作：过期、派活顺序、机器核对。
7. **highlight**、**__main__** —— 需要时再看。
