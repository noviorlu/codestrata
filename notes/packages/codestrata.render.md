---
written_by: claude-opus-5-5
target: codestrata.render
kind: package
code_sha: b9820ffd8d8e353a
status: draft
refs: render.py:1@1b5c0234,codestrata/web/ds.js:47@454a9417,render.py:17@742a821e,codestrata/web/app.js:335@f644897f,codestrata/web/ds.js:104@d7fdf381,codestrata/web/ds.js:110@a0ec69b8,codestrata/web/ds.js:13@04893e6b,codestrata/web/ds.js:35@b67f5ba4,render.py:20@5e4e1cfc,render.py:26@70185c58,render.py:36@b0254794,codestrata/web/app.js:232@b7807a3b,codestrata/web/app.js:42@0a996950,codestrata/web/app.js:251@577c9bd4,codestrata/web/app.js:530@cf93dc00,codestrata/web/app.js:255@9b6a4b25,codestrata/web/app.js:259@a8b2ab78,codestrata/web/app.js:261@98742921,codestrata/web/app.js:613@42698abf,codestrata/web/app.js:269@30563aad,codestrata/web/app.js:424@b119d4f6,codestrata/web/app.js:388@ca554534,codestrata/web/app.js:327@ef68ae85,codestrata/web/app.js:300@22533f15,codestrata/web/app.js:312@5173065b,codestrata/web/app.js:227@2156c296,codestrata/web/app.js:55@ea4a0dbf,codestrata/web/app.js:324@160a573a,codestrata/web/app.js:333@91906407,codestrata/web/graph.js:312@560acedc,codestrata/web/app.js:369@38a21d48,codestrata/web/app.js:362@dcc65010,codestrata/web/app.js:44@dbb63905,codestrata/web/app.js:51@0354f1ce,codestrata/web/app.js:160@ce24491f,codestrata/web/app.js:49@30308b92,codestrata/web/app.js:161@41d33897,codestrata/web/seq.js:85@25448a7a,codestrata/web/app.js:631@2ae47ef4,codestrata/web/seq.js:54@4b7d6ee4,codestrata/web/seq.js:50@db89b767,codestrata/web/seq.js:63@6f2c7eed,codestrata/web/seq.js:80@ad66bab0,codestrata/web/seq.js:98@d11fae72,codestrata/web/seq.js:110@02eed11a,codestrata/web/seq.js:181@8a7decf1,codestrata/web/seq.js:113@14c9dbd2,codestrata/web/seq.js:142@22523444,codestrata/web/seq.js:294@d8bc58c9,codestrata/web/seq.js:291@54c06dfd,codestrata/web/seq.js:248@407f576e,codestrata/web/seq.js:261@2dcfde47,codestrata/web/seq.js:103@85da7c7e,payload.py:420@556fb9ff,payload.py:580@e6c4cb43,payload.py:543@52abe3fa,payload.py:559@c7e2ec1e,render.py:30@3c13f3a9
---

## 是什么
单文件导出：把 `codestrata/web/` 下的前端（`web/index.html` + `web/app.css` + 7 个 JS）和一份数据内联成一个 HTML，只读、离线、可以直接发给别人。只有一个函数 `export`，只被 `__main__` 的 `cmd_graph` 调用。M5 给前端加了第 7 个文件 `web/seq.js`（时序图），导出版也照样带上它，但导出版本身没有时序图（见「局限」）。

## 为什么这样切
和 `serve` 用的是**同一套前端文件**，唯一的差别是数据源：serve 时前端 fetch /api/*，导出时读内嵌的 window.CS_EMBEDDED。切换由 `web/ds.js` 完成，UI 代码本身不感知（render.py:1）。数据怎么组装是 `payload` 的事（`export_payload`），这里只管打包——所以它不依赖任何内部模块。两种模式在「能做什么」上的差别也都收在 `web/ds.js` 里，不给导出版另写一套 UI：
- M4：serve 能在页面里换叠在图上的 run，导出版固定叠导出时那一个（一个「能不能换」的开关）；
- M5：时序图只在 serve 里有。导出版的 ds 也有 seq / seqOverview / seqFind 三个入口，但一调就返回一个说明「导出的单文件没有带时序图；请用 codestrata serve」的错误（codestrata/web/ds.js:47）；工具栏上根本不出「模块图 | 时序图」，地址里带着 view=seq 打开也会退回模块图并弹类似的说明。所以时序图这块代码在导出版里是死的，但带上它只多 19 KB，换来 app.js 不用分两种写法。

代价是**脚本清单要手工维护两份**：`web/index.html` 末尾的一串 script 标签给 serve 用，`SCRIPTS` 给导出用（render.py:17）。M5 两边都加了 seq.js，现在两份一致；没有测试核对这两份清单。漏了的后果看是哪个文件：
- `web/search.js` 漏了不会报错——`web/app.js` 里是「有搜索模块才初始化」，搜索栏和右上角的「搜索」按钮在 HTML 里默认都是隐藏的，导出版就只是悄悄没有搜索。
- `web/seq.js` 漏了就会报错：app.js 切视图时直接调 CS.seq.hide / show，不先看有没有这个模块（codestrata/web/app.js:335）。serve 里一点「时序图」就抛错；导出版平时走不到，但地址里带着 view=seq 打开时，启动会在这里抛错，整页显示「加载失败」。

## 读法
要读懂 `export`，得先知道它打包的前端长什么样（图上看不到，前端不是 Python）。整页是一个应用：上面一条（标题、统计、「?」；下一行是 运行 / 阶段 / 图 / 边 / 视图 开关），图铺满剩下的全部空间、在自己的框里上下左右滚；其余都**浮在图上、半透明**：右上角的搜索栏、图下沿的详情栏，两个都能收起、拖边框改大小（记在浏览器里）。「图」那一组（模块图 | 时序图）只在 serve 里、叠着一个 run 时出现；模块图和时序图**共用同一个图框**，同一时刻只显示一张。

- `web/ds.js` —— 数据源层，整个前端只通过它拿数据。live 走 /api/*；embedded 读内嵌 JSON，另外补了导出版才需要的：判断某个文件带没带全文、在内嵌文件里自己找引用、把共用目标表里的 xref 目标补回每个文件。**当前叠哪个 run 也放在这一层**：CS.ds.run 存「完整 id@阶段」（空 = 只看静态图），live 的图、边详情、引用、输入包四种请求都自动带上 run=（codestrata/web/ds.js:104）——叠加会影响的就这四样，其余模块照旧调 ds，不知道有 run 这回事。时序图的三个请求（seq、seqOverview、seqFind，codestrata/web/ds.js:110）也用这个 run。请求失败时，错误信息优先用服务端返回体里的 error（「这个 run 没有录时序事件」「这个 run 里没有 a → b 的调用」），没有才退回「url → 状态码」（codestrata/web/ds.js:13）——时序图出错时整块显示的就是这句话，所以它得是人话。embedded 的 run 永远是空、canSwitchRun 为 false（codestrata/web/ds.js:35），它的 runs() 用内嵌的 hotMeta 拼一个只有一项的列表，让启动走同一条路
- `web/graph.js` —— SVG 绘图：泳道、框、节点、边、「＋ / −」展开收起。缩放：图左上角的 ＋ / － / 100%，或按住 Ctrl（Mac 上 ⌘）滚滚轮，以鼠标所在点为中心（触控板捏合在浏览器里也是 Ctrl+滚轮，顺带支持）；「✥」移动模式下按在哪都能拖图，拖完那次 click 在捕获阶段拦掉，不会误选节点。选中时只把看不见的节点滚到「可见区域」中间——详情栏盖住的那截不算可见。M5 加了一个 hidden()：模块图被时序图盖住时，滚动、缩放、聚焦都不做（见下面「两张图共用一个图框」）
- `web/viewer.js` —— 全文窗口（逐行高亮 + 大纲）。Ctrl+点击名字跳到定义，旁边打开一栏：定义在最上面，下面是所有引用（按文件分组，调用 / 引用 / import）；点定义本身只开这一栏。跳转有「← 返回」栈，和编辑器的「转到定义 / 返回」一样。名字指向哪由 scan 时的交叉引用给出，这里只把能点的名字包一层 span
- `web/panel.js` —— 详情栏的左右两半：左边模块 / 边的机器事实（文件树、源码片段——片段里也能 Ctrl+点击），右边解读。搜索栏定位到某个文件 / 函数时，由它在文件树里展开并标出那一行
- `web/search.js` —— 搜索栏：名字索引一次拿全，在前端打分排序，不来回请求。按**名字本身**找（函数看自己的名字、文件看文件名、模块看最后一段），词里带 `.` 或 `/` 才看路径——早先连路径一起匹配，搜目录名时出来的全是那个目录下的函数。点结果先在图上展开到所在模块并选中，再在详情栏里展开到它；`/` 或 Ctrl+K 随时回到搜索框；框里有字时图上包含命中的节点一直高亮，换切面后重新套
- `web/seq.js` —— 时序图（M5）：一个 run 里跨节点的调用按时间排开。生命线 = (进程, 当前切面上的节点)，消息 = 两个节点之间的一次调用。上面一条固定不动（窗口信息、时间刷、生命线头），下面一张 SVG 一行一条。数据来自 /api/seq：按切面映射、同一节点内部的调用不画、放不下时把重复片段折成 loop 行、自动收窄时间窗，这些都是服务端 `seq` 模块现算的，前端只负责画行和把点击翻译成新的请求
- `web/app.js` —— 启动，串起上面六个：切面（展开 / 收起、连点时只认最后一次、重画后尽量保留选中）、叠哪个 run（运行按钮、阶段按钮、URL hash，见下面「换 run」）、两张图的切换和选中同步（见「两张图共用一个图框」）、详情栏、拖边框改大小的通用逻辑、「?」帮助。帮助里收着怎么读图、怎么操作，以及 hot 图的来历：case 命令、被 trace 的进程**按命令合并**（跑到仓库代码多的在前）、case 脚本的内容（录制时没存的标明是现在的内容）。统计那一行只留一个 hot 标记，点它打开帮助

`SCRIPTS` 的顺序就是依赖顺序：ds 被所有人用，viewer 定义了 panel 要用的 Ctrl+点击逻辑，seq 加载时只定义 CS.seq、用到 graph / app / ds 都在运行时，app 必须最后——见下面的 fragment 模式，它可能一加载就同步启动。

## 关键算法
### 拼装
读 `web/index.html`，把 stylesheet 链接换成内联的 `<style>`，用正则删掉所有外链 script 标签，再把「内嵌数据 + 按 `SCRIPTS` 顺序拼好的 JS」追加到末尾（render.py:20）。因为 script 标签是按正则整批删掉、再按 `SCRIPTS` 重拼的，index.html 里的顺序对导出版不起作用，两份清单各管各的。

### `</` 要转义
内嵌数据里的源码片段可能含 `</script>`，原样塞进 `<script>` 会提前结束脚本。`json.dumps` 之后把 `</` 换成 `<\/`（render.py:26）——在 JS 字符串里两者等价。

### fragment 模式
`fragment=True` 去掉 doctype 和 meta 外壳（render.py:36），给自己会包外壳的宿主（比如 artifact 页面）用。也因为这种宿主会在 DOMContentLoaded 之后才执行内联脚本，`web/app.js` 的启动写成了「已经加载完就直接启动」。

### 换 run（M4，只在 serve 里）
目标是不重启 serve 就能在「静态图 ↔ 这次 run ↔ 那次 run」之间来回切。
- **先定 run 再取图**（codestrata/web/app.js:232）：URL hash 里的 `#run=<id>@<phase>` → /api/runs 返回的 default（也就是 `serve --hot` 给的）→ 只看静态图。按 id 或 case 名在列表里找；找不到、或者还不能加载（没有计数：还在录或中断了），就退回静态图并弹一个浮层提示，而不是整页加载失败。两种情况说法不同（「找不到了（删了？）」/「还没有计数，还在录或要 runs merge」），因为该做的事不一样。提示不写进工具栏的进度那一行：图画好后 refreshStatus 的解读统计一回来就把那一行盖掉，所以改成图画完后弹浮层（codestrata/web/app.js:42）。/api/runs 本身失败时也照样把「已知 run」集合设成空（codestrata/web/app.js:251）——否则之后刷新列表时查这个集合会抛错、被 catch 吞掉，run 列表就一直是空的。
- **hash 里存解析好的完整 id**（codestrata/web/app.js:530）：图回来后按 hotMeta 把「run_id@阶段」写回 CS.ds.run 和 hash。case 名会随着重录指到新的 run，存 case 名的话刷新一下看到的就换了一个 run。
- **运行按钮**：显示 case 和录制时间，弹出的列表第一行是「静态图」，下面按 case 分组。每行：时间（悬停看完整 id）、tags、git 短哈希、活跃进程数、各阶段的函数数、录了时序事件的加「时序」标记、「⚠ 录制后改过 N 个文件」和「录制时安装包和仓库有 N 个文件不一致」；status 不是 ok 的行变淡并列出 problems；没有计数的行不能点，悬停提示去 runs merge。
- **阶段按钮**：当前 run 有两个以上阶段才出现（「全部」+ 各阶段）。从列表选一个 run 时，有 serving 阶段就先选它（codestrata/web/app.js:255）——启动阶段的初始化调用会淹没请求本身。
- **切换本身**（codestrata/web/app.js:259）：先让时序图作废在路上的请求、扔掉上一个 run 的时序数据和记下的那条消息、把时间窗退回新 run 的阶段起点（codestrata/web/app.js:261），再改 CS.ds.run、写 hash，然后拿当前切面调 setCut。于是换 run 就是「同一个切面再取一次图」：_cutSeq 丢掉晚回来的旧响应（codestrata/web/app.js:613），连着点几个 run 只认最后一个；keepSelection 让选中的节点 / 边换完还选着。换不过去（run 刚被删、还没有计数，setCut 返回 false）时把 CS.ds.run 和 hash 退回原来那个，并用浮层提示原因（codestrata/web/app.js:269）——不退的话，图还是旧的，之后取边详情、引用、输入包带的却是那个换不过去的 run。但如果这期间已经有更新的请求（_cutSeq 变了），就不退，免得盖掉后来的选择。设计里原本打算把 setCut 推广成 load({open, run, view})，run 放进 ds、view 用单独的 setView 之后就用不着了。
- **新录的 run**：窗口重新获得焦点时刷新列表（codestrata/web/app.js:424），有新的只在按钮上加个点，不自动切过去——正在看的图不该自己变；打开列表时点就消了。
- **换回静态图**：「只看跑到的」自动关掉（codestrata/web/app.js:388），不然节点会被全藏起来；这个开关连同帮助里的 hot 横幅一起藏掉。

导出版走同一段代码，但按钮是灰的（悬停说明要换请用 serve），不出阶段按钮，也不监听焦点。

### 两张图共用一个图框（M5，只在 serve 里）
设计上两张图共享两样东西：**切面**（open）和**选中**（CS.graph.state 里的 sel / selEdge）。时序图不另存一份，全部借模块图的，于是抽屉、搜索、hash 都不用知道有第二张图。
- **切换**（codestrata/web/app.js:327）：模块图的 svg 设成 display:none、藏起缩放按钮，时序图的容器在同一个图框里显示出来。「时序图」按钮只有当前 run 在 /api/runs 里标了录过事件时才能点；灰着时的悬停说明分两种（codestrata/web/app.js:300）：/api/runs 标了 events_error（录了事件，但整理成 span 时失败了）就提示用 runs merge 重来，否则才说录的时候要加 --events——两种情况该做的事不一样，前者重录一遍是白录。地址里带着 view=seq 却切不过去时，退回模块图并用浮层说清原因（codestrata/web/app.js:312）：导出版、还没选 run、这个 run 的事件整理失败、这个 run 没录事件，说法和按钮上的一致；地址里的 run 已经找不到时不再重复提示（启动时已经提示过一次）。
- **hash**：view=seq 跟在 run= 后面写进地址（codestrata/web/app.js:227），启动时模块图画完后再读（codestrata/web/app.js:55）——要先知道叠的是哪个 run、它有没有事件。
- **各记各的滚动位置**（codestrata/web/app.js:324）：两张图共用一个会滚的框，切走时记下这张图的滚动位置，切回来时回到原处。时序图要等数据回来、画好之后才能恢复（codestrata/web/app.js:333），之前框的高度还不对；要跳到某条消息时不恢复，交给「滚到选中的那条」。
- **graph.js 的 hidden()**（codestrata/web/graph.js:312）：svg 藏着时，所有 getBoundingClientRect 量出来都是 0，graph 会以为节点在可见区域之外、把共用的图框滚过去——在时序图里点一下、搜一个名字，时序图就被滚走了。所以 reveal / focus / showEl / setZoom 在图藏着时一律直接返回。Ctrl+滚轮的监听挂在图框上，照样拦下浏览器的默认缩放，于是在时序图里 Ctrl+滚轮什么也不做。
- **时序图上点 → 模块图的选中**：点生命线头 = CS.graph.pick 这个节点（再点一次取消），点消息 = CS.graph.pickEdge 这条边（codestrata/web/app.js:369），抽屉、面板走的都是原来的路。不强行打开抽屉（codestrata/web/app.js:362）：抽屉会盖住刚点的那一行，它的标题栏一直看得见，要看详情自己点开。
- **别处的选中 → 时序图的高亮**：选中还会从很多地方变（Esc、点空白、搜索、抽屉里的链接、换切面后保留选中），与其每处都通知时序图，不如在启动时把 graph 的四个回调各包一层（codestrata/web/app.js:44）：先跑原来的回调，当前是时序图、手上也有时序数据时按新的选中重画一遍（codestrata/web/app.js:51）。
- **抽屉标题写消息**：点消息时 CS.seq.picked 记下这一行，时序图里选中的边正好是它时，抽屉副标题换成这条消息本身（codestrata/web/app.js:160）：两端的函数、从第几秒开始、用时（或「到进程结束都没返回」）、连续几次合成一行、async 挂起几次、pid 和线程、被调函数的 文件:行。切视图后按当前视图重写一次标题。记下的这条在同一层包装里清掉（codestrata/web/app.js:49）：选中换成了别的节点、别的边，或者取消选中，它就不再是「刚点的那条」，不清的话之后再选回这条边，副标题写的还是很久以前点的那一次；唯独选的还是同一条边时留着——点消息本身就是先记下再 pickEdge，切回模块图时也会对同一条边再 pickEdge 一次，这两处一清就白记了。换 run 时 reset 也把它清掉。
- **「在时序图里看」**（codestrata/web/app.js:161）：模块图上选中一条边、当前 run 录了事件时，抽屉标题栏里多一个按钮。按下去调 seqFind 找这条边在当前切面上第一次被调用的时刻（服务端先在 run 选的阶段里找），从那一刻前 1 µs 开始取时间窗，切到时序图后把第一条高亮的消息（或包着它的 loop 行）滚到时序图固定表头之下、抽屉之上（codestrata/web/seq.js:85）。
- **切面、run 跟着走**（codestrata/web/app.js:631）：setCut 成功后如果正在看时序图，用同一个时间窗按新切面重取——在时序图的目录生命线上点 ＋ 展开，模块图和时序图一起细到子模块；新 run 没录事件就退回模块图。

### 时序图的画法（`web/seq.js`）
- **请求**：每次取图都把当前切面和记下的时间窗参数（t0、t1、max、fold）一起发出去；每次 show 递增一个序号，晚回来的旧响应直接丢掉（codestrata/web/seq.js:54）。时间刷的概览按 run 缓存（codestrata/web/seq.js:50），换了 run 就重取，旧 run 的概览晚回来也不会被当成新的。请求失败时除了把错误写进容器，还把手上的数据清掉（codestrata/web/seq.js:63），换 run 的 reset 也清（codestrata/web/seq.js:80）；render 没数据就直接返回（codestrata/web/seq.js:98）。否则之后选中一变（比如按 Esc），包在 graph 回调外面的那层就会拿上一次的数据重画、盖掉错误提示——失败的若是刚换过去的 run，画出来的就是旧 run 的时序。
- **固定表头**：第一行是窗口信息，写成「起点 + 宽度」——很密的一段不到 1 ms，写成「1.440s – 1.440s」看起来像是空的；然后是「起点」「下一屏 ▸」两个按钮和计数（多少行、多少条消息、节点内部几次没画、import 时的模块顶层执行几次没画、有进程的事件录到上限的警告）。按钮放在左边，因为右上角浮着搜索栏；表头里的窗口信息和时间刷还按搜索栏的实际宽度缩短（codestrata/web/seq.js:110）。第三行是生命线头：上排是进程（跨它的几条生命线，悬停看完整命令），下排是节点按钮，名字去掉仓库唯一的顶层包名；目录节点后面带「/」，能展开时右边有个 ＋（codestrata/web/seq.js:181）。
- **行**：一行一件事，按时间先后排、不按比例画，左边一列是相对窗口起点的时刻。四种行：消息（橙色箭头，async 的是虚线、到进程结束都没返回的换成过期色，标签是被调函数和用时）、loop（虚线框横跨涉及的生命线，写「↻ ×次数、一轮里的调用、总用时（点开看这一段）」）、空闲（「⋯ 空闲 340ms」）、派生子进程（从父进程的第一条生命线指到子进程的第一条，两个进程在这个窗口里都有生命线才画）。
- **画不下 / 没东西**：服务端返回太密时给一个「看建议的窗口」按钮（codestrata/web/seq.js:113），说明分两种：整段折过了还放不下，写「折叠后还有 N 行」；窗口里的 span 多到服务端不肯整段折一遍（几十万条要好几秒），它只估计、行数给的是空，这时改写「有 N 次跨文件调用」，照行数写就成了「null 行」；窗口里没有跨节点的调用时，说明有多少次发生在同一个节点内部（在模块图上展开这个节点就能看到）、多少次落在 index 之外的文件上。
- **时间刷**（codestrata/web/seq.js:142）：整个 run 的时间轴，调用最多的至多 6 个进程各画一条密度折线，阶段分界画成虚线并标名字，当前窗口是一块浅色。按住拖出一段就看那一段，点一下（没拖开）就从那一刻开始让服务端自动收窄（codestrata/web/seq.js:294）。按下时拦住冒泡，否则图框会把它当成拖动平移；拖到刷子外面才松开时，随后那次 click 会落到公共祖先上、冒泡到图框触发「点空白取消选中」，所以在图框上用捕获阶段吞掉紧接着的一次 click（codestrata/web/seq.js:291）。
- **点开 loop**（codestrata/web/seq.js:248）：请求这个 loop 自己的那段时间、fold=0、上限 600 行。不关折叠的话，服务端会把同一段又折成同一行，点了等于没点。
- **下一屏**（codestrata/web/seq.js:261）：从服务端给的 next_t0 接着看，不按这一屏最后一行的结束时刻猜——loop 的结束时刻里可能包着挂起的时间，按它猜会跳过一段。在点开的 loop 里翻页时继续不折叠，翻出这个 loop 的范围后回到普通的自动收窄。
- **键盘和焦点**：消息行、loop 行可以 Tab 到、按 Enter 或空格触发；生命线头和按钮本来就是 button。选中一变整张图就重画，焦点会掉回 body，所以重画前记下焦点在哪（哪个节点、哪个导航按钮、第几行），画完放回去（codestrata/web/seq.js:103）。
- **点空白**：生命线头、消息、loop、表头的按钮都自己拦住冒泡；点时序图的空白处照样冒泡到图框、取消选中，和模块图一样。

### 过期文件
Ctrl+点击的行列号是 scan 时的快照。文件在 scan 之后改过（大小或修改时间变了，payload.py:420），链接会落在别的字上，所以宁可不给：全文窗口标一句「重新 scan 才能 Ctrl+点击」，引用列表里来自改过文件的行标「改过」。hot 图另有一套判断（和录制时记下的文件哈希比）：录制后有文件改过时，hot 标记、帮助和运行列表里都提示叠加可能不准。

## 局限
导出版是固定的一个切面加一份有限的数据：
- 不能展开 / 收起（「＋ / −」不画）；排版宽度是导出时定的，窗口变宽只按比例放大（最多 1.25 倍），不像 serve 按图框宽度重排
- 只叠导出时那一个 run（`graph --hot`），不能换 run、换阶段；设计里多 run 一起导出排在 M7
- **没有时序图**：时序事件一律不嵌入（设计里 M7 也不嵌），工具栏上不出「模块图 | 时序图」，抽屉里也没有「在时序图里看」
- 搜索能用（名字索引内嵌了，payload.py:580），但点一个被收着的模块只能选中装着它的节点
- 整个文件控制在 14 MB 以内（`total_budget`，payload.py:543；单文件宿主上限 16 MB）：先算好其余部分，剩下的额度才给全文，这次跑到过的文件和解读里引用过的文件优先。xref 目标全文件共用一张表（payload.py:559），省下的额度能多带一两百个文件
- 没带全文的文件只能看顶层符号；Ctrl+点击跳向这种文件时只提示、留在原地；「谁引用了它」只在内嵌了全文的文件里找，会标明结果不全
- 不能写解读、不能跳编辑器；要这些用 serve

serve 里的时序图：
- 给搜索栏让的宽度只在重画时量一次，之后打开、收起或拖宽搜索栏，要等下一次重画才跟上
- 时间刷最多画 6 个进程；行不按时间比例排，两条消息隔多久只能看左边那列时刻和「空闲」行
- 进程之间只画派生；两个进程在当前窗口里有一个没有生命线，派生也不画

## 不确定
- render.py:30 把 `</div>\n\n` 替换成同样的字符串，是个空操作，看起来是早先改动留下的。
- CS.seq.picked 现在只在选中换成别的节点 / 边（或取消选中）、换 run 时清掉，同一条边上换了时刻不清。于是：在时序图里点了某条边 5 秒处的一条消息 → 切回模块图（边还选着）→ 点「在时序图里看」跳到这条边第一次出现的 1 秒处，抽屉副标题写的仍是 5 秒那条。翻「下一屏」之后也一样，副标题描述的消息可能已经不在屏上。
