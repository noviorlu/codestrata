# 设计决定

这一页只收**现在代码里仍然成立**的决定，每条一句话的标题 + 四项：决定、为什么、放弃的方案、在哪。
改掉了的决定直接删掉，不在这里写历史（历史在 git log 里）。

- 「为什么」只写记录过的理由：代码注释、早期的设计稿和模块解读、旧 README。没有记录的写「理由未记录」，不补猜。
- 「在哪」写文件和函数，不写行号（行号会漂）。
- 数字（实测、阈值）都来自上面这些出处或代码本身；标「实测」的是在 vllm-omni 或测试里量过的。

---

## 静态扫描与分层

### 只记文件级的事实，图上显示哪一层交给「切面」
- 决定：scan 每个 `.py` 记一个单元，边、符号、引用明细都在文件之间；图上显示的是目录树的一个切面（一组展开着的目录），
  默认切面按规模贪心拆：代码量超过全仓 10% 的节点里挑最大的拆，拆开后多出超过 30 个节点的不拆，节点到 80 个为止，
  少于 4 个节点的小仓库先拆最大的。
- 为什么：固定深度不适合大小悬殊的仓库（vllm-omni 里 version 只有 1 个文件，diffusion 有 580 个）；数据只有一份单元级的，
  展开 / 收起只是改集合、重新汇总，不用重扫，run 的叠加也和怎么切无关。拆分上限从 20 提到 30：
  20 会挡住宽的核心目录（vllm 的 v1 24 个、pip 的 _internal 22 个、pydantic 的 _internal 29 个）；不设上限，贪心会先拆
  代码量最大的「一族同类实现」（vllm-omni 的 model_executor.models 44 个子目录）。vllm-omni 上结果是 58 个节点。
- 放弃的方案：scan 时就按「二级包」聚合（粒度定死、图上没法再往里看；`scan --depth N` 仍可退回固定深度）；拆分不设上限。
- 在哪：`scan.py` 的 `scan` / `write_index`；`cut.py` 的 `node_of`、`view`、`default_open` 和文件头的五个常量。

### 扫哪些目录由用户定，同名或嵌套的根拒绝
- 决定：给了 `--roots` 就照单全收（包括 tests/、examples/），只有没人给时才由 `detect_roots` 猜；主菜单里由用户勾，
  服务端只接受候选里的目录。最后一段同名的两个根、一个在另一个里面的根，不能一起扫。
- 为什么：早先 scan 替用户去掉 tests/、examples/，用户勾了 tests/ 也扫不进来——图上有什么该由看图的人定，猜只是没人给时的退路。
  模块名相对根的父目录起，同名的根（src/foo 和 tests/foo）会产出同一批模块名、互相覆盖；嵌套的根里的文件会按两个模块名各扫一遍。
- 放弃的方案：scan 自动剔除 `NON_LIB_DIRS`。
- 在哪：`scan.py` 的 `clean_roots`、`check_roots`、`root_clashes`、`detect_roots`、`candidate_roots`；`app.py` 的 `_scan_argv`；
  `__main__.py` 的 `cmd_trace`（显式 `--roots` 也先过 `check_roots`）。

### 单元、目录、符号按路径认，显示名另给
- 决定：单元 id 是文件相对仓库根的路径，目录 id 是路径加 `/`，本层文件节点是 `<目录>*`，根目录的脚本在 `./` 里；
  符号键是 `<文件路径>#<限定名>`，边上引用的名字、xref 的目标（`s:` / `v:` / `m:`）用同一种写法（xref 内部仍按模块名解析，写出时才换）；
  `--phase` 在命令行上照旧写 `模块:限定名`（给人写的），解析时按符号的 `m` 对上路径；
  显示名不从 id 拆，由扫描端给 `label` / `sep`（Python 是点分的模块名和 `.`）。id 之间的关系只用 `cut.py` 和 `web/ids.js` 里的函数判断；
  页面上的名字来自数据（`names`、`labels`、布局的 `label`）。index.json 带 `format`，旧的点分索引读到时提示重新 scan。
- 为什么：点分名只对 Python 成立：C++ / CUDA 的文件名里有点（`runtime.cu`）、目录名里有连字符，Rust 的模块也不是点分的；
  多种语言放进同一张图，id 只能按路径。显示名换成扫描端给，Python 的图看起来和原来一模一样（新旧代码在 codestrata 和 vllm-omni 上
  scan、排版、叠加、时间顺序逐项对比一致，只有两处列表的先后变了）。run 的函数键本来就是 `文件:行`，不受影响，老 run 照样叠。
- 放弃的方案：Python 留点分名、别的语言用路径（两套规则，切面、排版、前端都要分情况）；id 用点分、显示名也从 id 拆（C++ 文件名表示不了）；
  符号键保留冒号分隔（`<路径>:<限定名>` 和函数键 `<路径>:<行>` 长得一样，容易混）。
- 在哪：`cut.py`（`unit_dir`、`root_dir`、`residual`、`within`、`label`、`find_dir`、`INDEX_FORMAT`）、`scan.py`（`unit_label`、`Symbol.key`）、
  `xref.py`（`_out_target`）、`trace/analysis.py`（`_module_paths`、`defining`）、
  `layout.py`（`_segs`、`name_in`）、`ui/graphview.py`（`names`、`labels`）、`ui/search.py`（`search_index`）、`web/ids.js`。

### 纵轴按依赖分层，不用 SCC 缩点，也不用架构高度
- 决定：`layout.layers` 直接对边排序：按权重贪心去环（Eades–Lin–Smyth），再 sifting（最多 20 轮）把逆向边的权重压到最小，
  最后从下往上数最长路分层（谁也不调的在最底层），超过 16 层按比例压进 16 条泳道。架构高度 `(出 − 入) / (出 + 入)` 只留在详情面板和派活顺序里。
- 为什么：Python 的循环 import 让强连通分量退化——vllm-omni 上 30 个包有 20 个塌进同一个环，缩点后分层信息全丢。
  架构高度只看每个模块自己的出入比例、不看谁连着谁，omni → omni_base 这种边会画成往上指。贪心在 vllm-omni 上为了拆环
  反过一条 4383 次调用的边，所以加 sifting（测试里的例子：贪心逆掉的权重 91，sifting 后 51）。从上往下数时，只被一个入口
  用到的叶子会飘在图中间（codestrata 自己的 render、highlight）。
- 放弃的方案：SCC 缩点后拓扑分层；架构高度当纵轴；从上往下数的最长路。
- 在哪：`layout.py` 的 `layers`、`MAX_LANES`；`scan.py` 模块说明末段；架构高度在 `cut.view` 里算。

### 叠了 run 时，分层按这次的调用加权
- 决定：import 边（图上不画，见「图上只有调用边」）当排版的静态权重 `1 + log1p(import 语句数)`；叠了 run 时，切面上节点间的调用另作为 runtime 边加进来，权重
  `RUNTIME_WEIGHT`（10）× `(1 + log1p(次数))`。
- 为什么：基类回调子类、按注册表分派这类和 import 方向相反的调用，按静态边分层会往上指。实测 runtime 边往上指的份额：
  vllm-omni 展开 entrypoints 从 23% 到 0%，nerfstudio 16% 到 6%，pip 47% 到 12%。log 是为了几百条 import 的一对不压过几十对只有一条的。
- 放弃的方案：静态图和叠不同 run 用同一套坐标只换颜色。代价是换 run 时节点会换泳道。
- 在哪：`layout.py` 的 `build`、`RUNTIME_WEIGHT`；`ui/graphview.py` 的 `graph_payload`（传 `runtime_edges`）；「只看跑到的」hot 图沿用总图的 `lane_of`。

### 交叉引用宁可不跳，也不跳错
- 决定：xref 只记能确定的：局部变量遮住的、MRO 上先碰到仓库外基类的、类型拿不准的一律不给链接；通过对象调用的方法
  （`engine.generate()`）只进「同名、没核实接收者类型」那一组，而且同名目标超过 3 个的名字整组丢掉。
  scan 之后改过的文件（按 xref 记下的大小和 mtime）不给 Ctrl+点击。
- 为什么：跳错一次，用户就不再信这个功能；改过的文件行列号对不上，链接会落在别的字上。`get`、`shape`、`to` 这种名字按名字列出来
  一大半都不是它，还会占掉 xref.json 的三分之一。
- 放弃的方案：没有类型推断的「按名字全列」。
- 在哪：`xref.py`（模块说明、`_Repo.class_member` / `unsure`、`ATTRS_MAX_SAME`）；`ui/source.py` 的 `_stale`、`_changed`、`xref_for`。
  名字解析本身算核心，跳转和引用列表的界面冻结（见「工程」第一条）。graph 的 scan 记录和 xref 同一遍、同一套名字解析，但定不下被调方的调用处另存在
  graph.json 里（给 scan-trace alignment 对行用），跳转不用它，这一条不变。

### scan 推一点类型：只推构造和类型标注写明的
- 决定：xref 推方法调用的接收者是什么类，只认代码里写明的：`x = C(…)`、`self.x = C(…)`（含 `C(…) if … else None`、`[C(…) for …]`）、
  参数 / 属性 / 类体字段的类型标注、函数 / 方法 / property 的返回值标注（`async def` 不算）、`list[C]` / `dict[K, C]` 取出来的元素、
  `getattr(obj, "x")`。一个属性几处赋的推不一样、有一处推不出，就当不知道；有标注的只按标注。函数里的局部变量只在这个函数里绑定过一次时才推
  （参数：没被重新赋值），不管分支、try、循环的先后。推出来的同时用于跳转和 graph 的调用记录。
  MRO 上排在仓库外基类后面的 mixin 方法：graph 的调用记录按 mixin 的算（近似，仓库外的基类多半没有它），跳转不给。
- 为什么：「代码里看不出」的一大半是 scan 不推类型造成的假阳性。vllm-omni 上 MiniCPM 一次请求（serving 阶段），只有 trace 的跨文件调用
  从 52.4% 降到 21.1%（按函数对 52.2% → 25.8%，请求路径上那一跳看不出的行 186 → 103，共 479 行）；剩下的主要是经仓库外的代码转一道、
  按配置或工厂造出来的对象（`self.model`、`self.connector`）。scan 新定下了 4105 处调用：这次跑到的 161 处里 157 处对上，另外 4 处
  标注写的是 Protocol、跑的是实现；没跑到的随机抽 40 处逐条读代码核对，全对。scan 用时 13.7 s → 14.2 s。
- 放弃的方案：接 pyright / jedi 这类类型检查器（多一个重依赖，大仓库上慢，还要配好被分析的环境）；按名字猜接收者（同名方法很多，猜错比不猜糟）；
  局部变量按语句顺序走、后赋的盖掉先赋的（10-01 第一版：`e = Slow(); if flag: e = Fast(); e.run()` 定成 `Fast.run`，跳错；改成只推绑定一次的之后，
  vllm-omni 全仓少定下 154 处，这次请求跑到的一处没少）；按控制流分支分别推（要做数据流分析，不值）。
- 在哪：`xtypes.py`（`rebound`：函数里绑定过不止一次的名字）；`xref.py` 的 `_Collect.self_spec` / `value_spec` / `type_spec`、`_Walk.type_local` / `bind_types` / `ann_type` / `call_type`、
  `_Repo.class_member_past_unknown`。测试 `test_type_inference`；前后对比用 `tests/bench/quality.py`。

---

## 边的分类

### import 触发的模块执行、类体执行都不是调用
- 决定：第 0 行（`<module>` 帧，含 3.12 泛型的定义帧）和落在类符号那一行的帧（class 语句执行时跑一次的类体）算「定义时的执行」，
  （哪些符号有这种执行由扫描端标 `x: ["defexec"]`，Python 给类标；`defining` 只认标记，不认语言）
  不计入符号、单元、文件的次数，作为被调方时不算调用，不把边染成橙色；「时间顺序」用同一个判断。
- 为什么：否则每条 import 边都会因为「导入过」被染成橙色，只被 import、一个函数都没调过的包也显示成「跑到了」。
  类体那一半起因是 httpx 的试用：sync 阶段惰性 import 了 httpcore，一堆 Async 类的类体被算成 sync 调了 async 的类。按行号认，已经录好的老 run 加载时一样分得出来。
- 放弃的方案：把 `<module>` 帧当普通调用。
- 在哪：`align.py` 的 `defining`、`to_package_graph`（`module_exec`、`class_frames`）；`seq.py` 的 `_Map.of`。测试 `test_class_body_is_definition_not_call`。

### 请求路径：调用上下文树，一个线程一节
- 决定：请求路径是每个线程的调用上下文树：一行是从线程的根到这里的一条调用链（父亲是调用那一刻真正在跑的那个，span 的 parent），
  同一条链上的多次调用合成一行，同一层按第一次被调用的先后排；这一段之前就在跑的祖先列出来当上下文（「之前」）。
  一个进程、一个线程一节（同名的线程合成一节），进程名取改过的进程标题，没有就取脚本名。页面上放在详情栏里（最多 4000 行），
  命令行 `codestrata path` 打全部。span 没有父亲的老 run 照老做法：一个函数挂在第一次调用它的那个调用方下面，同一个文件里调过来的
  根挂到同文件的调用方下面、标「同文件」。
- 为什么：「这次请求按什么顺序走过哪些函数」是定位要回答的问题，可时间顺序只给目录之间的边编号，边详情按次数排、轮询压在最上面；
  vllm-omni 的一次请求要在 39 条目录边里一条条点。按线程分开是因为 vLLM 的 stage 在不同进程、后台线程（收发、保存）一直在轮询，
  混在一起读不出主线。第一版（10-01 上午）是「第一次调用树」：一个函数只挂在第一个调用方下面——vllm-omni 上 thinker→talker 的交接 `llm2tts`
  （+0.546 s）因此挂到了 +0.108 s 的 `_handle_add_request` 底下（外部评审指出）；同文件的调用又没有时刻，只列出了跑过的一半函数。
  同文件的调用记进事件、span 带了父亲之后（10-01 下午），按真实的调用链建树。
- 放弃的方案：按时刻平铺所有调用（几千行，轮询淹掉主线）；只在时间顺序上加函数级的提示框；第一次调用树（新 run 上不再用）。
- 在哪：`path.py`；`seq.phase_calls`；`serve.py` 的 `/api/path`；`__main__.py` 的 `cmd_path`；`web/path.js`。测试 `test_request_path`、`tests/web/specs/path.mjs`。

### 运行时按进程 · 线程分列
- 决定（用户 2026-10-01 定的展示）：叠了录了时序事件的 run，模块图按进程 · 线程分成并排的几列，按进程分组；每列只放这条线程调到的节点，
  同一个节点在几列里各复制一份。列之间三种关系：共用同一个节点（各份放在同一高度，悬停 / 选中才连线）、谁起了谁（spawn）、谁把数据交给谁（handoff，
  标通道和次数）。线程名归一之后再合并（`Thread-N (target)` → target，线程池 `X_k` → `X ×N`），列按内容宽，进程能整个收起；
  列的先后：进程按启动先后，进程里顺着交接走。只跑仓库外代码、但是交接一头的线程给一列空的。
  叠了录了时序事件的 run 就是它，没有切回一张图的开关（用户 10-01：运行时一律按线程分，不要把所有线程合成一张的功能）；
  「这次跑了」「其中代码里看不出」管列里的边，时间顺序把列里的边和交接连线放在一起、跨线程按第一次发生的先后排名。
  列之间的连线可以点（详情里两头的函数），走两行节点之间的空隙、不从节点上穿过，标签放在节点上面当把手。
- 为什么：多进程、多线程的服务（vLLM：主线程、orchestrator、每个 stage 的收请求 / 主循环 / 输出 / 收发 chunk 的线程）合在一张图上
  看不出谁交给谁；请求路径按线程分节、只展开主线程，交接散在几节里。用户的原话是「有几个 thread 就把那个 thread call 到的 module duplicate
  对应的 thread 数量然后平行和主 thread 放置，这样我们就能够很清晰的看到 thread 和 thread 之间的 collaboration」。
  共用节点不一直画线：serving 阶段 21 个节点里 17 个在两列以上，一直画要几十条（外部评审量的），按同一高度对齐就看得出。
- 放弃的方案（设计说明里比过）：泳道时间线（Perfetto 那种，自己做工作量最大）、按时间合并的一张表（看不出重叠）、顺序图（箭头没有录的话只能按时刻猜）。
- 在哪：`lanes.py`（`build`、`thread_group`、`_order`、连线的 `pairs`）、`serve.py` 的 `/api/lanes`、`web/lanes.js`（`draw`、`linkRoute`、`paint`、`showLink`）、
  `web/app.js` 的 `lanesMode`、`drawMain`、`repaint`、`applyTimes`。
  测试 `test_lanes`、`tests/web/specs/lanes.mjs`。

### 叠了 run 默认只看跑到的
- 决定（2026-10-01 起只管没录时序事件的 run，录了的一律按线程分列）：选了一个 run 打开，默认是「只看跑到的」（单独排版的运行时图）；开关还在，用户自己关过之后换 run 不再替他打开。
  「这次跑了」数的是全部跑到的边（实线虚线都算），也管全部；「其中代码里看不出」只管虚线，前一个关着时点不了。
  点边：跑到的边的命中区在灰边上面，边上的次数、序号牌也能点。
- 为什么：vllm-omni 上叠了 run 首屏还是 72 个节点、286 条灰边，这次跑到的橙边在屏幕下面；「这次跑了 19」只数实线，实际跑了 39 条；
  hub 节点旁边在主路径的边上点下去，开的常常是一条 0 次的灰边。
- 在哪：`web/app.js` 的 `runBar`、`edgeChips`；`web/graph.js` 的 `draw`（命中区的叠放顺序）、`_placeLabels`、`paint`。测试 `tests/web/specs/overlay.mjs`、`calls.mjs`。

### 图上只有调用边，scan 和 trace 按调用行对上
- 决定：图上的边只有调用（函数 → 函数，含构造 `C(…)`、装饰器 `@x`、用 property、语法触发的特殊方法），每条边记 scan 看到的和
  trace 看到的。只 import、只读常量、类当参数、类型标注、`isinstance` 不成边；import 关系只当排版的权重。trace 说 F 在第 L 行调了 G，
  看 scan 在 F 的第 L 行记的调用：定下的被调方就是 G，或者写的是构造 `C(…)`、跑的是它沿继承找到的 `__init__` / `__new__` /
  `__post_init__`，两边都有；其余是只有 trace（代码里看不出会调到它），记下 scan 在那一行看到的是什么——基类的方法（子类覆盖的不算对上）、
  只知道名字、读了 property / 走了 `__getattr__`、这一行别的调用（仓库里的、仓库外的、定不下的一起列出，只看从这一行开始的调用、不算语法触发的特殊方法）、什么都没有。
  生成器 / 协程 / `with` 的帧在被消费的那一行才起：那一行没有写明的调用、或者被调方写在那一行那个调用的参数里，而 F 别处写了对 G 的调用，算两边都有（「写在第几行」）。构造的调用算在 F→C 上（被调方是类），
  和 scan 的那条记录对上，一次构造只算一次；构造时跑的代码不在仓库里的（dataclass 生成的 `__init__`、仓库外基类的）trace 看不到，
  边详情里单独说明，不说「没录到」。没有调用行的老 run 在整个函数里比，调用处按名字猜。画法：只有 scan 的灰实线；有 trace 的橙色、
  粗细不变、边上标次数，全都是只有 trace 的画虚线（收起后的一条边底下有一部分是的画实线，写明其中几次）。
- 为什么：graph 是核心模型（ARCHITECTURE 开头）：scan 和 trace 都落在同一张函数级的图上，scan-trace alignment 找两边的差别。
  早先在切面上比（被调的方法收到类上，在这条切面边的静态引用里就算「确认」）：这个文件 import 过那个类就算，调用落不到函数、更落不到行；
  按名字在调用方里找调用处，同一个函数里同名的调用好几处时分不出是哪一处（vllm-omni 的 `restore_queues` 有两处，`compute_logits` 四处），
  经框架调到的（`nn.Module.__call__` → `forward`、`map`）根本找不到。按行对之后这些都是实测的。子类覆盖算差别：
  多态正是要照亮的地方（基类的调用跑到了哪个子类）。只 import 的边、「仅类型」的边、死 import 的原因都不画了：它们不承载调用。
  构造挪到 F→C：trace 记的是 F→`Base.__init__`，基类在别的文件里时不挪就会多出一条「代码里没写」的边，而代码里写的那条 F→C 反倒是灰的；
  `__new__` 和 `__init__` 都在仓库里的类，一次构造 trace 记两次。
- 放弃的方案：每条边是「静态引用 × runtime 调用」的交叉（confirmed / static / dynamic / import_only，2026-09-30 之前）；
  三种边的分类名（「确认调用」「只有静态」「运行调用」）；按名字猜调用处（只留给没有调用行的老 run）；收起的边底下有一条只有 trace 就画虚线。
- 在哪：`graph.py`（scan 记录）；`align.py` 的 `to_package_graph`、`classify`、`judge`、`hot_on_cut`、`scan_edges_on_cut`；
  `ui/graphview.py`、`ui/edge.py`；`web/graph.js`、`web/panel.js`。测试 `test_trace_only_consistent_across_cuts`、`test_call_lines_for_syntax_calls`、
  `test_constructor_calls_counted_once`、`test_trace_only_notes`、`test_ctor_methods_and_property_setters`。

### `if TYPE_CHECKING:` 里的 import 不是依赖
- 决定：这种 import 不进 `edges`，不算架构高度和分层。类型标注不是调用，图上也没有它。xref 照样解析这些名字（标注里能 Ctrl+点击）。
- 为什么：运行时不执行。早先它和普通 import 一样算边，`from __future__ import annotations` 下标注里的名字又被算成「用到了 1 个符号」，
  图上凭空多一条实线回边、高度也被带偏。
- 放弃的方案：和普通 import 一样算边。
- 在哪：`scan.py`（`typeonly`）。测试 `test_type_checking_imports_are_not_dependencies`。

### 调用方是栈上最近的仓库帧；case 自己的代码例外
- 决定：标准库、site-packages 等仓库外的帧不入栈，A → 框架 → B 记成 A → B。入口脚本同一层目录（执行目录在仓库外时还有
  `CODESTRATA_CASE_DIRS`）里直接放着的 `.py` 算 case 的代码：只在栈上当调用方，键记成 `<外部代码>/文件名:行`，不计数、不上图。
- 为什么：只入栈仓库帧才能在大框架上保持低开销（仓库外的代码第一次命中就 DISABLE）。case 例外的起因：case 里定义、被仓库回调的函数
  （Flask 的视图）再调仓库函数时，调用方会落到最近的仓库帧上，画出 `dispatch_request → jsonify` 这种并不存在的边。
  代价（已知问题）：穿过框架事件循环的调用显示成直接调用。
- 放弃的方案：栈上只有仓库帧。
- 在哪：`trace/hook.py` 的 `_case_rel`、`_rel`、`_enter`。测试 `test_callbacks_from_case_code`、`test_case_code_detection`。

---

## 录制

### 用 sitecustomize 覆盖所有子进程，环境变量一律明确写死
- 决定：driver 把放着 `sitecustomize.py` 的临时目录插到 `PYTHONPATH` 最前面，每个新起的 Python 进程（包括 setsid 出去的服务）
  都自动挂上 hook。`CODESTRATA_EVENTS` 每次明确写 1 或 0，`CODESTRATA_PHASE_AT` 没给也写 `[]`，`CODESTRATA_CASE_DIRS` 在仓库里时写空串。
- 为什么：vLLM 这类框架每个 stage 一个 engine core 进程，只 trace 父进程会丢掉最关键的部分。明确写值是为了 shell 里 export 过的旧值
  不会悄悄生效——否则录出来的 run 和它的重录命令对不上。
- 放弃的方案：只 trace 父进程。
- 在哪：`trace/`（driver / hook） 的 `run`、`_SITECUSTOMIZE`；`__main__.py` 的 `cmd_trace`。

### 调用栈进出都订阅，按文件名缓存
- 决定：订阅 `PY_START` / `PY_RESUME` / `PY_THROW` 入栈、`PY_RETURN` / `PY_YIELD` / `PY_UNWIND` 出栈；`PY_UNWIND`、`PY_THROW` 不返回 DISABLE；
  sys.monitoring 的工具号先试 4、3，最后才用 `PROFILER_ID`。「代码 → 仓库文件」的缓存按文件名，不按 code 对象；模块顶层记成第 0 行。
- 为什么：只订阅 `PY_START` 时，调用者会变成「上一个开始执行的函数」（A 调 B、B 返回、A 调 C 被记成 B→C）。`throw()` / `close()` /
  asyncio 取消经 `PY_THROW` 恢复帧，不订阅会把清理代码里的调用挂到别的帧头上；这两个事件返回 DISABLE 会在被 trace 的程序里抛
  ValueError（测试里 asyncio 取消崩过）。3.12 起 cProfile 也走 sys.monitoring、占着 `PROFILER_ID`。code 对象按内容比较相等、不比文件名，
  几个空 `__init__.py` 会被当成同一个；模块顶层记第 1 行会和写在第 1 行的函数撞键。
- 放弃的方案：只订阅 `PY_START`；按 code 对象缓存。
- 在哪：`trace/hook.py` 的 `_SITECUSTOMIZE`（`_rel`、`_key`、`_enter` / `_leave`、注册回调那一段）。

### hook 不装信号处理器，用 STOP 文件换最后一次落盘
- 决定：被 trace 的程序的信号处理一律不动。driver 升级到 SIGTERM 之前写 `$CODESTRATA_OUT/STOP`，各进程的落盘线程 1 秒内看到就落一次盘
  （`why=stop`），driver 最多等 1.5 秒再发信号。
- 为什么：hook 的底线是不改程序的语义。装过一个「先落盘再退出」的 SIGTERM 处理器，评审证明它改变行为：Python 层的处理器要等主线程回到
  解释器才跑，卡在 C 里的进程收到 SIGTERM 不再立刻死，multiprocessing 的退出会挂住；链式调用旧处理器的程序被直接杀掉。
  代价是这份数据截止到发信号前一秒左右。
- 放弃的方案：给没人接管的 SIGTERM 装处理器。
- 在哪：`trace/`（driver / hook） 的 `_before_term`、`_flusher`（读 STOP）；测试 `test_program_semantics` 断言 SIGTERM 仍是 `SIG_DFL`。

### 子进程的数据不能丢、也不能写坏
- 决定：每个进程映像一份分片 `part-<pid>-<t0ns>.json`；包住 `os._exit` 和 `os.execv` / `os.execve`，先落盘再真的退出 / exec；落盘线程每 10 秒
  落一次；所有写在一把 RLock 下、临时文件名带线程号，最后一次落盘开始后落盘线程不再写；分片目录不在就不写（不 makedirs）。
- 为什么：atexit 不是总会跑——multiprocessing 的 fork 子进程以 `os._exit` 结束，exec 时不跑，被 SIGKILL 的什么都不跑。只用 pid 命名时，exec 之后
  新程序的分片会冲掉 exec 之前的。实测不串行时，进程退出撞上定时落盘会把分片写坏，merge 悄悄丢掉整个进程（`test_dump_race` 让 8 个进程恰好在
  第 10 秒前后退出）。不 makedirs：录制收尾、parts/ 打包删掉之后，还活着的孤儿进程不能把它重新建出来。`os._exit` 的包装无论如何都要真的退出，
  否则 fork 出的子进程会逃进父进程的代码。
- 放弃的方案：`part-<pid>.json`；两个线程写同一个 `.tmp`；`_dump` 里 `os.makedirs`。
- 在哪：`trace/hook.py` 的 `_base`、`_write`、`_dump`、`_exit_hook`、`_wrap_exec`、`_flusher`、`_after_fork`（fork 后重建锁）。

### 命令放进自己的会话，按 SIGINT → SIGTERM → SIGKILL 三级停
- 决定：`Popen(start_new_session=True)`；driver 接管 SIGINT / SIGTERM / SIGHUP / SIGQUIT（已被忽略的保持忽略）。超时或收到信号时对整个进程组
  发 SIGINT，等 `--stop-grace`（默认 90 秒）→ 写 STOP → SIGTERM → 等 15 秒 → SIGKILL；再来一个信号直接升一级，SIGQUIT 跳过 SIGINT。
  已经忽略 SIGINT 的进程（看 `/proc/<pid>/status` 的 SigIgn）直接从 SIGTERM 开始。
- 为什么：老做法 `subprocess.call` 加超时，超时或 Ctrl+C 时直接 SIGKILL 掉 bash，case 脚本的 `trap … EXIT` 来不及跑，setsid 出去的 API server
  和 engine core 成了孤儿、一直占着显存，最后 ≤10 秒的数据也丢了。SIGINT 放最前：Python 进程会抛 KeyboardInterrupt、正常走 atexit，case 的 trap
  也有机会停掉自己的服务。非交互 bash 用 `&` 起的后台进程天生忽略 SIGINT，发多久都没用。保持 SIGHUP 的忽略是为了 nohup 下的录制不被关终端打断。
- 放弃的方案：`subprocess.call` + 超时。
- 在哪：`trace/driver.py` 的 `run`、`_stop`、`_levels`、`_ignores`；测试 `test_nohup`、`test_sigquit`。

### 残留进程按 environ 和 (pid, 启动时刻) 认
- 决定：命令退出后，扫 `/proc/*/environ` 找 `CODESTRATA_OUT` 等于本 run parts 目录的进程；另外认「分片文件名里的 pid 还活着、`/proc/<pid>/stat` 的
  启动时刻等于分片里记的 `st`」的进程；driver 还设 `SPT_NOENV=1`。停的时候每一步都用 (pid, 启动时刻) 核对，停完再找，最多三轮，全停完才 merge。
  判断 driver 是否还活着、run 是否「还在录」也比对 pid 和启动时刻。
- 为什么：vLLM 的 engine core 用 setproctitle，它默认借 environ 那块内存写标题，会把 `/proc/<pid>/environ` 清空；两道防线任一生效都认得出。
  pid 会被复用，不核对启动时刻就会误杀、或把早死的 driver 当成还在录。残留的 bash 在 EXIT trap 里还会起新的子进程，只停第一批会漏。
- 放弃的方案：只看 environ；只看 pid。
- 在哪：`trace/driver.py` 的 `leftovers`、`stop_pids`、`stop_leftovers`；`runs.py` 的 `_alive`、`live`；`trace/driver.py` 的 `proc_start`；测试 `test_leftover_by_part_file`。
  只有 Linux 能这样做（已知问题）。

### `--phase 名字=函数`：进程第一次进入这个函数时切阶段，每个阶段整个 run 只切一次
- 决定：hook 在 `_enter` 里「第一次见到这个键」的分支按 (文件, co_qualname) 认触发函数（3.10 退回装饰器行 + 短名字），赢家用 O_EXCL 建
  `PHASE-<名字>.fired` 标记、原子地换 PHASE、停 0.1 秒；别的进程每 50 ms 看一次 PHASE。函数写法在建 run 之前解析（`模块:qualname` 查索引、
  顺着 C3 MRO 找继承来的方法；`文件路径:qualname` 按解释器的规则现算），写错立刻报。
- 为什么：第一次录真 GPU 的离线示例是一条阻塞的 python 命令，shell 看不到加载什么时候完、没法写 PHASE；事件数据显示 74 s 里 `Omni(...)` 占 60.5 s、
  `generate` 只有 1.84 s，启动和推理跑到的函数几乎不重叠（跨文件被调方只在启动 215 个、只在推理 202 个、共有 23 个），混成一段就分不清。
  分段写在 codestrata 的命令上、不改 sh。只在第一次见到键时检查，热路径零开销；标记保证后来才第一次进这个函数的进程不会把阶段切回去；
  停 0.1 秒让工作进程在 generate 期间的活都算进 generate（`test_phase_at`）。
- 放弃的方案：只靠 case 脚本写 PHASE（仍然支持，两种可以一起用）；按命令行里的先后切。
- 在哪：`trace/`（analysis / hook） 的 `_trig_check`、`_fire`、`resolve_phase_at`、`_qualnames`、`_inherited`、`fired_phases`、`merge_phase_log`。

---

## run 存储

### run 是唯一不能重建的数据：只增不删，只有 `runs rm` 能删
- 决定：静态分析只有一份（scan 时整份替换）；每次 trace 都是 `.codestrata/runs/<YYYYMMDD-HHMMSS-case>/` 下一个新目录，同名 case 重录不覆盖。
  除了 `runs.remove` 和 `runs.remove_events`，没有代码删 run 里的东西；`rm` 只认完整的 run id，还在录的不删。
  `.codestrata/` 里写 `.gitignore`（`*`）和一行 README.txt；runs/ 可以是软链；scan 跳过以点开头的目录。
- 为什么：一次录制往往是几分钟 GPU（起服务、加载模型、跑一段对话）。今天录 MiniCPM、明天录 Qwen，每个都应该录一次就能反复用。
  case 名会解析到「最新一次录完的」，拿它删东西太容易删错。旧说法「`.codestrata` 可随时重建」可能让以后的会话 `rm -rf`，所以靠软链、README.txt、
  README 三道防线；`.codestrata/` 不进 git 是因为实测 vllm-omni 的 `git status` 一直显示它。
- 放弃的方案：每个 case 一份 `trace-<case>.json`、重录覆盖（第一次读到时自动迁成 run）；`rm` 接受 case 名。
- 在哪：`runs.py`（模块说明、`new_run`、`remove`、`remove_events`）；`__main__.py` 的 `_outdir`、`_README`；`scan.py` 的 `_skip_dir`。

### run 里分原始数据和派生数据，原始的永久保留
- 决定：原始数据（`parts.tar.gz`、`events/raw.tar.gz`、`files/`、`legacy/`、run.json 和 detail.json 里录制时写下的字段）finalize 之后不再变；
  派生数据（`counts.json.gz`、`events/spans/`）由 `runs merge` 从原始数据重建。收尾拆成 `capture`（只跑一次）和 `derive`（可以重做）；
  打包先写临时包、重新打开核对成员数再替换，从不拿成员少的包换成员多的；事件日志单独打一个包。
- 为什么：合并逻辑还不成熟、以后还会改；事件的配对和折叠是最不成熟的逻辑。实测 parts 5.1 MB 打包后 365 KB；只存阶段计数 gzip 后 58 KB（原来的文件 1.75 MB）。
  录制时才拿得到的东西（执行时的哈希、脚本副本、GPU、git 改动）重算时不能拿「现在的样子」去盖。事件日志单独打包，`runs rm --events-only`
  就是删掉 events/ 一个目录，计数的原始包一个字节都不碰。
- 放弃的方案：只存合并后的计数；事件日志和分片混在同一个包里。
- 在哪：`runs.py` 的 `finalize`、`capture`、`_pack`、`_pack_all`、`_build_events`、`derive`、`merge_run`。

### 计数按「文件:首行号」存，加载时映射到当前 index；改过的文件按 qualname 挪
- 决定：run 只存原始键 `rel:firstlineno` 和录制时的 qualname（`names`），加载时现映射到当前 index 上。录制之后改过（或安装包和仓库不一致）的文件，
  `align.remap` 按 (文件, qualname) 把键挪到函数现在的行号（去掉 `.<locals>` 再查），对不上的改成 `文件:-1`、计入 `unmatched`。
  Python 3.10 没有 `co_qualname` 就不记名字。
- 为什么：代码改了之后老 run 照样能用，不让整个 run 作废。行号是会随编辑变的位置，名字是只有录制时拿得到的身份，两样都存，读的一侧才有退路。
  对不上的不留原键：老行号可能正好是另一个函数现在的定义行，数字看着正常其实是别人的；也不改成 0：第 0 行是模块顶层，这些调用就等于丢了。
  3.10 的 `co_name` 只是短名字，方法 `Model.forward` 会被挪到同文件里同名的顶层函数上——错挪比不挪更糟。
- 放弃的方案：存 index 快照；对不上的保留原行号（设计稿最初的写法）；3.10 退回 `co_name`。
- 在哪：`runs.py` 的 `load`、`load_counts`；`align.py` 的 `remap`、`sym_locs`、`to_package_graph`（-1 落进 `anon`）；`trace/hook.py` 的 `_key`、`_names`；测试 `test_remap_moved_functions`。

### 「录制之后改过没有」拿执行时的哈希和 index 比，不和工作区比
- 决定：hook 在每个进程第一次跑到一个文件时取它内容的 sha256 前 16 位；scan 对同一份原始字节取同一种哈希写进 `file_sha`。`runs.file_state` 逐个文件定
  mismatch / outside / gone / unknown / changed，只有 changed 和 mismatch 参与挪键；老 index 没有 `file_sha` 时才退回比工作区。
- 为什么：叠加用的行号来自 index，改了代码但没重新 scan 时 index 仍和 run 对得上，拿工作区比会误报。要「录一次永久复用」就得知道录制时实际执行的是哪一版，
  收尾时再取的话录制中途改过的文件会被当成没改（这种文件记进 `changed_during`，run 标 partial）。哈希原始字节而不是解码后的文本：
  否则每个带 BOM 或 CRLF 的文件都会被判成改过。examples 这类不在 index 里的文件标 outside，不叠加也不算过期。
- 放弃的方案：`trace.stale_files` 拿 run 比工作区（只留作老 index 的退路）；收尾时才取哈希。
- 在哪：`trace/hook.py` 的 `_rel`（`_shas`）；`scan.py` 的 `scan`（`file_sha`）；`runs.py` 的 `sha16`、`capture`、`file_state`。

### 清单拆成 run.json 和 detail.json，目录扁平，只用文件不用数据库
- 决定：`runs/<id>/` 一层；列表只读几 KB 的 run.json，procs、哈希、环境在 detail.json；所有写都先写临时文件再 `os.replace`。不用 sqlite，不做就地 schema 升级，
  读取端兼容所有 schema。老格式的迁移加文件锁、只拷不挪、核对（计数逐键相等、legacy 逐字节相同）通过才删老文件。
- 为什么：列 100 个 run 时不用读几十 MB；glob 只需一层，按 id 排序就是按时间排序。run 只有几十个，按时间窗取数据靠分块加 index.json 就够（设计稿第 10 节）。
  迁移只拷不挪：runs/ 常是指到另一块盘的软链，rename 跨不了文件系统。
- 放弃的方案：sqlite；按 case 分层的目录；迁移时用 rename 认领（设计稿 3.7 的原计划）。
- 在哪：`runs.py` 的 `new_run`、`catalog`、`_write`、`migrate`、`_migrate_locked`、`_cleanup_legacy`。

### REF 是「完整 id 或 case 名」；时序事件的问题不改 status
- 决定：`runs.resolve` 先当完整 id 查，再当 case 名：取最新一次 ok 的，没有就最新的 partial（并提示），再没有取最新的任意一个；后面可加 `@阶段` 或 `@t=起-止`。
  不支持 id 前缀。事件到了行数上限（`truncated`）或整理失败（`error`）只记在 events 摘要里，不加 problem。
- 为什么：id 前缀和日期冲突。重录中途失败时 case 名不会被失败的那次抢走。计数是完整的，要是因为时序缺了一截降成 partial，拿 case 名解析时就会跳到更早的一次
  （`test_events_cap` 用上限 1 录，断言仍是 ok）。
- 放弃的方案：id 前缀、`case/tag`、`case/latest`。
- 在哪：`runs.py` 的 `resolve`、`derive`、`_build_events`。

### 复刻命令存录制时原样的命令，而不是事后拼
- 决定：`main()` 在解析参数之前把原样 argv（入口脚本取绝对路径）和当前目录记成 run.json 的 `invocation`，`cmd_trace` 另记白名单里的继承环境
  `env_inherited`；`rerun_command` 给 `cd <目录> && <原样命令>`。只有没存 `invocation` 的老 run 才按参数拼。
- 为什么：按参数拼的漏掉什么就少什么：当时在哪个目录跑、相对路径指到哪、codestrata 装在哪、shell 里 export 了什么。目标是页面上能拿到一条照抄就能
  复刻的命令。`test_rerun_command_reproduces` 在 / 下照抄这条命令，再录出同样分段的 run。
- 放弃的方案：case 定义文件（cases.toml）：目标是录一次复用，不是方便重录，也省掉 TOML 和对 3.11 的依赖；变体就是另一个 `--case` 名加 `--env` / `--tag`。
- 在哪：`__main__.py` 的 `main`、`cmd_trace`；`runs.py` 的 `new_run`、`inherited_env`、`rerun_command`、`fmt_seconds`。

---

## 叠加

### 每个请求自带 run，换 run 不重启 serve
- 决定：`/api/graph`、`/api/edge`、`/api/refs` 都接受 `run=`，由 `Handler._hot` 每次现调 `runs.resolve`，按
  (run id, 阶段, (counts.json.gz 和 run.json 的 mtime)) 缓存最近 8 个；不做文件监视，`/api/runs` 每次现 glob。`serve --hot` 只决定页面打开时先选哪个，
  存成解析好的完整 id；不给时只显示静态图。
- 为什么：以前 hot 是 `Handler` 的类属性，换 run 要重启。每次现解析：删掉的 run 立刻 404，写 case 名时跟着最新的走，serve 开着时新录的也用得上。
  run.json 进缓存键是因为 meta 里带着 tags / note。浏览器验收：换 run 57 ms、换阶段 109 ms 出图。默认存完整 id：同一个 case 又录了新的也不会悄悄换掉默认。
  不自动选最近的 run：理由未记录（设计稿第 11 节只写了推荐不选）。
- 放弃的方案：进程级的单个 hot；文件监视；serve 热加载 index（scan 之后仍要重启 serve，主菜单会在原端口替人重启）。
- 在哪：`serve.py` 的 `Handler._hot`、`Handler._runs`、`main`（`default_run`）；`web/ds.js` 的 `CS.ds.run`。

---

## 时间轴与时间顺序

### trace 记调用写在调用方的哪一行：录指令偏移，写分片时换成行号
- 决定：hook 每记一条函数边，同时记下调用方（栈上最近的仓库帧）当时执行到的指令偏移（`f_lasti`），和每个调用处第一次见到时
  调用方的 code；写分片时才按 code 的行号表把偏移换成行号，拆成 `func_edges`（`a|b`）和 `func_lines`（`a|b|行`）。热路径上用元组做键，不拼字符串。
- 为什么：graph 要按行把 trace 和 scan 对上（同一个函数里同名的调用好几处时，按名字分不出是哪一处；经框架调到的按名字根本找不到）。
  行号不能当场取：3.12 的 `f_lineno` 要从函数头解码行号表，函数越长越慢（200 行的函数尾部近 1 μs），`f_lasti` 是现成的（20 多 ns）。
  两个版本上偏移换出来的行和 `f_lineno` 逐个比过一样。代价（2026-09-30，全是跨函数调用的极端情况，300 万次调用）：3.12 上 3.4 s → 4.0 s，
  3.10 上 4.3 s → 4.85 s；vllm-omni 的启动阶段（约 2 万次调用、70 s）前后一样。
- 放弃的方案：当场取 `f_lineno`（同一个基准 +50%，长函数更糟）；按名字在调用方里猜调用处。
- 在哪：`trace/hook.py` 的 `_enter`、`_fcalls` / `_fcode`、`_line_at`、`_write`；`trace/analysis.py` 的 `merge`；`align.remap`（调用行跟着调用方挪）；测试 `test_call_lines`。

### 时序事件记每一次调用，hook 只记、配对和折叠事后做
- 决定：录时序事件时（2026-10-01 起默认录，`--no-events` 关掉）hook 只写原始行：调用时分配进程内的 span 号，返回 / 挂起 / 恢复按帧找回同一个号写出去；日志里不写帧地址。
  记每一次调用（口径同 `func_edges`，同文件的也记，2026-10-01 起；之前只记跨文件的）。配对、深度、父 span、第一级折叠在 `events` 里事后做，
  第一级折叠按 (父 span, 段) 认兄弟；span 带父 span 的下标。上限 `CODESTRATA_EV_MAX`（默认 300 万）只管调用行。
- 为什么：hook 跑在被 trace 的程序里，每次调用都要付开销，所以只做最少的事；算法改了不用重录，`runs merge` 从原始日志重建。
  能对账：span 的 Σrep 等于 `func_edges` 之和，父 span 的被调方就是这一行的调用方（`test_events_truth`、`test_events_fake_service`）。
  同文件的也记（用户 2026-10-01 定）：只记跨文件时，请求路径缺了中间那几层（vllm-omni MiniCPM 的 serving 里同文件的调用 12.6 万次，比跨文件的 9.2 万次还多，
  24% 的 span 和它的父 span 之间隔着没记的同文件调用），只能从计数里猜着补、没有时刻。按 span 号不按栈：同一线程上交错的 asyncio 协程，
  先开始的不一定先结束。父 span 按重放时这个线程上最里层正在执行的 span 定，而不是按时间包含 + 深度：协程挂起期间别的协程在这个线程上跑，
  时间上包住它的不一定是它的父亲。按父 span 不按深度认兄弟：两个协程各自的子调用深度相同却不是兄弟；看「段」：中间有过挂起 / 恢复，合出来的时间窗会盖住别的协程的调用。
  上限只管调用行，否则上限前开始的调用会显示成没返回。默认录（2026-10-01 起）：请求路径、时间顺序都要它；MiniCPM 离线示例在 5090 上整条命令
  不录 86.0 s、`trace --events`（那时只记跨文件）87.9 s。之前默认不开，是因为 GPU 上的开销还没实测。
- 放弃的方案：按栈配对；按深度认兄弟；hook 里直接写 span；只记跨文件的调用（2026-10-01 之前）；每对函数第一次出现时记下栈（同文件的都记了就不需要）。
- 在哪：`trace/hook.py` 的 `_ev_call`、`_ev_mark`、`_ev_room`、`_ev_flush`；`events.py` 的 `parse`、`pair`、`fold`、`build`。

### 谁起了谁：包一层 Thread.start、fork_exec，fork 前后各记一笔
- 决定：时序事件开着时，hook 包一层 `threading.Thread.start`（记下在哪个线程的哪个 span 里起的，新线程第一次登记时写 F 行）、
  `_posixsubprocess.fork_exec` 和 `os.posix_spawn(p)`（起完拿到 pid，在父进程里写 P 行），`os.register_at_fork` 的 before / after_in_child
  （fork 之前记下，子进程里写 B 行）。「在哪个 span 里」是从调用处往外找第一个记过账的帧。只包一层、照原样调，出错不影响被 trace 的程序。
- 为什么：P0（用户 2026-10-01 定）要画线程之间「谁起了谁」。subprocess 和 multiprocessing 的 spawn 最后都经 `fork_exec`，fork 方式都经 `os.fork`，
  包这几处就够，不用为了打补丁去 import multiprocessing。exec 出来的子进程是全新的解释器，只有父进程知道是谁起的；fork 出来的子进程继承了父进程的
  内存，fork 之前记下、子进程自己写最简单。
- 放弃的方案：按时刻猜（子进程的起始时刻落在父进程的哪个 span 里——同一时刻好几个线程都在跑）；包 `subprocess.Popen`、`multiprocessing.Process.start`
  （要 import 它们、而且漏掉直接用 `os.fork` 的）。asyncio 的 `create_task` 不记：task 跑在同一个线程里，不另起一列。
- 在哪：`trace/hook.py` 的 `_ev_here`、`_start`、`_spawned`、`_before_fork`、`_after_fork_ev`；`events.py` 的 `parse`、`_origins`。测试 `test_events_truth`。

### 谁把数据交给谁：盯几种常见的通道，进程内按对象、跨进程按消息指纹配对
- 决定：时序事件开着时，hook 在 `queue`（Queue / PriorityQueue / LifoQueue 的 `_put` / `_get`）、`asyncio.queues`（同）、`janus`（`_put_internal` / `_get`）、
  pyzmq（`zmq.sugar.socket.Socket` 的 `send` / `recv_multipart`，`zmq._future._AsyncSocket` 的 `send` / `send_multipart` / `recv_multipart`）第一次被 import 完的时候
  包一层（`sys.meta_path` 上的 `_OnImport`），放 / 取、发 / 收各写一行。整理时队列按（队列 id, 对象 id）先进先出地配——对象在队列里一直活着，id 不会被复用；
  ZMQ 按消息指纹（数据帧的长度 + 首尾 32 字节的哈希）跨进程先发先收地配。ZMQ 按帧记：带 SNDMORE 的帧攒到一条消息的最后一帧再算（vLLM 的输出先
  `send(第一帧, SNDMORE)` 再 `send_multipart(其余的)`）；ROUTER 发的时候去掉第一帧（对方的身份，不发出去）、收的时候也去掉（vLLM 的 orchestrator 用 ROUTER、
  stage 用 DEALER）。asyncio 版的 ZMQ socket 背后真正收发的是一个同步的影子 socket：影子的收发不记，由 asyncio 那一层记，收的 span 是等它的协程。
  第一版（`e95d86d`）只包了 multipart、不认 ROUTER 的身份帧，在 vLLM 上一条都配不上（外部评审读 vLLM 源码指出）；改了之后用 vllm-omni 环境里真的 pyzmq
  （asyncio ROUTER ↔ 同步 DEALER、SNDMORE）在临时仓库上录过一遍，三条交接都配上了。
- 为什么：P0（用户 2026-10-01 定）要画线程之间「谁把数据交给谁」；只按时刻排的话同一时刻好几个线程都在跑，看不出因果。vllm-omni 的交接正好走这几种：
  主线程和 orchestrator 之间是 janus 队列，orchestrator 和各个 stage 进程之间、stage 进程里收请求的线程是 ZMQ，引擎循环和收发线程之间是 `queue.Queue`。
  按模块被 import 时再打补丁，不为了打补丁去 import asyncio、pyzmq（每个被录的 Python 进程都会跑 hook）。
- 放弃的方案：按 payload 的内容（pickle）配对（贵，还要拷大张量）；包 `Socket.send` / `recv`（multipart 会调它们，记重复）。
  没盯的：`queue.SimpleQueue`（C 写的，包不了）、线程池的 `submit`、共享内存、裸管道和 socket——stage1 到 stage2 走的共享内存通道两边都是仓库里的同一个模块，靠「共用同一个模块」那种连线连上。
- 在哪：`trace/hook.py` 的 `_queue_patch`、`_fp`、`_zdata`、`_zsend`、`_zmq_sync`、`_zmq_async`、`_OnImport`；`events.py` 的 `_handoffs`。
  测试 `test_events_truth`（`trace_cases/fakezmq` 是照 pyzmq 的样子写的假 pyzmq：send_multipart 逐帧调 send、ROUTER 的身份帧；场景照 vLLM 的收发方式）。
### 调用的先后画在模块图的边上，按名次上色
- 决定：录了事件的 run 在 serve 里多一个「时间顺序」开关：看得见的、跑到的边按第一次被调用的先后排名 1…N，按名次在三个色标之间插值上色、标序号。
  同一个进程里第一次到最后一次隔了超过阶段总长一半、而且至少 5 次的，序号后加 ↻。
- 为什么：讲一条调用链时的先后直接画在同一张图上，跟着切面、阶段一起变。按名次不按时刻：模型加载这种长时段会把按时刻插值的颜色都挤到一头。
  ↻ 的判据按同一进程算：几个 worker 各初始化一次、隔得再远也不算反复；轮询、每个 token 都走一遍的路径才算，它的序号只说明从什么时候开始。
- 放弃的方案：单独一张时序图（生命线 + 消息，M5 做过，已整个删掉）；按时刻插值上色。
- 在哪：`seq.py` 的 `edge_times`、`REPEAT_MIN`；`serve.py` 的 `Handler._seq`（`/api/seq/edges`）；`web/graph.js` 的 `_rankTimes`、`timeColor`、`_paintOrder`；`web/app.js` 的 `applyTimes`。

### 合成一行的连续调用，按次数均匀摊在它盖住的时间上
- 决定：第一级折叠只记第一次的开始和整行的结束；按阶段、按时间段计数时，把 rep 次调用均匀摊在 [开始, 结束] 上，没返回的整行算在开始。
- 为什么：一行能盖住几十秒（vllm-omni 的轮询，一行 3852 次、从 68 s 到 112 s），整行算在开始那一刻，一秒的时间段里会多出几千次、之后几十秒一次都没有。
  均匀是近似：只知道总数和首尾。
- 放弃的方案：整行算在开始时刻。
- 在哪：`seq.py` 的 `_calls_in`（`_pairs` 和 `window_counts` 共用）；测试 `test_calls_in_and_run_end`。

### 任意时间段写成 `@t=起-止`，和阶段名放在同一个位置
- 决定：时间轴上拖出的一段时间写成 REF 的 `@t=起-止`（微秒），CLI 的 `--hot`、serve 的缓存键、页面地址都照走；次数由 `seq.window_counts` 按这段时间里的 span 现算，
  形状和 counts.json.gz 一样，后面的 `remap`、`to_package_graph` 不分两种。拖到和整个 run 或某个阶段差不到 4 像素就当成它。
  时间轴终点取最后一条 span 的结束、最后一次切阶段、run 的时长三者最大的。
- 为什么：不另开通道。counts.json.gz 是按阶段切的，分不出任意一段时间，带时刻的只有时序事件。吸附：拖回原样不会凭空多出一个时间段。
  只按 span 定终点时，被 SIGTERM / SIGKILL 停掉的服务最后的调用没返回，最后一个阶段会倒着走。代价：时间段的次数只有跨文件的调用（横幅上写明）。
- 放弃的方案：阶段之外另设时间窗参数。理由未另外记录。
- 在哪：`runs.py` 的 `resolve`、`load`；`seq.py` 的 `parse_window`、`window_counts`、`run_end`、`phase_segments`；`web/timebar.js` 的 `snap`。

### span 读一遍，按切面归很多次
- 决定：`_pairs` 把整个 run 的 span 解压读一遍，按阶段聚合成「键对 → 首次 / 末次 / 次数」，缓存 8 份；`edge_times` 再把键对经 rel → 单元 → 当前切面节点归一遍。
  「键 → 符号」和「是不是定义」与模块图共用 `analysis.sym_locs`、`analysis.defining`。同一个请求同时来只算一次（按键加锁）。
- 为什么：解压、读 span 是贵的一步，归到节点很便宜。记录的数字（没复测）：158 万条 span 的 sympy run 第一次 2.2 s，之后换阶段 9 ms、每个新切面约 30 ms。
  共用判断，整个 run 上每条边的次数和 hot 图逐条相等（`test_seq_edge_times`）。
- 放弃的方案：每次请求按时间窗重读块（时序图时代的 16 块 LRU）。
- 在哪：`seq.py` 的 `_pairs`、`_pairs_scan`、`_Map`、`edge_times`、`_PAIRS`、`_BUSY`。

---

## 前端

### 一套零构建的前端，数据只经 ds.js 从 serve 取；取数只在 ui/ 里做
- 决定：前端是 `codestrata/web/` 下的普通 HTML/CSS/JS，零构建。UI 只调 `web/ds.js`，它 fetch 相对地址 `api/…`；数据一律由 `ui/` 下的模块从 graph（索引和叠上的 run）里取，serve 按请求给。
- 为什么：地址写成相对的，页面在 `/` 下和主菜单转发的 `/v/<端口>/` 下都对。零构建：理由未记录。
  单文件导出、GitHub 静态站曾经是另外两种数据源，2026-09-30 去掉了（见「不做分享（暂时）」）。
- 放弃的方案：没有记录。
- 在哪：`web/ds.js`；`ui/`；`serve.py`。

### 按浏览器里图框的宽度排版
- 决定：前端把图框实际宽度带给 `/api/graph?w=`，按 40px 取整、夹在 700–4000，放进缓存键；不传时用默认的 1180。画布宽度在图框宽度的几个倍数里挑
  「高度 + 1.5 × 超出图框的宽度」最小的。
- 为什么：宽屏上直接排得更宽、少折行，而不是把 1180 宽的图放大；取整让窗口拖一点点不必重排，也不让每个像素占一份缓存。写死的档位在宽屏上大多比图框还窄、试不到。
- 放弃的方案：固定 1180 宽再缩放；写死的 1400 / 1640 / 1900 / 2200 档位。
- 在哪：`serve.py` 的 `do_GET`（`w`）；`layout.py` 的 `build`（挑宽度那一段）。

---

## 安全

### serve 只听本机，Host 头必须对，有副作用的 GET 要带自定义头
- 决定：serve 绑 127.0.0.1；Host 头必须是 `127.0.0.1:端口` 或 `localhost:端口`，否则 403；会起编辑器的 `GET /api/open` 必须带 `X-Codestrata: 1`；
  文件路径 realpath 后必须在仓库内，静态文件必须在 web/ 下；serve 不接受写（没有 PUT）。
- 为什么：防 DNS rebinding——别的域名解析到 127.0.0.1 时浏览器按同源发请求，能读源码、开编辑器，但 Host 还是那个域名。Host 检查挡不住普通的别的网页用
  `<img src=…/api/open>` 发简单 GET；自定义头跨源要先过 CORS 预检，serve 不回 CORS，所以带头的请求一定出自自己的页面。其余 GET 只读，不必加。
- 放弃的方案：监听 0.0.0.0；只查 Host。
- 在哪：`serve.py` 的 `BaseHandler._host_ok`、`_from_page`、`HEADER`、`Handler._in_repo`、`asset`、`main`。

### 主菜单能执行命令，所以要口令 cookie + 自定义头 + Host 三道
- 决定：`codestrata app` 只听 127.0.0.1，查 Host；`/api/` 要口令 cookie（HttpOnly、SameSite=Strict，口令存在配置目录下 0600 的文件里，用启动时打印的 `/?t=` 链接设一次）
  和 `X-Codestrata` 头；扫描、录制、打开图只接受清单里的项目；Cookie 头手工拆，不用 `http.cookies`。
- 为什么：主菜单是整个 codestrata 里唯一能在本机执行任意命令的网络入口（录制表单的命令放在 trace 的 `--` 后面）。三道各挡一类来源：Host 挡 DNS rebinding；
  站点不分端口，127.0.0.1 上别的端口的页面也带得上 cookie，挡它们的是必带的头（跨源要预检，这里没有 do_OPTIONS）；本机别的进程、别的用户只有口令拦得住。
  HttpOnly：cookie 不分端口，别的本地服务的页面脚本不能读走口令。手工拆 Cookie：实测标准库解析器遇到一个它不认的别家 cookie（带引号的 JSON、有空格），后面的就全丢了，
  每个 `/api/` 都会 403。
- 放弃的方案：只靠 Host 检查；`http.cookies.SimpleCookie`。
- 在哪：`app.py` 的 `_guard`、`load_token`、`_cookie`、`App.token_ok`、`_registered`；测试 `test_app_http`、`test_cli_app`。

### 主菜单的图转发（`--proxy`）默认关
- 决定：默认「打开图」给图服务自己的地址 `http://127.0.0.1:<端口>/`；加 `--proxy` 才把图转发到主菜单端口下的 `/v/<端口>/`，而且只转给自己起的、还活着的图服务。
- 为什么：转发之后图页面和主菜单同源，少了一层隔离：图页面里要是有 XSS，就能调主菜单的接口。远程用时一条 SSH 隧道就够的便利，只在需要时换。
  只转自己起的端口：主菜单不能变成打到本机任意端口的跳板。
- 放弃的方案：默认转发（`27e4e80` 曾默认转发，`a40c95e` 改成可选）。
- 在哪：`app.py` 的 `App.proxy`、`_view`、`main`；`__main__.py` 的 `--proxy`。

### 密钥不存、不外露：环境只记白名单，网页上隐去
- 决定：run 只记 `--env` 写明的变量和白名单里的继承环境（CUDA_* / VLLM_* / HF_* / PATH…），名字按 `_` 分段像密钥的（TOKEN、KEY、SECRET、PASS、AUTH…）不记；
  网页上的复刻命令、case 命令、进程命令行里，像密钥的 `--env` 值、`--api-key X` 这类选项的值、URL 里的账号密码写成 `<已隐去>`，`runs show` 给完整的。
- 为什么：防止把 token 存进 run；这些东西会显示在网页上（录屏、截图时露出去）。按段匹配：`TOKENIZERS_PARALLELISM` 不是密钥。
- 放弃的方案：抓整份环境；用子串匹配密钥名。
- 在哪：`runs.py` 的 `inherited_env`、`_ENV_SECRET`、`_secret_flag`、`_redact_argv`、`_scrub`、`load`。

---

## 工程

### 读代码的功能冻结，只修 bug
- 决定：代码窗口、Ctrl+点击跳转和引用列表的界面、文件内查找、搜索栏、浏览器端高亮、主菜单 app 属于冻结区，只修 bug 不加功能；读代码优先「跳到你的编辑器」。
  核心（graph：scan × trace、名字和调用的解析（2026-09-30 起，含类型推断）、录制、叠加、时间轴）继续做深。
  例外（2026-09-30）：xref 的名字解析和 graph 的 scan 记录同一遍产出；代码窗口在「代码里看不出调到谁」的那一行行尾标出这次运行调到了谁、
  点了跳过去——这是 scan-trace alignment 的结果，属于核心。
- 为什么：定位是「仓库的运行路径工具」，真正别人没有的是运行时叠加；跳转定义这类事 pyright / jedi 和用户手边的编辑器做得更好，自己再造一个是往「浏览器里的 IDE」横向扩张。
- 放弃的方案：继续把 codestrata 做成通用的读代码工具。
- 在哪：`web/viewer.js`、`web/findbar.js`、`web/search.js`、`web/hl.js`、`app.py`；例外在 `ui/source.py` 的 `runtime_lines`、`web/viewer.js` 的 `.rtj`。

### 不做模块讲解层，重心是运行路径怎么走
- 决定：不提供「给每个模块写讲解」的功能（原来的解读层：tasks / pack / note / check、`notes/` 目录、页面右栏的解读和节点上的徽标都去掉）。
  serve 只读，不接受写。
- 为什么：使用方式是拿录下来的运行路径（这次调用按什么顺序走过哪些模块）去问 agent，而不是读逐模块的讲解；重点是运行路径怎么走。实际代价也大：本仓库 19 份讲解钉了 1907 处行号引用，一次拆分要搬 401 处，
  每轮刷新要花几十万 token，写出来的东西人读不下去。
- 放弃的方案：保留功能、只给本仓库的讲解瘦身；引用改锚定到函数上。
- 在哪：原来的实现在 git 历史里（`codestrata/notes.py`，删于 2026-09-30）。

### 不做两次运行的对比（暂时）
- 决定：去掉对比功能（`cmp=`、`graph --compare`、图上 A 橙 / B 紫 / 两边前景色、边详情里 B 的次数）。一次只叠一个 run；
  换 run 照常（运行菜单）。
- 为什么：现在的重心是看清一次运行的路径怎么走；留着就要维护一套 A / B 双份的汇总和界面。
  另外它本身也答不出「两次差在哪」：差别在模块内部，界面只到模块和跨模块的边。
- 放弃的方案：保留冻结；做成逐函数的差异清单。以后要做，按「两份逐函数计数做差」重新设计，而不是恢复原来的三种颜色。
- 在哪：原来的实现在 git 历史里（删于 2026-09-30）。

### 不做分享（暂时）
- 决定：去掉导出和分享——`codestrata graph` 整个命令：单文件 HTML、一个页面带多个 run、`--public` 公开页、`--link github` 静态站、`--fragment`。看图只用 `serve`（或从主菜单打开）。
- 为什么：现在用不上，留着在污染代码库：前端有三种数据源，`payload` 里有一套导出和公开化，几百行代码和测试只为导出存在；
  改核心（以函数调用为中心重整）时，每一步都还要照顾导出的数据格式。
- 放弃的方案：保留、冻结；放宽单文件的体积预算。以后要不要、怎么重做再定。
- 在哪：原来的实现在 git 历史里（`render.py`、`site.py`、`payload.py` 的 `export_payload` / `publicize`，删于 2026-09-30）。

### 依赖按需引入，不以零依赖为目标；数据存文件
- 决定：成熟的现成工具做得更好的，就用它（跳转、排版、原生代码的解析和录制都在此列），不为了少一个依赖自己实现。
  现在运行时依赖仍为空（Pygments 可选，只用于服务端高亮），这是现状，不是约束。新依赖优先选 `pip` 装得上、有预编译 wheel 的；
  要系统工具的（clang、Nsight Systems）装不上时明确说缺什么、这部分不出，不影响别的部分。
  数据都是 JSON / gzip / tar 文件，不用数据库；没有 case 定义文件。
- 为什么：早期设计稿把「只用 stdlib」写成了原则，这不是需求；照着它自己写了名字解析（`xref.py`）、分层排版（`layout.py`）这类有现成工具的东西，
  维护成本高，也分散了花在核心（运行时叠加）上的精力。`pip install` 之后一条命令出图仍然要紧，所以优先选好装的依赖。
  存文件：run 目录能直接拷走、原始数据人能读；对照 OpenGrok（要 Java + Tomcat + universal-ctags，为读代码架一套太重）。
- 放弃的方案：为了零依赖自己实现有现成工具的东西；OpenGrok / Sourcetrail 这类整套的读代码工具（Sourcetrail 已归档，活着的 fork 禁用了 Python 索引）；sqlite；cases.toml。
- 在哪：`pyproject.toml`（`dependencies`、`highlight` 可选依赖）。

### 模块边界：录和存分开，seq 和 events 只隔一个文件格式
- 决定：`trace` 不 import `runs`：`trace.driver.run` 只接收一个 parts 目录和一个 `after` 回调，收尾（打包、写 run.json）在 `run` 的 try/finally 里跑。`seq` 不 import `events`
  也不 import `runs`，只读 events/spans/ 的文件，run 目录由 `serve` 经 `runs.resolve` 找好交给它。新功能进新模块。
- 为什么：driver 的信号处理器要一直装到收尾做完，收尾中途按 Ctrl+C 才不会留下半截的 run——所以用回调而不是返回后再收尾。写 run、删 run 的代码全在 `runs` 里，
  审一个文件就能确认谁会删原始数据。`events` 保持是叶子、测试能直接调 `seq.edge_times`；代价是 spans/ 的格式两边各认一份（`test_seq_edge_times` 兜底）。
  原来的 `payload.py` 是 god module，2026-09-30 拆成了 `align.py`（两边的比较）和 `ui/` 下几个按页面区域分的模块；原来的 `trace.py` 已按运行环境拆成 hook / driver / analysis 三块。
- 放弃的方案：`driver.run` 返回后由调用方收尾。
- 在哪：`trace/driver.py` 的 `run`（`after`）；`runs.py` 的 `finalize`；`seq.py` 的 import。

### 主菜单是另起的进程，按钮背后是 CLI 子进程
- 决定：`codestrata app` 不在自己进程里调 scan / trace / serve 的函数：扫描、录制是 `python -u -m codestrata scan|trace …` 子进程，每个打开的仓库一个
  `codestrata serve --home` 子进程；扫描成功后在原端口重启这个 serve。同一个仓库同时只跑一个任务。
- 为什么：trace 的 driver 要在主线程装信号处理器，而主菜单的请求都在工作线程里；页面上显示的、run 里记的、终端里敲的是同一条命令（只多一个 `-u`）。serve 的状态挂在
  `Handler` 类属性上、一个进程只服务一个仓库、index 只在启动时读一次，原样复用比改成多仓库省事，一个图服务崩了也不带倒主菜单。扫描会重写 index、录制要读 index 解析
  `--phase`，两者不能交错。
- 放弃的方案：把 serve 改成多仓库、能热加载 index；在主菜单进程里直接调函数。
- 在哪：`app.py` 的 `make_app`、`_restart_after_scan`、`_start`；`jobs.py`（`_cli`、`TraceSpec`）；`viewers.py`；`codestrata/__init__.py` 的 `self_command`。
