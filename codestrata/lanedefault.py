"""分列默认看哪几列（用户 10-10 定）：转一手的列默认收进每个进程的「其他 N 列」窄列，线照连——和地址里写 lanes= 只看几列是同一个样子。

转一手的列：
    收发 socket 的  只在交接两头出现（没录到它调仓库函数，external），或者这一段里又收又交、只调了 FEW_FNS 个以内的仓库函数；
    只在轮询的      有主循环、这一段里每一轮都是空转（poll），而且只调了 FEW_FNS 个以内的仓库函数（主线程整段看也可能每轮都像空转，
                    但它调了很多别的，不算）；没认出主循环、不在交接链上（这一段里没收也没交）、只是反复调同一两个函数的（调用全在折叠行里，
                    见 segments.lane_kinds 的 repeat：save_loop 隔 100 ms 清一次共享内存）也算（用户 10-13 定）；
    线程池          同名的线程很多、没有主循环（threads）；
    这一段里没有调用的（quiet）：画着它只是因为起 / 收它的那条线、或者一个从这段之前就在跑的调用（折叠行按次数摊开算，摊进这段的算有调用）。
种类和 segments 同一份（segments.stages 的 kinds）；切段靠不住（老 run、这一段一次交接都没录到）时不收。
地址里写了 lanes= 照写的来，lanes=* 是全部。页面、/api/laneorder 的编号、命令行的 explain N 都按这一份算。
"""
from __future__ import annotations

FEW_FNS = 3


def folded(S: dict | None) -> set[str]:
    """默认收起的列 id（S：segments.stages 的结果；None 时不收）"""
    return set(reasons(S))


def reasons(S: dict | None) -> dict[str, str]:
    """默认收起的列 → 为什么收（页面的窄列悬停时一列一列写出来）"""
    if not S:
        return {}
    out = {}
    for lid, k in S["kinds"].items():
        why = _relay(k)
        if why:
            out[lid] = why
    return out


def _relay(k: dict) -> str | None:
    """转一手的列：为什么（大白话）；不是是 None"""
    few = k["fns"] <= FEW_FNS
    if k["kind"] == "external":
        return "只在交接两头出现（收发 socket）"
    if k["kind"] == "threads":
        return "线程池（同名的线程很多、没有主循环）"
    if k["kind"] == "quiet":
        return "这一段里没有调用"
    if k["kind"] == "poll" and few:
        return "只在轮询（每轮空转）"
    if k["kind"] == "few" and k.get("repeat") and not k["in"] and not k["out"] and few:    # 收了数据再反复处理的不算：它在链上
        return "只在反复调同一两个函数"
    if k["kind"] == "few" and k["in"] and k["out"] and few:
        return "又收又交、只调了几个函数（转一手）"
    return None


def default_folded(L: dict, S: dict | None) -> dict[str, str]:
    """画着的列里默认收起的 → 为什么收；default_lanes 是 None（不收）时是空的"""
    if default_lanes(L, S) is None:
        return {}
    why = reasons(S)
    return {ln["id"]: why[ln["id"]] for ln in L["lanes"] if ln["id"] in why}


def default_lanes(L: dict, S: dict | None) -> list[str] | None:
    """画着的列里默认看的那些（列 id，按画的先后）；没有要收的、或者全要收时 None（看全部列）"""
    f = folded(S)
    keep = [ln["id"] for ln in L["lanes"] if ln["id"] not in f]
    return keep if keep and len(keep) < len(L["lanes"]) else None
