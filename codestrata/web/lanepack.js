/* 分列里节点放在哪（纯函数，不碰 DOM）：每个节点在第几行、一列里横着怎么排、展开的目录画成框。
 * lanes.js 拿 keys / rows / colRows 建 laneroute 的输入，laneroute.js 第 1 步用 pack 排每一列，test_web 在 node 里测。
 *
 * 每一列有自己的切面（用户 10-02）：一列里 ＋ / − 不动别的列的节点、层和先后；展开的目录像模块图那样画成框（框头写名字、带 −）。
 * 所以一个节点放在哪一行只看它自己、不看哪一列画了什么（docs/plans/lanes-percut.md §1）：一列展开了，别的列最多被推开几个像素。
 *  - keys：节点 → 行的键 (y, s) 和横向的先后 x；
 *  - rows：所有键排好 → 第几行（同一个 y 的几个子行纵坐标一样，laneroute 撑开时把它们推开）；
 *  - pack：一列里横着怎么排，照搬模块图（layout.py build 的轨道排法）：子框按跨的行多少（多的在左）、名字排进「轨道」，
 *    跨的行不重叠的框叠在同一条轨道里；散节点在每一行里从最后一个跨过这一行的轨道右边开始、居中排。没有框时就是以前的每行居中。
 *
 * 接口（lanes.js 照这个接）：
 *  keys(G, ids, place, contains) → {id: {y, s, x, h}}
 *    G：公共切面的「只看跑到的」图 {nodes: [{id, cy, x, h}]}；ids：没收起的列里所有节点（重复的不要紧）；
 *    place：/api/lanes 的 {id: [B, sub]}（id 在图上的节点 B 里面，sub 是它在 B 里自己分的层）；
 *    contains(X, n)：节点 X 是不是盖住图上的节点 n（n 是 id）。
 *    规则（按先后）：在图上 → (cy, 0)，x、h 照图；在 B 里 → (B 的 cy, sub)，x 是 B 的 x；比图上粗、盖住几个 → 它们里最小的 cy、
 *    最小的 x；都不是 → 最下面单独一行（最低的 cy + 70，x = 0）。h 不在图上的是 34。一个 id 的键只看 G、place[id] 和它自己，
 *    和别的列画了什么无关。
 *  rows(K) → {layers: [每一行的 y，按 (y, s) 排，子行重复 y], layerOf: {id: 行号}, x: {id: x}}
 *    lanes.js：S.layers = layers，S.layerOf = layerOf，S.nodeH[id] = K[id].h。
 *  colRows(ids, R) → {行号: [ids]}：一列的 rows（S.cols[ci].rows），每行按 (x, id) 排——同一个 B 里的几个子节点 x 一样，按 id 分先后，
 *    各列一样。
 *  pack(col, S) → {base, rel, rows, frel, span, parent, home}
 *    col：S.cols[ci]，用到 rows {行号: [ids，输入的左右顺序]}、frames {fid: {parent: fid | null, minw}}（这一列画的框，不含唯一的根）、
 *    frameOf {id: 最里层的 fid | null}；S：用到 NW、GAP、PAD、MINW。
 *    base：列的基础宽（两侧竖轨之外）；rel：{id: 节点中心离列左边多远}；rows：{行号: [ids，按 rel 从左到右]}；
 *    frel：{fid: [x0, x1]}（离列左边）；span：{fid: [第一行, 最后一行]}；parent：{fid: 留下的外层框 | null}；home：{id: 最里层的框 | null}。
 *    没有节点的框不画（frel 等里都没有它）；frames 里没有的 fid 当没有框。
 *  常量：FH 框头高、FB 嵌套的框底一层错开多少、FPAD 框里左右留白、PGAP 同一行相邻两块之间的空隙、BTN 框头 − 的中心离框左边多远、
 *  CLEAR 线离 − 的中心至少多远。 */
(function (root) {
  'use strict';
  var FH = 20,      // 框头高（− + 名字 + 几个）
      FB = 8,       // 嵌套的框在同一行结束：里层的框底比外层的高这么多
      FPAD = 22,    // 框里左右留白：框头的 − 在框左边 BTN 处（半径 7），最左的节点的接点（离节点边至少 2% 宽）离它也有 8 以上
      PGAP = 14,    // 同一行里相邻两块（框和框、框和散节点）之间的空隙
      BTN = 15,     // 框头 − 的中心离框左边、离框顶（FH / 2）多远（同模块图 graph.js）
      CLEAR = 8,    // 线离 − 的中心至少这么远（不压按钮，点 − 不会点成线）
      NH = 34,      // 节点默认高
      EXTRA = 70;   // 不在图上的节点：放在最低的那一行下面这么多

  function byId(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function keys(G, ids, place, contains) {
    var at = {}, ns = G.nodes || [], y1 = null, K = {};
    ns.forEach(function (n) { at[n.id] = n; y1 = y1 == null ? n.cy : Math.max(y1, n.cy); });
    var extra = (y1 || 0) + EXTRA;
    ids.forEach(function (id) {
      if (K[id]) return;
      var n = at[id], pl = (place || {})[id];
      if (n) { K[id] = { y: n.cy, s: 0, x: n.x || 0, h: n.h || NH }; return; }
      if (pl && at[pl[0]]) { K[id] = { y: at[pl[0]].cy, s: pl[1] || 0, x: at[pl[0]].x || 0, h: NH }; return; }
      var y = null, x = null;                       // 比图上的粗：盖住的那几个里最高的一行、最左的
      ns.forEach(function (m) {
        if (!contains(id, m.id)) return;
        y = y == null ? m.cy : Math.min(y, m.cy); x = x == null ? (m.x || 0) : Math.min(x, m.x || 0);
      });
      K[id] = y != null ? { y: y, s: 0, x: x, h: NH } : { y: extra, s: 0, x: 0, h: NH };
    });
    return K;
  }

  function rows(K) {
    var ids = Object.keys(K), at = {}, ks = [];
    function tag(k) { return k.y + '|' + k.s; }
    ids.forEach(function (id) { var t = tag(K[id]); if (at[t] == null) { at[t] = 0; ks.push(K[id]); } });
    ks.sort(function (a, b) { return a.y - b.y || a.s - b.s; });
    ks.forEach(function (k, i) { at[tag(k)] = i; });
    var layerOf = {}, x = {};
    ids.forEach(function (id) { layerOf[id] = at[tag(K[id])]; x[id] = K[id].x; });
    return { layers: ks.map(function (k) { return k.y; }), layerOf: layerOf, x: x };
  }

  function colRows(ids, R) {
    var out = {};
    ids.forEach(function (id) { var l = R.layerOf[id]; if (l != null) (out[l] = out[l] || []).push(id); });
    Object.keys(out).forEach(function (l) { out[l].sort(function (a, b) { return (R.x[a] || 0) - (R.x[b] || 0) || byId(a, b); }); });
    return out;
  }

  function pack(col, S) {
    var NW = S.NW, GAP = S.GAP, R = col.rows || {}, F = col.frames || {}, fof = col.frameOf || {};
    var ls = Object.keys(R).map(Number).sort(function (a, b) { return a - b; }), nF = Object.keys(F).length;
    var rank = {};                                   // 这一列自己有节点的行排第几：别的列多出来的子行不改它，框的轨道就不跟着变
    ls.forEach(function (l, i) { rank[l] = i; });
    // 1. 留下有节点的框；外层框不在 frames 里就当没有（框都来自 serve，是一棵树；有环也不死循环）
    function up(f) { var p = F[f].parent; return p != null && F[p] && p !== f ? p : null; }
    var home = {}, kept = {}, span = {}, parent = {};
    ls.forEach(function (l) {
      R[l].forEach(function (id) {
        var f = fof[id] != null && F[fof[id]] ? fof[id] : null;
        home[id] = f;
        for (var g = f, k = 0; g != null && k <= nF; g = up(g), k++) {
          kept[g] = 1;
          span[g] = span[g] ? [Math.min(span[g][0], l), Math.max(span[g][1], l)] : [l, l];
        }
      });
    });
    var fs = Object.keys(kept).sort(byId);
    fs.forEach(function (f) {
      parent[f] = up(f);
      for (var p = parent[f], k = 0; p != null; p = up(p)) if (p === f || ++k > nF) { parent[f] = null; break; }
    });
    // 区域：整列（null）或一个框；kids 是直接在它里面的框，leaf 是直接在它里面的节点（按行，保持输入的左右顺序）
    var top = { kids: [], leaf: {} }, reg = {};
    fs.forEach(function (f) { reg[f] = { kids: [], leaf: {} }; });
    function regOf(a) { return a == null ? top : reg[a]; }
    fs.forEach(function (f) { regOf(parent[f]).kids.push(f); });
    ls.forEach(function (l) { R[l].forEach(function (id) { var g = regOf(home[id]).leaf; (g[l] = g[l] || []).push(id); }); });

    // 2. 轨道：跨的行多的在左，一样多按名字；跨的行不重叠的框叠在同一条轨道里（first-fit）
    function tracksOf(list) {
      function len(f) { return rank[span[f][1]] - rank[span[f][0]]; }
      var T = [];
      list.slice().sort(function (a, b) { return len(b) - len(a) || byId(a, b); }).forEach(function (f) {
        var lo = rank[span[f][0]], hi = rank[span[f][1]], i;
        for (i = 0; i < T.length; i++) if (!T[i].iv.some(function (r) { return r[0] <= hi && lo <= r[1]; })) break;
        if (i === T.length) T.push({ fs: [], iv: [] });
        T[i].fs.push(f); T[i].iv.push([lo, hi]);
      });
      return T;
    }
    // 3. 宽：从里往外。ends[行的名次] 是最后一个跨过这一行的轨道的右边（离区域里面的左边）
    var W = {};
    function measure(a) {
      var g = regOf(a);
      g.kids.forEach(measure);
      var T = g.T = tracksOf(g.kids), x = 0, ends = g.ends = {}, inner = 0;
      T.forEach(function (t) {
        t.w = Math.max.apply(null, t.fs.map(function (f) { return W[f]; }));
        x += t.w;
        t.iv.forEach(function (r) { for (var k = r[0]; k <= r[1]; k++) ends[k] = x; });
        x += PGAP;
        inner = x - PGAP;
      });
      Object.keys(g.leaf).forEach(function (l) {
        var e = ends[rank[l]] || 0;
        inner = Math.max(inner, e + (e ? PGAP : 0) + g.leaf[l].length * (NW + GAP) - GAP);
      });
      if (a != null) W[a] = Math.max(inner + 2 * FPAD, F[a].minw || 0);
      return inner;
    }
    var base = Math.max(S.MINW, measure(null) + 2 * S.PAD);
    // 4. 放：轨道从左往右，框占 [x, x + 自己的宽]；散节点在 [这一行最后一个轨道的右边 + PGAP, 右边] 里居中
    var rel = {}, frel = {};
    function place(a, x0, x1) {
      var g = regOf(a), pad = a == null ? S.PAD : FPAD, x = x0 + pad;
      g.T.forEach(function (t) {
        t.fs.forEach(function (f) { frel[f] = [x, x + W[f]]; place(f, x, x + W[f]); });
        x += t.w + PGAP;
      });
      Object.keys(g.leaf).forEach(function (l) {
        var ids = g.leaf[l], e = g.ends[rank[l]] || 0, lo = x0 + pad + e + (e ? PGAP : 0), hi = x1 - pad;
        var s = (lo + hi - (ids.length * (NW + GAP) - GAP)) / 2;
        ids.forEach(function (id, i) { rel[id] = s + i * (NW + GAP) + NW / 2; });
      });
    }
    place(null, 0, base);
    var out = {};
    ls.forEach(function (l) { out[l] = R[l].slice().sort(function (a, b) { return rel[a] - rel[b]; }); });
    return { base: base, rel: rel, rows: out, frel: frel, span: span, parent: parent, home: home };
  }

  var CS = root.CS = root.CS || {};
  CS.lanePack = { keys: keys, rows: rows, colRows: colRows, pack: pack,
                  FH: FH, FB: FB, FPAD: FPAD, PGAP: PGAP, BTN: BTN, CLEAR: CLEAR };
})(typeof window !== 'undefined' ? window : globalThis);
