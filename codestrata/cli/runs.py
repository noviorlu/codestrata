"""codestrata runs 的读动作：ls / show / wait。同一份数据渲染成文字和 JSON 信封；仓库和 RUN 走 locate（也认页面地址、-C、
按 run id 找仓库），真的只读（老格式的录制不迁移，只提示）。写的动作（tag / untag / note / rm / merge）还在 __main__.cmd_runs。"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import locate as _locate
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from ..ui import load as _load
from . import common, out

FS = {"changed": "录制后改过", "mismatch": "录制时就和仓库不一致", "gone": "已删除",
      "outside": "不在 index 里", "unknown": "没存哈希"}


# ---------------------------------------------------------------- 小工具（__main__ 的 rm、trace 摘要也用）

def size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return str(n)


def run_size(rd: Path) -> int:
    tot = 0
    for dp, _, fs in os.walk(rd):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


def ev_calls(ev: dict) -> str:
    """run.json 的 events 摘要里 n_calls 数的是什么：2026-10-01 之前录的只有跨文件的调用"""
    return "调用" if ev.get("scope") == "all" else "跨文件调用"


def _brief_path(v: str, keep: int = 2) -> str:
    """PATH 这类冒号分隔的长列表只列前几段（完整的在「复刻」那一行里）：又长、又把本机的目录全摆出来"""
    parts = v.split(":")
    if len(parts) <= keep + 1:
        return v
    return ":".join(parts[:keep]) + f":…（共 {len(parts)} 段，完整的见下面的复刻命令）"


def _repo(a, text: str | None = None):
    """runs 的仓库：-C > 前面的位置参数 > REF 里的页面地址 / run id > 当前目录往上"""
    chdir = a.C or (a.repo if a.repo not in (None, ".") else None)
    return _locate.from_cli(text, chdir, Path.cwd())


def _index(repo: Path) -> dict | None:
    try:
        return _load.load_index(repo)
    except SystemExit:
        return None


def _phases(run: dict, rd: Path) -> list[dict]:
    """各阶段的时间段，带上那个阶段录到的函数数"""
    n = {p["name"]: p.get("n_funcs") for p in run.get("phases") or []}
    return [{**p, "n_funcs": n.get(p["name"])} for p in common.phases(run, rd)]


# ---------------------------------------------------------------- ls

def ls(a) -> out.Result:
    _, repo, how, warns = _repo(a)
    warns += _locate.legacy_warning(repo)
    base = repo / ".codestrata" / "runs"
    cat = [r for r in _locate.catalog(repo) if not a.case or r.get("case") == a.case]
    idx = _index(repo)
    rows, total = [], 0
    for r in cat:
        rd = base / r["id"]
        stale = None
        if idx is not None:
            try:
                stale = _runs.stale_counts(repo, idx, rd)
            except (OSError, ValueError):
                pass
        sz = run_size(rd)
        total += sz
        rows.append({**_runs.brief(r, rd, stale), "status": _runs.state(r), "status_text": r.get("status_shown") or r.get("status"),
                     "phases": _phases(r, rd), "end_us": _seq.run_end(r, rd), "bytes": sz})
    lines = [f"runs 在 {base.resolve()}" + (f"（{base} 是软链）" if base.is_symlink() else "")]
    if not rows:
        lines.append("  （还没有 run）录一个：codestrata trace <repo> --case NAME -- <命令>（record：先问用户）")
    else:
        lines.append("  每行：run id、状态、用时、跑到仓库代码的进程数、git 提交、录制后改过的文件数、大小、有没有时序事件（时序! 是整理失败）、标签、「备注」")
    order = list(dict.fromkeys(r["case"] for r in rows))
    for case in order:
        lines.append(f"\n{case}")
        for r in (x for x in rows if x["case"] == case):
            changed = "-" if r["stale"] is None else str(r["stale"]["changed"] + r["stale"]["mismatch"])
            dur = f"{r['duration_s']:.0f}s" if r.get("duration_s") is not None else "-"
            ev = ("时序!" if r["events_error"] else "时序") if r["events"] or r["events_error"] else "    "
            lines.append(f"  {r['id']:<40} {r['status_text']:<9} {dur:>6}  进程 {r['n_procs_active'] if r['n_procs_active'] is not None else '-':>3}  "
                         f"git {(r['git'] or '')[:8] or '-':<8}  改过 {changed:>3}  {size(r['bytes']):>7}  {ev}  "
                         + " ".join(r["tags"]) + (f"  「{r['note']}」" if r["note"] else ""))
    if rows:
        lines.append(f"\n共 {len(rows)} 个 run，{size(total)}")
        if total > 1 << 30:
            lines.append("注意：runs/ 超过 1 GB；不要的可以 codestrata runs rm <完整 run id>（delete：先问用户）")
    nxt = [out.step("read", "status", rows[0]["id"] + (f"@{common.main_phase(cat[0])}" if common.main_phase(cat[0]) else ""),
                    repo=None if how == "cwd" else repo)] if rows else []
    return out.Result(data={"runs": rows, "bytes": total}, text=lines, repo=repo, warnings=warns, next=nxt)


# ---------------------------------------------------------------- show

def show(a) -> out.Result:
    ref, repo, how, warns = _repo(a, a.ref)
    try:
        res = _locate.resolve(repo, ref)
    except CodestrataError as e:
        e.warnings = warns + e.warnings
        raise
    run, rd = res.run, res.rd
    detail = _runs.read_json(rd / "detail.json") if (rd / "detail.json").is_file() else {}
    idx = _index(repo)
    fs = _runs.file_state(repo, idx, detail) if idx is not None else None
    rerun = _runs.rerun_command(run, repo)
    data = {"run": run, "status": _runs.state(run), "phases": _phases(run, rd), "end_us": res.end_us,
            "procs": _runs.procs_grouped(detail.get("procs")), "files": detail.get("files") or [],
            "gpu_devices": detail.get("gpu") or [], "leftovers": detail.get("leftovers") or [],
            "file_state": fs, "rerun": rerun, "dir": str(rd.resolve())}
    lines = _show_text(run, rd, detail, fs, rerun)
    flag = None if how == "cwd" else repo
    nxt = []
    if run.get("events") and _runs.state(run) in ("ok", "partial"):
        mp = common.main_phase(run)
        nxt.append(out.step("read", "lanes", run["id"] + (f"@{mp}" if mp else ""), repo=flag, why="这段时间里有哪几列"))
    return out.Result(data=data, text=lines, repo=repo, ref={"text": res.full, "slices_us": [list(s) for s in res.slices],
                                                             "lanes": res.lanes},
                      warnings=warns + res.warnings, next=nxt)


def _show_text(run: dict, rd: Path, detail: dict, fs: dict | None, rerun: str) -> list[str]:
    L = [f"run {run['id']}  {rd.resolve()}",
         f"  状态  {run.get('status_shown') or run.get('status')}"
         + (f"（{'；'.join(run.get('problems') or [])}）" if run.get("problems") else "")]
    for k, label in (("created", "录制于"), ("duration_s", "用时（秒）"), ("returncode", "退出码"),
                     ("stop", "怎么停的"), ("host", "机器"), ("cwd", "执行目录"), ("migrated_from", "迁移自")):
        if run.get(k) is not None:
            L.append(f"  {label:<6}{run[k]}")
    L.append(f"  命令  {' '.join(run.get('cmd') or [])}")
    if run.get("env"):
        L.append("  环境  " + " ".join(f"{k}={_brief_path(v)}" for k, v in run["env"].items()))
    if run.get("git"):
        g = run["git"]
        L.append(f"  git   {g['commit'][:12]}" + (f" ({g['branch']})" if g.get("branch") else "")
                 + (f"，{g['n_dirty']} 个文件有未提交的改动" if g.get("n_dirty") else ""))
    if run.get("tags") or run.get("note"):
        L.append(f"  标签  {' '.join(run.get('tags') or []) or '-'}　备注  {run.get('note') or '-'}")
    for p in run.get("phases") or []:
        t = f"{p['t_us'] / 1e6:7.1f}s 起" if p.get("t_us") is not None else ""
        L.append(f"  阶段  {p['name']:<12} {t:<11} {p['n_funcs']} 个函数，{p['n_calls']} 次调用")
    procs = detail.get("procs") or []
    if procs:
        L.append(f"  进程  {len(procs)} 个，跑到仓库代码的 {sum(1 for p in procs if p.get('n_funcs'))} 个：")
        for g in _runs.procs_grouped(procs)[:8]:
            L.append(f"        {g['n']}× {g['funcs']:>5} 个函数  {' '.join(g['argv'])[:110]}"
                     + ("  …（老版本只存了前 6 个参数）" if g["cut"] else ""))
    for exe, py in (detail.get("pythons") or {}).items():
        ds = py.get("dists") or {}
        key = [f"{k} {ds[k]}" for k in ("torch", "vllm", "vllm-omni", "transformers") if k in ds]
        L.append(f"  python {py.get('version')}  {exe}" + (f"（{'，'.join(key)}…共 {len(ds)} 个包）" if ds else ""))
    for gpu in detail.get("gpu") or []:
        L.append(f"  GPU{gpu['index']}  {gpu['name']}，驱动 {gpu['driver']}，{gpu['mem_mib']} MiB")
    if run.get("gpu"):                         # trace --gpu
        g = run["gpu"]
        L.append(f"  kernel {g['n_kernels']} 次（{g['n_names']} 种），GPU 上共 {g['gpu_us'] / 1000:.1f} ms"
                 + (f"，{g['unattached']} 次找不到发起它的 Python 调用" if g["unattached"] else "")
                 + (f"，CUPTI 丢了 {g['dropped']} 条" if g["dropped"] else ""))
    for f in detail.get("files") or []:
        L.append(f"  存下  {f['stored']:<32} ← {f['path']}（{f['why']}）")
    ev = run.get("events")
    if ev:
        if ev.get("error"):
            L.append(f"  时序  整理失败（原始日志已存，可以 runs merge 重来）：{ev['error']}")
        else:
            tr = ev.get("truncated") or []
            L.append(f"  时序  {ev['n_spans']} 段、{ev['n_calls']} 次{ev_calls(ev)}（{ev['n_procs']} 个进程），"
                     f"原始日志 {size(ev['bytes'] or 0)}"
                     + (f"；⚠ {len(tr)} 个进程到了行数上限（pid " + "、".join(map(str, tr[:8])) + ("…" if len(tr) > 8 else "")
                        + "），之后的调用没记时序，计数完整" if tr else ""))
    if detail.get("leftovers"):
        L.append("  残留  " + "，".join(f"{x['pid']} {x['signal']}" for x in detail["leftovers"]))
    if fs is not None:
        n = len(detail.get("file_shas") or {})
        by: dict = {}
        for rel, st in fs.items():
            by.setdefault(st, []).append(rel)
        L.append(f"  文件  这次跑到 {n} 个文件，相对当前的 index："
                 + ("全部没变" if not fs else "，".join(f"{FS[k]} {len(v)}" for k, v in sorted(by.items()))))
        for st in ("changed", "mismatch", "gone", "outside", "unknown"):
            for rel in sorted(by.get(st, []))[:12]:
                L.append(f"        {FS[st]:<10} {rel}")
            if len(by.get(st, [])) > 12:
                L.append(f"        …还有 {len(by[st]) - 12} 个")
    L.append(f"  复刻  {rerun}")
    if not run.get("invocation"):
        L.append("        （这个 run 录的时候还没存原始命令，上面是按 run 里存的参数拼的）")
    if run.get("env_inherited"):
        L.append("  录制时 shell 里的相关环境变量（不在命令里，复刻时要一样）：")
        L += [f"        {k}={v}" for k, v in run["env_inherited"].items()]
    return L


# ---------------------------------------------------------------- wait

def wait(a) -> out.Result:
    """等 run 录完（不再是 recording，或录制的进程没了）。给 case 名时等这个 case 最新的那一次（正在录的也算）。
    超时报 recording（退出码 4），下一步给更长的 --timeout"""
    ref, repo, how, warns = _repo(a, a.ref)
    name = ref.run or ""
    cat = _locate.catalog(repo)
    mine = [r for r in cat if r["id"] == name] or [r for r in cat if r.get("case") == name]
    if not mine:
        raise CodestrataError("run_not_found", f"{repo} 里没有叫 {name!r} 的 run 或 case",
                              candidates=sorted({r.get("case") for r in cat if r.get("case")}), warnings=warns)
    run = mine[0]                                 # catalog 新的在前
    rid, t0 = run["id"], time.monotonic()
    rj = repo / ".codestrata" / "runs" / rid / "run.json"
    flag = None if how == "cwd" else repo
    while _runs.live(run):
        if time.monotonic() - t0 > a.timeout:
            raise CodestrataError("recording", f"等了 {a.timeout:.0f} s，run {rid} 还在录", warnings=warns,
                                  next=[out.step("read", "runs", "wait", rid, "--timeout", str(int(a.timeout * 2)), repo=flag)])
        time.sleep(0.5)
        try:
            run = _runs.read_json(rj)
        except (OSError, ValueError):
            pass
    st = _runs.state(run)
    lines = [f"run {rid}：{st}，等了 {time.monotonic() - t0:.1f} s"]
    if st == "interrupted":
        nxt = [out.step("write", "runs", "merge", rid, repo=flag, why="录制中断了，从原始数据合并")]
    else:
        mp = common.main_phase(run)
        nxt = [out.step("read", "status", rid + (f"@{mp}" if mp else ""), repo=flag)]
    return out.Result(data={"id": rid, "status": st, "problems": run.get("problems") or []}, text=lines, repo=repo,
                      next=nxt, warnings=warns)

