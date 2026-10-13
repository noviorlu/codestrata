"""分列的进程头上写「这个进程在干什么」（用户 10-10 定）：这段时间里只有它跑的那个文件、干活的时段、主循环几轮——和 segments
同一份切段（segments.stages：stage 段、请求、独有的文件）。持有请求的进程写请求。

    stage1 │ minicpmo_4_5_omni_tts.py · +0.61→+3.08 s · 250 轮

parts 按要紧的先后排：页面上进程头窄时从后往前丢，第一样（干什么）放不下时中间省略。
独有的文件只写第一名，而且至少 OWN_MIN 次、占这一段这个进程调用的 OWN_SHARE 以上（只调了一次的 interface.py 不写）；
单进程的程序（没有别的进程可比）不写文件。时刻从这一段的开头算（同页面上别的 +秒）。看的是整个 run（有 serving 阶段，segments.whole_run）时
不写：大半是启动，切出来的段和轮数靠不住（用户 10-13 定）。
"""
from __future__ import annotations

OWN_MIN = 10
OWN_SHARE = 0.01


def summary(S: dict | None, lo: int) -> dict[int, dict]:
    """{pid: {"parts", "title"}}：进程头上的那一句（parts 用 · 连起来）和悬停时的说明。S：segments.stages 的结果（None：切段靠不住，不写）"""
    if not S or S.get("whole"):
        return {}

    def at(t: int) -> str:
        return f"{'+' if t >= lo else '−'}{abs(t - lo) / 1e6:.2f}"
    by: dict[int, list] = {}
    for s in S["segs"]:
        by.setdefault(s["pid"], []).append(s)
    out: dict[int, dict] = {}
    for pid, ss in by.items():
        a, b = ss[0]["slices_us"][0][0], ss[-1]["slices_us"][0][1]
        own = next((x["evidence"]["own_files"][0] for x in ss if _own_ok(x)), None)
        parts = ([own[0].rsplit("/", 1)[-1]] if own else []) + [f"{at(a)}→{at(b)} s", f"{sum(x['rounds']['n'] for x in ss)} 轮"]
        if len(ss) > 1:
            parts.append(f"{len(ss)} 段")
        title = "；".join(f"{x['id']} {at(x['slices_us'][0][0])}→{at(x['slices_us'][0][1])} s，主循环 {x['main']} {x['rounds']['n']} 轮"
                         for x in ss)
        if own:
            title += f"；这段时间里只有它跑的文件：{own[0]}（{own[1]} 次调用）"
        out[pid] = {"parts": parts, "title": title + "。和 codestrata segments 同一份"}
    reqs: dict[int, list] = {}
    for q in S["reqs"]:
        reqs.setdefault(q["pid"], []).append(q)
    for pid, qs in reqs.items():
        if pid in out:
            continue
        fn = qs[0]["fn"].partition("#")[2] or qs[0]["fn"]
        ends = [q["t1_us"] for q in qs]
        span = f"{at(qs[0]['t0_us'])}→{at(max(ends)) + ' s' if None not in ends else '（录到最后没结束）'}"
        out[pid] = {"parts": [f"请求 {fn}" + (f" ×{len(qs)}" if len(qs) > 1 else ""), span],
                    "title": f"持有请求的进程：{fn} " + (f"{len(qs)} 次，" if len(qs) > 1 else "") + f"{span}（时刻从这一段开头算）"}
    return out


def _own_ok(s: dict) -> bool:
    ev = s["evidence"]
    if ev["alone"] or not ev["own_files"]:
        return False
    return ev["own_files"][0][1] >= max(OWN_MIN, OWN_SHARE * (ev.get("calls") or 0))
