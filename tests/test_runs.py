"""run 存储和录制的端到端测试：在 CPU 假服务（tests/trace_cases/fake_repo）上跑真的 trace。

    .venv/bin/python tests/test_runs.py            # 全部，约 1.5 分钟
    .venv/bin/python tests/test_runs.py stop merge # 只跑名字里带这些词的

不依赖 pytest。每个用例在临时目录里拷一份假仓库，互不影响。
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from codestrata import payload, runs, trace  # noqa: E402

PY = sys.executable
FAKE = HERE / "trace_cases" / "fake_repo"


def cs(*args, env=None, check=True, timeout=180) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run([PY, "-m", "codestrata", *map(str, args)], capture_output=True, text=True,
                       env=e, timeout=timeout, cwd=HERE.parent)
    if check and r.returncode != 0:
        raise AssertionError(f"codestrata {' '.join(map(str, args))} → {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


_TMP: list[Path] = []


def fresh() -> Path:
    t = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(t)
    d = t / "repo"
    shutil.copytree(FAKE, d)
    cs("scan", d)
    return d


def trace_fake(repo: Path, case="fake", *extra, env=None, check=True):
    return cs("trace", repo, "--case", case, "--env", f"PY={PY}", *extra, "--", "bash", "fake_service.sh",
              env=env, check=check)


def latest(repo: Path) -> tuple[dict, dict, Path]:
    rd = sorted(p for p in (repo / ".codestrata" / "runs").iterdir() if not p.name.startswith("."))[-1]
    return json.loads((rd / "run.json").read_text()), json.loads((rd / "detail.json").read_text()), rd


def no_live(rd: Path) -> None:
    left = trace.leftovers(rd / "parts")
    assert not left, f"还有进程带着这个 run 的环境：{left}"


def wait_phase(repo: Path, name: str, timeout: float = 60) -> Path:
    """等录制中的 run 的 PHASE 变成 name，返回 run 目录。"""
    end = time.monotonic() + timeout
    runs_d = repo / ".codestrata" / "runs"
    while time.monotonic() < end:
        ds = list(runs_d.glob("2*")) if runs_d.is_dir() else []
        if ds and (ds[0] / "parts" / "PHASE").is_file() and (ds[0] / "parts" / "PHASE").read_text().strip() == name:
            return ds[0]
        time.sleep(0.1)
    raise AssertionError(f"等不到阶段 {name}")


def by_argv(detail: dict, needle: str) -> list[dict]:
    return [p for p in detail["procs"] if needle in " ".join(p["argv"] or [])]


# ---------------------------------------------------------------- 用例

def test_ok():
    """正常退出：ok；各进程怎么结束的都记下来；exec 前后两段都在；原始数据打包；阶段有时刻。"""
    repo = fresh()
    r = trace_fake(repo, "fake", "--tag", "model=fake", "--note", "第一次")
    assert "完整录完" in r.stdout, r.stdout
    run, det, rd = latest(repo)
    assert run["status"] == "ok" and run["stop"] == "exit" and run["returncode"] == 0, run
    assert [p["name"] for p in run["phases"]] == ["start", "serving", "shutdown"], run["phases"]
    assert all(p["t_us"] is not None for p in run["phases"])
    assert run["phases"][0]["t_us"] < run["phases"][1]["t_us"] < run["phases"][2]["t_us"]
    assert run["tags"] == ["model=fake"] and run["note"] == "第一次"
    assert run["env"] == {"PY": PY}
    whys = {p["why"] for p in det["procs"]}
    assert whys <= {"atexit", "_exit", "exec"}, det["procs"]
    srv = [p for p in by_argv(det, "fakesvc.server") if p["why"] == "atexit"]
    assert srv, "服务应当收到 SIGINT、走 atexit 正常落盘"
    ex = by_argv(det, "fakesvc.server")
    pre = [p for p in ex if p["why"] == "exec"]
    assert len(pre) == 1 and pre[0]["n_funcs"] >= 2, "exec 之前的数据要在"
    post = [p for p in det["procs"] if p["pid"] == pre[0]["pid"] and p is not pre[0]]
    assert post and "fakesvc.execd" in " ".join(post[0]["argv"]), "exec 之后的新程序单独一份"
    assert any(p["why"] == "_exit" for p in det["procs"]), "multiprocessing 子进程以 os._exit 结束"
    assert not (rd / "parts").exists() and (rd / "parts.tar.gz").is_file()
    assert det["sha_of"] == "executed" and det["file_shas"]
    assert det["script"]["stored"] and (rd / det["script"]["stored"]).read_text().startswith("#!/usr/bin/env bash")
    assert det["pythons"][PY]["version"] == sys.version.split()[0]
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))
    assert set(counts["phases"]) == {"start", "serving", "shutdown"}
    assert any(v == "handle" for v in counts["names"].values()), "要记下 qualname"
    no_live(rd)
    # 叠到图上：serving 阶段里有请求处理，没有启动时的初始化
    idx = payload.load_index(repo)
    hot, meta = payload.load_hot(repo, idx, "fake@serving")
    assert meta["run_id"] == run["id"] and meta["phase"] == "serving" and meta["status"] == "ok"
    assert "fakesvc.work:handle" in hot["symbols"] and "fakesvc.work:init_model" not in hot["symbols"]
    hot_all, _ = payload.load_hot(repo, idx, "fake")
    assert "fakesvc.work:init_model" in hot_all["symbols"]
    assert meta["file_state"] == {} and meta["stale_files"] == []
    for k in ("case", "cmd", "phase", "phases", "n_procs", "unmapped", "stale_files", "mapped_from",
              "n_mapped", "mapped_mismatch", "procs", "script"):
        assert k in meta, f"hot meta 少了老键 {k}"
    assert meta["script"]["saved"] is True


def test_rerecord():
    """同名 case 重录不覆盖；case 名解析到最新一次 ok 的，并打印解析到的 id。"""
    repo = fresh()
    trace_fake(repo)
    first, _, _ = latest(repo)
    time.sleep(1.1)
    trace_fake(repo)
    second, _, _ = latest(repo)
    got = runs.catalog(repo)
    assert {r["id"] for r in got} == {first["id"], second["id"]}
    r = cs("runs", repo, "show", "fake")
    assert f"run {second['id']}" in r.stdout
    # 完整 id 也能用，老的那次仍然在
    r = cs("runs", repo, "show", first["id"] + "@serving")
    assert f"run {first['id']}" in r.stdout


def test_timeout():
    """超时：partial / timeout；case 的 trap 照样停掉 setsid 的服务，服务正常落盘；没有残留。"""
    repo = fresh()
    trace_fake(repo, "fake", "--timeout", "6", env={"FAKE_HANG": "1"})
    run, det, rd = latest(repo)
    assert run["status"] == "partial" and run["stop"] == "timeout", run
    assert "超时" in run["problems"]
    assert any(p["why"] == "atexit" for p in by_argv(det, "fakesvc.server")), det["procs"]
    assert not (rd / "parts").exists()
    no_live(rd)


def test_interrupt():
    """录到一半 Ctrl+C（对 driver 发 SIGINT）：partial / interrupt，服务正常落盘，没有残留。"""
    _interrupt(signal.SIGINT)


def test_hangup():
    """录到一半终端关了（driver 收到 SIGHUP）：和 Ctrl+C 一样收尾，不留孤儿。"""
    _interrupt(signal.SIGHUP)


def _interrupt(sig):
    repo = fresh()
    e = dict(os.environ, FAKE_HANG="1")
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "fake", "--env", f"PY={PY}",
                          "--", "bash", "fake_service.sh"], env=e, cwd=HERE.parent,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait_phase(repo, "hang")
    p.send_signal(sig)
    out, err = p.communicate(timeout=120)
    run, det, rd = latest(repo)
    assert run["status"] == "partial" and run["stop"] == "interrupt", (run, err)
    assert any(x["why"] == "atexit" for x in by_argv(det, "fakesvc.server"))
    no_live(rd)


def test_leftover():
    """case 没停服务就退出、服务还忽略 SIGINT：driver 找到残留进程、跳过 SIGINT，发 SIGTERM 之前
    写 STOP 让落盘线程先落一次（hook 不装 SIGTERM 处理器）。"""
    repo = fresh()
    trace_fake(repo, "fake", "--stop-grace", "3", env={"FAKE_NO_TRAP": "1", "FAKE_IGNORE_INT": "1"})
    run, det, rd = latest(repo)
    assert run["status"] == "partial", run
    assert det["leftovers"], "应当记下残留进程"
    assert all(x["signal"] == "SIGTERM" for x in det["leftovers"]), det["leftovers"]
    srv = by_argv(det, "fakesvc.server")
    assert any(x["why"] == "stop" for x in srv), srv
    assert not (rd / "parts").exists()
    no_live(rd)


def test_leftover_sigint():
    """case 没停服务就退出、服务正常处理 SIGINT：driver 发 SIGINT 就停下了，服务走 atexit。"""
    repo = fresh()
    trace_fake(repo, "fake", env={"FAKE_NO_TRAP": "1"})
    run, det, rd = latest(repo)
    assert det["leftovers"] and all(x["signal"] == "SIGINT" for x in det["leftovers"]), det["leftovers"]
    assert any(x["why"] == "atexit" for x in by_argv(det, "fakesvc.server"))
    no_live(rd)


def test_driver_killed_then_merge():
    """driver 被 kill -9：runs ls 显示「中断」；还有进程在写时 merge 拒绝；停掉它们后 merge 得到 partial。"""
    repo = fresh()
    e = dict(os.environ, FAKE_HANG="1")
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "fake", "--env", f"PY={PY}",
                          "--", "bash", "fake_service.sh"], env=e, cwd=HERE.parent,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rd = wait_phase(repo, "hang")
    p.kill()
    p.wait()
    r = cs("runs", repo, "ls")
    assert "中断" in r.stdout, r.stdout
    r = cs("runs", repo, "merge", rd.name, check=False)
    assert r.returncode != 0 and "还有进程" in (r.stdout + r.stderr), r
    assert trace.leftovers(rd / "parts")
    trace.stop_leftovers(rd / "parts", 5)
    no_live(rd)
    cs("runs", repo, "merge", rd.name)
    run = json.loads((rd / "run.json").read_text())
    assert run["status"] == "partial" and run["stop"] == "driver-lost", run
    assert "status_shown" not in run
    r = cs("runs", repo, "ls")
    assert "中断" not in r.stdout and "partial" in r.stdout, r.stdout
    assert not (rd / "parts").exists() and (rd / "parts.tar.gz").is_file()
    idx = payload.load_index(repo)
    hot, meta = payload.load_hot(repo, idx, rd.name)
    assert "fakesvc.work:handle" in hot["symbols"]


def test_merge_rebuild():
    """runs merge 从 parts.tar.gz 重算，结果和录制时的一样。"""
    repo = fresh()
    trace_fake(repo)
    run, _, rd = latest(repo)
    before = (rd / "counts.json.gz").read_bytes()
    cs("runs", repo, "merge", run["id"])
    assert json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes())) == json.loads(gzip.decompress(before))


def test_file_state():
    """录制之后改了代码、重新 scan：这个文件是 changed；删掉的是 gone；hot 照样能加载。"""
    repo = fresh()
    trace_fake(repo)
    run, _, _ = latest(repo)
    w = repo / "fakesvc" / "work.py"
    w.write_text("# 改一行\n" + w.read_text())
    (repo / "fakesvc" / "execd.py").unlink()
    cs("scan", repo)
    r = cs("runs", repo, "show", run["id"])
    assert "录制后改过" in r.stdout and "fakesvc/work.py" in r.stdout, r.stdout
    assert "已删除" in r.stdout and "fakesvc/execd.py" in r.stdout, r.stdout
    idx = payload.load_index(repo)
    _, meta = payload.load_hot(repo, idx, "fake")
    assert meta["file_state"]["fakesvc/work.py"] == "changed"
    assert meta["file_state"]["fakesvc/execd.py"] == "gone"
    assert "fakesvc/work.py" in meta["stale_files"]


def test_manage():
    """tag / untag / note / rm；.codestrata 带 .gitignore 和 README.txt。"""
    repo = fresh()
    trace_fake(repo)
    run, _, rd = latest(repo)
    cs("runs", repo, "tag", "fake", "a=1", "b")
    cs("runs", repo, "untag", "fake", "b")
    cs("runs", repo, "note", "fake", "一句备注")
    got = json.loads((rd / "run.json").read_text())
    assert got["tags"] == ["a=1"] and got["note"] == "一句备注"
    assert (repo / ".codestrata" / ".gitignore").read_text().strip() == "*"
    assert "runs/" in (repo / ".codestrata" / "README.txt").read_text()
    r = cs("runs", repo, "rm", run["id"], check=False)          # 没有 --yes、不是终端：拒绝
    assert r.returncode != 0 and rd.exists()
    r = cs("runs", repo, "rm", "fake", "--yes", check=False)     # case 名不行：只认完整 id
    assert r.returncode != 0 and run["id"] in r.stderr and rd.exists(), r.stderr
    cs("runs", repo, "rm", run["id"], run["id"], "--yes")        # 重复写两遍：删一次，不报错
    assert not rd.exists()
    r = cs("runs", repo, "show", "fake", check=False)
    assert r.returncode != 0 and "没有叫" in (r.stdout + r.stderr)


def test_bad_names():
    repo = fresh()
    r = cs("trace", repo, "--case", "a/b", "--", "true", check=False)
    assert r.returncode != 0 and "case 名" in r.stderr
    r = cs("trace", repo, "--case", "x", "--tag", "a b", "--", "true", check=False)
    assert r.returncode != 0 and "tag" in r.stderr


def test_migrate_legacy():
    """老格式 trace-<case>.json + parts-<case>/ 迁进 runs/：计数逐键相等，老文件留在 legacy/，
    argv 被截断的老进程标出来。几个进程同时触发迁移只得到一个 run。"""
    repo = fresh()
    trace_fake(repo)
    run, det, rd = latest(repo)
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    tot = runs._sum(counts)
    old = {"case": "old", "cmd": ["bash", "fake_service.sh"], "returncode": 0,
           "pids": [{"pid": 1, "argv": ["python", "-m", "fakesvc.server", "--port", "1", "--ready"],
                     "n_funcs": 3}],
           "funcs": tot["funcs"], "func_edges": tot["func_edges"], "file_edges": {},
           "mapped": {}, "phases": counts, "file_shas": det["file_shas"]}
    cdir = repo / ".codestrata"
    (cdir / "trace-old.json").write_text(json.dumps(old))
    (cdir / "parts-old").mkdir()
    (cdir / "parts-old" / "part-1.json").write_text("{}")
    idx = payload.load_index(repo)
    want = payload.load_hot(repo, idx, run["id"])[0]
    runs._MIGRATED.clear()
    procs = [subprocess.Popen([PY, "-m", "codestrata", "runs", str(repo), "ls"], cwd=HERE.parent,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outs = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), outs
    olds = [r for r in runs.catalog(repo) if r["case"] == "old"]
    assert len(olds) == 1, olds
    assert not (cdir / "trace-old.json").exists() and not (cdir / "parts-old").exists()
    ord_ = cdir / "runs" / olds[0]["id"]
    assert json.loads(gzip.decompress((ord_ / "legacy" / "trace-old.json.gz").read_bytes())) == old
    got = payload.load_hot(repo, idx, "old")
    a, b = dict(got[0]), dict(want)
    a.pop("run"), b.pop("run")
    assert a == b
    assert got[1]["procs"][0]["cut"] is True, "老 trace 的 argv 被截断要标出来"


# ---------------------------------------------------------------- 评审发现的问题的回归测试

def test_dump_race():
    """落盘线程的定时落盘和进程退出时的落盘撞在一起：分片不能写坏（以前两边写同一个 .tmp）。"""
    repo = fresh()
    body = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(20000))
    (repo / "fakesvc" / "big.py").write_text(body + "\ndef run_all():\n    return sum(globals()[f'f{i}']() for i in range(20000))\n")
    # 在 hook 的第 10 秒定时落盘前后退出（有的走 atexit，有的走 os._exit）
    script = ("import os, sys, time; t0 = time.monotonic(); from fakesvc import big; big.run_all(); "
              "k = int(sys.argv[1]); time.sleep(max(0, 9.985 + k * 0.004 - (time.monotonic() - t0))); "
              "os._exit(0) if k % 2 else None")
    cmd = " & ".join(f"{PY} -c '{script}' {k}" for k in range(8)) + " & wait"
    cs("trace", repo, "--case", "race", "--", "bash", "-c", cmd, timeout=120)
    run, det, rd = latest(repo)
    assert "读不出来" not in " ".join(run["problems"]), run["problems"]
    ps = [p for p in det["procs"] if "run_all" in " ".join(p["argv"] or []) or p["n_funcs"] > 10000]
    assert len(ps) == 8 and all(p["n_funcs"] > 20000 for p in ps), [(p["why"], p["n_funcs"]) for p in det["procs"]]
    assert all(p["why"] in ("atexit", "_exit") for p in ps), [p["why"] for p in ps]


def test_leftover_by_part_file():
    """setproctitle 会清空 /proc/<pid>/environ：靠分片里记的 (pid, 启动时刻) 也要认得出。"""
    d = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(d)
    p = subprocess.Popen(["sleep", "30"])
    try:
        st = trace._proc_start(p.pid)
        (d / f"part-{p.pid}-1.json").write_text(json.dumps({"st": st}))
        assert trace.leftovers(d) == [p.pid]
        (d / f"part-{p.pid}-1.json").write_text(json.dumps({"st": st + 1}))   # pid 被复用了
        assert trace.leftovers(d) == []
    finally:
        p.kill()
        p.wait()


def test_program_semantics():
    """hook 不改变被 trace 程序的行为：SIGTERM 还是默认处理，os._exit(status=) 照常。"""
    repo = fresh()
    r = cs("trace", repo, "--case", "sem", "--", PY, "-c",
           "import signal, os; from fakesvc import work; work.init_model(); "
           "print('SIG', signal.getsignal(signal.SIGTERM) is signal.SIG_DFL, flush=True); os._exit(status=3)",
           check=False)
    run, _, _ = latest(repo)
    assert "SIG True" in r.stdout, r.stdout
    assert run["returncode"] == 3, run


def test_nohup():
    """driver 在 nohup 下（SIGHUP 被忽略）：终端关掉不打断录制。"""
    repo = fresh()
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "nh", "--",
                          PY, "-c", "import time; from fakesvc import work; work.init_model(); time.sleep(3)"],
                         cwd=HERE.parent,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    time.sleep(1.5)
    p.send_signal(signal.SIGHUP)
    p.wait(timeout=60)
    run, _, _ = latest(repo)
    assert run["status"] == "ok" and run["stop"] == "exit", run


def test_sigquit():
    """Ctrl+\\（SIGQUIT）：driver 不死，跳过 SIGINT 那一级直接停，不留孤儿。"""
    repo = fresh()
    e = dict(os.environ, FAKE_HANG="1")
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "q", "--env", f"PY={PY}",
                          "--", "bash", "fake_service.sh"], env=e, cwd=HERE.parent,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rd = wait_phase(repo, "hang")
    t = time.monotonic()
    p.send_signal(signal.SIGQUIT)
    p.wait(timeout=60)
    run = json.loads((rd / "run.json").read_text())
    assert run["stop"] == "interrupt" and run["status"] == "partial", run
    assert time.monotonic() - t < 30, "SIGQUIT 不该等 SIGINT 的 90 秒"
    no_live(rd)


def test_merge_union_and_keep_capture():
    """收尾时 parts/ 没删干净：merge 取包和散文件的并集，不拿少的盖多的；录制时存下的脚本、
    哈希不被 merge 改写。"""
    repo = fresh()
    trace_fake(repo)
    run, det, rd = latest(repo)
    before = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))
    with tarfile.open(rd / "parts.tar.gz", "r:gz") as tf:
        names = sorted(m.name for m in tf.getmembers())
        (rd / "parts").mkdir()
        tf.extract(names[0], rd / "parts")          # 只剩一个散文件（rmtree 删到一半）
    (repo / "fake_service.sh").write_text("# 录制之后改的\n")
    w = repo / "fakesvc" / "work.py"
    w.write_text("# 改\n" + w.read_text())
    cs("runs", repo, "merge", run["id"])
    with tarfile.open(rd / "parts.tar.gz", "r:gz") as tf:
        assert sorted(m.name for m in tf.getmembers()) == names
    assert json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes())) == before
    det2 = json.loads((rd / "detail.json").read_text())
    assert det2["file_shas"] == det["file_shas"] and det2["files"] == det["files"]
    assert (rd / det["script"]["stored"]).read_text().startswith("#!/usr/bin/env bash")
    assert not (rd / "parts").exists()


def test_rm_live_refused():
    """还在录的 run 不能删（case 名也解析不到它身上去）。"""
    repo = fresh()
    e = dict(os.environ, FAKE_HANG="1")
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "lv", "--env", f"PY={PY}",
                          "--", "bash", "fake_service.sh"], env=e, cwd=HERE.parent,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rd = None
        for _ in range(100):
            ds = list((repo / ".codestrata" / "runs").glob("2*")) if (repo / ".codestrata" / "runs").is_dir() else []
            if ds and (ds[0] / "run.json").is_file():
                rd = ds[0]
                break
            time.sleep(0.1)
        r = cs("runs", repo, "rm", rd.name, "--yes", check=False)
        assert r.returncode != 0 and "录制中" in r.stderr and rd.exists(), r
    finally:
        p.send_signal(signal.SIGINT)
        p.wait(timeout=120)


def test_legacy_unicode_case():
    """老版本允许的 case 名（中文、+）：迁移后原名照样能 --hot。"""
    repo = fresh()
    trace_fake(repo)
    run, det, rd = latest(repo)
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    tot = runs._sum(counts)
    old = {"case": "双工+v2", "cmd": ["x"], "returncode": 0, "pids": [], "funcs": tot["funcs"],
           "func_edges": tot["func_edges"], "mapped": {}, "phases": {}, "file_shas": {}}
    (repo / ".codestrata" / "trace-双工+v2.json").write_text(json.dumps(old, ensure_ascii=False))
    runs._MIGRATED.clear()
    idx = payload.load_index(repo)
    hot, meta = payload.load_hot(repo, idx, "双工+v2")
    assert meta["case"] == "双工+v2" and meta["phases"] == {} and hot["symbols"]


def test_single_phase_and_extras():
    """没写 PHASE 的 run：meta.phases 为空（前端不说「分了阶段」）；大的 --attach 也存；
    非 UTF-8 的参数不崩；超长 argv 标 argv_cut；重录命令带上 --timeout 和 --attach。"""
    repo = fresh()
    big = repo / "big.yaml"
    big.write_text("x: " + "a" * 300_000 + "\n")
    cs("trace", repo, "--case", "one", "--timeout", "60", "--attach", "big.yaml",
       "--", PY, "-c", "from fakesvc import work; work.init_model()", "é\udcff",    # \udcff：命令行里的 0xff 字节
       *[str(i) for i in range(80)])
    run, det, rd = latest(repo)
    assert run["status"] == "ok", run
    assert any(f["why"] == "attach" and f["path"].endswith("big.yaml") for f in det["files"]), det["files"]
    assert any(p["argv_cut"] for p in det["procs"]), det["procs"]
    idx = payload.load_index(repo)
    _, meta = payload.load_hot(repo, idx, "one")
    assert meta["phases"] == {}, meta["phases"]
    r = cs("runs", repo, "show", "one")
    assert "--timeout=60" in r.stdout and "--attach=" in r.stdout, r.stdout


def test_nonexistent_repo():
    d = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(d)
    r = cs("runs", d / "no" / "such", "ls", check=False)
    assert r.returncode != 0 and not (d / "no").exists()


def test_edit_during_recording():
    """录制过程中改了被跑到的文件：记下的是执行时的哈希，重新 scan 后标成 changed，
    run 本身也标出「录制过程中被改过」。"""
    repo = fresh()
    cs("trace", repo, "--case", "ed", "--", "bash", "-c",
       f"{PY} -c 'from fakesvc import work; work.init_model(); work.compute(1)'; sed -i '1i # edited' fakesvc/work.py")
    run, det, rd = latest(repo)
    assert "fakesvc/work.py" in det["changed_during"], det
    assert any("录制过程中被改过" in x for x in run["problems"]), run["problems"]
    cs("scan", repo)
    idx = payload.load_index(repo)
    _, meta = payload.load_hot(repo, idx, "ed")
    assert meta["file_state"].get("fakesvc/work.py") == "changed", meta["file_state"]


# ---------------------------------------------------------------- 时序事件（M3）

def _spans(rd: Path):
    from codestrata import events
    keys = json.loads((rd / "events" / "spans" / "keys.json").read_text())
    out = []
    for t0, dur, tid, depth, a, b, rep, ns in events.read_spans(rd / "events" / "spans"):
        out.append({"t0": t0, "dur": dur, "tid": tid, "depth": depth, "a": keys["keys"][a], "b": keys["keys"][b],
                    "rep": rep, "susp": ns})
    return out, keys


def _line(repo: Path, rel: str, needle: str) -> str:
    """函数在文件里的首行号 → 键 rel:行"""
    for i, ln in enumerate((repo / rel).read_text().splitlines(), 1):
        if ln.startswith(needle):
            return f"{rel}:{i}"
    raise AssertionError(f"{rel} 里没有 {needle}")


def test_events_truth():
    """7.1 的真值：同步嵌套、返回后再调、生成器、异常、asyncio 交错、多线程、fork、exec 都配对正确；
    span 的调用次数之和 = 计数里跨文件的 func_edges 之和。"""
    repo = fresh()
    cs("trace", repo, "--case", "truth", "--events", "--", PY, "-m", "fakesvc.truth")
    run, det, rd = latest(repo)
    assert run["status"] == "ok" and run["events"]["n_spans"] > 0, run
    sp, keys = _spans(rd)
    T, C, O = "fakesvc/truth.py", "fakesvc/callee.py", "fakesvc/other.py"
    k = lambda rel, fn: _line(repo, rel, f"def {fn}(") if not fn.startswith("async ") else _line(repo, rel, fn + "(")
    def one(a, b):
        got = [s for s in sp if s["a"] == a and s["b"] == b]
        assert len(got) >= 1, (a, b, [(s["a"], s["b"]) for s in sp])
        return got
    # 半路丢掉的生成器：只挂起过一次、没返回；之后同文件生成器里的调用深度是 0（不挂在死掉的 span 下）
    dropped = one(k(T, "s_drop"), k(C, "gen")) + one(k(T, "_started_gen"), k(C, "gen"))
    assert len(dropped) == 25 and all(s["susp"] == 1 and s["dur"] == -1 for s in dropped), dropped
    assert all(s["depth"] == 0 for s in one(k(T, "local_gen"), k(C, "one"))), one(k(T, "local_gen"), k(C, "one"))
    # close() / 取消：清理代码里的调用，调用方是生成器 / 协程自己，深一层
    gc = one(k(T, "s_close"), k(C, "gen_cleanup"))[0]
    fin = one(k(C, "gen_cleanup"), k(O, "deep"))[0]
    assert fin["depth"] == gc["depth"] + 1, (gc, fin)
    one(k(C, "async def serve_cancel"), k(O, "deep"))
    # 两个协程交错：各自的子调用各合各的（每条最多 2 次），总数 4
    h = one(k(C, "async def handle2"), k(O, "deep"))
    assert all(s["rep"] <= 2 for s in h) and sum(s["rep"] for s in h) == 4, h
    # 先后起的四个线程（glibc 会复用 ident）：各有各的名字
    names = {n for ts in keys["threads"].values() for n in ts.values()}
    assert {"req-0", "req-1", "req-2", "req-3"} <= names, names
    # 第一级折叠：50 次叶子调用合成一条；有跨文件子调用的 mid 不合
    lp = one(k(T, "s_loop"), k(C, "one"))
    assert len(lp) == 1 and lp[0]["rep"] == 50 and lp[0]["dur"] >= 0, lp
    assert len(one(k(T, "s_loop"), k(C, "mid"))) == 3
    # 同步嵌套：deep 在 mid 里面，深一层
    mid = one(k(T, "s_nest"), k(C, "mid"))[0]
    deep = [d for d in one(k(C, "mid"), k(O, "deep"))
            if mid["t0"] <= d["t0"] and d["t0"] + d["dur"] <= mid["t0"] + mid["dur"]]
    assert len(deep) == 1 and deep[0]["depth"] == mid["depth"] + 1, (mid, deep)
    # 返回后再调用：two 的调用方是 s_seq，不是 one
    one(k(T, "s_seq"), k(C, "one"))
    one(k(T, "s_seq"), k(C, "two"))
    assert not [s for s in sp if s["a"] == k(C, "one")]
    # 生成器：挂起 3 次，最后返回
    g = one(k(T, "s_gen"), k(C, "gen"))[0]
    assert g["susp"] == 3 and g["dur"] >= 0
    # 异常展开也算返回
    assert one(k(T, "s_exc"), k(C, "boom"))[0]["dur"] >= 0
    # asyncio 交错：先开始的 a（20ms）先结束，后开始的 b（60ms）——按栈配对会配反
    w = sorted(one(k(T, "async def runner"), k(C, "async def work")), key=lambda s: s["t0"])
    assert len(w) == 2 and all(s["susp"] >= 1 for s in w), w
    assert 15_000 <= w[0]["dur"] <= 45_000 and w[1]["dur"] >= 55_000, w
    # 多线程：s_threads 的两个线程同时跑（时间重叠）、s_threads2 的四个先后跑，六个不同的号
    th = sorted(one(k(T, "in_thread"), k(C, "slow")), key=lambda s: s["t0"])
    assert len(th) == 6 and len({s["tid"] for s in th}) == 6, th
    assert any(a["t0"] < b["t0"] < a["t0"] + a["dur"] for a, b in zip(th, th[1:])), th
    names = {n for ts in keys["threads"].values() for n in ts.values()}
    assert {"worker-0", "worker-1"} <= names, names
    # fork：子进程自己一份，fork 之前的调用不归它
    idx = json.loads((rd / "events" / "spans" / "index.json").read_text())
    main_pid = next(p["pid"] for p in idx["procs"] if p["n_spans"] >= 8)
    fk = one(k(T, "s_fork"), k(C, "child_work"))[0]
    assert fk is not None
    kids = [p for p in idx["procs"] if p["ppid"] == main_pid]
    assert len(kids) >= 3, idx["procs"]           # fork 的子进程 + exec 前后各一份
    # exec：exec_child 没返回（-1），exec 之后的新程序单独一份，线程号接着编（不互相覆盖名字）
    ex = one(k(T, "s_exec"), k(C, "exec_child"))[0]
    assert ex["dur"] == -1
    post = one("fakesvc/execd.py:0", k("fakesvc/work.py", "after_exec"))[0]
    assert post["tid"] != ex["tid"], (ex, post)
    # 次数对得上：Σrep = 跨文件的 func_edges
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    xf = sum(v for ph in counts.values() for e, v in ph["func_edges"].items()
             if e.split("|")[0].rpartition(":")[0] != e.split("|")[1].rpartition(":")[0])
    assert run["events"]["n_calls"] == xf, (run["events"], xf)


def test_events_fake_service():
    """真的服务形状（setsid 服务、multiprocessing、asyncio、分阶段）：事件和计数对得上，
    runs merge 重建出一样的 span，rm --events-only 只删事件。"""
    repo = fresh()
    trace_fake(repo, "fake", "--events")
    run, det, rd = latest(repo)
    assert run["status"] == "ok" and run["events"] and not run["events"]["truncated"], run
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    xf = sum(v for ph in counts.values() for e, v in ph["func_edges"].items()
             if e.split("|")[0].rpartition(":")[0] != e.split("|")[1].rpartition(":")[0])
    assert run["events"]["n_calls"] == xf, (run["events"], xf)
    # serving 阶段的时间窗里有请求处理（handle → work 的调用）
    ph = {p["name"]: p["t_us"] for p in run["phases"]}
    sp, _ = _spans(rd)
    hs = [s for s in sp if s["b"].startswith("fakesvc/work.py") and ph["serving"] <= s["t0"] < ph["shutdown"]]
    assert hs, "serving 阶段应当有跨文件调用"
    with tarfile.open(rd / "events" / "raw.tar.gz", "r:gz") as tf:
        assert all(m.name.startswith("ev-") for m in tf.getmembers())
    with tarfile.open(rd / "parts.tar.gz", "r:gz") as tf:
        assert not any(m.name.startswith("ev-") for m in tf.getmembers())
    before = sorted(map(tuple, (list(s.values()) for s in sp)))
    cs("runs", repo, "merge", run["id"])
    after, _ = _spans(rd)
    assert sorted(map(tuple, (list(s.values()) for s in after))) == before
    assert json.loads((rd / "run.json").read_text())["events"]["bytes"] == run["events"]["bytes"] \
        == (rd / "events" / "raw.tar.gz").stat().st_size      # 一律是压缩包的大小
    r = cs("runs", repo, "show", run["id"])
    assert "时序" in r.stdout and "--events" in r.stdout, r.stdout
    cs("runs", repo, "rm", run["id"], "--events-only", "--yes")
    assert not (rd / "events").exists() and (rd / "counts.json.gz").is_file()
    assert json.loads((rd / "run.json").read_text())["events"] is None


def test_events_cap():
    """每个进程的行数上限：到了就不再记新的调用，标 truncated；计数完整，所以 run 仍是 ok
    （case 名不会因此跳到更早的一次）。上限之前开始、之后才返回的调用照样有返回时刻。
    上限写成 3e6 这种、甚至写错了，都不能让 hook 整个失效。"""
    repo = fresh()
    cs("trace", repo, "--case", "cap", "--events", "--env", "CODESTRATA_EV_MAX=1", "--", PY, "-m", "fakesvc.truth")
    run, _, rd = latest(repo)
    assert run["events"]["truncated"] and run["status"] == "ok", run
    counts = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    assert sum(len(ph["funcs"]) for ph in counts.values()) > 10
    sp, _ = _spans(rd)
    first = min((s for s in sp if s["a"].startswith("fakesvc/truth.py")), key=lambda s: s["t0"])
    assert first["dur"] >= 0, first               # truth 导入 callee：之后才返回，也要有返回
    # 从 shell 继承来的上限也记进 run（重录命令里带上）
    cs("trace", repo, "--case", "cap3", "--events", "--", PY, "-m", "fakesvc.truth", env={"CODESTRATA_EV_MAX": "2"})
    run, _, _ = latest(repo)
    assert run["env"].get("CODESTRATA_EV_MAX") == "2" and run["events"]["truncated"], run
    assert "CODESTRATA_EV_MAX=2" in cs("runs", repo, "show", run["id"]).stdout
    for bad in ("3e6", "abc"):
        cs("trace", repo, "--case", "cap2", "--events", "--env", f"CODESTRATA_EV_MAX={bad}", "--",
           PY, "-m", "fakesvc.truth")
        run, _, _ = latest(repo)
        assert run["status"] == "ok" and run["events"]["n_calls"] > 10 and not run["events"]["truncated"], run


def test_events_parse_partial_line():
    """进程被杀时最后一行可能只写了一半：字段正好够数也不要。"""
    from codestrata import events
    d = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(d)
    f = d / "ev-300-1000.log"
    f.write_text("H 300 1000 1\nN 1 MainThread\nK 1 a.py:1\nK 2 b.py:1\nC 10 1 5 1 2\nR 20 1 5\nC 30 1 57 1 2\nR 900 1 5")
    log = events.parse(f)
    assert [e[0] for e in log["ev"]] == ["C", "R", "C"], log["ev"]
    sp = events.pair(log)
    assert sp[0][1] == 20 and sp[1][1] is None, sp


def test_events_pair_duplicates():
    """落盘重试可能把一批行写两遍：重复的调用、再挂起、再恢复都不算，深度和父亲不乱。"""
    from codestrata import events
    log = {"ev": [("C", 1, 1, 1, 1, 2), ("Y", 2, 1, 1, 0, 0), ("S", 3, 1, 1, 0, 0), ("S", 3, 1, 1, 0, 0),
                  ("Y", 4, 1, 1, 0, 0), ("Y", 4, 1, 1, 0, 0), ("S", 5, 1, 1, 0, 0), ("R", 6, 1, 1, 0, 0),
                  ("C", 7, 1, 2, 1, 2), ("C", 7, 1, 2, 1, 2), ("R", 8, 1, 2, 0, 0)], "keys": {}, "threads": {}}
    sp = events.pair(log)
    assert len(sp) == 2 and sp[0][6] == 2 and sp[0][7] == 0, sp        # 挂起 2 次，没有孩子
    assert sp[1][3] == 0 and sp[1][8] == 0, sp                           # 深度 0、没有父亲


def test_events_rm_unmerged():
    """录制中断、还没 merge 的 run：rm --events-only 之后再 merge，事件不会又整理出来。"""
    repo = fresh()
    e = dict(os.environ, FAKE_HANG="1")
    p = subprocess.Popen([PY, "-m", "codestrata", "trace", str(repo), "--case", "u", "--events", "--env", f"PY={PY}",
                          "--", "bash", "fake_service.sh"], env=e, cwd=HERE.parent,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rd = wait_phase(repo, "hang")
    p.kill()
    p.wait()
    trace.stop_leftovers(rd / "parts", 5)
    cs("runs", repo, "rm", rd.name, "--events-only", "--yes")
    cs("runs", repo, "merge", rd.name)
    run = json.loads((rd / "run.json").read_text())
    assert run.get("events") is None and not (rd / "events").exists(), run


def main(argv):
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    if argv:
        tests = [(n, f) for n, f in tests if any(a in n for a in argv)]
    bad = 0
    for n, f in tests:
        t = time.monotonic()
        try:
            f()
            print(f"  ✓ {n}  {time.monotonic() - t:.1f}s", flush=True)
        except Exception as e:
            bad += 1
            import traceback
            print(f"  ✗ {n}\n" + "".join(traceback.format_exception(e))[-3000:], flush=True)
    if not bad:                              # 失败时留着现场
        for t in _TMP:
            shutil.rmtree(t, ignore_errors=True)
    print("全部通过" if not bad else f"{bad} 个失败（临时目录留着：{' '.join(map(str, _TMP))}）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
