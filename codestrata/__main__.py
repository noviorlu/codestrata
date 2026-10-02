"""codestrata 命令行。

    codestrata scan  <repo>                      静态扫描 → .codestrata/index.json
    codestrata app                               主菜单：选文件夹，点按钮扫描 / 录制运行 / 打开图
    codestrata serve <repo> [--hot RUN]          本地部署前端：图 + 运行叠加 + 源码 + 跳编辑器
    codestrata trace <repo> --case NAME -- CMD   跑一个 case，记录真实调用（每次都存成一个新的 run）
    codestrata runs  <repo> ls|show|tag|untag|note|rm|merge   管理录下的 run

RUN 是一次录制：完整的 run id（runs ls 里看），或 case 名（取它最新一次录完的），
后面可以加 @阶段（如 minicpmo-duplex@serving）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import self_command
from . import align as _align
from . import compat as _compat
from . import cut as _cut
from . import graph as _graph
from . import runs as _runs
from . import scan as _scan
from .trace import analysis as _tana
from .trace import driver as _tdrv
from .trace import gpu as _tgpu
from . import xref as _xref
from .ui import load as _load


_README = """codestrata 的数据目录。

除 runs/ 以外都能删、都能重建（codestrata scan 重新生成索引）。
runs/ 是 trace 录下的运行数据，不能重建：每个 run 都是一次真实的运行（可能是几分钟的 GPU），
删了就没了。runs/ 可以是指向别处的软链，rm -rf .codestrata 只会删掉链接本身。
管理它们用 codestrata runs <repo> ls|show|tag|note|rm。
"""


def _outdir(repo: Path) -> Path:
    d = repo / ".codestrata"
    d.mkdir(parents=True, exist_ok=True)
    # 整个目录不进 git（被分析的仓库不该因为用了 codestrata 而多出一堆未跟踪文件）
    for name, text in ((".gitignore", "*\n"), ("README.txt", _README)):
        p = d / name
        if not p.exists():
            p.write_text(text, encoding="utf-8")
    return d


def _load_index(repo: Path) -> dict:
    return _load.load_index(repo)


def cmd_scan(a) -> int:
    repo = Path(a.repo).resolve()
    depth = None if a.depth == "auto" else int(a.depth)
    # 没给 --roots：沿用上次扫描的目录（重扫不该悄悄换掉用户选过的目录）；--roots 不带目录：重新自动探测
    prev = [x for x in ((_load.index_summary(repo) or {}).get("roots") or [])
            if x == _scan.ROOT_SCRIPTS or (repo / x).is_dir()]
    roots, how = a.roots, "（--roots 指定）"
    if roots is None and prev:
        roots, how = prev, "（沿用上次扫描的目录；要重新自动探测就加不带目录的 --roots）"
    elif not roots:
        roots, how = None, "（自动探测的；要换就用 --roots 指定）"
    idx = _scan.scan(repo, depth=depth, roots=roots, expand=a.expand)
    p = _scan.write_index(repo, idx, _outdir(repo))
    r = idx["repo"]
    print(f"扫描的目录：{'、'.join(r['roots'])}{how}")
    gone = [x for x in prev if x not in r["roots"]]
    if gone:
        print(f"  ⚠ 上次还扫了 {'、'.join(gone)}，这次没扫：图上不再有它们（要加回来就用 --roots 列全）")
    v = _cut.view(idx, set(idx["default_open"]))
    shown = _cut.visible(v)
    print(f"扫描 {r['n_files']} 文件（解析失败 {r['n_parse_errors']}），{len(idx['packages'])} 个模块、"
          f"{len(idx['edges'])} 条模块间 import 边、{len(idx['symbols'])} 个符号")
    if depth is None:
        split = "，".join(f"{_short(idx, x['node'])}（占 {x['share']:.0%}，拆成 {x['fanout']} 块）"
                          for x in r.get("auto_split") or [])
        print(f"默认切面 {len(shown)} 个节点、{len(v['edges'])} 条边；按规模自动拆开：{split or '无'}")
    else:
        print(f"默认切面 {len(shown)} 个节点、{len(v['edges'])} 条边（depth={depth}）")
    if r.get("unresolved_imports"):
        print(f"指向仓库里不存在的模块的 import {len(r['unresolved_imports'])} 条（不进图）："
              + "；".join(r["unresolved_imports"][:5]) + ("…" if len(r["unresolved_imports"]) > 5 else ""))
    print(f"→ {p}")
    print(f"→ {p.parent / 'symbols.json'}")
    # 交叉引用（全文窗口里 Ctrl+点击跳定义 / 列引用）和 graph 的调用（同一遍走出来）。和符号表同一时刻的快照，行号才对得上
    gb = _graph.Builder(idx)
    x = _xref.build(repo, idx, on_file=gb.add_file, on_end=gb.add_ctors)
    xp = _xref.write(p.parent, x)
    print(f"→ {xp}  （{sum(len(v) for v in x['files'].values())} 处能解析的名字）")
    g = gb.result()
    gp = _graph.write(p.parent, g)
    print(f"→ {gp}  （{sum(len(v) for v in g['calls'].values())} 处定下了被调方的调用、"
          f"{sum(len(v) for v in g['sites'].values())} 处定不下的）")
    print("\n架构高度（+1 入口 … −1 叶子），默认切面上的节点：")
    for name in sorted(shown, key=lambda n: -v["nodes"][n]["alt"]):
        x = v["nodes"][name]
        bar = "█" * int((x["alt"] + 1) * 11)
        tag = {"dir": "/", "residual": "", "unit": ""}[x["kind"]]
        print(f"  {x['alt']:+.2f} {bar:<24} {_short(idx, name) + tag:<40} {x['files']:4d}f {x['classes']:4d}c")
    return 0


def _short(idx: dict, name: str) -> str:
    """节点的显示名，去掉唯一的那个根（vllm_omni.engine → engine）。"""
    segs, sep = _cut.label(idx, name)
    pre = _cut.root_label(idx)
    if pre and segs[:len(pre)] == pre and len(segs) > len(pre):
        segs = segs[len(pre):]
    return sep.join(segs)


_TAG_RE = re.compile(r"^[A-Za-z0-9._:=/+-]+$")


def cmd_trace(a) -> int:
    _compat.require_trace()                 # 不能录的系统上，在建 run 目录之前就停
    repo = Path(a.repo).resolve()
    if not a.cmd:
        raise SystemExit("要在 -- 之后给出命令，例如：\n"
                         "  codestrata trace . --case demo -- python examples/foo.py")
    env = {}
    for kv in a.env:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            raise SystemExit(f"--env 要写成 K=V：{kv!r}")
        env[k] = v
    for t in a.tag:
        if not _TAG_RE.match(t):
            raise SystemExit(f"tag 只能用字母、数字和 . _ : = / + -：{t!r}")
    # 命令的执行目录：默认仓库根目录（case 脚本、复刻命令都按它写）；--cwd 可以换
    run_dir = Path(a.cwd).resolve() if a.cwd else repo
    if not run_dir.is_dir():
        raise SystemExit(f"--cwd 不是一个目录：{a.cwd}")
    here = _cwd()                            # 当前目录可能已经被删了
    if not a.cwd and here:
        lost = _tdrv.misplaced_paths(a.cmd, run_dir, Path(here))
        if lost:
            raise SystemExit(f"命令在仓库根目录 {repo} 执行，这些相对路径在那里没有、在当前目录下有："
                             f"{'、'.join(lost)}\n要在当前目录执行就加 --cwd .（或者写成绝对路径）")
    if a.roots:                              # 录之前就挡：别留下一个失败的 run
        try:
            _scan.check_roots(a.roots)
        except ValueError as e:
            raise SystemExit(str(e)) from None
    # --gpu：GPU 录制端要用本机的 CUDA 工具链现编（缓存）；录之前编好，编不过不留下失败的 run
    gpu_lib = None
    if a.gpu:
        if not a.events:
            raise SystemExit("--gpu 要时序事件（kernel 挂到发起它的那次调用上靠它），不能和 --no-events 一起用")
        try:
            gpu_lib = _tgpu.injection_lib(env)
        except RuntimeError as e:
            raise SystemExit(str(e)) from None
    # --attach 的相对路径和命令一样按执行目录算；那里没有再按当前目录
    attach = []
    for f in a.attach:
        p = Path(f)
        cand = [p] if p.is_absolute() else [run_dir / p] + ([Path(here) / p] if here else [])
        hit = next((c for c in cand if c.is_file()), None)
        if hit is None:
            raise SystemExit(f"--attach 的文件不存在：{f}")
        attach.append(str(hit.resolve()))
    # --phase 名字=函数：录之前就解析好（写错了现在报，不要等模型加载完才发现）。
    # 模块:qualname 的写法查静态索引；没 scan 过的仓库只能用 文件路径:qualname
    phase_at = []
    if a.phase:
        try:
            symbols = _load_index(repo).get("symbols")
        except SystemExit:
            symbols = None
        phase_at = _tana.resolve_phase_at(repo, a.phase, symbols)
        for t in phase_at:
            print(f"[codestrata] 阶段 {t['name']}：第一次进入 {t['qualname']}（{t['file']}:{t['line']}）时切过去"
                  + (f"——{t['func']} 是继承来的，定义在 {t['via']}" if t.get("via") else ""), file=sys.stderr)
    _outdir(repo)
    _runs.catalog(repo)                      # 先把老格式的 trace 迁进 runs/
    # 顶层包 → 仓库内目录：命令若跑的是 pip 安装的那份，trace 靠它映射回仓库
    # 默认用 scan 时选的目录（主菜单里用户勾的、或者 scan --roots 给的）：录制和图对的是同一批代码
    roots = a.roots or (_load.index_summary(repo) or {}).get("roots") or _scan.detect_roots(repo)
    pkgs = {r.split("/")[-1]: r for r in roots if r != _scan.ROOT_SCRIPTS}   # 根目录的脚本不会装进 site-packages
    # 行数上限是从 shell 继承来的：记进 run 的 env（在建 run 之前放进去，run.json 里才有、重录命令才带上）
    if a.events and os.environ.get("CODESTRATA_EV_MAX") and "CODESTRATA_EV_MAX" not in env:
        env["CODESTRATA_EV_MAX"] = os.environ["CODESTRATA_EV_MAX"]
    rd = _runs.new_run(repo, case=a.case, cmd=a.cmd, cwd=run_dir, env=env, tags=a.tag, note=a.note or "",
                       rec={"timeout": a.timeout, "stop_grace": a.stop_grace, "attach": attach,
                            "events": bool(a.events), "roots": a.roots, "gpu": bool(a.gpu),
                            "phase_at": [{k: t[k] for k in ("name", "func", "file", "qualname", "line")}
                                         for t in phase_at]},
                       invocation=getattr(a, "invocation", None),
                       env_inherited=_runs.inherited_env(os.environ, skip=env))
    # 时序事件（模块图「时间顺序」的数据）：hook 看这个变量；不记进 run 的 env（那是给命令的）
    # 明确写 0：shell 里恰好 export 了 CODESTRATA_EVENTS=1 也不录——以命令行为准，重录命令才对得上
    env_run = {**env, "CODESTRATA_EVENTS": "1" if a.events else "0"}
    if gpu_lib:                              # 和 CODESTRATA_EVENTS 一样是 codestrata 自己的，不记进 run 的 env
        env_run[_tgpu.ENV] = str(gpu_lib)
        print(f"[codestrata] GPU：录 kernel（CUPTI，{gpu_lib}）", file=sys.stderr)
    print(f"[codestrata] run {rd.name}（{rd.resolve()}）", file=sys.stderr)
    mono0 = _runs.read_json(rd / "run.json")["clock"]["mono0_ns"]

    def after(tr, info):
        # 在 driver 的信号处理器还装着的时候收尾：这时按 Ctrl+C 不会把打包打断
        return tr, _runs.finalize(repo, rd, tr, stop=info["stop"], returncode=info["returncode"],
                                  phase_times=info["phase_times"], duration_s=info["duration_s"],
                                  leftovers=info["leftovers"], attach=attach)
    tr, run = _tdrv.run(repo, a.cmd, rd / "parts", mono0_ns=mono0, timeout=a.timeout, pkgs=pkgs,
                         env_extra=env_run, stop_grace=a.stop_grace, after=after, phase_at=phase_at,
                         cwd=run_dir)
    detail = _runs.read_json(rd / "detail.json")
    sm = run["summary"]
    print(f"→ run {run['id']}：{_STATUS.get(run['status'], run['status'])}"
          + (f"（{'；'.join(run['problems'])}）" if run["problems"] else ""))
    print(f"  {rd.resolve()}")
    print(f"  进程 {sm['n_procs']} 个（跑到仓库代码的 {sm['n_procs_active']} 个），"
          f"函数 {sm['n_funcs']} 个被调到，文件间调用边 {len(tr['file_edges'])} 条，"
          f"退出码 {run['returncode']}，用时 {run['duration_s']}s")
    if len(run["phases"]) > 1:
        print("  阶段：" + " / ".join(f"{p['name']} {p['n_funcs']} 个函数" for p in run["phases"]))
    log = run.get("phase_log") or []
    by_hook = {e[0] for e in log if len(e) > 2 and e[2] == "hook"}
    by_sh = {e[0] for e in log if len(e) > 2 and e[2] == "sh"}
    missed = [t["name"] for t in phase_at if t["name"] not in by_hook | by_sh]
    if missed:
        print(f"  ⚠ 这些 --phase 没切到（对应的函数这次没被调用）：{'、'.join(missed)}")
    shadow = [t["name"] for t in phase_at if t["name"] in by_sh and t["name"] not in by_hook]
    if shadow:
        print(f"  ⚠ 这些阶段是 case 脚本写 PHASE 切的，同名的 --phase 没起作用：{'、'.join(shadow)}")
    if tr["mapped"]:
        bad, extra = detail["mapped_mismatch"], detail["mapped_only_installed"]
        print(f"  运行的是安装包 {detail['mapped_from']}，已映射回仓库 {len(tr['mapped'])} 个文件，"
              + (f"其中 {len(bad)} 个和仓库内容不一致——这些文件的行号不可信" if bad
                 else "内容与仓库逐文件一致")
              + (f"（另有 {len(extra)} 个只在安装包里：{', '.join(extra[:3])}）" if extra else ""))
    ev = run.get("events")
    if ev and ev.get("error"):
        print(f"  ⚠ 时序事件整理失败（原始日志已存，可以 runs merge 重来）：{ev['error']}")
    elif ev:
        print(f"  时序事件 {ev['n_lines']} 行 → {ev['n_spans']} 段（{ev['n_calls']} 次{_ev_calls(ev)}），"
              f"原始日志 {_size(ev['bytes'] or 0)}"
              + (f"；⚠ {len(ev['truncated'])} 个进程到了行数上限，之后的调用没记时序（计数完整）"
                 if ev["truncated"] else ""))
    elif a.events:
        old = sorted({v["version"] for v in (detail.get("pythons") or {}).values()
                      if v.get("version") and tuple(map(int, v["version"].split(".")[:2])) < (3, 12)})
        print(f"  （被录的 Python 是 {'、'.join(old)}，没有时序事件：要 3.12+。请求路径、时间顺序看不了，计数照常）" if old else
              "  ⚠ 没有录到时序事件：命令没起来，或者这次根本没有跨文件的调用")
    if detail["leftovers"]:
        print(f"  命令退出后停掉了 {len(detail['leftovers'])} 个残留进程："
              + "，".join(f"{x['pid']}（{x['signal']}）" for x in detail["leftovers"]))
    if detail["files"]:
        print("  存下的文件：" + "，".join(f"{f['path']}" for f in detail["files"]))
    if detail.get("attach_missing"):
        print("  ⚠ 这些 --attach 的文件没存下来：" + "，".join(detail["attach_missing"]))
    try:
        idx = _load_index(repo)
    except SystemExit:
        print("  （还没 scan，跑 codestrata scan 之后再 serve --hot 就能叠图）")
        return 0 if run["status"] != "failed" else 1
    hp = _align.to_package_graph(tr, idx)
    # 归不到具名函数的调用照样算在文件和模块上，只是没有函数名可挂——说清楚是什么，别写成「未映射」吓人；
    # 定义时的执行（模块顶层、类体）不是调用，哪儿都不算
    defs = "，".join(x for x in (f"{hp['module_frames']} 次 import 时的模块顶层执行" if hp.get("module_frames") else "",
                                 f"{hp['class_frames']} 次类体执行（class 语句定义类）" if hp.get("class_frames") else "") if x)
    print(f"  映射到 {len(hp['packages'])} 个包 / {len(hp['symbols'])} 个符号"
          + (f"（另有 {hp['anon']} 次在 lambda / 生成器表达式里：算到文件上，不单列函数）" if hp.get("anon") else "")
          + (f"（{defs}：是定义、不算调用）" if defs else ""))
    for k, v in sorted(hp["packages"].items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {v:8d}  {k}")
    # 分了阶段、有 serving 的，默认建议只看 serving（启动时的初始化会淹没请求本身）
    serving = any(p["name"] == "serving" for p in run["phases"])
    print(f"  叠到图上：codestrata serve {a.repo} --hot {run['id']}" + ("@serving" if serving else ""))
    if ev and not ev.get("error"):
        print(f"  请求路径：codestrata path {a.repo} {run['id']}" + ("@serving" if serving else ""))
    return 0 if run["status"] != "failed" else 1


def _ev_calls(ev: dict) -> str:
    """run.json 的 events 摘要里 n_calls 数的是什么：2026-10-01 之前录的只有跨文件的调用"""
    return "调用" if ev.get("scope") == "all" else "跨文件调用"


_STATUS = {"ok": "完整录完", "partial": "录到了但不完整", "failed": "失败（一个函数都没录到）",
           "recording": "录制中"}


def _brief_path(v: str, keep: int = 2) -> str:
    """PATH 这类冒号分隔的长列表只列前几段（完整的在「复刻」那一行里）：又长、又把本机的目录全摆出来"""
    parts = v.split(":")
    if len(parts) <= keep + 1:
        return v
    return ":".join(parts[:keep]) + f":…（共 {len(parts)} 段，完整的见下面的复刻命令）"


def _size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return str(n)


def _run_size(rd: Path) -> int:
    tot = 0
    for dp, _, fs in os.walk(rd):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


def cmd_runs(a) -> int:
    """管理录下的 run：列出、看详情、打标签、写备注、删除、从原始数据重算。"""
    repo = Path(a.repo).resolve()
    # 只读查询不建目录：路径写错了（比如少了 src/vllm-omni）要报出来，而不是悄悄建一个空的
    if not repo.is_dir():
        raise SystemExit(f"没有这个目录：{repo}")
    if not (repo / ".codestrata").is_dir():
        raise SystemExit(f"{repo} 下没有 .codestrata：还没 scan / trace 过？")
    base = _runs.runs_dir(repo)
    if a.verb == "ls":
        runs = _runs.catalog(repo)
        print(f"runs 在 {base.resolve()}" + (f"（{base} 是软链）" if base.is_symlink() else ""))
        try:
            idx = _load_index(repo)
        except SystemExit:
            idx = None
        if a.case:
            runs = [r for r in runs if r.get("case") == a.case]
        if not runs:
            print("  （还没有 run）录一个：codestrata trace <repo> --case NAME -- <命令>")
            return 0
        total = 0
        for case in sorted({r["case"] for r in runs}, key=lambda c: min(
                i for i, r in enumerate(runs) if r["case"] == c)):
            print(f"\n{case}")
            for r in (x for x in runs if x["case"] == case):
                rd = base / r["id"]
                sz = _run_size(rd)
                total += sz
                changed = "-"
                if idx is not None:
                    try:
                        fs = _runs.file_state(repo, idx, _runs.read_json(rd / "detail.json"))
                        changed = str(sum(1 for v in fs.values() if v in ("changed", "mismatch")))
                    except (OSError, ValueError):
                        pass
                sm = r.get("summary") or {}
                git = (r.get("git") or {}).get("commit", "")[:8] or "-"
                st = r.get("status_shown") or r.get("status")
                dur = f"{r['duration_s']:.0f}s" if r.get("duration_s") is not None else "-"
                print(f"  {r['id']:<40} {st:<9} {dur:>6}  进程 {sm.get('n_procs_active', '-'):>3}  "
                      f"git {git:<8}  改过 {changed:>3}  {_size(sz):>7}  {('时序' if not r['events'].get('error') else '时序!') if r.get('events') else '    '}  "
                      + " ".join(r.get("tags") or []) + (f"  「{r['note']}」" if r.get("note") else ""))
        print(f"\n共 {len(runs)} 个 run，{_size(total)}")
        if total > 1 << 30:
            print("注意：runs/ 超过 1 GB；不要的可以 codestrata runs <repo> rm <id>")
        return 0

    if a.verb == "show":
        run, rd, phase = _runs.resolve(repo, a.ref)
        detail = _runs.read_json(rd / "detail.json") if (rd / "detail.json").is_file() else {}
        print(f"run {run['id']}  {rd.resolve()}")
        print(f"  状态  {run.get('status_shown') or run.get('status')}"
              + (f"（{'；'.join(run.get('problems') or [])}）" if run.get("problems") else ""))
        for k, label in (("created", "录制于"), ("duration_s", "用时（秒）"), ("returncode", "退出码"),
                         ("stop", "怎么停的"), ("host", "机器"), ("cwd", "执行目录"), ("migrated_from", "迁移自")):
            if run.get(k) is not None:
                print(f"  {label:<6}{run[k]}")
        print(f"  命令  {' '.join(run.get('cmd') or [])}")
        if run.get("env"):
            print("  环境  " + " ".join(f"{k}={_brief_path(v)}" for k, v in run["env"].items()))
        if run.get("git"):
            g = run["git"]
            print(f"  git   {g['commit'][:12]}" + (f" ({g['branch']})" if g.get("branch") else "")
                  + (f"，{g['n_dirty']} 个文件有未提交的改动" if g.get("n_dirty") else ""))
        if run.get("tags") or run.get("note"):
            print(f"  标签  {' '.join(run.get('tags') or []) or '-'}　备注  {run.get('note') or '-'}")
        for p in run.get("phases") or []:
            t = f"{p['t_us'] / 1e6:7.1f}s 起" if p.get("t_us") is not None else ""
            print(f"  阶段  {p['name']:<12} {t:<11} {p['n_funcs']} 个函数，{p['n_calls']} 次调用")
        procs = detail.get("procs") or []
        if procs:
            print(f"  进程  {len(procs)} 个，跑到仓库代码的 {sum(1 for p in procs if p.get('n_funcs'))} 个：")
            for g in _runs.procs_grouped(procs)[:8]:
                print(f"        {g['n']}× {g['funcs']:>5} 个函数  {' '.join(g['argv'])[:110]}"
                      + ("  …（老版本只存了前 6 个参数）" if g["cut"] else ""))
        for exe, py in (detail.get("pythons") or {}).items():
            ds = py.get("dists") or {}
            key = [f"{k} {ds[k]}" for k in ("torch", "vllm", "vllm-omni", "transformers") if k in ds]
            print(f"  python {py.get('version')}  {exe}" + (f"（{'，'.join(key)}…共 {len(ds)} 个包）" if ds else ""))
        for gpu in detail.get("gpu") or []:
            print(f"  GPU{gpu['index']}  {gpu['name']}，驱动 {gpu['driver']}，{gpu['mem_mib']} MiB")
        for f in detail.get("files") or []:
            print(f"  存下  {f['stored']:<32} ← {f['path']}（{f['why']}）")
        if run.get("events"):
            ev = run["events"]
            if ev.get("error"):
                print(f"  时序  整理失败（原始日志已存，可以 runs merge 重来）：{ev['error']}")
            else:
                print(f"  时序  {ev['n_spans']} 段、{ev['n_calls']} 次{_ev_calls(ev)}（{ev['n_procs']} 个进程），"
                      f"原始日志 {_size(ev['bytes'] or 0)}"
                      + (f"；⚠ {len(ev['truncated'])} 个进程到了行数上限（pid "
                         + "、".join(map(str, ev["truncated"][:8])) + ("…" if len(ev["truncated"]) > 8 else "")
                         + "），之后的调用没记时序，计数完整"
                         if ev["truncated"] else ""))
        if detail.get("leftovers"):
            print("  残留  " + "，".join(f"{x['pid']} {x['signal']}" for x in detail["leftovers"]))
        try:
            idx = _load_index(repo)
        except SystemExit:
            idx = None
        if idx is not None:
            fs = _runs.file_state(repo, idx, detail)
            n = len(detail.get("file_shas") or {})
            by: dict = {}
            for rel, st in fs.items():
                by.setdefault(st, []).append(rel)
            print(f"  文件  这次跑到 {n} 个文件，相对当前的 index："
                  + ("全部没变" if not fs else "，".join(f"{_FS[k]} {len(v)}" for k, v in sorted(by.items()))))
            for st in ("changed", "mismatch", "gone", "outside", "unknown"):
                for rel in sorted(by.get(st, []))[:12]:
                    print(f"        {_FS[st]:<10} {rel}")
                if len(by.get(st, [])) > 12:
                    print(f"        …还有 {len(by[st]) - 12} 个")
        print(f"  复刻  {_runs.rerun_command(run, Path(a.repo))}")
        if not run.get("invocation"):
            print("        （这个 run 录的时候还没存原始命令，上面是按 run 里存的参数拼的）")
        if run.get("env_inherited"):
            print("  录制时 shell 里的相关环境变量（不在命令里，复刻时要一样）：")
            for k, v in run["env_inherited"].items():
                print(f"        {k}={v}")
        return 0

    if a.verb in ("tag", "untag"):
        for t in a.tags:
            if not _TAG_RE.match(t):
                raise SystemExit(f"tag 只能用字母、数字和 . _ : = / + -：{t!r}")
        run = _runs.set_tags(repo, a.ref, a.tags, remove=a.verb == "untag")
        print(f"run {run['id']}：标签 {' '.join(run['tags']) or '（无）'}")
        return 0
    if a.verb == "note":
        run = _runs.set_note(repo, a.ref, a.text)
        print(f"run {run['id']}：备注「{run['note']}」")
        return 0
    if a.verb == "rm":
        runs = {r["id"]: r for r in _runs.catalog(repo)}
        targets = []
        for ref in dict.fromkeys(a.refs):
            if ref not in runs:
                same = [i for i, r in runs.items() if r.get("case") == ref]
                raise SystemExit(f"rm 只认完整的 run id：{ref!r} 不是" + (
                    "。这个 case 的 run 有：\n  " + "\n  ".join(f"{i}  {runs[i].get('status')}" for i in same)
                    if same else ""))
            if _runs.live(runs[ref]):
                raise SystemExit(f"run {ref} 还在录制中，不能删")
            targets.append((runs[ref], base / ref))
        if a.events_only:                          # 没有时序事件的不用问、也不用删
            none = [run["id"] for run, rd in targets
                    if not (rd / "events").exists() and not list((rd / "parts").glob("ev-*.log") if (rd / "parts").is_dir() else [])]
            for i in none:
                print(f"  {i} 没有时序事件")
            targets = [(run, rd) for run, rd in targets if run["id"] not in none]
            if not targets:
                return 0
        for run, rd in targets:
            sz = (_run_size(rd / "events") + sum(p.stat().st_size for p in (rd / "parts").glob("ev-*.log"))
                  if a.events_only and (rd / "parts").is_dir() else
                  _run_size(rd / "events") if a.events_only else _run_size(rd))
            print(f"  {run['id']}  {run.get('status_shown') or run.get('status')}  {_size(sz)}"
                  + ("（时序事件）" if a.events_only else ""))
        if not a.yes:
            if not sys.stdin.isatty():
                raise SystemExit(("删时序事件" if a.events_only else "删 run") + "要确认（不能重建）：加 --yes")
            what = " 的时序事件" if a.events_only else ""
            if input(f"删掉这 {len(targets)} 个 run{what}？不能重建。[y/N] ").strip().lower() != "y":
                print("没删")
                return 1
        for run, _ in targets:
            if a.events_only:
                print(f"删了 {_runs.remove_events(repo, run['id'])} 的时序事件")
            else:
                print(f"删了 {_runs.remove(repo, run['id'])}")
        return 0
    if a.verb == "merge":
        run = _runs.merge_run(repo, a.ref)
        print(f"run {run['id']}：从原始数据重算完，状态 {run['status']}"
              + (f"（{'；'.join(run.get('problems') or [])}）" if run.get("problems") else ""))
        return 0
    raise SystemExit(f"不认识的动作 {a.verb}")


_FS = {"changed": "录制后改过", "mismatch": "录制时就和仓库不一致", "gone": "已删除",
       "outside": "不在 index 里", "unknown": "没存哈希"}


def cmd_path(a) -> int:
    from . import path as _path
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    run, rd, phase = _runs.resolve(repo, a.run)
    hot, _ = _runs.load(repo, idx, a.run)
    try:
        p = _path.request_path(idx, rd, run, phase, hot, max_rows=None)
    except LookupError as e:
        raise SystemExit(str(e)) from None
    print(json.dumps(p, ensure_ascii=False) if a.json else _path.format_text(p, a.depth))
    return 0


def cmd_serve(a) -> int:
    from . import serve as _serve
    return _serve.main(Path(a.repo).resolve(), port=a.port, hot=a.hot, home=a.home)


def cmd_app(a) -> int:
    from . import app as _app
    return _app.main(port=a.port, open_browser=not a.no_browser, proxy=a.proxy)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codestrata", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="which", required=True)   # 不能叫 cmd：
                                                       # trace 的位置参数也叫 cmd，会互相覆盖

    def common(p, roots_help="要扫描的目录，相对仓库根（给了就照单全收；不给就自动探测，跳过 tests/examples 这类）"):
        p.add_argument("repo", nargs="?", default=".")
        p.add_argument("--roots", nargs="*", default=None, help=roots_help)

    s = sub.add_parser("scan", help="静态扫描")
    common(s, "要扫描的目录，相对仓库根（给了就照单全收；不给就沿用上次扫描的目录，第一次扫时自动探测、跳过 tests/examples 这类；"
              "--roots 后面不带目录：重新自动探测）")
    s.add_argument("--depth", default="auto",
                   help="默认切面：auto 按规模自动拆分；给数字就展开所有深度小于它的目录（2 = 二级包）")
    s.add_argument("--expand", action="append", default=[], metavar="DIR",
                   help="默认切面里额外展开这个目录（可重复），比如 vllm_omni.model_executor.models")
    s.set_defaults(fn=cmd_scan)

    t = sub.add_parser("trace", help="跑一个 case，记录真实调用")
    common(t, "仓库代码在哪些目录（安装包映射回仓库用）；默认用 scan 时选的目录，没 scan 过才自动探测")
    t.add_argument("--case", required=True,
                   help="这个 case 的名字（字母、数字和 . _ -）。同名 case 重录不覆盖，每次都是新的 run")
    t.add_argument("--timeout", type=float, default=None, help="超过这么多秒就按三级顺序停掉命令")
    t.add_argument("--cwd", default=None, metavar="DIR",
                   help="命令在哪个目录执行（默认仓库根目录；--cwd . 是当前目录）")
    t.add_argument("--stop-grace", type=float, default=90.0,
                   help="停的时候发 SIGINT 之后等多久再发 SIGTERM（默认 90 秒）")
    t.add_argument("--tag", action="append", default=[], help="给 run 打标签，比如 model=Qwen2.5-Omni-7B（可重复）")
    t.add_argument("--note", default=None, help="给 run 写一句备注")
    t.add_argument("--env", action="append", default=[], metavar="K=V",
                   help="给命令加一个环境变量（可重复）；会记进 run，重录命令里也有")
    t.add_argument("--gpu", action="store_true",
                   help="同时录 GPU kernel（CUPTI）：每个 kernel 的起止、流，挂到发起它的那次调用上；要本机有带 CUPTI 的 "
                        "CUDA 工具链（CUDA_HOME，或 nvcc 在 PATH 上）和 g++，要时序事件")
    t.add_argument("--events", action=argparse.BooleanOptionalAction, default=True,
                   help="同时记时序事件（每次调用的起止时刻、谁调的、线程之间谁交给谁；请求路径、时间顺序要它）。默认开，被录的 Python "
                        "低于 3.12 时自动没有；--no-events 关掉")
    t.add_argument("--attach", action="append", default=[], metavar="FILE",
                   help="把这个文件的内容一起存进 run（比如被 case 脚本 source 的 common.sh）")
    t.add_argument("--phase", action="append", default=[], metavar="NAME=FUNC",
                   help="哪个进程第一次进入 FUNC 就切到阶段 NAME（可重复；每个阶段只切一次）。FUNC 写成 "
                        "模块:qualname（查静态索引，继承来的方法也认）或 文件路径:qualname，比如 "
                        "generate=vllm_omni.entrypoints.omni:Omni.generate。不用改被 trace 的脚本")
    t.add_argument("cmd", nargs="*", default=[],
                   help="-- 之后是要跑的命令")
    t.set_defaults(fn=cmd_trace)

    r = sub.add_parser("runs", help="管理录下的 run（ls / show / tag / untag / note / rm / merge）")
    r.add_argument("repo")
    rv = r.add_subparsers(dest="verb", required=True)
    x = rv.add_parser("ls", help="列出所有 run，按 case 分组，新的在前")
    x.add_argument("--case", default=None)
    x = rv.add_parser("show", help="一个 run 的详情、文件相对当前代码的状态、复刻命令")
    x.add_argument("ref", metavar="RUN")
    x = rv.add_parser("tag", help="加标签")
    x.add_argument("ref", metavar="RUN")
    x.add_argument("tags", nargs="+")
    x = rv.add_parser("untag", help="去掉标签")
    x.add_argument("ref", metavar="RUN")
    x.add_argument("tags", nargs="+")
    x = rv.add_parser("note", help="写备注（覆盖原来的）")
    x.add_argument("ref", metavar="RUN")
    x.add_argument("text")
    x = rv.add_parser("rm", help="删掉 run（不能重建，要确认；只认完整的 run id）")
    x.add_argument("refs", nargs="+", metavar="RUN_ID")
    x.add_argument("--yes", action="store_true")
    x.add_argument("--events-only", action="store_true", help="只删时序事件（events/），计数和其余数据留着")
    x = rv.add_parser("merge", help="从原始数据重算计数；录制中断（driver 没了）时从散着的分片合并")
    x.add_argument("ref", metavar="RUN")
    r.set_defaults(fn=cmd_runs)

    v = sub.add_parser("serve", help="本地服务：图 + 源码 + 跳编辑器")
    common(v)
    v.add_argument("--port", type=int, default=8900)
    v.add_argument("--hot", default=None, metavar="RUN")
    v.add_argument("--home", default=None, help=argparse.SUPPRESS)   # 主菜单（codestrata app）起的：回主菜单的链接
    v.set_defaults(fn=cmd_serve)

    pa = sub.add_parser("path", help="请求路径：一个 run（阶段）里每个进程、每个线程按第一次调用排的函数级调用树")
    pa.add_argument("repo", nargs="?", default=".")
    pa.add_argument("run", metavar="RUN", help="run id 或 case 名，可加 @阶段 / @t=起-止（要录了 --events 的 run）")
    pa.add_argument("--depth", type=int, default=None, help="只打这么多层（0 是根）")
    pa.add_argument("--json", action="store_true", help="打印 JSON（和 /api/path 一样）")
    pa.set_defaults(fn=cmd_path)

    m = sub.add_parser("app", help="主菜单：选文件夹、点按钮扫描 / 录制运行 / 打开图（浏览器里）")
    m.add_argument("--port", type=int, default=8930)
    m.add_argument("--no-browser", action="store_true", help="不自动打开浏览器，只打印地址")
    m.add_argument("--proxy", action="store_true",
                   help="图也经这个端口转发（远程用：ssh -L 只转这一个端口）。图页面和主菜单会同源，"
                        "少了一层隔离，所以默认不开")
    m.set_defaults(fn=cmd_app)

    # 自己先按第一个 "--" 切开：argparse 的 REMAINDER 和可选位置参数放在一起时
    # 会互相抢参数（`trace . --case X -- cmd` 会报 --case 缺失）。
    # 命令行、路径里可能有不是 UTF-8 的字节（Python 里是孤立的代理字符）：打印成转义，别崩
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    raw = list(sys.argv[1:] if argv is None else argv)
    invocation = {"argv": _prog(argv is None) + raw, "cwd": _cwd()}
    tail: list[str] = []
    if "--" in raw:
        i = raw.index("--")
        raw, tail = raw[:i], raw[i + 1:]
    a = ap.parse_args(raw)
    if getattr(a, "roots", None):
        a.roots = _scan.clean_roots(a.roots)
    a.invocation = invocation               # trace 存进 run：原样的命令 + 在哪个目录跑的，复刻用
    if a.which == "trace":
        a.cmd = tail or a.cmd
    return a.fn(a)


def _prog(from_argv: bool) -> list[str]:
    """怎么叫起的 codestrata：装好的入口脚本是它的绝对路径；python -m codestrata 是解释器 + -m。"""
    a0 = sys.argv[0] if from_argv and sys.argv else ""
    if a0 and not a0.endswith(("__main__.py", "-c")) and os.path.basename(a0) != "-m":
        return [os.path.abspath(a0)]
    return self_command()


def _cwd() -> str | None:
    try:
        return os.getcwd()
    except OSError:
        return None


if __name__ == "__main__":
    sys.exit(main())
