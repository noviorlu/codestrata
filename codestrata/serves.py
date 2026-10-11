"""开着的图服务（codestrata serve）的登记：配置目录下 serves/<端口>.json，{port, pid, repo, started, features, algo}。

serve 绑定端口之后写、退出时删（serve 装了 SIGTERM：主菜单停图服务用的是 terminate）。命令行按仓库找开着的页面
（view set / get / back / wait、explain --selected、status）。进程已经不在的登记在查找时顺手删掉；活着的还要问一次那个端口
（`/api/app` 回的 repo、pid 对得上才算：端口可能被别的程序复用了）——那一步在调用方（cli/view.py），这里不碰网络。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import compat as _compat
from . import confdir as _confdir

FEATURES = ["view"]             # /api/app 也回它：老 serve 没有 view，命令行退到 view url


def _dir() -> Path:
    return _confdir.config_dir() / "serves"


def register(port: int, pid: int, repo: Path, algo: str) -> Path:
    """写登记（整份原子地写）；写不了（配置目录只读）不影响 serve，返回路径"""
    d = _dir()
    rec = {"port": port, "pid": pid, "repo": str(Path(repo).resolve()), "started": time.time(), "features": FEATURES, "algo": algo}
    p = d / f"{port}.json"
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{port}.{pid}.tmp"
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass
    return p


def unregister(port: int, pid: int) -> None:
    """删掉自己的登记（同一个端口后来被别的 serve 登记了就不动）"""
    p = _dir() / f"{port}.json"
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("pid") == pid:
            p.unlink()
    except (OSError, ValueError):
        pass


def listed(repo: Path | None = None) -> list[dict]:
    """登记着、进程还在的图服务，新起的在前；给了 repo 只要这个仓库的。进程已经不在的登记顺手删掉"""
    out = []
    want = str(Path(repo).resolve()) if repo else None
    try:
        files = sorted(_dir().glob("*.json"))
    except OSError:
        return []
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _compat.pid_alive(rec.get("pid")):
            try:
                p.unlink()
            except OSError:
                pass
            continue
        if want is None or rec.get("repo") == want:
            out.append(rec)
    return sorted(out, key=lambda r: -(r.get("started") or 0))
