/* SVG 绘图。纯函数式：喂数据进来，画出来，把交互回调交给调用方。
 *
 * 边的颜色只表达「这条边是什么」，不表达「选没选中」：
 *   灰实线  静态引用——import 了，而且真的用到了对方的符号
 *   灰虚线  只 import——一个符号都没用到（再导出 / 类型标注 / 副作用 / 死 import）
 *   橙色    这次 runtime 真的走过，粗细 ∝ log(调用次数)
 *   橙虚线  只在 runtime 出现——静态 import 图里没有（插件、getattr、注册表）
 * 选中用蓝色光晕叠在边下面，边本身的颜色不变——否则选中一个节点后，
 * 它的所有边都变成同一种颜色，恰好把最想看的信息（哪些是真调用）抹掉了。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function el(t, a) { var e = document.createElementNS(NS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }

  /* a、b 两个节点之间的路径。同泳道时从顶边拱过去，否则竖向三次贝塞尔。 */
  function route(a, b) {
    if (Math.abs(a.cy - b.cy) < 2) {
      // 早先画成「a 右缘 → b 左缘」的直线，默认 b 在 a 右侧；b 在左侧时
      // 这条线会反向穿过两个框、被框挡住，箭头也落在 b 的远端。
      var dir = b.cx >= a.cx ? 1 : -1;
      var sx = a.cx + dir * a.w * 0.22, ex = b.cx - dir * b.w * 0.22;
      var top = Math.min(a.cy - a.h / 2, b.cy - b.h / 2);
      var lift = Math.min(26, 12 + Math.abs(ex - sx) * 0.08);
      return 'M' + sx + ',' + (a.cy - a.h / 2) + ' C' + sx + ',' + (top - lift) + ' '
        + ex + ',' + (top - lift) + ' ' + ex + ',' + (b.cy - b.h / 2 - 3);
    }
    var y1 = a.cy + a.h / 2, y2 = b.cy - b.h / 2 - 3;
    if (b.cy < a.cy) { y1 = a.cy - a.h / 2; y2 = b.cy + b.h / 2 + 3; }
    var my = (y1 + y2) / 2;
    return 'M' + a.cx + ',' + y1 + ' C' + a.cx + ',' + my + ' ' + b.cx + ',' + my + ' ' + b.cx + ',' + y2;
  }

  CS.graph = {
    nodes: {}, edges: [], G: null, hot: null, onPick: null, onPickEdge: null,
    state: { sel: null, selEdge: null, refs: true, imp: true, hot: true, dyn: true,
             onlyHot: false, onlyNoted: false },
    noteStatus: {},          // target → 'noted' | 'stale' | 'todo'
    counts: { ref: 0, imp: 0, warm: 0, dyn: 0 },

    draw: function (svg, G, hot, extra) {
      extra = extra || {};
      this.G = G; this.hot = hot || null;
      var kinds = extra.kinds || {}, rtOnly = extra.rtOnly || [];
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

      // 箭头是独立的 marker，不会跟着 stroke 变色，每种边色各备一个
      var defs = el('defs', {});
      [['a', 'var(--edge)'], ['ah', 'var(--hot)']].forEach(function (p) {
        // userSpaceOnUse：箭头大小固定，不随线宽放大（默认按 stroke-width 缩放，粗的 runtime 边箭头会大得离谱）
        var m = el('marker', { id: p[0], viewBox: '0 0 8 8', refX: '7', refY: '4', markerUnits: 'userSpaceOnUse',
          markerWidth: '8', markerHeight: '8', orient: 'auto-start-reverse' });
        m.appendChild(el('path', { d: 'M0,0 L8,4 L0,8 z', fill: p[1] })); defs.appendChild(m);
      });
      svg.appendChild(defs);

      var N = {}; G.nodes.forEach(function (n) { n.cx = n.x * G.width; N[n.id] = n; });
      this.N = N;

      var hotPk = (hot && hot.packages) || {}, hotEd = (hot && hot.edges) || {};
      var maxE = 1; for (var k in hotEd) maxE = Math.max(maxE, hotEd[k]);
      // 三层：光晕在最下，可见的边在中间，透明的宽命中区在最上（但仍在节点下面，节点照样能点）
      var hg = el('g', {}), eg = el('g', {}), xg = el('g', {});
      svg.appendChild(hg); svg.appendChild(eg); svg.appendChild(xg);
      this.edges = [];
      var self = this, cnt = { ref: 0, imp: 0, warm: 0, dyn: 0 };

      function add(src, dst, kind, hits, info) {
        var a = N[src], b = N[dst]; if (!a || !b) return;
        var d = route(a, b);
        var E = { a: src, b: dst, kind: kind, hits: hits, info: info,
                  w: hits ? 1.2 + 2.2 * Math.log1p(hits) / Math.log1p(maxE) : 1.2 };
        E.halo = el('path', { d: d, class: 'halo' });
        E.gap = el('path', { d: d, class: 'gap' });   // 光晕中间垫一道底色，灰虚线在蓝底上才看得清
        E.p = el('path', { d: d });
        E.x = el('path', { d: d, class: 'ehit' });
        var tip = el('title', {});
        tip.textContent = src + ' → ' + dst + '\n'
          + (kind === 'dyn' ? '静态 import 图里没有这条边（动态分派）'
             : (info.uses ? '用到对方 ' + info.uses + ' 个符号' : '只 import，没用到任何符号')
               + (info.dead ? '　·　' + info.dead + ' 个 import 没被引用' : ''))
          + (hits ? '\nruntime 调用 ' + hits + ' 次' : '') + '\n点击看具体是哪些函数';
        E.x.appendChild(tip);
        E.x.onclick = function (ev) { ev.stopPropagation(); self.pickEdge(src, dst); };
        E.x.onmouseenter = function () { E.p.classList.add('hover'); E.halo.classList.add('hover'); };
        E.x.onmouseleave = function () { E.p.classList.remove('hover'); E.halo.classList.remove('hover'); };
        hg.appendChild(E.halo); hg.appendChild(E.gap); eg.appendChild(E.p); xg.appendChild(E.x);
        self.edges.push(E);
        cnt[kind]++; if (hits && kind !== 'dyn') cnt.warm++;
      }
      G.edges.forEach(function (e) {
        var key = e[0] + '|' + e[1], info = kinds[key] || { uses: 1, dead: 0 };
        add(e[0], e[1], info.uses ? 'ref' : 'imp', hotEd[key] || 0, info);
      });
      rtOnly.forEach(function (e) { add(e[0], e[1], 'dyn', e[2], {}); });
      this.counts = cnt;

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

    /* 静态邻居（详情面板的「依赖 / 被依赖」用） */
    nb: function (id) {
      var i = [], o = [];
      this.G.edges.forEach(function (e) { if (e[0] === id) o.push(e[1]); if (e[1] === id) i.push(e[0]); });
      return { i: i, o: o };
    },

    edgeInfo: function (a, b) {
      for (var i = 0; i < this.edges.length; i++)
        if (this.edges[i].a === a && this.edges[i].b === b) return this.edges[i];
      return null;
    },

    vis: function (id) {
      var s = this.state;
      if (s.onlyHot && !((this.hot && this.hot.packages[id]) || 0)) return false;
      if (s.onlyNoted && (this.noteStatus[id] || 'todo') === 'todo') return false;
      return true;
    },

    paint: function () {
      var s = this.state, self = this, keep = null;
      if (s.selEdge) { keep = {}; var ab = s.selEdge.split('|'); keep[ab[0]] = keep[ab[1]] = 1; }
      else if (s.sel) {
        keep = {}; keep[s.sel] = 1;
        this.edges.forEach(function (E) { if (E.a === s.sel) keep[E.b] = 1; if (E.b === s.sel) keep[E.a] = 1; });
      }
      this.edges.forEach(function (E) {
        var warm = E.hits > 0 && s.hot && E.kind !== 'dyn';
        var show = E.kind === 'dyn' ? s.dyn : (warm || (E.kind === 'ref' ? s.refs : s.imp));
        show = show && self.vis(E.a) && self.vis(E.b);
        var mine = s.selEdge ? s.selEdge === E.a + '|' + E.b
                 : !!s.sel && (E.a === s.sel || E.b === s.sel);
        var cls = 'e ' + E.kind + (warm || E.kind === 'dyn' ? ' warm' : '')
                + (keep && !mine ? ' dim' : '') + (mine ? ' hi' : '');
        E.p.setAttribute('class', cls);
        E.p.style.strokeWidth = ((warm || E.kind === 'dyn') ? E.w : 1.2) + (mine ? 1 : 0);
        E.p.setAttribute('marker-end', 'url(#' + (warm || E.kind === 'dyn' ? 'ah' : 'a') + ')');
        [E.p, E.x, E.halo, E.gap].forEach(function (x) { x.style.display = show ? '' : 'none'; });
        E.halo.classList.toggle('on', !!s.selEdge && mine);
        E.gap.classList.toggle('on', !!s.selEdge && mine);
      });
      Object.keys(this.nodes).forEach(function (id) {
        var g = self.nodes[id];
        g.style.display = self.vis(id) ? '' : 'none';
        g.classList.toggle('dim', !!keep && !keep[id]);
        g.classList.toggle('sel', s.sel === id);
        g.classList.toggle('end', !!s.selEdge && !!keep && !!keep[id]);
      });
    },

    pick: function (id) {
      this.state.sel = id; this.state.selEdge = null; this.paint();
      if (this.onPick) this.onPick(id);
      var g = this.nodes[id];
      if (g && g.scrollIntoView) g.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
    },

    pickEdge: function (a, b) {
      this.state.selEdge = a + '|' + b; this.state.sel = null; this.paint();
      if (this.onPickEdge) this.onPickEdge(a, b);
    },

    highlight: function (pred) {
      var self = this;
      Object.keys(this.nodes).forEach(function (id) {
        self.nodes[id].classList.toggle('match', !!pred && pred(self.N[id]));
      });
    }
  };
})(window.CS);
