"""codestrata 命令行。

    codestrata scan  <repo>                      静态扫描 → .codestrata/index.json
    codestrata serve <repo> [--hot CASE]         本地部署前端：图 + 源码 + 解读 + 跳编辑器
    codestrata trace <repo> --case NAME -- CMD   跑一个 case，记录真实调用
    codestrata tasks <repo> [--write]            待解读的模块（自底向上）+ 给 agent 的输入包
    codestrata pack  <repo> <target>             打印某个模块给 agent 的输入包
    codestrata note  <repo> <target> <file.md>   写回一份解读（仓库总览的 target 是 _overview）
    codestrata check <repo> [target ...]         机器核对解读：过期、引用的 file:line / 符号是否存在
    codestrata graph <repo> [--hot CASE]         导出单文件 HTML（只读、离线、可分享）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cut as _cut
from . import notes as _notes
from . import payload as _payload
from . import render as _render
from . import scan as _scan
from . import trace as _trace


def _outdir(repo: Path) -> Path:
    d = repo / ".codestrata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index(repo: Path) -> dict:
    return _payload.load_index(repo)


def cmd_scan(a) -> int:
    repo = Path(a.repo).resolve()
    depth = None if a.depth == "auto" else int(a.depth)
    idx = _scan.scan(repo, depth=depth, roots=a.roots, expand=a.expand)
    p = _scan.write_index(repo, idx, _outdir(repo))
    r = idx["repo"]
    v = _cut.view(idx, set(idx["default_open"]))
    shown = _cut.visible(v)
    print(f"扫描 {r['n_files']} 文件（解析失败 {r['n_parse_errors']}），{len(idx['packages'])} 个模块、"
          f"{len(idx['edges'])} 条模块间 import 边、{len(idx['symbols'])} 个符号")
    if depth is None:
        split = "，".join(f"{_short(idx, x['node'])}（占 {x['share']:.0%}，拆成 {x['fanout']} 块）"
                          for x in r.get("auto_split") or [])
        print(f"默认切面 {len(shown)} 个节点、{len(v['edges'])} 条边；按规模自动拆开：{split or '无'}")
    else:
        print(f"默认切面 {len(shown)} 个节点、{len(v['edges'])} 条边（depth={depth}）")
    if r.get("unresolved_imports"):
        print(f"指向仓库里不存在的模块的 import {len(r['unresolved_imports'])} 条（不进图）："
              + "；".join(r["unresolved_imports"][:5]) + ("…" if len(r["unresolved_imports"]) > 5 else ""))
    print(f"→ {p}")
    print(f"→ {p.parent / 'symbols.json'}")
    print("\n架构高度（+1 入口 … −1 叶子），默认切面上的节点：")
    for name in sorted(shown, key=lambda n: -v["nodes"][n]["alt"]):
        x = v["nodes"][name]
        bar = "█" * int((x["alt"] + 1) * 11)
        tag = {"dir": "/", "residual": "", "unit": ""}[x["kind"]]
        print(f"  {x['alt']:+.2f} {bar:<24} {_short(idx, name) + tag:<40} {x['files']:4d}f {x['classes']:4d}c")
    return 0


def _short(idx: dict, name: str) -> str:
    roots = idx["repo"].get("roots") or []
    pre = roots[0].split("/")[-1] + "." if len(roots) == 1 else ""
    return name[len(pre):] if pre and name.startswith(pre) else name


def cmd_graph(a) -> int:
    """导出单文件 HTML（只读、离线、可分享）。要写解读或跳编辑器，用 serve。"""
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    hot, meta = _payload.load_hot(repo, idx, a.hot)
    pl = _payload.export_payload(repo, idx, hot=hot, hot_meta=meta, per_pkg=a.per_pkg)
    html = _render.export(pl, title=f"{idx['repo']['name']} · codestrata",
                          fragment=a.fragment)
    name = f"overview{'-' + a.hot if a.hot else ''}.html"
    out = Path(a.out) if a.out else (_outdir(repo) / name)
    out.write_text(html, encoding="utf-8")
    g = pl["graph"]
    ids = [n["id"] for n in g["nodes"]]                 # 和前端同口径：只数图上的节点
    noted = sum(1 for i in ids if pl["notes"][i]["present"] and not pl["notes"][i]["stale"])
    print(f"→ {out}  ({len(html) / 1024:.0f} KB，{len(g['nodes'])} 节点 / {len(g['edges'])} 边，"
          f"泳道 {g['lanes']}，解读 {noted}/{len(ids)}"
          + (f"，hot: {len(hot['packages'])} 个包跑到" if hot else "") + ")")
    return 0


def cmd_tasks(a) -> int:
    """列出还需要解读的模块（自底向上），可选把输入包写到文件里交给 agent。"""
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    hot, _ = _payload.load_hot(repo, idx, a.hot) if a.hot else (None, None)
    todo = _notes.tasks(repo, idx)
    total = len(_cut.visible(_cut.view(idx, set(idx["default_open"])))) + 1      # + 仓库总览
    print(f"待解读 {len(todo)} / {total}（默认切面上的节点 + 总览；按架构高度自底向上：先读叶子，再读依赖它们的）")
    for t in todo:
        print(f"  {t['alt']:+.2f}  {t['reason']:<7}  {t['target']:<36} "
              f"{t['files']}f {t['classes']}c {t['funcs']}fn")
    if a.write:
        d = _outdir(repo) / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(todo, 1):
            p = d / f"{i:02d}-{t['target']}.md"
            p.write_text(_notes.prompt_pack(repo, idx, t["target"], hot=hot), encoding="utf-8")
        print(f"→ 输入包写到 {d}/（{len(todo)} 个，文件名前缀即建议顺序）")
        print(f"  agent 产出的 Markdown 用这个写回：codestrata note {repo} <target> <file.md>")
    return 0


def cmd_pack(a) -> int:
    """打印一个模块的输入包。每次现算：下层解读写好后，上层的包会自动带上它们。"""
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    if not _cut.is_node(idx, a.target) and a.target != _notes.OVERVIEW:
        raise SystemExit(f"没有这个模块：{a.target}（仓库总览用 {_notes.OVERVIEW}）")
    hot, _ = _payload.load_hot(repo, idx, a.hot) if a.hot else (None, None)
    print(_notes.prompt_pack(repo, idx, a.target, hot=hot))
    return 0


def cmd_note(a) -> int:
    """把一份 Markdown 写成某个模块的解读（自动补 frontmatter 和 code_sha）。"""
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    if not _cut.is_node(idx, a.target) and a.target != _notes.OVERVIEW:
        raise SystemExit(f"没有这个模块：{a.target}（仓库总览用 {_notes.OVERVIEW}）")
    body = Path(a.file).read_text(encoding="utf-8") if a.file != "-" else sys.stdin.read()
    nt = _notes.save(repo, idx, a.target, body, meta={"written_by": a.by})
    print(f"→ {nt['path']}  code_sha={nt['code_sha_now']}")
    return 0


def cmd_check(a) -> int:
    """机器核对已写的解读：过期没有、引用的 file:line 和符号名在代码里是否真的存在。"""
    repo = Path(a.repo).resolve()
    idx = _load_index(repo)
    targets = a.targets or (list(idx["packages"]) + [_notes.OVERVIEW])
    if a.fix:
        for t in targets:
            n = _notes.fix_refs(repo, idx, t)
            if n:
                print(f"  修正 {t}：{n} 处引用改到了新行号（内容仍需重读确认，所以还标着过期）")
    bad = 0
    for t in targets:
        nt = _notes.load(repo, idx, t)
        if not nt["present"]:
            continue
        probs = _notes.verify(repo, idx, t)
        mark = "过期" if nt["stale"] else ("✗" if probs else "✓")
        print(f"  {mark:<3} {t}")
        for p in probs:
            print(f"        {p['text']}：{p['msg']}")
        bad += bool(probs) or nt["stale"]
    print(f"{'有问题' if bad else '全部通过'}（{bad} 份需要处理）")
    return 1 if bad else 0


def cmd_trace(a) -> int:
    repo = Path(a.repo).resolve()
    if not a.cmd:
        raise SystemExit("要在 -- 之后给出命令，例如：\n"
                         "  codestrata trace . --case demo -- python examples/foo.py")
    # 顶层包 → 仓库内目录：命令若跑的是 pip 安装的那份，trace 靠它映射回仓库
    roots = a.roots or _scan.detect_roots(repo)
    pkgs = {r.split("/")[-1]: r for r in roots}
    tr = _trace.run(repo, a.cmd, case=a.case, outdir=_outdir(repo), timeout=a.timeout, pkgs=pkgs)
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
    s.add_argument("--depth", default="auto",
                   help="默认切面：auto 按规模自动拆分；给数字就展开所有深度小于它的目录（2 = 二级包）")
    s.add_argument("--expand", action="append", default=[], metavar="DIR",
                   help="默认切面里额外展开这个目录（可重复），比如 vllm_omni.model_executor.models")
    s.set_defaults(fn=cmd_scan)

    g = sub.add_parser("graph", help="导出单文件 HTML（只读、可分享）")
    common(g)
    g.add_argument("--hot", default=None, metavar="CASE", help="叠加某个 case 的 runtime 结果")
    g.add_argument("--per-pkg", type=int, default=10, help="每个包嵌入多少个符号的源码")
    g.add_argument("--fragment", action="store_true", help="去掉 doctype 外壳（给 artifact 之类的宿主用）")
    g.add_argument("--out", default=None)
    g.set_defaults(fn=cmd_graph)

    k = sub.add_parser("tasks", help="列出待解读的模块，可把输入包写出来交给 agent")
    common(k)
    k.add_argument("--hot", default=None, metavar="CASE")
    k.add_argument("--write", action="store_true", help="把输入包写到 .codestrata/tasks/")
    k.set_defaults(fn=cmd_tasks)

    pk = sub.add_parser("pack", help="打印某个模块给 agent 的输入包")
    pk.add_argument("repo")
    pk.add_argument("target")
    pk.add_argument("--hot", default=None, metavar="CASE")
    pk.set_defaults(fn=cmd_pack)

    nn = sub.add_parser("note", help="把一份 Markdown 写成某个模块的解读")
    nn.add_argument("repo")
    nn.add_argument("target")
    nn.add_argument("file", help="Markdown 文件；- 表示从 stdin 读")
    nn.add_argument("--by", default="human", help="记在 frontmatter 的 written_by")
    nn.set_defaults(fn=cmd_note)

    c = sub.add_parser("check", help="机器核对已写的解读（过期 / 引用不存在）")
    c.add_argument("repo", nargs="?", default=".")
    c.add_argument("targets", nargs="*")
    c.add_argument("--fix", action="store_true",
                   help="把只是挪了位置的 file:line 引用改到新行号（不会把过期标记去掉）")
    c.set_defaults(fn=cmd_check)

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
