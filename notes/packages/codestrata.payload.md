---
written_by: claude-opus-5-5
target: codestrata.payload
kind: package
code_sha: 975fa968a334e0f6
status: draft
refs: payload.py:1@eae6f6c4,serve.py:330@7bd2304b,payload.py:779@977b39aa,codestrata/__main__.py:159@36d9c30d,site.py:242@79b352b0,payload.py:46@792c7b2a,payload.py:132@cdbac5e5,payload.py:442@c36f173a,payload.py:357@dfc3e98b,payload.py:419@ef38d1f0,payload.py:582@939c9802,payload.py:69@7c277874,payload.py:120@b455e869,payload.py:731@0e2e9052,runs.py:595@5028c052,serve.py:426@eae1c1a1,runs.py:790@84b0e0e7,runs.py:771@993ec58b,runs.py:781@d6141a36,notes.py:316@a5ce0618,payload.py:47@17be1534,runs.py:730@b2d6757f,runs.py:764@47fcd1f8,payload.py:37@d6513e46,runs.py:719@47887e94,payload.py:105@a74dafbd,payload.py:219@bf6ecf7f,payload.py:109@76ea6181,payload.py:227@b41f714c,payload.py:65@1d41b21d,serve.py:168@4317bbc0,payload.py:211@785b8360,payload.py:220@49dec5e4,payload.py:223@c9105fa6,serve.py:277@12773134,payload.py:140@213a94e3,payload.py:153@90fe571f,payload.py:396@b3119dbf,payload.py:269@f31c8ab5,payload.py:311@342b83d6,payload.py:431@73024331,payload.py:544@e6dabe0a,payload.py:561@65f7556a,payload.py:602@539a480b,payload.py:617@5e093a3b,payload.py:628@08d14eee,payload.py:678@8b3d5b0c,payload.py:646@70082336,payload.py:705@5b368878,payload.py:856@e58ee8b5,payload.py:958@61e30aeb,site.py:209@c798de4b,payload.py:910@88770b5b,payload.py:923@b590f093,payload.py:523@5f6ef7e4,site.py:179@c6be9769,codestrata/web/ds.js:301@4e548979,codestrata/web/ds.js:258@171b5f08,payload.py:60@ceb574c0,site.py:241@027e9882,site.py:243@28927561,tests/test_runs.py:758@e67ac2fe,site.py:245@e83c51cf,site.py:267@54de2e6b,site.py:311@73ece744,codestrata/render.py:29@71b78c76,payload.py:886@6528ed04,payload.py:124@7613e6ca,codestrata/web/ds.js:42@8df51fd0,payload.py:128@af1a7a55,codestrata/web/app.js:219@eeef2e3d,codestrata/web/app.js:229@3c7898c7,codestrata/web/app.js:590@0bcbb50e,codestrata/web/app.js:263@f174f742,codestrata/web/app.js:277@109b10a0,codestrata/__main__.py:330@82d17a7b,tests/test_runs.py:413@9143ab23,codestrata/web/app.js:241@a8e65004,runs.py:950@f71b3f7a,runs.py:955@c46549dd,runs.py:916@5782c208,runs.py:794@ea09f063,codestrata/__main__.py:454@c6d6ff8c,codestrata/__main__.py:470@0d32b1b5,codestrata/__main__.py:510@9b7d29d5,codestrata/web/seq.js:174@04b2edcd,seq.py:431@7488f4bc,runs.py:1026@ab3c0b1b,codestrata/web/app.js:743@39ad17db,codestrata/web/app.js:400@ffb38374,codestrata/web/app.js:772@f5e4ec59,codestrata/web/app.js:580@4e795724,payload.py:868@72251dcf,payload.py:876@a518b91f,payload.py:918@9ea6c4cf,codestrata/__main__.py:130@df83b690,payload.py:835@539d1041,payload.py:745@ac463ea8,payload.py:806@a8be4925,payload.py:803@b8be6b8f,payload.py:816@532605b4,payload.py:826@35ceec2a,payload.py:824@aad695df,payload.py:841@db36baee,payload.py:777@c4bde0bb,payload.py:795@00b5cce8,payload.py:797@9f77ec59,payload.py:800@c29c32ce,payload.py:728@9316d10d,payload.py:753@22f940c3,payload.py:749@555f82c9,payload.py:762@cf51b456,payload.py:767@82c4f33c,payload.py:775@4ac43a50,payload.py:774@c3e6312a,payload.py:845@ce965866,payload.py:847@072b54b5,payload.py:850@7a3701fa,payload.py:846@00fd06f5,codestrata/web/ds.js:27@cd3f15dc,codestrata/web/app.js:226@eb77056f,site.py:300@7c0c2fb3,site.py:302@cddaec19,site.py:293@6a26bc0d,tests/test_runs.py:810@018eded3,site.py:340@9f5b5f67,tests/test_runs.py:669@b398dc91,tests/test_runs.py:683@fc0a3f3c,tests/test_runs.py:690@aef4f847,tests/test_runs.py:693@9a4728e8,tests/test_runs.py:701@876e381d,tests/test_runs.py:713@e6c3c673,tests/test_runs.py:714@f17c6612,tests/test_runs.py:716@af39f28c,codestrata/web/ds.js:167@9c28fed8,codestrata/web/ds.js:74@3000c551,codestrata/web/ds.js:75@269cf616,codestrata/web/ds.js:150@706115dd,serve.py:282@afccde76,serve.py:294@2b2b2aed
---

## 是什么
把各路数据组装成前端要的形状：某个**切面**上的图（`cut` 汇总 + `layout` 排版）、runtime 叠加（某一次 run，由 `runs` 映射到当前 index；M7 起还能再叠一个 run 做对比）、源码（`highlight`）、解读（`notes`）、点开一条边时它到底承载了什么；还有右边搜索栏要的名字索引，和全文窗口 Ctrl+点击要的交叉引用（`xref`）。M8.1 起还有一道只给公开导出用的后处理 `publicize`：页面要放到公网上时，把导出里本机的主目录和工具目录抹掉。M8.2 起 `export_payload` 多了 `code=False`：给「源码从 GitHub 取」的静态站点（`site.export_site`）一份除源码以外全部照旧的导出数据。

## 为什么这样切
serve（live）和导出要给前端**完全相同**的数据，否则几种模式会慢慢漂移（payload.py:1）。于是组装逻辑单独成一层，各方都只调它：serve 按请求调单个函数，单文件导出一次性调 `export_payload` 把所有东西内嵌进去；M8.2 的静态站点（`graph --link github --out 目录`）也调同一个 `export_payload`，只关掉源码那一块（`code=False`，见下面「源码不内嵌的导出」），每个文件的跳转、引用倒排这些直接借这里的 `xref_for`、`load_xref`、`_inverted`。对比也守着这条：serve 的边详情接口和两种导出都一律调 `edge_compare`（没有第二个 run 时它就是 `edge_detail`，serve.py:330、payload.py:779），不各写一套「带不带 B」的分支。唯一有意的不同是 `graph --public`：它在导出的成品上再过一遍 `publicize`（单文件在 codestrata/__main__.py:159，站点在 site.py:242），serve 和不带 --public 的导出都不经过它——本机自己看，路径和复刻命令要原样的才能用（见下面「公开导出」）。

它在图上处于中间层，正因为它是汇合点：依赖 `cut`、`highlight`、`layout`、`notes`、`runs`、`xref` 六个下层模块，被 `serve`、`__main__` 和 `site` 依赖。切面、布局、高亮、引用倒排都委托给下层；run 的存储、解析、映射和过期判断整个交给 `runs`（M1 之前这些散在这里的 `load_hot` 里，直接读 `trace` 的产物）。它自己只做拼接、**按切面汇总**、两类数据的**交叉**、两个 run 的**对齐**，外加 serve 进程里几份按修改时间失效的缓存。

## 读法
1. `load_index` / `load_hot` —— 读 scan 的两个 JSON；把一个 run 叠到当前 index 上。`load_hot` 现在只是 `runs.load` 的薄包装（payload.py:46），见下面「关键算法」第一节
2. `graph_payload`（payload.py:132）—— `/api/graph` 的全部内容。`open_` 是切面（不给就是 scan 算出的默认切面），`width` 是浏览器里图框的宽度，`hot_b` / `hot_meta_b` 是对比的另一个 run
3. `edge_detail`（payload.py:442）和它底下的 `_pair_detail`（payload.py:357）—— 点开箭头看到的东西；对比时外面再套一层 `edge_compare`（payload.py:419）
4. `file_outline` / `file_view` / `symbol_source` —— 源码；后两个带上 `xref_for` 给的可点击 token
5. `search_index` / `reveal` —— 搜索栏：一次给全的名字索引，和「让某个模块在图上露出来要展开哪些目录」
6. `load_xref` 到 `refs`（payload.py:582 起）—— 交叉引用：缓存、过期判断、谁引用了这个定义
7. `export_payload` —— 把上面全部打包，给单文件导出；`others` / `compare` 是 M7 的多 run 导出，`code=False` 是 M8.2 给静态站点的（不带源码）
8. `_hot_on_cut`（payload.py:69）/ `_meta_brief`（payload.py:120）—— 对比和多 run 导出共用的两个小工具：一个 run 按切面汇总（连同每条边上有几次是动态分派），一个 run 的 meta 挑出页面要读的键
9. `publicize`（payload.py:731）—— 只给 `graph --public`：在 `export_payload` 的结果上抹掉主目录、收起 PATH 这类目录列表，最后整份再查一遍（站点导出还拿它处理随页面带上的本地源码）

## 关键算法
### `load_hot`：一个名字、一行提示，别的都在 `runs`
以前每个 case 只有一份 `trace-<case>.json`，同名重录就覆盖，`load_hot` 自己读文件、切阶段、比过期、合并进程、找脚本。M1 起每次 trace 都是 `.codestrata/runs/` 下一个新目录（录一次、永久复用，见 `docs/design/runs.md` 第 1、3 节），「REF 指的是哪个 run、它的计数和清单怎么读、哪些文件录制后改过」都成了 `runs` 的事，所以这里整个换成一句 `runs.load`（payload.py:46）：
- **ref 语法**（`runs.resolve`，runs.py:595）：完整 run id，或 case 名（取它最新一次 ok 的，没有就退到最新的 partial 并提示），后面可以加 `@阶段`；不写阶段就是各阶段相加——老的 `--hot 名字@阶段` 写法原样能用。第一次解析时 `catalog` 还会顺带把老的 `trace-<case>.json` 迁进 runs/，老 case 名不必手动搬
- **名字和调用方式不变**（第三个参数由 case 改叫 ref，调用方都按位置传）：`__main__` 的 graph / tasks / pack、`tests/test_runs.py` 照旧调 `load_hot`（graph 给了几个 --hot 就调几次）。serve 只在启动时调一次，用来当场校验 `--hot` 写没写错、并把它解析成页面默认选中的完整 id（serve.py:426）；之后每个请求自带 `run=`（对比时还有 cmp=），由 `serve.Handler._hot` 直接调 `runs.resolve` / `runs.load`，按 run 和计数文件的 mtime 缓存——所以页面上换 run、换阶段、换对比对象都不用重启（M4 / M7）。`runs.load` 返回的 meta 保留老的全部键（`procs`、`script`、`stale_files`、`phases`……，`web/app.js` 的 hot 横幅和帮助认它们），再加上 `run_id`、`status`、`problems`、`file_state`、`git`、`tags` 等；M8 起还有复刻用的 `rerun` / `rerun_exact` / `rerun_redacted` / `rerun_env` / `env_inherited` 和阶段怎么切的 `phase_at` / `phase_log`（见下面「一个文件里带几个 run」）。其中会显示在网页上的命令行——复刻命令、case 命令 `cmd`、`procs` 里各进程的 argv——在 `runs.load` 里就已经是隐去过的版本（runs.py:790、runs.py:771、runs.py:781），这一层拿到什么就传什么。hot 本身还带上 `run`，`notes.prompt_pack` 的 runtime 那一行据此写明数字来自哪个 run（notes.py:316）
- **打印用了哪个 run**（payload.py:47）：case 名解析到的是「最新一次录完的」，每录一次新的，同一个 `--hot 名字` 指的 run 就变了——不打印出来，用户分不清图上的数字来自哪一次（设计 4.5：每条命令都打印解析到的完整 id）。打到 stderr，因为 `pack` 的 stdout 是整个输入包，常被重定向给 agent。serve 按请求换 run 不经过这里、不打印：页面的 hot 横幅直接显示 meta 里的 `run_id`
- 原先也在这里的两件事一并搬走了。进程按命令合并成了 `runs.procs_grouped`（runs.py:730），「argv 被截断」改读每个进程记下的 `argv_cut`（新 run 由 hook 在 import 时记，迁移来的老 trace 在迁移时按「没有 ppid」补上），不再在读的时候现猜，另外带上被 setproctitle 改过的 `title`。case 脚本改为优先读 run 目录 `files/` 里录制时存下的副本（runs.py:764），老 run 没存才读现在的文件、标 `saved` 为假

### `load_index` 的 `file_sha`：故意留 None
scan 现在往 symbols.json 里写每个 .py 文件的内容哈希 `file_sha`，和录制时记下的哈希同一种。`load_index` 读它时**不给默认值**（payload.py:37）：老的 symbols.json 没有这个键，得到的是 None 而不是空字典。`runs.file_state` 靠这一点分辨「老 index」（`now is not None` 不成立，runs.py:719，退回拿工作区比，即 `trace.stale_files` 的老办法）和「新 index」（直接和 index 比——叠加用的行号来自 index，这才是该比的对象）。若默认成空字典，老 index 上所有文件都会被当成没改过，过期提示悄悄消失。

### 一切都按切面汇总（`graph_payload`）
scan 的数据全在单元（文件）之间；图上的节点是切面上的目录 / 本层文件 / 单个文件。`graph_payload` 先让 `cut.view` 给出节点和节点间的边，把它包成一个和老格式同形的「合成 index」交给 `layout.build`——布局模块完全不知道切面的存在。然后同一个 `node_of` 映射把其余数据也挪到节点上：
- 节点的文件、顶层符号、文档（`pkgFiles` / `pkgSyms` / `pkgDocs`）。C++ 文件和 README 挂在目录上，用 `cut.dir_node` 找到切面上包含那个目录的节点
- 边的种类 `edgeKinds`：用到对方几个**不同的**符号（多个单元对指向同一个符号只算一次，`_edge_uses_on_cut`，payload.py:105）、几个 import 没被引用，前端据此画灰实线 / 灰虚线
- hot 叠加：节点命中数、节点间调用数都从单元级累加，两端落在同一个节点里的调用不算边。这一步抽成了 `_hot_on_cut`（payload.py:69）：对比时 B、多 run 导出时每个别的 run 都要按同一个切面再汇总一遍，只写一处，几个 run 的数字才是同一种口径。`runtimeOnlyEdges` 是静态 import 图里根本没有、但 runtime 走过的节点间调用（payload.py:219）——不单独画出来，图就会说谎。同一个道理还有一半：两端之间碰巧有别的 import（比如只引用了一个常量），跑到的调用却全是动态分派（经由 self.model、注册表调到的类），这条边收起时如果按「有静态边」画成实线，展开之后实线就变成没跑到的灰边加一条虚线，看上去箭头「消失」了（vllm-omni 的 worker → models 就是这样）。所以 `_hot_on_cut` 还按边详情同一个口径——被调符号收到类之后不在这条切面边的静态引用里——算出动态分派的次数（`hot.dyn`，对比时 `cmp.dyn`），调用全是动态分派的静态边列进 `dynOnlyEdges`（`_dyn_only`，payload.py:109；对比时两个 run 都得是这样），前端把它画成和 runtimeOnlyEdges 一样的橙虚线。这个数必须按切面算、不能按单元对算完再加：同一个符号可能一对单元里静态引用、另一对里 runtime 调到，合成一条边之后算「确认」
- 每个节点带上 `kind`、`expandable`、`parent`、`collapsible`、`fanout`、`units`（payload.py:227），前端据此画「＋」和「收起到上一级」

返回里还有 `open` / `defaultOpen` / `autoSplit`，前端用它们判断当前是不是默认切面；`hotMeta` 原样透传 `runs.load` 给的 meta（CLI 经 `load_hot`，serve 经 `serve.Handler._hot`）；对比时另有 `cmp` 块，见下面「对比两个 run」。

切面先过一道 `_norm_open`（payload.py:65）：没给就换成 scan 的默认切面，给了就只留 `cut.is_node` 认得的名字（重新 scan 之后 URL 里残留的旧目录名被悄悄丢掉，而不是传给下层）。M5 起 serve 的时序图接口（`serve.Handler._seq`）也调它（serve.py:168），所以时序图的生命线和模块图的节点落在同一个切面上，两张图切换时选中的东西对得上。

### 对比两个 run（`graph_payload` 的 `hot_b`）
M7：同一个切面上叠 A、B 两个 run（比如同一份代码上两个模型的 serving 阶段），前端按「只有 A / 只有 B / 两边都有」画三种颜色。
- **A、B 汇总方式完全一样**：各调一次 `_hot_on_cut`，用的是同一个 `node_of`。对比看的是差异，两边若各有一套汇总，哪天一边的规则改了（比如同节点内的调用算不算边），图上就会冒出并不存在的差异。测试 test_compare_and_multi_export 逐个核对：`cmp` 里每个节点的 [A, B] 等于分别单独叠 A、单独叠 B 时的次数
- **多一个 `cmp` 块，A 那一份不动**（payload.py:211）：`ref_b`（B 的「run id@阶段」，前端把它写进地址——case 名会随重录指到别的 run）、`meta_b`（`_meta_brief`，横幅上写 B 是哪个 case、哪一次、录没录事件）、`nodes` {节点: [A, B]}、`edges` {"x|y": [A, B]}，只收至少一边不为 0 的。`hot` / `hotMeta` 仍然只是 A：不认识对比的地方（面板的其余部分、单 run 的逻辑）看到的形状和以前一样，对比只是在上面加一层
- **两处取并集**：`runtimeOnlyEdges` 取 A∪B，权重用两边的较大值（payload.py:220，和图上「粗细 ∝ log(较大值)」一致），不然只有 B 走过的动态分派边在图上就没了；hot 图（「只看跑到的」）按两边任一跑到的节点排版（payload.py:223），只有 B 跑到的节点才画得出来。总图不为对比重新排版：开关对比只换颜色，节点不挪位置
- 只有在有 A（`hot`）时才看 `hot_b`：没有 A 就谈不上对比。B 找不到、或者就是 A 自己（同一个 run 同一个阶段），由 serve 挡在前面——只叠 A、另回一句 `cmpError`，不让整张图 404；这里不判断

### 按图框的宽度排版
`width` 原样交给 `layout.build`，总图和 hot 图都用它：宽屏上图铺满、一行多放几个节点、少折行，而不是把按 1180 排好的图整体放大。serve 把浏览器报来的宽度按 40px 取整、夹在 700–4000 之间，并把它放进缓存键（serve.py:277）：窗口拖一点点不必重排，不同宽度的排版也不会混用。

### 框：谁套着谁
展开着的目录在图上画成一个框。一个节点直接被哪个框套着，就是 `cut.parent_of` 给出的那个展开着的目录（或展开着的本层文件节点）；框的外层框再往上问 `parent_of`，一直到根（payload.py:140 起）。只有一个根时不画根的框——它就是整张图；多个根时每个根一个框，也能收起。`collapsible` 就是「有没有套着它的框」：顶层节点没有，详情面板也就不给「收起到上一级」。

每个框还记下一共框着几个画得出来的节点（payload.py:153）：hot 视图只给跑到的节点排版，框头要写「画出来的 / 一共」，一共有几个只有这里知道。

### 边的五类归并（`_pair_detail`）
两个维度交叉：静态上有没有引用（`scan` 的 `edge_uses` / `edge_dead`），runtime 有没有调用（`trace.to_package_graph` 算出的 `edge_calls`）。
- **confirmed**：引用了，也调到了
- **static**：引用了，这次没走到（或者没有 runtime 数据）
- **dynamic**：调到了，但代码里没有静态引用——插件、`importlib`、注册表
- **import_only**：导入了但从没引用，原因沿用 scan 的分类；有 runtime 时，副作用 import 还会标出对方模块的顶层这次执行了没有

对齐时有一个粒度差：静态上引用的往往是**类**（`Handler(...)`），runtime 调到的是**方法**（`Handler.do_GET`）。`_top` 把 `模块:类.方法` 收到 `模块:类` 再对齐，于是一个类下面能列出「哪个方法被谁调了几次」。排序是 confirmed → dynamic → static（payload.py:396）：真调用和静态盲区最值得先看。

动态分派那一组「代码里没有指向它的引用」，光这么说用户接不下去，所以每一项再带两条线索。**调用处**（`_add_call_sites`，payload.py:269）：在调用方函数体的范围里按名字找 `名字(` 或 `'名字'`，于是 worker → minicpmo_4_5 的每个方法下面直接列出 `self.model.compute_logits(…)` 那一行——代码里有调用，只是 self.model 的类型要到运行时才定；找过但没找到（`sites` 是空列表）就照实说中间隔了 `__call__`、回调或仓库外的代码。**按名字登记**（`_add_wiring`，payload.py:311）：scan 收下的 `name_refs` 里用字符串写着这个类的地方（注册表、配置、插件表），带模块的类路径只认模块对得上的，只写类名的在仓库有同名类时会注明可能指别的。两条线索都只按名字匹配、不做类型推断，只读 scan 扫过的文件。

### 节点间的边 = 底下所有单元对的合并（`edge_detail`）
两端都是单个文件时直接走 `_pair_detail`；否则取两端底下所有有依赖（静态的或 runtime 的）单元对，逐对算完再按符号合并。状态要**合并完再定**：同一个符号可能在一对里是静态引用、在另一对里被 runtime 调到，分开看是 static + dynamic，合起来才是 confirmed。

### 对比时的边详情（`edge_compare`）
没有照设计 §6.3 最初写的那样给 `_pair_detail` / `edge_detail` 加一个 `hot_b` 参数，而是用 A、B 各算一遍 `edge_detail`，再按符号合（payload.py:419）：静态部分两边本来就一样，上面那套「合并完再定状态」的规则只在一处，不必让每一层都背着两份 runtime。合出来的是 **A 的明细**，每项多 `calls_b` / `runtime_b`（B 调了几次、谁调的）；状态、`counts` 里的 confirmed / dynamic / static / `calls` 仍然只说 A，`counts` 另加 B 的总数 `calls_b`，外加 `has_runtime_b`，面板据此在标题下写「对比的 run：m 次」，每项写「A n / B m」。

只有 B 调到、A 的明细里没有的符号补在最后，状态记 `only_b`、`calls` 记 0、条数单独记在 `counts` 的 `only_b` 里（payload.py:431）。不归进 dynamic：dynamic 的意思是「这次（A）调到了、代码里却没有静态引用」，归进去面板就会在「动态分派」里说成 A 调到了它，A 的 dynamic 条数和 `calls` 也会被 B 撑大。能落到这一组的只会是 B 那边的 dynamic——有静态引用的符号两遍都会列出来、已经挂上了 `calls_b`——所以 B 的调用一次都不会漏：测试核对各项 `calls_b` 之和等于 B 单独算的总数。

### 源码先整文件高亮再切片
`symbol_source` 取一个符号的前 40 行，但高亮的是整个文件（payload.py:544）：从中间切开再高亮，跨行字符串会被着错色。高亮结果有缓存，所以代价只在第一次。片段的 xref 只取这几行的 token。

### 搜索索引要紧凑（`search_index`）
搜索全在前端做（`web/search.js`），每敲一个字不来回请求，导出版也能用同一套——所以索引一次给全：`mods`（目录树上每个目录、每个单元，带文件数）、`files`（Python 文件和包里的 C++ / CUDA 文件）、和 `files` 对齐的 `units`、`syms`。符号有几万条，存完整键会让模块名重复两万多遍，所以每条只存「限定名、种类首字母、文件下标、行」，键由前端用「文件所属单元去掉 .__init__ + ":" + 限定名」拼回来（payload.py:561）。serve 只序列化一次、缓存住。

点中一个结果要先在图上露出那个模块：`reveal` 在**当前**切面上展开它的所有祖先、把它自己收起（`cut.open_for`），而不是跳回默认切面把用户展开的东西全丢掉。

### 交叉引用的缓存：整份换上去（`load_xref`）
xref.json 读一次、解析一次，缓存在模块级的 `_XREF`，键是（路径, 修改时间）：重新 scan 之后下一次请求自动换成新的。serve 是多线程的，所以换法是「整份建好再一次性赋给全局名」（payload.py:602）：快路径不加锁，先把 `_XREF` 读进局部变量再比键；要换时才拿 `_XREF_LOCK`，锁里再比一次（双重检查）。读的人拿到的要么整份旧的、要么整份新的，不会拿到一半。倒排表（目标 → 引用它的地方）只有 `refs` 要，所以不在加载时建，第一次用到时由 `_inverted` 在这份缓存自己的锁里调 `_xref.invert`。没有 xref.json 时返回 None，前端就不给 Ctrl+点击。

### 改过的文件宁可不给链接（`_stale`）
xref 的 token 是「行 + UTF-16 列」，文件在 scan 之后改过，行列号就对不上了：链接会落在别的字上、跳到不相干的定义。xref.json 记了每个文件构建时的 [字节数, mtime_ns]（`fp`），`_stale` 拿现在的 stat 比（payload.py:617）；老的 xref.json 没有指纹就照旧当没改过，文件没了算改过。`xref_for` 对改过的文件只回 `stale` 和空 token（payload.py:628），形状不变；平时回这个文件（或 lo..hi 行）的 token，外加这些 token **用到的**目标 {目标号: [目标, 定义位置]}，不带全表。

### 谁引用了这个定义（`refs`）
- 同一行的几处合成一条、记 ×N（`n`），种类取最强的：调用 > 普通引用 > import，排序也是调用在前（payload.py:678）。`counts` / `total` 仍按处数计，`lines` 是合并后的条数，最多列 `limit` 条
- 每条带那一行的原文，读的是**现在**的文件：`_line_text` 背后是按（路径, mtime_ns）缓存的 `_lines_of`（payload.py:646）——几百条引用常常落在同几个文件里，不必每条读一遍，文件一改键就变。所在文件 scan 后改过的条目照列、只标 `stale`（行号可能已经不对）——和全文窗口里整份不给链接不同，这里只提示
- 定义本身作为 `def` 放最上面：跳到某个引用之后，点它就回到定义。函数 / 类还带上这次 runtime 调了几次（`calls`）
- 「同名的 .xxx」（`maybe`，payload.py:705）：方法、类属性常常通过别的对象调用（engine.generate()），静态分析不知道接收者是什么类型，确认不了是不是它。xref 把这种解析不了的「表达式.名字」按名字存在 `attrs` 里；这里按名字列出、同一行合并、调用在前，标明没确认，并附上仓库里一共有几个同名成员（`same`）——只有它一个时基本就是它。同名成员超过 3 个的名字（get、to……）xref 压根不记（`ATTRS_MAX_SAME`），列出来一大半都不是它

### 导出有体积预算
`export_payload` 只导出默认切面，把整个导出控制在 14 MB（payload.py:856，单文件宿主上限 16 MB）：先把图、边详情、解读、符号片段、搜索索引、别的 run（`hotBy`）放进去，剩下的额度给全文。全文按「主 run 跑到过的 + 解读里引用过的」优先、再按体积从小到大挑；先用原始字节数估算，明显放不下的不去高亮——vllm-omni 上导出从 32 秒降到 10 秒。这道预算只管单文件：`code=False` 时全文一个都不内嵌，也就不用挑（见下一节）。

xref 的目标全导出共用一张表 `xrefTargets`：片段和文件只带 token，目标挪进共用表（`share`），前端取出时再补回（`web/ds.js`）。早先每个文件各带一份，同一个目标重复几百遍，占掉的额度够再内嵌一两百个文件。挑全文时一个文件的代价 = 它自己 + 它带来的**新**目标的字节数，放得下才把新目标并进表（payload.py:958）。

### 源码不内嵌的导出（`code=False`）
M8.2：单文件导出的体积上限来自单文件宿主（16 MB），vllm-omni 1600 多个文件只装得下两百多个；而扫的仓库基本都在 GitHub 上，按提交号钉住的地址内容不会变、又允许跨域取。`graph --link github --out 目录` 于是由 `site.export_site` 导出一个目录：页面在浏览器里按扫描时的提交号从 GitHub 取源码（jsDelivr，退到 raw），用 hl.js 自己高亮；codestrata 算出来的东西放在旁边的 data/ 下按需取。它调的仍是 `export_payload`，只多传 `code=False`（site.py:209）。
- **只少源码这一块**：符号片段那一轮循环直接跳过（payload.py:910），组装完图、边详情、解读、待办、输入包、搜索索引、`hotBy` 之后就返回，并去掉 `sources` 和共用表 `xrefTargets`（payload.py:923）；全文那一段（额度、按「跑到过 + 解读里引用过」排序、逐个高亮）整个不走，也就没有 `files` / `filesTruncated`。于是 `per_pkg`、`lines`、`total_budget` 在这个模式下都不起作用（site 照传 `per_pkg`，没有效果）。除此以外的形状和单文件一模一样：图、对比的 `cmp`、多 run 的 `hotBy`、每条边的 `edge_compare` 都是同一段代码算的，两种导出不会在「图上画了什么、边里有什么」上分叉
- **为什么不是 site 自己组装**：图、边详情、解读、多 run 这些正是这里十几个函数加上去重、`hotBy` 拼起来的，另写一份就是上面说的「几种模式慢慢漂移」。两种导出真正不同的只有源码怎么来，所以只在源码那两段加开关
- **不带的东西由谁补**：每个文件的大纲和跳转，站点用 `site._file_meta` 写进 data/f/<序号>.json——形状和 `file_view` 一样、只是没有 `lines`；它不调 `file_view`：后者要先把整个文件高亮一遍（payload.py:523），而这个模式下源码要到页面上取回之后才由 hl.js 高亮，服务端高亮出的 `lines` 用不上。跳转仍是这里的 `xref_for`（site.py:179），每个文件带自己用到的目标：按文件按需取，就不需要单文件为了省额度才有的全局共用表。符号片段由页面从取回的整个文件里切（codestrata/web/ds.js:301），顶层符号的文件和行号查的是 `graph_payload` 本来就内嵌的 `pkgSyms`（codestrata/web/ds.js:258；`_unit_syms` 每条带 f / l / b，payload.py:60），方法和嵌套函数再从 f/ 里的大纲找——所以站点上每个顶层符号都有片段（--public 时被扣下的本地文件除外），不像单文件只带每个包前 `per_pkg` 个
- **`edges` 和 `search` 留在返回值里**：站点要把它们写成 data/edges.json、data/search.json，但先让整份过了 `publicize` 才 pop 出来（site.py:241、site.py:243），所以它们和单文件里的一样受公开导出的规则管，不必在 site 里另抹一遍。测试 test_site_export 核对页面内嵌的 EMB 里没有 `files` / `sources` / `xrefTargets` / `edges` / `search`（tests/test_runs.py:758）
- **引用倒排也出自这里**：站点的 refs/<桶>.json 用 `load_xref` + `_inverted`（site.py:245、site.py:267），和 serve 的 `refs` 读的是同一张倒排；同一行合并、调用在前的规则由页面照 `refs` 再做一遍。`EMB.link`（提交号、文件表、桶数……）不是这里给的，是 site 在最后加上的（site.py:311）；`render.export` 看到它才多带一个 hl.js 的 `<script>`（codestrata/render.py:29）

### 一个文件里带几个 run（`others` / `compare`）
M7：graph --hot A --hot B … [--compare] 导出一个能在几个 run 之间切换的单文件。
- **主 run 全量，别的只带切面上的次数**：第一个 --hot 照旧嵌 `hot`、`hotMeta`、`graphHot` 和所有边的明细；其余的进 `hotBy`，键是「run id@阶段」，每个只带导出切面上的节点次数、节点间边次数、`unmapped`、它自己的 `runtimeOnlyEdges`（payload.py:886）和一份 meta。符号 / 文件级的计数和每条边的调用明细才是大头，每个 run 都带全，几个 run 就把全文的额度吃光了。`hotBy` 在算剩余额度之前放进去，占多少就从全文里扣多少
- **meta 挑页面要读的键**（`_meta_brief`，payload.py:124）：在导出里切到别的 run 时，web/ds.js 把这份 meta 当成 `hotMeta` 交给页面（codestrata/web/ds.js:42），横幅和帮助读的就是它。所以横幅要的安装包映射（`mapped_from` / `n_mapped` / `mapped_mismatch`）、`unmapped`、`stale_files`、`unmatched`，帮助里「这次跑了什么」要的 `cmd` / `procs` / `script`，还有 `file_state`，都得带上——少了它们，切过去时「运行的是安装包、有几个文件和仓库不一致」这类警告和命令、进程表会凭空消失，读者会以为那个 run 干干净净。这些都不大；和完整 meta 相比只少了 `migrated_from`，省体积靠的是上一条不带的 hot 明细（名字里的「brief」已经名不副实）。`cmp` 的 `meta_b` 用的也是它
- **M8：复刻信息和阶段来源也得带上**（payload.py:128）：新加的七个键都是「这次跑了什么」要读的。最上面的复刻块有 `rerun` 才画（codestrata/web/app.js:219），`rerun_exact` 为假时注明命令是按 run 里存的参数拼的，`rerun_redacted` 为真时注明隐去了什么（--env 和 --api-key 这类选项里像密钥的值、URL 里的账号密码，并说下面的 case 命令和进程表也一样）、完整的用 `runs show` 看（codestrata/web/app.js:229），`rerun_env` / `env_inherited` 是「连环境变量一起复制」和继承来的变量清单；run 选择器旁边的「复刻」按钮也只在 meta 有 `rerun` 时露出来（codestrata/web/app.js:590）。阶段表读 `phase_at`（每个 --phase 一条：名字、命令行上写的函数、解析出的 qualname、文件、行）和 `phase_log`（每条 [名字, t_us, 来源]，来源 start / hook / sh，codestrata/web/app.js:263），据此写每段从什么时刻开始、是第一次进入哪个函数切的还是 case 脚本写的、哪个 --phase 没切到；case 脚本切的阶段和某个 --phase 同名、而 `phase_log` 里这个名字没有 hook 那一条时，标「同名的 --phase 没起作用」（codestrata/web/app.js:277），和 `codestrata trace` 结束时打的提示是同一个条件（codestrata/__main__.py:330）。少了它们，导出里一切到别的 run，复刻命令、「复刻」按钮和阶段表就一起没了——导出正是拿去给别人看的，别人要的就是「这是怎么录出来的、怎么再录一次」。仍然都不大：`phase_log` 每切一次阶段一条，`env_inherited` 只是白名单里的变量。测试 test_rerun_command_reproduces 核对 brief 里的 `rerun` 和 `runs.load` 给的一样、`phase_at` / `env_inherited` 都在（tests/test_runs.py:413）
  - **隐去不在这里做**：`runs.load` 给的 meta 里，会显示在网页上的命令行都已经隐去过：`rerun` / `rerun_env` 是 `redact=True` 的（runs.py:790），帮助里的「case 命令」`cmd`（codestrata/web/app.js:241）和进程表里各进程的 `argv` 也都过了 `_redact_argv`（runs.py:771、runs.py:781）。它把 --env K=V 里名字像密钥的值、名字像密钥的选项的值（--api-key X、--hf-token=X：选项名去掉开头的 -、把 - 换成 _ 之后按同一套规则认，runs.py:950；这类选项后面紧跟着的若是 - 开头的参数，就当它是不带值的开关、不吃掉下一个，--no-auth --port 80 原样保留，代价是本身以 - 开头的密钥值不隐去）、所有参数里 URL 带的账号密码都写成 `<已隐去>`（runs.py:955）；名字按 `_` 分段认 TOKEN / KEY / SECRET / PASS 这类词，TOKENIZERS_PARALLELISM 不算（runs.py:916）。`env_inherited` 的值也已去掉 URL 里的账号密码（runs.py:794），名字像密钥的变量录制时就没记。serve 的 `hotMeta`、导出的主 run、`hotBy` 和 `meta_b` 都出自这同一份 meta，`_meta_brief` 只挑键不改值，所以网页和导出里帮助面板的复刻命令、case 命令和进程表都是隐去过的；CLI 的 `runs show` 打完整的（命令、进程、复刻命令都原样，codestrata/__main__.py:454、codestrata/__main__.py:470、codestrata/__main__.py:510），隐去的规则也只有 `runs` 那一处。serve 的时序图不走这份 meta（`seq` 直接读 run 目录的 detail.json），但用的是同一个函数：生命线上的进程名和悬停提示（codestrata/web/seq.js:174）用的 argv 在 `seq.build` 里先过了 `_redact_argv`（seq.py:431）——导出不带时序图，所以这只关 serve 的页面。老 run 没存原始命令、复刻命令是按参数拼出来的，拼出的 codestrata 那半截和 case 命令两段都过 `_redact_argv`（runs.py:1026），--api-key X 这类值在这种复刻命令里也看不到，和同一个 run 的 `cmd` 一致。隐去的是密钥，网页和导出一律做；主目录和 PATH 里本机装的工具是另一回事——本机看要原样的，只在 --public 时由这里的 `publicize` 处理（见下面「公开导出」）
  - **对比时 B 的也在，但页面还没读**：`cmp.meta_b` 同样带着这七个键，可页面现在只从 `meta_b` 读 case / phase / created / events，画对比横幅和对比按钮（codestrata/web/app.js:743、codestrata/web/app.js:400）；帮助里「这次跑了什么」和「复刻」按钮用的是 `hotMeta`（codestrata/web/app.js:772、codestrata/web/app.js:580），只说 A。要看 B 的复刻命令，得把 B 选成主 run（导出里 B 也在 `hotBy`，切过去就是它的）
- **去重**（payload.py:868）：同一个 run 可以写成 case 名，也可以写成完整 id，`__main__` 只能按字符串去重；解析成「run id@阶段」之后才知道是不是同一个，所以这里再去一次。和主 run 相同的也跳过：否则 `hotBy` 里会有一份主 run 的精简版，页面上选中主 run 时 ds.js 先查 `hotBy`，拿到的就是没有符号计数、没有边明细的那份（测试里「同一个 run 写两遍」那段）
- **--compare**：去重后剩下的第一个别的 run 当 B（payload.py:876），交给 `graph_payload` 得到 `cmp`；边详情一律走 `edge_compare`（payload.py:918），所以只有这一对带 `calls_b`。B 同时也在 `hotBy` 里：在页面上把 B 切成主视图时，它和其他别的 run 一样只有切面上的次数

### 公开导出（`publicize`）：主目录和本机工具目录不出门
M8.1：用户要把导出的页面放到 GitHub Pages 上。导出里到处是本机的绝对路径——复刻命令的 `cd <目录>`、case 命令、进程 argv、源码里写死的路径、解读正文——主目录里带着用户名；PATH 这类目录列表还顺带列出这台机器装了哪些工具（~/.kimi/bin、/opt/某某/bin）。`graph --public` 在 `export_payload` 之后、写 HTML 之前调 `publicize`（codestrata/__main__.py:159），传入主目录和要保留的目录 keep：仓库本身，加上每个 --hot 的 run 录制时所在的目录（`invocation.cwd`，老 run 退到 run 的 `cwd`，codestrata/__main__.py:130）——venv 往往就在那下面，留着读者才知道用的是哪个环境。

**为什么在这一层、而且是事后整份过一遍**：它得认得 payload 的形状（run 元数据在哪几个键下、源码条目里 xref 的列号），所以在 payload 而不在 render；而组装函数有十几个、以后还会加字段，在每个里面各自抹，新加的字段就会漏。在成品上走一遍所有字符串，再用最后一道检查兜住，漏不出去。不改传入的 pl：每一层都建新的 dict / list（测试拿同一个 pl 连调两次）。规则：
- **主目录 → `~`，所有字符串**（`fix`，payload.py:835）：路径、命令、argv、解读正文、源码、dict 的键都算。正则末尾是 `(?![\w-]|\.[\w-])`（payload.py:745）：/home/yc.bak、/home/yca 是别的名字，不换；句末的「/home/yc.」换。主目录是空或 / 时不换（源码行也不挪、没有最后那道检查），下面的目录列表照样收
- **源码行换了，同一行的 Ctrl+点击跟着挪**（`code`，payload.py:806）：xref.toks 每条是 [行, 起列, 止列, …]，列是原文的 UTF-16 下标（前端 JS 字符串的下标，`u16`，payload.py:803）。高亮过的行是 HTML，先去掉标签、反转义还原出原文，再找每处主目录的（UTF-16 位置, 长度）（payload.py:816）；这一行上排在它后面的 token 左移「长度 − 1」（换成的 ~ 只占 1，payload.py:826），跨着主目录的 token 直接丢掉（payload.py:824）——那个名字在新文本里已经不存在了。不挪的话，这一行后面的链接全错位、落到别的字上，和上面「改过的文件宁可不给链接」是同一种毛病。只有带 xref 的 lines 条目（files、sources）走这条（payload.py:841），别的照 `fix`
- **run 元数据里的目录列表只留项目的**（`meta_fix`，payload.py:777）：作用在 hotMeta、`hotBy` 各自的 meta、`cmp` 的 `meta_b` 三处（payload.py:795、payload.py:797、payload.py:800）。PATH / LD_LIBRARY_PATH / PYTHONPATH（payload.py:728）的值按冒号切开，在 keep 下面的段留着，其余连续几段合成一个 …（`plist`，payload.py:753）——剩下的只是本机装了什么，和复刻这个 run 无关。keep 里空的、/、主目录本身和它的上级先剔掉（payload.py:749）：空串和 / 留着的话整条 PATH 都算「在 keep 下面」、原样留下；run 若是直接在主目录里录的，主目录（或它的上级）留着的话 ~/.local/bin、~/.cargo/bin 这些本机工具目录也全都留下
  - `cmd`、各进程 `argv` 逐个参数收（`tok`，payload.py:762）：认整个参数是 PATH=… 或 --env=PATH=… 的；--env PATH=… 分开写时后一个参数本身就是 PATH=…。`env_inherited` 只收这三个键
  - `rerun` / `rerun_env` 是 `rerun_command` 拼好的一整条 shell 命令（`cmd_str`，payload.py:767）：先 shlex 切成参数、逐个收、再用 `runs._q` 重新加引号拼回去，`&&` 原样（payload.py:775）。带空格的值被引号包着（'PATH=/opt/My Tools/bin:…'），直接对字符串做替换会切在引号中间、留下半截目录；切不开（引号不配对）就退成正则，把「PATH=」后面到下一个空白为止的一整截换成 …、一段也不按 keep 留（payload.py:774；值里带空格的，空白后面那截还在）。没有「PATH=」这类字样的命令不切、原样返回
  - **先收目录、后换 ~**：`meta_fix` 先把三处 meta 做完，`fix` 才走整份（payload.py:845）——keep 是绝对路径，比的时候值里的主目录还得是原样的
  - 不收的：case 脚本原文（`script` 的 text）、解读、源码里写的 PATH=… 都只换主目录——它们是内容，不是本机状态。别的环境变量（CUDA_*、HF_* 之类）的值也只换主目录
- **最后兜一道**（payload.py:847）：把整个结果 dump 成 JSON，用同一个正则再找一遍，还有就 `SystemExit`，带上它前 60、后 20 个字符好找来源（payload.py:850）；`cmd_graph` 于是不写出 HTML。`fix` 只走 dict / list / str，别的容器（比如 tuple）里的字符串它看不到，以后新加的形状也可能绕过去——宁可不写出，也不把主目录发到公网上
- `fix` 之后、最后那道检查之前设上 `public` 为真（payload.py:846）：web/ds.js 读进导出版的数据源（codestrata/web/ds.js:27），帮助里的复刻块（meta 有 `rerun` 时才有）据此注明「这是公开页：路径里的主目录写成了 ~，PATH 这类目录列表里项目以外的部分省略成了 …，所以命令不能原样执行；原样的在录制的机器上用 `codestrata runs <repo> show <run id>` 看」（codestrata/web/app.js:226）

**站点导出（`--link github --public`）用它两次**。一次照旧在整份 payload 上（site.py:242）。另一次给随页面带上的本地源码（GitHub 上那个提交里没有或内容不一样的文件，data/src/ 下）：这些是纯文本、跳转在另一个 f/ 文件里，不在 payload 的 files 里，但「源码行换了、同一行的 token 跟着挪」正是 `code` 已经会做的事，所以 site 把含主目录的文件包成一份假的 {"files": {"x": {lines, xref.toks}}} 交给 `publicize`，拿回换好的行和挪好的列（site.py:300、site.py:302）；先把每行 HTML 转义再给——`code` 按「去掉标签、反转义」算列号，纯文本里的 < 不能被当成标签（site.py:293）。测试 test_site_export_public_local_home 核对换过之后的文本上 compute 的列号对得上（tests/test_runs.py:810）。从 GitHub 取的文件不经过这里：它们本来就公开在那儿。site 最后还把写出去的每个文件再查一遍主目录（site.py:340），查到就删掉导出结果、不写出——f/ 里的大纲、跳转目标和 refs/、attrs/ 的倒排都没过 `publicize`，由这一道兜住。

测试两层。test_publicize_rules（tests/test_runs.py:669）直接调：带空格被引号包着的 PATH 也收干净；keep 只给项目目录、和另外多给主目录、/、空串两种都跑一遍，hotMeta 上同一组断言都得过（tests/test_runs.py:683）；case 脚本原文里的 PATH=… 不动；源码行上 token 的列号挪对、跨着主目录的那个去掉（tests/test_runs.py:690）；句末的换、.bak 和紧跟字母的不换；藏在 tuple 里的主目录触发 SystemExit（tests/test_runs.py:693）。test_public_export（tests/test_runs.py:701）端到端：真录一个 run、`graph --public`，HTML 里没有「主目录/」也没有本机工具目录（tests/test_runs.py:713），仓库下的 PATH 段留着、参数里的主目录写成 ~（tests/test_runs.py:714），带 public 标记，源码里写的 PATH=/usr/bin:/bin 没被改（tests/test_runs.py:716）；不带 --public 的导出照旧原样。

## 局限
- 导出的页面是固定切面：不能展开（其他切面的边详情没有预先算）、没有 `reveal`；不传 `width`，按默认 1180 排版；单文件的引用列表只能在内嵌了全文的文件里找（ds.js 逐个内嵌文件扫 token，codestrata/web/ds.js:167），也没有「同名的 .xxx」——`--link github` 的站点从 refs/、attrs/ 的分桶取全量倒排，这两样都有。也不带时序图：`export_payload` 不算时序，`web/ds.js` 的导出版对时序图请求直接报「请用 codestrata serve」。
- 导出里的别的 run（`hotBy`）只有切面上的次数：切过去时边详情只剩静态引用（ds.js 把调用清掉并写明原因）、没有「只看跑到的」那张图（不带 `graphHot`）、文件和符号上的次数是空的；只在它身上出现的 runtime-only 边，导出里没有明细（`edges` 只给总图的边和主 run 的——对比时加上 B 的——runtime-only 边算了），点开只说「导出版里没有这条边的详情」。
- `code=False` 的返回值自己不是一份能用的页面数据：没有源码，也没有告诉页面去哪取的 `link`。直接交给 `render.export` 的话，导出版的 ds.js 按 `EMB.files` / `EMB.sources` 找源码（codestrata/web/ds.js:74、codestrata/web/ds.js:75），文件一个都打不开；要由 `site.export_site` 加上 `link`，页面才把取源码、大纲、边、搜索、引用换成从 GitHub 和 data/ 取的那一套（codestrata/web/ds.js:150）。这个开关只该由 site 用。
- 对比只比两个（设计 §10：不做 N 路）。边详情里 import 触发的模块顶层执行次数（`import_exec`）和 import_only 那一组的「对方顶层执行了没有」只是 A 的，没有 B 的一份。
- ref 找不到、阶段不存在、run 还没有计数（还在录，或录制中断、要先 `runs merge`）时，`runs` 直接以 `SystemExit` 报错，这里不兜底——CLI（和 serve 启动时校验 `--hot`）上退出并给出下一步该跑的命令；serve 按请求解析时由 `serve.Handler._hot` 转成 `LookupError`，回 404 并带上这句提示，页面照常可用（对比的 B 解析失败只降级成不对比，见上）。
- 每个切面的 payload 都带全部顶层符号，vllm-omni 上一份约 2.5 MB；serve 的缓存键是（切面和宽度, run, 对比的 run）（serve.py:282），只留最近的 32 份（serve.py:294）——换着看几个 run、几种对比组合时，同一个切面会各存一份。
- `publicize` 只管两样：主目录，和 run 元数据里那三个目录列表。主目录以外的个人路径（比如 /mnt/data/用户名）、源码和解读里写的名字、别的环境变量的值（除了其中的主目录）都原样；PATH 写在一个更长的参数里的（bash -c "export PATH=…; …"）也只换主目录不收——`tok` 只认整个参数就是 K=V 的。公开页上的复刻命令因此不能原样执行（页面上注明了），跨着主目录的名字也点不了。复刻命令里有 PATH 这类字样时要 shlex 切开再用 `_q` 加引号，不是 UTF-8 的参数原先写成 `$'…'`，shlex 不认这种写法，拼回来成了 `'$…'`（单引号里的 $ 和 \x 都是字面的，不再表示原来的字节）。
- `_XREF` 是进程级的单槽缓存：同一进程里交替查两个仓库会互相顶掉，每次重新解析整份 xref.json（serve 一个进程只服务一个仓库，所以实际碰不到）。
