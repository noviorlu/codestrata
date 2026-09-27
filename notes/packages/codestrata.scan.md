---
written_by: claude-opus-5-5
target: codestrata.scan
kind: package
code_sha: 260a19bf6d47f12d
status: draft
refs: scan.py:421@bb6ab5ba,scan.py:1@5f7a6e1c,scan.py:383@2373040a,scan.py:44@29d84015,scan.py:57@04872629,scan.py:226@0ee68e12,scan.py:264@6907e072,scan.py:237@75f875f9,scan.py:319@5ae71828,scan.py:365@6f938f80
---

## 是什么
静态扫描器：用 `ast` 遍历仓库里的每个 `.py`，产出总图需要的全部事实——包、包间 import 边、架构高度、每个类/函数的位置，以及每条边背后「具体引用了对方哪些符号 / 哪些 import 根本没用」。

## 为什么这样切
它是整个工具的**事实来源**，而且只做这一件事：不画图、不读 trace、不碰解读。产出落到 `.codestrata/` 下两个 JSON，别的模块只读这两个文件，所以它可以随时删掉重跑。它不 import 任何内部模块（叶子），被 `__main__` 调用。

`write_index` 把结果拆成 `index.json`（包和边，画图用，小）和 `symbols.json`（符号、文件映射、边的明细，大）——渲染总图时不需要全量加载符号表（scan.py:421）。

## 读法
1. 模块 docstring（scan.py:1）——先看「架构高度」的定义和为什么不用 SCC
2. `Symbol` —— 一个定义点有哪些字段；注意 `dline`（第一个装饰器行）和 `end`（结束行），它们都是给 runtime 反查用的
3. `detect_roots` / `NON_LIB_DIRS` —— 哪些目录算库、哪些不进图
4. `scan` —— 主流程，按文件循环，每个文件四步：解析 → 收符号（`walk`）→ 收 import 边 → 第二遍找实际引用
5. `scan` 末尾算高度、挂 C++ 文件；最后看 `write_index`

## 关键算法
### 架构高度而不是拓扑分层
`alt = (出 − 入) / (出 + 入)`（scan.py:383）。docstring 里记了为什么：Python 仓库普遍循环 import，在 vllm-omni 上 30 个包有 20 个塌进同一个强连通分量，缩点后分层信息全丢；最长路径分层又会退化成 19 层的链。出入度比值不需要无环。

### tests / examples 不进图
它们 import 一切、几乎没人 import 它们，算进来会把高度冲掉：vllm-omni 的 entrypoints 会从 +0.85 掉到 −0.33（scan.py:44 的注释）。

### src-layout：模块名相对包根的父目录算
`src/mypkg/core/x.py` 的模块名是 `mypkg.core.x`，不是 `src.mypkg.core.x`——代码里写的是 `import mypkg.core`。所以模块名相对 `mod_base = base.parent` 算，文件路径仍相对仓库根（trace 用的是后者）。早先两者都相对仓库根，src-layout 仓库的每条边都指向一个不存在的包，图上一条边也画不出来。

### 收符号只下潜语句容器
`walk` 只递归进 `_STMT_CONTAINERS`（scan.py:57）。def/class 只能出现在语句位置，所以不用遍历表达式子树；早先只白名单了 If/Try/With，for 循环体里的嵌套函数全漏了，换成全树递归又在 vllm-omni 上慢一个量级（scan.py:226 的注释）。

### 相对 import 要看 names
`from . import layout, render` 的目标是 `<base>.layout`、`<base>.render`，不是 `<base>` 本身；早先只取 base，所有这类 import 都塌成指向包自己的边（scan.py:264）。codestrata 自己全是这种写法，这个 bug 会让自扫描一条边都没有。

### 「import 了」和「用了」分两遍
第一遍记下每条 import 在本文件绑定的本地名字（`bound`，以及 `import a.b.c` 这种只绑定根名的 `chains`）；第二遍扫所有 `Name` / `Attribute` 读取，命中哪个绑定就算用了对方哪个符号，记进 `edge_uses`（经 `_use`，同一行只记一次）。一次都没被读到的绑定进 `edge_dead`，并按原因分类：
- `type`：在 `if TYPE_CHECKING:` 里（scan.py:237）——常配字符串标注，AST 里看不到引用，不能判死
- `reexport`：写在 `__init__.py` 里，是给包外用的
- `sideeffect`：`import a.b.c` 且从没出现 `a.b.c.X`——要的是模块顶层执行（scan.py:319）
- `intentional`：行上带 `noqa: F401`（scan.py:365）
- 其余才是 `unused`

这个区分是前端「灰实线 / 灰虚线」和边详情的数据来源。

### 局限（确定的）
- `from x import *` 无法追踪（直接跳过）。
- `from pkg.mod import Name` 里 Name 可能是子模块，静态上分不出来，一律当符号。
- C/C++/CUDA 文件只挂在包下供浏览（`aux`），不参与 import 图；pybind / `torch.ops` 这类跨语言边需要真正的 C++ 解析。
