"""造一个只有时序事件的假 run 目录（events/spans、detail.json、run.json），给切段的单元测试和规模测试用。

    b = Builder(["app.py:1", "app.py:10", ...])          # 键表
    t = b.thread(pid, tid, "MainThread", proc="python -m app")
    root = t.call(t0, dur, callee, caller=0)              # 返回 span 下标（parent 用它）
    t.call(t0 + 5, 3, callee2, parent=root)
    b.handoff("queue", (pid, tid, row, t), (pid2, tid2, row2, t2))
    rd = b.write(dir)
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path


class Thread:
    def __init__(self, b: "Builder", pid: int, tid: int):
        self.b, self.pid, self.tid = b, pid, tid

    def call(self, t0: int, dur: int, callee: int, caller: int = 0, parent: int = -1, depth: int | None = None,
             rep: int = 1, susp: int = 0) -> int:
        rows = self.b.rows.setdefault(self.pid, [])
        if depth is None:
            depth = 0 if parent < 0 else rows[parent][3] + 1
        rows.append([t0, dur, self.tid, depth, caller, callee, rep, susp, parent])
        return len(rows) - 1


class Builder:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.rows: dict[int, list] = {}
        self.threads: dict[str, dict[str, str]] = {}
        self.procs: dict[int, dict] = {}
        self.handoffs: list[dict] = []
        self.truncated: list[int] = []

    def thread(self, pid: int, tid: int, name: str, proc: str = "python app.py", start: int = 0) -> Thread:
        self.threads.setdefault(str(pid), {})[str(tid)] = name
        self.procs.setdefault(pid, {"pid": pid, "ppid": 1, "argv": proc.split(), "title": None, "t0_us": start,
                                    "t1_us": None, "n_funcs": 1, "why": "atexit"})
        return Thread(self, pid, tid)

    def handoff(self, via: str, a: tuple, b: tuple) -> None:
        """a / b：(pid, tid, span 下标, t_us)"""
        self.handoffs.append({"via": via, "from": [*a, 0], "to": [*b, 0]})

    def write(self, d: Path, run_id: str = "20991231-000000-synth", phases: list | None = None, old: bool = False) -> Path:
        """写成 d/.codestrata/runs/<run_id>；old：老格式（没有 handoffs、span 没有 parent）"""
        rd = Path(d) / ".codestrata" / "runs" / run_id
        sp = rd / "events" / "spans"
        sp.mkdir(parents=True, exist_ok=True)
        chunks = []
        for pid, rows in sorted(self.rows.items()):
            # 不重排：parent 是下标。真的 span 按 (t0, depth) 排好，测试里按时间先后加
            name = f"p{pid}-000.jsonl.gz"
            body = "\n".join(json.dumps(r[:8] if old else r) for r in rows) + "\n"
            (sp / name).write_bytes(gzip.compress(body.encode()))
            chunks.append({"pid": pid, "chunk": name, "t0_us": min(r[0] for r in rows),
                           "t1_us": max(r[0] + max(r[1], 0) for r in rows), "n": len(rows)})
        ix = {"pairing": "frame", "chunks": chunks, "procs": [], "truncated": self.truncated, "n_lines": 0,
              "n_spans": sum(c["n"] for c in chunks), "n_calls": 0}
        if not old:
            ix.update(scope="all", handoffs=self.handoffs, spawns=[], thread_from={})
        (sp / "index.json").write_text(json.dumps(ix))
        (sp / "keys.json").write_text(json.dumps({"keys": self.keys, "threads": self.threads}))
        (rd / "detail.json").write_text(json.dumps({"procs": list(self.procs.values())}))
        (rd / "counts.json.gz").write_bytes(gzip.compress(json.dumps({"phases": {}, "names": {}}).encode()))
        end = max(c["t1_us"] for c in chunks)
        phases = phases or [["start", 0]]
        run = {"schema": 3, "id": run_id, "case": run_id.split("-", 2)[2], "status": "ok", "problems": [],
               "phase_log": [[n, t, "hook"] for n, t in phases], "duration_s": end / 1e6,
               "phases": [{"name": n, "t_us": t, "n_funcs": 1, "n_calls": 1} for n, t in phases],
               "events": {"n_spans": ix["n_spans"], "truncated": self.truncated}, "rec": {}}
        (rd / "run.json").write_text(json.dumps(run))
        return rd
