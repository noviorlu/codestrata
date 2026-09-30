# 多语言的接口设计（草案）

**状态：草案。** 第 4 节的单元、目录 id 已经实现（`cut.py`、`web/ids.js`，2026-09-30）；其余没有实现。这一页定接口：以后加语言时，核心代码不用再改。
现有的数据格式见 [run-format.md](run-format.md)，代码结构见 [ARCHITECTURE.md](../ARCHITECTURE.md)。
标「待核实」的是还没在本机实测过的外部工具行为，第 11 节列出了怎么核实。

## 1 目标和边界

**目标**：录一次真实运行，看清它在**一个仓库**里经过的所有代码，不限一种语言。

**核心语言**：Python、C++、CUDA、Rust。CUDA 单独算一种：静态上和 C++ 共用 clang 系的工具，运行时却在 GPU 上，要另外的录制来源。
接口不为这四种写死：别的语言照同样的契约加扫描端和录制来源即可，但不在承诺范围内。

几个几种语言混在一个仓库里的例子：

| 仓库 | 语言 | 一次运行怎么走 |
|---|---|---|
| cohere-megakernel | Python（17 个 `.py`）、C++（nanobind 绑定、KV 缓存、JIT）、CUDA（decode 的 megakernel，`.cu` / `.cuh`） | Python 的服务和调度 → `native.ext()` 拿到 nanobind 扩展 `mk_ext` → C++ → 启动 CUDA kernel |
| vLLM | Python、C++ / CUDA（`csrc/`）、Rust（`rust/`，Cargo 工作区，经 PyO3 暴露给 Python） | 四种语言都在这一个仓库里 |
| vllm-omni | Python，另有 1 个 `.cu`（`TORCH_LIBRARY_FRAGMENT` 注册的算子）和 37 个写了 Triton kernel 的文件 | 几乎全是 Python |

**不做的**：C++ 的完整调用图（虚函数、模板实例化只做到能做准的部分）；不经提权、不重新编译就精确记下每一个原生函数的调用（见 7.2 的精度等级）。
把依赖的仓库（比如 vllm-omni 用到的 vLLM）一起看**没有决定做**，见附录；本页的接口给它留了位置，但不为它做任何事。

## 2 原则

1. **契约是数据格式，不是代码。** 扫描端、录制来源、导入端都是「产出某种格式文件的程序」，可以用任何语言写、可以调外部工具；
   核心只读这些格式。现在 run-format.md §9 对录制端已经是这个思路，这里推广到静态这边。
2. **核心不认语法。** 核心（装配索引、切面、排版、叠加、时间轴、页面）只认文件、单元、符号、边、键、span，不 parse 任何源码。
   认语法的代码全在各语言的扫描端里。
3. **每条事实带出处和精度。** 编译器 / 索引器给的是「准」，按名字对上的是「近似」，运行时看到的是「实测」。页面上近似的要标出来。
   沿用现在的规矩：**宁可不连，也不连错**。
4. **加语言 = 加扫描端和录制来源**，不改核心。
5. **老数据照样能用。** 现有的 run（键是 `相对路径:行`）和它们的计数一字不改就能读。
6. **按需用现成工具。** 成熟工具做得更好的就用它，不以零依赖为目标（decisions「依赖按需引入」）。C++ / CUDA / Rust 的扫描端和原生代码的录制来源
   本来就离不开外部工具（tree-sitter、clang 系、rust-analyzer、profiler）；运行时检测，没装就明确说缺什么、这部分不出，不影响别的部分。

## 3 名词

| 名词 | 意思 | 现在对应的 |
|---|---|---|
| 单元 | 图上最细的节点：**一个文件**，任何语言都一样；id 是相对仓库根的路径 | 一个 `.py`，id 是点分模块名 |
| 符号 | 一个定义：类 / 结构体、函数 / 方法、kernel | symbols.json 里的一条 |
| 函数键 | `<相对路径>:<首行号>`；`:0` 是文件顶层的执行 | 不变 |
| 扫描端 | 一种语言的静态分析，产出 5.1 的索引分片 | `scan.py`（只有 Python） |
| 录制来源 | 一次 run 里的一路运行时数据：我们的 Python hook、torch.profiler、Nsight Systems…… | 只有 Python hook |
| 导入端 | 把一路录制来源的原始数据换成统一的计数和 span | `analysis.merge` + `events.build`（只认 hook 的格式） |
| 连接层 | 按名字把一种语言里的「导出」和另一种语言里的「引用」连起来（`torch.ops`、pybind11、nanobind、PyO3） | 没有 |

## 4 单元、目录和符号的 id

- **单元 id = 文件相对仓库根的路径**（`src/decode/runtime.cu`、`vllm_omni/engine/core.py`）；**目录 id = 路径加 `/`**（`src/decode/`）；
  「本层文件」节点是 `<目录>/*`。
- 现在的点分名（`vllm_omni.engine`、包的 `<目录>.__init__`）只作**显示名**，由扫描端给（`label`）。换成路径是因为：C++ 文件名里有点（`runtime.cu`）、
  目录名里有连字符（`sm-profiler`），点分名表示不了。
- 目录树、切面、排版照旧，只是 id 换了写法。
- **符号键**从 `<点分模块名>:<限定名>` 改成 `<路径>#<限定名>`：C++ / Rust 的限定名里有 `::`，不能再拿冒号分。路径里不允许 `#`（扫描端遇到就跳过这个文件并报出来）。
- **函数键不变**：`<路径>:<行>`，解析仍用 `rpartition(":")`；调用边键仍是 `a|b`。老 run 因此不用改。

## 5 静态层

### 5.1 扫描端的产出：索引分片

每种语言一份分片，放在 `.codestrata/index/<语言>.json`（可重建）。核心把所有分片装配成一份索引
（现在的 index.json + symbols.json 的角色），切面、排版、叠加只读装配后的结果。

下例是扫 vLLM 仓库时 CUDA 扫描端的分片（节选；行号、include 的文件名是示意）：

```json
{"format": 1, "lang": "cuda",
 "tool": {"name": "codestrata-cxx", "version": "…", "fidelity": "exact"},
 "files":   {"csrc/layernorm_kernels.cu": {"sha": "…", "loc": 380, "label": "layernorm_kernels.cu"}},
 "symbols": [{"id": "csrc/layernorm_kernels.cu#vllm::rms_norm_kernel",
              "k": "kernel", "n": "vllm::rms_norm_kernel", "s": "rms_norm_kernel",
              "f": "csrc/layernorm_kernels.cu", "l": 15, "e": 60, "scip": "…"},
             {"id": "csrc/layernorm_kernels.cu#rms_norm",
              "k": "func", "n": "rms_norm", "s": "rms_norm", "f": "csrc/layernorm_kernels.cu", "l": 221, "e": 250}],
 "deps":    [["csrc/layernorm_kernels.cu", "csrc/dispatch_utils.h", "include", 1]],
 "uses":    [{"f": "csrc/layernorm_kernels.cu", "l": 240, "to": "csrc/layernorm_kernels.cu#vllm::rms_norm_kernel", "k": "launch"}],
 "exports": [],
 "externs": []}
```

C++ 那份分片里，`csrc/libtorch_stable/torch_bindings.cpp` 的注册会产出
`{"name": "op:_C::rms_norm", "to": "csrc/layernorm_kernels.cu#rms_norm", "f": "csrc/libtorch_stable/torch_bindings.cpp", "l": …, "via": "impl CUDA"}` 这样的 `exports`；
Python 那份分片里，`vllm/_custom_ops.py` 调 `torch.ops._C.rms_norm` 的那一行产出 `{"name": "op:_C::rms_norm", "f": "vllm/_custom_ops.py", "l": …, "from": "…#rms_norm"}` 这样的 `externs`。

| 字段 | 内容 | 核心拿来做什么 |
|---|---|---|
| `files` | 路径 → `sha`（§0 的 sha16）、`loc`、`label`（显示名）、`err`（解析失败的原因） | 单元、目录树、录制后改没改过 |
| `symbols` | `id`、`k`、`n`、`s`、`f`、`l`、`e`，可选 `dl`（装饰器 / 属性 / 模板开头的行）、`b`（基类）、`scip`（SCIP 符号串）、`x`（标记，见下） | 叠加落到函数、remap、边的明细、跳转 |
| `deps` | `[从, 到, 种类, 权重]`：声明出来的依赖。种类 `import`（Python / Rust 的 `use`、`mod`）、`include` | 图上的静态边、分层 |
| `uses` | `{f, l, to, k, why?}`：某文件某行引用了某个符号。`k` = `ref` / `call` / `launch`（host 端启动 kernel）/ `type`（只在类型上用到） | 边的实质（用到对方哪些符号）、调用处、动态分派的判断 |
| `exports` | `{name, to, f, l, via}`：以**另一种语言里的名字** `name`（5.4 的规范名）暴露出去的符号；`f`、`l` 是注册写在哪 | 连接层 |
| `externs` | `{name, f, l, from}`：某行引用了一个**由别的语言实现**的名字（`op:_C::silu_and_mul`、`py:mk_ext.<名字>`）；`from` 是这一行所在的符号 | 连接层 |
| `dead` | `{f, l, dep, why}`：声明了、却没用上的依赖；`why` 由扫描端给（Python 现在有 unused / type / reexport / sideeffect / intentional） | 虚线边、说明 |

符号的 `k` 统一成几类：`class`（Python 类、C++ class / struct / union / enum、Rust struct / enum / trait）、`func`（函数、方法）、`kernel`
（CUDA `__global__`、Triton `@triton.jit`）。`x` 放和语言有关、但核心要知道的标记，目前只有一个：
**`defexec`**——运行时的键落在这个符号的定义行上，表示「定义时的执行」而不是调用（Python 的类体）。现在这条规则写死在
`analysis.defining` 里，改成由扫描端标出来；C++ / Rust 没有这种执行，就不标。文件顶层 `:0` 仍是全语言通用的约定。

现在 Python 扫描已经有、别的语言可以没有的（`edge_sites`、`name_refs`、`docs`、架构高度）照旧由 Python 扫描端产出，放在分片的 `extra` 里，页面有就显示。

### 5.2 各语言的扫描端

每个原生语言的扫描端都分两件事：**认语法**（定义的起止、调用 / 启动出现在哪、`#include` / `use`、绑定的宏和属性）用 tree-sitter；
**认名字**（这个位置上的名字指向哪个定义）用这门语言的 SCIP 索引器。SCIP 不标「调用」，也不是每个索引器都给定义的范围（5.3），
所以语法这一半省不掉；而没有构建环境、跑不了索引器时，只剩语法这一半，名字按文本对，精度降成「近似」。

| 语言 | 认语法 | 认名字（准档） | `deps` | 连接用的 `exports` / `externs` |
|---|---|---|---|---|
| Python | 现在的 `ast` 扫描 | 现在的 `xref.py`（不换成 scip-python，理由见第 6 节） | import | `externs`：`torch.ops.<ns>.<op>` 的调用处、原生扩展模块上的名字；`exports`：`direct_register_custom_op` / `torch.library` 在 Python 里注册的算子 |
| C++ | tree-sitter（C++ 语法） | scip-clang，要 `compile_commands.json` | `#include` | `exports`：`PYBIND11_MODULE` / `NB_MODULE` 里的 `m.def`、`TORCH_LIBRARY*` 和 `STABLE_TORCH_LIBRARY*` 里的 `m.def` / `m.impl` |
| CUDA | tree-sitter（**CUDA 语法**：C++ 语法解析 `.cu` 会报错、丢掉 `<<<…>>>` 启动） | scip-clang（v0.3.0 起支持 CUDA；`k<<<…>>>(…)` 记成对 kernel 的引用） | 同上 | `uses` 里的 `launch`；`__global__` 记成 `kernel` |
| Rust | tree-sitter（Rust 语法） | rust-analyzer 自带的 `scip` 子命令，要 Rust 工具链（`cargo metadata`、跑 build script） | `mod`、`use` | `exports`：PyO3 的 `#[pymodule]` / `#[pyfunction]` / `#[pyclass]` / `#[pymethods]`（含 `name = …` 改名） |

精度写进分片的 `tool.fidelity`，也可以细到每条 `uses` / `exports` 上（`"fid": "approx"`）。

tree-sitter 的 Python 包（`tree-sitter` 0.26 和 `tree-sitter-cpp` / `tree-sitter-cuda` / `tree-sitter-rust` 语法包，MIT，都有预编译 wheel）
在本机 3.13 上装得上、能解析 kernel 定义和启动。

**扫描范围**：仓库里带进来的第三方源码（git submodule、`ext/`、`third_party/`，比如 cohere-megakernel 的 ThunderKittens 和 nanobind）默认不扫，和现在默认不扫 `tests/` 一样由用户决定。

### 5.3 SCIP 适配器

SCIP 是一种跨语言的代码索引格式（原属 Sourcegraph，现在在 `github.com/scip-code/scip`），C++ / CUDA（scip-clang）、Rust（rust-analyzer）都有产出它的工具。
核心带一个**语言无关**的 SCIP 适配器：读一份 `.scip`，给出「某文件某位置 → 某符号」和「某符号定义在哪」两张表，供各扫描端产出 `symbols`、`uses` 和第 6 节的跳转数据。
这样 C++ / CUDA / Rust 的扫描端 = 「tree-sitter 认语法 + 现成的索引器认名字 + 一小段认绑定写法的代码」，不再各自写名字解析。

SCIP 是 protobuf，官方没有 Python 绑定。它只用到 varint 和定长前缀两种线格式，手写解码器约 130 行，在一个样例上和官方 `scip print --json` 的输出逐份一致，
速度约 41 MB/s；也可以用 `protobuf` 库配 `scip.proto` 生成的代码，两种都行，按实现时的方便选。要注意的格式细节：

- 行列从 0 开始、左闭右开；位置有老的整数数组（3 个或 4 个数）和 2026 年新加的分类型写法两种，两种都要认。
- 列的单位看 `position_encoding`，但各索引器不一样：rust-analyzer 标明 UTF-8；scip-python 没标、实际是 UTF-16；scip-clang 没标、应是字节（待核实）。
  适配器按产出工具换算成页面要的 UTF-16。
- 角色只有定义 / 导入 / 读 / 写等，**没有「调用」**：调用出现在哪由语法给，SCIP 只回答那个位置上的名字指向谁。
- 一个调用处的「调用方」= 包住它的最内层定义。rust-analyzer 给定义的范围（`enclosing_range`），scip-clang 不给，C++ / CUDA 的定义范围由 tree-sitter 给。
- 符号的种类字段不可靠（有的索引器全填 0），种类从符号串的后缀推（`#` 类型、`().` 方法 / 函数、`/` 命名空间）。

SCIP 给不出、要扫描端自己补的：`deps`（include / use 的声明）、`k` 的细分（kernel）、调用和普通引用的区别、
`exports` / `externs`（绑定是写在宏和属性里的约定，不是语言层面的引用）、模板实例化后的具体名字。

### 5.4 连接层

把不同语言之间的调用连起来，靠的是**名字**：一边的扫描端报「我以 `torch.ops._C.silu_and_mul` 这个名字导出了 `silu_and_mul`」，
另一边报「我在这一行用了 `torch.ops._C.silu_and_mul`」，核心按名字对上，就得到一条跨语言的 `bind` 边。核心只做字符串匹配，认写法的都在扫描端。

名字统一成两种规范写法，同一个东西在各处的写法都换算到它：

- **算子** `op:<命名空间>::<算子>`：Python 写 `torch.ops._C.rms_norm`，C++ 注册写 `_C` 命名空间下的 `rms_norm`，profiler 的事件名是 `_C::rms_norm`，都是 `op:_C::rms_norm`。
- **Python 可见的原生对象** `py:<模块>.<限定名>`：pybind11、nanobind、PyO3 暴露出来的函数、类、方法。

| 写法 | 导出方（`exports`） | 引用方（`externs`） | 规范名 |
|---|---|---|---|
| PyTorch 自定义算子（C++） | `TORCH_LIBRARY` / `TORCH_LIBRARY_FRAGMENT(ns, m)` 里 `m.def("op(…)")`，`TORCH_LIBRARY_IMPL(ns, CUDA, m)` 里 `m.impl("op", …)`；稳定 ABI 版 `STABLE_TORCH_LIBRARY*` 同理（`m.impl("op", TORCH_BOX(&fn))`） | Python 的 `torch.ops.ns.op(…)` | `op:ns::op` |
| PyTorch 自定义算子（Python） | `direct_register_custom_op(op_name=…, op_func=…)`、`torch.library.custom_op("ns::op")` | 同上 | 同上 |
| pybind11 | `PYBIND11_MODULE(mod, m)` 里 `m.def("f", &f)`、`py::class_<T>(m, "T").def(…)`、`m.def_submodule("sub")` | Python 的 `import`、属性调用 | `py:<模块>.<名字>` |
| nanobind | `NB_MODULE(mod, m)` 里 `m.def("f", &f)`、`nb::class_<T>(m, "T").def(…)` | 同上 | 同上 |
| PyO3 | `#[pymodule]`（模块名来自 `Cargo.toml` 的 `[lib] name`）、`#[pyfunction]`、`#[pyclass(name = …, module = …)]`、`#[pymethods]`、`#[pyo3(name = …)]` | 同上 | 同上 |
| CUDA kernel 启动 | kernel 定义（`__global__`） | `kernel<<<…>>>(…)` | 同一语言内，走 `uses` 的 `launch`，不经连接层 |
| Triton | `@triton.jit def k` | `k[grid](…)` | 同一语言内（Python），走 `uses` 的 `launch` |

一条完整的例子（vLLM 仓库）：`vllm/_custom_ops.py` 的 `rms_norm` 调 `torch.ops._C.rms_norm` → `csrc/libtorch_stable/torch_bindings.cpp` 里
`STABLE_TORCH_LIBRARY_FRAGMENT(_C, ops)` 定义、`STABLE_TORCH_LIBRARY_IMPL(_C, CUDA, ops)` 把它实现为 C++ 函数 `rms_norm` →
`csrc/layernorm_kernels.cu` 的 `rms_norm` 启动 kernel `vllm::rms_norm_kernel`。前两跳经连接层，后一跳是 CUDA 扫描端的 `launch`。

别的例子：vllm-omni 的 `torch.ops.vllm_omni.fused_qk_rope`（Python 里经 `direct_register_custom_op` 注册，实现是一个 Triton kernel）和
`TORCH_LIBRARY_FRAGMENT(a2ap, m)`（`vllm_omni/diffusion/distributed/csrc/a2a_permute.cu`）；vLLM 的 `rust/` 里
`#[pyclass(name = "ToolParser", module = "vllm._rust_tool_parser")]`，Python 里是 `vllm._rust_tool_parser.ToolParser`；
cohere-megakernel 的 `NB_MODULE(mk_ext, m)`（`src/bindings/mk_ext.cpp`）。

要注意的几处，按「近似」连并在页面上标出来：

- **算子的命名空间不等于 `.so` 的名字**：vLLM 现在的算子在 `_C` 命名空间，却装在 `_C_stable_libtorch` 这个扩展里。按算子名连，不按模块名连。
- **命名空间是宏**：老版本 vLLM 写 `TORCH_LIBRARY_EXPAND(TORCH_EXTENSION_NAME, ops)`，命名空间要从编译参数（`-DTORCH_EXTENSION_NAME=…`）里拿。
- **模块名只知道最后一段**：`PYBIND11_MODULE(_C, m)` 装在哪个包下要看构建配置。
- **扩展模块是运行时拿到的**：cohere-megakernel 的 Python 代码不直接 `import mk_ext`，而是经 `native.ext()` 按路径加载后拿到模块对象，
  静态上只能按属性名（`ext().xxx(…)`）去对 `mk_ext` 导出的名字；运行时（7.2 的 L0）能拿到确切的模块名。

## 6 跳转

- **格式**：沿用现在 xref.json 的形状（`targets` / `where` / 按文件的 token 表 `[行, 起, 止, 目标, 种类]`，列是 UTF-16 下标），
  只把目标换成 4 节的符号键，并按语言分片。页面、serve 不关心数据是谁产出的。
- **来源**：
  - C++ / CUDA / Rust：SCIP 索引经 5.3 的适配器转成这个格式。
  - Python：继续用现在的 `xref.py`，改成写新 id 的格式。**不换成 scip-python**：它是 2023 年 pyright 的分支，2025-09 之后没有人在维护；
    在一个假项目上实测，`from x import *` 引进来的名字全指到模块上、相对导入 `from .impl import` 指到不存在的模块、符号种类全是 0，
    这几处现在的 `xref.py` 都做对了。（再导出、`self.x`、继承来的方法它能解析对。）jedi、basedpyright 另行实测，比 `xref.py` 好再换。
- **跨语言**：点 `torch.ops._C.silu_and_mul` 跳到 C++ 的实现，走连接层的 `bind` 边。

## 7 运行时：一个 run 里有多路录制来源

### 7.1 run 格式要改的

| 改什么 | 现在 | 改成 | 老 run |
|---|---|---|---|
| 版本 | 没有 | run.json 加 `format: 2` | 没有就是 1 |
| 函数键 | `相对路径:行` | 不变 | — |
| 录制来源 | 只有 hook，分片平铺在 `parts/` | run.json 加 `sources: [{id, kind, tool, clock, report}]`；别的来源的原始数据放 `parts/<来源 id>/`，原样永久保留 | hook 的分片仍平铺，id 记成 `py` |
| 线程登记 | 事件日志的 `N <tid> <线程名>`，`tid` 是进程内编的小整数 | 加上系统线程号：`N <tid> <线程名> <native tid>`（`threading.get_native_id()`）。profiler 的事件用的是系统线程号，没有它对不上 | 没有就对不上外部来源，只影响新功能 |
| 时钟锚点 | 只有 `CLOCK_MONOTONIC` | 每个进程映像在开始、每次落盘、结束时各记一对 `(monotonic_ns, realtime_ns)`：事件日志加 `A <mono> <real>` 行，分片加 `clock` 列表 | 没有就不能换算外部来源的时间 |
| 道 | span 的第 3 个字段是线程号 | 改叫「道」（lane）：CPU 线程，或 GPU 的（设备, 流）；keys.json 的 `threads` 换成 `lanes: {pid: {道号: {kind, name, native?, device?, stream?}}}` | 线程号原样当 CPU 道 |
| kernel 的发起 | 没有 | span 加第 9 个字段 `lag`：GPU 上开始执行比 CPU 发起晚多少 µs（只有 GPU 道有） | 没有这个字段 |
| 没解析出来的名字 | 没有 | 原生事件只知道名字、不知道文件行号的，键写成 `?<语言>:<名字>`（`?cuda:vllm::rms_norm_kernel<…>`、`?op:_C::rms_norm`），加载时再按符号表解析（7.6） | — |

### 7.2 原生代码的精度等级

原生代码的录制按代价分四级，一个 run 可以同时用几级：

| 级 | 看得到什么 | 靠什么 | 代价 |
|---|---|---|---|
| **L0 边界** | Python 调进原生代码的每一次调用：哪个 Python 函数、调了哪个原生入口、多久 | 我们的 hook 多订阅 `sys.monitoring` 的 CALL / C_RETURN / C_RAISE | 不要权限、不用重编；开销待测 |
| **L1 算子** | PyTorch 算子（`aten::*`、自定义算子）的起止 | torch.profiler 的 `cpu_op` 事件（自定义算子的事件名就是 `ns::op`） | 要在被测进程里开 profiler |
| **L2 kernel** | GPU 上每个 kernel / 拷贝的起止、在哪个流上、由哪次 CPU 调用发起 | torch.profiler（CUPTI）或 Nsight Systems | profiler 的开销；只该在关心的阶段开 |
| **L3 原生函数** | C++ / Rust 内部任意函数 | uprobes（bpftrace）、perf 采样、编译插桩 | 要特权或重编；以后再说 |

「sequence 怎么流」主要靠 L0 + L2：Python 这一侧的路径已经有了，L0 补上「从哪进了原生代码」，L2 补上「最后在 GPU 上跑了什么」。

**L0 的做法**（Python 3.12 实测）：

- CALL 在每个调用发生前触发，C_RETURN / C_RAISE 只在被调的不是 Python 函数时触发；所以「CALL 之后来了 C_RETURN」就是一次原生调用，两者的时刻差就是时长。
  原生代码里再调原生代码（比如 `map` 里调 `len`）看不见。
- 从被调对象认出是谁：pybind11 的函数用 `__module__` + `__name__`（它的 `__qualname__` 是乱码）；PyO3 的方法用 `__objclass__` 的模块 + `__qualname__`
  （没有 `__module__`）；`torch.ops.ns.op` 是 `OpOverloadPacket`，`_qualified_op_name` 就是 `ns::op`；nanobind 待核实。认出来的名字换成 5.4 的规范名，经连接层落到定义上。
- CALL 是按位置的事件，某个调用处返回 DISABLE 后这个位置就不再触发（连带它的 C_RETURN）。**C_RETURN 不能返回 DISABLE**：会抛 `ValueError`、并把回调注销掉，hook 从此失效。
- 开销是最大的未知数：CALL 在仓库代码的每个调用处都会触发，包括调 Python 函数的。要在真实负载上测，再决定是默认开还是按需开。

**L3 在本机不可用**：`perf_event_paranoid` 是 4、非特权 BPF 关着，perf、bpftrace（uprobes）、Nsight Systems 的 CPU 采样都要管理员权限。

### 7.3 导入端的契约

每路录制来源配一个导入端，`merge` 时调用。输入：`parts/<来源 id>/` 下的原始文件、run.json（`clock`、`phase_log`）、hook 记下的锚点和线程表。输出统一的一份：

- **计数**：按阶段的 `funcs` / `func_edges`（同 §4 的形状）。外部工具不知道我们的阶段，导入端按事件的时刻落进 `phase_log` 的区间。
- **span**：`(pid, 道, t0, dur, 调用方键, 被调方键, rep, n_susp, lag)`，时刻已换到 run 的时间轴上。
- **名字**：键 → 名字（remap 和显示用）。
- **报告**：对齐时钟用的方法和残差、丢掉的事件数、对不上的名字数，写进 run.json 的 `sources[].report`。

合并后的计数、span 和现在一样按 `(pid, 道)` 分块存，派生数据都能从原始数据重算（导入端改进了，`runs merge` 一遍老 run 就受益）。
两种外部格式都好读：torch.profiler 的是 JSON，Nsight Systems 的报告可以导出成 SQLite。

### 7.4 时钟对齐

run 的时间轴是 `CLOCK_MONOTONIC`（run-format §0）。外部工具的时间戳不是这个时钟，导入端负责换算，并且**必须验证**：

- **torch.profiler**：每个进程一份 trace。`baseTimeNanoseconds + ts × 1000` 是 `CLOCK_REALTIME` 的纳秒（`ts` 以带三位小数的微秒写出，要从字符串精确解析）。
  在 CPU 上实测：5 个打点全部落在前后读的 `time.time_ns()` 之间，和 monotonic 系列的时钟差了约 1.79×10¹⁸ ns。GPU 上 CUPTI 的时间戳由 PyTorch 换到同一个时钟上（源码如此，待 GPU 实测）。
- **Nsight Systems**：时间戳是相对会话开始的纳秒；导出时 `--ts-normalize=true` 换成 UTC 纪元纳秒。没有直接给 `CLOCK_MONOTONIC` 的选项。
- **换算**：`monotonic = realtime − (realtime − monotonic)`，这个差值取**同一进程**里 hook 记下的锚点（7.1）。两个时钟只在系统时间被跳变时才相对移动，
  所以开始和结束各一对锚点就够：两对差值不同，说明中间被调过时间，这一路标成「时间不可信」。
- **验证**：发起 kernel 的 CPU 事件（运行时 / 驱动 API 调用）必须落在我们 hook 记下的、同一线程上某个调用的时间段里。对不上的比例和偏移写进报告；
  超过阈值的这一路只给计数、不进时间顺序。

### 7.5 kernel 挂到发起它的调用上

GPU 上的 kernel 没有调用栈，只有一个关联号，指向 CPU 上发起它的那次 API 调用：

- **torch.profiler**：`cat: "kernel"` 的事件（`pid` 是设备号、`tid` 是流号）带 `correlation`，同号的 `cuda_runtime`（`cudaLaunchKernel` 等）或 `cuda_driver`
  （`cuLaunchKernel(Ex)`，Triton 走这个）事件带系统的 pid / tid 和时刻。默认只记调 `start()` 的那个线程上的算子，要打开实验选项 `profile_all_threads`。
- **Nsight Systems**：`CUPTI_ACTIVITY_KIND_KERNEL`（`correlationId`、`globalPid`、起止、设备、流、kernel 名）按 `(correlationId, pid)` 接
  `CUPTI_ACTIVITY_KIND_RUNTIME`（`globalTid`、时刻）：kernel 表里没有线程，线程要从 API 调用那边拿。

拿到（pid、系统线程号、时刻）之后，在我们自己的 span 里找那一刻正在执行的最内层仓库函数，它就是这条边的调用方；有 L0 / L1 时中间再插原生入口、算子这几层
（Python 函数 → `op:_C::rms_norm` → `rms_norm` → kernel）。kernel 这一行的 `t0` 是 GPU 上开始执行的时刻，`lag` 是它比发起晚多少；
「时间顺序」按**发起时刻**排（因果顺序），时间轴上 GPU 道按执行时刻画。

### 7.6 只有名字的原生事件

kernel 名、算子名只是字符串（C++ 的还带模板参数）；装好的 `.so` 通常有符号表、没有调试信息，所以原生的东西运行时只能拿到名字，文件和行号只能来自静态扫描。
导入端把它们写成 `?<语言>:<名字>` 键，**加载时**再按当前索引解析（和 run-format §8 的 remap 同一个思路：原始数据不动，扫描端改进后老 run 也能解析得更好）：

- 算子 `?op:ns::op` 经连接层的 `exports` 落到实现它的函数上。
- kernel 名去掉模板参数、参数表后，按符号的 `n`（限定名）精确对；Triton kernel 在 GPU 上的名字就是 Python 函数的 `__name__`，按 `kernel` 类符号的短名对。
  对不上再按 `s`（短名）且全索引唯一时对上，标「近似」。
- 对不上的（仓库外的代码：PyTorch 自己的 kernel、cuBLAS……）归到每种语言一个虚拟节点（「CUDA kernel（仓库外）」），不丢：图上仍能看到这次运行进了哪些 kernel、各多少次、多久。

### 7.7 怎么开录

`trace` 加一个选项声明要哪些录制来源（名字待定，比如 `--native kernels`）。本机上可用的做法：

| 做法 | 怎么做 | 好处 | 要注意 |
|---|---|---|---|
| **包一层 Nsight Systems**（本机装了 2025.3.2） | driver 用 `nsys profile -t cuda,nvtx --trace-fork-before-exec=true --cuda-graph-trace=node … -- <命令>` 起命令；hook 在关心的阶段调 `cudaProfilerStart / Stop`，配 `--capture-range=cudaProfilerApi` 只录这几段 | 不需要被测程序配合；非 PyTorch 的 CUDA 程序也能录（cohere-megakernel 的 megakernel 就是直接启动的）；CUDA graph 能细到每个 kernel（7.8） | 默认不跟 fork 出来的子进程（vLLM 默认 fork 工作进程），默认 CUDA graph 只记整张图；CPU 采样在本机不可用 |
| **在被测进程里开 torch.profiler** | 注入的 `sitecustomize` 在 `torch` 被 import 之后、按阶段开关 profiler（CPU + CUDA、`profile_all_threads`），每个进程的 trace 写进 `parts/<来源 id>/` | 对任何用 PyTorch 的程序都通用；顺带有 L1 算子 | CUDA graph 回放时 kernel 只挂到 `cudaGraphLaunch` 上 |
| **程序自带的开关** | vLLM（0.13 起）`--profiler-config`、`LLM.start_profile()` / `/start_profile`；vllm-omni 按 stage 开（MiniCPM-o 示例有 `--enable-profiler --profiler-stages`）；导入端从它的输出目录里取 trace | 最省事 | 只对这些程序有用；它们不开 `profile_all_threads`，只记调 `start()` 的线程；老版本的 `VLLM_TORCH_PROFILER_DIR` 已经去掉了 |

先在 GPU 上各试一次（第 11 节），再定先做哪个导入端。

### 7.8 CUDA graph 和编译出来的 kernel

vLLM 这类服务为了省 CPU 开销，常在启动时把模型的前向**捕获**成 CUDA graph，之后每一步只**回放**；用 `torch.compile` 时，kernel 是 Inductor 现生成的 Triton 代码。两件事都会改变「路径」的样子：

- **回放时模型的 Python 代码不再执行**。每一步里 hook 只看得到发起回放的那个函数，模型的路径只在捕获（启动）时走过一遍。页面要把这一点说清楚，不能让人以为模型代码没跑。
- **回放出来的 kernel 只关联到 `cudaGraphLaunch`**。要知道某个 kernel 当初是哪段 Python 代码发起的，得用 Nsight Systems 的 `--cuda-graph-trace=node`：
  图里每个节点记着捕获时创建它的那次 API 调用（同一线程、时刻落在 API 调用里面），再按 7.5 找到捕获时的 span。回放的 kernel 这一行的调用方是发起回放的函数，
  另记一个「捕获时的调用方」，页面上两者都给。只用 torch.profiler 做不到这一步。
  前提是**捕获本身也录下来**：捕获发生在启动时，用 `--capture-range` 只录服务阶段的话，节点就对不回去。所以要么整段录 CUDA API（数据量待测），
  要么启动时的捕获和服务阶段各录一段。（都待 GPU 实测。）
- **Inductor 生成的 kernel**（名字形如 `triton_poi_fused_…`、`triton_red_fused_…`）源码在编译缓存里，不在仓库里，归到「编译生成的 kernel」虚拟节点。
  能不能经 Inductor 在生成代码里写的注释对回模型源码，待核实，以后再说。

## 8 页面上怎么变

- 节点带语言（颜色或角标）；显示名来自扫描端的 `label`。
- 边：跨语言的 `bind` 和启动 kernel 的 `launch` 用新的线型，和现有的配色约定并存；「近似」的连法在边的详情里标出来。
- 时间轴：多出 GPU 道（可以收起）；「时间顺序」里 kernel 按发起时刻排。
- CUDA graph 回放的那几段标出来：「模型代码在启动时捕获，这里只回放」，kernel 同时给出回放时和捕获时的调用方（7.8）。
- 页面不再自己拆名字：短名用符号的 `s`，不再 `split('.')`。

## 9 现有代码要改的地方

| 模块 | 现在 | 改成 |
|---|---|---|
| `scan.py` | Python 扫描 + 装配（目录树、默认切面）+ 写 index.json / symbols.json，单元是点分名 | 拆开：Python 扫描端（写 5.1 的分片）和新的装配模块（读所有分片、按路径建目录树、算默认切面）。`_code_facts` / `_call_form` 这类「调用处」分析挪到扫描端，产出进 `uses` |
| `cut.py` | 点分 id；`unit_dir` 特判 `.__init__`；本层文件节点 `<目录>.*` | 路径 id（目录带 `/`）；本层文件节点 `<目录>/*` |
| `layout.py` | `pkg.split(".")` 取名字、只有一个根时去掉根前缀 | 用索引里的 `label` |
| `payload.py` | 按点分名找模块文件（`_module_files`、`_top`）、按 `:` 拆符号键、在请求时用 `ast` 算调用处 | 只读装配后的索引；调用处读 `uses`。（god module 的拆分正好借这次一起做） |
| `trace/analysis.py` | `defining` 写死「落在类定义行 = 类体」；`merge` 只认 hook 的分片 | `defining` 读符号的 `defexec` 标记；`merge` 按 `sources` 调各路导入端，hook 的那路就是现在的逻辑 |
| `trace/hook.py` | 线程只记进程内编号 | `N` 行带系统线程号；时钟锚点；可选的 L0 边界记录；按阶段开关外部 profiler（7.7） |
| `trace/driver.py` | 直接起命令 | 按录制来源决定是否包一层外部工具（Nsight Systems）；给每路来源建 `parts/<id>/` |
| `runs.py` | `remap` 按 Python 的 qualname 规则（去掉 `.<locals>`） | 规则按语言分（Python 保持现状，其余按 `n` 精确对）；run.json 加 `format`、`sources`；读老格式 |
| `events.py`、`seq.py` | 只有线程 | 道（CPU 线程 / GPU 流）、`lag`、`?` 键、`A` 锚点行 |
| 新：导入端 | 没有 | torch.profiler 的 JSON、Nsight Systems 导出的 SQLite 各一个 |
| `xref.py` | 写 xref.json，点分目标 | Python 的内置跳转端，写新 id 的同一格式；新增 SCIP 适配器（给 C++ / CUDA / Rust） |
| `highlight.py`、`web/hl.js` | 认 Python / Triton / C++ / CUDA | 加 Rust |
| 前端 | `split('.')` 取短名、点分 id | 读 `label` / `s`；语言标记；新线型；GPU 道 |
| 测试 | 一个假 Python 仓库 | 加：一个带 pybind11 / nanobind / `TORCH_LIBRARY` / PyO3 / kernel 启动的 C++ / CUDA / Rust 假仓库（只测静态）；手写的 profiler 样例数据测导入端（不用 GPU） |

## 10 顺序

每一步单独能验收，做完不留半截：

| 步 | 内容 | 验收 |
|---|---|---|
| **0 留口子** | 第 4 节的路径 id 和符号键；5.1 的分片和装配（Python 扫描拆成扫描端）；`defexec`；run 格式 2（`format`、`sources`、系统线程号、时钟锚点）；跳转格式换成新 id | 全套测试通过；现有仓库的图和改之前一样（除 id 写法）；老 run 叠上去的次数一字不差 |
| **1 C++ / CUDA** | C++ / CUDA 扫描端（按第 11 节的实测选档）、连接层、L0 边界、一个 kernel 导入端（按 GPU 实测选 Nsight Systems 或 torch.profiler） | 静态：cohere-megakernel 上 Python → nanobind → C++ → kernel 的边画得出来、点得进代码；运行时：见第 12 节 |
| **2 Rust** | Rust 扫描端（tree-sitter + rust-analyzer 的 SCIP + PyO3）、L0 对 PyO3 入口 | vLLM 仓库的 `rust/`：从 Python 走进 Rust 函数 |
| **3 原生函数级** | L3 | 要特权，以后再定 |

## 11 待核实

已经核实的（2026-09-30）：

- 静态：SCIP 手写解码器就能读（5.3）；scip-python 的问题（第 6 节）；scip-clang 支持 CUDA、kernel 启动记成引用；CMake 在 configure 阶段就写出
  `compile_commands.json`，不用编译；tree-sitter 的 CUDA 语法能解析 kernel 启动、C++ 语法不能。
- 运行时（CPU 上）：torch.profiler 的时钟和事件格式（7.4）；`sys.monitoring` 对原生调用的事件和 DISABLE 的限制（7.2）；
  pybind11 / PyO3 / `torch.ops` 的被调对象怎么认；Triton kernel 在 GPU 上的名字就是 Python 函数名；本机装了 Nsight Systems、没有特权（7.2、7.7）；
  vLLM 现在的算子注册写法（5.4）。
- cohere-megakernel 只支持 Hopper（`sm_90a`），要 CUDA 13、FlashAttention-3 和它自己的 checkpoint；本机是 RTX 5090（`sm_120`），也没有装 CUDA 工具链（`nvcc`）。

| 事 | 为什么要紧 | 怎么核实 |
|---|---|---|
| GPU 上 torch.profiler 的 kernel 事件字段、CUPTI 时间戳是否真在同一时钟；Nsight Systems 的时钟、`--cuda-graph-trace=node` 的节点能否对回捕获时的调用 | 7.4、7.5、7.8，选哪个导入端先做 | 在 GPU 上录一个小的 PyTorch 例子（带一个 CUDA graph），两种工具各一次 |
| L0 的开销；nanobind 的被调对象怎么认 | 默认开还是按需开；cohere-megakernel 的边界 | 在 CPU 上的负载上测，比较开关 CALL 事件的耗时；nanobind 写个小扩展看属性 |
| cohere-megakernel 的 `compile_commands.json`（CMake 项目，configure 要 CUDA 工具链） | C++ / CUDA 在它上面走准档还是近似档 | 装 CUDA 13 工具链后 configure；装不上就只用 tree-sitter（近似档） |
| scip-clang 的列单位 | 跳转的列对不对 | 含多字节字符的样例 |
| rust-analyzer 的 SCIP 输出 | Rust 扫描端 | 本机没有 Rust 工具链，要先装；在 vLLM 的 `rust/` 上试 |

## 12 待决定

1. **C++ / CUDA 的运行时在本机拿什么验收**：cohere-megakernel 在 RTX 5090 上跑不了（7.7、第 11 节）。
2. **多仓库做不做**（附录）。

## 附：多仓库（没有决定做）

一个仓库的运行常常大半走在它的依赖里：vllm-omni 的一次请求，路径的大部分在 vLLM 的引擎、调度、模型执行里，C++ / CUDA 则在 vLLM 的 `csrc/` 和 PyTorch 里。
现在调进仓库外代码的调用是透明的（记到最近的仓库函数头上），看不到依赖内部怎么走。要看，就得把依赖的源码也挂进来。这件事**没有决定做**；下面只记下它会是什么样，以及本页的接口怎么给它留了位置。

- **会是什么样**：工作区里挂多个源码根（主仓库、site-packages 里装好的包、某个依赖的源码 checkout），每个根一个路径前缀（主仓库是空串，别的像 `@vllm/`），
  文件的 id 就是「前缀 + 相对路径」。主仓库前缀是空串，所以现有的键全部不变。hook 从一个仓库根改成多个。
- **要知道的事实**：装好的 vLLM 0.30 里有 2681 个 `.py`，但 C++ / CUDA / Rust 只有编译好的 18 个 `.so`，没有 `csrc/`、`rust/` 的源码；
  要看原生代码，得另外 checkout 和装的**同一版本**的源码。
- **本页怎么留了位置**：单元 id 已经是路径（第 4 节），以后加前缀不用再改格式；run 的键同理。除此之外不为它做任何事。
