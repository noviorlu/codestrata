"""切段（steps.py、segments.py）和命令 segments / steps / links：合成的 span 上测判法，真录的 toy 上测命令。

    python tests/test_segments.py [名字里的词…]
"""
from __future__ import annotations

import json
import subprocess
import sys

from common import HERE, PY, cs, fresh, run_tests, tmpdir  # noqa: E402
from synth import Builder  # noqa: E402

from codestrata import segments, steps  # noqa: E402

# 键：0 轮头 schedule、1 has_requests（一轮调两次）、2 execute、3 forward（execute 里）、4 收尾 output、
#     5 poll、6 work、7 请求（阶段函数）、8 多调的 extra、9 合成一行的叶子
K = ["app/eng.py:1", "app/eng.py:5", "app/eng.py:9", "app/model.py:3", "app/eng.py:20",
     "app/io.py:2", "app/w.py:1", "app/omni.py:5", "app/extra.py:1", "app/io.py:9"]
NODE = {k: k.replace(":", "#f") for k in K} | {"app/omni.py:5": "app/omni.py#Omni.generate"}
REQ, A, B = 400, 100, 200


def label(k: str) -> str:
    return NODE.get(k, k)


def stage(b: Builder, pid: int, name: str, busy: range, long: int | None = None, start: int = 0):
    """一个 stage 进程的主线程：30 轮，每 1000 µs 一轮。busy 里的轮多调一次 extra、交出一次数据（给持有请求的进程）"""
    t = b.thread(pid, 1, "MainThread", start=start)
    b.procs[pid]["title"] = f"VLLM::StageProc_{name}_replica0_DP0"
    outs = []
    for k in range(30):
        t0 = 1000 + k * 1000 + (5000 if long is not None and k > long else 0)     # 超长的那一轮：到下一轮隔了 6 ms
        t.call(t0, 2, 1)
        t.call(t0 + 5, 2, 1)
        h = t.call(t0 + 10, 50, 0)
        e = t.call(t0 + 20, 20, 2, parent=h)
        t.call(t0 + 25, 10, 3, parent=e)
        if k in busy:
            x = t.call(t0 + 60, 5, 8, parent=h)
            outs.append((pid, 1, x, t0 + 62))
        t.call(t0 + 100, 5, 4)
    return outs


def scenario(d, old: bool = False):
    b = Builder(K)
    r = b.thread(REQ, 1, "MainThread", proc="python end2end.py")
    req = r.call(500, 39000, 7)
    for o in stage(b, A, "stage0", busy=range(10, 20), long=12):
        b.handoff("zmq", o, (REQ, 1, req, o[3] + 1))
    b.handoff("zmq", (REQ, 1, req, 11_040), (A, 1, -1, 11_050))          # 交给 stage0（第 11 轮里）：它开始前有交接，没有缺口
    stage(b, B, "stage1", busy=range(24, 29))                             # stage1 开始前没录到交给它的：缺口
                                                                          # （多调的只在 5 / 30 轮里：不到两成，不算常规）
    p = b.thread(A, 2, "recv")                                            # 只在轮询
    for k in range(40):
        p.call(500 + k * 900, 3, 5)
    f = b.thread(A, 3, "fold")                                            # 只有合成一行的连续调用：不当轮头
    f.call(600, 30000, 9, rep=500)
    for tid in range(10, 15):                                             # 5 条同名线程，每条干一件
        b.thread(A, tid, f"worker-{tid}").call(2000 + tid, 100, 6)
    for pid, st in ((300, 50), (301, 20)):                                # 名字一样的两个进程：按启动先后编号
        b.thread(pid, 1, "MainThread", proc="python -m app.helper", start=st).call(100, 5, 6)
    b.truncated = [B]
    run = {"rec": {"phase_at": [{"name": "serving", "file": "app/omni.py", "qualname": "Omni.generate", "line": 5}]}}
    return b.write(d, phases=[["start", 0], ["serving", 400]], old=old), run


def test_rounds_and_kinds():
    """轮头按票选（一轮调两次的 has_requests 不当轮头）；超长的轮不算空转；只在轮询的列是 poll；合成一行的叶子不当轮头；
    同名的 5 条线程是 threads；同名进程按启动先后编号"""
    rd, _ = scenario(tmpdir("cs-seg-"))
    S = segments.analyse(rd, 0, 40_000)
    ln = {x["alias"]: x for x in S["lanes"].values()}
    st0 = ln["stage0/MainThread"]
    assert S["ix"]["keys"][st0["loop"]["head"]] == "app/eng.py:1" and len(st0["rounds"]) == 30, st0["loop"]["head"]
    r12 = st0["rounds"][12]
    assert r12["long"] and not r12["spin"], r12
    assert [x["k"] for x in st0["rounds"] if not x["spin"]] == list(range(11, 21)), [x["k"] for x in st0["rounds"] if not x["spin"]]
    assert ln["stage0/recv"]["kind"] == "poll", ln["stage0/recv"]["kind"]
    assert ln["stage0/fold"]["loop"] is None and ln["stage0/fold"]["kind"] == "few"
    assert ln["stage0/worker"]["kind"] == "threads" and len(ln["stage0/worker"]["tids"]) == 5
    assert {"app.helper-1/MainThread", "app.helper-2/MainThread"} <= set(ln), sorted(ln)
    assert S["procs"][301] == "app.helper-1" and S["procs"][300] == "app.helper-2", S["procs"]


def test_stage_segments():
    """持有请求的进程不出段；每个进程取主循环最大的忙段；开始前没录到交给它的数据 → 缺口；截断的进程标出来；
    交接按（通道, 起列, 终列）合成组；只在轮询的是背景"""
    rd, run = scenario(tmpdir("cs-seg-"))
    S = segments.analyse(rd, 0, 40_000)
    reqs = segments.requests(S, run, "serving", 400, 40_000, label)
    assert [(q["lane"], q["t0_us"]) for q in reqs] == [("end2end/MainThread", 500)], reqs
    segs = segments.stage_segments(S, 0, 40_000, {q["pid"] for q in reqs})
    assert [(s["id"], s["proc"], s["rounds"]["first"], s["rounds"]["last"]) for s in segs] == \
        [("S1", "stage0", 11, 20), ("S2", "stage1", 25, 29)], [(s["id"], s["proc"], s["rounds"]) for s in segs]
    assert segs[0]["gaps"] == [] and segs[1]["gaps"] and segs[1]["gaps"][0]["last_us"] is None, [s["gaps"] for s in segs]
    assert segs[1]["truncated"] and not segs[0]["truncated"]
    assert segs[0]["rounds"]["out"] == 10 and segs[0]["main"] == "stage0/MainThread"
    groups, intra = segments.handoff_groups(S, 0, 40_000)
    assert [(g["id"], g["n"]) for g in groups] == [("l:handoff|zmq|end2end/MainThread|stage0/MainThread", 1),
                                                   ("l:handoff|zmq|stage0/MainThread|end2end/MainThread", 10)], groups
    assert intra == 0
    assert segments.background(S, segs) == ["stage0/recv"]
    # --all：持有请求的进程也出段（它没有主循环：还是两段）
    assert len(segments.stage_segments(S, 0, 40_000, set())) == 2


def test_head_override_and_params():
    """--head 指定轮头；阈值改了，输出里的 basis 跟着变"""
    rd, _ = scenario(tmpdir("cs-seg-"))
    S = segments.analyse(rd, 0, 40_000, head={f"{A}:MainThread": {1}})
    st0 = S["lanes"][f"{A}:MainThread"]
    assert S["ix"]["keys"][st0["loop"]["head"]] == "app/eng.py:5" and len(st0["rounds"]) == 60
    p = steps.Params(long=1000)
    S = segments.analyse(rd, 0, 40_000, p)
    assert not S["lanes"][f"{A}:MainThread"]["rounds"][12]["long"] and p.basis()["long"] == 1000


def test_self_times():
    """自己的时间：时长减去直接调的仓库函数；挂起过的 async 行跳过并标出来；没返回的按到段尾算"""
    b = Builder(K)
    t = b.thread(1, 1, "MainThread")
    h = t.call(0, 100, 0)
    t.call(10, 30, 2, parent=h)
    t.call(50, 20, 3, parent=h, susp=1)
    t.call(200, -1, 6)
    lr = steps.lane_rows(b.rows[1], {1})
    own, idle, skipped = steps.self_times(lr, 1, 0, 300)
    assert own[0] == 50 and own[2] == 30 and own[6] == 100 and 3 not in own and skipped, own   # h：100 - 30 - 20
    assert idle == 300 - 100 - 100, idle


def test_old_format_refused():
    """2026-10-01 之前的 run（没录交接、span 没有父亲）：认得出来（命令行拒绝并说明）"""
    rd, _ = scenario(tmpdir("cs-seg-"), old=True)
    assert segments.old_format(rd)
    rd2, _ = scenario(tmpdir("cs-seg-"))
    assert not segments.old_format(rd2)


# ---------------------------------------------------------------- 命令（真录的 toy）

_TRUTH: list = []


def truth():
    if not _TRUTH:
        repo = fresh()
        cs("trace", repo, "--case", "truth", "--phase", "work=fakesvc.truth:s_threads", "--", PY, "-m", "fakesvc.truth")
        rid = sorted(p.name for p in (repo / ".codestrata" / "runs").iterdir() if p.name.endswith("-truth"))[-1]
        _TRUTH.append((repo, rid))
    return _TRUTH[0]


def one_json(r) -> dict:
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    assert len(lines) == 1, r.stdout + r.stderr
    return json.loads(lines[0])


def test_commands_on_toy():
    """segments / steps / links 在真录的 run 上：信封、algo、basis；steps 要一列（写成进程报 ambiguous_lane、没写报 usage）；
    --with 写错报 item_not_found 带候选；links 的组 id 是 l:种类|通道|起列|终列"""
    repo, rid = truth()
    j = one_json(cs("segments", "-C", repo, f"{rid}@work", "--json"))
    assert j["ok"] and j["algo"] == steps.ALGO and "min_calls" in j["data"]["basis"], j
    assert j["data"]["requests"] and j["data"]["requests"][0]["fn"].endswith("#s_threads"), j["data"]["requests"]
    lanes = one_json(cs("lanes", "-C", repo, f"{rid}@work", "--json"))["data"]["lanes"]
    main = next(x for x in lanes if x["lane"].endswith("/MainThread"))
    r = subprocess.run([PY, "-m", "codestrata", "steps", "-C", str(repo), f"{rid}@work", "--json"], capture_output=True, text=True,
                       cwd=HERE.parent)
    assert r.returncode == 2 and one_json(r)["error"]["code"] == "usage", r.stdout
    r = subprocess.run([PY, "-m", "codestrata", "steps", "-C", str(repo), f"{rid}@work/{main['proc']}", "--json"],
                       capture_output=True, text=True, cwd=HERE.parent)
    j = one_json(r)
    assert j["error"]["code"] in ("ambiguous_lane", "no_loop"), j
    r = subprocess.run([PY, "-m", "codestrata", "steps", "-C", str(repo), f"{rid}@work/{main['lane']}", "--head", "nosuchfn", "--json"],
                       capture_output=True, text=True, cwd=HERE.parent)
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "item_not_found", r.stdout
    j = one_json(cs("links", "-C", repo, f"{rid}@work", "--kind", "all", "--json"))
    assert j["ok"] and all(x["id"].startswith(f"l:{x['kind']}|{x['via']}|") for x in j["data"]["links"]), j["data"]["links"][:2]
    assert any(x["kind"] == "spawn" for x in j["data"]["links"]), [x["id"] for x in j["data"]["links"]]


def test_old_run_refused_by_commands():
    """老 run：segments / steps 报 no_handoffs（退出码 4），下一步给 lanes 和 path（还能看原始的调用）"""
    repo, rid = truth()
    d = tmpdir("cs-seg-")
    rd, _ = scenario(d, old=True)
    (d / ".codestrata" / "index.json").write_text((repo / ".codestrata" / "index.json").read_text())
    for cmd in (["segments", "synth@serving"], ["steps", "synth@serving/stage0/MainThread"]):
        r = subprocess.run([PY, "-m", "codestrata", *cmd, "-C", str(d), "--json"], capture_output=True, text=True, cwd=HERE.parent)
        j = one_json(r)
        assert r.returncode == 4 and j["error"]["code"] == "no_handoffs", (cmd, j)
        assert [n["cmd"].split()[1] for n in j["next"]] == ["lanes", "path"], j["next"]


def test_finder_match():
    """find 的匹配：完全一样 > 前缀 > 子串、不分大小写、* 通配、按种类和目录过滤；类、文件、目录也找得到"""
    from codestrata import finder
    idx = {"symbols": {"a/x.py#Foo": {"n": "Foo", "k": "class", "f": "a/x.py", "l": 1},
                       "a/x.py#Foo.run": {"n": "Foo.run", "k": "method", "f": "a/x.py", "l": 3},
                       "a/y.py#run_all": {"n": "run_all", "k": "func", "f": "a/y.py", "l": 1},
                       "b/z.py#rerun": {"n": "rerun", "k": "func", "f": "b/z.py", "l": 1}},
           "files": {"a/x.py": "a", "a/y.py": "a", "b/z.py": "b"}, "dirs": {"a": {}, "b": {}}}
    names = [x["name"] for x in finder.match(idx, "run", kind="fn")]
    assert names == ["Foo.run", "run_all", "rerun"], names               # 完全一样（短名）> 前缀 > 子串
    assert [x["key"] for x in finder.match(idx, "FOO", kind="class")] == ["a/x.py#Foo"]
    assert {x["name"] for x in finder.match(idx, "*run", kind="fn")} == {"Foo.run", "rerun"}
    assert [x["name"] for x in finder.match(idx, "run", kind="fn", under="b")] == ["rerun"]
    assert [x["key"] for x in finder.match(idx, "x.py", kind="file")] == ["a/x.py"]
    assert [x["key"] for x in finder.match(idx, "b", kind="dir")] == ["b/"]
    per_node = {"a/x.py#Foo.run": {"L1": [3, 10, 20]}, "a/y.py#run_all": {"L1": [1, 5, 5], "L2": [2, 7, 9]}}
    assert finder.hits_of({"kind": "class", "key": "a/x.py#Foo"}, per_node) == {"L1": [3, 10, 20]}
    assert finder.hits_of({"kind": "dir", "key": "a/"}, per_node) == {"L1": [4, 5, 20], "L2": [2, 7, 9]}


def test_find_explain_path_on_toy():
    """find 给次数和列；explain 讲一条交接（两头的原文、调用链、scan 的说法）和一个函数（谁调它）；编号要视图（need_view）、
    只给 REF 是用法错；path --time 列自己的时间、--unseen 只列看不出的"""
    repo, rid = truth()
    j = one_json(cs("find", "callee", f"{rid}@work", "-C", repo, "--kind", "file", "--json"))
    assert j["data"]["items"] and j["data"]["items"][0]["key"] == "fakesvc/callee.py" and j["data"]["items"][0]["n"] > 0, j["data"]
    links = one_json(cs("links", "-C", repo, f"{rid}@work", "--json"))["data"]["links"]
    assert links, "truth 的 work 阶段里有队列交接"
    j = one_json(cs("explain", links[0]["id"], f"{rid}@work", "-C", repo, "--json"))
    d = j["data"]
    assert j["ok"] and d["n"] >= 1 and d["from"]["lane"] == links[0]["from"] and "scan" in d, d
    assert d["from"]["code"]["text"] and d["from"]["chain"], d["from"]
    fn = one_json(cs("find", "slow", f"{rid}@work", "-C", repo, "--kind", "fn", "--json"))["data"]["items"][0]["key"]
    d = one_json(cs("explain", fn, f"{rid}@work", "-C", repo, "--json"))["data"]
    assert d["item"] == fn and d["lanes"] and d["callers"] and d["first"]["chain"][-1]["fn"] == fn, d
    assert d["def"]["signature"].startswith("def slow"), d["def"]
    for args, code in ((["explain", "24", f"{rid}@work"], "need_view"), (["explain", f"{rid}@work"], "usage")):
        r = subprocess.run([PY, "-m", "codestrata", *args, "-C", str(repo), "--json"], capture_output=True, text=True, cwd=HERE.parent)
        assert one_json(r)["error"]["code"] == code, (args, r.stdout)
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--time", "--json"))
    assert j["data"]["self_time"] and j["data"]["self_time"][0]["us"] >= j["data"]["self_time"][-1]["us"], j["data"]["self_time"]
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--unseen", "--json"))
    assert "unseen" in j["data"] and all(x["n"] >= 0 for x in j["data"]["unseen"]), j["data"].keys()


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
