"""codestrata：仓库的运行路径工具——静态扫描出调用图，把一次真实运行（每个进程、每条线程）录下来叠上去，
看清这次在仓库里走了哪条路、按什么顺序。"""
import sys


def self_command(*args: str) -> list[str]:
    """用当前这个 Python 跑 codestrata 的命令行。主菜单起的后台任务、图服务子进程都用它：
    codestrata 装在哪个环境里，子进程就在哪个环境里"""
    return [sys.executable, "-m", "codestrata", *args]
