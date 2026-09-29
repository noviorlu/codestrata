"""主菜单（codestrata app）的项目：记住打开过哪些仓库、报告每个仓库的状态、浏览目录挑一个新的、
给「录制运行」的阶段输入框补全函数名。

只管数据：不管 HTTP（app.py），也不起进程（jobs.py、viewers.py）。
项目清单存在 $XDG_CONFIG_HOME/codestrata/projects.json（默认 ~/.config/codestrata/），整份原子地写。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import payload as _payload
from . import runs as _runs
from . import scan as _scan

MAX_DIRS = 500          # 一个目录里列出来的子目录上限（再多就是 node_modules 这种，不是要找的仓库）
MAX_RUNS = 20           # 项目卡片上列出来的 run 个数


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "codestrata"


class Registry:
    """打开过的项目，最近打开的在前。线程安全（服务是多线程的），每次改动都整份写回。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [p for p in d.get("projects") or [] if isinstance(p, dict) and p.get("path")]

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"projects": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return self._load()

    def paths(self) -> list[Path]:
        return [Path(p["path"]) for p in self.list()]

    def has(self, repo: Path) -> bool:
        return str(repo) in {p["path"] for p in self.list()}

    def add(self, repo: Path) -> Path:
        """加进清单（已在清单里就挪到最前）；返回规范化后的路径。不是目录就 ValueError"""
        repo = Path(repo).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError(f"不是一个目录：{repo}")
        with self._lock:
            items = [p for p in self._load() if p["path"] != str(repo)]
            self._save([{"path": str(repo), "opened": time.time()}] + items)
        return repo

    def touch(self, repo: Path) -> None:
        """记一次「打开」：挪到最前"""
        with self._lock:
            items = self._load()
            hit = [p for p in items if p["path"] == str(repo)]
            if hit:
                hit[0]["opened"] = time.time()
                self._save(hit + [p for p in items if p["path"] != str(repo)])

    def remove(self, repo: Path) -> bool:
        """从清单里去掉（不动仓库本身和它的 .codestrata/）"""
        with self._lock:
            items = self._load()
            rest = [p for p in items if p["path"] != str(repo)]
            if len(rest) == len(items):
                return False
            self._save(rest)
            return True


def _run_brief(r: dict) -> dict:
    # status_shown：录制进程已经没了的 recording 显示成「中断」（catalog 给的，同 runs ls）
    return {"id": r.get("id"), "case": r.get("case"), "status": r.get("status_shown") or r.get("status"),
            "loadable": r.get("status") in ("ok", "partial"), "created": r.get("created"),
            "phases": [p.get("name") for p in r.get("phases") or []], "events": bool(r.get("events"))}


def status(repo: Path) -> dict:
    """一个项目卡片要的全部：扫描过没有、多少文件、scan 之后改过几个、录过哪些 run"""
    repo = Path(repo)
    out = {"path": str(repo), "name": repo.name, "exists": repo.is_dir(), "index": None, "lag": 0,
           "runs": [], "n_runs": 0, "runs_error": None}
    if not out["exists"]:
        return out
    out["index"] = _payload.index_summary(repo)
    if out["index"]:
        out["lag"] = _payload.index_lag(repo)
    if _runs.has_runs(repo):                  # 不用 runs_dir：它会顺手建目录，看状态不该往仓库里写
        try:
            rs = _runs.catalog(repo)
        except SystemExit as e:               # runs/ 是软链、指向的盘没挂上
            out["runs_error"] = str(e)
        else:
            out["n_runs"] = len(rs)
            out["runs"] = [_run_brief(r) for r in rs[:MAX_RUNS]]
    return out


def scan_choices(repo: Path) -> dict:
    """「静态扫描」对话框：能选的目录（scan.candidate_roots，只列不挑）和上次扫描时选的（重新扫描时预先勾上；
    没扫描过是空列表——第一次扫哪些由用户自己勾）。上次选的不在候选里（命令行 scan --roots 给了更深的目录）
    也并进来，标 previous：用户上次的选择不能在对话框里丢掉。每项带 name（模块名用的最后一段），
    同名的一次只能选一个（scan.root_clashes）"""
    repo = Path(repo)
    cands = _scan.candidate_roots(repo)
    chosen = (_payload.index_summary(repo) or {}).get("roots") or []
    have = {c["path"] for c in cands}
    for r in chosen:
        d = repo / r
        if r not in have and d.is_dir():
            n = sum(1 for _ in _scan.iter_py_files(d))
            if n:
                cands.append({"path": r, "files": n, "package": (d / "__init__.py").exists(), "previous": True})
    for c in cands:
        c["name"] = c["path"].rstrip("/").split("/")[-1]
    return {"candidates": sorted(cands, key=lambda c: c["path"]), "chosen": chosen}


def _looks_like_repo(d: Path) -> dict:
    """子目录上的标记：是不是 git 仓库、有没有 Python 工程文件、扫描过没有（只看顶层，要快）"""
    def has(n: str) -> bool:
        return (d / n).exists()
    return {"git": has(".git"), "python": has("pyproject.toml") or has("setup.py") or has("setup.cfg"),
            "scanned": has(".codestrata/index.json")}


def browse(path: str | None) -> dict:
    """列出一个目录下的子目录（给「打开文件夹」挑仓库）。不给路径就从家目录开始；隐藏目录不列。
    路径不存在或不是目录：ValueError"""
    p = Path(path).expanduser() if path else Path.home()
    try:
        p = p.resolve()
    except OSError as e:
        raise ValueError(f"打不开：{p}（{e}）") from None
    if not p.is_dir():
        raise ValueError(f"不是一个目录：{p}")
    dirs, more = [], False
    try:
        entries = sorted(os.scandir(p), key=lambda e: e.name.lower())
    except OSError as e:
        raise ValueError(f"读不了这个目录：{p}（{e.strerror}）") from None
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if not e.is_dir():
                continue
        except OSError:
            continue
        if len(dirs) >= MAX_DIRS:
            more = True
            break
        d = Path(e.path)
        dirs.append({"name": e.name, "path": str(d), **_looks_like_repo(d)})
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None,
            "here": _looks_like_repo(p), "dirs": dirs, "more": more}


_SYMS: dict = {}          # repo → (symbols.json 的 mtime, [(qualname 小写, 键)])；整条替换，读的人不用锁


def find_symbols(repo: Path, q: str, limit: int = 20) -> list[str]:
    """给 --phase 的输入框补全：名字里含 q 的函数 / 方法，返回 `模块:限定名`（trace --phase 认的写法）。
    名字正好是 q 的排前面，其次限定名短的。没 scan 过就是 []"""
    q = (q or "").strip().lower()
    if not q:
        return []
    p = Path(repo) / ".codestrata" / "symbols.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return []
    hit = _SYMS.get(str(repo))
    if not hit or hit[0] != mt:
        # 两个请求同时来会各读一遍（结果一样，后写的覆盖）：比一把全局锁让一个大仓库挡住别的仓库好
        try:
            syms = _payload.load_index(Path(repo)).get("symbols") or {}
        except (OSError, ValueError, SystemExit):     # 正在重新 scan：symbols.json 可能写了一半
            return []
        hit = (mt, [(s["n"].lower(), k) for k, s in syms.items() if s.get("k") == "func"])
        _SYMS[str(repo)] = hit
    found = [(n, k) for n, k in hit[1] if q in n]
    found.sort(key=lambda x: (x[0].rsplit(".", 1)[-1] != q, len(x[0]), x[1]))
    return [k for _, k in found[:limit]]
