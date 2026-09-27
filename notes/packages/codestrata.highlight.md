---
written_by: claude-opus-5-5
target: codestrata.highlight
kind: package
code_sha: 59def89cd0ce1e4b
status: draft
refs: highlight.py:3@8f099d94,highlight.py:103@5e82261f,highlight.py:136@72cd3228,highlight.py:143@2d85d7a4,highlight.py:111@5670855f,highlight.py:37@cc9b6fc3,highlight.py:130@9a53d3fd
---

## 是什么
源码高亮：把 Python、Triton、C++、CUDA 文件转成**按行对齐**的 HTML 片段，外加 C++ 的符号大纲。只被 `payload` 用（`file_view`、`symbol_source`）。

## 为什么这样切
高亮在服务端做、用 Pygments，前端只管塞 HTML。这样 serve 和单文件导出拿到的是同一份结果，导出版离线也有高亮，不用把 JS 高亮库塞进 HTML（highlight.py:3）。它不认识「包」「符号键」这些概念，只认文件——所以是叶子，也可以单独拿去用。

## 读法
1. `EXT_LANG` / `detect` —— 扩展名到语言；Triton 不是扩展名，靠内容判断
2. `_cls` —— Pygments token 类型 → 页面 CSS 类
3. `_tokens` —— 拿 token 流，再叠 Triton / CUDA 的重标
4. `to_lines` —— 核心：切成行
5. `outline` —— C++ 的启发式大纲
6. `_cached` / `highlight_file` —— 缓存

## 关键算法
### 输出必须和源码逐行对齐
前端的行号、跳到第 N 行、从中间切片都依赖「第 N 个元素就是第 N 行」。三处保证：
- 词法器关掉 `stripnl` / `ensurenl`（highlight.py:103），不让它吞掉或补上首尾换行；
- 跨行 token（docstring、`/* */`）在换行处闭合、下一行重开 span（highlight.py:136）；
- 最后按源码行数截断或补齐（highlight.py:143）。
`payload.symbol_source` 也因此是「整文件高亮后再切」，而不是只高亮那一段——从中间切，跨行字符串的着色会错。

### Triton 是 Python 上的一层重标
kernel 就写在 `.py` 里，所以 Python 词法器打底，再把 `tl.load` 这类「tl、点、名字」三个 token 一起重标成 Triton 色（highlight.py:111），`@triton.*` 装饰器单独一色。判断一个 `.py` 是不是 Triton 用 `TRITON_RE`：出现 `import triton` / `@triton.` 即是。

### `.h` 强制当 C++
Pygments 默认把 `.h` 当 C，会把 class / template / namespace 标错；在 C++ 项目里 `.h` 基本都是 C++ 头文件（highlight.py:37）。

### 颜色不用 Pygments 的主题
token 只映射到类名（`t-kw`、`t-str`……），颜色由页面的 CSS 变量决定，亮色 / 暗色跟着页面走。

### 缓存按 (路径, mtime, 大小)
`lru_cache` 包在 `_cached` 上，键里带 mtime 和大小，文件一改自动失效，serve 不用重启。

## 局限
- C++ 大纲来自词法 token，没有 AST：声明和定义都会被捡到，前端会标「启发式」。
- 没装 Pygments 时退化为转义后的纯文本（highlight.py:130），行对齐仍然成立。
