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
    """一个 stage 进程的主线程：30 轮，每 1000 µs 一轮。busy 里的轮多调一次 extra（多花 300 µs）、交出一次数据（给持有请求的进程）"""
    t = b.thread(pid, 1, "MainThread", start=start)
    b.procs[pid]["title"] = f"VLLM::StageProc_{name}_replica0_DP0"
    outs = []
    for k in range(30):
        t0 = 1000 + k * 1000 + (5000 if long is not None and k > long else 0)     # 超长的那一轮：到下一轮隔了 6 ms
        t.call(t0, 2, 1)
        t.call(t0 + 5, 2, 1)
        h = t.call(t0 + 10, 350 if k in busy else 50, 0)
        e = t.call(t0 + 20, 20, 2, parent=h)
        t.call(t0 + 25, 10, 3, parent=e)
        if k in busy:
            x = t.call(t0 + 50, 300, 8, parent=h)
            outs.append((pid, 1, x, t0 + 340))
        t.call(t0 + 400, 5, 4)
    return outs


def scenario(d, old: bool = False):
    b = Builder(K)
    r = b.thread(REQ, 1, "MainThread", proc="python end2end.py")
    req = r.call(500, 39000, 7)
    for o in stage(b, A, "stage0", busy=range(10, 20), long=12):
        b.handoff("zmq", o, (REQ, 1, req, o[3] + 1))
    b.handoff("zmq", (REQ, 1, req, 11_040), (A, 1, -1, 11_050))          # 交给 stage0（第 11 轮里）：它开始前有交接，没有缺口
    stage(b, B, "stage1", busy=range(24, 29))                             # stage1 开始前没录到交给它的：缺口
                                                                          # （多调 extra 的轮在仓库函数里多花了时间：不是便宜的那类，不算常规）
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


def test_multi_slice_calls():
    """几片的时间段（t=a-b,c-d）：每对调用的次数正好是各片加起来（合成一行的连续调用按片摊），时间段的计数（window_counts）也是"""
    import json as _json
    from codestrata import seq
    rd, _ = scenario(tmpdir("cs-seg-"))
    run = _json.loads((rd / "run.json").read_text())
    one, two, both = (seq.phase_calls(rd, run, w) for w in ("t=1000-9000", "t=20000-31000", "t=1000-9000,20000-31000"))
    assert seq.window_segments(run, rd, "t=20000-31000,1000-9000")[0] == [(1000, 9000), (20000, 31000)]
    keys = set(one["calls"]) | set(two["calls"])
    assert keys == set(both["calls"]) and all(
        both["calls"][k][2] == (one["calls"].get(k) or [0, 0, 0])[2] + (two["calls"].get(k) or [0, 0, 0])[2] for k in keys), keys
    assert both["window"] == [1000, 31000] and both["span_us"] == 8000 + 11000, (both["window"], both["span_us"])
    c1, c2, c12 = (seq.window_counts(rd, run, w)["funcs"] for w in ("t=1000-9000", "t=20000-31000", "t=1000-9000,20000-31000"))
    assert c12 == {k: c1.get(k, 0) + c2.get(k, 0) for k in set(c1) | set(c2)}, (c12, c1, c2)


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
    """持有请求的进程不出段；每块忙段一段；开始前没录到交给它的数据 → 缺口；截断的进程标出来；
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
    """2026-10-01 之前的 run（时序事件只记了跨文件的调用、没录交接；或者没有调用行）：runs.too_old 认得出来"""
    from codestrata import runs
    rd, run = scenario(tmpdir("cs-seg-"), old=True)
    assert runs.too_old(json.loads((rd / "run.json").read_text()))
    rd2, _ = scenario(tmpdir("cs-seg-"))
    assert not runs.too_old(json.loads((rd2 / "run.json").read_text()))
    assert runs.too_old({"schema": 2}) and not runs.too_old({"schema": 3})


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
    """status REF 在真录的 run 上列出这段时间里的列，页面默认收起的列标出来；links 只列交接，组 id 是 l:handoff|通道|起列|终列"""
    repo, rid = truth()
    ld = one_json(cs("status", "-C", repo, f"{rid}@work", "--json"))["data"]
    lanes = ld["lanes"]
    # 页面默认收起的列也标出来（和页面同一份）：stdlib-put 只跑仓库外的代码、bg-loop 只在一两个文件里转
    pf = {x["lane"]: x["page_folded"] for x in lanes if x["page_folded"]}
    assert "仓库外" in pf.get("truth-1/stdlib-put", "") and "文件" in pf.get("truth-4/bg-loop", "") and "truth-1/MainThread" not in pf, pf
    assert ld["page_default"] == {"shown": len(lanes) - len(pf), "total": len(lanes)}, ld["page_default"]
    assert "页面默认只看" in cs("status", "-C", repo, f"{rid}@work").stdout
    j = one_json(cs("links", "-C", repo, f"{rid}@work", "--json"))
    assert j["ok"] and j["data"]["links"] and all(x["id"].startswith(f"l:handoff|{x['via']}|") for x in j["data"]["links"]), j["data"]["links"][:2]
    t = cs("links", "-C", repo, f"{rid}@work").stdout          # 文字：每组下一行写两头的函数（放 / 取……）
    assert "放 " in t or "发 " in t or "写 " in t, t
    for gone in (["segments"], ["steps"], ["find", "x"], ["guide"], ["lanes"]):
        r = subprocess.run([PY, "-m", "codestrata", *gone, "--json"], capture_output=True, text=True, cwd=HERE.parent)
        assert r.returncode == 2, (gone, r.stdout)
def test_follow_on_toy():
    """links --follow：put_job 里放进队列（录到的，就在这次调用里）→ 另一条线程取到；段的 REF 带着经过的列；--link 不配 --follow 报 usage；
    --link 两边次数不等报 link_mismatch（退出码 4）"""
    repo, rid = truth()
    j = one_json(cs("links", "-C", repo, rid, "--follow", "put_job#1", "--json"))
    ch = j["data"]["chain"]
    assert j["ok"] and ch["start"]["fn"].endswith("#put_job") and "@t=" in ch["start"]["stable"], j
    h = ch["hops"][0]
    assert (h["kind"], h["via"], h["stay"]) == ("recorded", "queue", "ancestor") and h["from"]["fn"].endswith("#put_job"), h
    seg = ch["segment"]
    assert seg["kind"] == "chain" and seg["ref"].startswith(f"{rid}@t=") and seg["ref"].endswith("/" + ",".join(seg["lanes"])), seg
    r = subprocess.run([PY, "-m", "codestrata", "links", "-C", str(repo), rid, "--link", "a/b:f => c/d:g", "--json"],
                       capture_output=True, text=True, cwd=HERE.parent)
    assert r.returncode == 2 and one_json(r)["error"]["code"] == "usage", r.stdout
    a, b = h["from"]["lane"], h["to"]["lane"]
    r = subprocess.run([PY, "-m", "codestrata", "links", "-C", str(repo), rid, "--follow", "put_job#1", "--link",
                        f"{a}:put_job => {b}:{h['to']['fn'].partition('#')[2]}", "--json"], capture_output=True, text=True, cwd=HERE.parent)
    j = one_json(r)
    assert r.returncode == 4 and j["error"]["code"] == "link_mismatch" and "次数不等" in j["error"]["msg"], j    # put_job 调了几次，取只有一次


def test_chain_for_page():
    """页面高亮的链（chainview.for_page → lanes.build 的 chain）：装着链上那次交接的连线带 chain [0]；候选里拼好的 --link 那一跳多连一条
    via link、inferred 的线，时间顺序不给它编号；view set --chain 原样写进地址；写错的链给 error、分列照画"""
    from codestrata import chainview, laneorder, lanes as _lanes, runs as _runs
    from codestrata.ui import load as _load
    repo, rid = truth()
    fol = one_json(cs("links", "-C", repo, rid, "--follow", "put_job#1", "--json"))["data"]["chain"]
    cand = fol["stop"]["candidates"]["link"]
    key = chainview.key(None, fol["start"]["stable"], [cand])
    idx = _load.load_index(repo)
    run, rd, _ = _runs.resolve(repo, rid)
    hot, _ = _runs.load_run(repo, idx, run, rd, None)
    info, marks = chainview.for_page(idx, rd, run, hot, key)
    assert info["error"] is None and [h["kind"] for h in info["hops"]] == ["recorded", "link"], info
    L = _lanes.build(idx, rd, run, None, hot, None, chain=marks)
    rec = [k for k in L["links"] if k.get("chain") == [0]]
    inf = [k for k in L["links"] if k.get("inferred")]
    assert len(rec) == 1 and rec[0]["via"] == "queue", [(k["via"], k.get("chain")) for k in L["links"] if k.get("chain")]
    assert len(inf) == 1 and inf[0]["via"] == "link" and inf[0]["chain"] == [1], inf
    aliases = _lanes.run_aliases(rd)
    assert not any("|link|" in x for x in laneorder.rank(L, aliases)["ids"]), "推出来的那条不编号"
    bad, none = chainview.for_page(idx, rd, run, hot, "~nosuch#1")
    assert bad["error"] and none is None, bad
    j = one_json(cs("view", "url", "-C", repo, rid, "--chain", key, "--json"))
    assert "chain=" in j["data"]["url"] and j["ok"], j
    r = subprocess.run([PY, "-m", "codestrata", "view", "url", "-C", str(repo), rid, "--chain", "~nosuch#1", "--json"],
                       capture_output=True, text=True, cwd=HERE.parent)
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "item_not_found" and "走不出来" in one_json(r)["error"]["msg"], r.stdout


def test_slices_on_toy():
    """几片的 REF（t=a-b,c-d）：path --time 的「这段」是各片加起来；links --follow 按整段走（起点按整段数、给 spanned）"""
    repo, rid = truth()
    ph = one_json(cs("status", "-C", repo, rid, "--json"))["data"]["phases"]
    end = max(x["t1_us"] for x in ph)
    two = f"{rid}@t=0-{end // 3},{2 * end // 3}-{end}"
    j = one_json(cs("links", "-C", repo, two, "--json"))
    assert j["ok"], j
    r = cs("path", "-C", repo, two, "--time")
    assert "2 片加起来" in r.stdout, r.stdout[:400]
    j = one_json(cs("links", "-C", repo, two, "--follow", "put_job#1", "--json"))
    assert j["ok"] and any(w["code"] == "spanned" for w in j["warnings"]) and j["data"]["chain"]["hops"], j
def test_old_run_refused_by_commands():
    """老 run：读命令报 old_run（退出码 4），说请重录；runs show 照样能看它是什么"""
    repo, rid = truth()
    d = tmpdir("cs-seg-")
    rd, _ = scenario(d, old=True)
    (d / ".codestrata" / "index.json").write_text((repo / ".codestrata" / "index.json").read_text())
    for cmd in (["status", "synth@serving"], ["links", "synth@serving"], ["path", "synth@serving"]):
        r = subprocess.run([PY, "-m", "codestrata", *cmd, "-C", str(d), "--json"], capture_output=True, text=True, cwd=HERE.parent)
        j = one_json(r)
        assert r.returncode == 4 and j["error"]["code"] == "old_run", (cmd, j)
        assert "重录" in j["error"]["msg"], j
    r = subprocess.run([PY, "-m", "codestrata", "runs", "show", "synth", "-C", str(d)], capture_output=True, text=True, cwd=HERE.parent)
    assert r.returncode == 0, r.stderr


def test_finder_hits():
    """一个东西在各列的次数：类合它的方法，目录合里面的函数（页面的标记、view --focus 用）"""
    from codestrata import finder
    per_node = {"a/x.py#Foo.run": {"L1": [3, 10, 20]}, "a/y.py#run_all": {"L1": [1, 5, 5], "L2": [2, 7, 9]}}
    assert finder.hits_of({"kind": "class", "key": "a/x.py#Foo"}, per_node) == {"L1": [3, 10, 20]}
    assert finder.hits_of({"kind": "dir", "key": "a/"}, per_node) == {"L1": [4, 5, 20], "L2": [2, 7, 9]}
def test_explain_path_on_toy():
    """explain 讲一个函数（定义、谁调它、它调谁）；写错名字报 item_not_found；path --time 列自己的时间、--unseen 只列看不出的"""
    repo, rid = truth()
    d = one_json(cs("explain", "slow", f"{rid}@work", "-C", repo, "--json"))["data"]
    assert d["item"].endswith("#slow") and d["lanes"] and d["callers"], d
    assert d["def"]["signature"].startswith("def slow"), d["def"]
    assert "谁调它" in cs("explain", "slow", f"{rid}@work", "-C", repo).stdout
    r = subprocess.run([PY, "-m", "codestrata", "explain", "nosuchfn", f"{rid}@work", "-C", str(repo), "--json"],
                       capture_output=True, text=True, cwd=HERE.parent)
    assert r.returncode == 3 and one_json(r)["error"]["code"] == "item_not_found", r.stdout
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--time", "--json"))
    assert j["data"]["self_time"] and j["data"]["self_time"][0]["us"] >= j["data"]["self_time"][-1]["us"], j["data"]["self_time"]
    j = one_json(cs("path", "-C", repo, f"{rid}@work", "--unseen", "--json"))
    assert "unseen" in j["data"] and all(x["n"] >= 0 for x in j["data"]["unseen"]), j["data"].keys()
def test_laneorder():
    """时间顺序的编号和视图无关：每列里两头都在这一列的边、交接连线都编；同一时刻的按稳定写法排（和列表下标无关）"""
    from codestrata import laneorder
    L = {"window": [0, 100],
         "lanes": [{"id": "1:Main", "pid": 1, "nodes": {"a": {}, "b": {}}, "edges": [
                       {"a": "a", "b": "b", "n": 2, "only": 0, "first": 10, "last": 20},
                       {"a": "b", "b": "a", "n": 1, "only": 1, "first": 10, "last": 10}]},
                   {"id": "1:w", "pid": 1, "nodes": {"c": {}}, "edges": []},
                   {"id": "2:Main", "pid": 2, "nodes": {"a": {}, "d": {}}, "edges": [
                       {"a": "a", "b": "d", "n": 1, "only": 0, "first": 5, "last": 5},
                       {"a": "a", "b": "x", "n": 1, "only": 0, "first": 1, "last": 1}]}],      # x 不在这一列：不画、不编
         "links": [{"kind": "handoff", "via": "zmq", "from": {"lane": "1:Main", "node": "a"}, "to": {"lane": "2:Main", "node": "a"},
                    "first": 30, "last": 30},
                   {"kind": "handoff", "via": "queue", "from": {"lane": "1:Main", "node": "a"}, "to": {"lane": "1:w", "node": "c"},
                    "first": 40, "last": 40},
                   {"kind": "spawn", "via": "thread", "from": {"lane": "1:Main"}, "to": {"lane": "1:w"}, "first": 2, "last": 2},
                   {"kind": "handoff", "via": "zmq", "from": {"lane": "2:Main"}, "to": {"lane": "1:Main"}, "first": 500, "last": 500}]}
    al = {"1:Main": "p1/Main", "1:w": "p1/w", "2:Main": "p2/Main"}
    o = laneorder.rank(L, al)
    assert [o["keys"][k] for k in ("e:2:Main|a|d", "e:1:Main|b|a", "e:1:Main|a|b", "l:0", "l:1")] == [0, 1, 2, 3, 4], o
    assert o["n"] == 5 and o["ids"][1] == "e:p1/Main|b|a", o["ids"]          # 同一时刻 10：先比最后一次，再比稳定写法


def test_view_url():
    """view url 拼出的地址解析回来是同一个视图（--focus 展开到它的文件、标出、选中）"""
    from codestrata import ref as R, viewspec
    repo, rid = truth()
    j = one_json(cs("view", "url", f"{rid}@work", "-C", repo, "--focus", "slow", "--order", "on", "--page", "1", "--json"))
    url = j["data"]["url"]
    assert url.startswith("http://127.0.0.1:1/#run=") and "@work" in url and "%3D" not in url, url
    p = R.parse(url)
    v = viewspec.from_keys(p.run + "@" + p.rest, p.view)
    assert v.order and v.mark == ["fakesvc/callee.py#slow"] and v.sel.startswith("n:"), v    # toy 小，默认切面已经看得到它：不用展开
    assert viewspec.fragment(v) == url.split("#", 1)[1], (viewspec.fragment(v), url)
def test_procinfo_and_default_lanes():
    """进程头上的一句（procinfo）：只有它跑的文件在前、占比太低 / 单进程不写、几段写段数、持有请求的写请求；
    默认收起的列（lanedefault 的一句话规则）：只跑仓库外的、线程池、只在一两个文件里转的收，主线程不收；
    toy 上 serve 给 procinfo、default_lanes"""
    from codestrata import lanedefault, procinfo, segments
    seg = lambda pid, a, b, n, own, calls, alone=False: {"pid": pid, "id": "S", "main": f"p{pid}/MainThread", "slices_us": [[a, b]],
                                                         "rounds": {"n": n}, "evidence": {"own_files": own, "calls": calls, "alone": alone}}
    S = {"segs": [seg(1, 1_100_000, 1_600_000, 29, [["m/llm.py", 57]], 3000), seg(2, 1_600_000, 4_100_000, 250, [["m/tts.py", 5]], 100),
                  seg(3, 2_000_000, 2_500_000, 3, [["m/w.py", 500]], 600), seg(3, 3_000_000, 3_500_000, 4, [], 600),
                  seg(4, 1_000_000, 2_000_000, 9, [["m/x.py", 900]], 900, alone=True)],
         "reqs": [{"pid": 9, "fn": "e.py#Omni.generate", "t0_us": 900_000, "t1_us": 5_500_000}]}
    P = procinfo.summary(S, 1_000_000)
    assert P[1]["parts"] == ["llm.py", "+0.10→+0.60 s", "29 轮"] and "m/llm.py（57 次调用）" in P[1]["title"], P[1]
    assert P[2]["parts"] == ["+0.60→+3.10 s", "250 轮"], "只调了 5 次的不写"
    assert P[3]["parts"] == ["w.py", "+1.00→+2.50 s", "7 轮", "2 段"], P[3]
    assert P[4]["parts"][0] == "+0.00→+1.00 s", "单进程（没有别的进程可比）不写文件"
    assert P[9]["parts"] == ["请求 Omni.generate", "−0.10→+4.50 s"], P[9]
    assert procinfo.summary(None, 0) == {} and procinfo.summary(dict(S, whole=True), 1_000_000) == {}, "整个 run 不写"
    runp = {"phases": [{"name": "start"}, {"name": "serving"}]}
    assert segments.whole_run(runp, 0, 9_000, 9_000) and not segments.whole_run(runp, 5, 9_000, 9_000)
    assert not segments.whole_run({"phases": [{"name": "work"}]}, 0, 9_000, 9_000), "没有 serving 的 run：整个 run 就是要看的"
    ln = lambda x, calls=100, files=5, thr=1, ext=False, th="w": {"id": x, "pid": 1, "thread": th, "n_threads": thr, "external": ext,
                                                                  "nodes": {"n": {"n": calls}}, "u": list(range(files)), "edges": []}
    L = {"lanes": [ln("a", th="MainThread", calls=3, files=1), ln("b", ext=True), ln("c", thr=8), ln("d", calls=4), ln("e", files=2),
                   ln("f"), ln("g", calls=900, files=3)], "links": [], "window": [0, 1]}
    why = lanedefault.default_folded(L)
    assert set(why) == {"b", "c", "e"} and "线程池" in why["c"], why
    assert lanedefault.default_lanes(L) == ["a", "d", "f", "g"], "主线程不收"
    assert lanedefault.default_lanes({"lanes": [ln("b", ext=True)]}) is None, "全要收时看全部"
    # 折叠行按次数摊开数：一行 186 次横跨 [-9 s, +9.8 s] 的折叠行在 [0, 4.5 s) 里有 44 次（只看开始时刻会算成没调用）
    row = lambda t, dur, key, rep: [t, dur, 7, 0, 0, key, rep, 0, -1]
    assert segments._n_in(row(-9_025_000, 18_850_000, 3, 186), 0, 4_500_000) == 44     # 隔 0.102 s 一次，4.5 s 里 44 次
    from codestrata import align, lanes as _lanes, runs as _runs, seq
    from codestrata.ui import load as _load
    repo, rid = truth()
    idx = _load.load_index(repo)
    run, rd, ph = _runs.resolve(repo, rid)
    segs, _, end = seq.window_segments(run, rd, ph)
    lo, hi = segs[0][0], segs[-1][1]
    nm, hw = segments.head_window(run, end, lo, hi, ph)
    S = segments.stages(rd, run, nm, lo, hi, align.node_labeler(idx), hw)
    L = _lanes.build(idx, rd, run, ph, _runs.load_run(repo, idx, run, rd, ph)[0], None)
    al, keep = _lanes.run_aliases(rd), lanedefault.default_lanes(L) or []
    fold = {al[ln["id"]] for ln in L["lanes"] if ln["id"] not in keep}
    assert "truth-1/req" in fold and "truth-1/MainThread" not in fold and procinfo.summary(S, lo), fold
    # 看的是整个 run（有 serving 阶段）：进程按启动的先后（每个进程映像的起点），不按第一次活动
    run2 = dict(run, phases=list(run.get("phases") or []) + [{"name": "serving"}])
    po = segments.proc_order(rd, run2, None, 0, seq.run_end(run2, rd), align.node_labeler(idx), None)
    assert po and po == _lanes.proc_starts(seq.span_index(rd)), po


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
