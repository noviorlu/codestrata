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
    assert a == {1: "end2end", 2: "stage0", 3: "stage1", 4: "stage2", 5: "python-5", 6: "python-6", 7: "cpuinfo"}, a
    rep = {1: "X_stage0_replica0_DP0", 2: "X_stage1_replica0_DP0", 3: "X_stage1_replica1_DP0"}
    assert laneid.proc_aliases(rep) == {1: "stage0", 2: "stage1_replica0", 3: "stage1_replica1"}
    assert laneid.proc_aliases({9: "-m my.mod"}) == {9: "-m_my.mod"}


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
    assert ref._split_range(run, "serve-2/stage1") == ("serve-2", ["stage1"])
    assert ref._split_range(run, "serve+0.5s-1s/a,b") == ("serve+0.5s-1s", ["a", "b"])
    assert ref._split_range(run, "t=1-2") == ("t=1-2", None)
    end = 5_000_000
    assert ref._range(run, "serve-2", end) == ("serve-2", [(3_000_000, 5_000_000)])
    assert ref._range(run, "t=10-20", end) == ("t=10-20", [(10, 20)])
    assert ref._range(run, "t=1.5s-2.25s", end) == ("t=1500000-2250000", [(1_500_000, 2_250_000)])
    assert ref._range(run, "serve+0.5s-1.5s", end) == ("t=1500000-2500000", [(1_500_000, 2_500_000)])
    for rng, code in (("t=0-6000000", "window_out_of_range"), ("t=5-3", "bad_window"), ("t=1-2,3-4", "bad_window"),
                      ("servng", "phase_not_found"), ("serve+1s-3s", "window_out_of_range"), ("t=x", "bad_window")):
        try:
            ref._range(run, rng, end)
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
    assert shlex.split(cmd) == ["codestrata", "runs", str(HERE / "a dir"), "merge", "R"], cmd
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


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
