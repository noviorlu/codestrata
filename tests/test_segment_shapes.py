"""切段在几种程序形状上的回归测试：不流式的流水线、阻塞取任务的 worker、先后两次请求、一个进程两条循环线程、
asyncio 里别的 task、两个进程交替干活、只在忙的轮里调的函数、一轮调两次的函数。每个都是会切错、而且错得很笃定的形状。

    python tests/test_segment_shapes.py [名字里的词…]
"""
from __future__ import annotations

import sys

from common import run_tests, tmpdir  # noqa: E402
from synth import Script  # noqa: E402

from codestrata import segments, steps  # noqa: E402

REC = {"phase_at": [{"name": "serving", "file": "app/client.py", "qualname": "Client.request", "line": 3}]}
CLIENT = "app/client.py:3"


def label(k: str) -> str:
    return "app/client.py#Client.request" if k == CLIENT else k.replace(":", "#f")


def cut(rd, lo: int, hi: int, head_window: tuple | None = None):
    """切段：(analyse 的结果, 段, 请求)"""
    A = segments.analyse(rd, lo, hi, head_window=head_window)
    reqs = segments.requests(A, {"rec": REC}, "serving", lo, hi, label)
    return A, segments.stage_segments(A, lo, hi, {q["pid"] for q in reqs}), reqs


def brief(segs: list[dict]) -> list[tuple]:
    return [(s["proc"], s["slices_us"][0][0], s["slices_us"][0][1]) for s in segs]


def lane(A: dict, alias: str) -> dict:
    return next(ln for ln in A["lanes"].values() if ln["alias"] == alias)


def pipeline(pre: int):
    """两段不流式的流水线：A 在 10–110 ms 每轮跑 model_a，干完一次交给 B；B 在 110–210 ms 跑 model_b。主循环每 1 ms 一轮
    （定时循环：闲着和干活的轮一样长）。pre：run 开始之前主循环已经空转了多久"""
    K = ["eng/loop.py:1", "eng/sched.py:10", "eng/model_a.py:5", "eng/model_b.py:5", CLIENT, "eng/out.py:1"]
    s = Script(K)
    s.thread(10, 1, "MainThread", proc="python -m eng.stage", title="StageProc_stage0")
    s.thread(20, 1, "MainThread", proc="python -m eng.stage", title="StageProc_stage1")
    s.thread(30, 1, "MainThread", proc="python client.py")
    busy = {10: (10_000, 110_000), 20: (110_000, 210_000)}
    req = s.call(30, 1, 9_500, 202_000, 4)
    roots = {pid: s.call(pid, 1, -pre - 10, 250_000 + pre + 20, 0) for pid in busy}
    for pid, (a, b) in busy.items():
        for k in range(-pre // 1000, 250):
            t = k * 1000
            s.call(pid, 1, t, 100, 1, parent=roots[pid])
            if a <= t < b:
                s.call(pid, 1, t + 150, 700, 2 if pid == 10 else 3, parent=roots[pid])
                if t + 1000 >= b:
                    o = s.call(pid, 1, t + 860, 50, 5, parent=roots[pid])
                    to = (20, 1, roots[20], t + 900) if pid == 10 else (30, 1, req, t + 900)
                    s.handoff("zmq", (pid, 1, o, t + 870), to)
    s.handoff("zmq", (30, 1, req, 9_900), (10, 1, roots[10], 9_950))
    return s.write(tmpdir("cs-shape-"), phases=[["start", -pre - 10 if pre else 0], ["serving", 9_400]], rec=REC)


def test_pipeline_not_by_idle_share():
    """空转按这一列自己的「便宜的那类轮」判，不按 run 里别处空闲了多久：前面加不加 2 s 启动空转，切出来的段一样"""
    want = [("stage0", 10_000, 110_000), ("stage1", 110_000, 210_000)]
    for pre in (0, 2_000_000):
        A, segs, _ = cut(pipeline(pre), 9_400, 250_000)
        assert brief(segs) == want, (pre, brief(segs))
        assert all(not s["gaps"] for s in segs), [s["gaps"] for s in segs]


def worker(nreq: int):
    """阻塞取任务的 worker（q.get 在仓库外）：每个请求 handle 一次，handle 里调 20 次 model"""
    K = ["svc/worker.py:1", "svc/worker.py:10", "svc/model.py:5", CLIENT]
    s = Script(K)
    s.thread(10, 1, "MainThread", proc="python -m svc.worker")
    s.thread(30, 1, "MainThread", proc="python client.py")
    root = s.call(10, 1, -10, 10_000_020, 0)
    for i in range(nreq):
        t = 8_000_000 + i * 200_000
        req = s.call(30, 1, t, 150_000, 3)
        h = s.call(10, 1, t + 1000, 140_000, 1, parent=root)
        for j in range(20):
            s.call(10, 1, t + 2000 + j * 6000, 5000, 2, parent=h)
        s.handoff("queue", (30, 1, req, t + 500), (10, 1, root, t + 900))
        s.handoff("queue", (10, 1, h, t + 140_500), (30, 1, req, t + 140_800))
    return s.write(tmpdir("cs-shape-"), phases=[["start", 0], ["serving", 0]], rec=REC)


def test_inner_loop_is_not_the_main_loop():
    """一次请求里面的内层循环（handle 里调 20 次 model）不当主循环、也不判成只在轮询；请求多了，每轮是一次 handle；
    认不出主循环的进程列在「没出段」里"""
    A, segs, _ = cut(worker(1), 0, 10_000_000)
    w = lane(A, "svc.worker/MainThread")
    assert w["loop"] is None and w["kind"] == "few", (w["kind"], w["loop"] and A["ix"]["keys"][w["loop"]["head"]])
    assert segs == [] and segments.background(A, segs) == []
    loose = segments.unsegmented(A, 0, 10_000_000, segs, {30})
    assert [(e["proc"], e["calls"], e["first_us"]) for e in loose] == [("svc.worker", 1, 8_001_000)], loose
    A, segs, _ = cut(worker(6), 0, 10_000_000)
    w = lane(A, "svc.worker/MainThread")
    assert A["ix"]["keys"][w["loop"]["head"]] == "svc/worker.py:10" and len(w["rounds"]) == 6, A["ix"]["keys"][w["loop"]["head"]]
    assert brief(segs) == [("svc.worker", 8_001_000, 9_141_000)], brief(segs)


def test_two_requests_two_segments():
    """先后两次请求：同一个进程出两段（中间空转 50 ms）；每轮都调的调度是轮头，不是只在忙的轮里调的 model"""
    K = ["eng/loop.py:1", "eng/sched.py:10", "eng/model.py:5", CLIENT, "eng/out.py:1"]
    s = Script(K)
    s.thread(10, 1, "MainThread", proc="python -m eng.stage", title="StageProc_stage0")
    s.thread(30, 1, "MainThread", proc="python client.py")
    root = s.call(10, 1, -2_000_000, 2_200_000, 0)
    reqs = [s.call(30, 1, 500, 11_000, 3), s.call(30, 1, 60_500, 21_000, 3)]
    for k in range(-2000, 100):
        t = k * 1000
        s.call(10, 1, t, 100, 1, parent=root)
        for qi, (a, b) in enumerate(((1_000, 11_000), (61_000, 81_000))):
            if a <= t < b:
                s.call(10, 1, t + 150, 700, 2, parent=root)
                o = s.call(10, 1, t + 860, 50, 4, parent=root)
                s.handoff("zmq", (10, 1, o, t + 870), (30, 1, reqs[qi], t + 900))
                if t == a:
                    s.handoff("zmq", (30, 1, reqs[qi], t - 300), (10, 1, root, t - 200))
    rd = s.write(tmpdir("cs-shape-"), phases=[["start", -2_000_000], ["serving", 0]], rec=REC)
    A, segs, reqs = cut(rd, 0, 100_000)
    assert A["ix"]["keys"][lane(A, "StageProc_stage0/MainThread")["loop"]["head"]] == "eng/sched.py:10"
    assert len(reqs) == 2 and brief(segs) == [("StageProc_stage0", 1_000, 11_000), ("StageProc_stage0", 61_000, 81_000)], brief(segs)
    assert segs[1]["gaps"] == [], segs[1]["gaps"]


def two_threads(io_from: int, eng_to: int):
    """一个进程两条循环线程：MainThread（引擎，每 1 ms 一轮，2 ms–eng_to 跑 model）、io_loop（每 0.5 ms 一轮，io_from 之后编码输出交给 client）"""
    K = ["svc/loop.py:1", "svc/loop.py:10", "svc/model.py:5", "svc/io.py:1", "svc/io.py:10", "svc/io.py:20", CLIENT]
    s = Script(K)
    s.thread(10, 1, "MainThread", proc="python -m svc.server")
    s.thread(10, 2, "io_loop", proc="python -m svc.server")
    s.thread(30, 1, "MainThread", proc="python client.py")
    req = s.call(30, 1, 0, 100_000, 6)
    r1 = s.call(10, 1, -10, 100_020, 0)
    r2 = s.call(10, 2, -10, 100_020, 3)
    for k in range(100):
        s.call(10, 1, k * 1000, 50, 1, parent=r1)
        if 2_000 <= k * 1000 < eng_to:
            s.call(10, 1, k * 1000 + 100, 800, 2, parent=r1)
    for k in range(200):
        t = k * 500
        s.call(10, 2, t, 20, 4, parent=r2)
        if t >= io_from:
            x = s.call(10, 2, t + 50, 400, 5, parent=r2)
            s.handoff("zmq", (10, 2, x, t + 440), (30, 1, req, t + 460))
    s.handoff("zmq", (30, 1, req, 1_000), (10, 1, r1, 1_100))
    return s.write(tmpdir("cs-shape-"), phases=[["start", 0], ["serving", 0]], rec=REC)


def test_process_with_two_loop_threads():
    """一个进程两条循环线程：前景轮合在一起切块——接着干就是一段（引擎 2–60 ms、输出 60–100 ms），中间歇了很久就是两段；
    第二段之前这个进程已经出过段，不报「没录到交给它的数据」"""
    A, segs, _ = cut(two_threads(60_000, 60_000), 0, 100_000)
    assert brief(segs) == [("svc.server", 2_000, 99_500)], brief(segs)
    A, segs, _ = cut(two_threads(60_000, 15_000), 0, 100_000)
    assert brief(segs) == [("svc.server", 2_000, 15_000), ("svc.server", 60_000, 99_500)], brief(segs)
    assert [s["main"] for s in segs] == ["svc.server/MainThread", "svc.server/io_loop"] and segs[1]["gaps"] == []


def test_asyncio_other_tasks_stay_out():
    """asyncio：同一条线程上别的 task（每 7 ms 一次 log_stats）不算进编排循环的轮里；编排进程只在 40–60 ms 处理输出"""
    K = ["orch/main.py:1", "orch/loop.py:10", "orch/loop.py:20", "orch/loop.py:30", "orch/stats.py:5", "orch/stats.py:9",
         CLIENT, "orch/req.py:1", "orch/req.py:7", "stage/eng.py:1", "stage/eng.py:5"]
    s = Script(K)
    s.thread(10, 4, "orchestrator", proc="python -m orch.main")
    s.thread(20, 1, "MainThread", proc="python -m stage.eng", title="StageProc_stage0")
    s.thread(30, 1, "MainThread", proc="python client.py")
    req = s.call(30, 1, 5_000, 90_000, 6)
    la = s.call(10, 4, -10, 100_020, 1, susp=100)       # 三个长寿的协程（挂起过：时长含挂起）
    ls = s.call(10, 4, -9, 100_020, 4, susp=15)
    lr = s.call(10, 4, -8, 100_020, 7, susp=2)
    for k in range(100):
        t = k * 1000
        s.call(10, 4, t, 30, 2, parent=la)
        if 40 <= k < 60:
            x = s.call(10, 4, t + 300, 200, 3, parent=la)
            s.handoff("zmq", (20, 1, None, t + 100), (10, 4, x, t + 310))
    for t in range(0, 100_000, 7_000):
        s.call(10, 4, t + 500, 100, 5, parent=ls)
    r = s.call(10, 4, 5_200, 300, 8, parent=lr)
    s.handoff("zmq", (30, 1, req, 5_100), (10, 4, r, 5_200))
    er = s.call(20, 1, -10, 100_020, 9)
    for k in range(100):
        s.call(20, 1, k * 1000 + 50, 600 if 39 <= k < 59 else 20, 10, parent=er)
    rd = s.write(tmpdir("cs-shape-"), phases=[["start", 0], ["serving", 5_000]], rec=REC)
    A, segs, _ = cut(rd, 0, 100_000)
    assert ("orch.main", 40_000, 60_000) in brief(segs), brief(segs)


def alternate(pattern: list[tuple], total: int):
    """两个 stage 每 1 ms 一轮；pattern [(pid, 起, 止)] 里的轮多调 model_x，每块干完交给另一个进程"""
    K = ["eng/loop.py:1", "eng/sched.py:10", "eng/model_a.py:5", "eng/model_b.py:5", CLIENT]
    s = Script(K)
    s.thread(10, 1, "MainThread", proc="python -m eng.stage", title="StageProc_stageA")
    s.thread(20, 1, "MainThread", proc="python -m eng.stage", title="StageProc_stageB")
    s.thread(30, 1, "MainThread", proc="python client.py")
    req = s.call(30, 1, 0, total, 4)
    roots = {10: s.call(10, 1, 0, total, 0), 20: s.call(20, 1, 0, total, 0)}
    other = {10: 20, 20: 10}
    for pid in (10, 20):
        for k in range(total // 1000):
            t = k * 1000
            s.call(pid, 1, t, 100, 1, parent=roots[pid])
            if any(p == pid and a <= t < b for p, a, b in pattern):
                m = s.call(pid, 1, t + 150, 700, 2 if pid == 10 else 3, parent=roots[pid])
                if not any(p == pid and a <= t + 1000 < b for p, a, b in pattern):
                    s.handoff("zmq", (pid, 1, m, t + 860), (other[pid], 1, roots[other[pid]], t + 900))
    s.handoff("zmq", (30, 1, req, 0), (10, 1, roots[10], 5))
    return s.write(tmpdir("cs-shape-"), phases=[["start", 0], ["serving", 0]], rec=REC)


def test_alternating_stages():
    """A 0–5 ms、B 5–30 ms、A 30–35 ms：三段，A 出两段；每轮都调的调度是轮头（次数是 model 的两倍，但不是「一轮调两次」）"""
    rd = alternate([(10, 0, 5_000), (20, 5_000, 30_000), (10, 30_000, 35_000)], 35_000)
    A, segs, _ = cut(rd, 0, 35_000)
    assert brief(segs) == [("stageA", 0, 5_000), ("stageB", 5_000, 30_000), ("stageA", 30_000, 34_000)], brief(segs)
    rd = alternate([(10, 0, 10_000), (20, 10_000, 20_000), (10, 20_000, 30_000), (20, 30_000, 40_000)], 40_000)
    A, _, _ = cut(rd, 0, 40_000)
    assert A["ix"]["keys"][lane(A, "stageA/MainThread")["loop"]["head"]] == "eng/sched.py:10"


def test_head_counts():
    """轮头：一轮调两次的（相邻两次轮头之间正好两次）去掉；只在忙的轮里调的（10 次）不会让每轮都调的（100 次）被当成它的倍数"""
    K = ["e/loop.py:1", "e/has.py:1", "e/sched.py:1", "e/exec.py:1", "e/sample.py:1", "e/update.py:1"]
    s = Script(K)
    s.thread(1, 1, "MainThread")
    root = s.call(1, 1, 0, 100_000, 0)
    for k in range(100):
        t = k * 1000
        s.call(1, 1, t, 5, 1, parent=root)
        s.call(1, 1, t + 10, 50, 2, parent=root)
        s.call(1, 1, t + 70, 20, 1, parent=root)
        s.call(1, 1, t + 100, 300 if 50 <= k < 60 else 30, 3, parent=root)
        if 50 <= k < 60:
            s.call(1, 1, t + 410, 200, 4, parent=root)
        s.call(1, 1, t + 700, 10, 5, parent=root)
    rd = s.write(tmpdir("cs-shape-"))
    A = segments.analyse(rd, 0, 100_000)
    ln = next(iter(A["lanes"].values()))
    assert A["ix"]["keys"][ln["loop"]["head"]] == "e/sched.py:1", A["ix"]["keys"][ln["loop"]["head"]]
    fg = [x["k"] for x in ln["rounds"] if not x["spin"]]
    assert fg == list(range(51, 61)), fg
    assert steps.ALGO == "seg/2"


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
