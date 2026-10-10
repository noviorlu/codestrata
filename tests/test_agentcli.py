"""给 agent 的命令（status / lanes / guide）和它们共用的一层：REF、列别名、引号、JSON 信封、错误码。

    python tests/test_agentcli.py [名字里的词…]
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

from common import HERE, PY, cs, fresh, run_tests, served  # noqa: E402

from codestrata import laneid, ref  # noqa: E402
from codestrata.cli import out  # noqa: E402
from codestrata.errors import EXIT, CodestrataError  # noqa: E402


def csc(*args, cwd, env=None) -> subprocess.CompletedProcess:
    """在 cwd 里跑 codestrata（不检查退出码）"""
    e = dict(os.environ)
    e["PYTHONPATH"] = str(HERE.parent) + os.pathsep + e.get("PYTHONPATH", "")
    e.update(env or {})
    return subprocess.run([PY, "-m", "codestrata", *map(str, args)], capture_output=True, text=True, cwd=cwd,
                          env=e, timeout=120)


def one_json(r: subprocess.CompletedProcess) -> dict:
    """stdout 上只有一个 JSON"""
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    assert len(lines) == 1, r.stdout
    return json.loads(lines[0])


_TRUTH: list = []


def truth():
    """录一次 fakesvc.truth（多线程、子进程），用 --phase 切出一个阶段 work；整个文件共用一份"""
    if not _TRUTH:
        repo = fresh()
        cs("trace", repo, "--case", "truth", "--phase", "work=fakesvc.truth:s_threads", "--",
           PY, "-m", "fakesvc.truth")
        rid = sorted(p.name for p in (repo / ".codestrata" / "runs").iterdir() if p.name.endswith("-truth"))[-1]
        _TRUTH.append((repo, rid))
    return _TRUTH[0]


# ---------------------------------------------------------------- 纯函数

def test_proc_aliases():
    """进程别名：去掉同一族共有的头尾词，取最短的唯一前缀；完全同名的加 pid；扩展名去掉"""
    names = {1: "end2end.py", 2: "StageEngineCoreProc_stage0_replica0_DP0", 3: "StageEngineCoreProc_stage1_replica0_DP0",
             4: "StageEngineCoreProc_stage2_replica0_DP0", 5: "python", 6: "python", 7: "cpuinfo.py"}
    a = laneid.proc_aliases(names)
    assert a == {1: "end2end", 2: "stage0", 3: "stage1", 4: "stage2", 5: "python-1", 6: "python-2", 7: "cpuinfo"}, a
    # 名字一样的按启动先后编号（不按 pid）：换一次录制，同一个位置上的进程名字还一样
    a = laneid.proc_aliases({5: "python", 6: "python", 9: "python-1"}, starts={5: 200, 6: 100})
    assert a[6] == "python-1" or a[9] == "python-1", a
    assert sorted(a.values()) == sorted(set(a.values())) and a[6].startswith("python-") and a[5].startswith("python-"), a
    assert laneid.proc_aliases({5: "srv", 6: "srv"}, starts={5: 200, 6: 100}) == {6: "srv-1", 5: "srv-2"}
    rep = {1: "X_stage0_replica0_DP0", 2: "X_stage1_replica0_DP0", 3: "X_stage1_replica1_DP0"}
    assert laneid.proc_aliases(rep) == {1: "stage0", 2: "stage1_replica0", 3: "stage1_replica1"}
    assert laneid.proc_aliases({9: "-m my.mod"}) == {9: "my.mod"}


def test_lane_aliases_and_select():
    """列别名：进程别名/线程，GPU 列 gpu<设备>.<流>，撞了加 -2；选择器按整段匹配、不分大小写、认 pid:线程"""
    procs = {10: "stage1", 11: "stage10", 12: "end2end"}
    lanes = [{"id": "10:MainThread", "pid": 10, "thread": "MainThread"},
             {"id": "10:GPU 0 · 流 7", "pid": 10, "thread": "GPU 0 · 流 7", "gpu": [0, 7]},
             {"id": "11:MainThread", "pid": 11, "thread": "MainThread"},
             {"id": "12:a b", "pid": 12, "thread": "a b"},
             {"id": "12:a_b", "pid": 12, "thread": "a_b"}]
    al = laneid.lane_aliases(lanes, procs)
    assert al == {"10:MainThread": "stage1/MainThread", "10:GPU 0 · 流 7": "stage1/gpu0.7",
                  "11:MainThread": "stage10/MainThread", "12:a b": "end2end/a_b", "12:a_b": "end2end/a_b-2"}, al
    assert laneid.select(["stage1"], al) == ["10:MainThread", "10:GPU 0 · 流 7"]
    assert laneid.select(["STAGE1/mainthread"], al) == ["10:MainThread"]
    assert laneid.select(["*/gpu*"], al) == ["10:GPU 0 · 流 7"]
    assert laneid.select(["*/MainThread", "stage1"], al) == ["10:MainThread", "10:GPU 0 · 流 7", "11:MainThread"]
    assert laneid.select(["12:a b"], al) == ["12:a b"]
    try:
        laneid.select(["stage9"], al)
        raise AssertionError("应当报 lane_not_found")
    except CodestrataError as e:
        assert e.code == "lane_not_found" and e.exit == 3 and "stage1" in e.candidates, (e.code, e.candidates)
    try:
        laneid.select(["stage1/Main"], al)
        raise AssertionError("半个词不该配上")
    except CodestrataError as e:
        assert e.candidates == ["stage1/MainThread", "stage1/gpu0.7"], e.candidates


def test_parse_ref_and_url():
    """REF 和页面地址：主菜单转发的 /v/<端口>/、页面写的 @t%3D、+ 不当空格、lanes 键、别的键留在 view 里"""
    r = ref.parse("run_x@serving/stage1,end2end/orchestrator")
    assert (r.run, r.rest, r.lanes, r.page) == ("run_x", "serving/stage1,end2end/orchestrator", [], None)
    r = ref.parse("run_x/stage1")
    assert (r.run, r.rest, r.lanes) == ("run_x", None, ["stage1"])
    r = ref.parse("http://127.0.0.1:8930/v/58351/#run=20261001-170349-x%40t%3D1-2&lanes=stage1&view=lanes&sel=l%3Ahandoff%7Czmq")
    assert r.page["port"] == 58351 and r.page["prefix"] == "/v/58351/", r.page
    assert (r.run, r.rest, r.lanes) == ("20261001-170349-x", "t=1-2", ["stage1"])
    assert r.view == {"view": "lanes", "sel": "l:handoff|zmq"}, r.view
    r = ref.parse("http://localhost:8900/#run=x@serving+0.6s-3.0s")
    assert r.rest == "serving+0.6s-3.0s"
    r = ref.parse("http://127.0.0.1:8900/")
    assert r.run is None and r.page["port"] == 8900
    for bad in ("", "@serving", "http://127.0.0.1/#run=x"):
        try:
            ref.parse(bad)
            raise AssertionError(bad)
        except CodestrataError as e:
            assert e.code == "usage", (bad, e.code)


def test_ranges():
    """范围：阶段名按最长匹配（serve 和 serve-2 都在）、t= 的微秒和秒、阶段 + 秒；越界、反了、写错都带候选"""
    run = {"id": "R", "phases": [{"name": "start"}, {"name": "serve"}, {"name": "serve-2"}],
           "phase_log": [["start", 0, "start"], ["serve", 1_000_000, "hook"], ["serve-2", 3_000_000, "hook"]]}
    assert ref.split_range(run, "serve-2/stage1") == ("serve-2", ["stage1"])
    assert ref.split_range(run, "serve+0.5s-1s/a,b") == ("serve+0.5s-1s", ["a", "b"])
    assert ref.split_range(run, "t=1-2") == ("t=1-2", None)
    end = 5_000_000
    assert ref.parse_range(run, "serve-2", end) == ("serve-2", [(3_000_000, 5_000_000)])
    assert ref.parse_range(run, "t=10-20", end) == ("t=10-20", [(10, 20)])
    assert ref.parse_range(run, "t=1.5s-2.25s", end) == ("t=1500000-2250000", [(1_500_000, 2_250_000)])
    assert ref.parse_range(run, "serve+0.5s-1.5s", end) == ("t=1500000-2500000", [(1_500_000, 2_500_000)])
    for rng, code in (("t=0-6000000", "window_out_of_range"), ("t=5-3", "bad_window"), ("t=1-2,3-4", "bad_window"),
                      ("servng", "phase_not_found"), ("serve+1s-3s", "window_out_of_range"), ("t=x", "bad_window")):
        try:
            ref.parse_range(run, rng, end)
            raise AssertionError(rng)
        except CodestrataError as e:
            assert e.code == code and e.exit == 3, (rng, e.code)
            assert "R@serve" in e.candidates and "R@t=0-5000000" in e.candidates, e.candidates


def test_quoting_roundtrip():
    """CLI 打出的每条命令过一遍 shlex.split 再解析，得到同一个 REF / 东西：# & | * 空格、页面地址都不被 shell 吃掉"""
    cases = ["R@serving/stage1/*", "l:handoff|zmq|stage1/x|end2end/y", "#24", "a&b", "x y",
             "http://127.0.0.1:8900/#run=R@serving&lanes=stage1", "R@t=1-2/*/gpu*"]
    for c in cases:
        cmd = out.command("lanes", c, repo=None)
        argv = shlex.split(cmd)
        assert argv == ["codestrata", "lanes", c], (c, cmd, argv)
    url = cases[5]
    back = ref.parse(shlex.split(out.command("status", url))[-1])
    assert (back.run, back.rest, back.lanes) == ("R", "serving", ["stage1"])
    cmd = out.command("runs", "merge", "R", repo=HERE / "a dir")
    assert shlex.split(cmd) == ["codestrata", "runs", "merge", "-C", str(HERE / "a dir"), "R"], cmd
    cmd = out.command("scan", repo=HERE / "a dir")
    assert shlex.split(cmd) == ["codestrata", "scan", str(HERE / "a dir")], cmd
    cmd = out.command("lanes", "R", repo=HERE)
    assert shlex.split(cmd) == ["codestrata", "lanes", "-C", str(HERE), "R"], cmd


def test_exit_codes_table():
    assert EXIT["usage"] == 2 and EXIT["run_not_found"] == 3 and EXIT["no_events"] == 4
    assert EXIT["no_live_page"] == 5 and EXIT["pending"] == 6


# ---------------------------------------------------------------- 命令

def test_guide():
    """guide ≤ 80 行，写着 REF 写法和每个命令；--json 是命令表；--skill 带 frontmatter"""
    r = cs("guide")
    lines = r.stdout.rstrip("\n").split("\n")
    assert len(lines) <= 80, len(lines)
    for w in ("REF", "status", "lanes", "引号", "--json", "退出码"):
        assert w in r.stdout, w
    j = one_json(cs("guide", "--json"))
    names = {c["name"] for c in j["data"]["commands"]}
    assert {"status", "lanes", "guide", "path", "trace"} <= names, names
    assert {c["effect"] for c in j["data"]["commands"]} <= {"read", "page", "write", "delete", "start", "record"}
    assert cs("guide", "--skill").stdout.startswith("---\nname: codestrata\n")


def test_status_and_lanes():
    """status / lanes 在录好的 run 上：文字和 JSON；从仓库的子目录里往上找到仓库；下一步能原样再跑"""
    repo, rid = truth()
    sub = repo / "fakesvc"
    r = csc("status", cwd=sub)
    assert r.returncode == 0 and rid in r.stdout and "从当前目录往上找到" in r.stdout, r.stdout + r.stderr
    j = one_json(csc("status", "truth@work", "--json", cwd=sub))
    assert j["ok"] and j["cmd"] == "status" and j["repo"] == str(repo), j
    assert j["ref"]["text"] == f"{rid}@work" and j["data"]["run"]["events"], j
    assert [p["name"] for p in j["data"]["phases"]] == ["start", "work"], j["data"]["phases"]
    assert all(n["effect"] == "read" for n in j["next"]), j["next"]
    # 下一步原样粘贴就能跑
    nxt = j["next"][0]["cmd"]
    r = csc(*shlex.split(nxt)[1:], cwd=sub)
    assert r.returncode == 0 and "MainThread" in r.stdout, r.stdout + r.stderr
    j = one_json(csc("lanes", f"{rid}@work", "--json", cwd=sub))
    lanes = j["data"]["lanes"]
    assert lanes and all("/" in x["lane"] for x in lanes), lanes
    main = next(x for x in lanes if x["lane"].endswith("/MainThread"))
    proc = main["proc"]
    # 只看一个进程 / 一列
    j2 = one_json(csc("lanes", f"{rid}@work/{proc}", "--json", cwd=sub))
    assert {x["proc"] for x in j2["data"]["lanes"]} == {proc}
    j3 = one_json(csc("lanes", f"{rid}@work/{main['lane']}", "--json", cwd=sub))
    assert [x["lane"] for x in j3["data"]["lanes"]] == [main["lane"]], j3["data"]["lanes"]
    assert j3["ref"]["lanes"] == [main["lane"]]
    # 从别的目录用 -C：下一步都带 -C
    j4 = one_json(cs("lanes", "-C", repo, "truth@work", "--json"))
    assert all(shlex.split(n["cmd"])[2:4] == ["-C", str(repo)] for n in j4["next"]), j4["next"]


def test_errors():
    """写错名字：退出码 3、带候选；--json 时 stdout 只有一个信封；argparse 的用法错也给信封（退出码 2）"""
    repo, rid = truth()
    for args, code in ((["nope"], "run_not_found"), ([f"{rid}@nosuch"], "phase_not_found"),
                       ([f"{rid}@t=0-999999999999"], "window_out_of_range"), ([f"{rid}/nosuch"], "lane_not_found"),
                       ([rid[:8]], "run_not_found")):
        r = csc("lanes", *args, "--json", cwd=repo)
        j = one_json(r)
        assert r.returncode == EXIT[code] and not j["ok"] and j["error"]["code"] == code, (args, r.returncode, j)
        assert j["error"]["candidates"], j
        r = csc("lanes", *args, cwd=repo)
        assert r.returncode == EXIT[code] and r.stdout == "" and f"[{code}]" in r.stderr and "候选" in r.stderr, r.stderr
    r = csc("lanes", "--json", "--nosuch", cwd=repo)
    j = one_json(r)
    assert r.returncode == 2 and j["error"]["code"] == "usage" and j["cmd"] == "lanes", j
    # 没录时序事件的 run：no_events（退出码 4）
    cs("trace", repo, "--case", "plain", "--no-events", "--", PY, "-m", "fakesvc.work")
    r = csc("lanes", "plain", "--json", cwd=repo)
    assert r.returncode == 4 and one_json(r)["error"]["code"] == "no_events", r.stdout
    # 不在仓库里、也没给 -C：repo_unknown
    r = csc("status", "--json", cwd="/", env={"XDG_CONFIG_HOME": str(repo / "nocfg")})
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "repo_unknown", r.stdout


def test_page_url():
    """页面地址当 REF：问那个端口的 serve（/api/app 回 repo、pid、port）找到仓库；lanes= 当列选择器；不建议重录"""
    repo, rid = truth()
    with served(repo) as get:
        st, app = get("/api/app")
        assert st == 200 and app["repo"] == str(repo) and app["pid"] > 0 and app["port"] == int(get.base.rsplit(":", 1)[1]), app
        url = f"{get.base}/#run={rid}%40work&lanes=*%2FMainThread"
        j = one_json(csc("status", url, "--json", cwd="/"))
        assert j["ok"] and j["data"]["found_by"] == "page" and j["ref"]["text"] == f"{rid}@work/*/MainThread", j
        j = one_json(csc("lanes", url, "--json", cwd="/"))
        assert j["ok"] and all(x["lane"].endswith("/MainThread") for x in j["data"]["lanes"]), j
        assert "trace" not in json.dumps(j["next"]), j["next"]
        r = csc("lanes", get.base + f"/#run={rid}@work/x", cwd="/")
        assert r.returncode == 2, r.stderr


def test_run_id_finds_repo():
    """完整 run id 在主菜单记得的仓库里唯一找到：不在仓库里也能用，下一步带 -C"""
    repo, rid = truth()
    cfg = repo.parent / "cfg"
    (cfg / "codestrata").mkdir(parents=True, exist_ok=True)
    (cfg / "codestrata" / "projects.json").write_text(json.dumps({"projects": [{"path": str(repo)}]}))
    j = one_json(csc("status", rid, "--json", cwd="/", env={"XDG_CONFIG_HOME": str(cfg)}))
    assert j["ok"] and j["data"]["found_by"] == "run" and j["repo"] == str(repo), j
    assert all("-C" in n["cmd"] for n in j["next"]), j["next"]


def test_path():
    """path 收 REF：老写法 path <repo> RUN 照旧打整棵树；给了列只打那几列、默认截到 200 行；--limit 写「给了 N / 共 M」；
    --json 是信封，每节带列别名；接在 head 后面不报 BrokenPipe"""
    repo, rid = truth()
    full = cs("path", repo, f"{rid}@work").stdout
    assert "== " in full and "/MainThread" in full and "给了" not in full, full[:500]
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--json"))
    lanes = [th["lane"] for p in j["data"]["procs"] for th in p["threads"]]
    assert j["ok"] and lanes and all("/" in x for x in lanes), lanes
    main = next(x for x in lanes if x.endswith("/MainThread"))
    j2 = one_json(cs("path", "-C", repo, f"{rid}@work/{main}", "--json"))
    assert [th["lane"] for p in j2["data"]["procs"] for th in p["threads"]] == [main], j2["data"]["procs"]
    # --limit 是每列几行：每一列都有内容，截过的列末尾写还有几行；--depth 藏掉的不算
    r = cs("path", "-C", repo, f"{rid}@work", "--limit", "1")
    secs = [b for b in r.stdout.split("\n== ")[1:]]
    assert len(secs) > 2 and all("+0." in b or "（之前）" in b for b in secs), r.stdout
    assert "…这一列还有 " in r.stdout and "（给了 " in r.stdout and "--limit" in r.stdout, r.stdout
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--depth", "0", "--json"))
    assert all(x["d"] == 0 for p in j["data"]["procs"] for th in p["threads"] for x in th["rows"])
    assert j["more"] is None, j["more"]
    p = subprocess.run(f"{shlex.quote(PY)} -m codestrata path -C {shlex.quote(str(repo))} {rid}@work | head -1",
                       shell=True, capture_output=True, text=True, cwd=HERE.parent)
    assert "BrokenPipe" not in p.stderr and "Traceback" not in p.stderr, p.stderr


def test_runs_json_and_wait():
    """runs ls / show --json：信封，带各阶段的微秒窗口；runs wait 对录完的 run 立刻返回；写错名字退出码 3"""
    repo, rid = truth()
    j = one_json(cs("runs", repo, "ls", "--json"))
    r0 = next(r for r in j["data"]["runs"] if r["id"] == rid)
    assert j["ok"] and [p["name"] for p in r0["phases"]] == ["start", "work"] and r0["end_us"] > 0, r0
    j = one_json(cs("runs", repo, "show", "truth", "--json"))
    assert j["data"]["run"]["id"] == rid and j["data"]["rerun"] and j["data"]["phases"], j["data"].keys()
    r = cs("runs", repo, "wait", "truth")
    assert rid in r.stdout and "ok" in r.stdout, r.stdout
    r = csc("runs", repo, "wait", "nope", "--json", cwd=HERE.parent)
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "run_not_found", r.stdout


def test_trace_json_and_phase_names():
    """trace --json：被录程序的输出和摘要都在 stderr，stdout 只有一个信封；case 脚本写来的阶段名里的怪字符换成 _"""
    repo = fresh()
    script = repo / "case.sh"
    script.write_text(f'echo "a b/c" > "$CODESTRATA_OUT/PHASE"; sleep 0.3; {shlex.quote(PY)} -c '
                      "\"print('child says hi'); from fakesvc import work; work.init_model()\"\n")
    r = csc("trace", repo, "--case", "pj", "--json", "--", "bash", str(script), cwd=HERE.parent)
    j = one_json(r)
    assert r.returncode == 0 and j["ok"] and j["cmd"] == "trace" and "child says hi" in r.stderr, (r.stdout, r.stderr[-500:])
    assert [p["name"] for p in j["data"]["phases"]] == ["start", "a_b_c"], j["data"]["phases"]
    assert j["next"] and j["next"][0]["effect"] == "read"


def test_read_commands_do_not_migrate():
    """给 agent 的读命令真的只读：老格式的 trace-*.json 不迁移，只提示（runs ls 照旧会迁）"""
    repo, rid = truth()
    old = repo / ".codestrata" / "trace-legacy.json"
    old.write_text("{}")
    try:
        j = one_json(cs("status", "-C", repo, "--json"))
        assert any(w["code"] == "legacy_runs" for w in j["warnings"]) and old.exists(), j["warnings"]
        one_json(cs("lanes", "-C", repo, f"{rid}@work", "--json"))
        assert old.exists()
    finally:
        old.unlink()


def test_serve_port_in_use():
    """端口被占：一句人话，不是 traceback"""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        repo, _ = truth()
        r = csc("serve", repo, "--port", s.getsockname()[1], cwd=HERE.parent)
        assert r.returncode == 1 and "用不了" in r.stderr and "Traceback" not in r.stderr, r.stderr
    finally:
        s.close()


def _recording_copy(repo, rid, sleeper):
    """把录好的 run 拷一份成「正在录」的（id 更新、driver 指向一个活着的进程）：runs wait、newer_recording 用"""
    import shutil
    from codestrata.trace import driver
    base = repo / ".codestrata" / "runs"
    nid = "20991231-000000-truth"
    shutil.copytree(base / rid, base / nid)
    rj = base / nid / "run.json"
    run = json.loads(rj.read_text())
    run.update(id=nid, status="recording", driver={"pid": sleeper.pid, "start": driver.proc_start(sleeper.pid)})
    rj.write_text(json.dumps(run))
    return nid


def test_recording_runs():
    """同一个 case 有一次更新的正在录：runs wait <case> 等的是它（超时退出码 4、下一步给更长的 --timeout）；
    status <case> 用录完的那次并警告 newer_recording；lanes 读正在录的报 recording、下一步 runs wait；driver 没了是 interrupted"""
    repo, rid = truth()
    sleeper = subprocess.Popen(["sleep", "60"])
    nid = None
    try:
        nid = _recording_copy(repo, rid, sleeper)
        r = csc("runs", "wait", "truth", "--timeout", "1", "--json", cwd=repo)
        j = one_json(r)
        assert r.returncode == 4 and j["error"]["code"] == "recording" and nid in j["error"]["msg"], j
        assert "--timeout 2" in j["next"][0]["cmd"], j["next"]
        j = one_json(csc("status", "truth", "--json", cwd=repo))
        assert j["data"]["run"]["id"] == rid and any(w["code"] == "newer_recording" and nid in w["msg"] for w in j["warnings"]), j
        r = csc("lanes", nid, "--json", cwd=repo)
        j = one_json(r)
        assert r.returncode == 4 and j["error"]["code"] == "recording" and "runs wait" in j["next"][0]["cmd"], j
        j = one_json(csc("status", nid, "--json", cwd=repo))
        assert j["data"]["run"]["status"] == "recording" and "runs wait" in j["next"][0]["cmd"], j
        sleeper.kill()
        sleeper.wait()
        j = one_json(csc("runs", "wait", "truth", "--json", cwd=repo))
        assert j["data"]["status"] == "interrupted" and "runs merge" in j["next"][0]["cmd"], j
        assert j["next"][0]["effect"] == "write"
    finally:
        sleeper.kill()
        if nid:
            import shutil
            shutil.rmtree(repo / ".codestrata" / "runs" / nid, ignore_errors=True)


def test_repo_lookup():
    """-C 指到仓库的子目录：往上找到仓库；-C 指的目录往上都没有 .codestrata/：status 照样看（还没 scan），别的命令报 repo_unknown，
    候选是主菜单记得的仓库、下一步带着原来的 REF；case 名在别的已知仓库里：run_not_found 的下一步指过去；
    页面地址问不到时，报错里带着 page_unknown 的警告"""
    repo, rid = truth()
    j = one_json(cs("status", "-C", repo / "fakesvc", "--json"))
    assert j["repo"] == str(repo) and j["data"]["found_by"] == "C", j
    empty = repo.parent / "empty"
    empty.mkdir(exist_ok=True)
    cfg = repo.parent / "cfg2"
    (cfg / "codestrata").mkdir(parents=True, exist_ok=True)
    (cfg / "codestrata" / "projects.json").write_text(json.dumps({"projects": [{"path": str(repo)}]}))
    env = {"XDG_CONFIG_HOME": str(cfg)}
    j = one_json(csc("status", "-C", empty, "--json", cwd="/", env=env))
    assert j["ok"] and j["repo"] == str(empty) and j["data"]["index"] is None and j["next"][0]["effect"] == "write", j
    r = csc("lanes", "-C", empty, "truth@work", "--json", cwd="/", env=env)
    j = one_json(r)
    assert r.returncode == 3 and j["error"]["code"] == "repo_unknown" and j["error"]["candidates"] == [str(repo)], j
    assert shlex.split(j["next"][0]["cmd"])[1:] == ["status", "-C", str(repo), "truth@work"], j["next"]
    other = repo.parent / "other"
    (other / ".codestrata").mkdir(parents=True, exist_ok=True)
    r = csc("status", "truth@work", "--json", cwd=other, env=env)
    j = one_json(r)
    assert r.returncode == 3 and j["error"]["code"] == "run_not_found" and str(repo) in j["error"]["msg"], j
    assert shlex.split(j["next"][0]["cmd"])[1:] == ["status", "-C", str(repo), "truth@work"], j["next"]
    r = csc("lanes", "http://127.0.0.1:1/#run=truth@work", "--json", cwd="/", env=env)
    j = one_json(r)
    assert j["error"]["code"] == "repo_unknown" and [w["code"] for w in j["warnings"]] == ["page_unknown"], j
    # 写在子命令前面的 -C、--json（git 式）
    j = one_json(cs("-C", repo, "--json", "status"))
    assert j["ok"] and j["repo"] == str(repo), j


def test_lanes_canonical_in_ref():
    """REF 里的列对着整个 run 核对、规整：大小写不同、写重了的合成一个标准写法；对不上的连 status 都报 lane_not_found"""
    repo, rid = truth()
    lanes = one_json(cs("lanes", "-C", repo, f"{rid}@work", "--json"))["data"]["lanes"]
    main = next(x["lane"] for x in lanes if x["lane"].endswith("/MainThread"))
    j = one_json(cs("status", "-C", repo, f"{rid}@work/{main.upper()},{main}", "--json"))
    assert j["ref"]["lanes"] == [main] and j["ref"]["text"] == f"{rid}@work/{main}", j["ref"]
    r = csc("status", "-C", repo, f"{rid}@work/nosuch9", "--json", cwd=HERE.parent)
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "lane_not_found", r.stdout


def test_old_resolve_shares_grammar():
    """页面和老命令走的 runs.resolve 和命令行认同一套范围写法：阶段 + 秒规整成 t=；越界说清楚、给候选；/api/lanes 也认"""
    from codestrata import runs
    repo, rid = truth()
    run, rd, phase = runs.resolve(repo, f"{rid}@work+0s-0.01s")
    assert phase.startswith("t=") and run["id"] == rid, phase
    # 页面收超出终点的时间段（时间条放长），不像命令行那样报越界；写错的照样报、给候选
    assert runs.resolve(repo, f"{rid}@t=0-999999999999")[2] == "t=0-999999999999"
    try:
        runs.resolve(repo, f"{rid}@nosuch")
        raise AssertionError("写错的阶段应当报错")
    except SystemExit as e:
        assert "没有阶段" in str(e) and f"{rid}@work" in str(e), e
    with served(repo) as get:
        st, la = get(f"/api/lanes?run={rid}@work%2B0s-0.01s")
        assert st == 200 and la["lanes"] is not None, (st, la.get("error"))


def test_phase_name_with_spaces():
    """case 脚本写来的阶段名带空格、斜杠：hook 记计数、driver 记时刻都换成 _，lanes RUN@a_b_c 能读（以前 KeyError）"""
    repo = fresh()
    script = repo / "case.sh"
    script.write_text(f'echo "a b/c" > "$CODESTRATA_OUT/PHASE"; sleep 0.3; {shlex.quote(PY)} -c '
                      "\"from fakesvc import work; work.init_model()\"\n")
    cs("trace", repo, "--case", "sp", "--", "bash", str(script))
    rid = sorted(p.name for p in (repo / ".codestrata" / "runs").iterdir() if p.name.endswith("-sp"))[-1]
    run = json.loads((repo / ".codestrata" / "runs" / rid / "run.json").read_text())
    assert [p["name"] for p in run["phases"]][-1] == "a_b_c" and run["phases"][-1]["t_us"] is not None, run["phases"]
    r = csc("lanes", f"{rid}@a_b_c", "--json", cwd=repo)
    assert r.returncode == 0 and one_json(r)["ok"], r.stdout + r.stderr


def test_json_internal_error_envelope():
    """--json 时意外的异常也只在 stdout 给一个信封（internal，退出码 1），堆栈写到 stderr"""
    import argparse
    import contextlib
    import io

    def boom(a):
        raise ValueError("坏了")
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = out.run("x", boom, argparse.Namespace(json=True))
    j = json.loads(buf.getvalue())
    assert rc == 1 and j["error"]["code"] == "internal" and "坏了" in j["error"]["msg"] and "Traceback" in err.getvalue(), j


def test_runs_text_and_json_agree():
    """runs show 文字和 JSON 是同一份数据：页面地址也认、不建议重录；status 用英文；trace 录失败给 failed_run（退出码 4）"""
    repo, rid = truth()
    url = f"http://127.0.0.1:1/#run={rid}%40work"
    r = csc("runs", "show", "-C", repo, url, cwd=HERE.parent)
    assert r.returncode == 0 and r.stdout.startswith(f"run {rid}") and "录一个" not in r.stdout + r.stderr, r.stdout + r.stderr
    j = one_json(csc("runs", "show", "-C", repo, url, "--json", cwd=HERE.parent))
    assert j["data"]["run"]["id"] == rid and j["data"]["status"] == "ok" and j["ref"]["text"] == f"{rid}@work", j["ref"]
    j = one_json(cs("runs", "ls", "-C", repo, "--json"))
    row = next(x for x in j["data"]["runs"] if x["id"] == rid)
    assert row["status"] == "ok" and row["phases"][0].keys() >= {"name", "t0_us", "t1_us", "n_funcs"}, row
    r = csc("trace", repo, "--case", "bad", "--json", "--", PY, "-c", "pass", cwd=HERE.parent)
    j = one_json(r)
    assert r.returncode == 4 and j["error"]["code"] == "failed_run" and "runs show" in j["next"][0]["cmd"], (r.returncode, j)


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
