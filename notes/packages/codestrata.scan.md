---
written_by: claude-opus-5-5
target: codestrata.scan
kind: package
code_sha: d25bd82c694a4c9c
status: draft
refs: scan.py:112@e3529493,scan.py:561@f74f5b17,scan.py:579@2a8f89e3,scan.py:581@c176b6f0,payload.py:35@d6513e46,scan.py:588@ae396e12,codestrata/__main__.py:80@d89a80ca,scan.py:1@5f7a6e1c,scan.py:272@255e30bf,scan.py:293@2fd7b37d,scan.py:304@e7e68c0d,scan.py:296@1920e340,scan.py:307@5e10daf1,runs.py:78@fb413b11,trace.py:108@0685df0e,scan.py:298@c8d01747,runs.py:628@2e266090,scan.py:514@2373040a,scan.py:51@b93afa5e,scan.py:400@b2d3284a,scan.py:422@22a9f949,scan.py:391@74e4ca0b,scan.py:63@04872629,scan.py:344@0ee68e12,scan.py:361@5898f2be,scan.py:449@b9696986,scan.py:496@6f938f80,scan.py:433@8526611d,scan.py:192@a99d3e2d
---

## 是什么
静态扫描器：用 `ast` 遍历仓库里的每个 `.py`，产出总图需要的全部事实——**文件级**的模块（单元）、单元间 import 边、架构高度、目录树、每个类/函数的位置，每条边背后「具体引用了对方哪些符号 / 哪些 import 根本没用」，以及每个 `.py` 文件的内容哈希（`file_sha`，给 runtime 的 run 判断「录制之后这个文件改过没有」）。

## 为什么这样切
它是整个工具的**事实来源**，而且只做这一件事：不画图、不读 trace、不碰解读，也不建交叉引用。产出落到 `.codestrata/` 下两个 JSON（index.json、symbols.json），别的模块只读这两个文件，所以这两个文件随时能删掉重跑。同一目录下的 runs/ 不是 scan 的产物，而是录制数据，删了就没了；scan 不碰它，`iter_py_files` 跳过以点开头的目录（scan.py:112），runs/ 里存的 `.py` 快照也不会被扫进 index。

它只记**最细的粒度**：每个 `.py` 文件一个单元（包的 `__init__.py` 记成 `<包>.__init__`，把目录本身的名字留给图上「整个目录收起来」的那个节点）。图上显示哪一层不是它的事——它只把目录树（`dirs`）和默认切面（`default_open`，由 `cut.default_open` 按规模算，scan.py:561）写进 index；展开 / 收起时由 `cut` 在单元数据上重新汇总，不用重扫。早先它在扫描时就按「二级包」聚合，粒度一旦定下来，图上就没法再往里看。

`write_index` 把结果拆成 index.json（单元、边、目录树，画图用，小）和 symbols.json（符号、文件映射、行数、哈希、边的明细，大）——渲染总图时不需要全量加载符号表（scan.py:579）。`file_sha` 和 `files`、`file_loc` 一样是按文件的数据，放进 symbols.json（scan.py:581）；`payload.load_index` 读回来时，老的 symbols.json 没有这个键就是 None（payload.py:35），`runs.file_state` 据此决定怎么比。写完它会把拆出去的键塞回 index（scan.py:588 的「调用方还要用」），因为调用方接着还要在同一个字典上算切面、建交叉引用。

交叉引用（全文窗口里 Ctrl+点击跳定义 / 列引用的 xref.json）**不在这里建**：`scan` 只返回 index，是 `__main__` 里的 `cmd_scan` 在 `write_index` 之后紧接着调 `xref.build` 并写盘（codestrata/__main__.py:80）。放在同一条命令里、紧跟着写 index，是为了让 xref 和符号表是同一时刻的快照，两边的行号才对得上；放在 scan 外面，则让 scan 保持「只产出总图事实」，xref 那套带作用域的第二遍解析不拖进来。

## 读法
1. 模块 docstring（scan.py:1）——两个产出文件各有什么，「架构高度」的定义和为什么不用 SCC
2. `Symbol` —— 一个定义点有哪些字段；注意 `dline`（第一个装饰器行）和 `end`（结束行），它们都是给 runtime 反查用的
3. `detect_roots` / `NON_LIB_DIRS` —— 哪些目录算库、哪些不进图
4. `scan` —— 主流程：先建 `unit_of_module`（模块名 → 单元，scan.py:272），再按文件循环，每个文件四步：读字节、解码并解析（scan.py:293），记行数和哈希（scan.py:304）→ 收符号（`walk`）→ 收 import 边 → 第二遍找实际引用
5. `scan` 末尾算高度、挂 C++ 文件、收文档（`collect_docs`）、建目录树和默认切面；最后看 `write_index`，再去 `cmd_scan` 看它之后接着建 xref

## 关键算法
### 字节只读一次：解码给 ast，原样哈希给 run
每个 `.py` 先 `read_bytes`（scan.py:293），同一份字节派两个用处：

- **解码**（scan.py:296）：用 `utf-8-sig`。Windows 编辑器存的文件开头常带 BOM，按普通 utf-8 解码时 BOM 会变成源码里的一个 U+FEFF 字符，`ast.parse` 直接报 `SyntaxError`——早先这种文件整个被算进解析失败（`n_parse_errors`），它的单元、符号、边全从图上消失。utf-8-sig 在解码时就去掉 BOM，行号不受影响（BOM 不占行）。`bytes.decode` 不像 `read_text` 那样做通用换行转换，所以这里手动把 CRLF 和单独的 CR 换成 LF：行数（`src.count("\n")`，scan.py:304）和第二遍查 noqa 用的 `src_lines` 与改用字节读之前完全一样，只用 CR 换行的老文件也不会被算成一行。xref 那边用 `read_text` 读、再手动去掉开头的 BOM，两边对同一个文件看到的仍是同一份文本。
- **哈希**（scan.py:307）：对**原始字节**取 sha256 的前 16 位，和 `runs.sha16`（runs.py:78）、`trace.file_shas`、trace 钩子在执行时记下的哈希（trace.py:108）是同一种，三边能直接比。必须哈希原始字节而不是解码后的文本：另外两边哈希的都是磁盘上的字节，改成哈希文本，每个带 BOM 或 CRLF 的文件都会被判成「改过」。用已经读进来的字节顺手算，不再多读一遍（docs/design/runs.md 3.5）；这也保证了哈希和 index 里的行号出自同一份内容——分两次读的话，两次之间文件被改，就会记下一个版本的哈希、另一个版本的行号。

`file_sha` 只给解析成功的 `.py` 记（解析失败的在 scan.py:298 就 `continue` 了，和 `files` 同进同出）；C/C++ 文件（`aux`）不记，trace 只录 Python。

### 为什么过期判断要和 index 比
run 只存原始键（`文件:行号`）和录制时的文件哈希，加载时现映射到当前 index 上；叠加用的行号来自 index 的符号表，而不是工作区。所以「这个 run 在这个文件上还准不准」应该拿 run 的哈希和 index 的 `file_sha` 比（`runs.file_state`，runs.py:628）：改了代码但还没重新 scan，index 仍描述旧代码，和 run 对得上，叠加是准的；老办法 `trace.stale_files` 拿 run 去比工作区，这种时候会误报。index 是老的、没有 `file_sha` 时，`file_state` 才退回去比工作区。

### 架构高度而不是拓扑分层
`alt = (出 − 入) / (出 + 入)`（scan.py:514）。docstring 里记了为什么：Python 仓库普遍循环 import，在 vllm-omni 上 30 个包有 20 个塌进同一个强连通分量，缩点后分层信息全丢；最长路径分层又会退化成 19 层的链。出入度比值不需要无环。这里算的是单元的高度；图上节点的高度由 `cut.view` 在切面上重算（节点内部的边不算）。

### tests / examples 不进图
它们 import 一切、几乎没人 import 它们，算进来会把高度冲掉：vllm-omni 的 entrypoints 会从 +0.85 掉到 −0.33（scan.py:51 的注释）。

### src-layout：模块名相对包根的父目录算
src-layout 下，文件 src/mypkg/core/x.py 的模块名是 mypkg.core.x，不是 src.mypkg.core.x——代码里写的是 import mypkg.core。所以模块名相对 `mod_base = base.parent` 算，文件路径仍相对仓库根（trace 用的是后者）。早先两者都相对仓库根，src-layout 仓库的每条边都指向一个不存在的包，图上一条边也画不出来。

### import 解析：精确到文件，每个导入名单独解析
文件级之后，import 的目标必须精确落到某个单元上：`import a.b` / `from a.b import X` 的目标是 `a.b` 这个模块（是包就落到 `a.b.__init__`）。`from pkg import a, b` 里每个名字**各自**判断（scan.py:400）：`pkg.a` 是仓库里的模块就是导入子模块，否则是 `pkg` 里的名字。早先整条语句只算一个目标，一行导入多个名字时绑定会被最后一个覆盖，「用了对方哪个符号」就记错了地方。同一条语句指向同一个单元只记一条边。

找不到对应文件的目标（构建时才生成的 `_version.py`、可选依赖的桩）不进图，只记数（scan.py:422），scan 结束时打印成 `repo.unresolved_imports`——它们没有节点可画，却会虚增源头的出边、把高度算偏。

### 相对 import 的「点」和 `__init__.py`
`from . import layout, render` 的目标是 `<base>.layout`、`<base>.render`，不是 `<base>` 本身；早先只取 base，所有这类 import 都塌成指向包自己的边。codestrata 自己全是这种写法，这个 bug 会让自扫描一条边都没有。

`__init__.py` 还要再特殊一层：它的模块名就是包本身，所以「一个点」指的是它自己，不用往上退（scan.py:391）。早先按普通模块处理，某个包的 `__init__.py` 里写 `from .x import` 被解析成兄弟包 x——vllm-omni 上凭空多出 15 条指向不存在的包的边。

### 作者写的文档挂到目录上
`collect_docs` 找三类文档：包目录里的 README；frontmatter 用 `primary_code_paths` / `related_code_paths` 声明了自己管哪些代码的设计文档（vllm-omni 的 docs/design 就是这样）；没有 frontmatter 的文档，开头 40 行里用反引号写出的仓库路径（最弱的一档，标「提到」）。README 挂到它所在的目录，图上显示在包含这个目录的节点里。解读层最缺的是「为什么」，而作者往往在文档里写过——输入包和详情面板都会列出它们。

### 收符号只下潜语句容器
`walk` 只递归进 `_STMT_CONTAINERS`（scan.py:63）。def/class 只能出现在语句位置，所以不用遍历表达式子树；早先只白名单了 If/Try/With，for 循环体里的嵌套函数全漏了，换成全树递归又在 vllm-omni 上慢一个量级（scan.py:344 的注释）。

### 「import 了」和「用了」分两遍
第一遍记下每条 import 在本文件绑定的本地名字（`bound`，以及 `import a.b.c` 这种只绑定根名的 `chains`）；第二遍扫所有 `Name` / `Attribute` 读取，命中哪个绑定就算用了对方哪个符号，记进 `edge_uses`（经 `_use`，同一行只记一次）。一次都没被读到的绑定进 `edge_dead`，并按原因分类：
- `type`：在 `if TYPE_CHECKING:` 里（scan.py:361）——常配字符串标注，AST 里看不到引用，不能判死
- `reexport`：写在 `__init__.py` 里，是给包外用的
- `sideeffect`：`import a.b.c` 且从没出现 `a.b.c.X`——要的是模块顶层执行（scan.py:449）
- `intentional`：行上带 `noqa: F401`（scan.py:496）
- 其余才是 `unused`

这个区分是前端「灰实线 / 灰虚线」和边详情的数据来源。

### 顺带记下的事实
每个文件的行数（scan.py:304，详情面板的文件树按目录汇总），每条 import 是不是函数内的延迟 import、是不是只在 `TYPE_CHECKING` 下（scan.py:433），以及类的装饰器名。它们都是直接从代码里读出的事实，不带任何判断。

## 局限
- `from x import *` 无法追踪（直接跳过）。
- `from pkg import Name` 里 Name 是包的 `__init__.py` 再导出的符号时，边指向 `pkg.__init__`，不是真正定义它的文件；目录收起时看不出差别，展开后会看到很多边汇到 `__init__`。（xref 会顺着再导出追到真正的定义，但那是跳转层的事，不改这里的边。）
- C/C++/CUDA 文件只挂在所在目录下供浏览（`aux`），不参与 import 图；pybind / `torch.ops` 这类跨语言边需要真正的 C++ 解析。
- 只有 `.py` 改成了 utf-8-sig；`collect_docs` 读 Markdown 仍是普通 utf-8（scan.py:192）。带 BOM 的设计文档开头不是 `---`，frontmatter 里声明的代码路径会被漏掉，只剩「开头 40 行里提到」那一档。
- 解析失败的文件既不在 `files` 里也没有 `file_sha`。某个 run 跑过的文件如果现在有语法错误，`runs.file_state` 看它不在 index 里、工作区里却还在，会标成 `outside`（不叠加、不算过期），而不是 `changed`。
