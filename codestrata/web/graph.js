/* SVG 绘图。纯函数式：喂数据进来，画出来，把交互回调交给调用方。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function el(t, a) { var e = document.createElementNS(NS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }

  CS.graph = {
    nodes: {}, edges: [], G: null, hot: null, onPick: null,
    state: { sel: null, imports: true, hot: true, onlyHot: false, onlyNoted: false },
    noteStatus: {},          // target → 'noted' | 'stale' | 'todo'

    draw: function (svg, G, hot) {
      this.G = G; this.hot = hot || null;
      svg.textContent = '';
      svg.setAttribute('viewBox', '0 0 ' + G.width + ' ' + G.height);

      var lg = el('g', {});
      (G.lane_rows || []).forEach(function (L) {
        if (!L.empty && L.i % 2 === 0)
          lg.appendChild(el('rect', { x: 0, y: L.y, width: G.width, height: L.h, class: 'laneband' }));
        lg.appendChild(el('line', { x1: 0, y1: L.y, x2: G.width, y2: L.y, class: 'lanerule' }));
        var rng = (L.hi > 0 ? '+' : '') + L.hi.toFixed(2) + '…' + (L.lo > 0 ? '+' : '') + L.lo.toFixed(2);
        if (L.empty) {
          var t0 = el('text', { x: 8, y: L.y + L.h / 2 + 3, class: 'lanealt empty' });
          t0.textContent = rng + '　（没有模块落在这段高度）';
          lg.appendChild(t0); return;
        }
        if (L.name) { var t = el('text', { x: 8, y: L.y + 14, class: 'lanetxt' }); t.textContent = L.name; lg.appendChild(t); }
        var a = el('text', { x: 8, y: L.y + (L.name ? 26 : 14), class: 'lanealt' });
        a.textContent = rng; lg.appendChild(a);
      });
      svg.appendChild(lg);

      var defs = el('defs', {});
      [['a', 'var(--edge)'], ['ah', 'var(--hot)']].forEach(function (p) {
        var m = el('marker', { id: p[0], viewBox: '0 0 8 8', refX: '7', refY: '4',
          markerWidth: '5.5', markerHeight: '5.5', orient: 'auto-start-reverse' });
        m.appendChild(el('path', { d: 'M0,0 L8,4 L0,8 z', fill: p[1] })); defs.appendChild(m);
      });
      svg.appendChild(defs);

      var N = {}; G.nodes.forEach(function (n) { n.cx = n.x * G.width; N[n.id] = n; });
      this.N = N;

      var hotPk = (hot && hot.packages) || {}, hotEd = (hot && hot.edges) || {};
      var maxE = 1; for (var k in hotEd) maxE = Math.max(maxE, hotEd[k]);
      var eg = el('g', {}); svg.appendChild(eg); this.edges = [];
      var self = this;
      G.edges.forEach(function (e) {
        var a = N[e[0]], b = N[e[1]]; if (!a || !b) return;
        var y1 = a.cy + a.h / 2, y2 = b.cy - b.h / 2 - 3;
        if (b.cy < a.cy) { y1 = a.cy - a.h / 2; y2 = b.cy + b.h / 2 + 3; }
        var my = (y1 + y2) / 2, d;
        if (Math.abs(a.cy - b.cy) < 2) d = 'M' + (a.cx + a.w / 2 + 3) + ',' + a.cy + ' L' + (b.cx - b.w / 2 - 4) + ',' + b.cy;
        else d = 'M' + a.cx + ',' + y1 + ' C' + a.cx + ',' + my + ' ' + b.cx + ',' + my + ' ' + b.cx + ',' + y2;
        var hits = hotEd[e[0] + '|' + e[1]] || 0;
        var p = el('path', { d: d, class: 'e' + (hits ? ' warm' : ''), 'marker-end': 'url(#' + (hits ? 'ah' : 'a') + ')' });
        if (hits) p.setAttribute('stroke-width', (1.2 + 2.2 * Math.log1p(hits) / Math.log1p(maxE)).toFixed(2));
        p.dataset.a = e[0]; p.dataset.b = e[1]; p.dataset.hits = hits;
        eg.appendChild(p); self.edges.push(p);
      });

      var ng = el('g', {}); svg.appendChild(ng); this.nodes = {};
      G.nodes.forEach(function (n) {
        var hits = hotPk[n.id] || 0;
        var g = el('g', { class: 'nd' + (hot ? (hits ? ' warm' : ' cold') : ''), tabindex: '0', role: 'button' });
        g.dataset.id = n.id;
        g.appendChild(el('rect', { x: n.cx - n.w / 2, y: n.cy - n.h / 2, width: n.w, height: n.h }));
        var t = el('text', { x: n.cx, y: n.cy - 3, class: 'nl', 'text-anchor': 'middle' });
        t.textContent = n.label; g.appendChild(t);
        var s = el('text', { x: n.cx, y: n.cy + 9, class: 'ns', 'text-anchor': 'middle' });
        s.textContent = n.files + 'f · ' + n.classes + 'c' + (hits ? (' · ' + hits) : ''); g.appendChild(s);
        var bd = el('text', { x: n.cx + n.w / 2 - 5, y: n.cy - n.h / 2 + 8, class: 'badge todo', 'text-anchor': 'end' });
        g.appendChild(bd); g._badge = bd;
        ng.appendChild(g); self.nodes[n.id] = g;
        g.onclick = function () { self.pick(n.id); };
        g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); self.pick(n.id); } };
      });
      this.paint();
    },

    setNoteStatus: function (map) {
      this.noteStatus = map || {};
      var self = this;
      Object.keys(this.nodes).forEach(function (id) {
        var st = self.noteStatus[id] || 'todo', b = self.nodes[id]._badge;
        b.setAttribute('class', 'badge ' + st);
        b.textContent = st === 'noted' ? '✓' : (st === 'stale' ? '!' : '');
      });
      this.paint();
    },

    nb: function (id) {
      var i = [], o = [];
      this.G.edges.forEach(function (e) { if (e[0] === id) o.push(e[1]); if (e[1] === id) i.push(e[0]); });
      return { i: i, o: o };
    },

    vis: function (id) {
      var s = this.state;
      if (s.onlyHot && !((this.hot && this.hot.packages[id]) || 0)) return false;
      if (s.onlyNoted && (this.noteStatus[id] || 'todo') === 'todo') return false;
      return true;
    },

    paint: function () {
      var s = this.state, self = this;
      this.edges.forEach(function (p) {
        var isHot = +p.dataset.hits > 0;
        var show = (isHot ? s.hot : s.imports) && self.vis(p.dataset.a) && self.vis(p.dataset.b);
        p.style.display = show ? '' : 'none';
        p.classList.toggle('dim', !!s.sel && show && p.dataset.a !== s.sel && p.dataset.b !== s.sel);
        p.classList.toggle('hi', !!s.sel && show && (p.dataset.a === s.sel || p.dataset.b === s.sel));
      });
      var keep = null;
      if (s.sel) { var x = this.nb(s.sel); keep = {}; keep[s.sel] = 1; x.i.concat(x.o).forEach(function (i) { keep[i] = 1; }); }
      Object.keys(this.nodes).forEach(function (id) {
        var g = self.nodes[id];
        g.style.display = self.vis(id) ? '' : 'none';
        g.classList.toggle('dim', !!keep && !keep[id]);
        g.classList.toggle('sel', s.sel === id);
      });
    },

    pick: function (id) {
      this.state.sel = id; this.paint();
      if (this.onPick) this.onPick(id);
      var g = this.nodes[id];
      if (g && g.scrollIntoView) g.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
    },

    highlight: function (pred) {
      var self = this;
      Object.keys(this.nodes).forEach(function (id) {
        self.nodes[id].classList.toggle('match', !!pred && pred(self.N[id]));
      });
    }
  };
})(window.CS);
