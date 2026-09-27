"""codestrata 命令行。

    codestrata scan  <repo>                      静态扫描 → .codestrata/index.json
    codestrata graph <repo> [--hot CASE]         出图 → .codestrata/overview.html
    codestrata trace <repo> --case NAME -- CMD   跑一个 case，记录真实调用
    codestrata serve <repo> [--port 8900]        本地服务：图 + 源码 + 跳编辑器
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import layout as _layout
from . import render as _render
from . import scan as _scan
from . import trace as _trace


def _outdir(repo: Path) -> Path:
    d = repo / ".codestrata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index(repo: Path) -> dict:
    """读回 index.json，并把拆出去的 symbols.json 合回来。"""
    d = _outdir(repo)
    p = d / "index.json"
    if not p.exists():
        raise SystemExit(f"没有 {p}；先跑 codestrata scan {repo}")
    idx = json.loads(p.read_text(encoding="utf-8"))
    sp = d / "symbols.json"
    if sp.exists():
        extra = json.loads(sp.read_text(encoding="utf-8"))
        idx["symbols"] = extra.get("symbols", {})
        idx["files"] = extra.get("files", {})
    return idx


def _resolve_depth(repo: Path, depth: str, roots: list[str] | None) -> tuple[dict, int]:
    """depth=auto 时自动加深，直到包数够画一张有信息量的图。

    小仓库（比如 codestrata 自己只有一个包）在 depth=2 下会退化成一个节点，
    这时必须下潜到模块粒度才有东西可看。
    """
    if depth != "auto":
        d = int(depth)
        return _scan.scan(repo, depth=d, roots=roots), d
    best = None
    for d in (2, 3, 4):
        idx = _scan.scan(repo, depth=d, roots=roots)
        n = len(idx["packages"])
        best = (idx, d)
        if n >= 4:
            break
    return best


def cmd_scan(a) -> int:
    repo = Path(a.repo).resolve()
    idx, depth = _resolve_depth(repo, a.depth, a.roots)
    p = _scan.write_index(repo, idx, _outdir(repo))
    r = idx["repo"]
    print(f"扫描 {r['n_files']} 文件（解析失败 {r['n_parse_errors']}），"
          f"包 {len(idx['packages'])} 个（depth={depth}），"
          f"import 边 {len(idx['edges'])} 条，符号 {len(idx['symbols'])} 个")
    print(f"→ {p}")
    print(f"→ {p.parent / 'symbols.json'}")
    print("\n架构高度（+1 入口 … −1 叶子）：")
    for name, v in sorted(idx["packages"].items(), key=lambda kv: -kv[1]["alt"]):
        bar = "█" * int((v["alt"] + 1) * 11)
        print(f"  {v['alt']:+.2f} {bar:<24} {name:<34} {v['files']:4d}f {v['classes']:4d}c")
    return 0


def cmd_graph(a) -> int:
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    g = _layout.build(idx, lanes=a.lanes, min_files=a.min_files, top=a.top)
    hot = hot_meta = None
    if a.hot:
        tp = _outdir(repo) / f"trace-{a.hot}.json"
        if not tp.exists():
            raise SystemExit(f"没有 {tp}；先跑 codestrata trace {repo} --case {a.hot} -- <命令>")
        tr = json.loads(tp.read_text(encoding="utf-8"))
        hot = _trace.to_package_graph(tr, idx)
        hot_meta = {"case": tr.get("case"), "cmd": tr.get("cmd"),
                    "n_procs": tr.get("n_procs"), "unmapped": hot.get("unmapped")}
    html = _render.render(idx, g, repo, hot=hot, hot_meta=hot_meta, per_pkg=a.per_pkg)
    name = f"overview{'-' + a.hot if a.hot else ''}.html"
    out = Path(a.out) if a.out else (_outdir(repo) / name)
    out.write_text(html, encoding="utf-8")
    print(f"→ {out}  ({len(html) / 1024:.0f} KB，{len(g['nodes'])} 节点 / {len(g['edges'])} 边"
          + (f"，hot: {len(hot['packages'])} 个包跑到" if hot else "") + ")")
    return 0


def cmd_trace(a) -> int:
    repo = Path(a.repo).resolve()
    if not a.cmd:
        raise SystemExit("要在 -- 之后给出命令，例如：\n"
                         "  codestrata trace . --case demo -- python examples/foo.py")
    tr = _trace.run(repo, a.cmd, case=a.case, outdir=_outdir(repo), timeout=a.timeout)
    p = _outdir(repo) / f"trace-{a.case}.json"
    p.write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
    print(f"→ {p}")
    print(f"  进程 {tr['n_procs']} 个，函数 {len(tr['funcs'])} 个被调到，"
          f"文件间调用边 {len(tr['file_edges'])} 条，退出码 {tr['returncode']}")
    try:
        idx = _load_index(repo)
    except SystemExit:
        print("  （还没 scan，跑 codestrata scan 之后再 graph --hot 就能叠图）")
        return 0
    hp = _trace.to_package_graph(tr, idx)
    print(f"  映射到 {len(hp['packages'])} 个包 / {len(hp['symbols'])} 个符号"
          f"（未映射调用 {hp['unmapped']}）")
    for k, v in sorted(hp["packages"].items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {v:8d}  {k}")
    return 0


def cmd_serve(a) -> int:
    from . import serve as _serve
    return _serve.main(Path(a.repo).resolve(), port=a.port, hot=a.hot)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codestrata", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="which", required=True)   # 不能叫 cmd：
                                                       # trace 的位置参数也叫 cmd，会互相覆盖

    def common(p):
        p.add_argument("repo", nargs="?", default=".")
        p.add_argument("--roots", nargs="*", default=None,
                       help="手动指定顶层包（默认自动探测，并排除 tests/examples 等）")

    s = sub.add_parser("scan", help="静态扫描")
    common(s)
    s.add_argument("--depth", default="auto", help="包聚合粒度，auto 会自动加深（默认 auto）")
    s.set_defaults(fn=cmd_scan)

    g = sub.add_parser("graph", help="出 HTML 图")
    common(g)
    g.add_argument("--hot", default=None, metavar="CASE", help="叠加某个 case 的 runtime 结果")
    g.add_argument("--lanes", type=int, default=9)
    g.add_argument("--min-files", type=int, default=1)
    g.add_argument("--top", type=int, default=None, help="只画最大的 N 个包")
    g.add_argument("--per-pkg", type=int, default=14, help="每个包嵌入多少个符号的源码")
    g.add_argument("--out", default=None)
    g.set_defaults(fn=cmd_graph)

    t = sub.add_parser("trace", help="跑一个 case，记录真实调用")
    common(t)
    t.add_argument("--case", required=True, help="给这次运行起个名字")
    t.add_argument("--timeout", type=float, default=None)
    t.add_argument("cmd", nargs="*", default=[],
                   help="-- 之后是要跑的命令")
    t.set_defaults(fn=cmd_trace)

    v = sub.add_parser("serve", help="本地服务：图 + 源码 + 跳编辑器")
    common(v)
    v.add_argument("--port", type=int, default=8900)
    v.add_argument("--hot", default=None, metavar="CASE")
    v.set_defaults(fn=cmd_serve)

    # 自己先按第一个 "--" 切开：argparse 的 REMAINDER 和可选位置参数放在一起时
    # 会互相抢参数（`trace . --case X -- cmd` 会报 --case 缺失）。
    raw = list(sys.argv[1:] if argv is None else argv)
    tail: list[str] = []
    if "--" in raw:
        i = raw.index("--")
        raw, tail = raw[:i], raw[i + 1:]
    a = ap.parse_args(raw)
    if a.which == "trace":
        a.cmd = tail or a.cmd
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
