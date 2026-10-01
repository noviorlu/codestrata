"""新旧代码给前端的数据逐项对比（重构用的对拍工具，不是回归测试）。

    .venv/bin/python tests/payload_parity.py <旧提交> <仓库> [RUN …]

把 <旧提交> 的 codestrata 导出到临时目录，和现在工作区里的代码各跑一遍，对同一份索引和 run 算：
  - 几个切面（默认、全部收起、展开两层以内的目录）上的图：不叠 run，和叠每个 RUN；
  - 这些图上每条边（含只在 runtime 出现的、仅类型的）的边详情（展开的切面上边太多时只算跑到的）；
  - 每个 RUN（录了时序事件的）在默认切面上的「时间顺序」。
两边的结果按 JSON 逐项比，列出前几处不一样的地方。RUN 的写法同 serve --hot（id、case 名、@阶段、@t=起-止）。
两边要认得同一个索引格式（新代码改了格式就先用旧代码……这个工具就不适用了）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

_DUMP = r'''
import json, sys
from pathlib import Path
from codestrata import cut, payload, runs, seq
repo = Path(sys.argv[1]); refs = sys.argv[2:]
idx = payload.load_index(repo)
# 展开两层以内的目录：全部展开在大仓库上节点太多（vllm-omni 1463 个），光排版就要很久，也不是真会看的切面
deep = sorted(d for d in idx.get("dirs") or {} if d.count("/") <= 2)
cuts = {"default": None, "closed": [], "deep": deep}
out = {}
for ref in [None] + refs:
    hot, meta = payload.load_hot(repo, idx, ref) if ref else (None, None)
    for name, open_ in cuts.items():
        g = payload.graph_payload(repo, idx, hot=hot, hot_meta=meta, open_=open_)
        pairs = sorted({(e[0], e[1]) for e in g["graph"]["edges"]}
                       | {(e[0], e[1]) for e in g["runtimeOnlyEdges"] + g["typeOnlyEdges"]})
        if name == "deep" and len(pairs) > 400:
            # 展开得深的大仓库上边太多：只算这次跑到的边；没跑到的单元对已经在另外两种切面的边详情里合进去了
            hot_edges = set((g.get("hot") or {}).get("edges") or {})
            pairs = [(a, b) for a, b in pairs if f"{a}|{b}" in hot_edges]
        out[f"{ref}|{name}|graph"] = g
        out[f"{ref}|{name}|edges"] = {f"{a}|{b}": payload.edge_detail(repo, idx, a, b, hot) for a, b in pairs}
    if ref:
        run, rd, phase = runs.resolve(repo, ref)
        try:
            out[f"{ref}|seq"] = seq.edge_times(idx, rd, run, open_=None, phase=phase)
        except Exception as e:
            out[f"{ref}|seq"] = {"error": type(e).__name__ + ": " + str(e)}
json.dump(out, sys.stdout, sort_keys=True, ensure_ascii=False, default=list)
'''


def _dump(src: Path, repo: Path, refs: list[str]) -> dict:
    env = {**os.environ, "PYTHONPATH": str(src)}
    r = subprocess.run([sys.executable, "-c", _DUMP, str(repo), *refs], capture_output=True, text=True, env=env,
                       timeout=3600)
    if r.returncode != 0:
        raise SystemExit(f"{src} 跑不下来：\n{r.stderr[-3000:]}")
    return json.loads(r.stdout)


def _diff(a, b, path: str, out: list, limit: int) -> None:
    if len(out) >= limit or a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'只在新的里' if k not in a else '只在旧的里'}")
            else:
                _diff(a[k], b[k], f"{path}.{k}", out, limit)
            if len(out) >= limit:
                return
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, limit)
    else:
        out.append(f"{path}: 旧 {json.dumps(a, ensure_ascii=False)[:160]} ≠ 新 {json.dumps(b, ensure_ascii=False)[:160]}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rev, repo, refs = argv[0], Path(argv[1]).resolve(), argv[2:]
    with tempfile.TemporaryDirectory(prefix="cs-parity-") as tmp:
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", rev, "codestrata"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
        old = _dump(Path(tmp), repo, refs)
    new = _dump(ROOT, repo, refs)
    diffs: list[str] = []
    _diff(old, new, "", diffs, 40)
    n_edges = sum(len(v) for k, v in new.items() if k.endswith("|edges"))
    print(f"对比了 {sum(1 for k in new if k.endswith('|graph'))} 张图、{n_edges} 条边的详情、"
          f"{sum(1 for k in new if k.endswith('|seq'))} 份时间顺序")
    if not diffs:
        print("逐项一致")
        return 0
    print(f"不一样的地方（最多列 40 处）：")
    for d in diffs:
        print("  " + d)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
