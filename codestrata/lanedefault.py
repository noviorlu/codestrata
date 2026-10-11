"""分列默认看哪几列（用户 10-10 定）：转一手的列默认收进每个进程的「其他 N 列」窄列，线照连——和地址里写 lanes= 只看几列是同一个样子。

转一手的列：
    收发 socket 的  只在交接两头出现（没录到它调仓库函数，external），或者这一段里又收又交、只调了 FEW_FNS 个以内的仓库函数；
    只在轮询的      有主循环、这一段里每一轮都是空转（poll），而且只调了 FEW_FNS 个以内的仓库函数（主线程整段看也可能每轮都像空转，
                    但它调了很多别的，不算）；
    线程池          同名的线程很多、没有主循环（threads）；
    这一段里没有调用的（quiet）：画着它只是因为起 / 收它的那条线、或者一个从这段之前就在跑的调用。
种类和 segments 同一份（segments.stages 的 kinds）；切段靠不住（老 run、这一段一次交接都没录到）时不收。
地址里写了 lanes= 照写的来，lanes=* 是全部。页面、/api/laneorder 的编号、命令行的 explain N 都按这一份算。
"""
from __future__ import annotations

FEW_FNS = 3


def folded(S: dict | None) -> set[str]:
    """默认收起的列 id（S：segments.stages 的结果；None 时不收）"""
    if not S:
        return set()
    return {lid for lid, k in S["kinds"].items() if _relay(k)}


def _relay(k: dict) -> bool:
    if k["kind"] in ("external", "threads", "quiet"):
        return True
    if k["kind"] == "poll":
        return k["fns"] <= FEW_FNS
    return k["kind"] == "few" and bool(k["in"] and k["out"]) and k["fns"] <= FEW_FNS


def default_lanes(L: dict, S: dict | None) -> list[str] | None:
    """画着的列里默认看的那些（列 id，按画的先后）；没有要收的、或者全要收时 None（看全部列）"""
    f = folded(S)
    keep = [ln["id"] for ln in L["lanes"] if ln["id"] not in f]
    return keep if keep and len(keep) < len(L["lanes"]) else None
