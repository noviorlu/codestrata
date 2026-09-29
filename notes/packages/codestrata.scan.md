---
written_by: claude-opus-5-5
target: codestrata.scan
kind: package
code_sha: 6561eeff4aa1f966
status: draft
refs: scan.py:135@cf3433c4,scan.py:397@8f7062c3,scan.py:771@f74f5b17,scan.py:776@cdb35e3c,scan.py:792@c176b6f0,payload.py:52@d6513e46,scan.py:799@ae396e12,scan.py:761@bd8a6524,scan.py:523@31448101,codestrata/__main__.py:85@d89a80ca,scan.py:1@5f7a6e1c,scan.py:399@ece62725,scan.py:436@255e30bf,scan.py:454@2fd7b37d,scan.py:465@e7e68c0d,scan.py:289@b898a049,scan.py:440@1da30e18,scan.py:131@f0c578ab,scan.py:143@f82da3ef,scan.py:164@875a23a8,scan.py:151@2e3321f2,scan.py:401@c19aae48,scan.py:172@0f390eab,scan.py:457@1920e340,scan.py:468@5e10daf1,runs.py:90@fb413b11,trace.py:148@0685df0e,scan.py:461@e256ee8e,runs.py:709@2e266090,scan.py:473@6e455720,scan.py:480@47fa472f,scan.py:702@2373040a,scan.py:51@29d84015,scan.py:583@b2d3284a,scan.py:609@22a9f949,scan.py:574@74e4ca0b,scan.py:601@bb22c4ee,scan.py:678@c7b7aa70,scan.py:64@04872629,scan.py:506@0ee68e12,scan.py:639@cfc7e49e,scan.py:684@6f938f80,scan.py:620@8526611d,scan.py:740@8316e21f,scan.py:341@a99d3e2d
---

## 是什么
静态扫描器：用 `ast` 遍历选定目录里的每个 `.py`，产出总图需要的全部事实——**文件级**的模块（单元）、单元间 import 边（运行时依赖 `edges` 和只在 `if TYPE_CHECKING:` 里的 `type_edges` 分开记）、架构高度、目录树、每个类/函数的位置，每条边背后「具体引用了对方哪些符号 / 哪些 import 运行时根本没用」，以及每个 `.py` 文件的内容哈希（`file_sha`，给 runtime 的 run 判断「录制之后这个文件改过没有」）。

它还回答扫描之前的问题「扫哪些目录」：`candidate_roots` 给主菜单的勾选框列出能选的目录（仓库根目录直接放着 `.py` 时排第一个的是 `ROOT_SCRIPTS`，即「.」），`root_clashes` 挡住会撞模块名的组合，`detect_roots` 只在没人给 roots 时兜底去猜。

## 为什么这样切
它是整个工具的**事实来源**，而且只做这一件事：不画图、不读 trace、不碰解读，也不建交叉引用。产出落到 `.codestrata/` 下两个 JSON（index.json、symbols.json），别的模块只读这两个文件，所以这两个文件随时能删掉重跑。同一目录下的 runs/ 不是 scan 的产物，而是录制数据，删了就没了；scan 不碰它，遍历时 `_skip_dir` 跳过以点开头的目录（scan.py:135），runs/ 里存的 `.py` 快照也不会被扫进 index。

**扫哪些目录是用户的决定**。`scan` 拿到 roots 只用 `clean_roots` 归一写法（结尾的 /、开头的 ./、重复的），然后照单全收（scan.py:397），包括 tests/、examples/——早先它会替用户把 `NON_LIB_DIRS` 里的目录去掉，于是用户在对话框里勾了 tests/ 也扫不进来。现在只有没给 roots 时才调 `detect_roots`：命令行 `scan` 不带 `--roots`，或 `trace` 找不到上一次 scan 选的目录时（`trace` 默认用 index 里记下的 roots，录制和图对的是同一批代码）。主菜单里是用户自己勾（`projects.scan_choices` 把上一次的选择并进候选、标 previous，`app` 的 `_scan_argv` 要求至少勾一个）。

它只记**最细的粒度**：每个 `.py` 文件一个单元（包的 `__init__.py` 记成 `<包>.__init__`，把目录本身的名字留给图上「整个目录收起来」的那个节点）。图上显示哪一层不是它的事——它只把目录树（`dirs`）和默认切面（`default_open`，由 `cut.default_open` 按规模算，scan.py:771）写进 index；展开 / 收起时由 `cut` 在单元数据上重新汇总，不用重扫。

`write_index` 把结果拆成 index.json（单元、边、`type_edges`、目录树，画图用，小）和 symbols.json（符号、文件映射、行数、哈希、边的明细，大）——渲染总图时不需要全量加载符号表（scan.py:776）。`file_sha` 和 `files`、`file_loc` 一样是按文件的数据，放进 symbols.json（scan.py:792）；`payload.load_index` 读回来时，老的 symbols.json 没有这个键就是 None（payload.py:52），`runs.file_state` 据此决定怎么比。写完它会把拆出去的键塞回 index（scan.py:799 的「调用方还要用」），因为调用方接着还要在同一个字典上算切面、建交叉引用。

同样放在 symbols.json 里的还有 `name_refs`（scan.py:761）：字符串常量里写着的仓库内类名——大写开头的标识符，或者 `"pkg.mod.Cls"` / `"pkg.mod:Cls"` 这种带模块的类路径（后者连模块一起记下）；`__all__` 里的是再导出清单，不收（scan.py:523）。它回答的是动态分派的「在哪儿按名字接上的」：注册表、插件表、配置里的 worker_cls。扫的时候先把所有像类名的字符串收下，扫完再只留仓库里真有这个类名的。

交叉引用（xref.json）**不在这里建**：`scan` 只返回 index，是 `__main__` 里的 `cmd_scan` 在 `write_index` 之后紧接着调 `xref.build` 并写盘（codestrata/__main__.py:85）。放在同一条命令里，是为了让 xref 和符号表是同一时刻的快照，行号才对得上；放在 scan 外面，则让 scan 保持「只产出总图事实」。

## 读法
1. 模块 docstring（scan.py:1）——两个产出文件各有什么（含 `type_edges`），「架构高度」的定义和为什么不用 SCC
2. `Symbol` —— 一个定义点有哪些字段；`dline`（第一个装饰器行）、`end`（结束行）、`also`（同名的另几个 def）都是给 runtime 反查用的，`decos` 给 payload 判断调用的写法
3. 选目录：`_skip_dir` / `_is_env` / `_subdirs` → `candidate_roots`（对话框的候选）→ `clean_roots` / `check_roots`（含 `root_clashes`）→ `detect_roots`（兜底）
4. `scan` —— 主流程：先用 `check_roots` 挡撞名和嵌套（scan.py:399），建 `unit_of_module`（模块名 → 单元，scan.py:436；每个根下有哪些文件、模块名怎么起由 `root_py_files` / `module_name` 统一回答），再按文件循环，每个文件四步：读字节、解码并解析（scan.py:454），记行数和哈希（scan.py:465）→ 收符号（`walk` + `add`）→ 收 import 边 → 第二遍找实际引用
5. `scan` 末尾算高度、挂 C++ 文件、收文档（`collect_docs`）、建目录树和默认切面；最后看 `write_index`

## 关键算法
### 候选目录：只列不挑，列出来的互不重叠
`candidate_roots` 从每个顶层子目录往下找（最多三层），每条路径上停在第一个能当根的目录：
- 有 `__init__.py`：是包，列它，不再往下；
- 有工程文件（`PROJECT_MARKERS`：pyproject.toml / setup.py / setup.cfg）：是仓库里嵌套的另一个工程，进去接着找它的包，它自己的 setup.py 不算「零散脚本」。模块名按根目录的最后一段起，把整个嵌套工程当根，里面的包就成了 `<工程目录>.<包>`，import 全对不上；
- 直接放着 `.py`（examples/、scripts/、没有 `__init__.py` 的 tests/）：列它本身，它下面的包也算在里面；
- 没有子目录可进、或到了第三层还不是包：列它本身。

顶层子目录找完，仓库根目录这一层若直接放着 `.py`（研究代码的 train.py / render.py），再把「.」插到最前面（scan.py:289），见下一节。

一个 `.py` 都没有的目录不列；列出的目录互不重叠：同一个文件只会落在一个根下、只有一个模块名。每项带 `.py` 文件数和是不是包，挑哪些全交给用户——tests/ 也列，扫进来会把高度冲掉（见下面），但那是用户知情的选择。

### 根目录的脚本：「.」只取这一层
「.」（`ROOT_SCRIPTS`）是个特殊的扫描目录：`root_py_files` 对它只列仓库根目录直接放着的 `.py`，不往下——下面的目录各自是别的扫描目录，这样才和别的根不重叠（`check_roots` 的嵌套检查也不会把「.」当成所有目录的父目录，它的写法不是前缀）。这些脚本不在任何包里，按「相对父目录」起名会只剩 `train` 这种裸名字，所以统一装进一个以仓库名命名的节点：`scripts_package` 把仓库目录名里的非单词字符换成 `_`，和另一个根的最后一段撞名（仓库名和包名一样很常见）就加 `_scripts`；模块名是 `<仓库名>.<脚本名>`，`root_name` 给出每个根在模块名里的第一段，`top` 就由它算。「.」下的 `__init__.py` 也不当包处理（scan.py:440）。根目录的脚本之间写的是裸名字（`import utils`：Python 按脚本所在目录找到的是 utils.py），`bare_scripts` 收下这些脚本名（减掉 `top` 里真正的包名），`canon` 在解析 import 时把它换成 `<仓库名>.utils`，脚本之间的边才画得出来。

### 目录跳过：隐藏的一律跳，SKIP_DIRS 只跳不是包的
`_skip_dir`（scan.py:131）是所有遍历（`_subdirs`、`iter_py_files`、`collect_docs`、挂 C++ 文件的 `walk_aux`）共用的判断：以点开头的目录一律跳过；`SKIP_DIRS` 里的名字（build、dist、env、venv……）只在它**没有** `__init__.py` 时跳过。这些名字在仓库顶层是构建产物，在包里却可能是真正的子包：早先在任何深度都按名字跳，pip 的 _internal/operations/build/ 整个从图上消失。

### 环境目录按内容认，不按名字认
仓库里的 venv / conda 环境名字不固定（envs/xxx、venv-hx），`SKIP_DIRS` 按名字挡不住；里面是装好的第三方库和标准库，扫进来既慢又全是噪声。`_is_env` 看目录里有没有 pyvenv.cfg 或 conda-meta/（scan.py:143），`_subdirs`（候选）、`iter_py_files`（真正扫描，scan.py:164）和 `collect_docs` 都跳过这种目录。`_subdirs` 还不进软链的目录（scan.py:151）：数据、模型目录常软链到大盘上，进去数文件很慢，而扫描用的 `os.walk` 本来也不跟软链。

### 同名或嵌套的根不能一起扫
模块名相对根目录的**父目录**算（见 src-layout 一节），所以最后一段相同的两个根（src/foo 和 tests/foo、hw1/tests 和 hw2/tests）会产出同一批模块名，`unit_of_module`、符号表按名字互相覆盖；一个根在另一个里面（src 和 src/pkg）时，里面的文件按两个模块名各扫一遍。`check_roots` 查这两种（同名的交给 `root_clashes` 按最后一段分组），不行就抛 `ValueError` 说明原因；`scan` 把它转成 `SystemExit`、什么都不写（scan.py:401）。`app` 的 `_scan_argv`、`trace` 显式给的 `--roots` 在起任务前调同一个函数，对话框也按 `name` 限制同名的只能勾一个。命令行上的写法先经 `clean_roots` 归一（CLI 在 `main` 里做一次）：模块名按最后一段起，`pkg/` 不去掉结尾的 / 最后一段就是空的，仓库内的 import 全对不上。

### 自动探测的顺序
`detect_roots` 依次试：顶层的库包（跳过 `NON_LIB_DIRS`）→ src/<包>（同样先跳过 tests 之类，全是才留）→ 只有 tests 之类的顶层包 → 含 `.py` 最多的顶层目录（scan.py:172）。src-layout 排在「只有测试包」前面：早先顺序反过来，src-layout 仓库只要有一个带 `__init__.py` 的 tests/，就只扫到 tests/。

### 字节只读一次：解码给 ast，原样哈希给 run
每个 `.py` 先 `read_bytes`（scan.py:454），同一份字节派两个用处：

- **解码**（scan.py:457）：用 utf-8-sig。Windows 编辑器存的文件开头常带 BOM，按普通 utf-8 解码时 `ast.parse` 直接报 `SyntaxError`——早先这种文件整个算进解析失败（`n_parse_errors`），单元、符号、边全从图上消失。`bytes.decode` 不做通用换行转换，所以手动把 CRLF 和单独的 CR 换成 LF：行数（scan.py:465）和查 noqa 用的 `src_lines` 与 `read_text` 读时完全一样。xref 那边用 `read_text` 读、再手动去掉开头的 BOM，两边看到的仍是同一份文本。
- **哈希**（scan.py:468）：对**原始字节**取 sha256 的前 16 位，和 `runs.sha16`（runs.py:90）、`trace.file_shas`、trace 钩子在执行时记下的哈希（trace.py:148）是同一种，三边能直接比。哈希解码后的文本，每个带 BOM 或 CRLF 的文件都会被判成「改过」。用已经读进来的字节顺手算，也保证哈希和 index 里的行号出自同一份内容（docs/design/runs.md 3.5）。

`file_sha` 只给解析成功的 `.py` 记（解析失败的在 scan.py:461 就 `continue` 了，和 `files` 同进同出）；C/C++ 文件（`aux`）不记，trace 只录 Python。

### 为什么过期判断要和 index 比
run 只存原始键（`文件:行号`）和录制时的文件哈希，加载时现映射到当前 index 上；叠加用的行号来自 index 的符号表，而不是工作区。所以「这个 run 在这个文件上还准不准」应该拿 run 的哈希和 index 的 `file_sha` 比（`runs.file_state`，runs.py:709）：改了代码但还没重新 scan，index 仍描述旧代码，和 run 对得上，叠加是准的；拿 run 去比工作区（`trace.stale_files`）这时会误报。index 是老的、没有 `file_sha` 时，`file_state` 才退回去比工作区。

### 同名的几个 def：留最后一个，前面的记进 also
符号按 `模块:限定名` 存，property 的 getter 和 setter、`overload`、if/else 里的两个版本是同一个键。`add`（scan.py:473）照旧留最后一个，把前面几个的 [行, 装饰器行, 末行] 记在 `also`（JSON 里的 "a"，scan.py:480）：trace 按「文件:首行」记，getter 跑到了也要对回这个符号（`trace.sym_locs` 把它们都建进索引），payload 找调用方函数体时也把这几段算上。只合并同一个文件里、同一种的：不同文件同名是模块名撞了（`root_clashes` 挡着）；一个函数一个类的不合，trace 靠种类区分「调用」和「定义」。

函数现在也记装饰器名（`_deco_names`，只留最后一段，JSON 里的 "d"）：property / setter 这类访问器在调用方写的是 `.名字` 而不是 `名字(`，payload 的 `_call_form` 靠它换找调用处的写法。类的装饰器（dataclass 之类）照旧记。

### 架构高度而不是拓扑分层
`alt = (出 − 入) / (出 + 入)`（scan.py:702），只数 `edges`，不数 `type_edges`。docstring 里记了为什么：Python 仓库普遍循环 import，在 vllm-omni 上 30 个包有 20 个塌进同一个强连通分量，缩点后分层信息全丢；最长路径分层又会退化成 19 层的链。出入度比值不需要无环。图上节点的高度由 `cut.view` 在切面上重算。

tests / examples 这类目录 import 一切、几乎没人 import 它们，算进来会把高度冲掉：vllm-omni 的 entrypoints 会从 +0.85 掉到 −0.33（scan.py:51 的注释）。所以 `detect_roots` 不自动选它们；用户明确选了就照扫。

### src-layout：模块名相对包根的父目录算
src/mypkg/core/x.py 的模块名是 mypkg.core.x，不是 src.mypkg.core.x——代码里写的是 import mypkg.core。所以 `module_name` 让模块名相对包根的父目录算，文件路径仍相对仓库根（trace 用的是后者）。早先两者都相对仓库根，src-layout 仓库的每条边都指向不存在的包。

### import 解析：精确到文件，每个导入名单独解析
`import a.b` / `from a.b import X` 的目标是 `a.b` 这个模块（是包就落到 `a.b.__init__`）。`from pkg import a, b` 里每个名字**各自**判断（scan.py:583）：`pkg.a` 是仓库里的模块就是导入子模块，否则是 `pkg` 里的名字。早先整条语句只算一个目标，一行导入多个名字时绑定会被最后一个覆盖。同一条语句指向同一个单元只记一条边。

找不到对应文件的目标（构建时才生成的 `_version.py`、可选依赖的桩）不进图，只记数（scan.py:609），打印成 `repo.unresolved_imports`——它们没有节点可画，却会虚增出边、把高度算偏。

### 相对 import 的「点」和 `__init__.py`
`from . import layout, render` 的目标是 `<base>.layout`、`<base>.render`，不是 `<base>` 本身；早先只取 base，codestrata 自扫描一条边都没有。`__init__.py` 的模块名就是包本身，所以「一个点」指的是它自己，不用往上退（scan.py:574）；早先按普通模块处理，vllm-omni 上凭空多出 15 条指向不存在的包的边。

### TYPE_CHECKING 里的 import 不是依赖
`if TYPE_CHECKING:`（或 `typing.TYPE_CHECKING`）里的 import 运行时根本不执行。scan 把它们整个分流（scan.py:601）：边权记进 `type_edges` 而不是 `edges`，绑定的名字记进 `typed` 而不是 `bound` / `chains`——第二遍不看 `typed`，所以标注里引用了也不算「用到」。早先它和普通 import 一样进 `edges`，`from __future__ import annotations` 下标注里的名字是普通 `Name`，被算成「用了 1 个符号」，图上凭空多一条实线回边、高度也被带偏。现在 `typed` 里的名字一律进 `edge_dead`、why 是 `type`；只有同一个本地名字还有运行时 import（函数里再 import 一次）时不记，引用归到运行时那条上（scan.py:678）。`edge_sites` 照旧记这条语句（带 "type" 标记），边详情里还能看到它；payload 只在切面上两端之间没有运行时 import 时才把它画成「仅类型」（默认不显示）。

### 收符号只下潜语句容器
`walk` 只递归进 `_STMT_CONTAINERS`（scan.py:64）。def/class 只能出现在语句位置，所以不用遍历表达式子树；早先只白名单了 If/Try/With，for 循环体里的嵌套函数全漏了，换成全树递归又在 vllm-omni 上慢一个量级（scan.py:506 的注释）。

### 「import 了」和「用了」分两遍
第一遍记下每条运行时 import 在本文件绑定的本地名字（`bound`，以及 `import a.b.c` 这种只绑定根名的 `chains`）；第二遍扫所有 `Name` / `Attribute` 读取，命中哪个绑定就算用了对方哪个符号，记进 `edge_uses`（经 `_use`，同一行只记一次）。运行时一次都没被读到的绑定进 `edge_dead`，按原因分类：
- `type`：在 `if TYPE_CHECKING:` 里（见上一节）
- `reexport`：写在 `__init__.py` 里，是给包外用的
- `sideeffect`：`import a.b.c` 且从没出现 `a.b.c.X`——要的是模块顶层执行（scan.py:639）
- `intentional`：行上带 `noqa: F401`（scan.py:684）
- 其余才是 `unused`

这个区分是前端「灰实线 / 灰虚线」和边详情的数据来源。每条 import 是不是函数内的延迟 import、是不是只在 `TYPE_CHECKING` 下，也记在 `edge_sites` 里（scan.py:620）。

### C/C++/CUDA 文件：挂在目录上，嵌套工程里的挂到包上
`aux` 只供浏览，不进 import 图。每个根里面的 C/C++/CUDA 文件挂到所在目录（点分名）。此外，根若是嵌套工程里的包（父目录不是仓库根、且有 `PROJECT_MARKERS` 里的文件，scan.py:740），整个工程目录里的这类文件（别的扫描目录除外）都挂到这个包上（`base.name`）：3DGS 的 submodules/diff-gaussian-rasterization/cuda_rasterizer/ 就在包旁边而不在包里。仓库根这一层不这么做，否则整个仓库的 C 代码都会挂到一个包上。两种来源共用 `add_aux`（记归属和行数）和 `walk_aux`（按 `_skip_dir` 跳目录）。

### 作者写的文档挂到目录上
`collect_docs` 找三类文档：包目录里的 README；frontmatter 用 `primary_code_paths` / `related_code_paths` 声明了自己管哪些代码的设计文档；没有 frontmatter 的文档，开头 40 行里用反引号写出的仓库路径（最弱的一档，标「提到」）。解读层最缺的是「为什么」，而作者往往在文档里写过——输入包和详情面板都会列出它们。

## 局限
- `from x import *` 无法追踪（直接跳过）。
- `from pkg import Name` 里 Name 是 `__init__.py` 再导出的符号时，边指向 `pkg.__init__`，不是真正定义它的文件；展开后会看到很多边汇到 `__init__`（xref 会顺着再导出追到定义，但不改这里的边）。
- 只认 `if TYPE_CHECKING:` 的 if 分支；`if not TYPE_CHECKING: … else:` 这种写法的 else 分支仍算运行时依赖。
- C/C++/CUDA 文件只挂在所在目录下供浏览（`aux`），不参与 import 图；pybind / `torch.ops` 这类跨语言边需要真正的 C++ 解析。
- `collect_docs` 读 Markdown 仍是普通 utf-8（scan.py:341）。带 BOM 的设计文档开头不是 `---`，frontmatter 里声明的代码路径会被漏掉。
- 解析失败的文件既不在 `files` 里也没有 `file_sha`。某个 run 跑过的文件如果现在有语法错误，`runs.file_state` 会标成 `outside`（不叠加、不算过期），而不是 `changed`。
