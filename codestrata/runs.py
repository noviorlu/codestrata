"""运行记录（run）：一次 trace 的全部产物。录一次，永久复用。

静态分析（.codestrata/index.json、symbols.json、xref.json）只有一份，随时 scan 重建；
run 不能重建——一次录制往往要几分钟 GPU（起服务、加载模型、跑一段对话）。所以：

  - 每次 trace 都是一个新目录 .codestrata/runs/<id>/，id = 录制时刻 + case 名。同名 case
    重录不覆盖旧的：今天录 MiniCPM、明天录 Qwen，两份都留着，随时叠到图上。
  - run 目录里分两类东西。原始数据——录制时才拿得到的：parts.tar.gz（各进程写出的分片）、
    files/（case 脚本、命令里提到的配置文件）、legacy/（迁移来的老文件）、run.json 和
    detail.json 里录制时写下的字段；finalize 之后不再改。派生数据——counts.json.gz：
    合并 parts 得到的调用计数，合并逻辑改了可以用 `runs merge` 从原始数据重算。
  - 除了 `runs rm`，没有代码会删 run。scan 不碰 runs/；runs/ 可以是软链（比如指到 /mnt/data），
    `rm -rf .codestrata` 只删掉链接本身。
  - run 只存原始键（文件:首行号）和录制时实际执行的文件的哈希，加载时现映射到当前的
    index 上（align.py），所以代码改了之后老 run 照样能用；哪些文件在录制
    之后改过，逐个标出来（file_state），而不是让整个 run 作废。
  - 录了时序事件的（trace 默认录，被录的 Python 3.12+）：原始日志在 events/raw.tar.gz（原始数据），整理好的 span
    在 events/spans/（派生，见 events.py）。`runs rm --events-only` 只删这一块。

数据格式见 docs/design/run-format.md，设计决策见 docs/design/decisions.md。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from . import align as _align
from . import compat as _compat
from . import events as _events
from . import kernels as _kernels
from . import seq as _seq
from .trace import analysis as _tana
from .trace import driver as _tdrv

SCHEMA = 3
CASE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_TEXT_EXTS = (".sh", ".bash", ".py", ".yaml", ".yml", ".json", ".toml")
_FILE_MAX = 200_000          # 自动存下的文本文件（case 脚本、命令里提到的配置）的大小上限
_MIGRATED: set[str] = set()  # 这个进程里已经检查过迁移的仓库


# ---------------------------------------------------------------- 小工具

def has_runs(repo: Path) -> bool:
    """录过没有：只看 .codestrata/runs 在不在（是软链也算，指向的盘没挂上时 catalog 会报出来）。
    不像 runs_dir 那样顺手建目录——只是看一眼状态的地方（主菜单的项目卡片）不该往仓库里写东西"""
    return os.path.lexists(Path(repo) / ".codestrata" / "runs")


def fmt_seconds(x: float) -> str:
    """秒数写进命令行：整数就不带小数点（900 而不是 900.0），别的原样（不像 :g 会把大数截成 6 位有效数字）"""
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def runs_dir(repo: Path) -> Path:
    d = Path(repo) / ".codestrata" / "runs"
    if not d.is_dir():
        if d.is_symlink():
            raise SystemExit(f"{d} 是软链，但指向的目录不在（{os.readlink(d)}）：盘没挂上？")
        d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, obj, gz: bool = False) -> None:
    """原子写：先写临时文件再 rename，读的一方（serve）永远看不到写了一半的文件。
    命令行里不是 UTF-8 的字节（Python 里是孤立的代理字符）写成 \\udcXX 转义——仍是合法 JSON。"""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":") if gz else None,
                      indent=None if gz else 1).encode("utf-8", "backslashreplace")
    try:
        with open(tmp, "wb") as f:
            f.write(gzip.compress(data, mtime=0) if gz else data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, gz: bool = False):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if gz else raw)


def sha16(p: Path) -> str:
    """和 trace.file_shas 同一种哈希，scan 的 file_sha 也是它：三边能直接比。"""
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""




def _alive(driver: dict | None) -> bool:
    if not driver or not driver.get("pid"):
        return False
    st = _tdrv.proc_start(driver["pid"])
    return st is not None and (driver.get("start") is None or st == driver["start"])


def live(run: dict) -> bool:
    """还在录：状态是 recording、driver 还是当初那个进程。"""
    return run.get("status") == "recording" and _alive(run.get("driver"))


def git_info(repo: Path) -> tuple[dict | None, list[str]]:
    """({commit, branch, n_dirty}, 改动中的文件)。不是 git 仓库（duplex-agents 就不是）时 (None, [])。"""
    def g(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    try:
        commit = g("rev-parse", "HEAD")
        if not commit:
            return None, []
        branch = g("rev-parse", "--abbrev-ref", "HEAD") or None
        dirty = [ln[3:] for ln in g("status", "--porcelain").splitlines() if ln][:200]
        return {"commit": commit, "branch": None if branch == "HEAD" else branch, "n_dirty": len(dirty)}, dirty
    except (OSError, subprocess.SubprocessError):
        return None, []


def _gpu() -> list | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    gpus = []
    for ln in out.stdout.splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) == 4:
            gpus.append({"index": int(p[0]), "name": p[1], "driver": p[2],
                         "mem_mib": int(float(p[3])) if p[3].replace(".", "").isdigit() else None})
    return gpus


def _dists(site_dirs) -> dict:
    """site-packages 里装了哪些包、什么版本（看 *.dist-info 目录名就够，不 import 任何东西）。"""
    out: dict[str, str] = {}
    for d in site_dirs or []:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.endswith(".dist-info"):
                stem = n[:-len(".dist-info")]
                name, _, ver = stem.rpartition("-")
                if name:
                    out.setdefault(name.replace("_", "-").lower(), ver)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- 录制：建目录、收尾

def new_run(repo: Path, *, case: str, cmd: list[str], cwd: Path, env: dict | None = None,
            tags: list[str] | None = None, note: str = "", rec: dict | None = None,
            invocation: dict | None = None, env_inherited: dict | None = None) -> Path:
    """建一个新的 run 目录（状态 recording）并返回它；各进程往 <run>/parts 里写。
    rec 是录制参数（timeout、stop_grace、attach、events、phase_at），老 run 没存原始命令时拼复刻命令用。
    invocation 是原样的 codestrata 命令 {argv, cwd}；env_inherited 是录制时 shell 里的相关环境变量
    （见 inherited_env）——两者合起来才能复刻：命令里的 --env 只是一部分，命令也会继承 shell 的环境。"""
    if not CASE_RE.match(case or ""):
        raise SystemExit(f"case 名只能用字母、数字和 . _ -：{case!r}")
    base = runs_dir(repo)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rid, k = f"{stamp}-{case}", 1
    while True:
        try:
            (base / rid).mkdir()
            break
        except FileExistsError:                   # 同一秒又录了一次
            k += 1
            rid = f"{stamp}-{case}-{k}"
    rd = base / rid
    try:
        git, _ = git_info(repo)
        _write(rd / "run.json", {
            "schema": SCHEMA, "id": rid, "case": case, "status": "recording", "problems": [],
            "driver": {"pid": os.getpid(), "start": _tdrv.proc_start(os.getpid())},
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": socket.gethostname(),
            "cmd": list(cmd), "cwd": str(cwd), "env": dict(env or {}), "git": git,
            "clock": {"mono0_ns": time.monotonic_ns(), "wall0": time.time()},
            "rec": dict(rec or {}), "tags": list(tags or []), "note": note or "",
            "invocation": invocation, "env_inherited": dict(env_inherited or {})})
        (rd / "parts").mkdir()
    except BaseException:
        shutil.rmtree(rd, ignore_errors=True)      # 还什么都没录：不留一个 ls 看不见的空目录
        raise
    return rd


def _collect_files(repo: Path, cwd: Path, procs: list[dict], script: dict | None,
                   attach: list[str]) -> list[dict]:
    """录制时顺手存下的文本文件：case 脚本、任何进程的命令行里出现的小配置文件
    （vllm-omni 的 --deploy-config 指的 yaml 就在这里）、--attach 点名的文件（被 source 的
    common.sh 不会出现在命令行里）。这些文件以后会改，run 里存的是录制时的样子。"""
    seen: dict[str, dict] = {}

    def add(path_str: str, why: str):
        p = Path(path_str)
        if not p.is_absolute():
            p = (cwd / p)
        try:
            p = p.resolve()
            # 自动收集的有大小上限；--attach 点名要的不限
            if not p.is_file() or (why != "attach" and p.stat().st_size > _FILE_MAX):
                return
        except OSError:
            return
        # 命令行里安装包中的 .py 不存：那是被当程序起的第三方代码（py-cpuinfo 会
        # python .../site-packages/cpuinfo/cpuinfo.py 自己起自己），版本已经记在 dists 里。
        # 安装包里的配置（非 editable 安装时 --deploy-config 指的 yaml）照存
        if why == "argv" and p.suffix == ".py" and any(sp in str(p) for sp in ("/site-packages/", "/dist-packages/")):
            return
        key = str(p)
        if key in seen or (why != "attach" and len(seen) >= 40):
            return
        seen[key] = {"path": path_str, "abs": key, "why": why}

    if script:
        add(script["path"], "script")
    for a in attach or []:
        add(a, "attach")
    for pr in procs:
        for a in (pr.get("argv") or [])[1:]:
            for piece in a.split("=", 1)[-1:]:     # --deploy-config=x.yaml 也认
                if piece.endswith(_TEXT_EXTS) and not piece.startswith("-"):
                    add(piece, "argv")
    return list(seen.values())


def _procs_of(tr: dict, mono0: int | None) -> list[dict]:
    rel_us = (lambda t: None if t is None or mono0 is None else max(0, (t - mono0) // 1000))
    return [{"pid": p.get("pid"), "ppid": p.get("ppid"), "argv": p.get("argv"),
             "argv_cut": bool(p.get("argv_cut")), "title": p.get("title"),
             "n_funcs": p.get("n_funcs", 0), "t0_us": rel_us(p.get("t0")), "t1_us": rel_us(p.get("t")),
             "why": p.get("why"), "py": (p.get("py") or {}).get("executable")}
            for p in tr.get("procs") or []]


def capture(repo: Path, rd: Path, tr: dict, run: dict, *, leftovers: list | None = None,
            attach: list[str] | None = None, late: bool = False) -> dict:
    """录制时才拿得到的东西，写进 detail.json 和 files/，只写这一次（runs merge 不重写）：
    实际执行的文件的哈希、安装包和仓库是否一致、Python 和包版本、GPU、git 改动、case 脚本和
    配置文件的副本、残留进程。late=True 表示录制的 driver 死了、现在才补（runs merge）。"""
    repo = Path(repo)
    cwd = Path(run.get("cwd") or repo)
    mapped = tr.get("mapped") or {}
    rels = sorted({k.rpartition(":")[0] for ph in tr["phases"].values() for k in ph["funcs"]})
    # 哈希取 hook 在进程第一次跑到这个文件时算的（执行的就是它）；老的分片没有，退回现在磁盘上的
    hook = tr.get("shas") or {}
    now = {rel: sha16(Path(mapped[rel]) if rel in mapped else repo / rel) for rel in rels}
    file_shas = {rel: hook.get(rel) or now[rel] for rel in rels}
    during = sorted(rel for rel in rels if hook.get(rel) and now[rel] and hook[rel] != now[rel])
    mismatch, only_inst = [], []
    for rel, real in mapped.items():
        if not (repo / rel).is_file():
            only_inst.append(rel)         # 构建时生成的文件（_version.py）：不是「不一致」
        elif (hook.get(rel) or sha16(Path(real))) != sha16(repo / rel):
            mismatch.append(rel)

    pythons = {}
    for p in tr.get("procs") or []:
        py = p.get("py") or {}
        exe = py.get("executable")
        if exe and exe not in pythons:
            pythons[exe] = {"version": py.get("version"), "dists": _dists(py.get("site"))}

    procs = _procs_of(tr, (run.get("clock") or {}).get("mono0_ns"))
    script = _tana.case_script(cwd, run.get("cmd") or [])
    files = _collect_files(repo, cwd, procs, script, attach or [])
    (rd / "files").mkdir(exist_ok=True)
    stored = []
    for i, f in enumerate(files):
        dst = rd / "files" / f"{i:02d}-{Path(f['abs']).name}"
        try:
            shutil.copyfile(f["abs"], dst)
        except OSError:
            continue
        stored.append({"path": f["path"], "sha": sha16(dst), "stored": f"files/{dst.name}", "why": f["why"]})
    missing = [a for a in attach or [] if not any(x["why"] == "attach" and x["path"] == a for x in stored)]
    script_rec = None
    if script:
        sc = next((x for x in stored if x["why"] == "script"), None)
        script_rec = {"path": script["path"], "stored": sc["stored"] if sc else None}
    _, dirty = git_info(repo)
    detail = {
        "sha_of": "executed", "file_shas": file_shas,
        "sha_late": sorted(rel for rel in rels if not hook.get(rel)),     # 这些是收尾时才取的
        "changed_during": during, "sha_conflicts": tr.get("sha_conflicts") or [],
        "mapped_from": os.path.commonpath(list(mapped.values())) if mapped else None,
        "mapped": mapped, "mapped_mismatch": sorted(mismatch), "mapped_only_installed": sorted(only_inst),
        "procs": procs, "leftovers": leftovers or [], "pythons": pythons, "gpu": _gpu(),
        "git": {"dirty": dirty}, "script": script_rec, "files": stored, "attach_missing": missing,
        "captured": "late" if late else "finalize"}
    _write(rd / "detail.json", detail)
    return detail


def _is_event_log(p: Path) -> bool:
    return p.name.startswith("ev-") and p.name.endswith(".log")


def _pack(dst: Path, members: list[Path]) -> bool:
    """把 members 打包成 dst（tar.gz）：先写临时包、重新打开核对成员数，再替换。
    不会用成员更少的包替换已有的包。"""
    members = sorted(members)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
    try:
        if dst.is_file():
            with tarfile.open(dst, "r:gz") as tf:
                if len(tf.getmembers()) > len(members):
                    return False
        with tarfile.open(tmp, "w:gz") as tf:
            for p in members:
                tf.add(p, arcname=p.name)
        with tarfile.open(tmp, "r:gz") as tf:
            if len(tf.getmembers()) != len(members):
                return False
        os.replace(tmp, dst)
        return True
    except (OSError, tarfile.TarError):
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _pack_all(rd: Path, src: Path) -> bool:
    """src 下的原始数据分两个包：各进程的分片 → parts.tar.gz，时序事件日志 → events/raw.tar.gz。"""
    files = [p for p in src.iterdir() if p.is_file() and not p.name.endswith(".tmp")]
    ev = [p for p in files if _is_event_log(p)]
    ok = _pack(rd / "parts.tar.gz", [p for p in files if not _is_event_log(p)])
    if ev:
        ok = _pack(rd / "events" / "raw.tar.gz", ev) and ok
    return ok


def _load_kernels(repo: Path, src: Path, run: dict, tr: dict):
    """src 下有 GPU 日志（trace --gpu）：kernels.Gpu，没有是 None。kernel 的次数和 GPU 时间（按发起的时刻落进阶段）
    当场加进 tr 的 phases / names——只看 cu 日志，时序事件没有、截断了、整理失败都不影响（录制收尾和 runs merge 每次都从
    分片重算 tr，所以加一次不会重复）。调用边要等 events.build 重放完，见 _build_events"""
    cu = sorted(p for p in src.iterdir() if p.is_file() and _kernels.is_log(p))
    if not cu:
        return None
    sym_path = Path(repo) / ".codestrata" / "symbols.json"
    symbols = (read_json(sym_path).get("symbols") or {}) if sym_path.is_file() else {}
    segs = _seq.phase_segments(run, float("inf"))
    names = list(tr["phases"]) or ["start"]

    def phase_at(t: int) -> str:
        return next((n for n, a, b in reversed(segs) if a <= t), names[0])

    g = _kernels.Gpu(cu, (run.get("clock") or {}).get("mono0_ns"), _kernels.resolver(symbols), phase_at)
    _add_counts(tr, g.counts())
    tr["names"] = {**(tr.get("names") or {}), **g.names}
    return g


def _add_counts(tr: dict, phases: dict) -> None:
    for ph, c in phases.items():
        dst = tr["phases"].setdefault(ph, {"funcs": {}, "func_edges": {}})
        for part, xs in c.items():
            d = dst.setdefault(part, {})
            for k, n in xs.items():
                d[k] = d.get(k, 0) + n


def _build_events(repo: Path, rd: Path, src: Path, run: dict, tr: dict) -> tuple[dict | None, dict | None]:
    """src 下有事件日志就整理成 span（派生数据，写 events/spans/）。返回 (run.json 的 events 摘要, gpu 摘要)。
    在打包之后调（原始日志先落进 events/raw.tar.gz）；整理失败只记下来，不耽误计数——之后可以 runs merge 重来。
    有 GPU 日志的：kernel 的次数先加进 tr（_load_kernels）；重放事件时按真实的栈找到调用方的，整理成功之后再把调用边加进 tr"""
    g = _load_kernels(repo, src, run, tr)
    ev = sorted(p for p in src.iterdir() if p.is_file() and _is_event_log(p))
    if not ev:
        return None, (g.summary() if g else None)
    raw = rd / "events" / "raw.tar.gz"
    size = raw.stat().st_size if raw.is_file() else None      # 一律是压缩包的大小
    try:
        idx = _events.build(ev, (run.get("clock") or {}).get("mono0_ns"), rd / "events" / "spans", gpu=g)
    except Exception as e:                                     # noqa: BLE001 —— 派生数据，失败了能重来
        return {"error": f"{type(e).__name__}: {e}"[:300], "bytes": size}, (g.summary() if g else None)
    if g:
        _add_counts(tr, g.edges)
    return ({"n_lines": idx["n_lines"], "n_spans": idx["n_spans"], "n_calls": idx["n_calls"], "scope": idx.get("scope"),
             "truncated": idx["truncated"], "n_procs": len({p["pid"] for p in idx["procs"]}), "bytes": size},
            g.summary() if g else None)


def derive(repo: Path, rd: Path, tr: dict, run: dict, detail: dict, *, packed: bool,
           events: dict | None = None, gpu: dict | None = None) -> dict:
    """派生数据：计数、各阶段、状态。录制收尾和 runs merge 都走这里；录制时的数据
    （detail 里除 procs 以外的字段、files/）不动。gpu 是 trace --gpu 的摘要（kernels.Gpu.summary），写进 run.json 的 gpu"""
    phases = tr["phases"]
    _write(rd / "counts.json.gz", {"phases": phases, "names": tr.get("names") or {}}, gz=True)
    detail = {**detail, "procs": _procs_of(tr, (run.get("clock") or {}).get("mono0_ns"))}
    _write(rd / "detail.json", detail)
    procs = detail["procs"]
    stop, returncode = run.get("stop"), run.get("returncode")
    leftovers = detail.get("leftovers") or []
    # 最后一次落盘是定时的（或切阶段时的）：之后被强杀了，最后几秒的数据没了
    unclean = [p["pid"] for p in procs if p.get("why") in ("periodic", "phase")]
    n_funcs = len({k for ph in phases.values() for k in ph["funcs"]})
    problems = []
    if stop == "timeout":
        problems.append("超时")
    elif stop == "interrupt":
        problems.append("被中断")
    elif stop == "driver-lost":
        problems.append("录制的进程中途没了")
    if returncode not in (0, None) and stop == "exit":
        problems.append(f"命令退出码 {returncode}")
    if unclean:
        problems.append(f"{len(unclean)} 个进程被强杀（最后几秒的数据可能缺）")
    if leftovers:
        problems.append(f"{len(leftovers)} 个残留进程被停掉")
    if tr.get("bad_parts"):
        problems.append(f"{len(tr['bad_parts'])} 个分片读不出来（这些进程的数据缺了）")
    if detail.get("changed_during") or detail.get("sha_conflicts"):
        n = len(set(detail.get("changed_during") or []) | set(detail.get("sha_conflicts") or []))
        problems.append(f"{n} 个文件在录制过程中被改过")
    # 时序事件到了行数上限、或整理失败，都不算进 status：计数是完整的，拿 case 名解析时不该因此
    # 跳到更早的一次；events 摘要里有 truncated / error，runs show 会说
    status = ("failed" if n_funcs == 0 else
              "ok" if not problems and returncode == 0 and stop == "exit" else "partial")
    if not packed:
        status = "recording"
        problems.append("parts 没打包成功，用 codestrata runs <repo> merge <id> 重来")

    t_of: dict = {}
    for e in run.get("phase_log") or []:         # 同一个阶段名出现多次（切回去了）：取第一次的时刻
        t_of.setdefault(e[0], e[1])
    order = list(dict.fromkeys([*t_of, *phases]))
    run.pop("status_shown", None)
    if events is not None:
        run["events"] = events
    run.setdefault("events", None)
    if gpu is not None:
        run["gpu"] = gpu
    run.update({
        "status": status, "problems": problems,
        "phases": [{"name": n, "t_us": t_of.get(n), "n_funcs": len(phases[n]["funcs"]),
                    "n_calls": sum(phases[n]["funcs"].values())} for n in order if n in phases],
        "summary": {"n_funcs": n_funcs,
                    "n_func_edges": len({k for ph in phases.values() for k in ph["func_edges"]}),
                    "n_files": len(detail.get("file_shas") or {}), "n_procs": len(procs),
                    "n_procs_active": sum(1 for p in procs if p["n_funcs"]),
                    "n_mapped": len(detail.get("mapped") or {}), "n_leftovers": len(leftovers),
                    "n_unclean": len(unclean)},
        "sizes": {p.name: p.stat().st_size for p in rd.iterdir() if p.is_file()},
    })
    _write(rd / "run.json", run)
    return run


def finalize(repo: Path, rd: Path, tr: dict, *, stop: str, returncode: int | None,
             phase_times: list | None, duration_s: float | None, leftovers: list | None = None,
             attach: list[str] | None = None) -> dict:
    """录制结束：存录制时的数据（capture），把 parts 打包，算派生数据和状态（derive）。
    打包失败时保留 parts/、状态留在 recording，之后可以 `runs merge` 重来；包已经替换好、
    只是 parts/ 没删干净的，不算失败（merge 会把两边合起来，不会拿少的盖多的）。"""
    run = read_json(rd / "run.json")
    run.update({"stop": stop, "returncode": returncode,
                "duration_s": round(duration_s, 1) if duration_s is not None else None,
                "phase_log": [list(x) for x in phase_times or []]})
    _write(rd / "run.json", run)
    detail = (read_json(rd / "detail.json") if (rd / "detail.json").is_file() else
              capture(repo, rd, tr, run, leftovers=leftovers, attach=attach))
    parts = rd / "parts"
    packed, events, gpu = True, None, None
    if parts.is_dir():
        packed = _pack_all(rd, parts)             # 原始数据先落包，再整理派生的 span
        events, gpu = _build_events(repo, rd, parts, run, tr)
        if packed:
            shutil.rmtree(parts, ignore_errors=True)
    return derive(repo, rd, tr, run, detail, packed=packed, events=events, gpu=gpu)


# ---------------------------------------------------------------- 迁移老的 trace-<case>.json

def migrate(repo: Path) -> list[str]:
    """把老的 .codestrata/trace-<case>.json（每个 case 只有一份，重录就被覆盖）搬进 runs/。
    幂等、可以并发（加文件锁串行）：id 由老文件的修改时间决定；先在 .tmp-<id>/ 里建好、
    逐键核对计数，整个 rename 成 <id>/，最后才删老文件——老文件逐字节压在 legacy/ 里，
    原始数据一份不丢。返回迁移了的 run id。"""
    repo = Path(repo)
    cs = repo / ".codestrata"
    base = runs_dir(repo)
    if not any(cs.glob("trace-*.json")) and not any(base.glob(".tmp-*")):
        return []
    # 整个迁移串行：同时起的几个 serve / runs ls 排队，后来的看到 run 已经在了就跳过。
    # 锁随进程释放，所以持锁时还在的 .tmp-* 一定是上次迁到一半死掉留下的
    with open(base / ".migrate.lock", "a") as lk, _compat.file_lock(lk):
        return _migrate_locked(repo, cs, base)


def _migrate_locked(repo: Path, cs: Path, base: Path) -> list[str]:
    # 持锁时还在的 .tmp-*：上次迁到一半死掉了。老文件一直留在原处（只拷不挪），删掉重来
    for tmp in base.glob(".tmp-*"):
        shutil.rmtree(tmp, ignore_errors=True)
    done = []
    for old in sorted(cs.glob("trace-*.json")):
        case = old.name[len("trace-"):-len(".json")]
        # 老版本不限制 case 名（可能有中文、+ 之类）：目录名用清洗过的，run.json 里仍是原名，
        # --hot 原名照样能找到
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", case) or "case"
        rid = time.strftime("%Y%m%d-%H%M%S", time.localtime(old.stat().st_mtime)) + f"-{safe}"
        final = base / rid
        if final.exists():
            # 上次落位之后、删老文件之前死掉了：核对 legacy 里那份和老文件一样，再把收尾做完
            _cleanup_legacy(cs, final, old, case)
            continue
        try:
            tr = json.loads(old.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tmp = base / f".tmp-{rid}"
        tmp.mkdir()
        try:
            phases = tr.get("phases") or {"start": {"funcs": tr.get("funcs") or {},
                                                     "func_edges": tr.get("func_edges") or {}}}
            _write(tmp / "counts.json.gz", {"phases": phases, "names": {}}, gz=True)
            # 核对：全部、每个阶段都要和老文件逐键相等
            back = read_json(tmp / "counts.json.gz", gz=True)["phases"]
            tot = _sum(back)
            ok = (tot["funcs"] == (tr.get("funcs") or tot["funcs"])
                  and tot["func_edges"] == (tr.get("func_edges") or tot["func_edges"])
                  and all(back[n] == phases[n] for n in phases))
            if not ok:
                print(f"[codestrata] 迁移 {old.name} 时计数核对不上，保留老文件、跳过", file=sys.stderr)
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            procs = [{"pid": p.get("pid"), "ppid": p.get("ppid"), "argv": p.get("argv"),
                      # 老版本只存了 sys.argv 的前 6 个、也没有 ppid：标出来，免得以为命令就这么长
                      "argv_cut": "ppid" not in p and len(p.get("argv") or []) >= 6,
                      "n_funcs": p.get("n_funcs", 0), "t0_us": None, "t1_us": None, "why": None, "py": None}
                     for p in tr.get("pids") or []]
            (tmp / "files").mkdir()
            script_rec = None
            if tr.get("script"):
                name = "00-" + Path(tr["script"]["path"]).name
                (tmp / "files" / name).write_text(tr["script"]["text"], encoding="utf-8")
                script_rec = {"path": tr["script"]["path"], "stored": f"files/{name}"}
            _write(tmp / "detail.json", {
                "sha_of": "repo", "file_shas": tr.get("file_shas") or {},
                "mapped_from": tr.get("mapped_from"), "mapped": tr.get("mapped") or {},
                "mapped_mismatch": tr.get("mapped_mismatch") or [],
                "mapped_only_installed": tr.get("mapped_only_installed") or [],
                "procs": procs, "leftovers": [], "pythons": {}, "gpu": None, "git": {"dirty": []},
                "script": script_rec, "files": []})
            rc = tr.get("returncode")
            n_funcs = len({k for ph in phases.values() for k in ph["funcs"]})
            _write(tmp / "run.json", {
                "schema": SCHEMA, "id": rid, "case": case,
                "status": "ok" if rc == 0 else ("failed" if n_funcs == 0 else "partial"),
                "problems": [] if rc == 0 else [f"命令退出码 {rc}"], "stop": "exit", "returncode": rc,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(old.stat().st_mtime)),
                "host": None, "cmd": tr.get("cmd") or [], "cwd": tr.get("cwd") or str(repo), "env": {},
                "git": None, "clock": None, "duration_s": None, "tags": [], "note": "",
                "phases": [{"name": n, "t_us": None, "n_funcs": len(v["funcs"]),
                            "n_calls": sum(v["funcs"].values())} for n, v in phases.items()],
                "summary": {"n_funcs": n_funcs, "n_procs": len(procs),
                            "n_procs_active": sum(1 for p in procs if p["n_funcs"]),
                            "n_mapped": len(tr.get("mapped") or {})},
                "migrated_from": old.name})
            # 老文件原样压进 legacy/，parts-<case>/ 打包。只拷不挪：runs/ 常常是指到另一块盘的
            # 软链，跨盘没法 rename；新 run 整个落位之后才删老文件
            (tmp / "legacy").mkdir()
            (tmp / "legacy" / (old.name + ".gz")).write_bytes(gzip.compress(old.read_bytes(), mtime=0))
            parts = cs / f"parts-{case}"
            if parts.is_dir():
                with tarfile.open(tmp / "parts.tar.gz", "w:gz") as tf:
                    for p in sorted(p for p in parts.iterdir() if p.is_file()):
                        tf.add(p, arcname=p.name)
            os.replace(tmp, final)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        done.append(rid)
        print(f"[codestrata] 老的 {old.name} 已迁成 run {rid}（在 {base.resolve()}）", file=sys.stderr)
        _cleanup_legacy(cs, final, old, case)
    return done


def _cleanup_legacy(cs: Path, final: Path, old: Path, case: str) -> None:
    """迁移的最后一步：run 里的 legacy 副本逐字节和老文件相同、parts 打包的成员齐全，才删老的。"""
    try:
        run = read_json(final / "run.json")
        if run.get("migrated_from") != old.name:
            return
        if gzip.decompress((final / "legacy" / (old.name + ".gz")).read_bytes()) != old.read_bytes():
            print(f"[codestrata] {old.name} 和 run {final.name} 里的副本不一样，保留老文件", file=sys.stderr)
            return
        parts = cs / f"parts-{case}"
        if parts.is_dir():
            names = sorted(p.name for p in parts.iterdir() if p.is_file())
            tb = final / "parts.tar.gz"
            if not tb.is_file():
                return
            with tarfile.open(tb, "r:gz") as tf:
                if sorted(m.name for m in tf.getmembers()) != names:
                    return
            shutil.rmtree(parts)
        old.unlink()
    except (OSError, ValueError, tarfile.TarError):
        return


# ---------------------------------------------------------------- 读：列表、解析、加载

def catalog(repo: Path) -> list[dict]:
    """所有 run 的 run.json，新的在前。第一次调用时顺带迁移老文件。"""
    repo = Path(repo)
    key = str(repo.resolve())
    if key not in _MIGRATED:
        _MIGRATED.add(key)
        migrate(repo)
    out = []
    for d in sorted(runs_dir(repo).iterdir(), reverse=True):
        if d.name.startswith(".") or not (d / "run.json").is_file():
            continue
        try:
            r = read_json(d / "run.json")
        except (OSError, ValueError):
            continue
        if r.get("status") == "recording" and not _alive(r.get("driver")):
            r["status_shown"] = "中断"            # 录制的进程已经没了：可以 runs merge
        out.append(r)
    return out


def resolve(repo: Path, ref: str) -> tuple[dict, Path, str | None]:
    """REF := <完整 run id> | <case>，后面可以加 @阶段，或者 @t=起-止（微秒，时间轴上拖出来的时间段，
    要录了时序事件）。只写 case 时取它最新的一次 ok 的；一次 ok 都没有就取最新的 partial（并提示）。"""
    ref, _, phase = (ref or "").partition("@")
    runs = catalog(repo)
    hit = next((r for r in runs if r["id"] == ref), None)
    if hit is None:
        mine = [r for r in runs if r.get("case") == ref]
        hit = (next((r for r in mine if r.get("status") == "ok"), None)
               or next((r for r in mine if r.get("status") == "partial"), None)
               or (mine[0] if mine else None))
        if hit is not None and hit.get("status") != "ok":
            print(f"[codestrata] case {ref} 没有完整录完的 run，用的是 {hit['id']}（{hit.get('status')}）",
                  file=sys.stderr)
    if hit is None:
        have = ", ".join(sorted({r.get('case') for r in runs})) or "（还没有）"
        raise SystemExit(f"没有叫 {ref!r} 的 run 或 case；有的 case：{have}\n"
                         f"  录一个：codestrata trace <repo> --case {ref or 'NAME'} -- <命令>")
    rd = runs_dir(repo) / hit["id"]
    try:
        win = _seq.parse_window(phase)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    if phase and not win and phase not in {p["name"] for p in hit.get("phases") or []}:
        raise SystemExit(f"run {hit['id']} 里没有阶段 {phase!r}；有的是："
                         + ", ".join(p["name"] for p in hit.get("phases") or []))
    return hit, rd, phase or None


def _sum(phases: dict) -> dict:
    out: dict[str, dict] = {"funcs": {}, "func_edges": {}}
    for opt in ("func_lines", "gpu_us"):        # 只有有的 run 才有：调用行（09-30 起）、GPU 时间（trace --gpu）
        if any(opt in ph for ph in phases.values()):
            out[opt] = {}
    for ph in phases.values():
        for name, dst in out.items():
            for k, v in (ph.get(name) or {}).items():
                dst[k] = dst.get(k, 0) + v
    return out


def load_counts(rd: Path, phase: str | None, with_names: bool = False):
    """{funcs, func_edges, func_lines?}：某个阶段的，或全部阶段相加（和老 trace 的 funcs 同义）。func_lines 只有
    09-30 之后录的 run 才有（run.json 的 schema 3）。
    with_names=True 时返回 (计数, names)：names 是录制时记下的 键 → qualname（remap 用）。"""
    c = read_json(rd / "counts.json.gz", gz=True)
    phases = c["phases"]
    out = dict(phases[phase]) if phase else _sum(phases)
    return (out, c.get("names") or {}) if with_names else out


def file_state(repo: Path, idx: dict, detail: dict) -> dict[str, str]:
    """run 里每个文件相对当前 index 的状态，只返回不是 same 的：
      mismatch  录制时跑的安装包就和仓库不一致（计数对应的代码和 index 不是同一份）
      outside   不在 index 里（scan 排除了的 examples、只在安装包里的 _version.py）：不叠加、不算过期
      gone      index 和工作区里都没有了
      changed   录制之后改过（和 index 的 file_sha 比——叠加用的行号来自 index）
      unknown   这个 run 没存哈希
    index 是老的、没有 file_sha 时，退回和工作区比（trace.stale_files 的老办法）。"""
    files = idx.get("files") or {}
    now = idx.get("file_sha")
    was = detail.get("file_shas") or {}
    mism = set(detail.get("mapped_mismatch") or [])
    only = set(detail.get("mapped_only_installed") or [])
    out: dict[str, str] = {}
    fallback = None
    for rel, sha in was.items():
        if rel in mism:
            out[rel] = "mismatch"
        elif rel not in files:
            out[rel] = "outside" if (rel in only or (Path(repo) / rel).is_file()) else "gone"
        elif not sha:
            out[rel] = "unknown"
        elif now is not None:
            if now.get(rel) and now[rel] != sha:
                out[rel] = "changed"
        else:
            if fallback is None:
                fallback = set(_tana.stale_files(Path(repo), {"file_shas": was}))
            if rel in fallback:
                out[rel] = "changed"
    return out


def procs_grouped(procs: list[dict]) -> list[dict]:
    """被 trace 的进程按命令合并：[{argv, n, funcs, cut, title}]，跑到仓库代码多的在前。"""
    by: dict[tuple, dict] = {}
    for p in procs or []:
        k = tuple(p.get("argv") or [])
        d = by.setdefault(k, {"argv": list(k), "n": 0, "funcs": 0, "cut": bool(p.get("argv_cut")),
                              "title": p.get("title")})
        d["n"] += 1
        d["funcs"] += p.get("n_funcs") or 0
    return sorted(by.values(), key=lambda d: (-d["funcs"], -d["n"]))


def read_detail(rd: Path) -> dict:
    """run 的 detail.json；读不出来（老 run、文件坏了）是 {}"""
    try:
        return read_json(rd / "detail.json")
    except (OSError, ValueError):
        return {}


def overlay(idx: dict, counts: dict, names: dict, fs: dict) -> tuple[dict, list]:
    """一份计数（某个阶段的、时间段的、分列里一列的）放到当前的 index 上：(hot, 改过的文件里对不上的键)。
    录制之后改过的文件（fs，见 file_state）按 qualname 把键挪到函数现在的行号上，叠加才不会落到别的函数上；
    hot["keymap"] 是录制时的键 → 现在的（读 span 时用；不发给页面）"""
    counts, unmatched = _align.remap(counts, names, fs, idx)
    hot = _align.to_package_graph(counts, idx)
    hot["keymap"] = _align.key_mapper(names, fs, idx)
    return hot, unmatched


def load(repo: Path, idx: dict, ref: str | None) -> tuple[dict | None, dict | None]:
    """把一个 run（的某个阶段）映射到当前的 index 上：(hot, meta)。hot 和老的 trace 一样由
    align.to_package_graph 现算；meta 保留老的全部键（前端认它们），再加上 run 的信息。"""
    if not ref:
        return None, None
    run, rd, phase = resolve(repo, ref)
    if not (rd / "counts.json.gz").is_file():
        raise SystemExit(f"run {run['id']} 还没有计数：" + (
            "还在录制中" if _alive(run.get("driver")) else
            f"录制中断了，先 codestrata runs {repo} merge {run['id']}"))
    win = _seq.parse_window(phase)
    counts, names = load_counts(rd, None if win else phase, with_names=True)
    if win:                                      # 时间段：次数按这段时间里的时序事件现算（只有跨文件的调用）；
        try:                                     # 调用行按整个 run 记的比例摊（span 不记调用行）
            counts = _seq.window_counts(rd, run, *win, ref_lines=counts.get("func_lines"))
        except LookupError as e:
            raise SystemExit(str(e)) from None
        except (OSError, ValueError) as e:
            raise SystemExit(_seq.unreadable(e, run["id"])) from None
    detail = read_detail(rd)
    fs = file_state(repo, idx, detail)
    hot, unmatched = overlay(idx, counts, names, fs)
    hot["run"] = run["id"] + (f"@{phase}" if phase else "")     # 写明这份次数来自哪个 run（和阶段 / 时间段）
    hot["lines_approx"] = bool(win) and "func_lines" in counts     # 时间段：每行的次数是摊出来的
    script = None
    sc = detail.get("script")
    if sc and sc.get("stored") and (rd / sc["stored"]).is_file():
        script = {"path": sc["path"], "text": (rd / sc["stored"]).read_text(encoding="utf-8", errors="replace"),
                  "saved": True}
    else:                                        # 老的 run 没存脚本：读现在的文件，标明是现在的
        s = _tana.case_script(Path(run.get("cwd") or repo), run.get("cmd") or [])
        script = {**s, "saved": False} if s else None
    phases = run.get("phases") or []
    end = _seq.run_end(run, rd)
    meta = {"case": run.get("case"), "cmd": _redact_argv(run.get("cmd") or []), "phase": phase,
            # 和老的 trace 一样：只有一个阶段时是空的（前端据此判断「分没分阶段」）
            "phases": {p["name"]: p["n_funcs"] for p in phases} if len(phases) > 1 else {},
            "n_procs": (run.get("summary") or {}).get("n_procs"), "unmapped": hot.get("anon"),
            # 定义时的执行（import 时的模块顶层、class 语句的类体）：不是调用，和上面的分开说
            "defs": (hot.get("module_frames") or 0) + (hot.get("class_frames") or 0),
            # 录制之后改过或删掉的文件（前端的「⚠ 录制后有文件改过」）；安装包和仓库不一致的
            # 另有 mapped_mismatch 那句话，不算在这里
            "stale_files": sorted(r for r, s in fs.items() if s in ("changed", "gone")),
            "file_state": fs,
            "mapped_from": detail.get("mapped_from"), "n_mapped": len(detail.get("mapped") or {}),
            "mapped_mismatch": detail.get("mapped_mismatch") or [],
            "procs": [{**p, "argv": _redact_argv(p.get("argv") or [])} for p in procs_grouped(detail.get("procs"))],
            "script": script,
            "run_id": run["id"], "status": run.get("status"), "problems": run.get("problems") or [],
            "git": run.get("git"), "tags": run.get("tags") or [], "note": run.get("note") or "",
            "created": run.get("created"), "migrated_from": run.get("migrated_from"),
            # 改过的文件里按名字对不上的键（lambda、改了名的、老 run 没存名字的）：这些调用的叠加可能偏
            "unmatched": len(unmatched), "events": run.get("events"),
            # 记了调用行没有（2026-09-30 之前录的没有）：没有的话代码窗口不标运行时调到了谁，页面上说明
            "has_lines": "func_lines" in counts,
            # 复刻：命令（原样的，或老 run 按参数拼的）、录制时继承的环境、--phase 怎么切的、各阶段的时刻
            # 网页上的：--env 里像密钥的值隐去，完整的在 runs show
            "rerun": rerun_command(run, Path(repo), redact=True),
            "rerun_exact": bool((run.get("invocation") or {}).get("argv")),
            "rerun_redacted": rerun_command(run, Path(repo), redact=True) != rerun_command(run, Path(repo)),
            "rerun_env": rerun_command(run, Path(repo), with_env=True, redact=True) if run.get("env_inherited") else None,
            "env_inherited": {k: _scrub(v) for k, v in (run.get("env_inherited") or {}).items()},
            "phase_at": (run.get("rec") or {}).get("phase_at") or [],
            "phase_log": run.get("phase_log") or [],
            # 时间轴（页面上的阶段条）：到哪一刻为止、各阶段的一段段；选的是时间段时它的起止
            # （这时次数只有跨文件的调用）
            "end_us": end, "timeline": [list(s) for s in _seq.phase_segments(run, end)] if end else [],
            "window": list(win) if win else None}
    return hot, meta


# ---------------------------------------------------------------- 管理：标签、备注、删除、重算

def _update(rd: Path, fn) -> dict:
    run = read_json(rd / "run.json")
    fn(run)
    _write(rd / "run.json", run)
    return run


def set_tags(repo: Path, ref: str, tags: list[str], remove: bool = False) -> dict:
    _, rd, _ = resolve(repo, ref)

    def f(run):
        cur = [t for t in run.get("tags") or [] if not (remove and t in tags)]
        if not remove:
            cur += [t for t in tags if t not in cur]
        run["tags"] = cur
    return _update(rd, f)


def set_note(repo: Path, ref: str, text: str) -> dict:
    _, rd, _ = resolve(repo, ref)
    return _update(rd, lambda run: run.__setitem__("note", text))


def remove(repo: Path, run_id: str) -> str:
    """删掉一个 run。只认完整的 run id（case 名会解析到「最新一次录完的」，拿它删东西太危险）；
    还在录的不删。"""
    base = runs_dir(repo)
    rd = base / run_id
    if "/" in run_id or run_id.startswith(".") or not (rd / "run.json").is_file():
        raise SystemExit(f"没有 id 为 {run_id!r} 的 run（rm 只认完整的 run id，runs ls 里看）")
    run = read_json(rd / "run.json")
    if live(run):
        raise SystemExit(f"run {run_id} 还在录制中（pid {run['driver']['pid']}），不能删")
    shutil.rmtree(rd)
    return run_id


def remove_events(repo: Path, run_id: str) -> str:
    """只删一个 run 的时序事件（events/，原始日志和 span 都删），计数和其余数据留着。"""
    rd = runs_dir(repo) / run_id
    if "/" in run_id or run_id.startswith(".") or not (rd / "run.json").is_file():
        raise SystemExit(f"没有 id 为 {run_id!r} 的 run（rm 只认完整的 run id，runs ls 里看）")
    run = read_json(rd / "run.json")
    if live(run):
        raise SystemExit(f"run {run_id} 还在录制中，不能删")
    left = _tdrv.leftovers(rd / "parts") if (rd / "parts").is_dir() else []
    if left:                                  # 还有进程在写：删了它还会写新的日志进来
        raise SystemExit(f"还有进程属于这个 run、可能还在往 {rd / 'parts'} 里写：{left}，先停掉它们")
    shutil.rmtree(rd / "events", ignore_errors=True)
    # 录制中断、还没 merge 的 run：原始日志还散在 parts/ 里，一起删，否则下次 merge 又整理出来
    for p in (rd / "parts").glob("ev-*.log") if (rd / "parts").is_dir() else []:
        p.unlink(missing_ok=True)
    return _update(rd, lambda r: r.__setitem__("events", None))["id"]


def merge_run(repo: Path, ref: str) -> dict:
    """从原始数据重算派生数据（计数、各阶段、状态）。原始分片取 parts.tar.gz 和散着的 parts/
    的并集（录制中断、或收尾时 parts/ 没删干净），并集打包回去——不会拿少的盖多的。
    录制时的数据（detail.json、files/）已经有的不重写；driver 死在收尾之前、还没有的，现在补
    （标成 late）。录制的进程还活着、或还有进程属于这个 run 时拒绝。"""
    run, rd, _ = resolve(repo, ref)
    run = read_json(rd / "run.json")     # 不用 catalog 给的那份：它带着只用来显示的 status_shown，会被写回去
    if live(run):
        raise SystemExit(f"run {run['id']} 还在录制中（pid {run['driver']['pid']}）")
    parts = rd / "parts"
    left = _tdrv.leftovers(parts) if parts.is_dir() else []
    if left:
        raise SystemExit(f"还有进程属于这个 run、可能还在往 {parts} 里写：{left}，先停掉它们")
    tarball = rd / "parts.tar.gz"
    if not parts.is_dir() and not tarball.is_file():
        raise SystemExit(f"run {run['id']} 没有原始分片（迁移来的老 run），没法重算")
    tmp = rd / f".merge-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for tb in (tarball, rd / "events" / "raw.tar.gz"):
            if tb.is_file():
                with tarfile.open(tb, "r:gz") as tf:
                    if sys.version_info >= (3, 12):
                        tf.extractall(tmp, filter="data")
                    else:
                        tf.extractall(tmp)
        if parts.is_dir():                        # 散着的分片盖在包上面：同名的是同一份或更新的
            for f in parts.iterdir():
                if f.is_file() and not f.name.endswith(".tmp"):
                    shutil.copy2(f, tmp / f.name)
        tr = _tana.merge(tmp)
        if run.get("status") == "recording" and not run.get("stop"):
            run["stop"] = "driver-lost"
        # --phase 切的阶段：标记在包里，driver 死在收尾之前的 run 也能把时刻补回来
        run["phase_log"] = _tana.merge_phase_log(
            run.get("phase_log") or [["start", 0, "start"]],
            _tana.fired_phases(tmp, (run.get("clock") or {}).get("mono0_ns"), sh=True))
        detail = (read_json(rd / "detail.json") if (rd / "detail.json").is_file() else
                  capture(repo, rd, tr, run, attach=(run.get("rec") or {}).get("attach"), late=True))
        packed = True
        if parts.is_dir():
            packed = _pack_all(rd, tmp)
        events, gpu = _build_events(repo, rd, tmp, run, tr)
        if parts.is_dir() and packed:
            shutil.rmtree(parts, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return derive(repo, rd, tr, run, detail, packed=packed, events=events, gpu=gpu)


# 复刻时要一样、但不会出现在命令行里的环境变量：被 trace 的命令继承 shell 的整个环境。
# 只记和跑模型、找解释器有关的这些；名字像密钥的一律不记（HF_TOKEN 之类）
_ENV_PREFIX = ("CUDA_", "VLLM_", "PYTORCH_", "TORCH_", "NCCL_", "HF_", "TRANSFORMERS_", "TOKENIZERS_",
               "OMP_", "MKL_", "NVIDIA_", "TRITON_", "XLA_")
_ENV_EXACT = ("PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
              "PYTHONHASHSEED", "CODESTRATA_EV_MAX")
# 名字里按 _ 分开的某一段是这些词的，当密钥（HF_TOKEN、VLLM_API_KEY、HF_HUB_TOKEN…）；
# TOKENIZERS_PARALLELISM、NCCL_IB_PKEY 这种只是含着这几个字母的不算
_ENV_SECRET = re.compile(r"(^|_)(TOKENS?|API_?KEYS?|KEYS?|SECRETS?|PASS|PASSWD|PASSWORD|PASSPHRASE|"
                         r"CREDS?|CREDENTIALS?|AUTH|COOKIES?|SESSION|PRIVATE)(_|$)", re.I)
_URL_USER = re.compile(r"(://)[^/@\s]+@")          # https://user:pw@host → https://<已隐去>@host
REDACTED = "<已隐去>"


def _scrub(v: str) -> str:
    return _URL_USER.sub(r"\1" + REDACTED + "@", v)


def inherited_env(environ, skip=()) -> dict:
    """录制时 shell 里和复刻有关的环境变量（skip 里的——命令行 --env 已经写明的——不重复记）。
    名字像密钥的不记；值里 URL 带的账号密码隐去。"""
    out = {}
    for k in sorted(environ):
        if k in skip or _ENV_SECRET.search(k):
            continue
        if k in _ENV_EXACT or k.startswith(_ENV_PREFIX):
            out[k] = _scrub(environ[k])
    return out


def shell_quote(x: str) -> str:
    """给 shell 的引号：一般的用 shlex.quote；带着不是 UTF-8 的字节（Python 里是孤立的代理字符）的，
    写成 bash / zsh 的 $'…'，按原来的字节还原，复制粘贴也不会变样。"""
    import shlex
    try:
        x.encode("utf-8")
        return shlex.quote(x)
    except UnicodeEncodeError:
        b = os.fsencode(x)
        return "$'" + "".join(chr(c) if 32 <= c < 127 and chr(c) not in "\\'" else f"\\x{c:02x}" for c in b) + "'"


def _secret_flag(a: str) -> bool:
    """--api-key、--hf-token 这种选项名（- 换成 _ 之后按段认，和环境变量同一套规则）。"""
    return a.startswith("-") and bool(_ENV_SECRET.search(a.lstrip("-").partition("=")[0].replace("-", "_")))


def _redact_argv(argv: list[str]) -> list[str]:
    """给网页看的命令行：--env K=V / --env=K=V 里 K 像密钥的，值换成 <已隐去>；--api-key X、
    --token=X 这种选项的值也是（后面紧跟着 - 开头的就当它是开关，不吃掉下一个选项）；所有参数里 URL
    带的账号密码隐去。"""
    out, env_next, secret_next = [], False, False
    for a in argv:
        if secret_next and not a.startswith("-"):   # 后面紧跟着别的选项的（--no-auth --port 80）是开关，没有值
            a = REDACTED
        elif env_next or a.startswith("--env="):
            pre, kv = ("", a) if env_next else ("--env=", a[len("--env="):])
            k, sep, v = kv.partition("=")
            if sep and _ENV_SECRET.search(k):
                kv = f"{k}={REDACTED}"
            a = pre + kv
        elif _secret_flag(a) and "=" in a:
            a = a.partition("=")[0] + "=" + REDACTED
        out.append(_scrub(a))
        secret_next = _secret_flag(a) and "=" not in a and not env_next
        env_next = a == "--env" and not env_next
    return out


def rerun_command(run: dict, repo: Path, with_env: bool = False, redact: bool = False) -> str:
    """一条可以直接复制的复刻命令。录制时存了原样的命令（invocation）就用它：cd 到当时的目录再原样
    执行，相对路径、codestrata 装在哪都和当时一样。老 run 没存的，从 run 里存的命令、--env、tag、
    备注、录制参数拼出来（值一律写成 --x=值，以 - 开头的值也不会被当成选项）。
    with_env：前面用 env 带上录制时 shell 里的相关环境变量（env_inherited），同一台机器上照抄就一样。
    redact：给网页用——--env 里像密钥的值、URL 里的账号密码换成 <已隐去>（runs show 给完整的）。
    codestrata 自己加进 run 的环境变量（从 shell 继承来的 CODESTRATA_EV_MAX）命令行上没有，补成 --env。"""
    pre = ""
    if with_env and run.get("env_inherited"):
        pre = "env " + " ".join(shell_quote(f"{k}={v}") for k, v in run["env_inherited"].items()) + " "
    inv = run.get("invocation") or {}
    if inv.get("argv"):
        argv = list(inv["argv"])
        given, nxt = set(), False
        for a in argv:
            if nxt or a.startswith("--env="):
                given.add((a if nxt else a[len("--env="):]).partition("=")[0])
            nxt = a == "--env" and not nxt
        extra = [f"--env={k}={v}" for k, v in (run.get("env") or {}).items() if k not in given]
        if extra:
            i = argv.index("--") if "--" in argv else len(argv)
            argv[i:i] = extra
        if redact:
            argv = _redact_argv(argv)
        cmd = pre + " ".join(shell_quote(x) for x in argv)
        return (f"cd {shell_quote(inv['cwd'])} && " if inv.get("cwd") else "") + cmd
    rec = run.get("rec") or {}
    parts = ["codestrata", "trace", str(Path(repo).resolve()), f"--case={run['case']}"]
    # run 里的 cwd 是命令实际执行的目录（老 run 里就是仓库根目录）：不是仓库根目录才要写 --cwd
    if run.get("cwd") and Path(run["cwd"]).resolve() != Path(repo).resolve():
        parts.append(f"--cwd={Path(run['cwd']).resolve()}")
    if rec.get("timeout"):
        parts.append(f"--timeout={fmt_seconds(rec['timeout'])}")
    if not rec.get("events"):                    # 默认录时序事件（09-30 之前默认不录）：没录的照样不录
        parts.append("--no-events")
    if rec.get("stop_grace") not in (None, 90.0):
        parts.append(f"--stop-grace={fmt_seconds(rec['stop_grace'])}")
    for k, v in (run.get("env") or {}).items():
        parts.append(f"--env={k}={REDACTED if redact and _ENV_SECRET.search(k) else v}")
    for f in rec.get("attach") or []:
        parts.append(f"--attach={f}")
    if rec.get("roots"):
        parts.append("--roots")
        parts.extend(rec["roots"])
    for t in rec.get("phase_at") or []:
        parts.append(f"--phase={t['name']}={t['func']}")
    for t in run.get("tags") or []:
        parts.append(f"--tag={t}")
    if run.get("note"):
        parts.append(f"--note={run['note']}")
    cmd = list(run.get("cmd") or [])
    if redact:
        parts, cmd = _redact_argv(parts), _redact_argv(cmd)
    return pre + " ".join(shell_quote(p) for p in parts) + " -- " + " ".join(shell_quote(c) for c in cmd)
