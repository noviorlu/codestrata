"""链（chain.py，links --follow）：合成的三个进程——stage1 的 save_loop 写共享内存 → stage2 的 recv_loop 收（积压：第 2、3 块等了很久）
→ 没录到的一跳（commit 之后主线程才跑 model）→ stage2 主线程下一轮把结果放进队列 → 发的线程（只跑仓库外的代码）经 zmq → end2end 的
orchestrator。测录到的跳、--link 按先后配、拒绝配不上的、停下时的候选、起点的几种写法、段的时间片。

    python tests/test_chain.py [名字里的词…]
"""
from __future__ import annotations

import sys

from common import run_tests, tmpdir  # noqa: E402
from synth import Script  # noqa: E402

from codestrata import chain, segments  # noqa: E402
from codestrata.errors import CodestrataError  # noqa: E402

FNS = {"eng/save.py:1": "save_loop", "eng/save.py:20": "Save.tick", "eng/shm.py:10": "Shm.put", "eng/recv.py:1": "recv_loop",
       "eng/recv.py:10": "Recv.poll", "eng/recv.py:20": "Recv.get_by_key", "eng/recv.py:30": "Recv.commit", "eng/main.py:1": "main",
       "eng/sched.py:10": "Sched.schedule", "eng/model.py:5": "Model.run", "eng/model.py:20": "Model.decode",
       "eng/model.py:30": "Model.warm", "eng/orch.py:1": "orchestrate"}
K = list(FNS)
k = {name: i for i, name in enumerate(FNS.values())}
PUTS = [2_000, 4_000, 6_000]
RECV = [2_500, 9_000, 15_000]           # 第 2、3 块在共享内存里等了很久（stage2 忙）


def label(key: str) -> str:
    return f"{key.split(':')[0]}#{FNS[key]}" if key in FNS else key


def scenario():
    s = Script(K)
    s.thread(10, 2, "Thread-1 (save_loop)", proc="python -m eng", title="StageProc_stage1")
    s.thread(20, 1, "MainThread", proc="python -m eng", title="StageProc_stage2")
    s.thread(20, 2, "Thread-2 (recv_loop)", proc="python -m eng", title="StageProc_stage2")
    s.thread(20, 3, "process_output_sockets", proc="python -m eng", title="StageProc_stage2")
    s.thread(30, 2, "orchestrator", proc="python end2end.py")
    save = s.call(10, 2, -1_000, 42_000, k["save_loop"])
    recv = s.call(20, 2, -1_000, 42_000, k["recv_loop"])
    main = s.call(20, 1, -1_000, 42_000, k["main"])
    orch = s.call(30, 2, -1_000, 42_000, k["orchestrate"])
    for t in range(0, 40_000, 1_000):
        s.call(10, 2, t, 50, k["Save.tick"], parent=save)
        s.call(20, 1, t, 50, k["Sched.schedule"], parent=main)
    for t in range(0, 40_000, 500):
        s.call(20, 2, t, 40, k["Recv.poll"], parent=recv)
    for i, (p, r) in enumerate(zip(PUTS, RECV)):
        put = s.call(10, 2, p + 100, 300, k["Shm.put"], parent=save)
        get = s.call(20, 2, r - 50, 150, k["Recv.get_by_key"], parent=recv)
        s.handoff("shm", (10, 2, put, p + 200), (20, 2, get, r))
        s.call(20, 2, r + 150, 100, k["Recv.commit"], parent=recv)
        run = (r + 300 + 999) // 1000 * 1000 + 100          # commit 之后主线程的下一轮跑 model
        s.call(20, 1, run, 600, k["Model.run"], parent=main)
        dec = s.call(20, 1, run + 1_000, 100, k["Model.decode"], parent=main)   # 再下一轮把结果放进队列
        s.handoff("queue", (20, 1, dec, run + 1_050), (20, 3, None, run + 1_070))
        s.handoff("zmq", (20, 3, None, run + 1_130), (30, 2, orch, run + 1_170))
        s.call(20, 1, [100, 9_100, 15_100][i], 50, k["Model.warm"], parent=main)
    return s.write(tmpdir("cs-chain-"), phases=[["start", -1_000], ["serving", 0]])


_W: list = []


def walker() -> chain.Walker:
    if not _W:
        rd = scenario()
        A = segments.analyse(rd, 0, 40_000)
        _W.append(chain.Walker(A, {}, label, 0, 40_000))
    return _W[0]


def code(fn) -> str:
    try:
        fn()
    except CodestrataError as e:
        return e.code
    return "ok"


def test_recorded_hop_then_stop_with_candidates():
    """第 2 块：put 里写共享内存（录到的，就在这次调用里）→ recv_loop 收到，之后没交出：停下，候选里 A 边是 commit（一份一次、
    离交出最近），B 边主线程的 Model.run 配得上，拼成一条能直接用的 --link"""
    W = walker()
    pos, st = W.start("Shm.put#2", None)
    assert (st["lane"], st["k"], st["k_lane"], st["t0_us"]) == ("stage1/save_loop", 2, 2, 4_100), st
    ch = W.walk(pos, [], (st["t0_us"], st["t1_us"]))
    (h,) = ch["hops"]
    assert (h["kind"], h["via"], h["stay"], h["k"], h["n"]) == ("recorded", "shm", "ancestor", 2, 3), h
    assert h["to"]["lane"] == "stage2/recv_loop" and h["to"]["t_us"] == 9_000 and h["to"]["fn"] == "eng/recv.py#Recv.get_by_key", h["to"]
    stop = ch["stop"]
    assert stop["reason"] == "none" and stop["until_us"] == 15_000 and stop["next_out"] is None, stop
    c = stop["candidates"]
    assert c["a"]["pick"] == "eng/recv.py#Recv.commit", c["a"]
    main = next(b for b in c["b"] if b["lane"] == "stage2/MainThread")
    assert [f["fn"] for f in main["fns"] if f["fits"]][:1] == ["eng/model.py#Model.run"], main
    assert c["link"] == "stage2/recv_loop:Recv.commit => stage2/MainThread:Model.run", c["link"]


def test_link_carries_the_chain_to_the_end():
    """加上那条 --link：第 2 次 commit 配第 2 次 Model.run（inferred: order）→ 主线程下一次交出（队列，inferred: time）→ 发的线程 → zmq →
    orchestrator，停下（之后它再没交出）。四跳都是第 2 份；段是两片时间 × 经过的五列"""
    W = walker()
    pos, st = W.start("Shm.put#2", None)
    ln = W.link("stage2/recv_loop:Recv.commit => stage2/MainThread:Model.run")
    ch = W.walk(pos, [ln], (st["t0_us"], st["t1_us"]))
    hs = ch["hops"]
    assert [(h["kind"], h["via"]) for h in hs] == [("recorded", "shm"), ("link", "link"), ("recorded", "queue"), ("recorded", "zmq")], hs
    assert all(h["k"] == 2 for h in hs) and hs[1]["basis"] == "order" and hs[2]["stay"] == "time", hs
    assert hs[1]["to"]["t_us"] == 10_100 and hs[2]["from"]["t_us"] == 11_150 and hs[-1]["to"]["lane"] == "end2end/orchestrator", hs
    assert ch["stop"]["reason"] == "none" and ch["stop"]["next_out"] is None, ch["stop"]
    assert ch["lanes"] == ["stage1/save_loop", "stage2/recv_loop", "stage2/MainThread", "stage2/process_output_sockets",
                           "end2end/orchestrator"], ch["lanes"]
    assert ch["slices_us"] == [[4_100, 4_400], [9_000, 12_270]], ch["slices_us"]


def test_link_over_a_recorded_hop():
    """--link 接的那一跳其实录到了：照 --link 配（agent 明说的），记下 recorded_too（命令行给 link_recorded 警告）"""
    W = walker()
    pos, st = W.start("Shm.put#2", None)
    ln = W.link("stage1/save_loop:Shm.put => stage2/recv_loop:Recv.commit")
    h = W.walk(pos, [ln], (st["t0_us"], st["t1_us"]))["hops"][0]
    assert (h["kind"], h["k"], h["stay"], h["to"]["t_us"]) == ("link", 2, "ancestor", 9_150), h
    assert h["recorded_too"] == "l:handoff|shm|stage1/save_loop|stage2/recv_loop", h


def test_link_mismatch():
    """次数不等（每轮都调的 schedule）、第 1 次 B 早于第 1 次 A（Model.warm）都拒绝；候选是 B 列里配得上的"""
    W = walker()
    for b in ("Sched.schedule", "Model.warm"):
        try:
            W.link(f"stage2/recv_loop:Recv.commit => stage2/MainThread:{b}")
        except CodestrataError as e:
            assert e.code == "link_mismatch" and "stage2/MainThread:Model.run" in e.candidates, (b, e.msg, e.candidates)
            assert ("次数不等" if b == "Sched.schedule" else "早于") in e.msg, e.msg
        else:
            raise AssertionError(b)
    assert code(lambda: W.link("stage2/recv_loop:Recv.commit => stage2/recv_loop:Recv.poll")) == "usage"
    assert code(lambda: W.link("stage2/recv_loop Recv.commit")) == "usage"
    assert code(lambda: W.link("stage2:Recv.commit => stage2/MainThread:Model.run")) == "ambiguous_lane"
    assert code(lambda: W.link("stage2/recv_loop:Model.run => stage2/MainThread:Model.run")) == "item_not_found"


def test_start_forms():
    """列#k 是第 k 轮（主线程第 3 轮里没交出：停下，下一次交出是第 1 块的结果，inferred: time）；列:FN#k 只数这一列；写错的报错"""
    W = walker()
    pos, st = W.start("stage2/MainThread#3", None)
    assert st["kind"] == "round" and (st["t0_us"], st["t1_us"]) == (2_000, 3_000), st
    ch = W.walk(pos, [], (st["t0_us"], st["t1_us"]))
    nxt = ch["stop"]["next_out"]
    assert not ch["hops"] and nxt["t_us"] == 4_150 and nxt["to"] == "stage2/process_output_sockets" and nxt["basis"] == "time", ch["stop"]
    pos, st = W.start("stage1/save_loop:Shm.put#1", None)
    assert st["kind"] == "call" and st["t0_us"] == 2_100, st
    assert code(lambda: W.start("Shm.put#9", None)) == "usage"
    assert code(lambda: W.start("Shm.put", None)) == "usage"
    assert code(lambda: W.start("nosuch#1", None)) == "item_not_found"
    assert code(lambda: W.start("stage2/MainThread#999", None)) == "usage"
    assert code(lambda: W.start("stage2#1", None)) == "ambiguous_lane"


def test_merge_and_misfit():
    assert chain.merge([(10, 5), (0, 3), (3_500, 3_600), (-50, 2)], 0, 3_550) == [[0, 11], [3_500, 3_550]]
    assert chain.misfit([(1,), (5,)], [(2,), (6,)]) is None
    assert chain.misfit([(1,), (5,)], [(2,)]) == ("count", 2, 1)
    assert chain.misfit([(1,), (5,)], [(2,), (4,)]) == ("order", 2, 5, 4)


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
