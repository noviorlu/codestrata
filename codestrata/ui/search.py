"""搜索栏的名字表（给 /api/search-index），让一个模块在图上露出来（给 /api/reveal）。"""
from __future__ import annotations

from .. import cut as _cut


def search_index(idx: dict) -> dict:
    """右边搜索栏要的全部名字，前端自己搜：
      mods   [[id, 种类 dir / unit, 文件数, 显示名, 分隔符], ...]   目录树上的每个目录和每个单元
      files  [路径, ...]                               单元的文件和包里的 C++ / CUDA 文件
      units  [所属单元, ...]                           和 files 对齐（C++ 文件是空串）
      syms   [[限定名, 种类首字母 c / f, 文件下标, 行], ...]   类、函数、方法
    符号不存完整的键（路径重复两万多遍）：键 = files[文件下标] + "#" + 限定名。"""
    tree = idx.get("dirs") or {}

    def mod(x: str, kind: str, n: int) -> list:
        segs, sep = _cut.label(idx, x)
        return [x, kind, n, sep.join(segs), sep]
    mods = [mod(d, "dir", len(_cut.units_of(idx, d))) for d in sorted(tree)]
    mods += [mod(u, "unit", v["files"]) for u, v in sorted((idx.get("packages") or {}).items())]
    unit_of = idx.get("files") or {}
    files = sorted(set(unit_of) | set(idx.get("aux") or {}))
    at = {f: i for i, f in enumerate(files)}
    syms = [[s["n"], s["k"][0], at[s["f"]], s["l"]] for _, s in sorted((idx.get("symbols") or {}).items())
            if s["f"] in at]
    return {"mods": mods, "files": files, "units": [unit_of.get(f, "") for f in files], "syms": syms}


def reveal(idx: dict, node: str, open_) -> list[str] | None:
    """让一个模块在图上露出来要展开哪些目录（在当前切面的基础上）。"""
    if not _cut.is_node(idx, node):
        return None
    if _cut.is_virtual(node):                # 「GPU · 仓库外」不在任何目录里，跑到了就画着：切面不用动
        return sorted(_cut.norm_open(idx, open_))
    return sorted(_cut.open_for(idx, _cut.norm_open(idx, open_), node))
