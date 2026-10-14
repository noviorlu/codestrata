"""分列默认收起哪几列（转一手的列收进每个进程的「其他 N 列」窄列，线照连）。一句话的规则，只看分列自己的数据：

不是主线程（也不是代表整个子进程的那一列），而且——只跑仓库外的代码（收发 socket 这类），或者是线程池（同名的线程 POOL 条以上），
或者只在 FEW_FILES 个以内的文件里转（收了就转手、轮询、反复清理这类）。
很小的程序里每条线程都只碰一两个文件，会收得多；页面上点「全部显示」或者点窄列展开。
"""
from __future__ import annotations

POOL = 4
FEW_FILES = 2


def _why(ln: dict) -> str | None:
    """这一列为什么默认收起（大白话）；不收是 None"""
    if ln.get("thread") == "MainThread" or ln.get("proc_main"):
        return None
    if ln.get("external"):
        return "只跑仓库外的代码（收发 socket 这类）"
    if (ln.get("n_threads") or 1) >= POOL:
        return "线程池（同名的线程很多）"
    if len(ln.get("u") or ()) <= FEW_FILES:
        return f"只在 {FEW_FILES} 个以内的文件里转（转手、轮询这类）"
    return None


def default_folded(L: dict) -> dict[str, str]:
    """默认收起的列 → 为什么收；全要收、或者一列都不收时是空的（看全部列）"""
    why = {ln["id"]: w for ln in L["lanes"] if (w := _why(ln))}
    return why if 0 < len(why) < len(L["lanes"]) else {}


def default_lanes(L: dict) -> list[str] | None:
    """默认看的列（列 id，按画的先后）；不收时 None（看全部列）"""
    f = default_folded(L)
    return [ln["id"] for ln in L["lanes"] if ln["id"] not in f] if f else None
