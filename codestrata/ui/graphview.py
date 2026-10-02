"""一个切面上的图：节点、边、框、排版、叠加（给 /api/graph）。"""
from __future__ import annotations

from pathlib import Path

from .. import align as _align
from .. import cut as _cut
from .. import layout as _layout


def _unit_syms(idx: dict) -> dict:
    """顶层类 / 函数按单元分组（方法太多，只在文件树展开时按需取）。"""
    if "_unit_syms" not in idx:
        out: dict[str, list] = {}
        for key, s in (idx.get("symbols") or {}).items():
            if "." in s["n"]:
                continue
            out.setdefault(s["p"], []).append(
                {"key": key, "n": s["n"], "k": s["k"], "f": s["f"], "l": s["l"], "b": s.get("b", [])})
        idx["_unit_syms"] = out
    return idx["_unit_syms"]


def frame_tree(idx: dict, parents: dict, counted) -> tuple[dict, dict]:
    """框：每个节点被哪个展开着的目录（或展开着的本层文件）直接套着，一路往上。只有一个根时不画根的框——它就是整张图。
    parents：{节点: 它的 parent（cut.parent_of，cut.view 的节点上有）}；counted：框头上数的是哪些节点（画得出来的）。
    返回 ({节点: 直接套着它的框，没有是 None}, {框: {"parent", "kind", "n": 框里一共几个 counted, "label", "sep"}})"""
    roots = _cut.roots_of(idx)
    top = roots[0] if len(roots) == 1 else None
    frame_of: dict[str, str | None] = {}
    frames: dict[str, dict] = {}
    for n, p in parents.items():
        f = p if p != top else None
        frame_of[n] = f
        while f and f not in frames:
            pp = _cut.parent_of(idx, f)
            segs, sep = _cut.label(idx, f)
            frames[f] = {"parent": pp if pp != top else None, "kind": _cut.kind(idx, f), "n": 0,
                         "label": sep.join(segs), "sep": sep}
            f = frames[f]["parent"]
    for n in counted:
        f = frame_of[n]
        while f:
            frames[f]["n"] += 1
            f = frames[f]["parent"]
    return frame_of, frames


def node_details(idx: dict, open_: set, v: dict, ids=None) -> tuple[dict, dict, dict]:
    """切面（open_，cut.view 的结果 v）上每个节点的 (顶层类 / 函数, 文件, 文档)：面板的符号、文件树、文档。
    文件含挂在目录上的（C/C++ 文件、目录里的 README）。ids 给了就只要这几个节点的"""
    mem, node_of = v["members"], v["node_of"]
    want = None if ids is None else set(ids)
    usyms = _unit_syms(idx)
    pkg_files: dict[str, list] = {}
    pkg_syms: dict[str, list] = {}
    for rel, u in (idx.get("files") or {}).items():
        if want is None or node_of[u] in want:
            pkg_files.setdefault(node_of[u], []).append(rel)
    for rel, d in (idx.get("aux") or {}).items():
        n = _cut.dir_node(idx, open_, d)
        if n and (want is None or n in want):
            pkg_files.setdefault(n, []).append(rel)
    for n, us in mem.items():
        if want is not None and n not in want:
            continue
        syms = [x for u in us for x in usyms.get(u, [])]
        syms.sort(key=lambda d: (d["k"] != "class", d["f"], d["l"]))
        pkg_syms[n] = syms
    for fs in pkg_files.values():
        fs.sort()
    pkg_docs: dict[str, list] = {}
    for key, ds in (idx.get("docs") or {}).items():
        n = node_of.get(key) or _cut.dir_node(idx, open_, key)
        if n and (want is None or n in want):
            have = {d["f"] for d in pkg_docs.get(n, [])}
            pkg_docs.setdefault(n, []).extend(d for d in ds if d["f"] not in have)
    return pkg_syms, pkg_files, pkg_docs


def short_names(idx: dict, ids, alias: dict) -> tuple[dict, dict]:
    """面板、搜索栏写的短名（不带框的相对部分）：撞了名的用补过父目录段的（alias，cut.disambiguate），其余是显示名的最后一段；
    还有完整的显示名（标题用：vllm_omni.engine.core）。返回 ({id: 短名}, {id: 完整的显示名})"""
    names, labels = {}, {}
    for n in ids:
        own = _cut.residual_base(n) if _cut.is_residual(n) else n
        names[n] = alias.get(own) or _cut.short(idx, own)
        segs, sep = _cut.label(idx, own)
        labels[n] = sep.join(segs)
    return names, labels


def cut_alias(idx: dict, v: dict, frames: dict | None = None) -> dict:
    """同一个切面上短名撞了的（flask.app 和 flask.sansio.app 都叫 app）：补上父目录段，图上和面板里一样（cut.disambiguate）。
    按切面（cut.view 的结果 v）上画得出来的节点和全部的框算，不看 hot 视图、分列的一列只画了其中哪些——名字只跟着切面走。
    frames：这个切面的框（frame_tree 的第二项），不给就现算"""
    if frames is None:
        frames = frame_tree(idx, {n: x["parent"] for n, x in v["nodes"].items()}, ())[1]
    return _cut.disambiguate(idx, set(_cut.visible(v)) | set(frames))


def graph_payload(repo: Path, idx: dict, *, hot: dict | None = None,
                  hot_meta: dict | None = None, open_=None, min_files: int = 1,
                  width: float = 1180.0) -> dict:
    """一个切面上的全部前端数据。open_ 是展开着的目录（不给就用 scan 算出的默认切面）；
    图、边的种类、hot 叠加、每个节点的文件 / 符号 / 文档，都按这个切面汇总。
    width：页面上图框有多宽——按它排版，宽屏上图铺满、少折行，而不是把 1180 宽的图放大"""
    open_ = _cut.norm_open(idx, open_)
    v = _cut.view(idx, open_)
    # 框（frame_tree）：框头上数的是框里画得出来的节点（hot 视图只画一部分）
    frame_of, frames = frame_tree(idx, {n: x["parent"] for n, x in v["nodes"].items()}, _cut.visible(v))
    for n, x in v["nodes"].items():
        x["frame"] = frame_of[n]
        x["collapsible"] = frame_of[n] is not None
    alias = cut_alias(idx, v, frames)
    syn = {"repo": idx["repo"], "packages": v["nodes"], "edges": v["edges"], "frames": frames, "alias": alias,
           "root_label": _cut.root_label(idx)}
    # 分层（纵轴）：import 关系只当排版的权重（图上不画）；叠了 run 再按这次实际发生的调用排，调用方在上——
    # 基类回调子类、注册表、回调这些调用和 import 的方向是反的
    hp, he, hd = _align.hot_on_cut(hot, v["node_of"]) if hot else ({}, {}, {})
    rt_calls = he
    g = _layout.build(syn, min_files=min_files, width=width,
                      runtime_edges=[(*k.split("|"), n) for k, n in sorted(rt_calls.items())])
    node_of = v["node_of"]
    repo_info = dict(idx["repo"])
    repo_info["n_symbols"] = len(idx.get("symbols") or {})
    repo_info["n_units"] = len(idx["packages"])
    pkg_syms, pkg_files, pkg_docs = node_details(idx, open_, v)
    # 图上的边只有调用：scan 边（代码里写了、定下了被调方的调用，graph.json）和这次 trace 到的调用。
    # 边的第三项：切面上这条 scan 边底下有几处调用
    kinds = _align.scan_edges_on_cut(idx, node_of)
    shown = {n["id"] for n in g["nodes"]}
    g["edges"] = [[*k.split("|"), w] for k, w in sorted(kinds.items()) if set(k.split("|")) <= shown]
    # 这次跑了、scan 里却没有边的节点间调用（插件、注册表、回调、self.model 这类）：单独给出来，前端照样画
    hot_view, rt_only = None, []
    if hot:
        hot_view = {**{k: v for k, v in hot.items() if k not in ("calls", "redirect", "keymap")},
                    "packages": hp, "edges": he, "dyn": hd}
        rt_only = [[*k.split("|"), n] for k, n in sorted(he.items())
                   if k not in kinds and set(k.split("|")) <= shown]
    # hot 视图单独排版：只放跑到的节点，每个节点的层沿用总图，纵坐标含义不变、横向更紧凑
    # 「跑到的」节点：这一段里有函数被调用进去的，加上这一段里任何一条 runtime 边（只有 trace 的也算）的两端。
    # 调用方不一定有「被调用」的次数：一直在跑的外层函数（case 脚本的 main 在上一个阶段就进去了）、
    # import 时执行的模块顶层（定义，不算调用）——少了它们，边就没有起点
    ran = ({p for p, n in hot_view["packages"].items() if n}
           | {x for k in hot_view["edges"] for x in k.split("|")}) if hot_view else set()
    g_hot = (_layout.build(syn, lane_of={n["id"]: n["lane"] for n in g["nodes"]},
                           lane_labels={r["i"]: r["label"] for r in g["lane_rows"]}, min_files=min_files, width=width,
                           only=ran)
             if hot_view else None)
    if g_hot:
        on = {n["id"] for n in g_hot["nodes"]}
        g_hot["edges"] = [e for e in g["edges"] if e[0] in on and e[1] in on]
    for nd in (g["nodes"] + (g_hot["nodes"] if g_hot else [])):   # 前端要知道哪些节点能展开、收起到哪里
        x = v["nodes"][nd["id"]]
        nd.update(kind=x["kind"], expandable=x["expandable"], parent=x["parent"],
                  collapsible=x["collapsible"], fanout=x["fanout"], units=x["units"])
    # 阶段从哪个函数开始（trace --phase）：落在这个切面的哪个节点上，前端据此标出阶段的起点 / 终点
    files = idx.get("files") or {}
    phase_marks = [{**{k: t.get(k) for k in ("name", "func", "qualname", "file", "line")},
                    "node": v["node_of"].get(files.get(t.get("file")))}
                   for t in (hot_meta or {}).get("phase_at") or []]
    # 面板、搜索栏写的短名，和完整的显示名（标题用）
    names, labels = short_names(idx, set(v["nodes"]) | set(frames), alias)
    return {"repo": repo_info, "graph": g, "graphHot": g_hot, "pkgs": v["nodes"], "names": names, "labels": labels,
            "rootLabel": _cut.sep_join(idx, _cut.root_label(idx)),
            "pkgSyms": pkg_syms, "pkgFiles": pkg_files, "pkgDocs": pkg_docs,
            "fileLoc": idx.get("file_loc") or {},
            "alias": alias, "runtimeOnlyEdges": rt_only,
            "hot": hot_view, "hotMeta": hot_meta, "phaseMarks": phase_marks,
            "open": sorted(open_), "defaultOpen": idx.get("default_open") or [],
            "autoSplit": idx["repo"].get("auto_split") or []}
