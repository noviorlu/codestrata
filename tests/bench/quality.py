"""核心质量的基准数（不是回归测试）：在一个 run 和当前的索引上打印几样能跟踪的数，改判定 / 类型推断前后各跑一次比。

    .venv/bin/python tests/bench/quality.py [REPO] [RUN@阶段] [--target 函数名 …] [--json]

默认是 vllm-omni 的 MiniCPM 那次请求（20260930-233507-run_single_prompt@serving，有调用行和时序事件）。打印：
  1. 跨文件的调用：一共几次、只有 trace（代码里看不出）几次、占多少；只有 trace 的按说明分（name / line / none / override /
     nomatch），name 再按写法分（self.属性.方法、局部变量或参数.方法、self.方法、getattr / 字符串、别的）——类型推断该压低的是前两种。
     次数让轮询的几对占了大头，所以也按「对」数一遍：跨文件的函数对几对、其中至少一处调用代码里看不出的几对。
  2. 请求路径上到几个目标函数（默认 compute_logits、_model_forward）的那条链：从根到它几跳、其中几跳代码里看不出；
     整个请求路径几行、其中几行的那一跳代码里看不出。
  3. /api/graph 的大小（默认切面，叠这个 run）。
只读：读索引和 run，不 scan、不 trace。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from codestrata import path as cs_path  # noqa: E402
from codestrata import runs  # noqa: E402
from codestrata.ui import graphview, load, source  # noqa: E402

REPO = "/home/yc/projects/vllm-omni"
RUN = "20260930-233507-run_single_prompt@serving"
TARGETS = ["compute_logits", "_model_forward"]


def receiver_form(text: str) -> str:
    """只知道名字的那一行，接收者是怎么写的"""
    if "getattr(" in text:
        return "getattr / 字符串"
    if re.search(r"\bself\.\w+(\[[^\]]*\])?\.\w+\s*\(", text):
        return "self.属性.方法"
    if re.search(r"\bself\.\w+\s*\(", text):
        return "self.方法"
    if re.search(r"\b\w+\.\w+\s*\(", text):
        return "局部变量或参数.方法"
    return "别的"


def measure(repo: Path, ref: str, targets: list[str]) -> dict:
    idx = load.load_index(repo)
    hot, meta = load.load_hot(repo, idx, ref)
    calls = hot["calls"]
    total = only = pairs = only_pairs = 0
    by_note: Counter = Counter()
    by_form: Counter = Counter()
    for pk, x in calls.items():
        if not (x["a"] and x["b"] and x["a"] != x["b"]):
            continue
        total += x["n"]
        only += x["only"]
        pairs += 1
        only_pairs += x["only"] > 0
        caller = pk.partition("|")[0]
        f = source.node_def(idx, caller)["f"]
        for y in x["lines"] or [{"l": (x.get("guessed") or [0])[0], "n": x["only"], "status": x.get("status"), "note": x.get("note")}]:
            if y["status"] != "trace":
                continue
            k = (y["note"] or {}).get("k") or "?"
            by_note[k] += y["n"]
            if k == "name":
                by_form[receiver_form(source.line_text(repo, f, y["l"]) if y["l"] else "")] += y["n"]
    out = {"run": ref, "has_lines": meta.get("has_lines"), "cross_file_calls": total, "trace_only": only,
           "trace_only_share": round(only / total, 4) if total else 0,
           "cross_file_pairs": pairs, "trace_only_pairs": only_pairs, "by_note": dict(by_note.most_common()),
           "name_by_receiver": dict(by_form.most_common())}
    run, rd, phase = runs.resolve(repo, ref)
    try:
        P = cs_path.request_path(idx, rd, run, phase, hot)
    except LookupError as e:
        P = None
        out["path"] = str(e)
    if P:
        chains = {}
        for t in targets:
            for p in P["procs"]:
                for th in p["threads"]:
                    rows = th["rows"]
                    hit = next((i for i, r in enumerate(rows) if r["fn"].rsplit(".", 1)[-1] == t), None)
                    if hit is None:
                        continue
                    chain, d = [], rows[hit]["d"]
                    for r in reversed(rows[:hit + 1]):          # 往回找每一层的父亲
                        if r["d"] == d:
                            chain.append(r)
                            d -= 1
                        if d < 0:
                            break
                    chain.reverse()
                    chains[t] = {"proc": p["name"], "thread": th["name"], "hops": len(chain) - 1,
                                 "hidden_hops": sum(1 for r in chain if r["line"] and r["line"]["status"] == "trace"),
                                 "chain": [r["fn"].partition("#")[2] for r in chain]}
                    break
                if t in chains:
                    break
        rows = [r for p in P["procs"] for th in p["threads"] for r in th["rows"]]
        out["path_rows"] = len(rows)
        out["path_rows_hidden"] = sum(1 for r in rows if r["line"] and r["line"]["status"] == "trace")
        out["chains"] = chains
    g = graphview.graph_payload(repo, idx, hot=hot, hot_meta=meta)
    out["api_graph_bytes"] = len(json.dumps(g, ensure_ascii=False).encode())
    return out


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    targets = TARGETS
    if "--target" in argv:
        i = argv.index("--target")
        targets, argv = argv[i + 1:], argv[:i]
    repo = Path(argv[0] if argv else REPO)
    ref = argv[1] if len(argv) > 1 else RUN
    m = measure(repo, ref, targets)
    if as_json:
        print(json.dumps(m, ensure_ascii=False))
        return 0
    print(f"{m['run']}（{'有' if m['has_lines'] else '没有'}调用行）")
    print(f"  跨文件的调用 {m['cross_file_calls']} 次，只有 trace {m['trace_only']} 次（{m['trace_only_share']:.1%}）")
    print(f"  按对数：跨文件的函数对 {m['cross_file_pairs']} 对，至少一处调用代码里看不出的 {m['trace_only_pairs']} 对"
          f"（{m['trace_only_pairs'] / max(m['cross_file_pairs'], 1):.1%}）")
    print("  只有 trace 按说明：" + "，".join(f"{k} {v}" for k, v in m["by_note"].items()))
    print("  其中 name 按接收者的写法：" + "，".join(f"{k} {v}" for k, v in m["name_by_receiver"].items()))
    for t, c in (m.get("chains") or {}).items():
        print(f"  请求路径上到 {t}：{c['hops']} 跳，其中 {c['hidden_hops']} 跳代码里看不出（{c['proc']} · {c['thread']}）")
        print("    " + " → ".join(c["chain"]))
    if "path_rows" in m:
        print(f"  请求路径一共 {m['path_rows']} 行，其中 {m['path_rows_hidden']} 行那一跳代码里看不出")
    print(f"  /api/graph {m['api_graph_bytes'] / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
