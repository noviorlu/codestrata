"""codestrata：给一个 Python 仓库画静态架构图，再把一次真实运行叠上去。"""
import sys


def self_command(*args: str) -> list[str]:
    """用当前这个 Python 跑 codestrata 的命令行。主菜单起的后台任务、图服务子进程都用它：
    codestrata 装在哪个环境里，子进程就在哪个环境里"""
    return [sys.executable, "-m", "codestrata", *args]
