---
written_by: claude-opus-5-5
target: _overview
kind: repo
code_sha: 95a07c68c2173ea5
status: draft
---

## 这个仓库做什么
codestrata 是**仓库的运行路径对比工具**：先静态扫描出一张按依赖分层的模块图，再把一次真实运行录下来的调用叠到同一张图上；
换个模型或配置再录一次，就能对比两次各走了哪些代码。录下的 run 永久保存、可反复叠加。核心（run 格式、叠加、对比、时间轴）
与语言无关，目前只有 Python 一个语言。定位、范围和已知问题见 `docs/STATUS.md`。

## 主干
scan（`ast` → `.codestrata/index.json`、`xref.json`）→ trace（被测进程里的 hook 记调用，外面的 driver 管进程）→ run
（`.codestrata/runs/<id>/`，不可重建）→ 加载时按 qualname 映射回当前 index → `payload` 组装 → `serve` 按请求给 / 导出成文件 → `web/` 前端。
每一步落在哪个函数、每个模块管什么，见 `docs/ARCHITECTURE.md`。

## 阅读顺序
1. `docs/STATUS.md`：现在是什么、做什么不做什么。
2. `docs/ARCHITECTURE.md`：数据流和模块地图。
3. 看数据：`docs/design/run-format.md`（run 的每个文件和字段）。
4. 看理由：`docs/design/decisions.md`（还在生效的设计决策）。
5. 某个模块的细节：`notes/packages/` 里对应的解读，或直接读代码（模块 docstring 都写了它为什么存在）。

## 局限
- 录制只在 Linux 上验证过；Windows 上 `trace.py` 顶层的 `signal.SIGKILL` 让整个命令行起不来（`docs/TODO.md` P0）。
- `trace.py`、`payload.py` 是 god module，模块之间还在用下划线私有名，拆分计划在 `docs/TODO.md`。
- 浏览器交互的测试还不在仓库里。
