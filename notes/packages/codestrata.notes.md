---
written_by: claude-opus-5-5
target: codestrata.notes
kind: package
code_sha: 539e6e6471fbc0a6
status: draft
refs: notes.py:1@b8d20e4f,notes.py:242@4d69b628,notes.py:268@6d691108
---

## 是什么
解读层的存取：人或 LLM agent 写的「为什么」。负责存在哪、怎么判断过期、按什么顺序派活、给 agent 什么输入包，以及用机器核对解读里能核对的部分。

## 为什么这样切
它是唯一和「人写的内容」打交道的模块，和 `scan` / `trace` 这些「可重建的事实」严格分开（notes.py:1）：
- 事实放 `.codestrata/`，随时删了重建；解读放仓库里的 `notes/`，跟代码一起进版本库——它**不能**重建。
- 一个目标一个文件，多个 agent 能并行写，git 能干净合并。

它不 import 任何内部模块（叶子），被 `payload`（导出时带上解读）、`serve`（读写 API）、`__main__`（CLI）使用。

## 读法
1. 模块 docstring —— 分工和「解读会腐烂」
2. `code_sha` —— 过期判定的依据
3. `load` / `save` —— frontmatter 怎么补、stale 怎么算
4. `tasks` → `prompt_pack` —— 派活
5. `verify` —— 机器核对
6. `md_to_html` —— 最后看，只是个够用的子集

## 关键算法
### 解读会腐烂：code_sha
每份解读的 frontmatter 存 `code_sha`：它所描述的源文件的内容哈希。包的解读哈希该包的所有文件；仓库总览（保留名 `_overview`）只哈希**架构骨架**——有哪些包、谁依赖谁——改一个函数体不会让总览过期，加一个包会。只看所描述的文件，所以改别的模块不会误报。

### 派活自底向上
`tasks` 按架构高度从低到高排（notes.py:242）：叶子没有内部依赖，可以孤立读懂；写到上层时下层的解读已经存在。`prompt_pack` 会把**依赖模块已有的解读**一并放进输入包，于是上层能引用下层、而不是各说各话（notes.py:268）。总览排在最后，它的输入包带上所有模块解读的第一句。

### 机器核对（`verify`）
LLM 写的解读里，有一部分是机器能核对的：`file:line` 引用（文件在不在、行号越没越界；只写文件名时在已扫描文件里找唯一匹配），反引号里的标识符（先查符号表，再查全仓源码里出现过的标识符；根名是标准库模块的，如 `os._exit`，真去 import 解析——只 import 标准库，不执行仓库或第三方代码）。核对不了「为什么这么写」对不对——那要人去读；但编出来的函数名、写错的行号、引用了已删除的代码，都能抓住。前端和 `codestrata check` 都会显示结果。

### Markdown 在 Python 侧渲染
`md_to_html` 只支持解读用得到的子集（标题、列表、代码块、行内码、粗体、链接），放在 Python 侧是为了不给单文件导出引 JS markdown 库——那样离线就得靠 CDN。

## 局限
- frontmatter 只支持一层 `key: value`，不是真的 YAML。
- `verify` 的名字核对是「存在性」而不是「指称正确」：写了一个真实存在、但指错了的函数名，它发现不了。
