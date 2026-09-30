"""录制：跑一个真实 case，记下实际发生的调用。分三块，运行环境不同、失败方式也不同：

- hook.py：被注入到被测进程里的那段代码（和 driver 之间的约定：环境变量、parts/ 下的文件）。
- driver.py：在外面跑命令、按 SIGINT → SIGTERM → SIGKILL 停、扫 /proc 找残留进程（只支持 Linux）。
- analysis.py：录之前解析 `--phase`，录完之后合并分片、折算到当前的 index（纯数据处理，任何系统都能跑）。

依赖方向：driver → hook、analysis；hook 和 analysis 互不依赖。
"""
