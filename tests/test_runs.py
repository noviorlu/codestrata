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
    """最新录的那个 run。按录制时刻（单调时钟）排，不按目录名——同一秒里录的两个，名字的先后看 case 名"""
    def when(p):
        try:
            return (json.loads((p / "run.json").read_text()).get("clock") or {}).get("mono0_ns") or 0
        except (OSError, ValueError):
            return 0
    rd = max((p for p in (repo / ".codestrata" / "runs").iterdir() if not p.name.startswith(".")), key=when)
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


def test_collect_files_skips_installed_py():
    """命令行里安装包中的 .py（py-cpuinfo 自己起自己）不存；安装包里的 yaml 配置、仓库里的脚本照存。"""
    t = fresh()
    sp = t / "venv" / "lib" / "python3.12" / "site-packages"
    (sp / "cpuinfo").mkdir(parents=True)
    (sp / "cpuinfo" / "cpuinfo.py").write_text("print(1)\n")
    (sp / "pkg" / "deploy").mkdir(parents=True)
    (sp / "pkg" / "deploy" / "x.yaml").write_text("a: 1\n")
    (t / "demo.py").write_text("print(2)\n")
    procs = [{"argv": ["python", str(sp / "cpuinfo" / "cpuinfo.py"), "--json"]},
             {"argv": ["python", "demo.py", f"--deploy-config={sp / 'pkg' / 'deploy' / 'x.yaml'}"]}]
    got = {Path(f["abs"]).name: f["why"] for f in runs._collect_files(t, t, procs, None, [])}
    assert got == {"demo.py": "argv", "x.yaml": "argv"}, got
    # --attach 点名要的不受这条限制
    got = {Path(f["abs"]).name for f in runs._collect_files(t, t, [], None, [str(sp / "cpuinfo" / "cpuinfo.py")])}
    assert got == {"cpuinfo.py"}, got


def trace_offline(repo: Path, case="off", *extra, env=None, check=True):
    return cs("trace", repo, "--case", case, *extra, "--", PY, "-m", "fakesvc.offline", env=env, check=check)


def phase_counts(rd: Path) -> dict:
    """{阶段: {文件:qualname: 次数}}（按名字，不按行号：fake_repo 的文件改了行号测试照样对）"""
    c = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))
    nm = c.get("names") or {}
    return {ph: {k.rpartition(":")[0] + ":" + nm.get(k, k.rpartition(":")[2]): n for k, n in d["funcs"].items()}
            for ph, d in c["phases"].items()}


def test_hook_template_parses():
    """注入的 sitecustomize 本身是合法的 Python（模板里的 \n 要写成 \\n，少一层就是语法错误，
    所有进程都静默不录）。"""
    import ast
    ast.parse(trace._SITECUSTOMIZE)


def test_phase_at():
    """--phase 名字=函数：一条阻塞的 python 命令也能分段。模块:qualname 查索引，继承来的方法
    （Engine.close → BaseEngine.close）也认；别的进程（fork 出来的工作进程）跟着切，
    generate 期间它干的活算进 generate；阶段时刻是切换那一刻的精确时间。"""
    repo = fresh()
    r = trace_offline(repo, "off", "--phase", "generate=fakesvc.offline:Engine.generate",
                      "--phase", "shutdown=fakesvc.offline:Engine.close")
    assert "继承来的" in r.stderr and "BaseEngine.close" in r.stderr, r.stderr
    run, _, rd = latest(repo)
    assert [p[0] for p in run["phase_log"]] == ["start", "generate", "shutdown"], run["phase_log"]
    ts = [p[1] for p in run["phase_log"]]
    assert ts == sorted(ts) and ts[1] > ts[0], ts
    assert [t["qualname"] for t in run["rec"]["phase_at"]] == ["Engine.generate", "BaseEngine.close"]
    # 时刻是 hook 切换那一刻（PHASE 第二行 / 标记文件里的 monotonic_ns），不是 driver 轮询看到的时刻
    with tarfile.open(rd / "parts.tar.gz") as tf:
        fired = tf.extractfile("PHASE-generate.fired").read().decode().split()
    assert fired[0] == "hook" and ts[1] == (int(fired[2]) - run["clock"]["mono0_ns"]) // 1000, (ts, fired)
    pc = phase_counts(rd)
    gen, close, compute, load = ("fakesvc/offline.py:Engine.generate", "fakesvc/offline.py:BaseEngine.close",
                                 "fakesvc/work.py:compute", "fakesvc/work.py:load_weight")
    assert pc["generate"].get(gen) == 1 and gen not in pc["start"], pc   # 触发的这次调用算进新阶段
    assert pc["generate"].get(compute) == 3 and compute not in pc["start"], pc   # 工作进程跟着切了
    assert pc["start"].get(load) == 3 and load not in pc["generate"], pc
    assert pc["shutdown"].get(close) == 1 and close not in pc["generate"], pc
    # 没有触发的阶段在 CLI 里报出来；这里都切到了
    assert "没切到" not in r.stdout, r.stdout


def test_phase_at_once_and_order():
    """每个阶段整个 run 只切一次，顺序按实际发生：写 --phase 的先后不影响。work 由工作进程第一次进
    compute 切出来；close 之后主进程才第一次进 compute，不会把阶段切回 work。
    文件路径:qualname 的写法不查索引。没被调用的 --phase 报「没切到」。"""
    repo = fresh()
    r = trace_offline(repo, "off2", "--phase", "shutdown=fakesvc/offline.py:BaseEngine.close",
                      "--phase", "work=fakesvc/work.py:compute", "--phase", "never=fakesvc/work.py:pre_exec",
                      env={"OFFLINE_LATE": "1"}, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    run, _, rd = latest(repo)
    assert [p[0] for p in run["phase_log"]] == ["start", "work", "shutdown"], run["phase_log"]
    pc = phase_counts(rd)
    compute = "fakesvc/work.py:compute"
    assert pc["work"].get(compute) == 3, pc
    assert pc["shutdown"].get(compute) == 1, pc                 # 主进程后来的那次：还在 shutdown
    assert "never" in r.stdout and "没切到" in r.stdout, r.stdout
    # 文件路径写法：Engine.close 在这个文件里没定义（是继承的），按源码核对要报错并给出同名的
    r = trace_offline(repo, "off3", "--phase", "x=fakesvc/offline.py:Engine.close", check=False)
    assert r.returncode != 0 and "BaseEngine.close" in r.stdout + r.stderr, r.stdout + r.stderr


def test_phase_at_errors():
    """写错的 --phase 在跑命令之前就报（不等模型加载完）。"""
    repo = fresh()
    for spec, want in [("start=fakesvc.offline:Engine.generate", "不能叫 start"),
                       ("generate", "名字=函数"),
                       ("a b=fakesvc.offline:Engine.generate", "字母、数字"),
                       ("g=fakesvc.offline:Engin.generate", "fakesvc.offline:Engine.generate"),
                       ("g=fakesvc/nope.py:f", "没有这个文件"),
                       ("g=../outside.py:f", "不在仓库"),
                       ("g=Engine.generate", "模块:qualname")]:
        r = trace_offline(repo, "bad", "--phase", spec, check=False)
        out = r.stdout + r.stderr
        assert r.returncode != 0 and want in out, (spec, out)
    r = trace_offline(repo, "bad", "--phase", "a=fakesvc/work.py:compute", "--phase", "a=fakesvc/work.py:compute",
                      check=False)
    assert r.returncode != 0 and "重复" in r.stdout + r.stderr
    rs = repo / ".codestrata" / "runs"
    assert not (rs.is_dir() and any(p.name.endswith("-bad") for p in rs.iterdir()))   # 一个 run 都没建
    # 没 scan 过的仓库：模块写法要先 scan，文件路径写法照样能用
    t = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(t)
    bare = t / "repo"
    shutil.copytree(FAKE, bare)
    r = trace_offline(bare, "bare", "--phase", "g=fakesvc.offline:Engine.generate", check=False)
    assert r.returncode != 0 and "scan" in r.stdout + r.stderr
    trace_offline(bare, "bare", "--phase", "g=fakesvc/offline.py:Engine.generate")
    run, _, _ = latest(bare)
    assert [p[0] for p in run["phase_log"]] == ["start", "g"], run["phase_log"]


def test_rerun_command_reproduces():
    """run 里存了原样的命令和当时的目录：runs show 打印的复刻命令照抄就能再录一次（同样的阶段）；
    UI 的元数据里也有。录制时 shell 里相关的环境变量另存（像密钥的不存，--env 写明的不重复）。"""
    repo = fresh()
    trace_offline(repo, "rr", "--events", "--phase", "generate=fakesvc.offline:Engine.generate",
                  "--env", "CUDA_VISIBLE_DEVICES=0",
                  env={"VLLM_FAKE_KNOB": "7", "HF_TOKEN": "hf_secret", "MY_API_KEY": "x", "CUDA_VISIBLE_DEVICES": "5"})
    run, _, rd = latest(repo)
    inv = run["invocation"]
    assert inv["argv"][:3] == [PY, "-m", "codestrata"] and inv["cwd"] == str(HERE.parent), inv
    ei = run["env_inherited"]
    assert ei.get("VLLM_FAKE_KNOB") == "7" and "HF_TOKEN" not in ei and "MY_API_KEY" not in ei, ei
    assert "CUDA_VISIBLE_DEVICES" not in ei, ei                  # --env 已经写明了
    show = cs("runs", repo, "show", run["id"]).stdout
    line = next(ln for ln in show.splitlines() if ln.strip().startswith("复刻"))
    cmd = line.split("复刻", 1)[1].strip()
    assert cmd.startswith("cd ") and "--phase generate=fakesvc.offline:Engine.generate" in cmd, cmd
    assert "VLLM_FAKE_KNOB=7" in show and "hf_secret" not in show, show
    idx = payload.load_index(repo)
    _, meta = payload.load_hot(repo, idx, run["id"])
    assert meta["rerun"] == cmd and meta["rerun_exact"] is True, meta["rerun"]
    assert meta["rerun_env"].startswith("cd ") and "env " in meta["rerun_env"] and "VLLM_FAKE_KNOB=7" in meta["rerun_env"]
    assert [t["name"] for t in meta["phase_at"]] == ["generate"] and meta["phase_log"][1][0] == "generate"
    brief = payload._meta_brief(meta)
    assert brief["rerun"] == cmd and brief["phase_at"] and brief["env_inherited"]
    # 照抄复刻命令（从别的目录起的 shell 里）：又录出一个同 case、同样分段的 run
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=180, cwd="/")
    assert r.returncode == 0, r.stdout + r.stderr
    run2, _, rd2 = latest(repo)
    assert rd2 != rd and run2["case"] == "rr" and run2["rec"]["events"] is True
    assert [p[0] for p in run2["phase_log"]] == ["start", "generate"], run2["phase_log"]
    assert run2["env"] == {"CUDA_VISIBLE_DEVICES": "0"}, run2["env"]


def test_rerun_command_legacy():
    """老 run 没存原始命令：按 run 里的参数拼（仓库写绝对路径，--phase / --events / --roots 都带上），
    并注明是拼的。"""
    repo = fresh()
    trace_offline(repo, "old", "--events", "--roots", "fakesvc", "--phase", "g=fakesvc/offline.py:Engine.generate",
                  "--timeout", "60", "--attach", "fake_service.sh")
    run, _, rd = latest(repo)
    run.pop("invocation")
    run.pop("env_inherited")
    (rd / "run.json").write_text(json.dumps(run))
    cmd = runs.rerun_command(run, Path("relative/somewhere"))
    assert cmd.startswith("codestrata trace " + str(repo.resolve()) + " --case=old"), cmd
    for x in ("--events", "--phase=g=fakesvc/offline.py:Engine.generate", "--roots fakesvc", "--timeout=60",
              f"--attach={repo.resolve() / 'fake_service.sh'}", f"-- {PY} -m fakesvc.offline"):
        assert x in cmd, (x, cmd)
    show = cs("runs", repo, "show", run["id"]).stdout
    assert "按 run 里存的参数拼的" in show, show
    _, meta = payload.load_hot(repo, payload.load_index(repo), run["id"])
    assert meta["rerun_exact"] is False and meta["rerun_env"] is None
    # 拼出来的那条给网页时也整条隐去：case 命令里的 --api-key 值、--env 里像密钥的值
    old = {**run, "cmd": [PY, "-m", "fakesvc.offline", "--api-key", "sk-555"], "env": {"HF_TOKEN": "hf_x"}}
    red = runs.rerun_command(old, repo, redact=True)
    assert "sk-555" not in red and "hf_x" not in red and red.count("<已隐去>") == 2, red
    assert "sk-555" in runs.rerun_command(old, repo)


def test_phase_at_race():
    """两个进程同时第一次进触发函数：没抢到标记的那个也跟着切（它这次调用算进新阶段）；
    4 个线程同时进：切阶段的那 0.1 s 里别的线程的调用不丢、也不算进旧阶段；
    fork 出来的子进程以 os._exit 结束，拍在内存里的快照也写出去了。"""
    repo = fresh()
    cs("trace", repo, "--case", "race", "--phase", "gen=fakesvc/work.py:compute",
       "--phase", "load=fakesvc/work.py:load_weight", "--", PY, "-m", "fakesvc.race")
    run, _, rd = latest(repo)
    pc = phase_counts(rd)
    assert pc["gen"].get("fakesvc/work.py:compute") == 2, pc
    assert "fakesvc/work.py:compute" not in pc["start"], pc
    assert pc["load"].get("fakesvc/work.py:load_weight") == 4, pc
    assert all("fakesvc/work.py:load_weight" not in pc[p] for p in ("start", "gen")), pc
    assert [e[0] for e in run["phase_log"]] == ["start", "gen", "load"], run["phase_log"]


def test_phase_log_from_markers():
    """两个阶段隔了不到 driver 一次轮询（0.1 s）也都在 phase_log 里、时刻精确、来源是 hook；
    driver 死了之后 runs merge 也能从包里的标记把 phase_log 补回来；嵌套函数用 模块:outer.inner
    （索引里的名字）也认得出 .<locals>.。"""
    repo = fresh()
    r = trace_offline(repo, "fast", "--phase", "init=fakesvc.offline:Engine.__init__",
                      "--phase", "load=fakesvc.work:init_model", "--phase", "nest=fakesvc.offline:make_hook.hooked")
    assert "make_hook.<locals>.hooked" in r.stderr, r.stderr
    run, _, rd = latest(repo)
    log = run["phase_log"]
    assert [e[0] for e in log] == ["start", "init", "load", "nest"], log
    assert [e[2] for e in log] == ["start", "hook", "hook", "hook"], log
    assert log[1][1] < log[2][1] < log[3][1], log
    with tarfile.open(rd / "parts.tar.gz") as tf:
        marks = {m.name: tf.extractfile(m).read().decode().split() for m in tf.getmembers() if m.name.endswith(".fired")}
    assert log[1][1] == (int(marks["PHASE-init.fired"][2]) - run["clock"]["mono0_ns"]) // 1000, (log, marks)
    # 模拟 driver 死在收尾之前：phase_log 没了，runs merge 从标记补回来
    run.pop("phase_log")
    (rd / "run.json").write_text(json.dumps(run))
    cs("runs", repo, "merge", run["id"])
    run2 = json.loads((rd / "run.json").read_text())
    assert [e[0] for e in run2["phase_log"]] == ["start", "init", "load", "nest"], run2["phase_log"]
    assert [p["name"] for p in run2["phases"]] == ["start", "init", "load", "nest"], run2["phases"]
    # 写成解释器里的名字也行
    trace_offline(repo, "fast2", "--phase", "nest=fakesvc.offline:make_hook.<locals>.hooked")
    run3, _, _ = latest(repo)
    assert [e[0] for e in run3["phase_log"]] == ["start", "nest"], run3["phase_log"]


def test_merge_recovers_sh_phase_times():
    """driver 死在收尾之前（run.json 里没有轮询记下的 phase_log）：runs merge 靠 driver 替 case 脚本
    建的标记把 serving / shutdown 的时刻补回来，不止 --phase 切的。"""
    repo = fresh()
    trace_fake(repo, "shrec")
    run, _, rd = latest(repo)
    want = [e[0] for e in run["phase_log"]]
    assert want == ["start", "serving", "shutdown"], run["phase_log"]
    run.pop("phase_log")
    (rd / "run.json").write_text(json.dumps(run))
    cs("runs", repo, "merge", run["id"])
    run2 = json.loads((rd / "run.json").read_text())
    assert [e[0] for e in run2["phase_log"]] == want, run2["phase_log"]
    assert all(e[1] is not None for e in run2["phase_log"]) and run2["phase_log"][1][2] == "sh", run2["phase_log"]
    assert [p["t_us"] is not None for p in run2["phases"]] == [True, True, True], run2["phases"]


def test_phase_at_same_target_and_sh_name():
    """两个 --phase 指到同一个函数（子类继承来的是同一份代码）直接报错；case 脚本写的阶段和
    --phase 同名：标成 case 脚本切的、提醒同名的 --phase 没起作用，driver 替它建了标记。"""
    repo = fresh()
    r = trace_offline(repo, "dup", "--phase", "a=fakesvc.offline:Engine.close",
                      "--phase", "b=fakesvc.offline:BaseEngine.close", check=False)
    assert r.returncode != 0 and "指向同一个函数" in r.stdout + r.stderr, r.stdout + r.stderr
    r = trace_fake(repo, "shname", "--phase", "serving=fakesvc/work.py:handle")
    assert "同名的 --phase 没起作用" in r.stdout and "serving" in r.stdout, r.stdout
    run, _, rd = latest(repo)
    src = {e[0]: e[2] for e in run["phase_log"]}
    assert src.get("serving") == "sh", run["phase_log"]
    with tarfile.open(rd / "parts.tar.gz") as tf:
        assert tf.extractfile("PHASE-serving.fired").read().decode().startswith("sh "), "driver 替 case 脚本建的标记"


def test_qualnames_and_mro():
    """文件路径写法按编译器的规则得 co_qualname（match / async for / try-except* 里的 def、global
    声明过的嵌套 def）；继承的方法按 C3 MRO 找，Base[T] 去下标，MRO 里先碰到仓库外的基类就不猜。"""
    t = Path(tempfile.mkdtemp(prefix="cs-runs-"))
    _TMP.append(t)
    src = (
        "import sys\n"
        "match sys.platform:\n"
        "    case 'linux':\n"
        "        def in_match(): pass\n"
        "    case _:\n"
        "        def in_match(): pass\n"
        "async def agen():\n"
        "    async for x in y:\n"
        "        def in_afor(): pass\n"
        "try:\n"
        "    pass\n"
        "except* ValueError:\n"
        "    def in_star(): pass\n"
        "def g_outer():\n"
        "    global gdecl\n"
        "    def gdecl(): pass\n"
        "    def plain(): pass\n"
        "class K:\n"
        "    def m(self):\n"
        "        class Inner:\n"
        "            def im(self): pass\n"
    )
    (t / "x.py").write_text(src)
    qs = trace._qualnames(t / "x.py")
    ns = {}
    exec(compile(src.replace("async for x in y", "async for x in []"), str(t / "x.py"), "exec"), ns)
    real = {ns["in_match"].__code__.co_qualname, ns["gdecl"].__code__.co_qualname} if "gdecl" in ns else set()
    for q in ("in_match", "agen.<locals>.in_afor", "in_star", "gdecl", "g_outer.<locals>.plain",
              "K.m.<locals>.Inner.im"):
        assert q in qs, (q, sorted(qs))
    assert "g_outer.<locals>.gdecl" not in qs, sorted(qs)
    ns["g_outer"]()
    assert ns["gdecl"].__code__.co_qualname == "gdecl"                    # 和解释器对得上
    C = lambda n, bases=(), **kw: {"k": "class", "n": n, "f": "m.py", "l": 1, "b": list(bases), **kw}
    F = lambda n: {"k": "func", "n": n, "f": "m.py", "l": 2}
    sy = {"m:Core": C("Core"), "m:Core.close": F("Core.close"), "m:Mixin": C("Mixin"), "m:Mixin.close": F("Mixin.close"),
          "m:BaseEngine": C("BaseEngine", ["Core"]), "m:Engine": C("Engine", ["BaseEngine", "Mixin"]),
          "m:GBase": C("GBase", ["Generic[T]"]), "m:GBase.generate": F("GBase.generate"),
          "m:GEngine": C("GEngine", ["GBase[int]"]),
          "m:Ext1": C("Ext1", ["torch.nn.Module", "Core"]), "m:Ext2": C("Ext2", ["Core", "torch.nn.Module"])}
    s, via = trace._inherited(sy, "m", "Engine.close")
    assert via == "m:Core.close", via                                   # MRO：Engine, BaseEngine, Core, Mixin
    s, via = trace._inherited(sy, "m", "GEngine.generate")
    assert via == "m:GBase.generate", via
    s, _ = trace._inherited(sy, "m", "Ext1.close")
    assert isinstance(s, str) and "Module" in s, s                       # 先碰到仓库外的基类：不猜
    s, via = trace._inherited(sy, "m", "Ext2.close")
    assert via == "m:Core.close", via


def test_phase_at_py310_fallback():
    """没有 co_qualname 的 Python 3.10：按 co_firstlineno + 短名字认。默认参数里的生成器表达式和
    函数在同一行、import 时就跑，不能当成它。（机器上没有 3.10 就跳过）"""
    py310 = next((p for p in [os.path.expanduser("~/miniconda3/envs/ttt/bin/python"), shutil.which("python3.10")]
                  if p and os.path.exists(p)), None)
    if not py310:
        print("    （没有 Python 3.10，跳过）")
        return
    repo = fresh()
    cs("trace", repo, "--case", "p310", "--phase", "t=fakesvc/py310.py:target", "--", py310, "-m", "fakesvc.py310")
    run, _, rd = latest(repo)
    c = json.loads(gzip.decompress((rd / "counts.json.gz").read_bytes()))["phases"]
    lines = (repo / "fakesvc/py310.py").read_text().splitlines()
    main_l = next(i for i, ln in enumerate(lines, 1) if ln.startswith("def main"))
    tgt_l = next(i for i, ln in enumerate(lines, 1) if ln.startswith("def target"))
    assert [e[0] for e in run["phase_log"]] == ["start", "t"], run["phase_log"]
    # 键「文件:首行」上生成器表达式（import 时）在 start、target 那一次在 t；main 在 start
    assert c["t"]["funcs"].get(f"fakesvc/py310.py:{tgt_l}") == 1, c
    assert c["start"]["funcs"].get(f"fakesvc/py310.py:{tgt_l}", 0) >= 1, c
    assert f"fakesvc/py310.py:{main_l}" in c["start"]["funcs"], c


def test_phase_at_same_line_genexpr():
    """同一行上的生成器表达式先占了「文件:首行」这个键（3.12 也会）：target 真被调用时照样切。"""
    repo = fresh()
    cs("trace", repo, "--case", "gx", "--phase", "t=fakesvc/py310.py:target", "--", PY, "-m", "fakesvc.py310")
    run, _, _ = latest(repo)
    assert [e[0] for e in run["phase_log"]] == ["start", "t"], run["phase_log"]


def test_fire_does_not_dump_on_traced_thread():
    """_fire 在被 trace 的程序的线程里跑：不能在那里落盘（_dump 会吞掉程序的信号处理器抛的
    KeyboardInterrupt / SystemExit），只拍内存快照、交给落盘线程写。"""
    src = trace._SITECUSTOMIZE
    body = src[src.index("    def _fire(name):"):src.index("    _py = []")]
    assert "_dump(" not in body and "_want_dump[0] = True" in body and "defer=True" in body, body


def test_rerun_secrets_and_bytes():
    """网页 / 导出里的复刻命令：--env 里像密钥的值、URL 里的账号密码隐去，runs show 给完整的；
    TOKENIZERS_* 这种不是密钥；shell 里继承来的 CODESTRATA_EV_MAX 补进命令；不是 UTF-8 的参数
    写成 $'…'，bash 还原出原来的字节。"""
    repo = fresh()
    trace_offline(repo, "sec", "--events", "--env", "HF_TOKEN=hf_secret123",
                  "--env", "HF_ENDPOINT=https://me:pw9@mirror.example/x",
                  env={"CODESTRATA_EV_MAX": "500", "TOKENIZERS_PARALLELISM": "false", "VLLM_API_KEY": "k"})
    run, _, rd = latest(repo)
    assert run["env_inherited"].get("TOKENIZERS_PARALLELISM") == "false" and "VLLM_API_KEY" not in run["env_inherited"]
    _, meta = payload.load_hot(repo, payload.load_index(repo), run["id"])
    for k in ("rerun", "rerun_env"):
        assert "hf_secret123" not in meta[k] and "pw9" not in meta[k] and "<已隐去>" in meta[k], meta[k]
    assert "--env=CODESTRATA_EV_MAX=500" in meta["rerun"] and meta["rerun_redacted"] is True, meta["rerun"]
    show = cs("runs", repo, "show", run["id"]).stdout
    assert "hf_secret123" in show and "CODESTRATA_EV_MAX=500" in show, show
    out = rd.parent.parent / "sec-export.html"
    cs("graph", repo, "--hot", run["id"], "--out", out)
    html = out.read_text()
    assert "hf_secret123" not in html and "pw9" not in html and "&lt;已隐去&gt;" in html or "<已隐去>" in html
    # 网页 / 导出里显示的 case 命令、进程命令行：--api-key 的值、URL 里的密码也隐去（runs show 给完整的）
    cs("trace", repo, "--case", "sec2", "--", PY, "-m", "fakesvc.offline", "--api-key", "sk-999", "--hf-token=tok-888", "https://u:pw7@h.example/")
    run, _, rd = latest(repo)
    _, meta = payload.load_hot(repo, payload.load_index(repo), run["id"])
    shown = json.dumps([meta["cmd"], meta["procs"], meta["rerun"]], ensure_ascii=False)
    assert "sk-999" not in shown and "tok-888" not in shown and "pw7" not in shown and "<已隐去>" in shown, shown
    assert "sk-999" in cs("runs", repo, "show", run["id"]).stdout
    out2 = rd.parent.parent / "sec2-export.html"
    cs("graph", repo, "--hot", run["id"], "--out", out2)
    assert "sk-999" not in out2.read_text() and "pw7" not in out2.read_text()
    # 时序图（serve 页面）上的进程命令行也隐去；--no-auth 这种后面紧跟选项的是开关，不吃掉下一个选项
    from codestrata import seq
    cs("trace", repo, "--case", "sec3", "--events", "--", PY, "-m", "fakesvc.offline", "--api-key", "sk-777")
    run, det, rd = latest(repo)
    sq = seq.build(repo, payload.load_index(repo), rd, run, det)
    shown = json.dumps(sq["procs"], ensure_ascii=False)
    assert sq["procs"] and "sk-777" not in shown and "<已隐去>" in shown, shown
    assert runs._redact_argv(["x", "--no-auth", "--port", "80", "--api-key", "k"]) == \
        ["x", "--no-auth", "--port", "80", "--api-key", "<已隐去>"]
    # 不是 UTF-8 的参数
    fake = {"case": "x", "invocation": {"argv": ["codestrata", "trace", ".", "--", "echo", "caf\udce9"], "cwd": "/tmp"}}
    cmd = runs.rerun_command(fake, repo)
    assert "$'caf\\xe9'" in cmd, cmd
    r = subprocess.run(["bash", "-c", cmd.split("&& ", 1)[1].replace("codestrata trace . -- ", "")],
                       capture_output=True, timeout=10)
    assert r.stdout == b"caf\xe9\n", r.stdout


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
    非 UTF-8 的参数不崩；超长 argv 标 argv_cut；复刻命令（原样的）带上 --timeout 和 --attach。"""
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
    line = next(ln for ln in r.stdout.splitlines() if ln.strip().startswith("复刻"))
    assert "--timeout 60" in line and "--attach big.yaml" in line and " cd " in " " + line, line


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


# ---------------------------------------------------------------- 时序图（M5）

def _truth_run():
    repo = fresh()
    cs("trace", repo, "--case", "truth", "--events", "--", PY, "-m", "fakesvc.truth")
    run, det, rd = latest(repo)
    return repo, run, det, rd


def test_seq_build():
    """切面上的消息：两端落在不同节点；节点内部的只计数；画得下就不折；生命线按进程分组；
    fork / exec 的子进程有派生行。"""
    from codestrata import seq
    repo, run, det, rd = _truth_run()
    idx = payload.load_index(repo)
    r = seq.build(repo, idx, rd, run, det)
    ms = [x for x in r["rows"] if x["k"] == "m"]
    assert ms and all(x["a"] != x["b"] for x in ms)
    assert not [x for x in r["rows"] if x["k"] == "loop"], "画得下就不折"
    spans, _ = _spans(rd)
    assert sum(x["rep"] for x in ms) + r["stat"]["internal"] + r["stat"]["unmapped"] + r["stat"]["imports"] \
        == sum(s["rep"] for s in spans)
    lanes = r["lifelines"]
    pids = [l["pid"] for l in lanes]
    assert pids == sorted(pids, key=lambda p: [q["pid"] for q in r["procs"]].index(p)), "生命线按进程分组"
    assert all(0 <= x["from"] < len(lanes) and 0 <= x["to"] < len(lanes) for x in ms)
    assert any(x["k"] == "spawn" for x in r["rows"]), "fork 出来的子进程要有派生行"
    ts = [x["t"] for x in r["rows"]]
    assert ts == sorted(ts)
    # 只看一个阶段 / 从某个时刻起
    r2 = seq.build(repo, idx, rd, run, det, t0=r["rows"][5]["t"])
    assert r2["rows"][0]["t"] >= r["rows"][5]["t"]


def test_seq_fold_and_budget():
    """画不下才折循环（第一级折叠后的 50 次叶子调用已经是一条）；给定窗口太密不截断，给建议窗口；
    自动收窄的窗口折叠后不超过上限。"""
    from codestrata import seq
    repo, run, det, rd = _truth_run()
    idx = payload.load_index(repo)
    full = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, max_rows=2000)
    n = len(full["rows"])
    small = seq.build(repo, idx, rd, run, det, max_rows=20)
    assert len(small["rows"]) <= 20 and small["window"][1] < full["window"][1], (len(small["rows"]), small["window"])
    assert n > 40, n
    loops = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, max_rows=n - 10)
    assert loops["too_dense"] is None and any(x["k"] == "loop" for x in loops["rows"]) \
        and len(loops["rows"]) <= n - 10, (n, len(loops["rows"]))
    dense = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, max_rows=20)
    assert dense["too_dense"] and dense["rows"] == [] and dense["too_dense"]["suggest"][1] > 0, dense["too_dense"]


def test_seq_find_and_api():
    """/api/seq、/api/seq/overview、/api/seq/find 经真的 serve 走一遍；没录事件的 run 给 404 说明。"""
    import socket
    import urllib.request
    repo, run, det, rd = _truth_run()
    cs("trace", repo, "--case", "plain", "--", PY, "-m", "fakesvc.truth")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)], cwd=HERE.parent,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def get(path):
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read())
                except OSError:
                    time.sleep(0.1)
            raise AssertionError("serve 没起来")
        st, r = get(f"/api/seq?run={run['id']}")
        assert st == 200 and r["rows"] and r["lifelines"], r
        st, o = get(f"/api/seq/overview?run={run['id']}")
        assert st == 200 and o["procs"] and len(o["procs"][0]["density"]) == 400
        m = next(x for x in r["rows"] if x["k"] == "m")
        st, f = get(f"/api/seq/find?run={run['id']}&a={m['a']}&b={m['b']}&after=-1")
        assert st == 200 and f["t"] <= m["t"], (f, m)
        st, e = get("/api/seq?run=plain")
        assert st == 404 and "--events" in e["error"], e
        st, e = get("/api/seq")
        assert st == 400
        st, rl = get("/api/runs")
        assert {x["case"]: x["events"] for x in rl["runs"]} == {"truth": True, "plain": False}
    finally:
        srv.kill()
        srv.wait()


def test_seq_cuts_and_find():
    """同一微秒的几次调用不拆到两屏；不折叠时分屏、next_t0 接得上；find 先在阶段里找、不算 import；
    fork+exec 的子进程的派生行在 fork 的时刻（exec 之前的调用之前）；统计只数显示的那一段。"""
    from codestrata import seq
    mk = lambda t, pid=1: {"t": t, "d": 1, "pid": pid, "tid": 1, "a": "x", "b": "y", "f": "f.py", "l": t % 7 + 1, "rep": 1}
    msgs = [mk(1000 + 10 * i, 1) for i in range(30)] + [mk(1000 + 10 * i, 2) for i in range(30)]
    msgs.sort(key=lambda m: m["t"])
    n = seq._fit(msgs, 21, fold=False)
    assert 0 < n < len(msgs) and msgs[n]["t"] != msgs[n - 1]["t"], n            # 退到时刻的边界上
    ties = [mk(5, p) for p in range(50)]
    assert seq._fit(ties, 20, fold=False) == 50                                  # 一个时刻放不下也整组放进来
    repo, run, det, rd = _truth_run()
    idx = payload.load_index(repo)
    # 不折叠分屏：前后两屏接得上、不重不漏
    a = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, fold=False, max_rows=20)
    b = seq.build(repo, idx, rd, run, det, t0=a["next_t0"], t1=10 ** 12, fold=False, max_rows=20)
    ma = [x for x in a["rows"] if x["k"] == "m"]
    mb = [x for x in b["rows"] if x["k"] == "m"]
    assert ma and mb and not [x for x in a["rows"] + b["rows"] if x["k"] == "loop"]
    assert a["next_t0"] == ma[-1]["t"] + 1 and mb[0]["t"] >= a["next_t0"]
    full = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, fold=False, max_rows=2000)
    fm = [x["t"] for x in full["rows"] if x["k"] == "m"]
    assert [x["t"] for x in ma + mb] == fm[:len(ma) + len(mb)]
    # 统计只数显示的那一段
    assert a["stat"]["imports"] <= full["stat"]["imports"]
    # 不画 import 触发的模块顶层执行
    assert not [x for x in full["rows"] if x["k"] == "m" and x["l"] == 0]
    # fork+exec 的子进程：派生行在它 exec 之前的调用之前
    sp = [x for x in full["rows"] if x["k"] == "spawn"]
    for s_ in sp:
        first = min((x["t"] for x in full["rows"] if x["k"] == "m" and x["pid"] == s_["pid"]), default=None)
        assert first is None or s_["t"] <= first, (s_, first)
    # find：跳过 <module>，先在给的阶段里找
    hit = seq.find(idx, rd, open_=None, a="fakesvc.truth", b="fakesvc.callee")
    assert hit and hit["t"] > 0
    tr_ = [x for x in full["rows"] if x["k"] == "m" and x["a"] == "fakesvc.truth" and x["b"] == "fakesvc.callee"]
    assert hit["t"] == tr_[0]["t"], (hit, tr_[0]["t"])
    later = seq.find(idx, rd, open_=None, a="fakesvc.truth", b="fakesvc.callee", window=(tr_[5]["t"], 10 ** 12))
    assert later["t"] >= tr_[5]["t"]


def test_seq_estimate_and_fit():
    """画不下时估出来的建议窗口，再请求它不能又是「画不下」（原先会原地打转）；贪心折叠的行数不单调时，
    _fit 退到时刻边界后也不超过上限；不折叠的分屏一屏接一屏，拼起来就是整段。"""
    from codestrata import seq
    mk = lambda i, tok: {"t": 1000 + i, "d": 1, "pid": 1, "tid": 1, "a": tok, "b": "z", "f": "f.py", "l": 1, "rep": 1}
    msgs = [mk(i, t) for i, t in enumerate("AAABAAABAAAB")]
    for lim in range(1, 7):
        n = seq._fit(msgs, lim)
        assert n == 0 or len(seq._with_idle(seq._fold_loops(msgs[:n]))) <= max(lim, 1) or n == 1, (lim, n)
    repo, run, det, rd = _truth_run()
    idx = payload.load_index(repo)
    old = seq.ESTIMATE_X
    try:
        seq.ESTIMATE_X = 0                           # 什么窗口都走估算的那条路
        r = seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, max_rows=20)
        assert r["too_dense"] and r["too_dense"]["estimate"], r["too_dense"]
        s0, s1 = r["too_dense"]["suggest"]
        r2 = seq.build(repo, idx, rd, run, det, t0=s0, t1=s1, max_rows=20)
        assert r2["too_dense"] is None and r2["rows"], r2["too_dense"]
        # 不折叠的分屏：一屏接一屏走到头，拼起来和一次取全的一样
        full = [x["t"] for x in seq.build(repo, idx, rd, run, det, t0=0, t1=10 ** 12, fold=False,
                                          max_rows=2000)["rows"] if x["k"] == "m"]
        got, t = [], 0
        for _ in range(50):
            p = seq.build(repo, idx, rd, run, det, t0=t, t1=10 ** 12, fold=False, max_rows=20)
            got += [x["t"] for x in p["rows"] if x["k"] == "m"]
            if p["next_t0"] is None:
                break
            t = p["next_t0"]
        assert got == full, (len(got), len(full))
    finally:
        seq.ESTIMATE_X = old


def test_remap_moved_functions():
    """M6：录制之后把函数下移几行、重新 scan：按 qualname 挪回来，hot.symbols 的次数不变；
    包的 __init__.py 里的函数、嵌套函数、装饰过的函数也对得上；lambda 算 unmatched。"""
    repo = fresh()
    init = repo / "fakesvc" / "__init__.py"
    init.write_text(init.read_text() + "\n\ndef helper():\n    return 1\n")
    w = repo / "fakesvc" / "work.py"
    w.write_text(w.read_text() + """

def deco(f):
    return f


@deco
def decorated():
    def inner():
        return 2
    return inner() + (lambda: 3)()
""")
    cs("scan", repo)
    cs("trace", repo, "--case", "mv", "--", PY, "-c",
       "import fakesvc; from fakesvc import work; fakesvc.helper(); work.init_model(); work.decorated()")
    idx = payload.load_index(repo)
    before, _ = payload.load_hot(repo, idx, "mv")
    want = {k: before["symbols"].get(k) for k in ("fakesvc:helper", "fakesvc.work:init_model", "fakesvc.work:load_weight",
                                                    "fakesvc.work:decorated", "fakesvc.work:decorated.inner")}
    assert all(want.values()), want
    # 每个函数都下移几行（插空行 / 注释），重新 scan
    init.write_text("# moved\n\n\n\n\n" + init.read_text())
    src = w.read_text().replace("def init_model", "# a\n# b\n# c\n\ndef init_model").replace("@deco", "# x\n# y\n@deco")
    w.write_text(src)
    cs("scan", repo)
    idx = payload.load_index(repo)
    after, meta = payload.load_hot(repo, idx, "mv")
    got = {k: after["symbols"].get(k) for k in want}
    assert got == want, (got, want)
    assert meta["file_state"].get("fakesvc/work.py") == "changed" and meta["unmatched"] >= 1, meta["unmatched"]
    # 对不上的（这里改了名）不能落到原来那一行上现在的别的函数头上；次数还算在文件上
    src = w.read_text()
    old_line = next(i for i, ln in enumerate(src.splitlines(), 1) if ln.startswith("def load_weight"))
    w.write_text(src.replace("def load_weight(", "def other_fn(i):\n    return i\n\n\ndef load_weight_renamed(", 1)
                 .replace("load_weight(i)", "load_weight_renamed(i)"))
    assert w.read_text().splitlines()[old_line - 1].startswith("def other_fn")
    cs("scan", repo)
    idx = payload.load_index(repo)
    h3, m3 = payload.load_hot(repo, idx, "mv")
    assert not h3["symbols"].get("fakesvc.work:other_fn"), h3["symbols"]
    assert h3["files"]["fakesvc/work.py"] >= before["files"]["fakesvc/work.py"] - 1, (h3["files"], before["files"])


def test_compare_and_multi_export():
    """M7：两个 run 对比——节点、边上带 [A, B]，只有一边跑到的也在；边详情带 calls_b，和 B 自己的
    明细对得上；只在 runtime 出现的边、「只看跑到的」取并集。导出能带多个 run、--compare 带对比块。"""
    repo = fresh()
    cs("trace", repo, "--case", "a", "--", PY, "-c", "from fakesvc import work; work.init_model()")
    cs("trace", repo, "--case", "b", "--", PY, "-m", "fakesvc.truth")
    idx = payload.load_index(repo)
    ha, ma = payload.load_hot(repo, idx, "a")
    hb, mb = payload.load_hot(repo, idx, "b")
    g = payload.graph_payload(repo, idx, hot=ha, hot_meta=ma, hot_b=hb, hot_meta_b=mb)
    c = g["cmp"]
    assert c and c["ref_b"].startswith(mb["run_id"]) and c["meta_b"]["case"] == "b"
    ga = payload.graph_payload(repo, idx, hot=ha, hot_meta=ma)
    gb = payload.graph_payload(repo, idx, hot=hb, hot_meta=mb)
    for n, (x, y) in c["nodes"].items():
        assert x == ga["hot"]["packages"].get(n, 0) and y == gb["hot"]["packages"].get(n, 0), n
    assert any(x and not y for x, y in c["nodes"].values()) or any(y and not x for x, y in c["nodes"].values())
    assert {tuple(e[:2]) for e in g["runtimeOnlyEdges"]} >= {tuple(e[:2]) for e in gb["runtimeOnlyEdges"]}
    k = next(k for k, v in c["edges"].items() if v[1])
    a, b = k.split("|")
    d = payload.edge_compare(repo, idx, a, b, ha, hb)
    db = payload.edge_detail(repo, idx, a, b, hb)
    assert d["has_runtime_b"] and d["counts"]["calls_b"] == db["counts"]["calls"]
    assert sum(it.get("calls_b", 0) for it in d["items"]) == db["counts"]["calls"]
    ob = [it for it in d["items"] if it["status"] == "only_b"]
    assert d["counts"].get("only_b", 0) == len(ob) and all(it["calls"] == 0 and it["calls_b"] for it in ob)
    # 导出：两个 run、对比
    out = repo / "exp.html"
    r = cs("graph", repo, "--hot", "a", "--hot", "b", "--compare", "--out", out)
    html = out.read_text()
    assert out.stat().st_size < 16 * 1024 * 1024 and '"hotBy"' in html and '"cmp"' in html, r.stdout
    emb = json.loads(html.split("window.CS_EMBEDDED = ", 1)[1].split(";</script>", 1)[0].replace("<\\/", "</"))
    assert len(emb["hotBy"]) == 1 and emb["cmp"]["ref_b"].startswith(mb["run_id"]), list(emb["hotBy"])
    r = cs("graph", repo, "--hot", "a", "--compare", check=False)
    assert r.returncode != 0 and "--compare" in (r.stdout + r.stderr)
    r = cs("graph", repo, "--hot", "a", "--hot", "", check=False)          # 脚本里变量没设
    assert r.returncode != 0 and "空值" in (r.stdout + r.stderr)
    # 同一个 run 写两遍：不会把主 run 换成精简版
    cs("graph", repo, "--hot", "a", "--hot", ma["run_id"], "--out", out)
    emb = json.loads(out.read_text().split("window.CS_EMBEDDED = ", 1)[1].split(";</script>", 1)[0].replace("<\\/", "</"))
    assert emb["hotBy"] == {} and emb["hot"]["symbols"], list(emb["hotBy"])
    # serve：对比的 run 找不到 / 就是自己 → 只叠 A、说一声，不让整张图 404
    import socket
    import urllib.request
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close()
    srv = subprocess.Popen([PY, "-m", "codestrata", "serve", str(repo), "--port", str(port)], cwd=HERE.parent,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def get(path):
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read())
                except OSError:
                    time.sleep(0.1)
            raise AssertionError("serve 没起来")
        st, g1 = get(f"/api/graph?run=a&cmp=nope")
        assert st == 200 and g1["cmp"] is None and "找不到" in g1["cmpError"], (st, g1.get("cmpError"))
        st, g2 = get(f"/api/graph?run=a&cmp=a")
        assert st == 200 and g2["cmp"] is None and "同一个" in g2["cmpError"]
        st, g3 = get(f"/api/graph?run=a&cmp=b")
        assert st == 200 and g3["cmp"] and not g3.get("cmpError")
    finally:
        srv.kill()
        srv.wait()


def test_notes_fix_refs_keeps_changed():
    """check --fix 只改挪了位置的引用；那一行内容改掉了的，修完还得报出来（指纹不能被顺手刷新）。"""
    repo = fresh()
    w = repo / "fakesvc" / "work.py"
    lines = w.read_text().splitlines()
    ln_moved = next(i for i, l in enumerate(lines, 1) if l.startswith("def compute"))
    ln_changed = next(i for i, l in enumerate(lines, 1) if l.startswith("def load_weight"))
    md = repo / "n.md"
    md.write_text(f"## 是什么\n`compute` 在 work.py:{ln_moved}，`load_weight` 在 work.py:{ln_changed}。\n")
    cs("note", repo, "fakesvc.work", md)
    # 顶上插一行（两个都往下挪一行），再把 load_weight 那一行改掉
    w.write_text("# 插一行\n" + w.read_text().replace("def load_weight(i: int) -> int:", "def load_weight(i: int, k: int = 1) -> int:"))
    cs("scan", repo)
    cs("check", repo, "fakesvc.work", "--fix", check=False)
    r = cs("check", repo, "fakesvc.work", check=False)
    out = r.stdout + r.stderr
    assert f"work.py:{ln_moved}" not in out, out                       # 挪了的已经改到新行号，不再报
    assert "改掉了" in out and r.returncode != 0, out                    # 改掉了的那一行还在报


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
