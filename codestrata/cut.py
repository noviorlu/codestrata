"""图上显示的是目录树的一个「切面」。

scan 记下的是最细的粒度：每个源文件是一个单元，依赖边、符号、调用明细都在单元之间。
图上不可能把 1608 个文件都画出来，所以显示的是目录树的一个切面——哪些目录展开、哪些收起：

  - 收起的目录是一个节点，代表整棵子树；
  - 展开的目录不再是节点，换成它的孩子：每个子目录一个节点；直接放在它下面的文件，
    不多（≤ FILE_LIMIT）时各自是一个节点，多时合成一个「本层文件」节点，
    这个节点还可以再展开到文件。

id 按路径写，不认语言：
  - 单元：文件相对仓库根的路径（vllm_omni/engine/core.py、src/decode/runtime.cu）；
  - 目录：路径加 /（vllm_omni/engine/）；仓库根目录直接放着的脚本所在的目录是 ROOT_DIR（./）；
  - 本层文件：<目录>*（vllm_omni/engine/*）。
显示名不从 id 拆：每个单元和目录带 label 和 sep（label 按 sep 切开是一段段的显示名），由扫描端给——
Python 是点分的模块名（vllm_omni.engine.core，sep 是 .），别的语言是路径（src/decode/runtime.cu，sep 是 /）。

open 集合（展开的目录和展开的本层文件节点）就是切面的全部状态。图上点「展开 / 收起」就是
改 open、重新汇总、重新排版。默认的 open 由 default_open 按规模自动算出来：固定深度不适合
大小悬殊的仓库——vllm-omni 里 version 只有 1 个文件，diffusion 有 580 个。
"""
from __future__ import annotations

FILE_LIMIT = 12      # 展开一个目录时，直接文件不超过这么多就各自成节点，否则合成「本层文件」
SPLIT_FRAC = 0.10    # 自动拆分：代码量超过全仓这个比例的节点才拆
MAX_CHILDREN = 30    # 自动拆分：拆开后会变成超过这么多个节点的不拆（宽而平，通常是一族同类实现）。
                     # 20 会把宽的核心也挡住（vllm 的 v1 24 个、pip 的 _internal 22 个、pydantic 的 _internal 29 个），
                     # 模型 / 插件这类同类实现通常是几十上百个；不设上限又会先拆它们
MAX_NODES = 80       # 自动拆分：图上节点数的上限
MIN_NODES = 4        # 小仓库：节点少于这个数时，不看比例，先把最大的拆开

ROOT_DIR = "./"      # 仓库根目录直接放着的脚本（scan --roots .）所在的目录
INDEX_FORMAT = 4     # 索引里 id 的写法：单元、目录按路径（本模块），符号键是 <路径>#<限定名>；旧的读到了要重新 scan


# ---------------------------------------------------------------- id 的写法

def unit_dir(unit: str) -> str:
    """单元所在的目录。"""
    i = unit.rfind("/")
    return unit[:i + 1] if i >= 0 else ROOT_DIR


def root_dir(root: str) -> str:
    """scan 的一个扫描根（相对仓库根的目录，`.` 是根目录的脚本）→ 它在目录树上的 id。"""
    return ROOT_DIR if root in (".", "") else root.strip("/") + "/"


def residual(d: str) -> str:
    return d + "*"


def is_residual(node: str) -> bool:
    return node.endswith("/*")


def residual_base(node: str) -> str:
    """本层文件节点 → 它的目录。"""
    return node[:-1]


def within(x: str, d: str) -> bool:
    """id x（目录、本层文件、单元）在目录 d 的子树里（不含 d 自己）。"""
    if d == ROOT_DIR:                      # 根目录的脚本：只装直接放着的文件，不装别的扫描根
        return x != d and (x == residual(d) or "/" not in x)
    return x != d and x.startswith(d)


# ---------------------------------------------------------------- 显示名

def label(index: dict, node: str) -> tuple[list[str], str]:
    """节点的显示段和分隔符：(["vllm_omni", "engine"], ".")。本层文件用它目录的。
    扫描端没给的，按路径切。"""
    base = residual_base(node) if is_residual(node) else node
    x = (index.get("dirs") or {}).get(base) or (index.get("packages") or {}).get(base) or {}
    if x.get("label"):
        sep = x.get("sep") or "/"
        return x["label"].split(sep), sep
    return [p for p in base.split("/") if p and p != "."] or [base], "/"


def sep_join(index: dict, segs: list[str]) -> str:
    """root_label 这类显示段拼回一个字符串（用根目录的分隔符）。"""
    roots = roots_of(index)
    return (label(index, roots[0])[1] if roots else "/").join(segs)


def short(index: dict, node: str) -> str:
    """最后一段：engine、core、runtime.cu。"""
    return label(index, node)[0][-1]


def find_dir(index: dict, text: str) -> str | None:
    """命令行里写的目录（vllm_omni/engine、vllm_omni/engine/ 或点分的 vllm_omni.engine）→ 目录 id。"""
    tree = index.get("dirs") or {}
    for cand in (text, text.rstrip("/") + "/"):
        if cand in tree:
            return cand
    for d in tree:
        segs, sep = label(index, d)
        if sep.join(segs) == text:
            return d
    return None


# ---------------------------------------------------------------- 目录树

def dir_tree(units: dict, roots: list[str]) -> dict:
    """{目录: {"parent", "dirs": [子目录], "units": [直接放在里面的单元], "label", "sep"}}。

    目录的显示名从单元的推：去掉单元显示名的最后一段（Python 的 vllm_omni.engine.core → vllm_omni.engine，
    包的 __init__ 单元是 vllm_omni.engine.__init__ → 同一个目录）；再往上的目录每层去掉一段。"""
    tops = {root_dir(r) for r in roots}
    tree: dict[str, dict] = {}

    def parent_of_dir(d: str) -> str | None:
        if d in tops or d == ROOT_DIR:
            return None
        inner = d.rstrip("/")
        return unit_dir(inner) if "/" in inner else None

    def ensure(d: str, lab: list[str] | None, sep: str) -> dict:
        if d not in tree:
            parent = parent_of_dir(d)
            tree[d] = {"parent": parent, "dirs": [], "units": []}
            if lab:
                tree[d]["label"], tree[d]["sep"] = sep.join(lab), sep
            if parent:
                ensure(parent, lab[:-1] if lab and len(lab) > 1 else None, sep)
                tree[parent]["dirs"].append(d)
        elif lab and "label" not in tree[d]:
            tree[d]["label"], tree[d]["sep"] = sep.join(lab), sep
        return tree[d]

    for u in sorted(units):
        v = units[u] if isinstance(units, dict) else {}
        sep = v.get("sep") or "/"
        lab = v["label"].split(sep)[:-1] if v.get("label") else None
        ensure(unit_dir(u), lab or None, sep)["units"].append(u)
    for v in tree.values():
        v["dirs"].sort()
    return tree


def roots_of(index: dict) -> list[str]:
    tree = index.get("dirs") or {}
    return sorted(d for d, v in tree.items() if not v["parent"])


def node_of(index: dict, open_: set, unit: str) -> str:
    """一个单元在这个切面上落在哪个节点。"""
    tree = index["dirs"]
    d = unit_dir(unit)
    chain = [d]
    while tree[chain[-1]]["parent"]:
        chain.append(tree[chain[-1]]["parent"])
    for x in reversed(chain):              # 从根往下，第一个收起的目录就是它的节点
        if x not in open_:
            return x
    return unit if _files_individually(tree, d, open_) else residual(d)


def _files_individually(tree: dict, d: str, open_: set) -> bool:
    """展开的目录 d 里，直接文件是各自成节点，还是合成「本层文件」。没有子目录的目录
    直接摊开到文件——否则展开它只会变出一个「本层文件」节点，等于没展开。"""
    return (len(tree[d]["units"]) <= FILE_LIMIT or not tree[d]["dirs"] or residual(d) in open_)


def members(index: dict, open_: set) -> dict[str, list]:
    """切面上每个节点包含哪些单元。"""
    out: dict[str, list] = {}
    for u in index["packages"]:
        out.setdefault(node_of(index, open_, u), []).append(u)
    return out


def kind(index: dict, node: str) -> str:
    if is_residual(node):
        return "residual"
    return "dir" if node in index["dirs"] else "unit"


def is_node(index: dict, node: str) -> bool:
    return node in index.get("packages", {}) or node in index.get("dirs", {}) \
        or (is_residual(node) and residual_base(node) in index.get("dirs", {}))


def units_of(index: dict, node: str) -> list[str]:
    """一个节点（不论当前切面）代表哪些单元：目录是整棵子树，本层文件是直接文件，单元是它自己。"""
    tree = index["dirs"]
    if is_residual(node):
        return list(tree[residual_base(node)]["units"])
    if node in tree:
        out, stack = [], [node]
        while stack:
            d = stack.pop()
            out += tree[d]["units"]
            stack += tree[d]["dirs"]
        return out
    return [node] if node in index["packages"] else []



def fanout(index: dict, node: str) -> int:
    """展开这个节点后，它会变成几个节点。"""
    tree = index["dirs"]
    if is_residual(node):
        return len(tree[residual_base(node)]["units"])
    if node in tree:
        n = len(tree[node]["units"])
        return len(tree[node]["dirs"]) + (n if _files_individually(tree, node, set()) else (1 if n else 0))
    return 0


def expandable(index: dict, node: str) -> bool:
    return fanout(index, node) > 1 or (node in index.get("dirs", {}) and fanout(index, node) == 1
                                         and bool(index["dirs"][node]["dirs"]))


def parent_of(index: dict, node: str) -> str | None:
    """收起这个节点时，要收起的是哪个展开着的目录（或本层文件节点）。"""
    if is_residual(node):
        return residual_base(node)
    tree = index["dirs"]
    if node in tree:
        return tree[node]["parent"]
    d = unit_dir(node)
    return d if _files_individually(tree, d, set()) else residual(d)


def view(index: dict, open_: set) -> dict:
    """在切面上汇总：节点（文件数、行数、类 / 函数数、出入边、高度）和节点间的边。"""
    mem = members(index, open_)
    of = {u: n for n, us in mem.items() for u in us}
    pk = index["packages"]
    nodes: dict[str, dict] = {}
    for n, us in mem.items():
        segs, sep = label(index, n)
        nodes[n] = {"files": sum(pk[u]["files"] for u in us), "loc": sum(pk[u]["loc"] for u in us),
                    "classes": sum(pk[u]["classes"] for u in us), "funcs": sum(pk[u]["funcs"] for u in us),
                    "out": 0, "in": 0, "alt": 0.0, "kind": kind(index, n), "units": len(us),
                    "expandable": expandable(index, n), "parent": parent_of(index, n),
                    "fanout": fanout(index, n), "label": sep.join(segs), "sep": sep}
    edges: dict[tuple[str, str], int] = {}
    for a, b, w in index.get("edges") or []:
        na, nb = of[a], of[b]
        if na != nb:
            edges[(na, nb)] = edges.get((na, nb), 0) + w
    for (a, b), w in edges.items():
        nodes[a]["out"] += w
        nodes[b]["in"] += w
    for v in nodes.values():
        o, i = v["out"], v["in"]
        v["alt"] = round((o - i) / (o + i), 4) if o + i else 0.0
    return {"nodes": nodes, "edges": [[a, b, w] for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1])],
            "members": mem, "node_of": of}


def root_label(index: dict) -> list[str]:
    """只有一个根时，它的显示段（图上的名字不再重复写它）；多个根时是空的。"""
    roots = roots_of(index)
    return label(index, roots[0])[0] if len(roots) == 1 else []


def disambiguate(index: dict, ids) -> dict[str, str]:
    """切面上短名（显示名的最后一段）撞了的节点 / 框：{id: 补上父目录段、在这一组里分得开的名字}。
    flask.app 和 flask.sansio.app 都叫 app → app、sansio.app；vllm 的 kernels 和 model_executor.kernels
    同理。没撞的不在结果里（照旧只写最后一段）。本层文件节点跟它的目录算一个名字；
    单根仓库的根包名不算一段。"""
    pre = root_label(index)

    def path(d: str) -> tuple[list[str], str]:
        segs, sep = label(index, d)
        if pre and segs[:len(pre)] == pre and len(segs) > len(pre):
            segs = segs[len(pre):]
        return segs, sep

    by: dict[str, list] = {}
    for d in {residual_base(n) if is_residual(n) else n for n in ids}:
        by.setdefault(path(d)[0][-1], []).append(d)
    out: dict[str, str] = {}
    for grp in by.values():
        if len(grp) < 2:
            continue
        k, top = 2, max(len(path(d)[0]) for d in grp)
        while k < top and len({tuple(path(d)[0][-k:]) for d in grp}) < len(grp):
            k += 1
        for d in grp:
            segs, sep = path(d)
            out[d] = sep.join(segs[-k:])
    return out


def visible(v: dict) -> list[str]:
    """切面上真正会画出来的节点：既没符号又没连边的（只有空 __init__.py 的目录）不画。"""
    return [n for n, x in v["nodes"].items()
            if not (x["out"] == 0 and x["in"] == 0 and x["classes"] == 0 and x["funcs"] == 0)]


def depth_of(index: dict, d: str) -> int:
    """目录在树上的深度：扫描根是 1。"""
    tree, n = index["dirs"], 1
    while tree[d]["parent"]:
        d, n = tree[d]["parent"], n + 1
    return n


def default_open(index: dict, depth: int | None = None, expand: list[str] | None = None) -> tuple[list, list]:
    """默认切面。返回 (open 列表, 自动拆分的记录)。

    给了 depth：展开所有深度小于它的目录（depth=2 就是老的「二级包」）。
    没给：从根目录开始，反复把「代码量超过全仓 SPLIT_FRAC、拆开后不超过 MAX_CHILDREN 个节点」
    里最大的那个拆开，直到没有可拆的或节点数到了 MAX_NODES。节点少于 MIN_NODES 的小仓库，
    先不看比例把最大的拆开。宽而平的（几十个同类子目录）留成一个节点——图上一下多出几十个
    节点没法读，它的内部结构交给详情面板的文件树。
    expand 里的目录可以写 id，也可以写点分的显示名（find_dir）。
    """
    tree = index["dirs"]
    open_ = set(roots_of(index))
    log: list[dict] = []
    if depth is not None:
        open_ |= {d for d in tree if depth_of(index, d) < depth}
    else:
        total = sum(v["loc"] for v in index["packages"].values()) or 1
        while True:
            v = view(index, open_)
            vis = visible(v)
            if len(vis) >= MAX_NODES:
                break
            cands = []
            for n in vis:
                x = v["nodes"][n]
                if not x["expandable"] or x["fanout"] > MAX_CHILDREN:
                    continue
                if x["loc"] > SPLIT_FRAC * total or len(vis) < MIN_NODES:
                    cands.append(n)
            if not cands:
                break
            n = max(cands, key=lambda c: v["nodes"][c]["loc"])
            trial = open_ | {n}
            if len(visible(view(index, trial))) > MAX_NODES:
                break
            open_ = trial
            log.append({"node": n, "share": round(v["nodes"][n]["loc"] / total, 3), "fanout": v["nodes"][n]["fanout"]})
    for e in expand or []:
        res = e.endswith("*") and not e.endswith("/*")
        d = find_dir(index, e[:-1].rstrip(".") if res else (residual_base(e) if is_residual(e) else e))
        if d is None:
            continue
        open_.add(residual(d) if (res or is_residual(e)) else d)
        p = tree[d]["parent"]
        while p:                           # 展开一个深处的目录，它的祖先也必须展开
            open_.add(p)
            p = tree[p]["parent"]
    return sorted(open_), log


def open_for(index: dict, open_: set, node: str) -> set:
    """让 node 在切面上可见所需的 open：它的祖先全部展开，它自己收起。"""
    tree = index["dirs"]
    out = set(open_)
    base = residual_base(node) if is_residual(node) else (node if node in tree else unit_dir(node))
    p = base if (is_residual(node) or node not in tree) else tree[base]["parent"]
    while p:
        out.add(p)
        p = tree[p]["parent"]
    if node in tree:
        out = {x for x in out if not (x == node or within(x, node))}
    elif not is_residual(node) and not _files_individually(tree, base, set()):
        out.add(residual(base))
    return out


def dir_node(index: dict, open_: set, d: str) -> str | None:
    """一个目录落在切面的哪个节点上（C/C++ 文件、目录里的 README 挂在那里）。
    目录本身展开着时，挂到它的「本层文件」节点，或它的 __init__.py 单元。"""
    tree = index["dirs"]
    if d not in tree:
        return None
    chain = [d]
    while tree[chain[-1]]["parent"]:
        chain.append(tree[chain[-1]]["parent"])
    for x in reversed(chain):
        if x not in open_:
            return x
    if not _files_individually(tree, d, open_):
        return residual(d)
    init = ("" if d == ROOT_DIR else d) + "__init__.py"
    if init in index["packages"]:
        return init
    return tree[d]["units"][0] if tree[d]["units"] else None


def norm_open(idx: dict, open_) -> set:
    """请求里给的切面：没给（None）就是默认切面；给了的只留认得的目录 / 本层文件节点"""
    return set(idx.get("default_open") or []) if open_ is None else {o for o in open_ if is_node(idx, o)}
