"""链的取数：在一段时间里把链走出来（links --follow 和页面共用一份），视图描述里的 chain 键（写法、解析），给分列画链要的东西。

    chain=<算链的范围>~<起点>[~<--link>…]
        范围  阶段名、t=起-止（几片的逗号隔开）或空（整个 run）：链是在哪一段里走出来的。页面上看的是链的 REF（只有几片），
              「第 k 次」得在原来那一段里数，所以单独记着；
        起点  不随范围变的写法（列:FN@t=微秒，links --follow 的输出里给的）；
        --link 原样（'A列:FN => B列:FN'）。
页面上：录到的跳标在画着的那条连线上（lanes.build 的 chain），推出来的 --link 那一跳多画一条（via link，inferred: order）。
"""
from __future__ import annotations

from . import chain as _chain
from . import lanes as _lanes
from . import segments as _segments
from . import seq as _seq
from .errors import CodestrataError

SEP = "~"


def key(window: str | None, start: str, links: list[str]) -> str:
    """视图描述里 chain 键的值"""
    return SEP.join([window or "", start, *links])


def parse(text: str) -> tuple[str | None, str, list[str]]:
    """chain 键的值 → (范围或 None, 起点, --link)"""
    parts = (text or "").split(SEP)
    if len(parts) < 2 or not parts[1].strip():
        raise CodestrataError("usage", f"chain 写成 范围~起点[~--link…]（links --follow 输出的 view set 里有拼好的）：{text!r}")
    return parts[0] or None, parts[1], [x for x in parts[2:] if x]


def walk(idx: dict, rd, hot: dict, lo: int, hi: int, head_window: tuple, start: str, links: list[str], lanes: list[str] | None = None):
    """在 [lo, hi] 里走链：(Walker, 起点的说明, Walker.walk 的结果, --link)。head_window：认轮头用的那段（segments.head_window）"""
    A = _segments.analyse(rd, lo, hi, head_window=head_window)
    W = _chain.Walker(A, _lanes.EndFns(idx, rd, hot), lo, hi)
    L = [W.link(t) for t in links]
    pos, st = W.start(start, lanes)
    return W, st, W.walk(pos, L, (st["t0_us"], st["t1_us"])), L


def for_page(idx: dict, rd, run: dict, hot: dict, text: str) -> tuple[dict, tuple | None]:
    """页面要的：({key, start, hops, stop, lanes, error}, 给 lanes.build 的 chain=(录到的交接下标 → [第几跳], 推出来的跳) 或 None)。
    走不出来（写错、配不上）时 error 是说明，分列照画"""
    try:
        window, start, links = parse(text)
        segs, _, end = _seq.window_segments(run, rd, window)
        lo, hi = segs[0][0], segs[-1][1]
        _, st, ch, _ = walk(idx, rd, hot, lo, hi, _segments.head_window(run, end, lo, hi, window)[1], start, links)
    except CodestrataError as e:
        return {"key": text, "error": e.msg}, None
    except (LookupError, ValueError) as e:
        return {"key": text, "error": str(e)}, None
    marks: dict[int, list] = {}
    extra = []
    for i, raw in enumerate(ch["raw"]):
        if raw[0] == "h":
            marks.setdefault(raw[1], []).append(i)
        else:
            extra.append({"hop": i, "from": raw[1], "to": raw[2]})
    hops = [{"i": i + 1, "kind": h["kind"], "via": h["via"], "basis": h["basis"], "stay": h["stay"], "k": h["k"], "n": h["n"],
             "from": h["from"]["lane"], "to": h["to"]["lane"], "t_from": h["from"]["t_us"], "t_to": h["to"]["t_us"]}
            for i, h in enumerate(ch["hops"])]
    return ({"key": text, "start": st["stable"], "hops": hops, "stop": ch["stop"]["reason"], "lanes": ch["lanes"], "error": None},
            (marks, extra))
