# 状态

最后更新：2026-09-29。每次收工时更新这一页；历史交给 git log，这里只写现在。

## 定位

**仓库的运行路径对比工具。** 跑一次，看清这次运行在一个陌生的大仓库里走了哪条路、按什么顺序；
换个模型或配置再跑一次，看清两次差在哪。

- 核心与语言无关：run 的存储格式（按 `文件:首行号` 记的调用次数和调用边、时序 span、阶段）、叠加、对比、
  时间轴都不认语言。
- 目前只有 Python 一个语言：静态扫描用 `ast`，录制用 `sys.monitoring`（3.12+），更早的版本退回 `setprofile`。
  以后加别的语言，只需要加一套扫描器和录制端，产出同样格式的数据。

## 范围

| 类别 | 内容 | 策略 |
|---|---|---|
| 核心 | 边上的「静态引用 × 运行时调用」、录制（多进程 / 服务 / 阶段）、叠加、对比两个 run、时间轴 / 时间顺序 | 继续做深 |
| 冻结 | 代码窗口、Ctrl+点击跳转、文件内查找、搜索栏、浏览器端高亮、单文件导出、GitHub 静态站、主菜单 app | 只修 bug，不加功能；读代码优先「跳到你的编辑器」 |
| 收缩 | 解读层（tasks / pack / note / check） | 功能保留；本仓库自己的解读只在里程碑刷新，只写现状 |
| 以后再说 | 其他语言；把运行路径作为上下文交给 coding agent | 核心稳了再验证 |

## 里程碑（当前）

在 vllm-omni 上录 MiniCPM 和 Qwen 各一次，用 codestrata 在 10 分钟内答出：加一个新模型要碰哪些文件、
哪些是 MiniCPM 特有的路径。答得出来就写成文章；答不出来，卡在哪修哪。时间盒两周（到 2026-10-13）。

## 能用的

- `scan`：Python 仓库的模块图，按依赖分层，目录树切面可展开 / 收起。
- `trace`：录一次真实运行（子进程、fork / exec、setsid 出去的服务、停进程三级升级），存成可复用的 run；
  `--phase` 按函数切阶段；`--events` 记时序（3.12+）。
- `serve`：图 + 运行叠加 + 时间轴（阶段 / 任意时间段）+ 时间顺序上色 + 对比两个 run（目前只是图上三种颜色）。
- 测试：`tests/test_runs.py`、`test_app.py`、`test_package.py`、`test_web.py`（node）、`test_platform.py`、
  `test_browser.py`（headless Chrome，7 组：图、叠加、时间轴、时间顺序、对比、代码窗口、查找；用假服务当场录的 run）；`tests/hl_parity.py` 对拍浏览器端高亮和 Pygments，
  默认语料是本机的 vllm-omni，别人要自己给目录。

## 已知问题（如实写，不粉饰）

- **平台**：录制只支持 Linux，别的系统上 `trace` 直接拒绝（`compat.require_trace`）。scan / serve / graph / runs 在别的系统上
  能 import、能用（`tests/test_platform.py` 模拟没有 fcntl / SIGKILL 的环境），但没在真的 Windows / macOS 上跑过。
- **god module**：`payload.py`（事实、runtime、坐标、源码、xref、解读全认识）。
- **模块间用下划线私有名**：`runs._read`（5 处）、`payload._norm_open` / `_inverted` / `_known`、`trace._proc_start`、
  `notes._resolve_ref` / `_REF_RE`，以及函数里的 `from .runs import _q`（payload）、`from .scan import _STMT_CONTAINERS`（trace）。
- **读图须知埋得太深**：调用方是「最近的仓库内帧」，穿过框架事件循环的调用会显示成直接调用；次数高的多半是轮询；
  3.12 以下录制很慢。
- **对比只有颜色**，没有「只有 A 走到的 / 只有 B 走到的 / 次数差很多的」清单。
- 本仓库的解读（`notes/`）写得太细、夹着历史叙述，每次改代码维护成本高。

## 文档地图（每类信息只放一处）

| 想知道的 | 去哪看 |
|---|---|
| 怎么用 | `README.md` → `docs/usage.md` |
| 现在什么状态、做什么不做什么 | 本页 |
| 接下来做什么、谁在做 | `docs/TODO.md` |
| 用着哪里不好 | `docs/DOGFOOD.md` |
| 代码怎么组织、数据怎么流 | `docs/ARCHITECTURE.md` |
| run 的数据长什么样（接其他语言的契约） | `docs/design/run-format.md` |
| 为什么这样设计 | `docs/design/decisions.md` |
| 某个模块的细节 | `notes/packages/`（产品的解读层用在自己身上）或代码本身 |
| agent 怎么干活 | `CLAUDE.md` |
| 过去的设计稿 | `docs/archive/`（不再维护） |

## 交接

2026-09-30：做完 TODO P0「平台判断」（新增 `codestrata/compat.py`、`tests/test_platform.py`）。开工前 dogfood 了一轮（用对比回答
「扫 gsplat 比扫 flask 多走了哪些代码」），发现对比在界面上答不出来，已记进 DOGFOOD，并收紧了 TODO「对比做成差异清单」的验收标准。
本仓库的解读有 3 份按规矩暂不刷新（`codestrata.__main__`、`codestrata.runs`、`codestrata.trace` 标着过期），下个里程碑统一刷新。
**下一步**：TODO P0 第 1 条「前端测试进仓库」。

## 每次开工 / 收工

见仓库根目录的 `CLAUDE.md`。待办在 `docs/TODO.md`，用下来的问题记在 `docs/DOGFOOD.md`。
