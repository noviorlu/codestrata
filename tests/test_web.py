"""前端里不碰 DOM 的纯函数：全文窗口的查找（findbar.find）、时间轴的吸附 / 放大 / 标签（timebar）、
分列的摆放和排线（lanepack、laneroute）。

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
    r = js(["lanepack.js", "laneroute.js"], f"(() => {{ const S = {json.dumps(spec)}, SC = {json.dumps(crowd)}; return {expr}; }})()")
    if r is None:
        print("    （没有 node，跳过）")
        return
    assert r["n"] == r["uniq"] == 11, r
    assert r["bad"] == [], r["bad"]                                   # 线不从别的节点框里穿过
    assert all(v == 1 for v in r["pick"].values()), r["pick"]         # 沿线取点，最近的都是它（或一样近）
    assert r["l1"] == [True, True] and r["l2"] == [True, True], r     # 往右的走上面、往左的走下面
    assert r["e2side"] and r["starts"], r                             # 隔层的边走列的侧边；接点不重合
    assert r["shift"] > 12 * 9 and max(r["tracks"]) >= 12, r          # 12 条挤在一层：下面的层往下推


def _pack_spec():
    """test_lane_pack 的图：main 列里 A ⊃ B（同一行开始）、和 A 并排的 C（跨过没有它的节点的第 3 行）、和 A 叠在同一条轨道里的 G、
    A 里还有和 A 在同一行结束的 B2、没有节点的 E / K；w 列的 H 也跨过一行空的；v 列的 J 在左边、上一行三个节点，它跨过的第 2 行只有它右边的 s2（s2 往上连到最左的 L 走左侧）；还有只跑仓库外代码的列、收起的进程（有框也不画）。
    第 1、2 行是同一个 y 的两个子行。散节点的输入顺序和排出来的不一样（第 1 行 x1 在前）。
    s 列：第 6、7 行也是同一个 y 的子行，中间没有框头、轨带、标记；第 6 行有高 44 的 st6 夹在矮的 sa6 和 SB 之间，sa6 S 形落进 SB 里的 sk1；
    跨两行的 SZ 和只跨一行的 SA（名字在前）在第 3 行重叠，SZ 该在左。
    h 列：第一行就开始的 F1、F2 并排，列的中间正好在 F2 的 − 上，仓库外的列、v 列的 R 各有一条连线接在它的列头上"""
    rows = {"p:main": {"0": ["T", "L0"], "1": ["x1", "b1", "a1"], "2": ["c2", "b2", "y2"], "3": ["a3", "z3"], "4": ["c4", "w4"],
                       "5": ["D5", "g5"]},
            "p:w": {"0": ["T"], "1": ["m1"], "3": ["n3"], "5": ["q5"]},
            "p:v": {"0": ["L", "M", "R"], "1": ["k1", "s1"], "2": ["s2"], "3": ["k3"]},
            "p:s": {"2": ["sp2"], "3": ["sa3", "sp3"], "6": ["st6", "sa6", "sk0"], "7": ["sk1", "sk2"]},
            "p:h": {"0": ["h0", "h1"]}}
    layer_of = {}
    for rs in rows.values():
        for k, ids in rs.items():
            layer_of.update({i: int(k) for i in ids})
    E = lambda lane, *ab: [{"key": f"{lane[2:]}:{a}>{b}", "lane": lane, "a": a, "b": b} for a, b in ab]  # noqa: E731
    return {
        "NW": 132, "GAP": 10, "PAD": 12, "MINW": 104, "EXTW": 92, "FOLDW": 112, "headY": 140, "top": 168,
        "layers": [0, 110, 110, 220, 330, 440, 550, 550], "layerOf": layer_of, "nodeH": {"c2": 46, "st6": 44, "sa6": 30},
        "cols": [{"lanes": ["p:main"], "rows": rows["p:main"], "gap": 0,
                  "frames": {"A": {"parent": None, "minw": 120}, "B": {"parent": "A", "minw": 90}, "B2": {"parent": "A", "minw": 0},
                             "C": {"parent": None, "minw": 200}, "E": {"parent": "A", "minw": 300}, "G": {"parent": None, "minw": 80},
                             "K": {"parent": None, "minw": 50}},
                  "frameOf": {"b1": "B", "b2": "B", "a1": "A", "a3": "B2", "c2": "C", "c4": "C", "g5": "G"}},
                 {"lanes": ["p:w"], "rows": rows["p:w"], "gap": 14,
                  "frames": {"H": {"parent": None, "minw": 100}}, "frameOf": {"m1": "H", "n3": "H"}},
                 {"lanes": ["p:v"], "rows": rows["p:v"], "gap": 8,
                  "frames": {"J": {"parent": None, "minw": 60}, "Q": {"parent": "J", "minw": 400}}, "frameOf": {"k1": "J", "k3": "J", "s1": "nope"}},
                 {"lanes": ["p:x"], "external": True, "rows": {}, "gap": 8},
                 {"lanes": ["p:f1", "p:f2"], "fold": True, "rows": {}, "gap": 14, "frames": {"Z": {"parent": None, "minw": 99}}, "frameOf": {}},
                 {"lanes": ["p:s"], "rows": rows["p:s"], "gap": 8,
                  "frames": {"SZ": {"parent": None, "minw": 0}, "SA": {"parent": None, "minw": 0}, "SB": {"parent": None, "minw": 0}},
                  "frameOf": {"sp2": "SZ", "sp3": "SZ", "sa3": "SA", "sk0": "SB", "sk1": "SB", "sk2": "SB"}},
                 {"lanes": ["p:h"], "rows": rows["p:h"], "gap": 8,
                  "frames": {"F1": {"parent": None, "minw": 0}, "F2": {"parent": None, "minw": 220}}, "frameOf": {"h0": "F1", "h1": "F2"}}],
        "edges": E("p:main", ("T", "a1"), ("T", "b1"), ("x1", "c2"), ("a1", "a3"), ("b2", "z3"), ("T", "D5"), ("c4", "T"),
                   ("y2", "w4"), ("a3", "c4"), ("a1", "x1"), ("g5", "D5"), ("D5", "b2"), ("b1", "b2"), ("L0", "x1"), ("a1", "c2"))
        + E("p:w", ("T", "m1"), ("m1", "n3"), ("n3", "q5")) + E("p:v", ("L", "k1"), ("R", "k1"), ("M", "s1"), ("L", "s1"), ("s2", "L"))
        + E("p:s", ("sp2", "sp3"), ("sa6", "sk1"), ("sk0", "sk2")),
        "links": [{"key": f"l{i}", "from": {"lane": a, "node": x}, "to": {"lane": b, "node": y}} for i, (a, x, b, y) in enumerate([
            ("p:main", "a1", "p:w", "m1"), ("p:w", "n3", "p:main", "z3"), ("p:main", "T", "p:w", "T"), ("p:w", "T", "p:main", "c2"),
            ("p:x", None, "p:main", "D5"), ("p:main", "b2", "p:x", None), ("p:main", "g5", "p:w", "q5"), ("p:f1", None, "p:main", "y2"),
            ("p:v", "k1", "p:w", "m1"), ("p:main", "L0", "p:v", "M"), ("p:x", None, "p:h", None), ("p:v", "R", "p:h", None)])],
        "reserve": {"p:main|a1": 24, "p:main|c2": 12, "p:w|m1": 24, "p:v|k1": 12}, "gapEnd": 8}


def test_lane_pack():
    """每列各有各的切面时的摆放（lanepack.js）和排线（laneroute.js 的框）：
    没有框时就是以前的每行居中；框装着它的节点（连同起 / 收标记）和子框（左右留 FPAD），子框的框头在外层框头下面；
    别的节点不进框、横着离框至少 PGAP，并排的框不重叠；跨的行多的框在左；列两侧的竖轨离框至少 6；
    除了在轨带里横着走的（和从列头竖着下来的那一段），线不穿过和两头无关的框；框里的节点从底边下到下带，横轨还在框里；
    框里最靠边的节点走侧边时从它的侧面出来；线离框头的 − 至少 8（接在列头上的也是）；同一个 y 的子行之间 S 形也落得下去；
    散节点的输入顺序打乱、别的列多了框和子行，这一列的框位置不变；没有节点的框不画、没有 NaN；
    一个节点的行只看它自己，别的列换了切面不动它"""
    S = _pack_spec()
    # 别的列（w）展开了：多了两个子行（一个插在 C 跨的行里，按行号算 C 就比 A 长了），这一列（main）的行号跟着变
    S2 = json.loads(json.dumps(S))
    def mv(k): return k + (k >= 4) + (k >= 5)                                        # noqa: E306
    for c in S2["cols"]:
        c["rows"] = {str(mv(int(k))): v for k, v in c["rows"].items()}
    S2["layerOf"] = {i: mv(k) for i, k in S2["layerOf"].items()}
    S2["layers"] = [0, 110, 110, 220, 330, 330, 440, 440, 550, 550]
    S2["cols"][1]["rows"].update({"4": ["nw4"], "6": ["nw6"]})
    S2["cols"][1]["frames"]["N"] = {"parent": None, "minw": 150}
    S2["cols"][1]["frameOf"].update({"nw4": "N", "nw6": "N"})
    S2["layerOf"].update({"nw4": 4, "nw6": 6})
    expr = """(() => {
      const P = CS.lanePack, R = CS.laneRoute, o = R.route(S), pk = R.picker(o.paths), bad = [], NW = S.NW;
      const colOf = {}; S.cols.forEach(c => c.lanes.forEach(l => { colOf[l] = c; }));
      const anc = (c, id) => { const s = []; for (let f = (c.frameOf || {})[id]; f != null && c.frames[f]; f = c.frames[f].parent) s.push(f); return s; };
      const split = k => { const i = k.indexOf('|'); return [k.slice(0, i), k.slice(i + 1)]; };
      const box = p => [p.cx - p.w / 2, p.cy - p.h / 2, p.cx + p.w / 2, p.cy + p.h / 2];
      const rect = F => [F.x, F.y, F.x + F.w, F.y + F.h];
      const meet = (a, b) => a[0] < b[2] - 0.5 && b[0] < a[2] - 0.5 && a[1] < b[3] - 0.5 && b[1] < a[3] - 0.5;
      const ends = {};
      S.edges.forEach(e => { ends[e.key] = [[e.lane, e.a], [e.lane, e.b]]; });
      S.links.forEach(k => { ends[k.key] = [[k.from.lane, k.from.node], [k.to.lane, k.to.node]].filter(x => x[1]); });
      const fk = Object.keys(o.fpos).sort();
      // 框装着它的节点（连同上面的标记）、子框，左右留 FPAD；别的节点不进框；框头、− 的位置
      fk.forEach(k => {
        const F = o.fpos[k], r = rect(F), [lane, f] = split(k), c = colOf[lane];
        Object.keys(o.pos).forEach(pk2 => {
          const [l2, id] = split(pk2), b = box(o.pos[pk2]);
          if (l2 === lane && anc(c, id).includes(f)) {
            const top = b[1] - (S.reserve[pk2] || 0);
            if (!(b[0] >= r[0] + R.FPAD - 0.01 && b[2] <= r[2] - R.FPAD + 0.01 && top >= F.y + R.FH - 0.01 && b[3] <= r[3]))
              bad.push('member ' + pk2 + ' not in ' + k);
          } else if (b[1] < r[3] - 0.5 && r[1] < b[3] - 0.5 && Math.max(r[0] - b[2], b[0] - r[2]) < R.PGAP - 0.01)
            bad.push(pk2 + ' within PGAP of ' + k);                       // 别的节点不进框，横着离框至少 PGAP
        });
        const par = c.frames[f].parent, Q = par != null && o.fpos[lane + '|' + par];
        if (Q && !(F.x >= Q.x + R.FPAD - 0.01 && F.x + F.w <= Q.x + Q.w - R.FPAD + 0.01 && F.y >= Q.y + R.FH - 0.01 && F.y + F.h <= Q.y + Q.h - R.FB + 0.01))
          bad.push('child ' + k + ' not in ' + par);
        if (F.head.x !== F.x || F.head.y !== F.y || F.head.w !== F.w || F.head.h !== R.FH || F.btn.x !== F.x + 15 || F.btn.y !== F.y + R.FH / 2)
          bad.push('head ' + k);
      });
      // 不是一个套着另一个的两个框不重叠（并排的、别的列的）
      fk.forEach((k1, i) => fk.slice(i + 1).forEach(k2 => {
        const [la, fa] = split(k1), [lb, fb] = split(k2), c = colOf[la];
        const inside = (x, y) => { for (let p = c.frames[x].parent; p != null; p = c.frames[p].parent) if (p === y) return true; return false; };
        if (!(la === lb && (inside(fa, fb) || inside(fb, fa))) && meet(rect(o.fpos[k1]), rect(o.fpos[k2]))) bad.push(k1 + ' meets ' + k2);
      }));
      // 线：不穿过别的节点框；除了横段，不穿过和两头无关的框；中间的竖段（列两侧、缝里的竖轨）离框至少 6；离 − 至少 8
      let sides = 0, lows = 0;
      Object.keys(o.paths).forEach(key => {
        const P2 = o.paths[key].pts, E2 = ends[key], curve = o.paths[key].d.indexOf(' C') > 0;
        const own = E2.map(x => x[0] + '|' + x[1]);
        const related = k => { const [lane, f] = split(k); return E2.some(x => x[0] === lane && anc(colOf[lane], x[1]).includes(f)); };
        for (let i = 1; i < P2.length; i++) {
          const a = P2[i - 1], b = P2[i], vert = Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) > 1;
          // 轨带里的横段：横着、不在任何一行节点的高度上（从节点侧面出来的那一段在节点的高度上，不算）
          const flat = Math.abs(a[1] - b[1]) < 0.01 && !Object.values(o.pos).some(p => Math.abs(a[1] - p.cy) < p.h / 2);
          // 从列头竖着下来的那一段会从第一行就开始的框的框头底下穿过（已知，框头画在线上面；离 − 至少 8 在下面查）
          const stub = Math.min(a[1], b[1]) <= S.headY + 3.01;
          for (let t = 0; t <= 1; t += 0.05) {
            const x = a[0] + (b[0] - a[0]) * t, y = a[1] + (b[1] - a[1]) * t;
            Object.keys(o.pos).forEach(n => {
              const q = box(o.pos[n]);
              if (!own.includes(n) && x > q[0] + 1 && x < q[2] - 1 && y > q[1] + 1 && y < q[3] - 1) bad.push(key + ' through ' + n);
            });
            if (!flat && !stub) fk.forEach(k => {
              const r = rect(o.fpos[k]);
              if (!related(k) && x > r[0] + 1 && x < r[2] - 1 && y > r[1] + 1 && y < r[3] - 1) bad.push(key + ' through frame ' + k);
            });
          }
          if (vert && !curve && i > 1 && i < P2.length - 1) {
            sides++;
            fk.forEach(k => {
              const F = o.fpos[k], y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
              if (y0 < F.y + F.h - 0.5 && F.y < y1 - 0.5 && a[0] > F.x - 6 + 0.01 && a[0] < F.x + F.w + 6 - 0.01) bad.push(key + ' side near ' + k);
            });
          }
        }
        // 框里的节点从底边竖着下到下带的那一段：拐弯的横轨还在装着它的每个框里（框底挂在下带下面）
        if (!curve) own.forEach(n => {
          const p = o.pos[n], [lane, id] = split(n), fs = anc(colOf[lane], id);
          [[P2[0], P2[1]], [P2[P2.length - 1], P2[P2.length - 2]]].forEach(([e, f]) => {
            if (!fs.length || Math.abs(e[1] - (p.cy + p.h / 2)) > 3.5 || Math.abs(e[0] - p.cx) > p.w / 2 || Math.abs(e[0] - f[0]) > 0.01 || f[1] <= e[1]) return;
            lows++;
            fs.forEach(g => { const F = o.fpos[lane + '|' + g]; if (F && f[1] > F.y + F.h - 0.5) bad.push(key + ' below the bottom of ' + lane + '|' + g); });
          });
        });
      });
      fk.forEach(k => pk.near(o.fpos[k].btn.x, o.fpos[k].btn.y, 8).forEach(h => bad.push(h.key + ' near the − of ' + k)));
      const nan = []; (function walk(v, p) {
        if (typeof v === 'number') { if (!isFinite(v)) nan.push(p); }
        else if (v && typeof v === 'object') Object.keys(v).forEach(k => walk(v[k], p + '.' + k));
      })(o, 'o');
      // 摆放：没有框时同以前（每行在列里居中）；散节点的顺序打乱、别的列多了框和子行，框的位置不变
      const strip = c => Object.assign({}, c, { frames: {}, frameOf: {} });
      const today = c => {
        let most = 0; Object.values(c.rows).forEach(r => { most = Math.max(most, r.length); });
        const base = Math.max(S.MINW, most * (NW + S.GAP) - S.GAP + 2 * S.PAD), rel = {};
        Object.values(c.rows).forEach(ids => { const x0 = (base - (ids.length * (NW + S.GAP) - S.GAP)) / 2;
          ids.forEach((id, i) => { rel[id] = x0 + i * (NW + S.GAP) + NW / 2; }); });
        return { base, rel };
      };
      const same = [0, 1, 2].map(ci => { const p = P.pack(strip(S.cols[ci]), S), t = today(S.cols[ci]);
        return p.base === t.base && JSON.stringify(Object.keys(t.rel).sort().map(k => p.rel[k])) === JSON.stringify(Object.keys(t.rel).sort().map(k => t.rel[k]))
          && Object.values(p.rows).every(ids => (p.rel[ids[0]] - NW / 2) + (p.rel[ids[ids.length - 1]] + NW / 2) === p.base); });
      const plain = R.route(Object.assign({}, S, { cols: S.cols.map(c => c.fold || c.external ? c : strip(c)) }));
      const bare = R.route(Object.assign({}, S, { cols: S.cols.map(c => { const d = Object.assign({}, c); delete d.frames; delete d.frameOf; return d; }) }));
      const p0 = P.pack(S.cols[0], S), rev = Object.assign({}, S.cols[0], { rows: {} });
      Object.keys(S.cols[0].rows).forEach(l => { rev.rows[l] = S.cols[0].rows[l].slice().reverse(); });
      const o2 = R.route(S2), sw = k => o.fpos[k].w;
      const ci = l => S.cols.findIndex(c => c.lanes[0] === l), hc = o.cols[ci('p:h')], c4 = o.pos['p:main|c4'], q4 = o.paths['main:c4>T'].pts;
      return { bad, nan, sides, lows, fk, same, plainFrames: Object.keys(plain.fpos).length, bareEq: JSON.stringify(plain) === JSON.stringify(bare),
        row1: p0.rows[1], frel: p0.frel, span: p0.span, base: p0.base, home: P.pack(S.cols[2], S).home.s1 === null,
        shuffled: JSON.stringify(P.pack(rev, S).frel) === JSON.stringify(p0.frel),
        other: JSON.stringify(P.pack(S2.cols[0], S2).frel) === JSON.stringify(p0.frel),
        otherW: ['A', 'B', 'C', 'G'].every(f => o2.fpos['p:main|' + f].w === sw('p:main|' + f)), o2N: !!o2.fpos['p:w|N'],
        curves: ['main:T>a1', 'v:R>k1', 'main:x1>c2', 'main:b1>b2'].filter(k => o.paths[k].d.indexOf(' C') > 0),
        sideOf: ['main:a1>c2', 'main:L0>x1'].filter(k => o.paths[k].d.indexOf(' C') < 0),
        gaps: o.layerY.slice(1).map((y, i) => y - o.layerY[i]),
        // 同一个 y 的两个子行之间的 S 形落多少
        drops: S.edges.filter(e => o.paths[e.key].d.indexOf(' C') > 0 && S.layers[S.layerOf[e.a]] === S.layers[S.layerOf[e.b]])
          .map(e => { const q = o.paths[e.key].pts; return [e.key, q[q.length - 1][1] - q[0][1]]; }),
        sfrel: P.pack(S.cols[ci('p:s')], S).frel,
        mid: Math.abs(hc.x + hc.w / 2 - o.fpos['p:h|F2'].btn.x) < 8,               // h 列的中间真在 F2 的 − 上（不挪就压到）
        heads: S.links.filter(k => k.to.lane === 'p:h').map(k => !!o.paths[k.key]),
        exit: Math.abs(q4[0][0] - (c4.cx - c4.w / 2)) < 0.01 && Math.abs(q4[0][1] - q4[1][1]) < 0.01 && Math.abs(q4[0][1] - c4.cy) < c4.h / 2
          && q4[1][0] < q4[0][0] };
    })()"""
    keys_expr = """(() => {
      const P = CS.lanePack, G = { nodes: [{ id: 'pkg/a', cy: 0, x: 0.2, h: 40 }, { id: 'pkg/sub/', cy: 110, x: 0.5 }, { id: 'other', cy: 220, x: 0.8, h: 34 }] };
      const has = (X, n) => X.endsWith('/') && n !== X && n.startsWith(X);
      const B = ['pkg/', 'other', 'ghost', 'pkg/sub/'];
      const K1 = P.keys(G, ['pkg/sub/x', 'pkg/sub/y', 'pkg/sub/z', 'pkg/a'].concat(B), { 'pkg/sub/x': ['pkg/sub/', 1], 'pkg/sub/y': ['pkg/sub/', 0], 'pkg/sub/z': ['pkg/sub/', 1] }, has);
      const K2 = P.keys(G, ['pkg/'].concat(B), {}, has), R1 = P.rows(K1), R2 = P.rows(K2);
      const seq = R => { const r = P.colRows(B, R); return Object.keys(r).map(Number).sort((a, b) => a - b).map(l => r[l]); };
      return { K1, indep: B.every(id => JSON.stringify(K1[id]) === JSON.stringify(K2[id])), R1, seq1: seq(R1), seq2: seq(R2),
               mixed: P.colRows(['pkg/sub/z', 'pkg/sub/x', 'pkg/a', 'pkg/', 'pkg/sub/y'], R1) };
    })()"""
    r = js(["lanepack.js", "laneroute.js"], f"(() => {{ const S = {json.dumps(S)}, S2 = {json.dumps(S2)}; return {expr}; }})()")
    if r is None:
        print("    （没有 node，跳过）")
        return
    k = js(["lanepack.js"], keys_expr)
    assert r["fk"] == ["p:h|F1", "p:h|F2", "p:main|A", "p:main|B", "p:main|B2", "p:main|C", "p:main|G",
                       "p:s|SA", "p:s|SB", "p:s|SZ", "p:v|J", "p:w|H"], r["fk"]   # E、K、Q 没节点，收起的不画
    assert r["bad"] == [], r["bad"]
    assert r["nan"] == [], r["nan"]
    assert r["sides"] >= 3 and r["lows"] >= 2, r                    # 真有走侧边、缝里的竖段，框里的节点下到下带的段被检查到
    assert r["same"] == [True, True, True], r["same"]               # 没有框：同以前的每行居中
    assert r["plainFrames"] == 0 and r["bareEq"], r                 # 没有框的列：frames 给空的、不给都一样，没有 fpos
    assert r["row1"] == ["b1", "a1", "x1"], r["row1"]               # 框在左（B 在 A 里），散节点在右，不按输入顺序
    assert r["span"] == {"A": [1, 3], "B": [1, 2], "B2": [3, 3], "C": [2, 4], "G": [5, 5]}, r["span"]
    assert r["frel"]["G"][0] == r["frel"]["A"][0] < r["frel"]["B"][0] < r["frel"]["C"][0], r["frel"]   # G 和 A 叠在同一条轨道
    assert r["frel"]["C"][1] - r["frel"]["C"][0] == 200 and r["home"], r                 # C 按 minw 撑宽；不认识的框当没有
    assert r["shuffled"] and r["other"] and r["otherW"] and r["o2N"], r                  # 框的位置只看这一列
    assert r["curves"] == ["main:T>a1", "v:R>k1", "main:x1>c2", "main:b1>b2"], r["curves"]   # 进框照样 S 形落下去
    assert r["sideOf"] == ["main:a1>c2", "main:L0>x1"], r["sideOf"]  # S 形会压到 − / 擦过无关的框：走侧边
    assert min(r["gaps"]) >= 34 + 6 and r["gaps"][0] > 0, r["gaps"]  # 同一个 y 的子行也撑开了
    drops = dict(r["drops"])
    assert {"s:sa6>sk1", "s:sk0>sk2", "main:b1>b2"} <= set(drops) and min(drops.values()) >= 16, r["drops"]   # 子行之间中间什么都没有也落得下去
    F = r["sfrel"]
    assert F["SZ"][0] == F["SB"][0] < F["SA"][0], F                  # 跨的行多的在左（SA 名字在前、跨得少，排在右边的轨道）
    assert r["mid"] and r["heads"] == [True, True], r                # 接在 h 列头上的两条：列的中间压着 F2 的 −，挪开了（上面 bad 查离 − 8）
    assert r["exit"], r                                              # c4 在 C 里、是这一行最左的：往上走左侧时从它的左侧面出来
    K = k["K1"]
    assert K["pkg/sub/x"] == {"y": 110, "s": 1, "x": 0.5, "h": 34} and K["pkg/sub/y"]["s"] == 0, K     # 在图上的节点里面：(B 的 cy, sub)
    assert K["pkg/a"] == {"y": 0, "s": 0, "x": 0.2, "h": 40} and K["pkg/"] == {"y": 0, "s": 0, "x": 0.2, "h": 34}, K   # 比图上粗：最小的
    assert K["ghost"] == {"y": 290, "s": 0, "x": 0, "h": 34}, K                                          # 都不是：最下面一行
    assert k["R1"]["layers"] == [0, 110, 110, 220, 290], k["R1"]
    assert k["R1"]["layerOf"]["pkg/sub/y"] == k["R1"]["layerOf"]["pkg/sub/"] == 1 and k["R1"]["layerOf"]["pkg/sub/z"] == 2, k["R1"]
    assert k["indep"] and k["seq1"] == k["seq2"], k                  # 别的列换了切面：这一列的键、行的先后不变
    assert k["mixed"] == {"0": ["pkg/", "pkg/a"], "1": ["pkg/sub/y"], "2": ["pkg/sub/x", "pkg/sub/z"]}, k["mixed"]   # x 一样按 id


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
