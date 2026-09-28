/* 时序图：一个 run 里的跨文件调用按时间排开。和模块图共用切面（open）和选中：
 * 生命线 = (进程, 切面节点)，消息 = 两个节点之间的一次调用。点生命线头 = 选中节点，点消息 = 选中边，
 * 详情照旧在下面的抽屉里。数据来自 /api/seq（服务端按切面现折叠：同一节点内的调用不画、
 * 重复的片段折成 loop 行），时间刷用 /api/seq/overview。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var COLW = 156, ROWH = 26, GUT = 84, BRUSH = 46;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  // 微秒 → 人读的时长
  function dur(us) {
    if (us == null || us < 0) return '未返回';
    if (us < 1000) return us + 'µs';
    if (us < 1e6) return (us / 1000).toFixed(us < 1e4 ? 2 : 1) + 'ms';
    return (us / 1e6).toFixed(us < 1e7 ? 2 : 1) + 's';
  }
  function at(us) { return (us / 1e6).toFixed(us < 1e7 ? 3 : 2) + 's'; }
  // 窗口：起点 + 宽度（很密的一段不到 1ms，写成「1.440s – 1.440s」看起来像是空的）
  function span(a, b) { return at(a) + ' + ' + dur(Math.max(0, b - a)); }
  // 节点名在图上太长：去掉仓库的顶层包名前缀
  function short(id) {
    var roots = (CS.app && CS.app.data && CS.app.data.repo && CS.app.data.repo.roots) || [];
    var pre = roots.length === 1 ? roots[0].split('/').pop() + '.' : '';
    return pre && id.indexOf(pre) === 0 ? id.slice(pre.length) : id;
  }

  CS.seq = {
    data: null, over: null, req: null, _seq: 0,

    /* 取一个时间窗并画出来。opts：{t0, t1, max}；不给 t0 就从当前阶段的起点开始，自动收窄 */
    show: function (opts) {
      var self = this, my = ++this._seq, root = document.getElementById('seqv');
      opts = opts || {};
      var focusSel = opts.focusSel;
      this.req = Object.assign({}, opts);
      delete this.req.focusSel;
      root.hidden = false;
      if (!root.firstChild) root.innerHTML = '<div class="sq-empty">读取时序…</div>';
      var prog = document.getElementById('prog'), run = CS.ds.run;
      prog.textContent = '读取时序…';
      // 概览按 run 缓存：换了 run 就重取（旧 run 的请求晚回来也不能拿来用）
      var over = this.over && this.over._run === run ? Promise.resolve(this.over)
        : CS.ds.seqOverview().then(function (o) { if (o) o._run = run; return o; }).catch(function () { return null; });
      return Promise.all([CS.ds.seq(Object.assign({ open: CS.app.curOpen() }, this.req)), over])
        .then(function (r) {
          if (my !== self._seq) return;
          self.data = r[0];
          self.over = r[1];
          if (prog.textContent === '读取时序…') prog.textContent = '';
          self.render();
          if (focusSel) self.scrollToSel();
        }).catch(function (e) {
          if (my !== self._seq) return;
          if (prog.textContent === '读取时序…') prog.textContent = '';
          self.data = null;                          // 不留上一次的：之后的重画不能把旧图（可能是别的 run 的）盖回来
          root.innerHTML = '<div class="sq-empty">' + esc(e.message) + '</div>';
        });
    },

    hide: function () {
      this._seq++;
      var root = document.getElementById('seqv'), prog = document.getElementById('prog');
      if (root) root.hidden = true;
      if (prog && prog.textContent === '读取时序…') prog.textContent = '';
    },

    /* 换 run：在路上的请求作废、概览重取、窗口回到新 run 的阶段起点（换切面时窗口保留，直接 show） */
    reset: function () {
      this._seq++;
      this.over = null;
      this.picked = null;
      this.data = null;
      this.req = {};
    },

    /* 把选中的那条边的第一条消息（或包着它的 loop）滚进可见的地方（抽屉上面） */
    scrollToSel: function () {
      var box = document.querySelector('.gbox'), el = document.querySelector('#seqv .sq-m.on, #seqv .sq-loop.on');
      if (!box || !el) return;
      var b = box.getBoundingClientRect(), r = el.getBoundingClientRect();
      var head = document.querySelector('#seqv .sq-head'), top = b.top + (head ? head.offsetHeight : 0) + 12;
      var dr = document.getElementById('drawer'), bottom = b.bottom - 12;
      if (dr) bottom = Math.min(bottom, dr.getBoundingClientRect().top - 12);
      if (r.top < top || r.bottom > bottom) box.scrollTop += r.top - top - Math.max(0, (bottom - top - r.height) / 3);
      if (r.left < b.left + 90 || r.right > b.right - 20) box.scrollLeft += r.left - b.left - 120;
    },

    render: function () {
      var d = this.data, self = this, root = document.getElementById('seqv');
      if (!d) return;
      var sel = CS.graph.state.sel, selEdge = CS.graph.state.selEdge;
      var L = d.lifelines || [], rows = d.rows || [];
      var W = GUT + Math.max(1, L.length) * COLW + 24;
      var h = '<div class="sq-head" style="min-width:' + W + 'px">' + this._bar(d) + this._brush(d) + this._lanes(d, W) + '</div>';
      var ae = document.activeElement, keep = ae && root.contains(ae)
        ? (ae.dataset.node ? '[data-node="' + ae.dataset.node + '"]' : ae.dataset.nav ? '[data-nav="' + ae.dataset.nav + '"]'
           : ae.dataset.i != null ? '.sq-row[data-i="' + ae.dataset.i + '"]' : null) : null;
      root.innerHTML = h + '<div class="sq-body"></div>';
      root.style.setProperty('--sqw', W + 'px');
      // 右上角浮着的搜索栏会盖住窗口信息和时间刷的右边：给它让出地方
      var sb = document.getElementById('sbar');
      root.style.setProperty('--sbw', (sb && !sb.hidden && getComputedStyle(sb).display !== 'none' ? sb.offsetWidth + 24 : 0) + 'px');
      var body = root.querySelector('.sq-body');
      if (d.too_dense) {
        body.innerHTML = '<div class="sq-empty">这个时间窗' + (d.too_dense.rows != null ? '里折叠后还有 ' + d.too_dense.rows + ' 行'
          : '里有 ' + d.too_dense.calls + ' 次跨文件调用') + '，画不下。'
          + '<button class="chip" data-sug="1">看建议的窗口 ' + at(d.too_dense.suggest[0]) + ' – ' + at(d.too_dense.suggest[1]) + '</button></div>';
      } else if (!rows.length) {
        body.innerHTML = '<div class="sq-empty">这个时间窗里没有跨节点的调用'
          + (d.stat && d.stat.internal ? '（有 ' + d.stat.internal + ' 次调用发生在同一个节点内部：在模块图上展开这个节点就能看到）' : '')
          + (d.stat && d.stat.unmapped ? '（' + d.stat.unmapped + ' 次落在 index 之外的文件上）' : '') + '。</div>';
      } else {
        this._draw(body, d, W, sel, selEdge);
      }
      this._wire(root);
      if (keep) { var k = root.querySelector(keep); if (k) k.focus(); }      // 重画之后焦点留在原来那个东西上
    },

    _bar: function (d) {
      var w = d.window, st = d.stat || {};
      // 按钮放左边：右上角浮着搜索栏，会盖住右边
      return '<div class="sq-bar">'
        + '<span class="sq-win" title="' + at(w[0]) + ' – ' + at(w[1]) + '">' + span(w[0], w[1]) + '</span>'
        + '<button class="chip" data-nav="start" title="回到当前阶段的起点（折叠视图）">起点</button>'
        + '<button class="chip" data-nav="next" title="从这一屏最后一条之后接着看"' + (d.next_t0 == null ? ' disabled' : '') + '>下一屏 ▸</button>'
        + '<span class="sq-n">' + (d.fold === false ? '展开的循环（不折叠）· ' : '') + (st.rows || 0) + ' 行 · ' + (st.messages || 0) + ' 条消息'
        + (st.internal ? ' · 节点内部 ' + st.internal + ' 次没画' : '')
        + (st.imports ? ' · import 时的模块执行 ' + st.imports + ' 次没画' : '')
        + ((d.truncated || []).length ? ' · <span style="color:var(--stale)">有进程的事件到了上限，之后的没录</span>' : '') + '</span>'
        + '</div>';
    },

    /* 时间刷：每个进程一条密度线（整个 run），阶段分界、当前窗口；按住拖选一个新窗口 */
    _brush: function (d) {
      var o = this.over;
      if (!o || !o.procs || !o.procs.length) return '';
      var bins = o.bins, end = o.end_us || 1, n = Math.min(o.procs.length, 6);
      var procs = o.procs.slice().sort(function (a, b) { return sum(b.density) - sum(a.density); }).slice(0, n);
      function sum(a) { var s = 0; a.forEach(function (x) { s += x; }); return s; }
      var H = BRUSH, lh = (H - 6) / n, paths = '';
      procs.forEach(function (p, i) {
        var mx = Math.max.apply(null, p.density) || 1, y0 = 3 + (i + 1) * lh, pts = [];
        p.density.forEach(function (v, k) { pts.push((k / bins * 1000).toFixed(1) + ',' + (y0 - (v / mx) * (lh - 1)).toFixed(1)); });
        paths += '<polyline class="sq-dens" points="' + pts.join(' ') + '"/>';
      });
      var ph = (d.phases || []).map(function (p) {
        var x = (p.t_us / end * 1000).toFixed(1);
        return '<line class="sq-ph" x1="' + x + '" x2="' + x + '" y1="0" y2="' + H + '"/><text class="sq-pht" x="' + (+x + 3) + '" y="10">' + esc(p.name) + '</text>';
      }).join('');
      var w0 = d.window[0] / end * 1000, w1 = Math.max(w0 + 2, d.window[1] / end * 1000);
      return '<svg class="sq-brush" viewBox="0 0 1000 ' + H + '" preserveAspectRatio="none" data-end="' + end + '">'
        + '<rect class="sq-win-r" x="' + w0.toFixed(1) + '" y="0" width="' + (w1 - w0).toFixed(1) + '" height="' + H + '"/>'
        + paths + ph + '<rect class="sq-drag" x="0" y="0" width="0" height="' + H + '" style="display:none"/></svg>';
    },

    /* 生命线头：第一行进程（跨它的几条生命线），第二行节点 */
    _lanes: function (d, W) {
      var L = d.lifelines || [], procs = {}, h1 = '', h2 = '';
      (d.procs || []).forEach(function (p) { procs[p.pid] = p; });
      var sel = CS.graph.state.sel, i = 0;
      while (i < L.length) {
        var j = i;
        while (j < L.length && L[j].pid === L[i].pid) j++;
        var p = procs[L[i].pid] || {};
        h1 += '<div class="sq-proc" style="left:' + (GUT + i * COLW) + 'px;width:' + ((j - i) * COLW - 6) + 'px" title="'
          + esc((p.argv || []).join(' ')) + '">' + esc(p.label || '?') + ' <span class="sq-pid">pid ' + L[i].pid + '</span></div>';
        i = j;
      }
      L.forEach(function (l, k) {
        var dir = l.kind === 'dir' && CS.ds.canCut;
        h2 += '<button class="sq-life' + (l.node === sel ? ' on' : '') + (dir ? ' dir' : '') + '" data-node="' + esc(l.node) + '" style="left:' + (GUT + k * COLW) + 'px;width:' + (COLW - 6) + 'px" title="'
          + esc(l.node) + '（点一下选中这个模块）">' + esc(short(l.node)) + (l.kind === 'dir' ? '/' : '') + '</button>'
          + (dir ? '<button class="sq-xp" data-xp="' + esc(l.node) + '" style="left:' + (GUT + k * COLW + COLW - 28) + 'px" title="展开这个目录（模块图和时序图一起细到它下面的子模块）">＋</button>' : '');
      });
      return '<div class="sq-lanes" style="width:' + W + 'px">' + h1 + h2 + '</div>';
    },

    _draw: function (body, d, W, sel, selEdge) {
      var L = d.lifelines, rows = d.rows, H = rows.length * ROWH + 16;
      var svg = el('svg', { class: 'sq-svg', width: W, height: H, viewBox: '0 0 ' + W + ' ' + H }, null);
      body.appendChild(svg);
      var defs = el('defs', {}, svg);
      var mk = el('marker', { id: 'sqa', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
      el('path', { d: 'M0,0 L8,4 L0,8 z', class: 'sq-ah' }, mk);
      var cx = function (k) { return GUT + k * COLW + (COLW - 6) / 2; };
      L.forEach(function (l, k) {
        el('line', { class: 'sq-ll' + (l.node === sel ? ' on' : ''), x1: cx(k), x2: cx(k), y1: 0, y2: H }, svg);
      });
      var firstOf = {};
      L.forEach(function (l, k) { if (firstOf[l.pid] == null) firstOf[l.pid] = k; });
      var t0 = d.window[0];
      rows.forEach(function (r, i) {
        var y = 8 + i * ROWH + ROWH / 2, g = el('g', { class: 'sq-row sq-' + r.k, 'data-i': i }, svg);
        if (r.k === 'm' || r.k === 'loop') { g.setAttribute('tabindex', '0'); g.setAttribute('role', 'button'); }
        if (r.k !== 'idle') el('text', { class: 'sq-t', x: 8, y: y + 4 }, g).textContent = '+' + dur(r.t - t0).replace('未返回', '');
        if (r.k === 'm') {
          var x1 = cx(r.from), x2 = cx(r.to), on = selEdge === r.a + '|' + r.b;
          g.setAttribute('class', 'sq-row sq-m' + (on ? ' on' : '') + (r.async ? ' async' : '') + (r.d < 0 ? ' open' : ''));
          el('line', { class: 'sq-hit', x1: x1, x2: x2, y1: y, y2: y }, g);
          el('line', { class: 'sq-arrow', x1: x1, x2: x2 + (x2 > x1 ? -3 : 3), y1: y, y2: y, 'marker-end': 'url(#sqa)' }, g);
          var lx = Math.min(x1, x2) + 6, tx = el('text', { class: 'sq-lab', x: lx, y: y - 5 }, g);
          tx.textContent = r.fb + (r.rep > 1 ? ' ×' + r.rep : '') + '  ' + dur(r.d) + (r.async ? '（async，挂起 ' + r.susp + ' 次）' : '');
          var tt = el('title', {}, g);
          tt.textContent = r.fa + ' → ' + r.fb + '\n' + r.a + ' → ' + r.b + '\n' + r.f + ':' + r.l + '\n开始 ' + at(r.t) + '，用时 ' + dur(r.d)
            + '\npid ' + (L[r.from] || {}).pid + ' 线程 ' + r.tid;
        } else if (r.k === 'loop') {
          if (r.body.some(function (x) { return selEdge === x.a + '|' + x.b; })) g.setAttribute('class', 'sq-row sq-loop on');
          var ks = [];
          r.body.forEach(function (x) { ks.push(x.from, x.to); });
          var lo = Math.min.apply(null, ks), hi = Math.max.apply(null, ks), bx = cx(lo) - 10, bw = cx(hi) - cx(lo) + 20;
          el('rect', { class: 'sq-loopbox', x: bx, y: y - ROWH / 2 + 3, width: Math.max(bw, 60), height: ROWH - 6, rx: 5 }, g);
          var lt = el('text', { class: 'sq-lab', x: bx + 8, y: y + 4 }, g);
          lt.textContent = '↻ ×' + r.n + '　' + r.body.map(function (x) { return x.fb; }).join(' → ') + '　' + dur(r.d) + '（点开看这一段）';
        } else if (r.k === 'idle') {
          el('text', { class: 'sq-idle', x: GUT, y: y + 4 }, g).textContent = '⋯ 空闲 ' + dur(r.d);
        } else if (r.k === 'spawn') {
          var a = firstOf[r.ppid], b = firstOf[r.pid];
          if (a != null && b != null) {
            el('line', { class: 'sq-spawn', x1: cx(a), x2: cx(b) + (cx(b) > cx(a) ? -3 : 3), y1: y, y2: y, 'marker-end': 'url(#sqa)' }, g);
            el('text', { class: 'sq-lab', x: Math.min(cx(a), cx(b)) + 6, y: y - 5 }, g).textContent = '起了子进程 ' + r.pid;
          }
        }
      });
    },

    _wire: function (root) {
      var self = this, d = this.data;
      // 点生命线头、消息、loop 自己处理，不能冒泡到图框（图框的「点空白处取消选中」会把刚选中的又清掉）；
      // 点时序图的空白处照样冒泡上去取消选中，和模块图一样
      [].forEach.call(root.querySelectorAll('.sq-life'), function (b) {
        b.onclick = function (ev) { ev.stopPropagation(); CS.app.seqPickNode(b.dataset.node); };
      });
      [].forEach.call(root.querySelectorAll('.sq-xp'), function (b) {
        b.onclick = function (ev) { ev.stopPropagation(); CS.app.expand(b.dataset.xp); };
      });
      [].forEach.call(root.querySelectorAll('.sq-row'), function (g) {
        var r = d.rows[+g.dataset.i];
        // 点开 loop：请求那一段、不折叠；很长的分屏看（下一屏接着不折）
        if (r.k === 'm') g.onclick = function (ev) { ev.stopPropagation(); CS.app.seqPickMsg(r, d); };
        if (r.k === 'loop') g.onclick = function (ev) { ev.stopPropagation(); self.show({ t0: r.t, t1: r.t + Math.max(r.d, 1), fold: 0, max: 600 }); };
        if (r.k === 'm' || r.k === 'loop') g.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); g.onclick(ev); }
        });
      });
      [].forEach.call(root.querySelectorAll('.sq-bar button, .sq-empty button'), function (b) {
        b.addEventListener('click', function (ev) { ev.stopPropagation(); });
      });
      var sug = root.querySelector('[data-sug]');
      if (sug) sug.onclick = function () { self.show({ t0: d.too_dense.suggest[0], t1: d.too_dense.suggest[1] }); };
      [].forEach.call(root.querySelectorAll('[data-nav]'), function (b) {
        b.onclick = function () {
          if (b.dataset.nav === 'start') { self.show({}); return; }
          // 从服务端给的 next_t0 接着看（这一屏之后的第一条），不按最后一行的结束时刻猜——
          // loop 的结束时刻里可能包着挂起的时间，那样会跳过一段
          if (d.next_t0 == null) { if (CS.viewer) CS.viewer.toast('已经是最后一屏'); return; }
          var q = self.req || {};
          if (q.fold === 0 && q.t1 != null && d.next_t0 <= q.t1) self.show({ t0: d.next_t0, t1: q.t1, fold: 0, max: q.max || 600 });
          else self.show({ t0: d.next_t0 });
        };
      });
      var br = root.querySelector('.sq-brush');
      if (br) this._wireBrush(br);
    },

    _wireBrush: function (br) {
      var self = this, end = +br.dataset.end, drag = br.querySelector('.sq-drag'), x0 = null;
      function fx(ev) { var r = br.getBoundingClientRect(); return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)); }
      br.addEventListener('click', function (ev) { ev.stopPropagation(); });
      br.addEventListener('mousedown', function (ev) {
        if (ev.button !== 0) return;
        ev.preventDefault();
        ev.stopPropagation();                         // 图框按住空白处拖动是平移：在时间刷上拖是选窗口
        x0 = fx(ev);
        drag.style.display = '';
        drag.setAttribute('x', x0 * 1000); drag.setAttribute('width', 0);
        function mv(e2) { var x = fx(e2); drag.setAttribute('x', Math.min(x0, x) * 1000); drag.setAttribute('width', Math.abs(x - x0) * 1000); }
        function up(e2) {
          window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up);
          drag.style.display = 'none';
          // 拖完在别处松开：随后那次 click 落在两者的共同祖先上、冒泡到图框会取消选中——吞掉它
          var box = document.querySelector('.gbox');
          function swallow(e3) { e3.stopPropagation(); e3.preventDefault(); }
          if (box) { box.addEventListener('click', swallow, true); setTimeout(function () { box.removeEventListener('click', swallow, true); }, 0); }
          var x = fx(e2), a = Math.min(x0, x) * end, b = Math.max(x0, x) * end;
          // 点一下（没拖开）：从那一刻开始自动收窄；拖出一段：就看这一段
          if (Math.abs(x - x0) < 0.004) self.show({ t0: Math.round(a) });
          else self.show({ t0: Math.round(a), t1: Math.round(b) });
        }
        window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
      });
    }
  };
})(window.CS);
