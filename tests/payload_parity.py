"""新旧代码给前端的数据逐项对比（重构用的对拍工具，不是回归测试）。

    .venv/bin/python tests/payload_parity.py <旧提交> <仓库> [RUN …] [--new <新提交>]

把 <旧提交> 的 codestrata 导出到临时目录，和现在工作区里的代码（或 --new 给的另一个提交）各跑一遍，对同一份索引和 run 算：
  - 几个切面（默认、全部收起、展开两层以内的目录）上的图：不叠 run，和叠每个 RUN；
  - 这些图上每条边（含只在 runtime 出现的、老代码里仅类型的）的边详情（展开的切面上边太多时只算跑到的）；
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
from codestrata import runs
try:                                    # 界面取数拆成 ui/ 之后
    from codestrata.ui import edge as E, graphview as G, load as L
except ImportError:                     # 之前都在 payload.py 里
    from codestrata import payload as E
    G = L = E
repo = Path(sys.argv[1]); refs = sys.argv[2:]
idx = L.load_index(repo)
# 展开两层以内的目录：全部展开在大仓库上节点太多（vllm-omni 1463 个），光排版就要很久，也不是真会看的切面
deep = sorted(d for d in idx.get("dirs") or {} if d.count("/") <= 2)
cuts = {"default": None, "closed": [], "deep": deep}
out = {}
for ref in [None] + refs:
    hot, meta = L.load_hot(repo, idx, ref) if ref else (None, None)
    for name, open_ in cuts.items():
        g = G.graph_payload(repo, idx, hot=hot, hot_meta=meta, open_=open_)
        pairs = sorted({(e[0], e[1]) for e in g["graph"]["edges"]}
                       | {(e[0], e[1]) for e in g["runtimeOnlyEdges"] + g.get("typeOnlyEdges", [])})   # 老的有「仅类型」的边
        if name == "deep" and len(pairs) > 400:
            # 展开得深的大仓库上边太多：只算这次跑到的边；没跑到的单元对已经在另外两种切面的边详情里合进去了
            hot_edges = set((g.get("hot") or {}).get("edges") or {})
            pairs = [(a, b) for a, b in pairs if f"{a}|{b}" in hot_edges]
        out[f"{ref}|{name}|graph"] = g
        out[f"{ref}|{name}|edges"] = {f"{a}|{b}": E.edge_detail(repo, idx, a, b, hot) for a, b in pairs}
    if ref:
        run, rd, phase = runs.resolve(repo, ref)
        try:                                             # 分列（模块图的时间顺序 2026-10-08 去掉了）
            from codestrata import lanes
            out[f"{ref}|lanes"] = lanes.build(idx, rd, run, phase, hot, None)
        except Exception as e:
            out[f"{ref}|lanes"] = {"error": type(e).__name__ + ": " + str(e)}
out["__src__"] = __import__("codestrata").__file__          # 确认导入的是哪一份代码
json.dump(out, sys.stdout, sort_keys=True, ensure_ascii=False, default=list)
'''


def _dump(src: Path, repo: Path, refs: list[str], cwd: str) -> dict:
    # 两边各自只能看到自己那一份代码：在一个中立的目录里跑（python -c 会把当前目录排在 PYTHONPATH 前面，
    # 在仓库根目录跑的话导入的是工作区）；-S 不加载 site-packages（.venv 里可编辑安装的 codestrata 会把
    # 旧提交里没有的子模块从工作区补上）。codestrata 只用标准库
    env = {**os.environ, "PYTHONPATH": str(src)}
    r = subprocess.run([sys.executable, "-S", "-c", _DUMP, str(repo), *refs], capture_output=True, text=True,
                       env=env, timeout=3600, cwd=cwd)
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
    new_rev = None
    if "--new" in argv:
        i = argv.index("--new")
        new_rev, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    rev, repo, refs = argv[0], Path(argv[1]).resolve(), argv[2:]

    def export(r: str, into: Path) -> Path:
        into.mkdir()
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", r, "codestrata"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(into)], input=arch.stdout, check=True)
        return into
    with tempfile.TemporaryDirectory(prefix="cs-parity-") as tmp:
        cwd = Path(tmp) / "cwd"
        cwd.mkdir()
        old = _dump(export(rev, Path(tmp) / "old"), repo, refs, str(cwd))
        new = _dump(export(new_rev, Path(tmp) / "new") if new_rev else ROOT, repo, refs, str(cwd))
    src_old, src_new = old.pop("__src__"), new.pop("__src__")
    print(f"旧：{src_old}\n新：{src_new}")
    if src_old == src_new:
        raise SystemExit("两边导入的是同一份代码，比不出东西")
    diffs: list[str] = []
    _diff(old, new, "", diffs, 40)
    n_edges = sum(len(v) for k, v in new.items() if k.endswith("|edges"))
    print(f"对比了 {sum(1 for k in new if k.endswith('|graph'))} 张图、{n_edges} 条边的详情、"
          f"{sum(1 for k in new if k.endswith('|lanes'))} 份分列")
    if not diffs:
        print("逐项一致")
        return 0
    print("不一样的地方（最多列 40 处）：")
    for d in diffs:
        print("  " + d)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
