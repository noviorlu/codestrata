"""前端里不碰 DOM 的纯函数：全文窗口的查找（findbar.find）、时间轴的吸附 / 放大 / 标签（timebar）。

    .venv/bin/python tests/test_web.py
要 node（没有就跳过）。页面上的交互（拖、键盘、高亮）在浏览器里测，这里只测算法。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from common import HERE, run_tests  # noqa: E402

WEB = HERE.parent / "codestrata" / "web"
# 脚本只在加载时挂几个监听、摸一下 CSS.highlights：给个空壳就能在 node 里加载
SHIM = "global.window = global; global.document = { addEventListener() {} }; window.addEventListener = () => {};\n"


def js(files: list[str], expr: str):
    """在 node 里加载 web/ 下的这几个脚本，算 expr（JSON 可序列化）；没有 node 返回 None"""
    node = shutil.which("node")
    if not node:
        return None
    src = SHIM + "".join((WEB / f).read_text(encoding="utf-8") + "\n" for f in files)
    src += f"process.stdout.write(JSON.stringify({expr}));\n"
    r = subprocess.run([node, "-e", src], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_find():
    """查找：默认不分大小写；区分大小写；全字匹配按 VS Code 的分隔符（下划线连着的不算一个词，匹配本身以
    分隔符开头 / 结尾的那一头不要求）；正则；空匹配（a*、^）跳过；正则写错给 error；不重叠"""
    L = ["def foo(self):", "    return self.foo_bar + Foo", "x = foo.bar  # foo", "", "aaa"]
    cases = {
        "plain": ("foo", {}),
        "case": ("foo", {"cs": True}),
        "word": ("foo", {"ww": True}),
        "word_case": ("Foo", {"ww": True, "cs": True}),
        "regex": (r"fo+\b", {"re": True}),
        "empty": ("a*", {"re": True}),
        "literal_paren": ("(", {}),
        "bad_regex": ("(", {"re": True}),
        "sep_start": (".foo", {"ww": True}),
        "sep_both": ("(self)", {"ww": True}),
        "no_overlap": ("aa", {}),
        "blank": ("", {}),
        "astral_dot": ("a.b", {"re": True}),
        "unicode_prop": (r"\p{Lu}\w+", {"re": True, "cs": True}),
        "legacy_escape": (r"foo\.bar\-?", {"re": True}),
    }
    L = L + ["a\U0001F600b 中文"]
    expr = "{" + ",".join(
        f"{k}: CS.findbar.find({json.dumps(L)}, {json.dumps(q)}, Object.assign({{cs: false, ww: false, re: false}}, {json.dumps(o)}))"
        for k, (q, o) in cases.items()) + "}"
    r = js(["findbar.js"], expr)
    if r is None:
        print("    （没有 node，跳过）")
        return
    hits = {k: v["hits"] for k, v in r.items()}
    assert hits["plain"] == [[1, 4, 7], [2, 16, 19], [2, 26, 29], [3, 4, 7], [3, 15, 18]], hits["plain"]
    assert hits["case"] == [[1, 4, 7], [2, 16, 19], [3, 4, 7], [3, 15, 18]]
    assert hits["word"] == [[1, 4, 7], [2, 26, 29], [3, 4, 7], [3, 15, 18]]       # foo_bar 里的不算
    assert hits["word_case"] == [[2, 26, 29]]
    assert hits["regex"] == [[1, 4, 7], [2, 26, 29], [3, 4, 7], [3, 15, 18]]
    assert hits["empty"] == [[2, 21, 22], [3, 9, 10], [5, 0, 3], [6, 0, 1]]                # 空匹配不算、也不卡住
    assert hits["literal_paren"] == [[1, 7, 8]]
    assert hits["bad_regex"] == [] and r["bad_regex"]["error"]
    assert hits["sep_start"] == []                   # self.foo_bar：右边挨着 _，不是一个词
    assert hits["sep_both"] == [[1, 7, 13]]          # 两头都是分隔符：不要求外面还是分隔符
    assert hits["no_overlap"] == [[5, 0, 2]]
    assert hits["blank"] == []
    # 正则带 u：. 配上一整个 emoji（UTF-16 里占两位）；\p{Lu} 能用；u 下不合法的老写法（\-）退回不带 u 照样能用
    assert hits["astral_dot"] == [[6, 0, 4]], hits["astral_dot"]
    assert hits["unicode_prop"] == [[2, 26, 29]], hits["unicode_prop"]
    assert hits["legacy_escape"] == [[3, 4, 11]], hits["legacy_escape"]


def test_find_cap():
    """匹配很多也全找出来（跳转走遍全部，页面上只标视野附近的）；到 20 万个才停，并说明（页面上写「200000+」）"""
    r = js(["findbar.js"], '[CS.findbar.find(Array(5000).fill("a a a a"), "a", {cs: false, ww: false, re: false}).hits.length,'
                           ' (x => [x.hits.length, !!x.capped])(CS.findbar.find(Array(60000).fill("a a a a"), "a", {cs: false, ww: false, re: false}))]')
    if r is None:
        print("    （没有 node，跳过）")
        return
    assert r == [20000, [200000, True]], r


def test_lane_route():
    """分列的排线（laneroute.js）：每条线路径不同；除了两头，线不从任何节点框里穿过；往右的连线走节点上面、往左的走下面
    （一来一回成一个圈）；隔层的边走列的侧边；一层的通道挤了就把下面的层往下推；接点不重合；沿每条线取点，离它最近的就是它"""
    spec = {
        "NW": 132, "GAP": 10, "PAD": 12, "MINW": 104, "EXTW": 92, "FOLDW": 112, "headY": 140, "top": 168,
        "layers": [0, 110, 220, 330], "layerOf": {"A": 0, "B": 1, "C": 2, "D": 3, "E": 1}, "nodeH": {},
        "cols": [{"lanes": ["p:main"], "rows": {"0": ["A"], "1": ["B", "E"], "2": ["C"], "3": ["D"]}, "gap": 0},
                 {"lanes": ["p:w"], "rows": {"0": ["A"], "2": ["C"]}, "gap": 8},
                 {"lanes": ["p:x"], "external": True, "rows": {}, "gap": 8}],
        "edges": [{"key": "e1", "lane": "p:main", "a": "A", "b": "B"}, {"key": "e2", "lane": "p:main", "a": "A", "b": "D"},
                  {"key": "e3", "lane": "p:main", "a": "A", "b": "C"}, {"key": "e4", "lane": "p:main", "a": "D", "b": "B"},
                  {"key": "e5", "lane": "p:main", "a": "B", "b": "E"}, {"key": "e6", "lane": "p:w", "a": "A", "b": "C"}],
        "links": [{"key": "l1", "from": {"lane": "p:main", "node": "A"}, "to": {"lane": "p:w", "node": "A"}},
                  {"key": "l2", "from": {"lane": "p:w", "node": "A"}, "to": {"lane": "p:main", "node": "A"}},
                  {"key": "l3", "from": {"lane": "p:main", "node": "C"}, "to": {"lane": "p:w", "node": "A"}},
                  {"key": "l4", "from": {"lane": "p:x", "node": None}, "to": {"lane": "p:main", "node": "D"}},
                  {"key": "l5", "from": {"lane": "p:w", "node": "C"}, "to": {"lane": "p:x", "node": None}}],
        "reserve": {"p:main|A": 24}}
    crowd = json.loads(json.dumps(spec))
    crowd["links"] += [{"key": f"x{i}", "from": {"lane": "p:main", "node": "B"}, "to": {"lane": "p:w", "node": "C"}} for i in range(12)]
    expr = """(() => {
      const R = CS.laneRoute, o = R.route(S), oc = R.route(SC), pk = R.picker(o.paths), bad = [], pick = {};
      const box = k => { const p = o.pos[k]; return [p.cx - p.w / 2 + 1, p.cy - p.h / 2 + 1, p.cx + p.w / 2 - 1, p.cy + p.h / 2 - 1]; };
      const ends = { e1: ['p:main|A', 'p:main|B'], e2: ['p:main|A', 'p:main|D'], e3: ['p:main|A', 'p:main|C'], e4: ['p:main|D', 'p:main|B'],
                     e5: ['p:main|B', 'p:main|E'], e6: ['p:w|A', 'p:w|C'], l1: ['p:main|A', 'p:w|A'], l2: ['p:w|A', 'p:main|A'],
                     l3: ['p:main|C', 'p:w|A'], l4: ['p:main|D'], l5: ['p:w|C'] };
      for (const [k, P] of Object.entries(o.paths)) {
        for (const n of Object.keys(o.pos)) {
          if (ends[k].includes(n)) continue;
          const b = box(n);
          for (let i = 1; i < P.pts.length; i++) for (let f = 0; f <= 1; f += 0.05) {
            const x = P.pts[i-1][0] + (P.pts[i][0] - P.pts[i-1][0]) * f, y = P.pts[i-1][1] + (P.pts[i][1] - P.pts[i-1][1]) * f;
            if (x > b[0] && x < b[2] && y > b[1] && y < b[3]) { bad.push(k + ' through ' + n); i = 1e9; break; }
          }
        }
        let own = 0, n = 0;
        for (let i = 1; i < P.pts.length; i++) for (let f = 0.1; f < 1; f += 0.2) {
          const x = P.pts[i-1][0] + (P.pts[i][0] - P.pts[i-1][0]) * f, y = P.pts[i-1][1] + (P.pts[i][1] - P.pts[i-1][1]) * f;
          const h = pk.near(x, y, 7); n++;
          if (h.length && (h[0].key === k || (h[1] && h[1].d - h[0].d < 1.5 && h.some(z => z.key === k)))) own++;
        }
        pick[k] = own / n;
      }
      const A = o.pos['p:main|A'], WA = o.pos['p:w|A'], first = k => o.paths[k].pts[0], last = k => o.paths[k].pts[o.paths[k].pts.length - 1];
      const sx = Object.keys(o.paths).map(k => first(k)[0] + ',' + first(k)[1]);
      return { n: Object.keys(o.paths).length, uniq: new Set(Object.values(o.paths).map(p => p.d)).size, bad, pick,
        l1: [first('l1')[1] < A.cy, last('l1')[1] < WA.cy], l2: [first('l2')[1] > WA.cy, last('l2')[1] > A.cy],
        e2side: o.paths.e2.pts.some(p => p[0] > A.cx + A.w / 2), starts: sx.length === new Set(sx).size,
        shift: oc.layerY[2] - o.layerY[2], tracks: oc.tracks.ch };
    })()"""
    r = js(["laneroute.js"], f"(() => {{ const S = {json.dumps(spec)}, SC = {json.dumps(crowd)}; return {expr}; }})()")
    if r is None:
        print("    （没有 node，跳过）")
        return
    assert r["n"] == r["uniq"] == 11, r
    assert r["bad"] == [], r["bad"]                                   # 线不从别的节点框里穿过
    assert all(v == 1 for v in r["pick"].values()), r["pick"]         # 沿线取点，最近的都是它（或一样近）
    assert r["l1"] == [True, True] and r["l2"] == [True, True], r     # 往右的走上面、往左的走下面
    assert r["e2side"] and r["starts"], r                             # 隔层的边走列的侧边；接点不重合
    assert r["shift"] > 12 * 9 and max(r["tracks"]) >= 12, r          # 12 条挤在一层：下面的层往下推


def test_timebar_math():
    """时间轴：拖到离阶段 / 整个 run 不到 tol 就吸过去（有几段的阶段、不能选的阶段不吸）；放大到一段时前后留 25%、
    至少 1 ms 宽、不出 run；放大后还占六成以上就看整个 run；时间段的标签"""
    segs = [["start", 0, 1000], ["serving", 1000, 5000], ["shutdown", 5000, 6000], ["start", 6000, 100000]]
    expr = "{" + ",".join([
        "run: CS.timebar.snap(S, 3, 99998, 100000, 5)",
        "phase: CS.timebar.snap(S, 1004, 4996, 100000, 5)",
        "far: CS.timebar.snap(S, 1010, 4996, 100000, 5)",
        "twice: CS.timebar.snap(S, 0, 1000, 100000, 5)",                 # start 有两段：不吸
        "notpick: CS.timebar.snap(S, 1004, 4996, 100000, 5, ['start', 'shutdown'])",
        "fit: CS.timebar.fit(1000, 5000, 100000)",
        "fitEdge: CS.timebar.fit(0, 400, 100000)",
        "fitTiny: CS.timebar.fit(5000, 5000, 100000)",
        "fitBig: CS.timebar.fit(10000, 90000, 100000)",
        "label: CS.timebar.label('t=103715942-104715942')",
        "labelShort: CS.timebar.label('t=1000-1500')",
        "labelPhase: CS.timebar.label('serving')",
        "parse: [CS.timebar.parse('t=5-17'), CS.timebar.parse('serving'), CS.timebar.parse('t=5')]",
    ]) + "}"
    r = js(["timebar.js"], f"(() => {{ const S = {json.dumps(segs)}; return {expr}; }})()")
    if r is None:
        print("    （没有 node，跳过）")
        return
    assert r["run"] == "" and r["phase"] == "serving" and r["far"] == "t=1010-4996", r
    assert r["twice"] == "t=0-1000" and r["notpick"] == "t=1004-4996", r
    assert r["fit"] == [0, 6000], r["fit"]                        # 前后各留 25%，左边不出 0
    assert r["fitEdge"] == [0, 1000], r["fitEdge"]                # 不到 1 ms 宽：撑到 1 ms，贴着 0
    assert r["fitTiny"] == [4500, 5500], r["fitTiny"]             # 零宽：以它为中心撑到 1 ms
    assert r["fitBig"] == [0, 100000], r["fitBig"]
    assert r["label"] == "103.72 s – 104.72 s" and r["labelShort"] == "0.001000 s – 0.001500 s", r
    assert r["labelPhase"] == "serving" and r["parse"] == [[5, 17], None, None], r


if __name__ == "__main__":
    sys.exit(run_tests(globals(), sys.argv[1:]))
