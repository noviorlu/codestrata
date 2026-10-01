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
import time
from pathlib import Path

from common import FAKE, HERE, PY, cs, fresh, run_tests, tmpdir  # noqa: E402

from codestrata import align, cut, runs  # noqa: E402
from codestrata.ui import edge as ui_edge, graphview as ui_graphview, load as ui_load, source as ui_source  # noqa: E402
from codestrata.trace import analysis as trace_analysis, driver as trace_driver, hook as trace_hook  # noqa: E402


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
    left = trace_driver.leftovers(rd / "parts")
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
    idx = ui_load.load_index(repo)
    hot, meta = ui_load.load_hot(repo, idx, "fake@serving")
    assert meta["run_id"] == run["id"] and meta["phase"] == "serving" and meta["status"] == "ok"
    assert "fakesvc/work.py#handle" in hot["symbols"] and "fakesvc/work.py#init_model" not in hot["symbols"]
    hot_all, _ = ui_load.load_hot(repo, idx, "fake")
    assert "fakesvc/work.py#init_model" in hot_all["symbols"]
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
    assert trace_driver.leftovers(rd / "parts")
    trace_driver.stop_leftovers(rd / "parts", 5)
    no_live(rd)
    cs("runs", repo, "merge", rd.name)
    run = json.loads((rd / "run.json").read_text())
    assert run["status"] == "partial" and run["stop"] == "driver-lost", run
    assert "status_shown" not in run
    r = cs("runs", repo, "ls")
    assert "中断" not in r.stdout and "partial" in r.stdout, r.stdout
    assert not (rd / "parts").exists() and (rd / "parts.tar.gz").is_file()
    idx = ui_load.load_index(repo)
    hot, meta = ui_load.load_hot(repo, idx, rd.name)
    assert "fakesvc/work.py#handle" in hot["symbols"]


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
    idx = ui_load.load_index(repo)
    _, meta = ui_load.load_hot(repo, idx, "fake")
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
    ast.parse(trace_hook._SITECUSTOMIZE)


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
    # 图上标阶段的起点 / 终点：触发函数落在切面的哪个节点上（继承来的按定义它的文件）
    idx = ui_load.load_index(repo)
    hot, meta = ui_load.load_hot(repo, idx, "off@generate")
    marks = ui_graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta, open_=["fakesvc/"])["phaseMarks"]
    assert [(m["name"], m["qualname"], m["node"]) for m in marks] == [
        ("generate", "Engine.generate", "fakesvc/offline.py"), ("shutdown", "BaseEngine.close", "fakesvc/offline.py")], marks
    assert ui_graphview.graph_payload(repo, idx)["phaseMarks"] == []


def test_layers_point_down():
    """纵轴是依赖的层次：边从上指向下（调用方在上）；环里打断的是轻的那条；叠了 run 时实际的调用比
    静态 import 重——import 方向反过来的回调（基类调子类）也画成往下；没有边的放最底层"""
    from codestrata import layout
    lay = layout.layers(["a", "b", "c", "d", "iso"], [("a", "b", 5), ("b", "c", 5), ("c", "a", 1), ("a", "d", 1)])
    assert lay["a"] < lay["b"] < lay["c"] and lay["a"] < lay["d"] and lay["iso"] == max(lay.values()), lay
    # 贪心（Eades）在这里会逆掉 a → c 这条重边（共 91）；sifting 之后逆掉的是 c → a 和 b → c（共 51）
    edges = [("a", "c", 90), ("b", "c", 1), ("c", "a", 50), ("c", "b", 90), ("d", "a", 50)]
    lay = layout.layers(["a", "b", "c", "d"], edges)
    assert sum(w for a, b, w in edges if lay[a] >= lay[b]) == 51, lay
    # 叠了 run：base 按 import 在 sub 下面，但 runtime 是 base 调 sub（回调）→ base 在上
    idx = {"repo": {"roots": ["p"]}, "edges": [["p.sub", "p.base", 3]], "frames": {},
           "packages": {n: {"files": 1, "loc": 10, "classes": 1, "funcs": 1, "out": 1, "in": 1, "alt": 0.0}
                        for n in ("p.sub", "p.base")}}
    static = {n["id"]: n["lane"] for n in layout.build(idx)["nodes"]}
    assert static["p.sub"] < static["p.base"], static
    hot = {n["id"]: n["lane"] for n in layout.build(idx, runtime_edges=[("p.base", "p.sub", 500)])["nodes"]}
    assert hot["p.base"] < hot["p.sub"], hot


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
    t = tmpdir("cs-runs-")
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
    idx = ui_load.load_index(repo)
    _, meta = ui_load.load_hot(repo, idx, run["id"])
    assert meta["rerun"] == cmd and meta["rerun_exact"] is True, meta["rerun"]
    assert meta["rerun_env"].startswith("cd ") and "env " in meta["rerun_env"] and "VLLM_FAKE_KNOB=7" in meta["rerun_env"]
    assert [t["name"] for t in meta["phase_at"]] == ["generate"] and meta["phase_log"][1][0] == "generate"
    # 照抄复刻命令（从别的目录起的 shell 里）：又录出一个同 case、同样分段的 run
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=180, cwd="/")
    assert r.returncode == 0, r.stdout + r.stderr
    run2, _, rd2 = latest(repo)
    assert rd2 != rd and run2["case"] == "rr" and run2["rec"]["events"] is True
    assert [p[0] for p in run2["phase_log"]] == ["start", "generate"], run2["phase_log"]
    assert run2["env"] == {"CUDA_VISIBLE_DEVICES": "0"}, run2["env"]


def test_trace_cwd():
    """命令默认在仓库根目录执行；脚本写的是当前目录下的相对路径时，开录之前就说清楚（不留失败的 run），
    --cwd 换执行目录，run 里记下实际的执行目录，复刻命令照样重跑"""
    repo = fresh()
    here = tmpdir("cs-runs-") / "work"
    here.mkdir()
    (here / "case.py").write_text("from fakesvc import work\nwork.init_model()\n")
    env = dict(os.environ)
    base = [PY, "-m", "codestrata", "trace", str(repo), "--case", "cwd", "--env", f"PYTHONPATH={repo}"]
    r = subprocess.run(base + ["--", PY, "case.py"], cwd=here, capture_output=True, text=True, timeout=120,
                       env={**env, "PYTHONPATH": str(HERE.parent)})
    assert r.returncode != 0 and "--cwd ." in r.stderr and "case.py" in r.stderr, r.stdout + r.stderr
    assert not any((repo / ".codestrata" / "runs").glob("*-cwd")), "开录之前就停，不该留下 run"
    r = subprocess.run(base + ["--cwd", ".", "--", PY, "case.py"], cwd=here, capture_output=True, text=True,
                       timeout=120, env={**env, "PYTHONPATH": str(HERE.parent)})
    assert r.returncode == 0, r.stdout + r.stderr
    run, _, rd = latest(repo)
    assert run["cwd"] == str(here) and run["status"] == "ok", (run["cwd"], run["status"])
    cmd = runs.rerun_command(run, repo)
    assert "--cwd ." in cmd and cmd.startswith(f"cd {here}"), cmd
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120, cwd="/",
                       env={**env, "PYTHONPATH": str(HERE.parent)})
    assert r.returncode == 0, r.stdout + r.stderr
    again, _, rd2 = latest(repo)
    assert rd2 != rd and again["cwd"] == str(here) and again["status"] == "ok"
    # 只看路径在哪边存在：两边都有、两边都没有（比如输出目录）、以 - 开头的，都不算
    (repo / "case.py").write_text("")
    assert trace_driver.misplaced_paths(["python", "case.py", "--out", "out/x", "-m", "a/b"], repo, here) == []
    assert trace_driver.misplaced_paths(["bash", "./case.py"], repo / "fakesvc", here) == ["./case.py"]


def test_trace_roots_and_attach():
    """trace 不给 --roots：用上次 scan 选的目录（不是重新自动探测）。--attach 的相对路径按执行目录（--cwd）找，
    不是按仓库根目录"""
    repo = fresh()
    (repo / "extra").mkdir()
    (repo / "extra" / "__init__.py").write_text("")
    (repo / "extra" / "m.py").write_text("def f():\n    return 1\n")
    from codestrata import scan as scan_mod
    assert scan_mod.detect_roots(repo) != ["fakesvc"], scan_mod.detect_roots(repo)
    cs("scan", repo, "--roots", "fakesvc")
    here = tmpdir("cs-runs-")
    (here / "sub").mkdir()
    (here / "sub" / "cfg.yaml").write_text("a: 1\n")
    r = subprocess.run([PY, "-m", "codestrata", "trace", str(repo), "--case", "rt", "--cwd", "sub", "--attach", "cfg.yaml",
                        "--env", f"PYTHONPATH={repo}", "--", PY, "-c",
                        "import os; from fakesvc import work; work.init_model(); "
                        "open('pkgs.txt', 'w').write(os.environ['CODESTRATA_PKGS'])"],
                       cwd=here, capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": str(HERE.parent)})
    assert r.returncode == 0, r.stdout + r.stderr
    run, det, _ = latest(repo)
    assert (here / "sub" / "pkgs.txt").read_text() == "fakesvc=fakesvc"        # 顶层包 → 仓库里的目录
    assert run["rec"]["roots"] is None, run["rec"]                              # 没给 --roots：复刻时照样按索引
    assert run["cwd"] == str((here / "sub").resolve()), run["cwd"]
    assert any(f["why"] == "attach" and f["path"].endswith("sub/cfg.yaml") for f in det["files"]), det["files"]


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
    cmd = runs.rerun_command(run, Path(os.path.relpath(repo)))          # 相对路径也写成绝对的
    assert cmd.startswith("codestrata trace " + str(repo.resolve()) + " --case=old"), cmd
    assert "--cwd" not in cmd, cmd                                        # 在仓库根目录录的
    assert f"--cwd={repo.resolve() / 'fakesvc'}" in runs.rerun_command({**run, "cwd": str(repo / "fakesvc")}, repo)
    for x in ("--events", "--phase=g=fakesvc/offline.py:Engine.generate", "--roots fakesvc", "--timeout=60",
              f"--attach={repo.resolve() / 'fake_service.sh'}", f"-- {PY} -m fakesvc.offline"):
        assert x in cmd, (x, cmd)
    show = cs("runs", repo, "show", run["id"]).stdout
    assert "按 run 里存的参数拼的" in show, show
    _, meta = ui_load.load_hot(repo, ui_load.load_index(repo), run["id"])
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
    t = tmpdir("cs-runs-")
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
    qs = trace_analysis._qualnames(t / "x.py")
    ns = {}
    exec(compile(src.replace("async for x in y", "async for x in []"), str(t / "x.py"), "exec"), ns)
    real = {ns["in_match"].__code__.co_qualname, ns["gdecl"].__code__.co_qualname} if "gdecl" in ns else set()
    for q in ("in_match", "agen.<locals>.in_afor", "in_star", "gdecl", "g_outer.<locals>.plain",
              "K.m.<locals>.Inner.im"):
        assert q in qs, (q, sorted(qs))
    assert "g_outer.<locals>.gdecl" not in qs, sorted(qs)
    ns["g_outer"]()
    assert ns["gdecl"].__code__.co_qualname == "gdecl"                    # 和解释器对得上
    C = lambda n, bases=(), **kw: {"k": "class", "n": n, "f": "m.py", "m": "m", "l": 1, "b": list(bases), **kw}
    F = lambda n: {"k": "func", "n": n, "f": "m.py", "m": "m", "l": 2}
    sy = {f"m.py#{x['n']}": x for x in (
        C("Core"), F("Core.close"), C("Mixin"), F("Mixin.close"), C("BaseEngine", ["Core"]), C("Engine", ["BaseEngine", "Mixin"]),
        C("GBase", ["Generic[T]"]), F("GBase.generate"), C("GEngine", ["GBase[int]"]),
        C("Ext1", ["torch.nn.Module", "Core"]), C("Ext2", ["Core", "torch.nn.Module"]))}
    s, via = trace_analysis._inherited(sy, "m", "Engine.close")
    assert via == "m:Core.close", via                                   # MRO：Engine, BaseEngine, Core, Mixin
    s, via = trace_analysis._inherited(sy, "m", "GEngine.generate")
    assert via == "m:GBase.generate", via
    s, _ = trace_analysis._inherited(sy, "m", "Ext1.close")
    assert isinstance(s, str) and "Module" in s, s                       # 先碰到仓库外的基类：不猜
    s, via = trace_analysis._inherited(sy, "m", "Ext2.close")
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
    src = trace_hook._SITECUSTOMIZE
    body = src[src.index("    def _fire(name):"):src.index("    _py = []")]
    assert "_dump(" not in body and "_want_dump[0] = True" in body and "defer=True" in body, body


def test_rerun_secrets_and_bytes():
    """网页上的复刻命令：--env 里像密钥的值、URL 里的账号密码隐去，runs show 给完整的；
    TOKENIZERS_* 这种不是密钥；shell 里继承来的 CODESTRATA_EV_MAX 补进命令；不是 UTF-8 的参数
    写成 $'…'，bash 还原出原来的字节。"""
    repo = fresh()
    trace_offline(repo, "sec", "--events", "--env", "HF_TOKEN=hf_secret123",
                  "--env", "HF_ENDPOINT=https://me:pw9@mirror.example/x",
                  env={"CODESTRATA_EV_MAX": "500", "TOKENIZERS_PARALLELISM": "false", "VLLM_API_KEY": "k"})
    run, _, rd = latest(repo)
    assert run["env_inherited"].get("TOKENIZERS_PARALLELISM") == "false" and "VLLM_API_KEY" not in run["env_inherited"]
    _, meta = ui_load.load_hot(repo, ui_load.load_index(repo), run["id"])
    for k in ("rerun", "rerun_env"):
        assert "hf_secret123" not in meta[k] and "pw9" not in meta[k] and "<已隐去>" in meta[k], meta[k]
    assert "--env=CODESTRATA_EV_MAX=500" in meta["rerun"] and meta["rerun_redacted"] is True, meta["rerun"]
    show = cs("runs", repo, "show", run["id"]).stdout
    assert "hf_secret123" in show and "CODESTRATA_EV_MAX=500" in show, show
    # 网页上显示的 case 命令、进程命令行：--api-key 的值、URL 里的密码也隐去（runs show 给完整的）
    cs("trace", repo, "--case", "sec2", "--", PY, "-m", "fakesvc.offline", "--api-key", "sk-999", "--hf-token=tok-888", "https://u:pw7@h.example/")
    run, _, rd = latest(repo)
    _, meta = ui_load.load_hot(repo, ui_load.load_index(repo), run["id"])
    shown = json.dumps([meta["cmd"], meta["procs"], meta["rerun"]], ensure_ascii=False)
    assert "sk-999" not in shown and "tok-888" not in shown and "pw7" not in shown and "<已隐去>" in shown, shown
    assert "sk-999" in cs("runs", repo, "show", run["id"]).stdout
    # --no-auth 这种后面紧跟选项的是开关，不吃掉下一个选项
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
    idx = ui_load.load_index(repo)
    want = ui_load.load_hot(repo, idx, run["id"])[0]
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
    got = ui_load.load_hot(repo, idx, "old")
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
    d = tmpdir("cs-runs-")
    p = subprocess.Popen(["sleep", "30"])
    try:
        st = trace_driver.proc_start(p.pid)
        (d / f"part-{p.pid}-1.json").write_text(json.dumps({"st": st}))
        assert trace_driver.leftovers(d) == [p.pid]
        (d / f"part-{p.pid}-1.json").write_text(json.dumps({"st": st + 1}))   # pid 被复用了
        assert trace_driver.leftovers(d) == []
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
    idx = ui_load.load_index(repo)
    hot, meta = ui_load.load_hot(repo, idx, "双工+v2")
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
    idx = ui_load.load_index(repo)
    _, meta = ui_load.load_hot(repo, idx, "one")
    assert meta["phases"] == {}, meta["phases"]
    r = cs("runs", repo, "show", "one")
    line = next(ln for ln in r.stdout.splitlines() if ln.strip().startswith("复刻"))
    assert "--timeout 60" in line and "--attach big.yaml" in line and " cd " in " " + line, line


def test_nonexistent_repo():
    d = tmpdir("cs-runs-")
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
    idx = ui_load.load_index(repo)
    _, meta = ui_load.load_hot(repo, idx, "ed")
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


def _calls(x: dict) -> list[int | float]:
    """一行 span → 各次调用的开始时刻：折叠行（rep > 1）按次数均匀摊在 [开始, 结束] 上，没返回的（dur < 0）全算在开始"""
    if x["rep"] <= 1 or x["dur"] <= 0:
        return [x["t0"]] * x["rep"]
    return [x["t0"] + i * (x["dur"] / (x["rep"] - 1)) for i in range(x["rep"])]


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
    d = tmpdir("cs-runs-")
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
    trace_driver.stop_leftovers(rd / "parts", 5)
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


def test_edge_times_api():
    """/api/seq/edges 经真的 serve 走一遍：录了事件的 run 给每条边的时间；没录事件的、没有这个阶段的给 404 说明。"""
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
        st, te = get(f"/api/seq/edges?run={run['id']}")
        assert st == 200 and te["edges"] and all(v["first"] <= v["last"] for v in te["edges"].values()), te
        st, e = get("/api/seq/edges?run=plain")
        assert st == 404 and "--events" in e["error"], e
        st, e = get(f"/api/seq/edges?run={run['id']}@nosuch")
        assert st == 404, e
        st, tw = get(f"/api/seq/edges?run={run['id']}@t=0-{te['span_us']}")      # 时间段：和整个 run 一样
        assert st == 200 and tw["edges"] == te["edges"], (tw, te)
        st, e = get(f"/api/seq/edges?run={run['id']}@t=9-3")
        assert st == 404 and "起点" in e["error"], e
        st, g = get(f"/api/graph?run={run['id']}@t=0-{te['span_us']}")
        assert st == 200 and g["hotMeta"]["window"] == [0, te["span_us"]], g.get("hotMeta")
        st, e = get("/api/seq/edges")
        assert st == 400
        for gone in ("/api/seq", "/api/seq/overview", "/api/seq/find"):     # 时序图去掉了
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{gone}?run={run['id']}", timeout=10)
                raise AssertionError(f"{gone} 还在")
            except urllib.error.HTTPError as e:
                assert e.code == 404, (gone, e.code)
        st, rl = get("/api/runs")
        assert {x["case"]: x["events"] for x in rl["runs"]} == {"truth": True, "plain": False}
    finally:
        srv.kill()
        srv.wait()


def test_seq_edge_times():
    """「时间顺序」上色的数据：切面上每条边在一个阶段里第一次 / 最后一次被调用的时刻和次数。节点内部的、
    import / 类体这种定义时的执行、index 外的不算（这里从原始 span 另算一遍对照：折叠行展开成一次次调用，
    阶段的段左闭右开、最后一段闭到 run 的终点）；整个 run 上次数和 hot 图的调用次数一致
    （分了阶段时边界上会差一点：时间窗按时刻切，fork 出来的进程是轮询着跟着切阶段的）"""
    from codestrata import seq
    repo = fresh()
    trace_offline(repo, "ph", "--events", "--phase", "generate=fakesvc.offline:Engine.generate")
    run, _, rd = latest(repo)
    idx = ui_load.load_index(repo)
    spans, _ = _spans(rd)
    end = seq.run_end(run, rd)
    for phase, opened in ((None, None), ("generate", None), ("generate", ["fakesvc/"])):
        r = seq.edge_times(idx, rd, run, open_=opened, phase=phase)
        t0, t1 = r["window"]
        assert (t0 > 0) == bool(phase), r["window"]
        inside = lambda c: any(a <= c < b or c == b == end for a, b in r["intervals"])      # noqa: E731
        v = cut.view(idx, set(opened if opened is not None else idx["default_open"]))
        loc, _ = align.sym_locs(idx["symbols"])
        want: dict = {}
        for x in spans:    # 另算一遍：键 → 单元 → 切面节点；同一个节点、定义时的执行、index 外的不算
            cs_ = [c for c in _calls(x) if inside(c)]
            if not cs_:
                continue
            (ra, _, la), (rb, _, lb) = x["a"].rpartition(":"), x["b"].rpartition(":")
            na, nb = (v["node_of"].get(idx["files"].get(ra)), v["node_of"].get(idx["files"].get(rb)))
            if na is None or nb is None or na == nb or align.defining(idx["symbols"], loc, rb, int(lb)):
                continue
            f, l = x["t0"] + round(min(cs_) - x["t0"]), x["t0"] + round(max(cs_) - x["t0"])
            w = want.setdefault(f"{na}|{nb}", {"first": f, "last": l, "n": 0})
            w["first"], w["last"], w["n"] = min(w["first"], f), max(w["last"], l), w["n"] + len(cs_)
        got = {k: {f: v[f] for f in ("first", "last", "n")} for k, v in r["edges"].items()}
        assert want and got == want, (got, want)
        assert all(v["repeat"] == (v["n"] >= seq.REPEAT_MIN and v["spread"] > r["span_us"] / 2) for v in r["edges"].values())
        if phase is None:
            hot, meta = ui_load.load_hot(repo, idx, run["id"])
            he = ui_graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta, open_=opened)["hot"]["edges"]
            assert {k: v["n"] for k, v in r["edges"].items()} == he, (r["edges"], he)


def test_phase_intervals():
    """阶段的时间段按 phase_log：切回去的阶段有几段；时刻不知道的阶段按时间排时明说，不退成整个 run"""
    from codestrata import seq
    run = {"phase_log": [["start", 0, "start"], ["a", 10, "hook"], ["b", 20, "hook"], ["a", 30, "marker"]],
           "phases": [{"name": "start", "t_us": 0}, {"name": "a", "t_us": 10}, {"name": "b", "t_us": 20}]}
    iv = seq.phase_intervals(run, 50)
    assert iv == {None: [(0, 50)], "start": [(0, 10)], "a": [(10, 20), (30, 50)], "b": [(20, 30)]}, iv
    old = {"phases": [{"name": "start", "t_us": 0}, {"name": "x", "t_us": None}]}      # 老 run：只有 phases
    assert seq.phase_intervals(old, 9) == {None: [(0, 9)], "start": [(0, 9)]}
    # 时间轴上的一段段：按时间排，切回去的阶段再出现一次
    assert seq.phase_segments(run, 50) == [("start", 0, 10), ("a", 10, 20), ("b", 20, 30), ("a", 30, 50)]


def test_calls_in_and_run_end():
    """折叠行（rep 次调用合成一行）按次数均匀摊在它盖住的时间上：窗口 / 阶段的段各分到自己那一份，切成几段加起来
    正好是 rep；没返回的整行算在开始。时间轴的终点取 span 的结束、最后一次切阶段、run 时长里最大的，span 文件
    坏了不算它（加载图不该因此失败）"""
    from codestrata import seq
    assert seq._calls_in(0, 100, 5, 20, 60) == (2, 25, 50)          # 5 次：0 25 50 75 100
    assert seq._calls_in(0, 100, 5, 0, 50, open_hi=True) == (2, 0, 25)
    assert seq._calls_in(0, 100, 5, 50, 100) == (3, 50, 100)
    assert seq._calls_in(0, 100, 5, 101, 200) is None
    assert seq._calls_in(10, -1, 7, 0, 10) == (7, 10, 10) and seq._calls_in(10, -1, 7, 11, 99) is None
    assert seq._calls_in(10, 0, 1, 0, 10, open_hi=True) is None and seq._calls_in(10, 0, 1, 0, 10) == (1, 10, 10)
    parts = [seq._calls_in(3, 997, 50, a, b, open_hi=b < 1000) for a, b in ((0, 100), (100, 333), (333, 1000))]
    assert sum(p[0] for p in parts if p) == 50, parts
    rd = tmpdir("cs-end-")
    sp = rd / "events" / "spans"
    sp.mkdir(parents=True)
    (sp / "keys.json").write_text('{"keys": []}')
    (sp / "index.json").write_text(json.dumps({"chunks": [{"chunk": "x", "pid": 1, "t0_us": 0, "t1_us": 1000}]}))
    killed = {"phase_log": [["start", 0, "start"], ["shutdown", 1500, "hook"]], "duration_s": 0.0012}
    assert seq.run_end(killed, rd) == 1500                            # 切到 shutdown 之后再没有返回的调用
    assert all(a <= b for _, a, b in seq.phase_segments(killed, seq.run_end(killed, rd)))
    assert seq.run_end({"duration_s": 0.002}, rd) == 2000
    (sp / "index.json").write_text("{坏了")
    assert seq.run_end({"duration_s": 0.0001}, rd) == 100
    assert seq.run_end({}, tmpdir("cs-end-none-")) is None
    # _pairs 按阶段分：切阶段那一刻的调用归新阶段；一行折叠的调用（50、100、150）跨了两个阶段就分成两份
    rows = [[100, 5, 1, 0, 0, 1, 1, 0], [50, 100, 1, 0, 1, 0, 3, 0]]
    (sp / "p1-000.jsonl.gz").write_bytes(gzip.compress("\n".join(json.dumps(r) for r in rows).encode()))
    (sp / "keys.json").write_text('{"keys": ["x.py:1", "y.py:2"]}')
    (sp / "index.json").write_text(json.dumps({"chunks": [{"chunk": "p1-000.jsonl.gz", "pid": 1, "t0_us": 50, "t1_us": 150}]}))
    two = {"phase_log": [["a", 0, "start"], ["b", 100, "hook"]], "duration_s": 0.0002}
    agg = seq._pairs(sp, two)[1]["agg"]
    assert {k: v[:3] for k, v in agg["a"].items()} == {(1, 0): [50, 50, 1]}, agg["a"]
    assert {k: v[:3] for k, v in agg["b"].items()} == {(0, 1): [100, 100, 1], (1, 0): [100, 150, 2]}, agg["b"]
    assert {k: v[:3] for k, v in agg[None].items()} == {(0, 1): [100, 100, 1], (1, 0): [50, 150, 3]}, agg[None]


def test_time_window():
    """时间轴拖出来的时间段（@t=起-止）：解析、报错；次数按窗口里开始的 span 现算（从原始 span 另算一遍对照）；
    加载成 hot 图、「时间顺序」的边和它一致；meta 带时间轴要的 end_us / timeline / window；
    没录事件的 run 选时间段要说清楚"""
    from codestrata import seq
    assert seq.parse_window("serving") is None and seq.parse_window(None) is None
    assert seq.parse_window("t=5-17") == (5, 17)
    for bad in ("t=17-5", "t=5-5", "t=x-2", "t=5", "t=-1-5"):
        try:
            seq.parse_window(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    def check(repo, idx, run, rd, t0, t1):
        spans, _ = _spans(rd)
        end = seq.run_end(run, rd)
        assert end and end >= max(x["t0"] + max(x["dur"], 0) for x in spans)
        c = seq.window_counts(rd, t0, t1)
        want_f, want_e = {}, {}
        for x in spans:                                # 折叠行展开成一次次调用，数落在窗口里的
            n = sum(1 for c_ in _calls(x) if t0 <= c_ <= t1)
            if n:
                want_f[x["b"]] = want_f.get(x["b"], 0) + n
                want_e[f"{x['a']}|{x['b']}"] = want_e.get(f"{x['a']}|{x['b']}", 0) + n
        diff = {k: (c["func_edges"].get(k), want_e.get(k)) for k in set(c["func_edges"]) | set(want_e)
                if c["func_edges"].get(k) != want_e.get(k)}
        assert c == {"funcs": want_f, "func_edges": want_e} and want_e, (rd, t0, t1, diff, c["funcs"], want_f)
        ref = f"{run['id']}@t={t0}-{t1}"
        hot, meta = ui_load.load_hot(repo, idx, ref)
        assert meta["phase"] == f"t={t0}-{t1}" and meta["window"] == [t0, t1] and hot["run"] == ref, meta["phase"]
        assert meta["end_us"] == end and meta["timeline"] == [list(s) for s in seq.phase_segments(run, end)]
        he = ui_graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta)["hot"]["edges"]
        te = seq.edge_times(idx, rd, run, open_=None, phase=f"t={t0}-{t1}")
        assert te["window"] == [t0, t1] and {k: v["n"] for k, v in te["edges"].items()} == he, (te["edges"], he)
        return c

    # 分了阶段的：窗口正好是一个阶段
    repo = fresh()
    trace_offline(repo, "ph", "--events", "--phase", "generate=fakesvc.offline:Engine.generate")
    run, _, rd = latest(repo)
    idx = ui_load.load_index(repo)
    end = seq.run_end(run, rd)
    (a, b), = seq.phase_intervals(run, end)["generate"]
    check(repo, idx, run, rd, a, b)
    # 调用多、有折叠行（rep > 1）的：整个 run，和一个不和任何东西对齐的窗口（中间那三分之一的调用）
    trepo, trun, _, trd = _truth_run()
    tidx = ui_load.load_index(trepo)
    ts = sorted(x["t0"] for x in _spans(trd)[0])
    assert max(x["rep"] for x in _spans(trd)[0]) > 1
    whole_c = check(trepo, tidx, trun, trd, 0, seq.run_end(trun, trd))
    whole, whole_e = whole_c["funcs"], whole_c["func_edges"]
    part = check(trepo, tidx, trun, trd, ts[len(ts) // 3], ts[2 * len(ts) // 3])["funcs"]
    assert all(n <= whole[k] for k, n in part.items()) and sum(part.values()) < sum(whole.values())
    # 从最长的折叠行中间切开：这一行只算窗口里的那几次，不是整行（也不是一次都没有）
    x = max((x for x in _spans(trd)[0] if x["rep"] > 1 and x["dur"] > 0), key=lambda x: x["dur"])
    lo = x["t0"] + x["dur"] // 2
    cut = check(trepo, tidx, trun, trd, lo, lo + x["dur"])["func_edges"]
    assert 0 < cut[f"{x['a']}|{x['b']}"] < whole_e[f"{x['a']}|{x['b']}"], (x, cut)
    _, meta = ui_load.load_hot(repo, idx, f"{run['id']}@generate")
    assert meta["window"] is None and meta["end_us"] == end
    for bad, say in ((f"{run['id']}@t=9-3", "起点要小于终点"), (f"{run['id']}@t=a-b", "t=起-止")):
        try:
            runs.resolve(repo, bad)
            raise AssertionError(bad)
        except SystemExit as e:
            assert say in str(e), e
    # span 文件坏了：整个 run、阶段照常加载（时间轴按切阶段和时长），时间段说清楚「读不出来」，不抛原始异常
    tsp = trd / "events" / "spans"
    chunk = json.loads((tsp / "index.json").read_text())["chunks"][0]["chunk"]
    (tsp / chunk).write_bytes(b"garbage")
    try:
        ui_load.load_hot(trepo, tidx, f"{trun['id']}@t=0-{seq.run_end(trun, trd)}")
        raise AssertionError("坏了的 span 也加载出来了")
    except SystemExit as e:
        assert "读不出来" in str(e) and "merge" in str(e), e
    (tsp / "keys.json").write_text("{坏了")
    _, meta = ui_load.load_hot(trepo, tidx, trun["id"])
    assert meta["end_us"] and meta["window"] is None
    trace_offline(repo, "plain")                       # 没录事件：阶段照常，时间段说清楚
    plain, _, _ = latest(repo)
    try:
        ui_load.load_hot(repo, idx, f"{plain['id']}@t=0-5")
        raise AssertionError("没录事件也加载出来了")
    except SystemExit as e:
        assert "--events" in str(e), e


def test_call_lines():
    """trace 记调用写在调用方的哪一行（func_lines）：3.12 的 sys.monitoring 和 3.10 的 setprofile 两条路一样；
    同一条边各行相加等于 func_edges；录制之后函数整个下移了几行，调用行跟着挪（align.remap）"""
    repo = fresh()
    off = repo / "fakesvc" / "offline.py"
    lines = off.read_text().splitlines()
    main_l = next(i for i, x in enumerate(lines, 1) if x.startswith("def main"))
    want = {next(i for i, x in enumerate(lines, 1) if s in x and i > main_l)
            for s in ("e = Engine()", "e.generate(", "e.close()", "make_hook()()")}
    py310 = next((p for p in [os.path.expanduser("~/miniconda3/envs/ttt/bin/python"), shutil.which("python3.10")]
                  if p and os.path.exists(p)), None)
    for case, py in (("cl", PY), ("cl310", py310)):
        if not py:
            print("  （没有 python3.10：跳过 setprofile 那条路）")
            continue
        cs("trace", repo, "--case", case, "--", py, "-m", "fakesvc.offline")
        run, rd, _ = runs.resolve(repo, case)
        assert run["schema"] == 3, run["schema"]
        for ph in runs.read_json(rd / "counts.json.gz", gz=True)["phases"].values():
            per: dict = {}
            for k, n in ph["func_lines"].items():
                e = k.rpartition("|")[0]
                per[e] = per.get(e, 0) + n
            assert per == ph["func_edges"], (case, per, ph["func_edges"])
        c = runs.load_counts(rd, None)
        got = {int(k.rpartition("|")[2]) for k in c["func_lines"] if k.startswith(f"fakesvc/offline.py:{main_l}|")}
        assert got == want, (case, got, want)
    # 录制之后 main 整个下移 3 行、重新 scan：调用行跟着挪
    off.write_text("# a\n# b\n# c\n" + off.read_text())
    cs("scan", repo)
    idx = ui_load.load_index(repo)
    run, rd, _ = runs.resolve(repo, "cl")
    counts, names = runs.load_counts(rd, None, with_names=True)
    moved, _ = align.remap(counts, names, runs.file_state(repo, idx, runs.read_json(rd / "detail.json")), idx)
    got = {int(k.rpartition("|")[2]) for k in moved["func_lines"] if k.startswith(f"fakesvc/offline.py:{main_l + 3}|")}
    assert got == {l + 3 for l in want}, (got, want)


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
    idx = ui_load.load_index(repo)
    before, _ = ui_load.load_hot(repo, idx, "mv")
    want = {k: before["symbols"].get(k) for k in ("fakesvc/__init__.py#helper", "fakesvc/work.py#init_model",
                                                    "fakesvc/work.py#load_weight", "fakesvc/work.py#decorated",
                                                    "fakesvc/work.py#decorated.inner")}
    assert all(want.values()), want
    # 每个函数都下移几行（插空行 / 注释），重新 scan
    init.write_text("# moved\n\n\n\n\n" + init.read_text())
    src = w.read_text().replace("def init_model", "# a\n# b\n# c\n\ndef init_model").replace("@deco", "# x\n# y\n@deco")
    w.write_text(src)
    cs("scan", repo)
    idx = ui_load.load_index(repo)
    after, meta = ui_load.load_hot(repo, idx, "mv")
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
    idx = ui_load.load_index(repo)
    h3, m3 = ui_load.load_hot(repo, idx, "mv")
    assert not h3["symbols"].get("fakesvc/work.py#other_fn"), h3["symbols"]
    assert h3["files"]["fakesvc/work.py"] >= before["files"]["fakesvc/work.py"] - 1, (h3["files"], before["files"])


_CLS = {
    "cb/__init__.py": "",
    "cb/util.py": "def deco(cls):\n    return cls\n",
    # 只定义、方法一次都没调到的类：import 过（类体跑过），但这个模块不能算「跑到了」
    "cb/idle.py": "class Idle:\n    def work(self):\n        return 0\n",
    "cb/lazy.py": (
        "from cb import idle\n"
        "from cb.util import deco\n\n\n"
        "@deco\n"                                   # 装饰过的类：类体帧的 co_firstlineno 是装饰器那一行
        "class Pool:\n"
        "    class Options:\n"                       # 嵌套的类
        "        retries = 1\n\n"
        "    def request(self):\n"
        "        return 1\n\n\n"
        "def factory():\n"
        "    class Local:\n"                         # 函数里定义的类：每调一次 factory 跑一次类体
        "        pass\n"
        "    return Local\n"),
    "cb/main.py": (
        "def late():\n"
        "    from cb import lazy\n"                  # 惰性 import（httpx 的 HTTPTransport.__init__ 里 import httpcore 就是这样）
        "    lazy.Pool().request()\n"
        "    for _ in range(3):\n"
        "        lazy.factory()\n\n\n"
        "if __name__ == '__main__':\n"
        "    late()\n"),
}


def test_class_body_is_definition_not_call():
    """类体（class 语句执行时跑一次的帧）和模块顶层一样是定义、不是调用：不算到类符号、文件、模块上，
    否则惰性 import 进来的一堆类会让那个阶段「跑到了」它们（httpx 试用：sync 阶段 import httpcore，
    AsyncConnectionPool 等等的类体被算成 sync 调了 async 的类）。装饰过的、嵌套的、函数里的类都一样；
    按行号在加载时分，录制之后改过行号（remap）的也一样。"""
    t = tmpdir("cs-cls-")
    repo = t / "repo"
    for rel, src in _CLS.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "cls", "--phase", "late=cb.main:late", "--", PY, "-m", "cb.main")
    # 「时间顺序」（seq）和模块图用同一个「定义时的执行」判断（align.defining）
    from codestrata import seq
    idx0 = ui_load.load_index(repo)
    sm = seq._Map(idx0, ["cb/"])
    S = idx0["symbols"]
    for k, want in (("cb/lazy.py#Pool", True), ("cb/lazy.py#Pool.Options", True), ("cb/lazy.py#Pool.request", False),
                    ("cb/lazy.py#factory", False)):
        assert sm.of(f'{S[k]["f"]}:{S[k].get("dl", S[k]["l"])}')[1] is want, k
    assert sm.of("cb/lazy.py:0")[1] and not sm.of("cb/lazy.py:3")[1]

    def check(idx):
        classes = {k for k, s in idx["symbols"].items() if s["k"] == "class"}
        h, m = ui_load.load_hot(repo, idx, "cls@late")
        assert not classes & set(h["symbols"]), h["symbols"]
        assert h["symbols"] == {"cb/main.py#late": 1, "cb/util.py#deco": 1, "cb/lazy.py#Pool.request": 1,
                                "cb/lazy.py#factory": 3}, h["symbols"]
        assert "cb/idle.py" not in h["packages"] and "cb/idle.py" not in h["files"], (h["packages"], h["files"])
        assert h["packages"]["cb/lazy.py"] == 4 and h["files"]["cb/lazy.py"] == 4, (h["packages"], h["files"])
        assert set(h["module_exec"]) == {"cb/idle.py", "cb/lazy.py", "cb/util.py"}, h["module_exec"]
        assert h["class_frames"] == 6, h["class_frames"]        # Pool、Options、Idle、Local × 3
        g = ui_graphview.graph_payload(repo, idx, hot=h, open_=["cb/"])
        assert "cb/idle.py" not in {n["id"] for n in g["graphHot"]["nodes"]}, g["hot"]["packages"]
        return m
    check(ui_load.load_index(repo))
    # 录制之后行号变了：类体的键按 qualname 挪到类现在的行上，照样认得出
    lz = repo / "cb" / "lazy.py"
    lz.write_text("# 插两行\n\n" + lz.read_text())
    cs("scan", repo)
    m = check(ui_load.load_index(repo))
    assert m["file_state"].get("cb/lazy.py") == "changed" and m["unmatched"] == 0, (m["file_state"], m["unmatched"])


_DD = {
    "dd/__init__.py": "",
    "dd/registry.py": ('MODELS = {"Net": ("impl", "net", "Net")}\n'
                       'PLUGINS = ["dd.models.impl.net.Net", "dd.models.helpers:Net"]\n\n\n'
                       'def lookup(name):\n    return MODELS[name]\n'),
    "dd/wire.py": 'FALLBACK = "Net"\n',
    "dd/other.py": 'ALT = "dd.models.helpers.Net"\n',       # 别的模块里的同名类，不是它
    "dd/runner/__init__.py": "",
    "dd/runner/loop.py": (
        "from dd.models import helpers\n\n\n"
        "class Runner:\n"
        "    def __init__(self, model, tag):\n"
        "        self.model, self.tag = model, tag\n\n"
        "    def step(self):\n"
        "        if self.tag:\n"
        "            helpers.tag()\n"
        "        return self.model.forward(helpers.SCALE)\n\n"
        "    def batch(self, xs):\n"
        "        return list(map(self.model.forward, xs))\n"),
    "dd/models/__init__.py": "",
    "dd/models/helpers.py": "SCALE = 2\n\n\ndef tag():\n    return 't'\n\n\nclass Net:\n    pass\n",
    "dd/models/impl/__init__.py": "__all__ = ['Net']\n",
    "dd/models/impl/net.py": "class Net:\n    def forward(self, x):\n        return x * 2\n",
    "dd/main.py": (
        "# 诱饵：函数体外面也写着 lookup(name)，调用处只能在 build 里找\n"
        "import importlib\nimport sys\n\nfrom dd.registry import MODELS\nfrom dd.runner.loop import Runner\n\n\n"
        "def build(name):\n"
        "    assert name in MODELS\n"
        "    sub, mod, cls = getattr(importlib.import_module('dd.registry'), 'lookup')(name)\n"
        "    return getattr(importlib.import_module(f'dd.models.{sub}.{mod}'), cls)()\n\n\n"
        "if __name__ == '__main__':\n"
        "    r = Runner(build('Net'), 'tag' in sys.argv)\n"
        "    for _ in range(3):\n"
        "        r.step()\n"
        "    r.batch([1])\n"),
}


def test_dynamic_dispatch_consistent_across_cuts():
    """收起的一条边上碰巧有别的 import（runner 只 import 了 helpers 的一个常量），跑到的调用却是经由
    self.model 动态分派到 impl 的：收起时不能画成「引用 + runtime」的实线（展开后那条实线会「消失」，
    变成没跑到的灰边加一条虚线）。图上每条边的动态分派次数和点开边看到的明细必须对得上，每个切面都是。"""
    t = tmpdir("cs-dyn-")
    repo = t / "repo"
    for rel, src in _DD.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "dyn", "--", PY, "-m", "dd.main")
    cs("trace", repo, "--case", "mix", "--", PY, "-m", "dd.main", "tag")
    idx = ui_load.load_index(repo)
    hd, md = ui_load.load_hot(repo, idx, "dyn")
    hm, mm = ui_load.load_hot(repo, idx, "mix")
    RM, RI, RH = "dd/runner/|dd/models/", "dd/runner/|dd/models/impl/", "dd/runner/|dd/models/helpers.py"
    MR = "dd/main.py|dd/registry.py"        # 文件对文件：静态引用的是 MODELS，跑到的 lookup 是 getattr 取的

    def agree(g, hot):
        """图上的次数 = 边详情里的次数；图上的动态分派次数 = 边详情里「动态分派」那组的次数"""
        for k, n in g["hot"]["edges"].items():
            a, b = k.split("|")
            d = ui_edge.edge_detail(repo, idx, a, b, hot)
            dyn = sum(it["calls"] for it in d["items"] if it["status"] == "dynamic")
            assert d["counts"]["calls"] == n and dyn == g["hot"]["dyn"].get(k, 0), (k, n, d["counts"], g["hot"]["dyn"])

    shut = ui_graphview.graph_payload(repo, idx, hot=hd, hot_meta=md, open_=["dd/"])
    ids = {n["id"] for n in shut["graph"]["nodes"]}
    assert {"dd/runner/", "dd/models/"} <= ids, ids
    assert RM in shut["edgeKinds"] and shut["hot"]["edges"][RM] == 4 and shut["hot"]["dyn"][RM] == 4, shut["hot"]
    assert RM in shut["dynOnlyEdges"] and MR in shut["dynOnlyEdges"], shut["dynOnlyEdges"]
    agree(shut, hd)
    opened = ui_graphview.graph_payload(repo, idx, hot=hd, hot_meta=md, open_=["dd/", "dd/models/"])
    assert [RI.split("|")[0], RI.split("|")[1], 4] in opened["runtimeOnlyEdges"], opened["runtimeOnlyEdges"]
    assert RH in opened["edgeKinds"] and not opened["hot"]["edges"].get(RH) and RH not in opened["dynOnlyEdges"]
    agree(opened, hd)
    # 同一条边上也有确认调用（helpers.tag()）：照旧画实线，动态分派的次数单独带着
    mix = ui_graphview.graph_payload(repo, idx, hot=hm, hot_meta=mm, open_=["dd/"])
    assert mix["hot"]["edges"][RM] == 7 and mix["hot"]["dyn"][RM] == 4 and RM not in mix["dynOnlyEdges"], mix["hot"]
    agree(mix, hm)
    agree(ui_graphview.graph_payload(repo, idx, hot=hm, hot_meta=mm, open_=["dd/", "dd/models/"]), hm)
    # 动态分派的调用处：调用方函数体里那一行；经由 map() 这种仓库外的代码调到的，找过但找不到（[]）
    def callers(a, b):
        d = ui_edge.edge_detail(repo, idx, a, b, hd)
        return {c["sym"].partition("#")[2]: c for it in d["items"] if it["status"] == "dynamic"
                for r in it["runtime"] for c in r["callers"]}
    for a, b in (("dd/runner/loop.py", "dd/models/impl/net.py"), ("dd/runner/", "dd/models/")):
        cs_ = callers(a, b)
        assert [x["s"] for x in cs_["Runner.step"]["sites"]] == ["return self.model.forward(helpers.SCALE)"], cs_
        assert cs_["Runner.step"]["sites"][0]["f"] == "dd/runner/loop.py", cs_
        assert cs_["Runner.batch"]["sites"] == [] and cs_["Runner.batch"]["callee"] == "forward", cs_
    got = callers("dd/main.py", "dd/registry.py")["build"]["sites"]
    assert len(got) == 1 and "'lookup')(name)" in got[0]["s"], got
    # 按名字登记：带模块的类路径只认模块对得上的，同一处登记留带模块的那一行；只写类名的另起一处；
    # __all__ 是再导出清单不算；仓库里有同名类（helpers.Net）要说出来
    d = ui_edge.edge_detail(repo, idx, "dd/runner/loop.py", "dd/models/impl/net.py", hd)
    w = next(it for it in d["items"] if it["status"] == "dynamic")["wiring"]
    ln = next(i for i, x in enumerate(_DD["dd/main.py"].splitlines(), 1) if "build('Net')" in x)
    assert [(t["f"], t["l"], t["exact"]) for t in w["refs"]] == [
        ("dd/registry.py", 2, True), ("dd/main.py", ln, False), ("dd/wire.py", 1, False)], w
    assert w["same_name"] == 2 and w["n"] == 3 and "dd.models.impl.net.Net" in w["refs"][0]["s"], w
    nr = ui_load.load_index(repo)["name_refs"]
    assert not any(f.endswith("impl/__init__.py") for f, *_ in nr["Net"]), nr["Net"]


_SYN = {
    "sx/__init__.py": "",
    "sx/box.py": (
        "import functools\n\n\n"
        "class Box:\n"
        "    @property\n"
        "    def value(self):\n        return 1\n\n"
        "    @property\n"
        "    def size(self):\n        return 2\n\n"
        "    @size.setter\n"
        "    def size(self, v):\n        pass\n\n"
        "    @functools.cached_property\n"
        "    def heavy(self):\n        return 3\n\n"
        "    def __enter__(self):\n        return self\n\n"
        "    def __exit__(self, *exc):\n        return False\n\n"
        "    def __iter__(self):\n        return iter([1])\n\n"
        "    def __getitem__(self, i):\n        return i\n\n"
        "    def __add__(self, o):\n        return self\n\n"
        "    def __call__(self, x):\n        return x\n\n"
        "    def __len__(self):\n        return 1\n\n"
        "    def __contains__(self, x):\n        return True\n\n"
        "    def __hash__(self):\n        return 1\n\n"
        "    def __sub__(self, o):\n        return self\n\n\n"
        "class Made:\n"
        "    def __new__(cls):\n        return super().__new__(cls)\n\n\n"
        "def deco(f):\n    return f\n"),
    "sx/use.py": (
        "from sx.box import Box, Made, deco\n\n\n"
        "def run(b):\n"
        '    """Enter it with care: for all items in b, a + b is fine."""\n'
        "    # v = b.value 写在注释里的不算\n"
        "    v = b.value\n"
        "    b.size = 3\n"
        "    s = b.size\n"
        "    k = b.heavy\n"
        "    with b:\n        pass\n"
        "    for x in b:\n        pass\n"
        "    y = b[0]\n"
        "    z = b + b\n"
        "    return b(5)\n\n\n"
        "def typed(\n"                              # 多行、带标注的签名：list[int]、-> 不是调用处
        "    b: 'Box',\n"
        "    items: list[int],\n"
        "    lookup: dict[str, int] | None = None,\n"
        ") -> int:\n"
        "    cache: dict[str, int] = {}\n"               # 标注里的 [] 也不是
        "    if b:\n"                                    # 真值判断 → __len__
        "        pass\n"
        "    if 3 in b:\n"                               # in → __contains__
        "        pass\n"
        "    d = {b: 1}\n"                               # 字典的键 → __hash__
        "    w = b - b\n"
        "    Made()\n"                                   # 类名(…) → __new__
        "    return b[1]\n\n\n"
        "def wrap():\n"
        "    @deco\n"                                    # 装饰器应用：调用方里写的是 @deco
        "    def inner():\n"
        "        pass\n"
        "    return inner\n\n\n"
        "if __name__ == '__main__':\n"
        "    run(Box())\n"
        "    typed(Box(), [1])\n"
        "    wrap()\n"),
}


def test_call_sites_by_syntax():
    """不写名字的调用：property 取属性就是调用（`.名字`，有 setter 的也要认得 getter），特殊方法由
    with / for / [] / + 触发；边详情的 from 要落在调用方里写这些的那一行上（docstring 和注释里的不算），
    落不了的（对象(…) 调 __call__）说清楚是怎么调到的，而不是「没直接写 __call__(…)」。"""
    repo = tmpdir("cs-syn-") / "repo"
    for rel, src in _SYN.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "syn", "--", PY, "-m", "sx.use")
    idx = ui_load.load_index(repo)
    hot, _ = ui_load.load_hot(repo, idx, "syn")
    d = ui_edge.edge_detail(repo, idx, "sx/use.py", "sx/box.py", hot)
    got = {r["sym"].partition("#")[2]: c for it in d["items"] for r in it["runtime"] for c in r["callers"]
           if c["sym"] == "sx/use.py#run"}
    assert not any("<L" in k for k in got), sorted(got)           # getter 不能成了「Box 里的某个闭包」
    use = _SYN["sx/use.py"].splitlines()
    want = {"Box.value": ["v = b.value"], "Box.size": ["b.size = 3", "s = b.size"], "Box.heavy": ["k = b.heavy"],
            "Box.__enter__": ["with b:"], "Box.__exit__": ["with b:"], "Box.__iter__": ["for x in b:"],
            "Box.__getitem__": ["y = b[0]"], "Box.__add__": ["z = b + b"]}
    for q, lines in want.items():
        c = got[q]
        assert [x["s"] for x in c["sites"]] == lines, (q, c)
        assert all(use[x["l"] - 1].strip() == x["s"] for x in c["sites"]), (q, c)
    assert got["Box.value"]["how"] == "attr" and got["Box.value"]["form"] == ".value", got["Box.value"]
    assert got["Box.__enter__"]["how"] == "syntax" and got["Box.__enter__"]["form"] == "with …", got["Box.__enter__"]
    call = got["Box.__call__"]
    assert call["sites"] == [] and call["how"] == "implicit" and call["form"] == "对象(…)", call
    # 按语法树认，不按文本：签名的续行、标注里的 list[int]、dict[str, int] | None、-> 都不算调用处
    typed = {r["sym"].partition("#")[2]: c for it in d["items"] for r in it["runtime"] for c in r["callers"]
             if c["sym"] == "sx/use.py#typed"}
    for q, lines in {"Box.__getitem__": ["return b[1]"], "Box.__len__": ["if b:"], "Box.__contains__": ["if 3 in b:"],
                     "Box.__hash__": ["d = {b: 1}"], "Box.__sub__": ["w = b - b"], "Made.__new__": ["Made()"]}.items():
        assert [x["s"] for x in typed[q]["sites"]] == lines, (q, typed[q])
    deco = next(c for it in d["items"] for r in it["runtime"] for c in r["callers"]
                if r["sym"] == "sx/box.py#deco" and c["sym"] == "sx/use.py#wrap")
    assert [x["s"] for x in deco["sites"]] == ["@deco"], deco
    # 符号表：函数也记装饰器；同名的 def 照旧留最后一个（setter），getter 的位置记在 "a" 里
    size, box = idx["symbols"]["sx/box.py#Box.size"], _SYN["sx/box.py"].splitlines()
    assert size["d"] == ["setter"] and [a[0] for a in size["a"]] == [box.index("    def size(self):") + 1], size


_CALLBACK = {                                   # 仓库：Flask 的形状，视图由使用者注册、由 dispatch_request 回调
    "web/__init__.py": "",
    "web/ctx.py": "from contextlib import contextmanager\n\n\n@contextmanager\ndef request_ctx():\n    yield\n",
    "web/app.py": (
        "from web.ctx import request_ctx\n\n\n"
        "class App:\n"
        "    def __init__(self):\n        self.views = {}\n\n"
        "    def route(self, path):\n"
        "        def deco(fn):\n            self.views[path] = fn\n            return fn\n"
        "        return deco\n\n"
        "    def dispatch_request(self, path):\n"
        "        with request_ctx():\n            return self.views[path]()\n"),
    "web/json.py": "def jsonify(obj):\n    return repr(obj)\n",
    "web/templating.py": "def render(s, **kw):\n    return s.format(**kw)\n",
    "web/model.py": "class Model:\n    def forward(self, x):\n        return x + 1\n",
    "web/worker.py": ("from extlib import runner\nfrom web.model import Model\n\n\n"
                      "def run():\n    return runner.execute(Model().forward, 1)\n"),
}
_CB_LIB = {"extlib/__init__.py": "", "extlib/runner.py": "def execute(fn, x):\n    return fn(x)\n"}
_CB_CASE = {                              # case 脚本和它旁边的模块：放在仓库外，或者仓库里 scan 不扫的 examples/
    "case.py": ("from web.app import App\nfrom web.json import jsonify\nfrom web.templating import render\n"
                "from web import worker\nimport views\n\napp = App()\n\n\n"
                "@app.route('/a')\ndef view_a():\n    return jsonify({'a': 1})\n\n\n"
                "@app.route('/b')\ndef view_b():\n    return render('hi {x}', x=1)\n\n\n"
                "app.route('/c')(views.view_c)\nfor p in ('/a', '/b', '/c'):\n    app.dispatch_request(p)\n"
                "worker.run()\n"),
    "views.py": "from web.json import jsonify\n\n\ndef view_c():\n    return jsonify([3])\n",
}


def test_callbacks_from_case_code():
    """case 脚本（仓库外）里定义、被仓库代码回调的函数（Flask 的视图）调到的仓库函数，调用方是 case 的
    代码，不是最近的仓库帧：dispatch_request → jsonify 这条边并不存在，不能画成动态分派。穿过安装包 /
    标准库的调用照旧记到最近的仓库帧上（worker.run 经由 site-packages 里的 runner 调 Model.forward、
    dispatch_request 经由 contextlib 进 request_ctx）。同一份 case 放在仓库外和放在仓库里 scan 不扫的
    examples/，图上一样；被调的次数照算，funcs 里只有仓库代码。"""
    t = tmpdir("cs-cb-")
    repo, case, sp = t / "repo", t / "case", t / "lib" / "site-packages"
    for base, files in ((repo, _CALLBACK), (sp, _CB_LIB), (case, _CB_CASE), (repo / "examples", _CB_CASE)):
        for rel, src in files.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(src)
    cs("scan", repo)
    env = ["--env", f"PYTHONPATH={repo}{os.pathsep}{sp}"]
    cs("trace", repo, "--case", "out", "--events", *env, "--", PY, str(case / "case.py"))
    cs("trace", repo, "--case", "in", *env, "--", PY, "examples/case.py")
    idx = ui_load.load_index(repo)
    assert "examples/case.py" not in idx["files"], "examples/ 应当不在 index 里"
    ho, mo = ui_load.load_hot(repo, idx, "out")
    hi, mi = ui_load.load_hot(repo, idx, "in")
    want = {"web/app.py|web/ctx.py": 3, "web/worker.py|web/model.py": 1}
    assert ho["edges"] == want and hi["edges"] == want, (ho["edges"], hi["edges"])
    assert ho["symbols"] == hi["symbols"] and ho["symbols"]["web/json.py#jsonify"] == 2, (ho["symbols"], hi["symbols"])
    assert list(ho["edge_calls"]["web/worker.py|web/model.py"]["web/model.py#Model.forward"]["callers"]) == ["web/worker.py#run"]
    g = ui_graphview.graph_payload(repo, idx, hot=ho, hot_meta=mo)
    assert not g["runtimeOnlyEdges"] and not g["hot"]["dyn"], (g["runtimeOnlyEdges"], g["hot"]["dyn"])
    # 数据里：调用方记成仓库外的 case 代码（index 之外，和 examples/ 里的一样不上图）；funcs 只有仓库代码
    out_run, rd_out, _ = runs.resolve(repo, "out")
    c = runs.load_counts(rd_out, None)
    assert all(k.startswith("web/") for k in c["funcs"]), sorted(c["funcs"])
    into = {k.split("|")[0].rpartition(":")[0] for k in c["func_edges"] if k.split("|")[1].startswith("web/json.py:")}
    assert into == {"<外部代码>/case.py", "<外部代码>/views.py"}, into
    assert out_run["status"] == "ok" and out_run["summary"]["n_procs_active"] == 1, out_run
    # 时序事件和计数同一个口径：没有 dispatch_request → jsonify 这种 span
    sp_, _ = _spans(rd_out)
    assert not [s for s in sp_ if s["a"].startswith("web/app.py") and s["b"].startswith(("web/json", "web/templ"))], sp_
    xf = sum(v for e, v in c["func_edges"].items()
             if e.split("|")[0].rpartition(":")[0] != e.split("|")[1].rpartition(":")[0])
    assert out_run["events"]["n_calls"] == xf, (out_run["events"], xf)


_CASEPKG = {                            # python -m casepkg.main：包的 __init__.py 在 __main__ 有 __file__ 之前就跑了
    "casepkg/__init__.py": ("from web.app import App\nfrom web.json import jsonify\n\napp = App()\n\n\n"
                            "@app.route('/a')\ndef view_a():\n    return jsonify(1)\n"),
    "casepkg/helpers.py": "def twice(f):\n    return f() + f()\n",
    "casepkg/main.py": ("from casepkg import app\nfrom casepkg.helpers import twice\n\n"
                        "for _ in range(50):\n    twice(lambda: 1)\n"
                        "app.dispatch_request('/a')\n"),
}
_UCASE = {                              # python -m unittest：__main__ 是标准库里的，只能靠执行目录认 case 的代码
    "test_views.py": ("import unittest\n\nfrom web.app import App\nfrom web.json import jsonify\n\napp = App()\n\n\n"
                      "@app.route('/x')\ndef view_x():\n    return jsonify(2)\n\n\n"
                      "class T(unittest.TestCase):\n    def test_a(self):\n        app.dispatch_request('/x')\n"),
}


def test_case_code_detection():
    """case 的代码怎么认：python -m 包.模块 时包的 __init__.py（先跑、那时还没有入口文件）事后补认；入口是库
    （python -m unittest）时按执行目录（--cwd，经 CODESTRATA_CASE_DIRS 传给 hook）认。认出来的 case 代码只在
    栈上当调用方：它回调仓库函数不画成动态分派；case 里自己调来调去不记边、不计数"""
    t = tmpdir("cs-case-")
    repo = t / "repo"
    for base, files in ((repo, _CALLBACK), (t / "m", _CASEPKG), (t / "u", _UCASE)):
        for rel, src in files.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "m", "--cwd", t / "m", "--env", f"PYTHONPATH={repo}", "--", PY, "-m", "casepkg.main")
    cs("trace", repo, "--case", "u", "--cwd", t / "u", "--env", f"PYTHONPATH={repo}", "--", PY, "-m", "unittest", "test_views")
    idx = ui_load.load_index(repo)
    for case, src in (("m", "<外部代码>/__init__.py"), ("u", "<外部代码>/test_views.py")):
        hot, meta = ui_load.load_hot(repo, idx, case)
        g = ui_graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta)
        assert not g["runtimeOnlyEdges"] and not g["hot"]["dyn"], (case, g["runtimeOnlyEdges"], g["hot"]["dyn"])
        _, rd, _ = runs.resolve(repo, case)
        c = runs.load_counts(rd, None)
        into = {k.split("|")[0].rpartition(":")[0] for k in c["func_edges"] if k.split("|")[1].startswith("web/json.py:")}
        assert into == {src}, (case, into)
        assert all(k.startswith("web/") for k in c["funcs"]), (case, sorted(c["funcs"]))
        assert not [k for k in c["func_edges"] if k.split("|")[1].startswith("<")], (case, c["func_edges"])


_GP = {
    "gp/__init__.py": "",
    "gp/core.py": ("def ident[T](x: T) -> T:\n    return x\n\n\n"
                   "class Box[T]:\n    def get(self):\n        return 1\n"),
    "gp/main.py": ("def run():\n    from gp import core\n    core.ident(1)\n    core.Box().get()\n\n\n"
                   "if __name__ == '__main__':\n    run()\n"),
}


def test_generic_defs_are_definitions():
    """PEP 695 的 def f[T] / class C[T]：定义时先跑一帧 <generic parameters of …>，它和模块顶层一样是定义，
    不算成对 f / C 的调用（3.12 起才有这种写法）"""
    if sys.version_info < (3, 12):
        print("    （跳过：要 Python 3.12）")
        return
    repo = tmpdir("cs-gp-") / "repo"
    for rel, src in _GP.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    cs("trace", repo, "--case", "gp", "--phase", "run=gp.main:run", "--", PY, "-m", "gp.main")
    h, _ = ui_load.load_hot(repo, ui_load.load_index(repo), "gp@run")
    assert h["symbols"] == {"gp/main.py#run": 1, "gp/core.py#ident": 1, "gp/core.py#Box.get": 1}, h["symbols"]
    assert h["files"]["gp/core.py"] == 2 and h["class_frames"] == 1, (h["files"], h["class_frames"])
    assert set(h["module_exec"]) == {"gp/core.py"}, h["module_exec"]


_RX = {
    "rx/__init__.py": "from rx.executor import Executor\nfrom .models import LIMIT as DEFAULT_LIMIT\n",
    "rx/executor/__init__.py": "from .abstract import Executor\n",
    "rx/executor/abstract.py": "class Executor:\n    def run(self):\n        return 1\n",
    "rx/models.py": ("LIMIT: int = 30\nSTATI = (301, 302)\ntry:\n    FAST = True\nexcept ImportError:\n"
                     "    FAST = False\n\n\nclass Request:\n    pass\n"),
    "rx/sessions.py": ("from .models import LIMIT, STATI, FAST, Request\nfrom rx.executor import Executor\n"
                       "from rx import DEFAULT_LIMIT\n\n\n"
                       "def go():\n    return LIMIT, STATI, FAST, Request(), Executor().run(), DEFAULT_LIMIT\n"),
}


def test_edge_defs_vars_and_reexports():
    """边详情的「to」：模块级变量（带标注的 `LIMIT: int = 30` 也算）、__init__ 再导出的类 / 改了名的变量
    都要有定义，而且和 Ctrl+点击（xref）落在同一处；老的 xref.json 没有 names：照旧没有定义、不报错。"""
    repo = tmpdir("cs-defs-") / "repo"
    for rel, src in _RX.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    idx = ui_load.load_index(repo)

    def defs(a, b):
        items = ui_edge.edge_detail(repo, idx, a, b)["items"]
        return {it["name"]: it["def"] and (it["def"]["f"], it["def"]["l"], it["def"]["k"], it.get("sig"))
                for it in items}
    assert defs("rx/sessions.py", "rx/models.py") == {
        "LIMIT": ("rx/models.py", 1, "var", ["LIMIT: int = 30"]),
        "STATI": ("rx/models.py", 2, "var", ["STATI = (301, 302)"]),
        "FAST": ("rx/models.py", 4, "var", ["FAST = True"]),          # try 里的第一次
        "Request": ("rx/models.py", 9, "class", ["class Request:"])}, defs("rx/sessions.py", "rx/models.py")
    ex = defs("rx/sessions.py", "rx/executor/__init__.py")
    assert ex == {"Executor": ("rx/executor/abstract.py", 1, "class", ["class Executor:"])}, ex
    alias = defs("rx/sessions.py", "rx/__init__.py")
    assert alias == {"DEFAULT_LIMIT": ("rx/models.py", 1, "var", ["LIMIT: int = 30"])}, alias
    # 和 Ctrl+点击同一处
    x = ui_source.xref_for(repo, "rx/sessions.py")
    ctrl = {t.rpartition("#")[2]: tuple(w) for t, w in x["targets"].values() if t[0] in "sv"}
    assert ctrl["Executor"] == ex["Executor"][:2] and ctrl["LIMIT"] == alias["DEFAULT_LIMIT"][:2], ctrl
    # 目录级的边（合并了几对单元）照样带着
    d = ui_edge.edge_detail(repo, idx, "rx/sessions.py", "rx/executor/")
    assert [it["def"]["f"] for it in d["items"]] == ["rx/executor/abstract.py"], d["items"]
    # 老的 xref.json（没有 names）：没有定义，面板照旧说没找到
    p = repo / ".codestrata" / "xref.json"
    X = json.loads(p.read_text())
    del X["names"]
    p.write_text(json.dumps(X))
    os.utime(p, ns=(time.time_ns() + 10**9,) * 2)
    assert defs("rx/sessions.py", "rx/models.py")["LIMIT"] is None


# TYPE_CHECKING 里的 import：tc.ctx 只在标注里用 App（from __future__ 下是 Name，不是字符串）；
# tc.sub.util 用字符串标注；tc.cli 同一个名字函数里再运行时 import 一次；运行时 ctx 经 self.app 调到 app
_TC = {
    "tc/__init__.py": "",
    "tc/app.py": ("from .ctx import Ctx\n\n\n"
                  "class App:\n"
                  "    def run(self):\n        return Ctx(self).push()\n\n"
                  "    def hook(self):\n        return 1\n"),
    "tc/ctx.py": ("from __future__ import annotations\n\nfrom typing import TYPE_CHECKING\n\n"
                  "if TYPE_CHECKING:\n    from .app import App\n\n\n"
                  "class Ctx:\n"
                  "    def __init__(self, app: App) -> None:\n        self.app: App = app\n\n"
                  "    def push(self) -> int:\n        return self.app.hook()\n"),
    "tc/sub/__init__.py": "",
    "tc/sub/util.py": ("import typing\n\nif typing.TYPE_CHECKING:\n    from ..ctx import Ctx\n\n\n"
                   "def depth(c: 'Ctx') -> int:\n    return 0\n"),
    "tc/cli.py": ("from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from .app import App\n\n\n"
                  "def main() -> 'App':\n    from .app import App\n    App().run()\n    return App()\n"),
    "tc/__main__.py": "from .cli import main\n\nmain()\n",
}


def test_type_checking_imports_are_not_dependencies():
    """if TYPE_CHECKING: 里的 import 运行时不执行：不算依赖、不进架构高度、不画成实线——不管名字在标注里
    有没有被引用（早先 from __future__ 下的标注引用会把它变成「1 符号」的实线回边）。它另记在 type_edges，
    边详情里是「仅类型」；函数里再运行时 import 同一个名字的，照旧是依赖。Ctrl+点击标注里的名字照样能跳。"""
    t = tmpdir("cs-tc-")
    repo = t / "repo"
    for rel, src in _TC.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(src)
    cs("scan", repo)
    idx = ui_load.load_index(repo)
    E = {(a, b): w for a, b, w in idx["edges"]}
    T = {(a, b): w for a, b, w in idx.get("type_edges") or []}
    CTX, APP, CLI, SUB, UTIL = "tc/ctx.py", "tc/app.py", "tc/cli.py", "tc/sub/", "tc/sub/util.py"
    assert (CTX, APP) not in E and T[(CTX, APP)] == 1, (E, T)
    assert (UTIL, CTX) not in E and T[(UTIL, CTX)] == 1, (E, T)
    assert E[(CLI, APP)] == 1 and T[(CLI, APP)] == 1, (E, T)      # 函数里的那条是真依赖
    # 高度只看运行时的 import：ctx 只被 app import，是叶子
    assert idx["packages"][CTX]["alt"] == -1.0, idx["packages"][CTX]
    assert f"{CTX}|{APP}" not in idx["edge_uses"], idx["edge_uses"]
    why = lambda k: sorted((x["n"], x["why"]) for x in idx["edge_dead"].get(k, []))
    assert why(f"{CTX}|{APP}") == [("App", "type")] and why(f"{UTIL}|{CTX}") == [("Ctx", "type")]
    assert why(f"{CLI}|{APP}") == [] and "tc/app.py#App" in idx["edge_uses"][f"{CLI}|{APP}"], idx["edge_uses"]
    g = ui_graphview.graph_payload(repo, idx, open_=["tc/"])
    assert f"{CTX}|{APP}" not in g["edgeKinds"] and [CTX, APP, 1] in g["typeOnlyEdges"], g["typeOnlyEdges"]
    assert f"{CLI}|{APP}" in g["edgeKinds"] and not any(e[:2] == [CLI, APP] for e in g["typeOnlyEdges"])
    assert g["pkgs"][CTX]["alt"] == -1.0 and g["pkgs"][CTX]["out"] == 0, g["pkgs"][CTX]
    assert [SUB, CTX, 1] in g["typeOnlyEdges"], g["typeOnlyEdges"]         # 收起的目录 → 文件
    for a, b, n in ((CTX, APP, "App"), (SUB, CTX, "Ctx")):
        d = ui_edge.edge_detail(repo, idx, a, b)
        assert not d["static_edge"] and d["type_edge"] and d["items"] == [] and d["n_sites"] == 1, d
        assert [(x["n"], x["why"]) for x in d["import_only"]] == [(n, "type")], d["import_only"]
    d = ui_edge.edge_detail(repo, idx, CLI, APP)
    assert d["static_edge"] and d["type_edge"], d                     # 两样都有：是依赖
    # runtime：ctx 经 self.app 调到 app 的 hook——两端之间运行时没有 import，是只在 runtime 出现的边
    cs("trace", repo, "--case", "tc", "--", PY, "-m", "tc")
    hot, meta = ui_load.load_hot(repo, idx, "tc")
    g = ui_graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta, open_=["tc/"])
    assert any(e[:2] == [CTX, APP] for e in g["runtimeOnlyEdges"]), g["runtimeOnlyEdges"]
    d = ui_edge.edge_detail(repo, idx, CTX, APP, hot)
    assert [(it["name"], it["status"]) for it in d["items"]] == [("App", "dynamic")], d["items"]
    assert [x["why"] for x in d["import_only"]] == ["type"], d["import_only"]
    # 标注里的名字 Ctrl+点击照样跳到定义（xref 自己解析 import，不看边）
    x = json.loads((repo / ".codestrata" / "xref.json").read_text())
    lines = _TC["tc/ctx.py"].splitlines()
    hits = [x["targets"][k[3]] for k in x["files"]["tc/ctx.py"] if lines[k[0] - 1][k[1]:k[2]] == "App"]
    assert hits and set(hits) == {"s:tc/app.py#App"}, hits


def test_path_ids():
    """节点 id 按路径写、不认语言（cut.py）：单元是文件路径，目录带 /，本层文件是 <目录>*，
    根目录的脚本在 ./ 里（它只装直接放着的文件，不装别的扫描根）；显示名来自 label / sep，没有时按路径切。"""
    from codestrata import cut
    assert cut.unit_dir("a/b/c.py") == "a/b/" and cut.unit_dir("train.py") == cut.ROOT_DIR
    assert cut.root_dir("src/lib") == "src/lib/" and cut.root_dir(".") == cut.ROOT_DIR
    assert cut.residual("a/b/") == "a/b/*" and cut.is_residual("a/b/*") and not cut.is_residual("a/b/")
    assert cut.residual_base("a/b/*") == "a/b/"
    assert cut.within("a/b/c.py", "a/") and cut.within("a/b/", "a/") and cut.within("a/*", "a/")
    assert not cut.within("a/", "a/") and not cut.within("ab/x.py", "a/")
    assert cut.within("train.py", "./") and cut.within("./*", "./") and not cut.within("pkg/x.py", "./")
    units = {"pkg/__init__.py": {"label": "pkg.__init__", "sep": "."}, "pkg/sub/x.py": {"label": "pkg.sub.x", "sep": "."},
             "src/lib/y.py": {"label": "lib.y", "sep": "."}, "run.py": {"label": "repo.run", "sep": "."},
             "csrc/k.cu": {}}
    tree = cut.dir_tree(units, ["pkg", "src/lib", ".", "csrc"])
    assert sorted(d for d, v in tree.items() if v["parent"] is None) == ["./", "csrc/", "pkg/", "src/lib/"], tree
    assert tree["pkg/sub/"]["parent"] == "pkg/" and tree["pkg/"]["units"] == ["pkg/__init__.py"]
    assert (tree["pkg/"]["label"], tree["pkg/sub/"]["label"], tree["src/lib/"]["label"], tree["./"]["label"]) == \
        ("pkg", "pkg.sub", "lib", "repo"), tree
    idx = {"dirs": tree, "packages": {u: dict(v, files=1, loc=1, classes=0, funcs=0) for u, v in units.items()}}
    assert cut.label(idx, "pkg/sub/x.py") == (["pkg", "sub", "x"], ".")
    assert cut.label(idx, "pkg/sub/*") == (["pkg", "sub"], ".")            # 本层文件用它目录的
    assert cut.label(idx, "csrc/k.cu") == (["csrc", "k.cu"], "/")          # 没给 label：按路径切
    assert cut.short(idx, "csrc/k.cu") == "k.cu"
    for text in ("pkg/sub/", "pkg/sub", "pkg.sub"):                        # 命令行里写哪种都认
        assert cut.find_dir(idx, text) == "pkg/sub/", text
    assert cut.find_dir(idx, "nope") is None


def test_duplicate_short_labels():
    """同一个切面上最后一段相同的节点（flask.app 和 flask.sansio.app、vllm 的两个 kernels/）：图上、面板里
    补上父目录段分开；没撞的照旧只写最后一段；框里的「本层文件」不动。"""
    t = tmpdir("cs-lb-")
    repo = t / "repo"
    for rel in ("lb/__init__.py", "lb/app.py", "lb/cli.py", "lb/sansio/__init__.py", "lb/sansio/app.py",
                "lb/sansio/scaffold.py", "lb/kernels/__init__.py", "lb/kernels/k.py",
                "lb/ops/__init__.py", "lb/ops/kernels/__init__.py", "lb/ops/kernels/k.py", "lb/ops/util.py",
                "lb/sansio/big.py", "lb/big/sub/__init__.py", *(f"lb/big/m{i}.py" for i in range(13))):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(f"def f_{rel.replace('/', '_')[:-3]}():\n    return 1\n")
    cs("scan", repo)
    idx = ui_load.load_index(repo)
    g = ui_graphview.graph_payload(repo, idx, open_=["lb/", "lb/sansio/", "lb/ops/"])
    lab = {n["id"]: n["label"] for n in g["graph"]["nodes"]}
    assert lab["lb/app.py"] == "app" and lab["lb/sansio/app.py"] == "sansio.app", lab
    assert lab["lb/kernels/"] == "kernels/" and lab["lb/ops/kernels/"] == "ops.kernels/", lab
    assert lab["lb/cli.py"] == "cli" and lab["lb/sansio/scaffold.py"] == "scaffold" and lab["lb/ops/util.py"] == "util", lab
    assert len(set(lab.values())) == len(lab), lab
    assert g["alias"]["lb/sansio/app.py"] == "sansio.app" and "lb/cli.py" not in g["alias"], g["alias"]
    # 面板、搜索栏用的短名（names）：撞了名的补过父目录段，其余是显示名的最后一段；本层文件节点用它目录的
    assert g["names"]["lb/sansio/app.py"] == "sansio.app" and g["names"]["lb/cli.py"] == "cli", g["names"]
    # 文件多（又有子目录）、合成了「本层文件」的 lb.big 和 lb.sansio.big 撞名：框里的本层文件节点照旧写「本层文件」
    g3 = ui_graphview.graph_payload(repo, idx, open_=["lb/", "lb/sansio/", "lb/big/"])
    lab3 = {n["id"]: n["label"] for n in g3["graph"]["nodes"]}
    assert lab3["lb/big/*"] == "本层文件" and lab3["lb/sansio/big.py"] == "sansio.big", lab3
    # 收起 sansio：只剩一个 app，不再补
    g2 = ui_graphview.graph_payload(repo, idx, open_=["lb/", "lb/ops/"])
    assert {n["id"]: n["label"] for n in g2["graph"]["nodes"]}["lb/app.py"] == "app" and "lb/app.py" not in g2["alias"]


def test_serve_ignores_old_cmp_links():
    """对比功能已经去掉：serve 忽略老链接里的 cmp=，图照常出来、不带对比的数据"""
    repo = fresh()
    cs("trace", repo, "--case", "a", "--", PY, "-c", "from fakesvc import work; work.init_model()")
    cs("trace", repo, "--case", "b", "--", PY, "-m", "fakesvc.truth")
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
        st, g = get("/api/graph?run=a&cmp=b")
        st0, g0 = get("/api/graph?run=a")
        assert st == st0 == 200 and "cmp" not in g and g["hot"]["edges"] == g0["hot"]["edges"], (st, list(g))
    finally:
        srv.kill()
        srv.wait()


def test_no_export_command():
    """导出 / 分享（graph 命令、单文件 HTML、静态站、--public）已经去掉：命令行不认 graph"""
    r = cs("graph", fresh(), check=False)
    assert r.returncode != 0 and "invalid choice" in (r.stdout + r.stderr), r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
