"""主菜单（codestrata app）里点按钮跑的后台任务：静态扫描、录一次运行。

每个任务就是一条 `python -m codestrata scan|trace …` 子进程——和在终端里敲的命令一模一样，
录下的 run 里记的复刻命令也就是它。输出逐行收进内存给页面轮询；同一个仓库同时只跑一个任务
（扫描会重写 index，录制要读 index 解析 --phase，两者不能交错）。

TraceSpec 是「录制运行」表单的数据：校验、拼成命令行、从一个已有的 run 还原（复刻）。
"""
from __future__ import annotations

import itertools
import shlex
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import self_command
from .runs import CASE_RE, fmt_seconds
from .trace import resolve_phase_at

MAX_LINES = 4000        # 每个任务在内存里留的输出行数（更早的丢掉，行号照样往上数）
KEEP_DONE = 5           # 每个仓库留几个已经结束的任务（页面上只看最近一个；再早的丢掉，免得一直占内存）


def _cli(*args: str) -> list[str]:
    """任务的命令行：python -u -m codestrata …。-u 让 codestrata 自己的输出不缓冲（页面实时看到）；
    不用 PYTHONUNBUFFERED 环境变量——那会一路传给被录的命令，和终端里复刻出来的不一样"""
    cmd = self_command(*args)
    return [cmd[0], "-u", *cmd[1:]]


def scan_argv(repo: Path) -> list[str]:
    return _cli("scan", str(repo))


@dataclass
class TraceSpec:
    """「录制运行」表单。command 是一行 shell 风格的命令（在仓库根目录执行，和 trace 一样），
    phases 是 [[阶段名, 函数], …]（trace --phase 的 名字=函数），env 是 trace --env 的 K=V。
    tags / roots / stop_grace 表单上不显示，只是从一个 run 复刻时原样带过去"""
    repo: str
    case: str
    command: str
    phases: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    timeout: float | None = None
    events: bool = True
    note: str = ""
    attach: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    roots: list | None = None
    stop_grace: float | None = None

    @classmethod
    def from_json(cls, d: dict) -> "TraceSpec":
        """页面提交的表单 → TraceSpec；字段类型不对就 ValueError（再调 validate 查内容）"""
        if not isinstance(d, dict):
            raise ValueError("表单要是一个 JSON 对象")

        def seconds(k: str) -> float | None:
            v = d.get(k)
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                raise ValueError(f"{k} 要是秒数：{v!r}") from None

        phases, env = d.get("phases") or [], d.get("env") or {}
        attach, tags, roots = d.get("attach") or [], d.get("tags") or [], d.get("roots")
        if not (isinstance(phases, list) and all(isinstance(p, list) and len(p) == 2 for p in phases)):
            raise ValueError("phases 要是 [[名字, 函数], …]")
        if not (isinstance(env, dict) and isinstance(attach, list) and isinstance(tags, list)
                and (roots is None or isinstance(roots, list))):
            raise ValueError("env 要是 {K: V}，attach / tags / roots 要是列表")
        return cls(repo=str(d.get("repo") or ""), case=str(d.get("case") or "").strip(),
                   command=str(d.get("command") or "").strip(),
                   phases=[[str(a).strip(), str(b).strip()] for a, b in phases if str(a).strip() or str(b).strip()],
                   env={str(k).strip(): str(v) for k, v in env.items() if str(k).strip()},
                   timeout=seconds("timeout"), events=bool(d.get("events", True)), note=str(d.get("note") or ""),
                   attach=[str(a) for a in attach if str(a).strip()], tags=[str(t) for t in tags],
                   roots=[str(r) for r in roots] if roots is not None else None, stop_grace=seconds("stop_grace"))

    @classmethod
    def from_run(cls, repo: Path, run: dict) -> "TraceSpec":
        """一个已有 run 的 run.json → 同样的录制参数（「复刻」：表单预先填好，改改再录）"""
        rec = run.get("rec") or {}
        return cls(repo=str(repo), case=run.get("case") or "", command=shlex.join(run.get("cmd") or []),
                   phases=[[p["name"], p["func"]] for p in rec.get("phase_at") or []],
                   env=dict(run.get("env") or {}), timeout=rec.get("timeout"),
                   events=bool(rec.get("events")), note="", attach=list(rec.get("attach") or []),
                   tags=list(run.get("tags") or []), roots=rec.get("roots"), stop_grace=rec.get("stop_grace"))

    def validate(self, symbols: dict | None) -> None:
        """内容检查，错了就 ValueError（中文说明直接给页面看）。阶段用 trace 自己的 resolve_phase_at
        检查（和命令行 --phase 同一套规则，函数写错了现在就报、还带候选）——symbols 是仓库的静态索引
        （没 scan 过是 None：那样只能写 文件路径:函数）。别的（tag 的写法、附带文件在不在）交给 trace
        自己在任务输出里报，这里不重复它的逻辑"""
        if not CASE_RE.match(self.case):
            raise ValueError(f"case 名只能用字母、数字和 . _ -：{self.case!r}")
        try:
            words = shlex.split(self.command)
        except ValueError as e:
            raise ValueError(f"命令解析不了：{e}") from None
        if not words:
            raise ValueError("要给出命令（在仓库根目录执行，比如 python examples/demo.py）")
        if self.phases:
            try:
                resolve_phase_at(Path(self.repo), [f"{n}={f}" for n, f in self.phases], symbols)
            except SystemExit as e:
                raise ValueError(str(e)) from None
        if any("=" in k or not k.strip() for k in self.env):
            raise ValueError("环境变量名里不能有 =")
        for k, what in (("timeout", "超时"), ("stop_grace", "停止的宽限时间")):
            v = getattr(self, k)
            if v is not None and v <= 0:
                raise ValueError(f"{what}要大于 0 秒")

    def argv(self) -> list[str]:
        """拼成 codestrata trace 的命令行。值一律写成 --x=值：以 - 开头的值不会被当成选项"""
        a = ["trace", self.repo, f"--case={self.case}"]
        if self.events:
            a.append("--events")
        if self.timeout is not None:
            a.append(f"--timeout={fmt_seconds(self.timeout)}")
        if self.stop_grace is not None:
            a.append(f"--stop-grace={fmt_seconds(self.stop_grace)}")
        a += [f"--phase={n}={f}" for n, f in self.phases]
        a += [f"--env={k}={v}" for k, v in self.env.items()]
        a += [f"--attach={p}" for p in self.attach]
        a += [f"--tag={t}" for t in self.tags]
        if self.note:
            a.append(f"--note={self.note}")
        if self.roots is not None:
            a += ["--roots", *self.roots]           # nargs=*：只能一个个跟在后面（目录名不会以 - 开头）
        return _cli(*a, "--", *shlex.split(self.command))

    def to_json(self) -> dict:
        return asdict(self)


class JobError(Exception):
    """任务起不来：说明直接给页面看"""


class Busy(JobError):
    """同一个仓库已经有任务在跑"""


@dataclass
class Job:
    id: str
    kind: str                     # "scan" | "trace"
    repo: str
    argv: list
    started: float
    proc: subprocess.Popen = field(repr=False)
    lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LINES), repr=False)
    n: int = 0                    # 一共收到过多少行（lines 只留最后 MAX_LINES 行）
    ended: float | None = None
    returncode: int | None = None
    stopping: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)   # 护着 lines 和 n

    @property
    def running(self) -> bool:
        return self.ended is None

    def add(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
            self.n += 1

    def snapshot(self, since: int = 0) -> dict:
        """给页面轮询：第 since 行之后的新输出（行号从 0 数；早于内存里最早一行的就从最早一行给）"""
        with self._lock:
            n, lines = self.n, list(self.lines)
        first = n - len(lines)
        start = max(since, first)
        return {"id": self.id, "kind": self.kind, "repo": self.repo, "cmd": shlex.join(self.argv),
                "started": self.started, "ended": self.ended, "running": self.running,
                "returncode": self.returncode, "stopping": self.stopping,
                "from": start, "n": n, "lines": lines[start - first:]}


class JobManager:
    """起任务、收输出、停任务。on_done(job) 在命令退出之后、任务标成结束之前调用：它做的事
    （比如扫描完重启图服务）算在任务里——页面看到「完成」时它已经做完了，同一个仓库也起不了新任务；
    它可以用 job.add() 往输出里写一行说明"""

    def __init__(self, on_done=None):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._on_done = on_done

    def active(self, repo: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values() if j.repo == repo and j.running), None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def for_repo(self, repo: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.repo == repo]

    def start(self, kind: str, repo: str, argv: list[str]) -> Job:
        """起一个任务。同一个仓库已经有任务在跑：Busy；命令起不来（比如仓库目录没了）：JobError"""
        with self._lock:
            if any(j.repo == repo and j.running for j in self._jobs.values()):
                raise Busy(f"{repo} 已经有任务在跑，等它结束或先停掉")
            try:
                # 自己一个会话：停止时 SIGINT 只发给 codestrata（trace 会按三级顺序停掉被录的命令，
                # 把 run 收好），不会连带打到主菜单
                proc = subprocess.Popen(argv, cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as e:
                raise JobError(f"起不来：{e.strerror}（{repo}）") from None
            job = Job(id=str(next(self._ids)), kind=kind, repo=repo, argv=argv, started=time.time(), proc=proc)
            self._prune(repo)
            self._jobs[job.id] = job
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    def _prune(self, repo: str) -> None:
        """这个仓库已经结束的任务只留最近 KEEP_DONE 个（调用方拿着 self._lock）"""
        done = sorted((j for j in self._jobs.values() if j.repo == repo and not j.running), key=lambda j: j.started)
        for j in done[:max(0, len(done) - KEEP_DONE)]:
            del self._jobs[j.id]

    def _pump(self, job: Job) -> None:
        for raw in job.proc.stdout:
            job.add(raw.decode("utf-8", errors="replace").rstrip("\n"))
        job.returncode = job.proc.wait()
        if self._on_done:
            try:
                self._on_done(job)
            except Exception as e:                # noqa: BLE001 —— 回调出错不能让任务一直「在跑」
                job.add(f"[codestrata app] 任务结束后的处理出错：{e}")
        job.ended = time.time()

    def stop(self, job_id: str) -> bool:
        """发 SIGINT（和在终端里按 Ctrl+C 一样）。已经结束了就返回 False"""
        job = self.get(job_id)
        if not job or not job.running:
            return False
        job.stopping = True
        try:
            job.proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return False
        return True

    def stop_all(self, grace: float = 120.0) -> None:
        """主菜单退出时：还在跑的都停掉。先 SIGINT，给 grace 秒收尾——trace 自己停被录的命令最多要
        stop_grace（默认 90 秒），再把 run 打包；到时间还没退才 SIGKILL"""
        with self._lock:
            live = [j for j in self._jobs.values() if j.running]
        for j in live:
            self.stop(j.id)
        deadline = time.time() + grace
        for j in live:
            try:
                j.proc.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                j.proc.kill()
