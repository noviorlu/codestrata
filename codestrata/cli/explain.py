"""codestrata explain：讲一个函数这次怎么跑的——定义、在哪几列跑过、谁调它、它调了谁、启动了哪些 GPU kernel。
只给原料，「为什么」由 agent 读代码后说。"""
from __future__ import annotations

from .. import explain as _explain
from .. import funcref as _funcref
from .. import runs as _runs
from .. import seq as _seq
from ..errors import CodestrataError
from . import common, out

NAME = "explain"
EFFECT = "read"
DOES = "讲一个函数：定义、这段时间里在哪几列跑过、谁调它、它调了谁（代码里看不出的标出来）、启动了哪些 GPU kernel"
USAGE = "codestrata explain 函数 REF [--json]（函数写 路径#限定名、限定名，或唯一的名字）"
EXAMPLE = "codestrata explain OmniGPUModelRunner._model_forward 20261013-191530-run_single_prompt@serving"


def add_args(p) -> None:
    p.add_argument("item", metavar="函数", help="路径#限定名、限定名，或唯一的名字")
    p.add_argument("ref", metavar="REF", help="RUN@范围，或页面地址（加单引号）")


def run(a) -> out.Result:
    c = common.context(a)
    common.require_events(c)
    r = c.res
    idx = common.index(c)
    label = common.labeler(idx)
    hot, _ = _runs.load_run(c.repo, idx, r.run, r.rd, r.phase)
    keys = _seq.span_index(r.rd)["keys"]
    try:
        node, ids = _funcref.resolve(a.item, keys, label)
    except CodestrataError as e:                     # 录到的键里没有：scan 的索引里有就讲它（这段时间里没跑过）
        node = _funcref.resolve_symbol(a.item, idx.get("symbols") or {}, ("func", "method", "function"))
        if e.code != "item_not_found" or node is None:
            raise
        ids = set()
    d = _explain.function(r.rd, r.run, hot, node, ids, r.phase)
    d["def"] = _explain.definition(c.repo, idx, node)
    c.warnings += _stale(c, r, d)
    return out.Result(data=d, text=_text(d, r.slices[0][0]), repo=c.repo, ref=c.ref_json(), warnings=c.warnings)


def _stale(c, r, d) -> list[dict]:
    """录制之后改过的文件：行号按函数挪过，原文可能对不上"""
    if not d.get("def"):
        return []
    try:
        fs = _runs.file_state(c.repo, common.index(c), _runs.read_detail(r.rd))
    except (OSError, ValueError):
        return []
    f = d["def"]["file"]
    return [{"code": "stale", "msg": f"{f} 录制之后改过，行号和原文可能和录的时候对不上"}] if fs.get(f) in ("changed", "gone") else []


def _unseen_tag(x: dict) -> str:
    """只有 trace 的（全部 / 其中几次）标出来，带上为什么（align.note_short：写的是基类的方法、只知道名字、经别的转了一道……）"""
    st = x.get("status")
    if st not in ("trace", "mixed"):
        return ""
    head = "代码里看不出" if st == "trace" else f"其中 {x.get('only')} 次代码里看不出"
    return f"  [{head}" + (" · " + x["why"] if x.get("why") else "") + "]"


def _text(d: dict, lo: int) -> list[str]:
    L = [f"函数 {d['item']}。时刻从这一段开头（t={lo}）算"]
    dd = d.get("def")
    if dd:
        L.append(f"  定义  {dd['signature'] or '?'}  {dd['file']}:{dd['line']}")
        if dd.get("doc"):
            L.append(f'        "{dd["doc"]}"')
    if d["lanes"]:
        L.append("这段时间里  " + "；".join(f"{x['lane']} ×{x['n']}（{out.secs(x['first_us'], lo)} → {out.secs(x['last_us'], lo)}）"
                                         for x in d["lanes"]))
    else:
        L.append("这段时间里没跑过（仓库里有，scan 的索引里找到的）")
    for title, xs in (("谁调它", d["callers"]), ("它调谁", d["calls"])):
        if xs:
            L.append(title)
            for x in xs:
                ln = "、".join(map(str, x["lines"]))
                L.append(f"  ×{x['n']:<6} {common.short(x['fn'])}" + (f"  行 {ln}" if ln else "") + _unseen_tag(x))
    if d["kernels"]:
        L.append(f"它启动的 GPU kernel（{len(d['kernels'])} 种）")
        for x in d["kernels"]:
            L.append(f"  ×{x['n']:<6} {x['fn'].partition('#')[2] or x['fn']}")
    if d.get("ran_as"):
        L.append("代码里写成调它、跑的是同名的别的方法（子类覆盖的或接口的实现）")
        for x in d["ran_as"]:
            by = "；".join(f"{common.short(y['fn'])} 行 {y['line']}" for y in x["callers"][:3])
            L.append(f"  ×{x['n']:<6} {common.short(x['fn'])}  ← {by}")
    return L
