/* 按进程 · 线程分列（P0，用户 2026-10-01 定的展示；数据是 /api/lanes，见 lanes.py）。
 *
 * 叠了录了时序事件的 run 时，模块图按线程分成并排的几列，按进程分组：每列只放这条线程调到的节点，列里的边是
 * 这条线程里的调用。同一个节点在几列里各有一份，放在同一高度（纵坐标沿用「只看跑到的」那张图的分层），横着
 * 一眼看得出是同一个；鼠标停在一份上（或选中它）时高亮别的列里的副本并连上。列之间的连线一直画：
 *   谁把数据交给谁（handoff）：粗线，标通道和次数（janus / zmq / queue …）
 *   谁起了谁（spawn）：细虚线，标「起」和次数
 * 列按内容宽（小列窄），一个进程的几列能整个收起（进程头上的 ▾）。缩放、拖动沿用 graph.js 的图框。
 * 点节点、点列里的边：和模块图一样开详情栏（CS.graph 的 onPick / onPickEdge）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function el(t, a) { var e = document.createElementNS(NS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function fmtN(n) { return n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + '万' : String(n); }
  // TOP：图框左上角浮着缩放按钮，进程头、列头往下让一点
  var NW = 132, GAP = 10, PAD = 12, MINW = 104, EXTW = 92, FOLDW = 112, TOP = 36, HEAD = TOP + 58, VIA = {
    janus: 'janus 队列', zmq: 'ZMQ', queue: 'queue.Queue', asyncio: 'asyncio.Queue',
    thread: '起线程', exec: '起子进程（exec）', fork: '起子进程（fork）' };

  CS.lanes = {
    data: null, collapsed: {},

    /* 取数并画（app.drawMain 在「按线程分列」开着时调） */
    show: function () {
      var self = this, svg = document.getElementById('g');
      var d = CS.app.data, tok = (this._tok = (this._tok || 0) + 1);
      return CS.ds.lanes(d.open).then(function (L) {
        if (tok !== self._tok) return;
        self.data = L;
        self.draw(svg, L, d.graphHot || d.graph, d.names || {});
      }).catch(function (e) {
        if (tok !== self._tok) return;
        svg.textContent = '';
        svg.setAttribute('viewBox', '0 0 600 60');
        var t = el('text', { x: 12, y: 30, class: 'ln-err' });
        t.textContent = '按线程分列读取失败：' + e.message;
        svg.appendChild(t);
      });
    },

    draw: function (svg, L, G, names) {
      var self = this;
      svg.textContent = '';
      // 纵坐标：「只看跑到的」那张图的分层（同一个节点在各列里同一高度）
      var Y = {}, X = {}, H = {}, ys = [];
      (G.nodes || []).forEach(function (n) { Y[n.id] = n.cy; X[n.id] = n.x; H[n.id] = n.h; ys.push(n.cy); });
      var y0 = ys.length ? Math.min.apply(null, ys) : 0, y1 = ys.length ? Math.max.apply(null, ys) : 0;
      var extra = y1 + 70;                           // 不在那张图上的节点（很少见）：放在最下面一层
      function yOf(id) { return Y[id] != null ? Y[id] : extra; }
      // 每一列的宽：同一高度上最多几个节点
      var cols = [], x = 0, pidCols = {}, procs = [];
      L.lanes.forEach(function (ln) {
        if (!pidCols[ln.pid]) { pidCols[ln.pid] = []; procs.push(ln.pid); }
        pidCols[ln.pid].push(ln);
      });
      procs.forEach(function (pid) {
        var ls = pidCols[pid], gx = x;
        if (self.collapsed[pid]) {
          cols.push({ fold: true, pid: pid, lanes: ls, x: x, w: FOLDW });
          x += FOLDW + 14;
        } else {
          ls.forEach(function (ln) {
            var rows = {};
            Object.keys(ln.nodes).forEach(function (id) { (rows[yOf(id)] = rows[yOf(id)] || []).push(id); });
            var most = 0;
            Object.keys(rows).forEach(function (k) {
              rows[k].sort(function (a, b) { return (X[a] || 0) - (X[b] || 0); });
              most = Math.max(most, rows[k].length);
            });
            var w = ln.external ? EXTW : Math.max(MINW, most * (NW + GAP) - GAP + 2 * PAD);
            cols.push({ lane: ln, pid: pid, x: x, w: w, rows: rows });
            x += w + 8;
          });
          x += 6;
        }
        procs[procs.indexOf(pid)] = { pid: pid, x: gx, w: x - gx - 14, lanes: ls };
      });
      var W = Math.max(x, 400), top = HEAD + 14, Hh = top + (Math.max(y1, extra) - y0) + 60;
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + Hh);
      // 让 graph.js 的图框（缩放、拖动、适应宽度）照样工作；模块图那边的节点 / 边清空，免得开关、搜索去动它们
      CS.graph.svg = svg; CS.graph.G = { width: W, height: Hh, nodes: [], edges: [] };
      CS.graph.nodes = {}; CS.graph.edges = []; CS.graph.N = {};

      var bg = el('g', {}), eg = el('g', {}), lk = el('g', { class: 'ln-links' }), ng = el('g', {});
      var tw = el('g', { class: 'ln-twins' }), lab = el('g', {});
      svg.appendChild(bg); svg.appendChild(eg); svg.appendChild(tw); svg.appendChild(lk); svg.appendChild(ng);
      svg.appendChild(lab);
      var pos = {}, laneOf = {};                     // "列|节点" → 中心 {x, y, w, h}；列 id → 列的几何
      function nodeY(id) { return top + (yOf(id) - y0); }

      // 进程头：名字 + 收起 / 展开
      procs.forEach(function (P) {
        var name = P.lanes[0].proc, fold = !!self.collapsed[P.pid];
        var g = el('g', { class: 'ln-proc', 'data-pid': P.pid });
        g.appendChild(el('rect', { x: P.x, y: TOP + 2, width: Math.max(P.w, 40), height: 22, rx: 6 }));
        var t = el('text', { x: P.x + 22, y: TOP + 17, class: 'ln-pname' });
        t.textContent = name + '（pid ' + P.pid + '）';
        var tip = el('title', {}); tip.textContent = name + '（pid ' + P.pid + '）\n' + P.lanes.length + ' 列；点 '
          + (fold ? '▸ 展开' : '▾ 收起'); t.appendChild(tip);
        g.appendChild(t);
        var b = el('text', { x: P.x + 8, y: TOP + 17, class: 'ln-fold', role: 'button', tabindex: '0',
                             'aria-label': (fold ? '展开 ' : '收起 ') + name });
        b.textContent = fold ? '▸' : '▾';
        var go = function (ev) { ev.stopPropagation(); self.collapsed[P.pid] = !fold; self.draw(svg, L, G, names); };
        b.onclick = go; t.onclick = go;
        b.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(ev); } };
        g.appendChild(b);
        lab.appendChild(g);
      });

      cols.forEach(function (C) {
        var col = el('g', { class: 'ln-col' + (C.fold ? ' fold' : '') + (C.lane && C.lane.external ? ' ext' : '') });
        col.appendChild(el('rect', { x: C.x, y: TOP + 28, width: C.w, height: Hh - TOP - 32, rx: 8, class: 'ln-band' }));
        var head = el('text', { x: C.x + C.w / 2, y: TOP + 44, 'text-anchor': 'middle', class: 'ln-th' });
        if (C.fold) {
          head.textContent = C.lanes.length + ' 列（收起）';
          C.lanes.forEach(function (ln) { laneOf[ln.id] = { x: C.x, w: C.w, fold: true }; });
        } else {
          var ln = C.lane;
          head.textContent = ln.thread + (ln.n_threads > 1 ? ' ×' + ln.n_threads : '');
          var tip = el('title', {});
          tip.textContent = ln.proc + ' · ' + ln.thread + (ln.n_threads > 1 ? '（' + ln.n_threads + ' 个线程）' : '')
            + (ln.names && ln.names.length && (ln.names.length > 1 || ln.names[0] !== ln.thread)
               ? '\n原名：' + ln.names.join('、') + (ln.n_threads > ln.names.length ? ' …' : '') : '')
            + (ln.external ? '\n只跑仓库外的代码（这里没有节点），是交接的一头才列出来' : '');
          col.appendChild(tip);                 // 悬停提示挂在整列上（挂在列头的 text 里会混进它的文字）
          if (ln.external) {
            var sub = el('text', { x: C.x + C.w / 2, y: TOP + 58, 'text-anchor': 'middle', class: 'ln-ext' });
            sub.textContent = '仓库外的代码'; col.appendChild(sub);
          }
          laneOf[ln.id] = { x: C.x, w: C.w };
          // 这一列的节点：同一高度上按「只看跑到的」图里的左右顺序排
          Object.keys(C.rows).forEach(function (k) {
            var ids = C.rows[k], n = ids.length, span = n * (NW + GAP) - GAP, x0 = C.x + (C.w - span) / 2;
            ids.forEach(function (id, i) {
              var cx = x0 + i * (NW + GAP) + NW / 2, cy = nodeY(id), h = H[id] || 34;
              pos[ln.id + '|' + id] = { x: cx, y: cy, w: NW, h: h };
              var info = ln.nodes[id];
              var g = el('g', { class: 'nd warm ln-nd', tabindex: '0', role: 'button', 'data-id': id, 'data-lane': ln.id });
              g.appendChild(el('rect', { x: cx - NW / 2, y: cy - h / 2, width: NW, height: h }));
              var t = el('text', { x: cx, y: cy - 3, class: 'nl', 'text-anchor': 'middle' });
              var nm = names[id] || id; t.textContent = nm.length > 18 ? nm.slice(0, 17) + '…' : nm; g.appendChild(t);
              var s = el('text', { x: cx, y: cy + 9, class: 'ns', 'text-anchor': 'middle' });
              s.textContent = info.n ? '被调 ' + fmtN(info.n) + ' 次' : '只往外调'; g.appendChild(s);
              var tp = el('title', {});
              tp.textContent = id + '\n' + ln.thread + ' 里' + (info.n ? '被调了 ' + info.n + ' 次' : '只当调用方')
                + '\n别的列里也有它的话，鼠标停在这里会连上；点了看详情';
              g.appendChild(tp);
              g.onmouseenter = function () { self.twins(id, true); };
              g.onmouseleave = function () { self.twins(id, false); };
              var pick = function (ev) { ev.stopPropagation(); self.select(id); if (CS.graph.onPick) CS.graph.onPick(id); };
              g.onclick = pick;
              g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } };
              ng.appendChild(g);
            });
          });
          // 列里的边：这条线程里节点之间的调用
          ln.edges.forEach(function (e) {
            var a = pos[ln.id + '|' + e.a], b = pos[ln.id + '|' + e.b];
            if (!a || !b) return;
            var d = self.route(a, b), dashed = e.n > 0 && e.only >= e.n;
            var p = el('path', { d: d, class: 'ln-e' + (dashed ? ' dyn' : '') });
            var hit = el('path', { d: d, class: 'ehit' });
            var tip2 = el('title', {});
            tip2.textContent = e.a + ' → ' + e.b + '\n' + ln.thread + ' 里调了 ' + e.n + ' 次'
              + (dashed ? '，全都是代码里看不出会调到的' : e.only ? '，其中约 ' + e.only + ' 次代码里看不出' : '')
              + '\n点击看具体是哪些函数（不分线程）';
            hit.appendChild(tip2);
            hit.onclick = function (ev) { ev.stopPropagation(); if (CS.graph.onPickEdge) CS.graph.onPickEdge(e.a, e.b); };
            eg.appendChild(p); eg.appendChild(hit);
            var L2 = p.getTotalLength ? p.getTotalLength() : 0, pt = L2 ? p.getPointAtLength(L2 / 2) : null;
            if (pt) {
              var c = el('text', { x: pt.x, y: pt.y + 3, class: 'ecnt', 'text-anchor': 'middle' });
              c.textContent = fmtN(e.n); c.onclick = hit.onclick; eg.appendChild(c);
            }
          });
        }
        col.appendChild(head);
        bg.appendChild(col);
      });

      // 列之间的连线：一头是哪一列的哪个节点（收起的进程、没有节点的列：接在列头下面）
      function end(e) {
        var C = laneOf[e.lane];
        if (!C) return null;
        var p = !C.fold && e.node ? pos[e.lane + '|' + e.node] : null;
        return p || { x: C.x + C.w / 2, y: HEAD + 4, w: Math.min(C.w - 8, NW), h: 8, head: true };
      }
      (L.links || []).forEach(function (k) {
        var a = end(k.from), b = end(k.to);
        if (!a || !b || (a === b)) return;
        var right = b.x >= a.x, sx = a.x + (right ? 1 : -1) * a.w / 2, ex = b.x + (right ? -1 : 1) * b.w / 2;
        if (Math.abs(b.x - a.x) < 1) { sx = a.x; ex = b.x; }
        var dx = Math.max(40, Math.abs(ex - sx) / 2);
        var d = 'M' + sx + ',' + a.y + ' C' + (sx + (right ? dx : -dx)) + ',' + a.y + ' ' + (ex - (right ? dx : -dx)) + ',' + b.y
          + ' ' + ex + ',' + b.y;
        var cls = 'ln-link ' + k.kind + ' via-' + k.via;
        var p = el('path', { d: d, class: cls, 'marker-end': 'url(#lnarrow-' + k.kind + ')' });
        var t = el('title', {});
        t.textContent = (k.kind === 'handoff' ? '谁把数据交给谁：经 ' + (VIA[k.via] || k.via) : '谁起了谁：' + (VIA[k.via] || k.via))
          + '，' + k.n + ' 次\n' + k.from.lane.split(':').slice(1).join(':') + (k.from.node ? '（' + k.from.node + '）' : '')
          + ' → ' + k.to.lane.split(':').slice(1).join(':') + (k.to.node ? '（' + k.to.node + '）' : '')
          + (k.to.t != null && L.window ? '\n第一次在 +' + ((k.to.t - L.window[0]) / 1e6).toFixed(3) + ' s' : '');
        p.appendChild(t);
        lk.appendChild(p);
        var Lp = p.getTotalLength ? p.getTotalLength() : 0, pt = Lp ? p.getPointAtLength(Lp / 2) : null;
        if (pt) {
          var c = el('text', { x: pt.x, y: pt.y - 4, class: 'ln-ltxt ' + k.kind, 'text-anchor': 'middle' });
          c.textContent = (k.kind === 'handoff' ? k.via : '起') + (k.n > 1 ? ' ×' + fmtN(k.n) : '');
          c.appendChild(t.cloneNode(true));
          lk.appendChild(c);
        }
      });
      var defs = el('defs', {});
      [['handoff', 'var(--cool)'], ['spawn', 'var(--muted)']].forEach(function (q) {
        var m = el('marker', { id: 'lnarrow-' + q[0], viewBox: '0 0 8 8', refX: '7', refY: '4', markerUnits: 'userSpaceOnUse',
                               markerWidth: '8', markerHeight: '8', orient: 'auto' });
        m.appendChild(el('path', { d: 'M0,0 L8,4 L0,8 z', fill: q[1] })); defs.appendChild(m);
      });
      svg.appendChild(defs);
      this.pos = pos; this.tw = tw; this.svg = svg; this.sel = null;
      CS.graph.wireBox(svg.parentNode);
      CS.graph.fit();
    },

    /* a → b（同一列里）的路径：b 在下面竖着下去，否则从 a 的顶边拱上去再落进 b 的顶边 */
    route: function (a, b) {
      var bt = b.y - b.h / 2 - 3;
      if (b.y > a.y + 2) {
        var y1 = a.y + a.h / 2, my = (y1 + bt) / 2;
        return 'M' + a.x + ',' + y1 + ' C' + a.x + ',' + my + ' ' + b.x + ',' + my + ' ' + b.x + ',' + bt;
      }
      var at = a.y - a.h / 2, tp = Math.min(at, bt) - 26;
      return 'M' + a.x + ',' + at + ' C' + a.x + ',' + tp + ' ' + b.x + ',' + tp + ' ' + b.x + ',' + bt;
    },

    /* 同一个节点在别的列里的副本：高亮并连上（鼠标停着、或者选中了它） */
    twins: function (id, on) {
      if (!this.svg) return;
      var keep = this.sel;
      this.tw.textContent = '';
      [].forEach.call(this.svg.querySelectorAll('.ln-nd'), function (g) {
        g.classList.toggle('twin', (on && g.dataset.id === id) || (!!keep && g.dataset.id === keep));
      });
      var self = this;
      [on ? id : null, keep].forEach(function (x) {
        if (!x) return;
        var ps = Object.keys(self.pos).filter(function (k) { return k.slice(k.indexOf('|') + 1) === x; })
          .map(function (k) { return self.pos[k]; }).sort(function (p, q) { return p.x - q.x; });
        for (var i = 1; i < ps.length; i++)
          self.tw.appendChild(el('line', { x1: ps[i - 1].x + ps[i - 1].w / 2, y1: ps[i - 1].y,
                                           x2: ps[i].x - ps[i].w / 2, y2: ps[i].y, class: 'ln-twin' }));
      });
    },

    select: function (id) {
      var s = this.sel = this.sel === id ? null : id;
      if (this.svg) [].forEach.call(this.svg.querySelectorAll('.ln-nd'), function (g) {
        g.classList.toggle('sel', !!s && g.dataset.id === s);
      });
      this.twins(id, false);
    }
  };
})(window.CS);
