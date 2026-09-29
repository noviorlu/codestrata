/* SVG 绘图。纯函数式：喂数据进来，画出来，把交互回调交给调用方。
 *
 * 边的颜色只表达「这条边是什么」，不表达「选没选中」：
 *   灰实线  静态引用——import 了，而且真的用到了对方的符号
 *   灰虚线  只 import——一个符号都没用到（再导出 / 类型标注 / 副作用 / 死 import）
 *   橙色    这次 runtime 真的走过，粗细 ∝ log(调用次数)
 *   橙虚线  动态分派——跑到的调用在代码里找不到对应的引用（插件、getattr、注册表、self.model 这类接口）。
 *           两端之间可能根本没有 import，也可能有 import、但 import 的东西这次没跑到；后一种不能画成
 *           实线：收起时实线、展开后变成灰边加一条虚线，看起来就像箭头「消失」了
 * 选中用蓝色光晕叠在边下面，边本身的颜色不变——否则选中一个节点后，
 * 它的所有边都变成同一种颜色，恰好把最想看的信息（哪些是真调用）抹掉了。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function el(t, a) { var e = document.createElementNS(NS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }

  function sameLane(a, b) { return Math.abs(a.cy - b.cy) < 2; }

  /* 每条边在两端节点上的接点：同一个节点同一条边（顶 / 底）上的接点沿宽度摊开，按另一端的横坐标
     排序——左边来的接在左边、右边来的接在右边，交叉最少。早先都接在正中间，一个节点展开后
     几十条箭头叠成一根。返回 "a|b" → [起点 x, 终点 x] */
  function ports(N, pairs) {
    var sides = {}, out = {};
    function put(id, side, key, end, other) {
      (sides[id + '|' + side] = sides[id + '|' + side] || []).push({ key: key, end: end, other: other });
    }
    pairs.forEach(function (p) {
      var a = N[p[0]], b = N[p[1]]; if (!a || !b) return;
      var key = p[0] + '|' + p[1], down = b.cy > a.cy && !sameLane(a, b);
      put(p[0], down ? 'b' : 't', key, 0, b.cx);     // 箭头一律从顶边进入目标（route）
      put(p[1], 't', key, 1, a.cx);
      out[key] = [a.cx, b.cx];
    });
    Object.keys(sides).forEach(function (k) {
      var L = sides[k], n = N[k.slice(0, k.lastIndexOf('|'))];
      if (L.length < 2) return;
      L.sort(function (x, y) { return x.other - y.other || x.end - y.end; });
      var span = Math.min(n.w * 0.8, 9 * (L.length - 1));      // 接点间距最多 9px，少的时候聚在中间
      L.forEach(function (x, i) { out[x.key][x.end] = n.cx - span / 2 + span * i / (L.length - 1); });
    });
    return out;
  }

  /* a、b 两个节点之间的路径（sx、ex 是两端的接点横坐标）。箭头一律从顶边进入 b：
     b 在下面时从 a 的底边竖着下去；b 在上面或同一泳道时从 a 的顶边出发，拱到 b 的上方再落进去 */
  function route(a, b, sx, ex) {
    var bt = b.cy - b.h / 2, ey = bt - 3;
    if (b.cy > a.cy && !sameLane(a, b)) {
      var y1 = a.cy + a.h / 2, my = (y1 + ey) / 2;
      return 'M' + sx + ',' + y1 + ' C' + sx + ',' + my + ' ' + ex + ',' + my + ' ' + ex + ',' + ey;
    }
    var at = a.cy - a.h / 2, top = Math.min(at, bt);
    var lift = Math.min(40, 14 + Math.abs(ex - sx) * 0.08);
    return 'M' + sx + ',' + at + ' C' + sx + ',' + (top - lift) + ' ' + ex + ',' + (top - lift) + ' ' + ex + ',' + ey;
  }

  CS.graph = {
    nodes: {}, edges: [], G: null, hot: null, onPick: null, onPickEdge: null,
    zoom: 1, panMode: false,   // 缩放倍数（相对「适应宽度」）；移动模式：按住任意位置拖动
    state: { sel: null, selEdge: null, selFrame: null, refs: true, imp: true, type: false, hot: true, dyn: true,
             onlyHot: false, onlyNoted: false },
    noteStatus: {},          // target → 'noted' | 'stale' | 'todo'
    counts: { ref: 0, imp: 0, type: 0, warm: 0, dyn: 0 },

    draw: function (svg, G, hot, extra) {
      extra = extra || {};
      this.G = G; this.hot = hot || null;
      // 对比（另一个 run）：节点、边上带 [A, B] 两个次数，画三种颜色（只有 A 橙、只有 B 紫、两边都跑到前景色）
      this.cmp = (extra && extra.cmp) || null;
      var kinds = extra.kinds || {}, rtOnly = extra.rtOnly || [], dynOnly = {}, rtKey = {};
      (extra.dynOnly || []).forEach(function (k) { dynOnly[k] = 1; });
      rtOnly.forEach(function (e) { rtKey[e[0] + '|' + e[1]] = 1; });
      // 仅类型（TYPE_CHECKING 里的 import）：这次跑到了的，由 runtime 那条边代表，不再叠一条
      var typeOnly = (extra.typeOnly || []).filter(function (e) { return !rtKey[e[0] + '|' + e[1]]; });
      svg.textContent = '';
      svg.setAttribute('viewBox', '0 0 ' + G.width + ' ' + G.height);
      this.svg = svg;

      var lg = el('g', {});
      (G.lane_rows || []).forEach(function (L) {
        if (!L.empty && L.i % 2 === 0)
          lg.appendChild(el('rect', { x: 0, y: L.y, width: G.width, height: L.h, class: 'laneband' }));
        lg.appendChild(el('line', { x1: 0, y1: L.y, x2: G.width, y2: L.y, class: 'lanerule' }));
        var rng = (L.hi > 0 ? '+' : '') + L.hi.toFixed(2) + '…' + (L.lo > 0 ? '+' : '') + L.lo.toFixed(2);
        if (L.empty) {
          // 只写高度区间（放在左边的留白里，不伸进框）；「这段高度没有模块」放在悬停提示里
          var t0 = el('text', { x: 8, y: L.y + L.h / 2 + 3, class: 'lanealt empty' });
          t0.textContent = rng;
          var tt = el('title', {}); tt.textContent = '没有模块落在 ' + rng + ' 这段高度'; t0.appendChild(tt);
          lg.appendChild(t0); return;
        }
        if (L.name) { var t = el('text', { x: 8, y: L.y + 14, class: 'lanetxt' }); t.textContent = L.name; lg.appendChild(t); }
        var a = el('text', { x: 8, y: L.y + (L.name ? 26 : 14), class: 'lanealt' });
        a.textContent = rng; lg.appendChild(a);
      });
      svg.appendChild(lg);

      // 箭头是独立的 marker，不会跟着 stroke 变色，每种边色各备一个
      var defs = el('defs', {});
      [['a', 'var(--edge)'], ['ah', 'var(--hot)'], ['ahb', 'var(--hotb)'], ['ahf', 'var(--ink)']].forEach(function (p) {
        // userSpaceOnUse：箭头大小固定，不随线宽放大（默认按 stroke-width 缩放，粗的 runtime 边箭头会大得离谱）
        var m = el('marker', { id: p[0], viewBox: '0 0 8 8', refX: '7', refY: '4', markerUnits: 'userSpaceOnUse',
          markerWidth: '8', markerHeight: '8', orient: 'auto-start-reverse' });
        m.appendChild(el('path', { d: 'M0,0 L8,4 L0,8 z', fill: p[1] })); defs.appendChild(m);
      });
      svg.appendChild(defs);

      var N = {}; G.nodes.forEach(function (n) { n.cx = n.x * G.width; N[n.id] = n; });
      this.N = N;
      var self = this;

      // 展开着的目录：一个框把它底下的节点框在一起。框体在边的下面（背景），
      // 框头（收起按钮 + 名字）在边的命中区上面，否则按钮会被透明的宽命中区挡住。
      var fg = el('g', {}), fh = el('g', {});
      this.frames = {}; this.heads = {}; this.inFrame = {};
      var fpar = {};
      (G.frames || []).forEach(function (F) { fpar[F.id] = F.parent; });
      G.nodes.forEach(function (n) {             // 每个框底下有哪些节点（「只看……」过滤后要重数）
        for (var f = n.frame; f; f = fpar[f]) (self.inFrame[f] = self.inFrame[f] || []).push(n.id);
      });
      (G.frames || []).forEach(function (F) {
        var g = el('g', { class: 'frame', 'data-frame': F.id });
        g.appendChild(el('rect', { x: F.x, y: F.y, width: F.w, height: F.h, rx: 10 }));
        fg.appendChild(g); self.frames[F.id] = g;
        var h = el('g', { class: 'fh', 'data-frame': F.id }), tx = F.x + 10;
        if (CS.ds.canCut) {
          var cb = el('g', { class: 'xp', role: 'button', tabindex: '0', 'aria-label': '收起 ' + F.label });
          cb.appendChild(el('circle', { cx: F.x + 15, cy: F.y + 12, r: 7 }));
          var ct = el('text', { x: F.x + 15, y: F.y + 15.5, 'text-anchor': 'middle' });
          ct.textContent = '−'; cb.appendChild(ct);
          var tip = el('title', {});
          tip.textContent = '收起 ' + F.label + '：框里的 ' + (F.total || F.n) + ' 个节点合回一个'; cb.appendChild(tip);
          var go = function (ev) { ev.preventDefault(); ev.stopPropagation(); if (self.onCollapse) self.onCollapse(F.id); };
          cb.onclick = go;
          cb.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') go(ev); };
          cb.onmouseenter = function () { g.classList.add('hover'); };
          cb.onmouseleave = function () { g.classList.remove('hover'); };
          h.appendChild(cb); tx = F.x + 28;
        }
        var t = el('text', { x: tx, y: F.y + 16, class: 'fl' });
        t.textContent = F.label; h.appendChild(t);
        var c = el('text', { x: tx + F.lw + 8, y: F.y + 16, class: 'fn' });
        c.textContent = F.count || ('· ' + F.n); h.appendChild(c);
        h._count = c; h._F = F; h._label = t; h._tx = tx;
        fh.appendChild(h); self.heads[F.id] = h;
      });
      svg.appendChild(fg);

      var hotPk = (hot && hot.packages) || {}, hotEd = (hot && hot.edges) || {}, cmp = this.cmp;
      var hotDyn = (hot && hot.dyn) || {};
      if (cmp) {                                   // 粗细、「跑到了」都按两边的较大值
        hotPk = {}; hotEd = {};
        Object.keys(cmp.nodes).forEach(function (k) { hotPk[k] = Math.max(cmp.nodes[k][0], cmp.nodes[k][1]); });
        Object.keys(cmp.edges).forEach(function (k) { hotEd[k] = Math.max(cmp.edges[k][0], cmp.edges[k][1]); });
      }
      this.hitPk = hotPk;
      var maxE = 1; for (var k in hotEd) maxE = Math.max(maxE, hotEd[k]);
      // 三层：光晕在最下，可见的边在中间，透明的宽命中区在最上（但仍在节点下面，节点照样能点）
      var hg = el('g', {}), eg = el('g', {}), xg = el('g', {});
      svg.appendChild(hg); svg.appendChild(eg); svg.appendChild(xg); svg.appendChild(fh);
      // 框头上的数紧跟在名字后面：名字的实际宽度要画出来才量得准（估算对长名字会偏）
      Object.keys(this.heads).forEach(function (f) {
        var h = self.heads[f], w = h._label.getComputedTextLength ? h._label.getComputedTextLength() : 0;
        if (w) h._count.setAttribute('x', h._tx + w + 8);
      });
      this.edges = [];
      var cnt = { ref: 0, imp: 0, type: 0, warm: 0, dyn: 0 };

      // 仅类型默认不显示：关着就不画、也不占接点（开关一动整张图重画，见 app.controls）。
      // 节点详情里照样列出来（typeOnly），不管开关
      this.typeOnly = typeOnly;
      var types = this.state.type ? typeOnly : [];
      var P = ports(N, G.edges.concat(rtOnly, types));
      function add(src, dst, kind, hits, info) {
        var a = N[src], b = N[dst]; if (!a || !b) return;
        var px = P[src + '|' + dst], d = route(a, b, px[0], px[1]);
        var ab = cmp ? (cmp.edges[src + '|' + dst] || [0, 0]) : null;
        var dab = cmp ? ((cmp.dyn || {})[src + '|' + dst] || [0, 0]) : null;
        var E = { a: src, b: dst, kind: kind, hits: hits, info: info, ab: ab,
                  dynOnly: kind !== 'dyn' && !!dynOnly[src + '|' + dst],
                  side: ab ? (ab[0] && ab[1] ? 'both' : ab[0] ? 'a' : ab[1] ? 'b' : '') : '',
                  w: hits ? 1.2 + 2.2 * Math.log1p(hits) / Math.log1p(maxE) : 1.2 };
        E.halo = el('path', { d: d, class: 'halo' });
        E.gap = el('path', { d: d, class: 'gap' });   // 光晕中间垫一道底色，灰虚线在蓝底上才看得清
        E.p = el('path', { d: d });
        E.x = el('path', { d: d, class: 'ehit' });
        var tip = el('title', {});
        tip.textContent = src + ' → ' + dst + '\n'
          + (kind === 'dyn' ? '静态 import 图里没有这条边（动态分派）'
             : kind === 'type' ? '只在 if TYPE_CHECKING: 里 import（仅类型）：运行时不存在，不算进架构高度'
             : (info.uses ? '用到对方 ' + info.uses + ' 个符号' : '只 import，没用到任何符号')
               + (info.dead ? '　·　' + info.dead + ' 个 import 没被引用' : ''))
          + (ab ? '\nruntime 调用 A ' + ab[0] + ' / B ' + ab[1] : (hits ? '\nruntime 调用 ' + hits + ' 次' : ''))
          + (E.dynOnly ? '\n跑到的调用全是动态分派：这条边上的 import / 引用这次都没跑到，跑到的调用不经过它们'
             : kind === 'dyn' ? ''
             : dab && (dab[0] || dab[1]) ? '\n其中动态分派 A ' + dab[0] + ' / B ' + dab[1] + ' 次'
             : !cmp && hotDyn[src + '|' + dst] ? '\n其中 ' + hotDyn[src + '|' + dst] + ' 次是动态分派（代码里看不到引用）' : '')
          + (kind === 'type' ? '\n点击看 import 语句' : '\n点击看具体是哪些函数');
        E.x.appendChild(tip);
        E.x.onclick = function (ev) {
          ev.stopPropagation();
          if (self.state.selEdge === src + '|' + dst) self.clear(); else self.pickEdge(src, dst);   // 再点一次取消选中
        };
        E.x.onmouseenter = function () { E.p.classList.add('hover'); E.halo.classList.add('hover'); };
        E.x.onmouseleave = function () { E.p.classList.remove('hover'); E.halo.classList.remove('hover'); };
        hg.appendChild(E.halo); hg.appendChild(E.gap); eg.appendChild(E.p); xg.appendChild(E.x);
        self.edges.push(E);
        cnt[kind]++; if (E.dynOnly) cnt.dyn++; else if (hits && kind !== 'dyn') cnt.warm++;
      }
      G.edges.forEach(function (e) {
        var key = e[0] + '|' + e[1], info = kinds[key] || { uses: 1, dead: 0 };
        add(e[0], e[1], info.uses ? 'ref' : 'imp', hotEd[key] || 0, info);
      });
      rtOnly.forEach(function (e) { add(e[0], e[1], 'dyn', e[2], {}); });
      types.forEach(function (e) { add(e[0], e[1], 'type', 0, {}); });
      cnt.type = typeOnly.length;              // 关着也要数：图例上的开关靠它出现
      this.counts = cnt;

      var ng = el('g', {}); svg.appendChild(ng); this.nodes = {};
      G.nodes.forEach(function (n) {
        var hits = hotPk[n.id] || 0, nab = cmp ? (cmp.nodes[n.id] || [0, 0]) : null;
        var side = nab ? (nab[0] && nab[1] ? ' both' : nab[0] ? ' warm' : nab[1] ? ' warmb' : ' cold') : (hot ? (hits ? ' warm' : ' cold') : '');
        var g = el('g', { class: 'nd' + side, tabindex: '0', role: 'button', 'data-id': n.id });
        g.dataset.id = n.id;
        g.appendChild(el('rect', { x: n.cx - n.w / 2, y: n.cy - n.h / 2, width: n.w, height: n.h }));
        var t = el('text', { x: n.cx, y: n.cy - 3, class: 'nl', 'text-anchor': 'middle' });
        t.textContent = n.label; g.appendChild(t);
        var s = el('text', { x: n.cx, y: n.cy + 9, class: 'ns', 'text-anchor': 'middle' });
        s.textContent = n.files + 'f · ' + n.classes + 'c' + (nab ? (hits ? ' · ' + nab[0] + '/' + nab[1] : '') : (hits ? (' · ' + hits) : ''));
        g.appendChild(s);
        if (n.expandable && CS.ds.canCut) {
          // 左上角的 ＋：在当前图上展开成子模块
          var xp = el('g', { class: 'xp', role: 'button', tabindex: '0' });
          xp.appendChild(el('circle', { cx: n.cx - n.w / 2 + 1, cy: n.cy - n.h / 2 + 1, r: 7 }));
          var xt = el('text', { x: n.cx - n.w / 2 + 1, y: n.cy - n.h / 2 + 4.5, 'text-anchor': 'middle' });
          xt.textContent = '+'; xp.appendChild(xt);
          var tip = el('title', {}); tip.textContent = '展开成 ' + n.fanout + ' 个子模块'; xp.appendChild(tip);
          xp.onclick = function (ev) { ev.stopPropagation(); if (self.onExpand) self.onExpand(n.id); };
          xp.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); ev.stopPropagation(); if (self.onExpand) self.onExpand(n.id); } };
          g.appendChild(xp);
        }
        var bd = el('text', { x: n.cx + n.w / 2 - 5, y: n.cy - n.h / 2 + 8, class: 'badge todo', 'text-anchor': 'end' });
        g.appendChild(bd); g._badge = bd;
        ng.appendChild(g); self.nodes[n.id] = g;
        // 再点一次选中的节点就取消选中（程序里调 pick 总是选中，比如从详情面板跳过来）
        var toggle = function () { if (self.state.sel === n.id) self.clear(); else self.pick(n.id); };
        g.onclick = function (ev) { ev.stopPropagation(); toggle(); };
        g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } };
      });
      this.wireBox(svg.parentNode);
      this.fit();
      this.paint();
    },

    /* 图框：点空白处（泳道、框体、图框两侧）取消选中；图比窗口宽时按住空白处拖动来平移。
       节点、边、按钮的点击自己 stopPropagation，到不了这里 */
    wireBox: function (box) {
      if (!box || box._wired) return;
      box._wired = true;
      var self = this, drag = null, moved = false;
      box.addEventListener('mousedown', function (ev) {
        // 平时只在空白处按下才拖；移动模式下哪里都能拖（按在节点上拖也不会选中它）
        if (ev.button !== 0 || (!self.panMode && ev.target.closest('.nd, .ehit, .xp'))) return;
        drag = { x: ev.clientX, y: ev.clientY, sl: box.scrollLeft, st: box.scrollTop };
        moved = false;
        if (self.panMode) ev.preventDefault();
      });
      // 拖动结束时的那次 click 不能落到节点 / 边上（捕获阶段先拦下）
      box.addEventListener('click', function (ev) {
        if (moved) { moved = false; ev.stopPropagation(); ev.preventDefault(); }
      }, true);
      // 按住 Ctrl（Mac 上 ⌘）滚滚轮缩放，以鼠标所在的点为中心；不按 Ctrl 的滚轮照常滚页面。
      // 触控板的双指捏合在浏览器里也是「按着 Ctrl 的滚轮」，一并支持
      box.addEventListener('wheel', function (ev) {
        if (!(ev.ctrlKey || ev.metaKey)) return;
        ev.preventDefault();
        self.zoomBy(Math.exp(-ev.deltaY * (ev.deltaMode === 1 ? 0.05 : 0.0022)), ev.clientX, ev.clientY);
      }, { passive: false });
      window.addEventListener('mousemove', function (ev) {
        if (!drag) return;
        var dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
        moved = true; box.classList.add('dragging');
        box.scrollLeft = drag.sl - dx;
        box.scrollTop = drag.st - dy;
      });
      window.addEventListener('mouseup', function () { drag = null; box.classList.remove('dragging'); });
      box.addEventListener('click', function () {
        var s = self.state;
        if (s.sel || s.selEdge || s.selFrame) self.clear();
      });
      // 缩放 / 移动按钮
      var ctl = box.parentNode && box.parentNode.querySelector('.gctl');
      if (ctl) [].forEach.call(ctl.querySelectorAll('[data-z]'), function (b) {
        b.onclick = function () {
          var z = b.dataset.z;
          if (z === 'pan') { self.setPan(!self.panMode); return; }
          if (z === 'reset') { self.setZoom(1); return; }
          // 以图框的中心为准
          var r = box.getBoundingClientRect();
          self.zoomBy(z === 'in' ? 1.25 : 0.8, r.left + r.width / 2, r.top + r.height / 2);
        };
      });
      box.addEventListener('scroll', function () { self.fade(); });
      window.addEventListener('resize', function () { self.fit(); });
    },

    /* 图框铺满页面中间那一大块（整页宽，上面一条和下面的抽屉之外的高度），在框里上下左右滚。
       live 模式按图框宽度排版（app 把宽度传给 serve），画布宽就等于图框宽；展开多了画布更宽，
       最多缩到 0.88 倍，再宽就横向滚动。导出版的画布宽度是固定的，宽屏上最多放大到 1.25 倍 */
    fit: function () {
      var svg = this.svg, G = this.G, box = svg && svg.parentNode, wrap = box && box.parentNode;
      if (!wrap || !G) return;
      var scale = Math.max(0.88, Math.min(1.25, box.clientWidth / G.width));
      svg.style.minWidth = svg.style.maxWidth = 'none';
      svg.style.width = Math.round(G.width * scale * this.zoom) + 'px';
      var zl = wrap.querySelector('.gzl');
      if (zl) zl.textContent = Math.round(this.zoom * 100) + '%';
      this.fade();
    },

    /* 图框能用多宽（排版时也按它） */
    boxWidth: function () {
      var w = document.getElementById('gwrap');
      return (w && w.clientWidth ? w.clientWidth : document.documentElement.clientWidth - 32) - 2;
    },

    /* 缩放到 z 倍，(cx, cy) 这个屏幕上的点缩放前后指着图上同一个地方 */
    setZoom: function (z, cx, cy) {
      var svg = this.svg, box = svg && svg.parentNode;
      if (!box || this.hidden()) return;
      z = Math.max(0.3, Math.min(4, z));
      var r0 = svg.getBoundingClientRect(), rb = box.getBoundingClientRect();
      if (cx == null) { cx = rb.left + rb.width / 2; cy = rb.top + rb.height / 2; }
      var fx = r0.width ? (cx - r0.left) / r0.width : 0.5, fy = r0.height ? (cy - r0.top) / r0.height : 0;
      this.zoom = Math.abs(z - 1) < 0.02 ? 1 : z;
      this.fit();
      var r1 = svg.getBoundingClientRect();
      box.scrollLeft += (r1.left + fx * r1.width) - cx;
      box.scrollTop += (r1.top + fy * r1.height) - cy;
      this.fade();
    },

    zoomBy: function (k, cx, cy) { this.setZoom(this.zoom * k, cx, cy); },

    setPan: function (on) {
      this.panMode = on;
      var box = this.svg && this.svg.parentNode, b = box && box.parentNode.querySelector('[data-z="pan"]');
      if (box) box.classList.toggle('panmode', on);
      if (b) b.setAttribute('aria-pressed', on);
    },

    /* 图框能横向滚动时，哪边还有东西就在哪边渐隐；顺便显示「可以拖动」的提示 */
    fade: function () {
      var box = this.svg && this.svg.parentNode, wrap = box && box.parentNode;
      if (!wrap) return;
      var more = box.scrollWidth - box.clientWidth > 2;
      var l = wrap.querySelector('.gfade.l'), r = wrap.querySelector('.gfade.r');
      if (l) l.classList.toggle('on', more && box.scrollLeft > 2);
      if (r) r.classList.toggle('on', more && box.scrollLeft < box.scrollWidth - box.clientWidth - 2);
      box.classList.toggle('pan', more);
      var hint = document.getElementById('panhint');
      if (hint) hint.hidden = !more;
    },

    /* 图藏着（时序图在前面）：量出来的位置全是 0，滚动、缩放都不能做——会把时序图滚走 */
    hidden: function () { return !this.svg || this.svg.style.display === 'none'; },

    focus: function (id) {
      if (this.hidden()) return;
      var el = this.heads && this.heads[id] ? this.heads[id].querySelector('.xp') : this.nodes[id];
      if (el && el.focus) el.focus({ preventScroll: true });
    },

    /* 把刚展开的框 / 刚收回的节点横向滚进图框里（只横向：纵向交给页面，框可能比屏幕还高） */
    reveal: function (id) {
      if (this.hidden()) return;
      var box = this.svg && this.svg.parentNode, el = (this.frames || {})[id] || this.nodes[id];
      if (!el || !box || box.scrollWidth <= box.clientWidth) return;
      var r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
      if (r.left >= b.left && r.right <= b.right) return;
      box.scrollLeft += (r.left + r.width / 2) - (b.left + b.width / 2);
    },

    /* 取消选中：节点、边、框都不选，面板回到总览 */
    clear: function () {
      this.state.sel = this.state.selEdge = this.state.selFrame = null; this.paint();
      if (this.onClear) this.onClear();
    },

    /* 选中的节点被展开成了框：框算选中，面板不动（它讲的还是这个目录） */
    selectFrame: function (id) {
      this.state.sel = this.state.selEdge = null; this.state.selFrame = id; this.paint();
      if (this.onSelectFrame) this.onSelectFrame(id);
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
      if (s.onlyHot && !((this.hitPk || (this.hot && this.hot.packages) || {})[id] || 0)) return false;
      if (s.onlyNoted && (this.noteStatus[id] || 'todo') === 'todo') return false;
      return true;
    },

    paint: function () {
      var s = this.state, self = this, keep = null;
      this.edges.forEach(function (E) {
        // 有 import、但跑到的调用全是动态分派的边：「动态分派」开着就画成橙虚线，关了就退回没跑到的静态边
        E._dyn = E.kind === 'dyn' || (E.dynOnly && s.dyn);
        E._warm = E.hits > 0 && s.hot && E.kind !== 'dyn' && !E.dynOnly;
        E._show = (E.kind === 'dyn' ? s.dyn : E.kind === 'type' ? s.type
                   : (E._warm || E._dyn || (E.kind === 'ref' ? s.refs : s.imp))) && self.vis(E.a) && self.vis(E.b);
      });
      // 选中节点时留亮的：它自己和看得见的边连着的节点（关掉的那类边不算）
      if (s.selEdge) { keep = {}; var ab = s.selEdge.split('|'); keep[ab[0]] = keep[ab[1]] = 1; }
      else if (s.sel) {
        keep = {}; keep[s.sel] = 1;
        this.edges.forEach(function (E) {
          if (!E._show) return;
          if (E.a === s.sel) keep[E.b] = 1; if (E.b === s.sel) keep[E.a] = 1;
        });
      }
      this.edges.forEach(function (E) {
        var dyn = E._dyn, warm = E._warm, show = E._show;
        var mine = s.selEdge ? s.selEdge === E.a + '|' + E.b
                 : !!s.sel && (E.a === s.sel || E.b === s.sel);
        // hot 视图里没被调用的静态边退到背景：要看的是这个 case 走过的路
        var lit = warm || dyn;
        // 对比时：只有 A 跑到 = 橙（warm），只有 B = 紫（warmb），两边都跑到 = 前景色（both）
        var tone = !lit ? '' : E.side === 'b' ? ' warmb' : E.side === 'both' ? ' both' : ' warm';
        var cls = 'e ' + (dyn ? 'dyn' : E.kind) + (lit ? tone : (s.onlyHot ? ' bg' : ''))
                + (keep && !mine ? ' dim' : '') + (mine ? ' hi' : '');
        E.p.setAttribute('class', cls);
        E.p.style.strokeWidth = (lit ? E.w : 1.2) + (mine ? 1 : 0);
        E.p.setAttribute('marker-end', 'url(#' + (!lit ? 'a' : E.side === 'b' ? 'ahb' : E.side === 'both' ? 'ahf' : 'ah') + ')');
        [E.p, E.x, E.halo, E.gap].forEach(function (x) { x.style.display = show ? '' : 'none'; });
        E.halo.classList.toggle('on', !!s.selEdge && mine);
        E.gap.classList.toggle('on', !!s.selEdge && mine);
        // 选中的边挪到各自那一层的最上面：线可以叠在一起，但选中时要看得出哪根指到哪
        if (mine) [E.halo, E.gap, E.p, E.x].forEach(function (x) { x.parentNode.appendChild(x); });
      });
      Object.keys(this.nodes).forEach(function (id) {
        var g = self.nodes[id];
        g.style.display = self.vis(id) ? '' : 'none';
        g.classList.toggle('dim', !!keep && !keep[id]);
        g.classList.toggle('sel', s.sel === id);
        g.classList.toggle('end', !!s.selEdge && !!keep && !!keep[id]);
      });
      // 框：「只看跑到的 / 已解读」把框里的节点全滤掉了就不画这个框；滤掉一部分就写「剩几个 / 一共几个」
      Object.keys(this.frames || {}).forEach(function (f) {
        var h = self.heads[f], F = h._F, ids = self.inFrame[f] || [];
        var k = ids.filter(function (i) { return self.vis(i); }).length;
        self.frames[f].style.display = h.style.display = k ? '' : 'none';
        self.frames[f].classList.toggle('sel', s.selFrame === f);
        h._count.textContent = k < ids.length ? '· ' + k + '/' + (F.total || F.n) : (F.count || '· ' + F.n);
      });
    },

    pick: function (id, stay) {
      this.state.sel = id; this.state.selEdge = this.state.selFrame = null; this.paint();
      if (this.onPick) this.onPick(id);
      var g = this.nodes[id];
      if (!stay && g && !this.inView(g)) this.showEl(g, true);
    },

    /* 图框里真正看得见的区域：浮在下沿的详情栏盖住的那一截不算 */
    viewRect: function () {
      var box = this.svg && this.svg.parentNode;
      if (!box) return null;
      var b = box.getBoundingClientRect(), bottom = b.bottom, dr = document.getElementById('drawer');
      if (dr) { var d = dr.getBoundingClientRect(); if (d.top < bottom) bottom = Math.max(b.top + 80, d.top - 8); }
      return { left: b.left, right: b.right, top: b.top, bottom: bottom };
    },

    inView: function (el) {
      var v = this.viewRect(), r = el.getBoundingClientRect();
      return !!v && r.left >= v.left && r.right <= v.right && r.top >= v.top && r.bottom <= v.bottom;
    },

    /* 把图上的一个元素滚到看得见的区域中间（不会滚到详情栏底下去） */
    showEl: function (el, smooth) {
      if (this.hidden()) return;
      var box = this.svg && this.svg.parentNode, v = this.viewRect();
      if (!el || !box || !v) return;
      var r = el.getBoundingClientRect();
      box.scrollBy({ left: (r.left + r.width / 2) - (v.left + v.right) / 2,
                     top: (r.top + r.height / 2) - (v.top + v.bottom) / 2, behavior: smooth ? 'smooth' : 'auto' });
    },

    pickEdge: function (a, b) {
      this.state.selEdge = a + '|' + b; this.state.sel = this.state.selFrame = null; this.paint();
      if (this.onPickEdge) this.onPickEdge(a, b);
    },

    /* 刚展开出来的节点闪一下 */
    flash: function (ids) {
      var self = this;
      ids.forEach(function (id) {
        var g = self.nodes[id];
        if (!g) return;
        g.classList.add('fresh');
        setTimeout(function () { g.classList.remove('fresh'); }, 1600);
      });
    },

    highlight: function (pred) {
      var self = this;
      Object.keys(this.nodes).forEach(function (id) {
        self.nodes[id].classList.toggle('match', !!pred && pred(self.N[id]));
      });
    }
  };
})(window.CS);
