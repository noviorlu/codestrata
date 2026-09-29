"""主菜单（codestrata app）里「打开图」：每个打开的项目一个 `codestrata serve` 子进程。

图页面本身不变——还是那个一个进程服务一个仓库的 serve，只是由主菜单替你起：端口自动挑，
带上 --home（页面上放回主菜单的链接），扫描完重启让它读到新的 index（serve 只在启动时读 index），
主菜单退出时一起收掉。每个仓库一个日志（<日志目录>/serve-<仓库路径的哈希>.log，每次启动覆盖），
起不来时把末尾给页面看。
"""
from __future__ import annotations

import hashlib
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import self_command

START_TIMEOUT = 120.0    # 大仓库（1600 个文件）serve 起来要几秒；再宽一些


class ViewerError(Exception):
    """serve 起不来：带着日志末尾"""


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


@dataclass
class _Viewer:
    repo: str
    port: int
    proc: subprocess.Popen
    log: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None


class Viewers:
    def __init__(self, home: str, logdir: Path):
        self.home, self.logdir = home, logdir
        self._v: dict[str, _Viewer] = {}
        self._lock = threading.Lock()          # 护着 _v 和 _locks，只在查 / 改字典时拿，很短
        self._locks: dict[str, threading.Lock] = {}   # 每个仓库一把：起一个大仓库要几秒，别挡住别的仓库
        self._closed = False                   # stop_all 之后：正在起的算作废，不再起新的

    def _repo_lock(self, repo: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(repo, threading.Lock())

    def _get(self, repo: str) -> _Viewer | None:
        with self._lock:
            return self._v.get(repo)

    def _set(self, repo: str, v: _Viewer | None) -> None:
        """登记（v 为 None 是注销）。stop_all 之后起好的一律作废：杀掉、报错——否则主菜单退出了它还在跑"""
        with self._lock:
            if v and not self._closed:
                self._v[repo] = v
                return
            self._v.pop(repo, None)
        if v:
            self._kill(v)
            raise ViewerError("主菜单正在退出")

    def ensure(self, repo: str) -> str:
        """起（或复用）这个仓库的 serve，等它能接连接了返回地址；起不来 ViewerError"""
        with self._repo_lock(repo):
            v = self._get(repo)
            if v and v.alive:
                return v.url
            v = self._start(repo)                  # 死掉的那份的端口可能已被别人占了：挑新的
            self._set(repo, v)
            return v.url

    def _start(self, repo: str, port: int | None = None) -> _Viewer:
        """port：沿用原来的端口（重启时，页面上开着的标签刷新一下就行）；None 就挑一个空闲的"""
        self.logdir.mkdir(parents=True, exist_ok=True)
        port = port or free_port()
        log = self.logdir / f"serve-{hashlib.sha1(repo.encode()).hexdigest()[:12]}.log"
        with open(log, "wb") as out:
            proc = subprocess.Popen(self_command("serve", repo, "--port", str(port), "--home", self.home),
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        v = _Viewer(repo=repo, port=port, proc=proc, log=log)
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if not v.alive:
                raise ViewerError(f"图服务没起来（退出码 {proc.returncode}）：\n{self._tail(log)}")
            if _listening(port):
                return v
            time.sleep(0.2)
        proc.kill()
        raise ViewerError(f"图服务 {START_TIMEOUT:.0f} 秒还没起来：\n{self._tail(log)}")

    @staticmethod
    def _tail(log: Path, n: int = 20) -> str:
        try:
            return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    def _kill(self, v: _Viewer) -> None:
        if v.alive:
            v.proc.terminate()
            try:
                v.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                v.proc.kill()

    def restart(self, repo: str) -> None:
        """重新扫描之后：正在跑的就在原端口上重启（读新的 index）；没在跑就什么都不做，下次打开时自然是新的。
        起不来 ViewerError（旧的已经停了）"""
        with self._repo_lock(repo):
            v = self._get(repo)
            if not v or not v.alive:
                return
            self._kill(v)
            self._set(repo, None)
            self._set(repo, self._start(repo, v.port))

    def stop(self, repo: str) -> None:
        with self._repo_lock(repo):
            v = self._get(repo)
            self._set(repo, None)
        if v:
            self._kill(v)

    def stop_all(self) -> None:
        with self._lock:
            self._closed = True
            vs, self._v = list(self._v.values()), {}
        for v in vs:
            self._kill(v)
