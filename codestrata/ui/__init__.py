"""界面取数：serve 按请求从 graph（扫描出的索引，叠上的 run）里取前端要的数据。只读，不产出任何东西。

  load       读索引（index.json + symbols.json）、把一个 run 叠上来（经 runs.load → align）
  graphview  一个切面上的图：节点、边、框、排版、叠加
  edge       点开一条边：它承载了哪些引用和调用（两边怎么对上由 align 定）
  source     代码窗口：整个文件、符号片段、大纲、Ctrl+点击的跳转和引用
  search     搜索栏的名字表，让一个模块在图上露出来
"""
