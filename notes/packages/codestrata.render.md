---
written_by: claude-opus-5-5
target: codestrata.render
kind: package
code_sha: bab38e5f56ee67d6
status: draft
refs: render.py:1@1b5c0234,render.py:17@628cbed4,render.py:26@70185c58
---

## 是什么
单文件导出：把 `codestrata/web/` 下的前端（HTML + CSS + 5 个 JS）和一份数据内联成一个 HTML，只读、离线、可以直接发给别人。

## 为什么这样切
和 `serve` 用的是**同一套前端文件**，唯一的差别是数据源：serve 时前端 fetch `/api/*`，导出时读内嵌的 `window.CS_EMBEDDED`。切换由 `web/ds.js` 完成，UI 代码本身不感知（render.py:1）。数据怎么组装是 `payload` 的事，它只管打包——所以它不依赖任何内部模块，只被 `__main__` 的 `graph` 子命令调用。

## 读法
只有一个函数 `export`；但要读懂它，得先知道它打包的前端长什么样（图上看不到，因为前端不是 Python）：

- `web/ds.js` —— 数据源层：live 走 `/api/*`，embedded 读内嵌 JSON；整个前端只通过它拿数据。live 能按切面重新要图（`graph(open)`），导出版只有导出时那一个切面、不能展开
- `web/graph.js` —— SVG 绘图：泳道、节点、边（边的颜色编码种类，选中用蓝色光晕）；能展开的节点左上角画「＋」，导出版不画
- `web/viewer.js` —— 整个文件的查看窗口（逐行高亮 + 大纲）
- `web/panel.js` —— 左：模块 / 边的机器事实；右：解读（空槽、已写、过期、核对结果）
- `web/app.js` —— 启动：串起上面四个；展开 / 收起时算出新的 `open`、重新要图、重画（收起用的是 payload 给每个节点的 `parent`）

`SCRIPTS` 的顺序就是依赖顺序（render.py:17）。

## 关键算法
### `</` 要转义
内嵌数据里的源码片段可能含 `</script>`，原样塞进 `<script>` 会提前结束脚本。`json.dumps` 之后把 `</` 换成 `<\/`（render.py:26）——在 JS 字符串里两者等价。

### fragment 模式
`fragment=True` 去掉 doctype 和 meta 外壳，给自己会包外壳的宿主（比如 artifact 页面）用。也因为这种宿主会在 DOMContentLoaded 之后才执行内联脚本，`web/app.js` 的启动写成了「已经加载完就直接启动」。

## 局限
整个导出文件控制在 14 MB 以内（`payload.export_payload` 的 `total_budget`，单文件宿主的上限是 16 MB）：先算好其余部分，剩下的额度才给全文，这次 case 跑到过的文件和解读里引用过的文件优先。大仓库只能带一部分，没带上的文件在导出版里只能看顶层符号，要看全文用 serve。
