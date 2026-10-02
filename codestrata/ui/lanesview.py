"""分列（/api/lanes）的图和面板要的、和切面有关的数据。每列可以有自己的切面（lanes.build 的 cuts，?cuts= 给），
图上画的、面板上讲的都按那一列的切面来；共用的切面（base，模块图用的那个）的节点在模块图的数据里已经有了。
这里在 lanes.build 的结果上补：
  - info {id: 节点信息}：各列的节点、连线两头的节点、各列画出来的框。节点同模块图数据的 pkgs[id]（cut.view 的节点，
    加上 frame、collapsible），再加 hits（这一段里调进去几次，同 hot.packages）和 name（面板、搜索栏写的短名，同 names；
    撞名按画它的（第一）列的切面算，见下面的 names）；完整的显示名是 label。节点信息只看 id，同一个 id 在哪一列的切面上
    都一样。只是框（哪一列里都没有收成节点）的 id 只有 kind、label、sep、name、frame、collapsible、hits；
  - more {id: {syms, files, docs}}：不是 base 节点的那些节点的顶层符号、文件、文档（同 pkgSyms / pkgFiles / pkgDocs）；
  - place {id: [B, sub]}：比 base 细的节点——在 base 的节点 B 里面——排在 B 那一层底下的第几个子层。B 里这一段各列调到的单元
    按调用和 import 自己分一次层（权重同模块图的分层），id 取它调到的单元里最靠上的那层。只看 id 和这一段，和哪一列展开了什么、
    画了哪些兄弟节点无关：各列共用一套纵坐标。和 base 节点一样粗或者更粗的不在里面；
  - 每列的 names {id: 图上写的字}（同模块图在这一列的切面上写的字：框里的写相对于框的名字；撞名按整个切面算
    （graphview.cut_alias），不只看这一列画了的——在别的列里展开 / 收起改不了这一列的名字）、
    frames {框: {"parent", "n": 框里几个这一列的节点, "minw": 框头要的宽度, "label": 框头上的名字}}（这一列的节点往上每一层展开着的
    目录，单根仓库的根不算，同模块图的框）。每列原来的 names（合进来的线程原名）挪到 thread_names。
"""
from __future__ import annotations

import json

from .. import cut as _cut
from .. import layout as _layout
from .. import seq as _seq
from . import graphview as _graphview


def parse_cuts(idx: dict, raw: str | None) -> dict | None:
    """?cuts= 的 JSON [{"lanes": [列 id…], "open": [展开的目录…]}…]（同样切面的列写在一组里）→ {列 id: 规整过的切面}。
    没给是 None；写得不对抛 ValueError（给人看的话）"""
    if raw is None or raw == "":
        return None
    try:
        xs = json.loads(raw)
    except ValueError:
        xs = None
    if not (isinstance(xs, list) and all(
            isinstance(x, dict) and isinstance(x.get("lanes"), list) and isinstance(x.get("open"), list)
            and all(isinstance(s, str) for s in x["lanes"] + x["open"]) for x in xs)):
        raise ValueError('cuts 要写成 JSON：[{"lanes": [列 id…], "open": [展开的目录…]}…]')
    return {lid: sorted(_cut.norm_open(idx, x["open"])) for x in xs for lid in x["lanes"]}


def decorate(idx: dict, hot: dict | None, L: dict, base) -> dict:
    """lanes.build 的结果 L 补上 info / more / place，每列补上 names / frames（见模块说明）；改的就是 L，也返回它。
    base 是共用的切面（None 是默认切面）"""
    lanes = L["lanes"]
    maps: dict = {}
    aliases: dict = {}

    def map_of(open_: list):
        k = ",".join(open_)
        if k not in maps:
            maps[k] = _seq.cut_map(idx, open_)
        return maps[k]

    def alias_of(open_: list) -> dict:
        """这个切面上撞了名的：补过父目录段的名字，同模块图在这个切面上的写法（graphview.cut_alias）"""
        k = ",".join(open_)
        if k not in aliases:
            aliases[k] = _graphview.cut_alias(idx, map_of(open_).v)
        return aliases[k]

    # 每个节点 id 落在哪个切面上（列的节点、连线那一头的节点都在它那一列的切面上）。节点信息只看 id，取第一个
    home: dict[str, list] = {}
    for ln in lanes:
        for n in ln["nodes"]:
            home.setdefault(n, ln["open"])
    lane_by = {ln["id"]: ln for ln in lanes}
    for x in L["links"]:
        for e in (x["from"], x["to"]):
            if e["node"] is not None and e["lane"] in lane_by:
                home.setdefault(e["node"], lane_by[e["lane"]]["open"])
    nodes = {n: map_of(o).v["nodes"][n] for n, o in home.items()}
    lane_frames = {ln["id"]: _graphview.frame_tree(idx, {n: nodes[n]["parent"] for n in ln["nodes"]}, ln["nodes"])[1]
                   for ln in lanes}
    frame_of = _graphview.frame_tree(idx, {n: x["parent"] for n, x in nodes.items()}, ())[0]
    shown: dict[str, dict] = {}                  # 各列画出来的框（同一个框在几列里，取第一个：只用它的 kind / label / parent）
    fhome: dict[str, list] = {}                  # 框 → 画它的（第一）列的切面
    for ln in lanes:
        for f, x in lane_frames[ln["id"]].items():
            shown.setdefault(f, x)
            fhome.setdefault(f, ln["open"])
    # 面板、搜索栏写的短名：撞名按它所在的那一列的切面算，同模块图在那个切面上的写法
    short = {n: _graphview.short_names(idx, (n,), alias_of(o))[0][n] for n, o in {**fhome, **home}.items()}
    packages = (hot or {}).get("packages") or {}

    def hits(n: str) -> int:
        return sum(packages.get(u, 0) for u in _cut.units_of(idx, n))

    info: dict[str, dict] = {}
    for n, x in nodes.items():
        info[n] = {**x, "frame": frame_of[n], "collapsible": frame_of[n] is not None, "hits": hits(n), "name": short[n]}
    for f, x in shown.items():
        if f not in info:
            info[f] = {"kind": x["kind"], "label": x["label"], "sep": x["sep"], "frame": x["parent"],
                       "collapsible": x["parent"] is not None, "hits": hits(f), "name": short[f]}
    bm = _seq.cut_map(idx, base)
    L["info"] = info
    L["more"] = _more(idx, lanes, map_of, bm.v["nodes"])
    L["place"] = _place(idx, hot, L, {n: map_of(o).v["members"][n] for n, o in home.items()}, bm.node_of)
    pre = _cut.root_label(idx)
    for ln in lanes:
        fs = lane_frames[ln["id"]]
        alias = alias_of(ln["open"])
        names = {n: _layout.name_in(info, alias, pre, n, info[n]["frame"] if info[n]["frame"] in fs else None)
                 for n in ln["nodes"]}
        names.update((f, _layout.name_in(info, alias, pre, f, x["parent"])) for f, x in fs.items())
        ln["thread_names"] = ln.pop("names")     # lanes.build 的 names 是合进来的线程原名：挪开，names 换成图上的名字
        ln["names"] = names
        ln["frames"] = {f: {"parent": x["parent"], "n": x["n"], "minw": round(_layout.head_w(names[f], f"· {x['n']}"), 1),
                            "label": names[f]} for f, x in fs.items()}
    return L


def _more(idx: dict, lanes: list, map_of, base_nodes: dict) -> dict:
    """不是 base 节点的那些列节点：{id: {"syms", "files", "docs"}}（graphview.node_details，按各自那一列的切面算）"""
    todo: dict[str, list] = {}                   # 切面的键 → 要算的节点
    cut_of: dict[str, list] = {}
    seen: set = set()
    for ln in lanes:
        k = ",".join(ln["open"])
        cut_of[k] = ln["open"]
        for n in ln["nodes"]:
            if n not in base_nodes and n not in seen:
                seen.add(n)
                todo.setdefault(k, []).append(n)
    out: dict[str, dict] = {}
    for k, ids in todo.items():
        syms, files, docs = _graphview.node_details(idx, set(cut_of[k]), map_of(cut_of[k]).v, ids)
        for n in ids:
            out[n] = {"syms": syms.get(n, []), "files": files.get(n, []), "docs": docs.get(n, [])}
    return out


_WRAP = 5        # 同一层的子模块一行最多放几个，多的排进下一个子行
_SUBROW = 1000   # 子行的编号：层 × _SUBROW + 这一层里的第几行


def _place(idx: dict, hot: dict | None, L: dict, members: dict, base_of: dict) -> dict:
    """比 base 细的列节点 → [base 里装着它的节点 B, 在 B 底下的第几个子行]（见模块说明；子行 = 层 × _SUBROW + 折行后的第几行）。
    members：节点 → 它里面的单元（它那一列的切面上的）；base_of：单元 → base 的节点"""
    ran = set(L.get("units") or [])             # 这一段里各列调到的单元：和切面无关
    ids = {n for ln in L["lanes"] for n in ln["nodes"]}
    want: dict[str, tuple] = {}                  # 节点 → (B, 它调到的单元)
    for n in sorted(ids):
        us = [u for u in members[n] if u in ran]
        b = base_of.get(us[0]) if us else None
        if b is not None and b != n and _inside(idx, n, b):
            want[n] = (b, us)
    if not want:
        return {}
    # B 里调到的单元之间的 import（静态边）和这一段的调用：每个 B 只分一次层
    bs = {b for b, _ in want.values()}
    st: dict[str, list] = {}
    for a, c, w in idx.get("edges") or []:
        if a != c and a in ran and c in ran and base_of.get(a) == base_of.get(c) and base_of.get(a) in bs:
            st.setdefault(base_of[a], []).append((a, c, w))
    calls: dict[tuple, int] = {}
    for x in ((hot or {}).get("calls") or {}).values():
        a, c = x.get("a"), x.get("b")
        if a != c and a in ran and c in ran and base_of.get(a) == base_of.get(c) and base_of.get(a) in bs:
            calls[(a, c)] = calls.get((a, c), 0) + x["n"]
    rt: dict[str, list] = {}
    for (a, c), k in sorted(calls.items()):
        rt.setdefault(base_of[a], []).append((a, c, k))
    lay: dict[str, dict] = {}
    for b in bs:
        lay[b] = _layout.weighted_layers({u for u in ran if base_of.get(u) == b}, st.get(b, []), rt.get(b, []))
    # 同一层的子模块太多时折行（同模块图排版折行）：B 底下同一深度、同一层的，按 id 排名次，每 WRAP 个占一个子行。
    # 名次在「这一段里调到的单元往上到 B 的每一级」里算——和哪一列展开了什么、画了哪些兄弟节点无关
    peers: dict[tuple, dict] = {}                # (B, 深度, 层) → {id: 1}
    for u in sorted(ran):
        b = base_of.get(u)
        if b not in lay:
            continue
        chain, x = [], u
        while x is not None and x != b:
            chain.append(x)
            x = _cut.parent_of(idx, x)
        if x != b:
            continue
        lo = lay[b][u]
        for i, x in enumerate(reversed(chain)):   # 从 B 往下数第 i + 1 级
            low = min(lo, peers.get(("lay", b, x), lo))
            peers[("lay", b, x)] = low
            peers.setdefault(("dep", b, x), i + 1)
    groups: dict[tuple, list] = {}
    for k, v in peers.items():
        if k[0] == "lay":
            groups.setdefault((k[1], peers[("dep", k[1], k[2])], v), []).append(k[2])
    rank = {(b, x): i for (b, _, _), xs in groups.items() for i, x in enumerate(sorted(xs))}
    out: dict[str, list] = {}
    for n, (b, us) in want.items():
        layer = min(lay[b][u] for u in us)
        out[n] = [b, layer * _SUBROW + rank.get((b, n), 0) // _WRAP]
    return out


def _inside(idx: dict, n: str, b: str) -> bool:
    """n 在 b 里面：b 是 n 往上（cut.parent_of）的某一层，b 自己不算"""
    p = _cut.parent_of(idx, n)
    while p is not None:
        if p == b:
            return True
        p = _cut.parent_of(idx, p)
    return False
