/* 按进程 · 线程分列的排线：节点放在哪、每条线怎么走（纯函数，不碰 DOM；lanes.js 拿去画，test_web 在 node 里测）。
 *
 * 用户 10-01：「所有的 arrow 都 tight 在一起了很难点击到，想办法 spread 一下」「你再研究一下排线」。每条线有自己的接点、自己的轨道，
 * 不和别的线叠成一根；轨道的先后按「交叉最少」排（ELK Layered 的正交排线，Sander GD 2003）：
 *  - 「轨带」：每一层节点上面一条（2·层）、下面一条（2·层 + 1），两层之间的空隙里是上一层的下带和这一层的上带；
 *  - 列里的边：往下的从 a 的底边 S 形落进 b 的顶边——隔层的只要中间几层在这一列里没有节点挡着也这样走；同一层的走上带；
 *    挡着的（隔层往下、往上）沿列的左 / 右侧竖着走：a 是这一行最靠那一侧的节点时从它的侧面出来（每面最多 4 条），
 *    否则从底边 / 顶边进轨带再拐过去；都从顶边进 b。左右两侧按「同一侧的几条只能套着、不能交错」分（长的先挑），
 *    竖轨先占列里节点旁边空着的地方，不够才把列加宽；
 *  - 列之间的连线：往右的从节点顶边出来走上带，往左的从底边出来走下带、从底边进终点（用户 10-01：一来一回的两条「一个从上面走
 *    一个从下面走，类似于一个 loop」）；两头在同一层就在这条轨带里横着走，不在同一层就在终点那一列旁边的缝里竖着走到终点那一层。
 *    接在列头上的（没有节点的列、收起的进程）走第一层的上带；
 *  - 先排竖轨（列两侧、列之间的缝），再按竖轨和接点的真实横坐标排轨带；接点按轨道的先后排（往左拐的在左、往右拐的在右，
 *    近的在里），排完再排一遍轨带，来回两次；
 *  - 轨带放不下就把下面的层整体往下推（所有列一起推，同一个节点在各列里还是同一高度），有空余高度的轨带把轨道间距放宽到 14。
 * 选线（picker）：点哪条按离鼠标最近的那条算，不靠 SVG 命中区谁叠在上面。 */
(function (root) {
  'use strict';
  var TS = 10,      // 轨带里横轨的最小间距（ELK 的默认值）；有空余高度时放宽到 TSMAX
      TSMAX = 14,
      VS = 8,       // 列两侧、列之间的缝里竖轨的间距
      RAD = 5,      // 拐角的圆角
      ARROW = 3,    // 箭头停在节点外面几个像素
      PMAX = 16, PMIN = 8,   // 节点一条边上接点的间距（不小于箭头宽；接点太多时再挤，但不出节点的边）
      FMAX = 4;     // 节点侧面最多出几条

  /* 一条轨带（或一条竖的通道）里各段的先后（ELK 的 OrthogonalRoutingGenerator）。segs：[{lo, hi, conns: [{p, s, pk}]}]，
     lo..hi 是沿通道方向的范围，conns 是两头拐出去的地方：p 是位置，s = -1 拐向低的一侧、+1 拐向高的一侧（横轨带的低侧是上面）。
     两段重叠（隔不到 gap）时数两种放法各交叉几次，便宜的那种记成「谁在低侧」的一条约束；一样多时 tie(a, b) < 0 表示 a 放低侧。
     两头接在同一条节点边上的那种交叉不算（接点重排能消掉）。约束有环时按 Eades–Lin–Smyth 去掉最少的。
     每段得到 rl（从低侧数第几条）、rh（从高侧数第几条）；返回一共几条轨道 */
  function order(segs, gap, tie) {
    var n = segs.length, E = [];
    if (!n) return 0;
    function cnt(s, side, lo, hi, o) {
      var c = 0;
      s.conns.forEach(function (q) {
        if (q.s !== side || q.p < lo - 0.5 || q.p > hi + 0.5) return;
        if (q.pk && o.conns.some(function (r) { return r.pk === q.pk; })) return;
        c++;
      });
      return c;
    }
    for (var i = 0; i < n; i++) for (var j = i + 1; j < n; j++) {
      var a = segs[i], b = segs[j];
      if (!(b.lo < a.hi + gap && a.lo < b.hi + gap)) continue;
      var c1 = cnt(a, 1, b.lo, b.hi, b) + cnt(b, -1, a.lo, a.hi, a);   // a 在 b 的低侧时的交叉
      var c2 = cnt(b, 1, a.lo, a.hi, a) + cnt(a, -1, b.lo, b.hi, b);
      if (c1 < c2) E.push([i, j, c2 - c1]);
      else if (c2 < c1) E.push([j, i, c1 - c2]);
      else E.push(tie(a, b) < 0 ? [i, j, 0] : [j, i, 0]);
    }
    // Eades–Lin–Smyth：反复摘掉只出不进的（放前面）、只进不出的（放后面），都没有时摘「出 - 进」最大的
    var out = [], inn = [], adj = [], rem = [], s1 = [], s2 = [], left = n;
    for (i = 0; i < n; i++) { out[i] = 0; inn[i] = 0; adj[i] = []; }
    E.forEach(function (e) { out[e[0]] += 1 + e[2]; inn[e[1]] += 1 + e[2]; adj[e[0]].push(e); adj[e[1]].push(e); });
    function drop(v) {
      rem[v] = 1; left--;
      adj[v].forEach(function (e) { if (e[0] === v) inn[e[1]] -= 1 + e[2]; else out[e[0]] -= 1 + e[2]; });
    }
    while (left) {
      var changed = true;
      while (changed) {
        changed = false;
        for (var v = 0; v < n; v++) {
          if (rem[v]) continue;
          if (!out[v]) { s2.unshift(v); drop(v); changed = true; }
          else if (!inn[v]) { s1.push(v); drop(v); changed = true; }
        }
      }
      if (!left) break;
      var best = -1, bd = -Infinity;
      for (v = 0; v < n; v++) if (!rem[v] && out[v] - inn[v] > bd) { bd = out[v] - inn[v]; best = v; }
      s1.push(best); drop(best);
    }
    var ord = s1.concat(s2), at = [];
    ord.forEach(function (v2, k) { at[v2] = k; });
    var succ = segs.map(function () { return []; }), pred = segs.map(function () { return []; });
    E.forEach(function (e) {
      var u = e[0], w = e[1];
      if (at[u] > at[w]) { var t = u; u = w; w = t; }             // 环上去掉的那几条反过来
      succ[u].push(w); pred[w].push(u);
    });
    var rl = [], rh = [], m = 0;
    ord.forEach(function (v2) { rl[v2] = 0; pred[v2].forEach(function (u) { rl[v2] = Math.max(rl[v2], rl[u] + 1); }); m = Math.max(m, rl[v2]); });
    ord.slice().reverse().forEach(function (v2) { rh[v2] = 0; succ[v2].forEach(function (u) { rh[v2] = Math.max(rh[v2], rh[u] + 1); }); });
    segs.forEach(function (s, k) { s.rl = rl[k]; s.rh = rh[k]; });
    return m + 1;
  }

  function r1(v) { return Math.round(v * 10) / 10; }

  /* 折线 → 带圆角的 path；pts 是选线用的折线（圆角处差不到 2 像素） */
  function poly(pts) {
    var P = [];
    pts.forEach(function (p) {                     // 去掉重复点、共线的中间点
      var q = P[P.length - 1];
      if (q && Math.abs(q[0] - p[0]) < 0.01 && Math.abs(q[1] - p[1]) < 0.01) return;
      var o = P[P.length - 2];
      if (o && q && ((Math.abs(o[0] - q[0]) < 0.01 && Math.abs(q[0] - p[0]) < 0.01) || (Math.abs(o[1] - q[1]) < 0.01 && Math.abs(q[1] - p[1]) < 0.01))) P.pop();
      P.push(p);
    });
    var d = 'M' + r1(P[0][0]) + ',' + r1(P[0][1]);
    for (var i = 1; i < P.length; i++) {
      var p = P[i];
      if (i === P.length - 1) { d += ' L' + r1(p[0]) + ',' + r1(p[1]); break; }
      var a = P[i - 1], b = P[i + 1];
      var la = Math.hypot(p[0] - a[0], p[1] - a[1]), lb = Math.hypot(b[0] - p[0], b[1] - p[1]);
      var r = Math.min(RAD, la / 2, lb / 2);
      var p1 = [p[0] - (p[0] - a[0]) / la * r, p[1] - (p[1] - a[1]) / la * r];
      var p2 = [p[0] + (b[0] - p[0]) / lb * r, p[1] + (b[1] - p[1]) / lb * r];
      d += ' L' + r1(p1[0]) + ',' + r1(p1[1]) + ' Q' + r1(p[0]) + ',' + r1(p[1]) + ' ' + r1(p2[0]) + ',' + r1(p2[1]);
    }
    return { d: d, pts: P };
  }

  /* 从 a 的底边 S 形落进 b 的顶边 */
  function scurve(sx, y1, ex, ey) {
    var my = (y1 + ey) / 2, pts = [];
    for (var i = 0; i <= 20; i++) {                 // 选线用的折线：三次贝塞尔取 21 个点
      var t = i / 20, u = 1 - t;
      pts.push([u * u * u * sx + 3 * u * u * t * sx + 3 * u * t * t * ex + t * t * t * ex,
                u * u * u * y1 + 3 * u * u * t * my + 3 * u * t * t * my + t * t * t * ey]);
    }
    return { d: 'M' + r1(sx) + ',' + r1(y1) + ' C' + r1(sx) + ',' + r1(my) + ' ' + r1(ex) + ',' + r1(my) + ' ' + r1(ex) + ',' + r1(ey), pts: pts };
  }

  /* S：{NW, GAP, PAD, MINW, EXTW, FOLDW, headY, top,
         layers: [各层中心的基准纵坐标，递增], layerOf: {节点: 层号}, nodeH: {节点: 高},
         cols: [{fold, external, lanes: [列 id], rows: {层号: [节点（从左到右）]}, gap: 这一列左边的缝的基础宽}],
         edges: [{key, lane, a, b}]（列里的边）, links: [{key, from: {lane, node}, to: {lane, node}}]（列之间）,
         reserve: {"列|节点": 节点上方要留的高（「▶ 起 / ■ 收」）}, gapEnd: 最右边的缝}
     → {W, H, cols: [{x, w}], pos: {"列|节点": {cx, cy, w, h}}, heads: [列头接线处 {cx, cy, w, h, head}],
        paths: {key: {d, pts, low}}, layerY: [...], tracks: {ch: [各轨带几条横轨], side, gut}} */
  function route(S) {
    var nL = S.layers.length, nC = S.cols.length, colOf = {};
    // 1. 列的基础宽、节点在列里的相对位置（列两侧的竖轨、列之间的缝还没算）
    var C = S.cols.map(function (c, ci) {
      c.lanes.forEach(function (l) { colOf[l] = ci; });
      var base = S.MINW, rel = {};
      if (c.fold) base = S.FOLDW;
      else if (c.external) base = S.EXTW;
      else {
        var most = 0;
        Object.keys(c.rows).forEach(function (k) { most = Math.max(most, c.rows[k].length); });
        base = Math.max(S.MINW, most * (S.NW + S.GAP) - S.GAP + 2 * S.PAD);
        Object.keys(c.rows).forEach(function (k) {
          var ids = c.rows[k], span = ids.length * (S.NW + S.GAP) - S.GAP, x0 = (base - span) / 2;
          ids.forEach(function (id, i) { rel[id] = x0 + i * (S.NW + S.GAP) + S.NW / 2; });
        });
      }
      return { c: c, base: base, rel: rel };
    });
    var ax = [], x = 0;                              // 粗略的横坐标：先排接点、挑侧边、排竖轨用；竖轨排完换成最后的（第 4 步）
    C.forEach(function (c, ci) { x += S.cols[ci].gap; ax[ci] = x; x += c.base; });
    function axNode(lane, id) { var ci = colOf[lane]; return ax[ci] + C[ci].rel[id]; }
    function axGut(g) { return g < nC ? ax[g] - S.cols[g].gap / 2 : ax[nC - 1] + C[nC - 1].base + (S.gapEnd || 8) / 2; }
    function freeRow(ci, l, L) {                    // 第 l 行里列边到最靠边的节点之间空着多宽
      var ids = (C[ci].c.rows || {})[l];
      if (!ids || !ids.length) return C[ci].base;
      var xs = ids.map(function (id) { return C[ci].rel[id]; });
      return L ? Math.min.apply(null, xs) - S.NW / 2 : C[ci].base - Math.max.apply(null, xs) - S.NW / 2;
    }
    function spanFree(ci, lo, hi, L) {              // 竖轨从轨带 lo 到 hi 经过的那几行里最窄的空
      var f = Infinity;
      for (var l = 0; l < nL; l++) if (lo - 0.5 <= 2 * l && 2 * l + 1 <= hi + 0.5) f = Math.min(f, freeRow(ci, l, L));
      return f;
    }
    var maxh = [];
    C.forEach(function (c) {
      Object.keys(c.c.rows || {}).forEach(function (k) {
        c.c.rows[k].forEach(function (id) { var li = S.layerOf[id]; maxh[li] = Math.max(maxh[li] || 0, S.nodeH[id] || 34); });
      });
    });
    for (var li = 0; li < nL; li++) maxh[li] = maxh[li] || 34;

    // 2. 每条线走哪几段。横段在一条轨带里，两头各是一个接点 {port} 或一条竖轨 {v}；竖轨在列的一侧或一条缝里
    var H = [], side = {}, gut = {}, ports = {}, plan = {}, sideEdges = [], pkAt = {};
    // 接点挂在哪条边上：pk 是「列|节点|t / b」或「head|列号」，pkAt 记它属于哪个节点（节点 id 里可能有 |，不从字符串里拆）
    function npk(lane, id, s) { var pk = lane + '|' + id + '|' + s; pkAt[pk] = { lane: lane, id: id }; return pk; }
    function port(pk, key, end, other) { var p = { key: key, end: end, other: other, pk: pk }; (ports[pk] = ports[pk] || []).push(p); return p; }
    function hseg(ch, e1, e2, key) { var h = { ch: ch, e: [e1, e2], key: key }; H.push(h); if (e1.port) e1.port.h = h; if (e2.port) e2.port.h = h; return h; }
    function vseg(bag, k, c1, c2, key) { var v = { lo: Math.min(c1, c2), hi: Math.max(c1, c2), key: key, bag: k }; (bag[k] = bag[k] || []).push(v); return v; }
    function clear(ci, i, j, xa, xb) {               // 第 i 层和第 j 层之间（不含两头）这一列里没有节点挡着 xa..xb
      var lo = Math.min(xa, xb) - S.NW / 2 - 6, hi = Math.max(xa, xb) + S.NW / 2 + 6, rows = C[ci].c.rows || {};
      for (var k = i + 1; k < j; k++)
        if ((rows[k] || []).some(function (id) { var x1 = ax[ci] + C[ci].rel[id]; return x1 > lo && x1 < hi; })) return false;
      return true;
    }
    (S.edges || []).forEach(function (e) {
      var ci = colOf[e.lane];
      if (ci == null || C[ci].rel[e.a] == null || C[ci].rel[e.b] == null) return;
      var i = S.layerOf[e.a], j = S.layerOf[e.b], ka = e.lane + '|' + e.a, kb = e.lane + '|' + e.b;
      var xa = axNode(e.lane, e.a), xb = axNode(e.lane, e.b);
      if (j === i + 1 || (j > i + 1 && clear(ci, i, j, xa, xb))) {
        plan[e.key] = { type: 'adj', a: ka, b: kb };
        port(npk(e.lane, e.a, 'b'), e.key, 0, xb); port(npk(e.lane, e.b, 't'), e.key, 1, xa);
      } else if (j === i) {
        var pa = port(npk(e.lane, e.a, 't'), e.key, 0, xb), pb = port(npk(e.lane, e.b, 't'), e.key, 1, xa);
        plan[e.key] = { type: 'same', a: ka, b: kb, h: hseg(2 * i, { port: pa }, { port: pb }, e.key) };
      } else {
        var down = j > i;
        var q = { type: 'side', key: e.key, a: ka, b: kb, ida: e.a, idb: e.b, ci: ci, i: i, j: j, down: down,
                  c1: down ? 2 * i + 1 : 2 * i, c2: 2 * j, xa: xa, xb: xb };
        q.pa = port(npk(e.lane, e.a, down ? 'b' : 't'), e.key, 0, ax[ci]); q.pb = port(npk(e.lane, e.b, 't'), e.key, 1, ax[ci]);
        plan[e.key] = q; sideEdges.push(q);
      }
    });
    // 2b. 走列的哪一侧：同一侧的只能套着、不能交错（长的先挑；交错一次罚 100，和两头的中点不在一边罚 2，再看哪边少）
    var byCol = {}, faces = {};
    sideEdges.forEach(function (q) { (byCol[q.ci] = byCol[q.ci] || []).push(q); });
    Object.keys(byCol).forEach(function (ci) {
      var on = { L: [], R: [] };
      byCol[ci].slice().sort(function (p, r) { return (Math.abs(r.c2 - r.c1) - Math.abs(p.c2 - p.c1)) || (p.key < r.key ? -1 : 1); })
        .forEach(function (q) {
          var lo = Math.min(q.c1, q.c2), hi = Math.max(q.c1, q.c2), mid = (q.xa + q.xb) / 2 - (ax[q.ci] + C[q.ci].base / 2);
          function cost(sd) {
            var c = 0;
            on[sd].forEach(function (r) {
              var l2 = Math.min(r.c1, r.c2), h2 = Math.max(r.c1, r.c2);
              if ((lo < l2 && l2 < hi && hi < h2) || (l2 < lo && lo < h2 && h2 < hi)) c++;
            });
            return c * 100 + (sd === 'L' ? mid > 0 : mid < 0) * 2 + on[sd].length * 0.01;
          }
          q.L = cost('L') < cost('R');
          on[q.L ? 'L' : 'R'].push(q);
        });
    });
    function unport(p) { var P = ports[p.pk], k = P.indexOf(p); if (k >= 0) P.splice(k, 1); if (!P.length) delete ports[p.pk]; }
    function outer(ci, l, id, L) { var r = C[ci].c.rows[l]; return r && (L ? r[0] : r[r.length - 1]) === id; }
    sideEdges.forEach(function (q) {
      var L = q.L, fa = q.a + '|' + (L ? 'l' : 'r');
      if (outer(q.ci, q.i, q.ida, L) && (faces[fa] || []).length < FMAX) {     // a 是这一行最靠这一侧的：从它的侧面出来
        unport(q.pa); q.fa = fa; q.c1 = 2 * q.i + 0.5; (faces[fa] = faces[fa] || []).push({ q: q });
      }
      q.v = vseg(side, q.ci + (L ? 'L' : 'R'), q.c1, q.c2, q.key);
      q.v.ends = [{ c: q.c1, s: L ? 1 : -1, pk: q.fa }, { c: q.c2, s: L ? 1 : -1 }];   // 横段都往列里面拐
      q.pa.other = q.pb.other = L ? ax[q.ci] : ax[q.ci] + C[q.ci].base;
      if (!q.fa) q.h1 = hseg(q.c1, { port: q.pa }, { v: q.v }, q.key);
      q.h2 = hseg(q.c2, { v: q.v }, { port: q.pb }, q.key);
    });
    function endOf(e) {
      var ci = colOf[e.lane];
      if (ci == null) return null;
      if (!S.cols[ci].fold && e.node && C[ci].rel[e.node] != null)
        return { node: e.lane + '|' + e.node, lane: e.lane, id: e.node, li: S.layerOf[e.node], x: axNode(e.lane, e.node), ci: ci };
      return { pk: 'head|' + ci, head: ci, ch: 0, x: ax[ci] + C[ci].base / 2, ci: ci };
    }
    function under(A, low) {                         // 一头接在节点的顶边（上带）还是底边（下带）
      if (A.head != null) return;
      A.low = low; A.ch = 2 * A.li + (low ? 1 : 0); A.pk = npk(A.lane, A.id, low ? 'b' : 't');
    }
    (S.links || []).forEach(function (k) {
      var A = endOf(k.from), B = endOf(k.to);
      if (!A || !B || (A.head != null && A.head === B.head)) return;   // 收起的同一个进程里的
      var low = A.head == null && B.head == null && B.x < A.x;          // 往左的走下面
      under(A, low); under(B, low);
      if (A.ch === B.ch) {
        var pa = port(A.pk, k.key, 0, B.x), pb = port(B.pk, k.key, 1, A.x);
        plan[k.key] = { type: 'link1', A: A, B: B, h: hseg(A.ch, { port: pa }, { port: pb }, k.key) };
      } else {
        var g = A.ci < B.ci ? B.ci : B.ci + 1, gx = axGut(g), v = vseg(gut, g, A.ch, B.ch, k.key);
        v.ends = [{ c: A.ch, s: A.x < gx ? -1 : 1 }, { c: B.ch, s: B.x < gx ? -1 : 1 }];
        var pa2 = port(A.pk, k.key, 0, gx), pb2 = port(B.pk, k.key, 1, gx);
        plan[k.key] = { type: 'link2', A: A, B: B, g: g, v: v,
                        h1: hseg(A.ch, { port: pa2 }, { v: v }, k.key), h2: hseg(B.ch, { v: v }, { port: pb2 }, k.key) };
      }
    });

    // 3. 接点：先按另一头的横坐标排开
    var off = {};
    function pkX(pk) {
      var m = pkAt[pk];
      var ci = +pk.slice(5);                        // 列头：竖轨排完之后是最后的列中间
      return m ? axNode(m.lane, m.id) : colX && colX.length ? colX[ci] + colW[ci] / 2 : ax[ci] + C[ci].base / 2;
    }
    function place(pk, P) {
      var n = P.length, w = pkAt[pk] ? S.NW : Math.min(C[+pk.slice(5)].base - 10, S.NW);
      var sp = n > 1 ? Math.min(Math.max(PMIN, Math.min(PMAX, w * 0.88 / (n - 1))), w * 0.96 / (n - 1)) : 0;
      P.forEach(function (p, i) { off[p.key + '|' + p.end] = -sp * (n - 1) / 2 + sp * i; });
    }
    Object.keys(ports).forEach(function (pk) {
      ports[pk].sort(function (p, q) { return p.other - q.other || (p.key < q.key ? -1 : p.key > q.key ? 1 : p.end - q.end); });
      place(pk, ports[pk]);
    });
    function portX(p) { return pkX(p.pk) + (off[p.key + '|' + p.end] || 0); }

    // 4. 竖轨先排：列两侧的（长的在外）、缝里的；竖轨先占列里节点旁边空着的地方，不够才加宽（wSide）
    var nSide = {}, nGut = {}, wSide = {};
    Object.keys(side).forEach(function (k) {
      var L = k.slice(-1) === 'L';
      side[k].forEach(function (v) { v.conns = v.ends.map(function (e) { return { p: e.c, s: e.s, pk: e.pk }; }); });
      nSide[k] = order(side[k], 1, function (a, b) { var la = a.hi - a.lo, lb = b.hi - b.lo; return L ? (la >= lb ? -1 : 1) : (la >= lb ? 1 : -1); });
      side[k].forEach(function (v) { v.t = L ? v.rh : v.rl; v.to = nSide[k] - 1 - v.t; });    // to：从列边往里数第几条
      var ci = parseInt(k, 10), w = 0;
      side[k].forEach(function (v) { w = Math.max(w, 10 + v.to * VS - spanFree(ci, v.lo, v.hi, L)); });   // 离节点至少 6
      wSide[k] = w;
    });
    Object.keys(gut).forEach(function (k) {
      gut[k].forEach(function (v) { v.conns = v.ends.map(function (e) { return { p: e.c, s: e.s }; }); });
      nGut[k] = order(gut[k], 1, function (a, b) { return a.lo <= b.lo ? -1 : 1; });
      gut[k].forEach(function (v) { v.t = v.rl; });
    });
    // 横向到这里就定了（竖轨的条数、列两侧加多宽都有了），之后排轨带、重排接点用的都是最后的横坐标
    var colX = [], colW = [], area = [], gutX = [], gutW = [];
    x = 0;
    for (var ci = 0; ci <= nC; ci++) {
      var gw0 = ci < nC ? S.cols[ci].gap : (S.gapEnd || 8);
      gutX[ci] = x; gutW[ci] = Math.max(gw0, (nGut[ci] || 0) * VS + 8); x += gutW[ci];
      if (ci === nC) break;
      var wl = wSide[ci + 'L'] || 0, wr = wSide[ci + 'R'] || 0;
      colX[ci] = x; area[ci] = x + wl; colW[ci] = wl + C[ci].base + wr; x += colW[ci];
    }
    var W = x;
    ax = area;                                       // 节点、接点的横坐标从这里起都是最后的
    function sideX(v) { var c3 = parseInt(v.bag, 10); return v.bag.slice(-1) === 'L' ? colX[c3] + 4 + v.to * VS : colX[c3] + colW[c3] - 4 - v.to * VS; }
    function gutTX(g, t) { var n = nGut[g] || 0; return gutX[g] + gutW[g] / 2 - (n - 1) * VS / 2 + t * VS; }
    function vX(v) { return typeof v.bag === 'number' ? gutTX(v.bag, v.t) : sideX(v); }
    var foff = {};
    Object.keys(faces).forEach(function (fk) {      // 侧面的接点：往上的在上（里面的在上），往下的在下（外面的在上），互不交叉
      var F = faces[fk];
      F.forEach(function (f) { var q = f.q, up = q.c2 < q.c1; f.r = up ? [0, -q.v.to] : [1, q.v.to]; });
      F.sort(function (a, b) { return a.r[0] - b.r[0] || a.r[1] - b.r[1]; });
      var n = F.length, sp = n > 1 ? Math.min(8, 24 / (n - 1)) : 0;
      F.forEach(function (f, i) { foff[f.q.key] = -sp * (n - 1) / 2 + sp * i; });
    });

    // 5. 轨带：按接点和竖轨的横坐标排；接点再按轨道的先后重排（往左拐的在左、往右拐的在右，近的在里），来回两次
    var nCh = [];
    function endX(e) { return e.port ? portX(e.port) : vX(e.v); }
    function endS(e, ch) {                           // 这一头从轨带拐向哪一侧（上 -1 / 下 +1）
      if (e.port) return pkAt[e.port.pk] ? (ch % 2 ? -1 : 1) : -1;
      var other = e.v.lo === ch ? e.v.hi : e.v.lo;
      return other > ch ? 1 : -1;
    }
    function bands() {
      H.forEach(function (h) {
        var x1 = endX(h.e[0]), x2 = endX(h.e[1]);
        h.lo = Math.min(x1, x2); h.hi = Math.max(x1, x2);
        h.conns = [{ p: x1, s: endS(h.e[0], h.ch), pk: h.e[0].port && h.e[0].port.pk },
                   { p: x2, s: endS(h.e[1], h.ch), pk: h.e[1].port && h.e[1].port.pk }];
      });
      for (var c = 0; c < 2 * nL; c++) {
        var segs = H.filter(function (h) { return h.ch === c; }), up = c % 2 === 0;
        // 上带：节点在高的一侧（下面），长的放外面（低侧）；下带反过来
        nCh[c] = order(segs, 8, function (a, b) { var la = a.hi - a.lo, lb = b.hi - b.lo; return up ? (la >= lb ? -1 : 1) : (la >= lb ? 1 : -1); });
        segs.forEach(function (h) { h.t = up ? h.rh : h.rl; });                 // t：从节点往外数第几条
      }
    }
    bands();
    for (var it = 0; it < 2; it++) {
      Object.keys(ports).forEach(function (pk) {
        var P = ports[pk], x0 = pkX(pk);
        P.forEach(function (p) {
          if (!p.h) { p.g = 1; p.r = p.other; return; }
          var far = p.h.e[0].port === p ? endX(p.h.e[1]) : endX(p.h.e[0]);
          if (far < x0) { p.g = 0; p.r = p.h.t; } else { p.g = 2; p.r = -p.h.t; }
        });
        P.sort(function (p, q) { return p.g - q.g || p.r - q.r || (p.key < q.key ? -1 : p.key > q.key ? 1 : p.end - q.end); });
        place(pk, P);
      });
      bands();
    }

    // 6. 撑开：轨带不够高往下推；有空余的把轨道间距放宽
    var reserve = [];
    C.forEach(function (c) {
      c.c.lanes.forEach(function (lane) {
        Object.keys(c.c.rows || {}).forEach(function (k) {
          c.c.rows[k].forEach(function (id) {
            var l = S.layerOf[id];
            reserve[l] = Math.max(reserve[l] || 0, (S.reserve || {})[lane + '|' + id] || 0);
          });
        });
      });
    });
    function band(b) { return nCh[b] ? 6 + nCh[b] * TS + 4 : 0; }    // 一条轨带要的高
    var layerY = [], shift = 0, pitch = [];
    for (var c = 0; c < nL; c++) {
      reserve[c] = reserve[c] || 0;
      var need = reserve[c] + 6 + band(2 * c) + (c > 0 ? band(2 * c - 1) : 0);
      var have = c === 0 ? (S.top - maxh[0] / 2) - (S.headY + 6) : (S.layers[c] - S.layers[c - 1]) - maxh[c] / 2 - maxh[c - 1] / 2;
      shift += Math.max(0, need - have);
      layerY[c] = S.top + (S.layers[c] - S.layers[0]) + shift;
      var nt = (nCh[2 * c] || 0) + (c > 0 ? (nCh[2 * c - 1] || 0) : 0);
      if (nt) { var pt = Math.min(TSMAX, TS + Math.max(0, have - need) / (nt + 1)); pitch[2 * c] = pt; if (c > 0) pitch[2 * c - 1] = pt; }
    }
    // 7. 坐标、路径
    var pos = {}, heads = [];
    C.forEach(function (c, ci2) {
      heads[ci2] = { cx: colX[ci2] + colW[ci2] / 2, cy: S.headY, w: Math.min(colW[ci2] - 8, S.NW), h: 8, head: true };
      if (c.c.fold) return;
      Object.keys(c.rel).forEach(function (id) {
        var p = { cx: area[ci2] + c.rel[id], cy: layerY[S.layerOf[id]], w: S.NW, h: S.nodeH[id] || 34 };
        c.c.lanes.forEach(function (lane) { pos[lane + '|' + id] = p; });
      });
    });
    function chY(b, t) {                             // 轨带 b 的第 t 条横轨：上带从节点往上数，下带从节点往下数
      var l = b >> 1, ts = pitch[b] || TS;
      return b % 2 ? layerY[l] + maxh[l] / 2 + 6 + t * ts : layerY[l] - maxh[l] / 2 - reserve[l] - 6 - t * ts;
    }
    function px(k, pk, key, end) { return (pk.indexOf('head|') === 0 ? heads[+pk.slice(5)].cx : pos[k].cx) + (off[key + '|' + end] || 0); }
    function top(k) { return pos[k].cy - pos[k].h / 2; }
    function bot(k) { return pos[k].cy + pos[k].h / 2; }
    var paths = {};
    Object.keys(plan).forEach(function (key) {
      var q = plan[key], r;
      if (q.type === 'adj') r = scurve(px(q.a, '', key, 0), bot(q.a), px(q.b, '', key, 1), top(q.b) - ARROW);
      else if (q.type === 'same') {
        var sx = px(q.a, '', key, 0), ex = px(q.b, '', key, 1), y = chY(q.h.ch, q.h.t);
        r = poly([[sx, top(q.a)], [sx, y], [ex, y], [ex, top(q.b) - ARROW]]);
      } else if (q.type === 'side') {
        var xs = sideX(q.v), pts = [], y2 = chY(q.h2.ch, q.h2.t), ex2 = px(q.b, '', key, 1);
        if (q.fa) {
          var ya = pos[q.a].cy + foff[key];
          pts.push([q.L ? pos[q.a].cx - pos[q.a].w / 2 : pos[q.a].cx + pos[q.a].w / 2, ya], [xs, ya]);
        } else {
          var sx2 = px(q.a, '', key, 0), y1 = chY(q.h1.ch, q.h1.t);
          pts.push([sx2, q.down ? bot(q.a) : top(q.a)], [sx2, y1], [xs, y1]);
        }
        pts.push([xs, y2], [ex2, y2], [ex2, top(q.b) - ARROW]);
        r = poly(pts);
      } else {
        var A = q.A, B = q.B, xa = px(A.node, A.pk, key, 0), xb = px(B.node, B.pk, key, 1);
        var ya2 = A.head != null ? S.headY : A.low ? bot(A.node) : top(A.node);
        var yb = B.head != null ? S.headY + ARROW : B.low ? bot(B.node) + ARROW : top(B.node) - ARROW;
        if (q.type === 'link1') {
          var yt = chY(q.h.ch, q.h.t);
          r = poly([[xa, ya2], [xa, yt], [xb, yt], [xb, yb]]);
        } else {
          var xg = gutTX(q.g, q.v.t), ya1 = chY(q.h1.ch, q.h1.t), yb1 = chY(q.h2.ch, q.h2.t);
          r = poly([[xa, ya2], [xa, ya1], [xg, ya1], [xg, yb1], [xb, yb1], [xb, yb]]);
        }
        r.low = !!A.low;                             // 往左、走节点下面的连线（标签放在线下面，圈外）
      }
      paths[key] = r;
    });
    var lastY = layerY.length ? layerY[nL - 1] + maxh[nL - 1] / 2 + band(2 * nL - 1) : S.top;
    return { W: W, H: lastY + 60, cols: colX.map(function (x0, i) { return { x: x0, w: colW[i] }; }), pos: pos, heads: heads,
             paths: paths, layerY: layerY, tracks: { ch: nCh, side: nSide, gut: nGut } };
  }

  /* 选线：paths 的折线 → near(x, y, r)：离 (x, y) 不超过 r 的线，按距离从近到远 [{key, d}]（一样近的短的在前） */
  function picker(paths) {
    var CELL = 24, grid = {}, len = {};
    Object.keys(paths).forEach(function (key) {
      var P = paths[key].pts, L = 0;
      for (var i = 1; i < P.length; i++) {
        var a = P[i - 1], b = P[i];
        L += Math.hypot(b[0] - a[0], b[1] - a[1]);
        for (var gx = Math.floor(Math.min(a[0], b[0]) / CELL); gx <= Math.floor(Math.max(a[0], b[0]) / CELL); gx++)
          for (var gy = Math.floor(Math.min(a[1], b[1]) / CELL); gy <= Math.floor(Math.max(a[1], b[1]) / CELL); gy++) {
            var c = grid[gx + ',' + gy] = grid[gx + ',' + gy] || {};
            c[key] = 1;
          }
      }
      len[key] = L;
    });
    function dist(P, x, y) {
      var best = Infinity;
      for (var i = 1; i < P.length; i++) {
        var a = P[i - 1], b = P[i], dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
        var t = L2 ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2)) : 0;
        best = Math.min(best, Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy));
      }
      return best;
    }
    return {
      near: function (x, y, r) {
        var seen = {}, out = [];
        for (var gx = Math.floor((x - r) / CELL); gx <= Math.floor((x + r) / CELL); gx++)
          for (var gy = Math.floor((y - r) / CELL); gy <= Math.floor((y + r) / CELL); gy++) {
            var c = grid[gx + ',' + gy];
            if (!c) continue;
            Object.keys(c).forEach(function (key) {
              if (seen[key]) return;
              seen[key] = 1;
              var d = dist(paths[key].pts, x, y);
              if (d <= r) out.push({ key: key, d: d });
            });
          }
        return out.sort(function (p, q) { return p.d - q.d || len[p.key] - len[q.key]; });
      }
    };
  }

  var CS = root.CS = root.CS || {};
  CS.laneRoute = { route: route, picker: picker, order: order };
})(typeof window !== 'undefined' ? window : globalThis);
