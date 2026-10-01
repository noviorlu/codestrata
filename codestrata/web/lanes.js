/* 按进程 · 线程分列（P0，用户 2026-10-01 定的展示；数据是 /api/lanes，见 lanes.py）。
 *
 * 叠了录了时序事件的 run，运行时的图就是它（用户 10-01：运行时一律按线程分，不要合成一张图的功能）：模块图按
 * 进程 · 线程分成并排的几列，按进程分组；每列只放这条线程调到的节点，列里的边是这条线程里的调用。同一个节点在几列里
 * 各有一份，放在同一高度（纵坐标沿用「只看跑到的」那张图的分层）；鼠标停在一份上（或选中它）时高亮别的列里的副本并连上。
 * 列之间的连线：谁把数据交给谁（handoff，粗线，标通道和次数）、谁起了谁（spawn，绿色细虚线）、谁回收了谁（join，红色细虚线：
 * join / waitpid 等到它结束）。起线程、回收线程的那个节点像阶段的起点 / 终点那样描成绿 / 红、上面写「▶ 起 …」「■ 收 …」；
 * 列头写这一列的线程什么时候起、什么时候收（或者没人收）。选中一条连线，两头的节点下面标出那一行代码（起线程、放 / 取、
 * 发 / 收、join 的那一行），详情里列出每一对的代码（lanedetail.js），点了在代码窗口里看那一行。
 * 「边」那一行的开关照样管用：这次跑了 / 其中代码里看不出管列里的边，时间顺序把列里的边和交接连线放在一起、
 * 跨线程按第一次发生的先后排名上色、标序号。点节点、点列里的边：和模块图一样开详情；点列之间的连线：详情里列出
 * 两头各是哪个函数、几次、什么时候。缩放、拖动沿用 graph.js 的图框。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  function el(t, a) { var e = document.createElementNS(NS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fmtN(n) { return n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + '万' : String(n); }
  function short(k) { return k ? k.slice(k.indexOf('#') + 1) : ''; }
  function laneName(id) { return id.slice(id.indexOf(':') + 1); }
  // TOP：图框左上角浮着缩放按钮，进程头、列头往下让一点
  // HEAD：列头（线程名、仓库外的代码、起 / 收两行）的底
  var NW = 132, GAP = 10, PAD = 12, MINW = 104, EXTW = 92, FOLDW = 112, TOP = 36, HEAD = TOP + 72, REPEAT = 5;
  var VIA = { janus: 'janus 队列', zmq: 'ZMQ', queue: 'queue.Queue', asyncio: 'asyncio.Queue',
              thread: '起线程', exec: '起子进程（exec）', fork: '起子进程（fork）',
              join: 'join 等它结束', wait: 'waitpid 等子进程退出' };
  var KIND = { handoff: '谁把数据交给谁', spawn: '谁起了谁', join: '谁回收了谁' };
  // 连线两头的那一行代码是什么：放 / 取，起线程 / 线程入口，线程入口 / join 的那一行
  var ENDS = { handoff: ['放 / 发', '取 / 收'], spawn: ['起', '入口'], join: ['入口', '收'] };
  /* 微秒 → 相对这一段开头的秒数（这一段之前的是负的） */
  function when(us, w0) {
    if (us == null) return '?';
    var s = (us - w0) / 1e6;
    return (s < 0 ? '−' : '+') + Math.abs(s).toFixed(3) + ' s';
  }
  function clip(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  /* 列头的起 / 收两行：[{kind: start|end, text, title}] */
  function life(ln, w0) {
    var out = [], s = ln.start, e = ln.stop, proc = ln.thread === 'MainThread';
    function who(id) { return id ? laneName(id) : '不在任何一列里的线程'; }
    if (s) out.push({ kind: 'start', text: '▶ 起 ' + (s.n > 1 ? '×' + s.n + ' ' : '') + when(s.t, w0),
      title: '▶ 起：' + (s.n > 1 ? s.n + ' 个' + (proc ? '进程' : '线程') + '，第一个' : '') + '在 ' + when(s.t, w0) + ' 由 ' + who(s.lane) + ' 起'
        + (s.daemon ? '（其中守护线程 ' + s.daemon + ' 个）' : '') });
    if (e) {
      var tot = e.joined + e.exited + e.running, how = proc ? 'waitpid 等到退出' : 'join 等到结束', txt, tt;
      if (e.joined === tot) {
        txt = '■ 收 ' + (tot > 1 ? '×' + tot + ' ' : '') + when(e.t, w0);
        tt = '■ 收：' + (tot > 1 ? '全部 ' + tot + ' 个都被等到了，最后一个' : '') + '在 ' + when(e.t, w0) + ' 被 ' + who(e.lane) + ' ' + how;
      } else if (proc) {
        txt = '■ 没看到谁收'; tt = '■ 没看到谁 waitpid 等它退出（可能是轮询 poll() 收的，或者到录制结束还在跑）';
      } else {
        txt = e.joined ? '■ 收 ' + e.joined + '/' + tot : e.running ? '■ 没收 · 还在跑' : '■ 没收 · 跑完了';
        tt = '■ ' + (e.joined ? e.joined + ' 个被 ' + who(e.lane) + ' ' + how + '（最后一个在 ' + when(e.t, w0) + '）；' : '')
          + (e.exited ? e.exited + ' 个自己跑完了、没人 join；' : '') + (e.running ? e.running + ' 个到录制结束还在跑；' : '')
          + '\n没人 join 的：非守护线程进程退出时解释器会等它，守护线程直接丢下';
      }
      out.push({ kind: 'end', text: txt, title: tt });
    }
    return out;
  }

  CS.lanes = {
    // 详情栏（lanedetail.js）也用的写法和说法
    fmt: { esc: esc, short: short, laneName: laneName, when: when, VIA: VIA, KIND: KIND, ENDS: ENDS },
    data: null, collapsed: {}, sel: null, edges: [], links: [], nodes: [],

    /* 取数并画（app.drawMain 在叠着录了时序事件的 run 时调） */
    show: function () {
      var self = this, svg = document.getElementById('g');
      var d = CS.app.data, tok = (this._tok = (this._tok || 0) + 1), ref = CS.ds.run;
      this.ready = null;
      return CS.ds.lanes(d.open).then(function (L) {
        if (tok !== self._tok) return;
        self.data = L;
        self.draw(svg, L, d.graphHot || d.graph, d.names || {});
        self.ready = ref;                          // 画好了的是哪个 run（@阶段）
        if (CS.app.lanesDrawn) CS.app.lanesDrawn();
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
      var self = this, w0 = (L.window || [0])[0];
      svg.textContent = '';
      this.names = names; this.sel = null;
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
      procs = procs.map(function (pid) {
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
        return { pid: pid, x: gx, w: x - gx - 14, lanes: ls };
      });
      // 列头和第一行节点之间留一条通道：接在列头上的连线（没有节点的列、收起的进程）从这里走，不压列头的字
      var W = Math.max(x, 400), top = HEAD + 60, Hh = top + (Math.max(y1, extra) - y0) + 60;
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + Hh);
      // 让 graph.js 的图框（缩放、拖动、适应宽度）照样工作；模块图那边的节点 / 边清空，免得开关、搜索去动它们
      CS.graph.svg = svg; CS.graph.G = { width: W, height: Hh, nodes: [], edges: [] };
      CS.graph.nodes = {}; CS.graph.edges = []; CS.graph.N = {}; CS.graph.tg = null;

      var bg = el('g', {}), eg = el('g', {}), lk = el('g', { class: 'ln-links' }), ng = el('g', {});
      var tw = el('g', { class: 'ln-twins' }), xl = el('g', {}), xg = el('g', {}), lab = el('g', {}), tg = el('g', { class: 'tord' });
      var lt = el('g', { class: 'ln-ltxts' }), defs = el('defs', {}), ct = el('g', { class: 'ln-codes' });
      // 从下往上：列的底、列里的边、副本之间的虚线、列之间的连线；命中区在它们上面、节点下面（列里的边的在连线的上面：
      // 跨列的长连线会从别的列里的短边上穿过，交叉的地方点到的是短边，长连线换个地方点）；连线的标签在节点上面——
      // 放在路径上不压节点的地方，每条连线都有一个一定点得到的把手；序号牌在最上面
      // 选中连线时两头标的那一行代码（ct）在最上面
      [defs, bg, eg, tw, lk, xl, xg, ng, lab, lt, tg, ct].forEach(function (g) { svg.appendChild(g); });
      this.defs = defs; this._mk = {}; this.tg = tg; this.tw = tw; this.ct = ct; this.svg = svg; this.L = L; this.W = W;
      var pos = {}, laneOf = {};                     // "列|节点" → 中心 {cx, cy, w, h}；列 id → 列的几何
      this.pos = pos;
      function nodeY(id) { return top + (yOf(id) - y0); }

      // 进程头：名字 + 收起 / 展开
      procs.forEach(function (P) {
        var name = P.lanes[0].proc, fold = !!self.collapsed[P.pid];
        var g = el('g', { class: 'ln-proc', 'data-pid': P.pid });
        g.appendChild(el('rect', { x: P.x, y: TOP + 2, width: Math.max(P.w, 40), height: 22, rx: 6 }));
        var t = el('text', { x: P.x + 22, y: TOP + 17, class: 'ln-pname' });
        t.textContent = name + '（pid ' + P.pid + '）';
        var tip = el('title', {}); tip.textContent = name + '（pid ' + P.pid + '）\n' + P.lanes.length + ' 列；点 '
          + (fold ? '▸ 展开' : '▾ 收起'); g.appendChild(tip);
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

      this.edges = []; this.links = []; this.nodes = [];
      cols.forEach(function (C) {
        var col = el('g', { class: 'ln-col' + (C.fold ? ' fold' : '') + (C.lane && C.lane.external ? ' ext' : '') });
        col.appendChild(el('rect', { x: C.x, y: TOP + 28, width: C.w, height: Hh - TOP - 32, rx: 8, class: 'ln-band' }));
        var head = el('text', { x: C.x + C.w / 2, y: TOP + 44, 'text-anchor': 'middle', class: 'ln-th' });
        col.appendChild(head);
        bg.appendChild(col);
        if (C.fold) {
          head.textContent = C.lanes.length + ' 列（收起）';
          C.lanes.forEach(function (ln) { laneOf[ln.id] = { x: C.x, w: C.w, fold: true }; });
          return;
        }
        var ln = C.lane;
        head.textContent = ln.thread + (ln.n_threads > 1 ? ' ×' + ln.n_threads : '');
        var tip = el('title', {});
        tip.textContent = ln.proc + ' · ' + ln.thread + (ln.n_threads > 1 ? '（' + ln.n_threads + ' 个线程）' : '')
          + (ln.names && ln.names.length && (ln.names.length > 1 || ln.names[0] !== ln.thread)
             ? '\n原名：' + ln.names.join('、') + (ln.n_threads > ln.names.length ? ' …' : '') : '')
          + (ln.external ? '\n只跑仓库外的代码（这里没有节点），是交接的一头才列出来' : '');
        col.appendChild(tip);                     // 悬停提示挂在整列上（挂在列头的 text 里会混进它的文字）
        if (ln.external) {
          var sub = el('text', { x: C.x + C.w / 2, y: TOP + 58, 'text-anchor': 'middle', class: 'ln-ext' });
          sub.textContent = '仓库外的代码'; col.appendChild(sub);
        }
        life(ln, w0).forEach(function (x, i) {        // 起 / 收：像阶段的起点 / 终点
          var lt2 = el('text', { x: C.x + C.w / 2, y: TOP + (ln.external ? 71 : 58) + 13 * i, 'text-anchor': 'middle',
                                 class: 'ln-life ' + x.kind });
          lt2.textContent = x.text; col.appendChild(lt2);
          tip.textContent += '\n' + x.title;
        });
        laneOf[ln.id] = { x: C.x, w: C.w };
        // 这一列的节点：同一高度上按「只看跑到的」图里的左右顺序排
        Object.keys(C.rows).forEach(function (k) {
          var ids = C.rows[k], span = ids.length * (NW + GAP) - GAP, x0 = C.x + (C.w - span) / 2;
          ids.forEach(function (id, i) {
            var cx = x0 + i * (NW + GAP) + NW / 2, cy = nodeY(id), h = H[id] || 34;
            pos[ln.id + '|' + id] = { cx: cx, cy: cy, w: NW, h: h };
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
            var pick = function (ev) { ev.stopPropagation(); self.pickNode(id); };
            g.onclick = pick;
            g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } };
            ng.appendChild(g);
            self.nodes.push({ id: id, lane: ln.id, g: g });
          });
        });
        // 列里的边：这条线程里节点之间的调用。接点沿节点宽度摊开（graph.js 的 ports），上下排着的几条边不叠成一根
        var N = {}, pairs = [];
        ln.edges.forEach(function (e) {
          var ka = ln.id + '|' + e.a, kb = ln.id + '|' + e.b;
          if (pos[ka] && pos[kb]) { N[ka] = pos[ka]; N[kb] = pos[kb]; pairs.push([ka, kb]); }
        });
        var P = CS.graph.ports(N, pairs);
        ln.edges.forEach(function (e) {
          var ka = ln.id + '|' + e.a, kb = ln.id + '|' + e.b, a = pos[ka], b = pos[kb];
          if (!a || !b) return;
          var px = P[ka + '|' + kb], d = self.route(a, b, px[0], px[1]), dashed = e.n > 0 && e.only >= e.n;
          var E = { kind: 'edge', lane: ln, e: e, key: 'e:' + ka + '|' + e.b, dashed: dashed, first: e.first, last: e.last, n: e.n };
          E.p = el('path', { d: d, class: 'ln-e' + (dashed ? ' dyn' : '') });
          E.x = el('path', { d: d, class: 'ehit ln-hit' });
          E.tipBase = e.a + ' → ' + e.b + '\n' + ln.proc + ' · ' + ln.thread + ' 里调了 ' + e.n + ' 次'
            + (dashed ? '，全都是代码里看不出会调到的' : e.only ? '，其中约 ' + e.only + ' 次代码里看不出' : '')
            + '\n点击看具体是哪些函数（详情不分线程）';
          E.tip = el('title', {}); E.tip.textContent = E.tipBase; E.x.appendChild(E.tip);
          eg.appendChild(E.p); xg.appendChild(E.x);
          var L2 = E.p.getTotalLength ? E.p.getTotalLength() : 0, pt = L2 ? E.p.getPointAtLength(L2 / 2) : null;
          if (pt) {
            E.lab = el('text', { x: pt.x, y: pt.y + 3, class: 'ecnt', 'text-anchor': 'middle' });
            E.lab.textContent = fmtN(e.n); eg.appendChild(E.lab);
          }
          self.wire(E);
          self.edges.push(E);
        });
      });

      // 列之间的连线：一头是哪一列的哪个节点（收起的进程、没有节点的列：接在列头下面）
      function end(e) {
        var C = laneOf[e.lane];
        if (!C) return null;
        var p = !C.fold && e.node ? pos[e.lane + '|' + e.node] : null;
        return p || { cx: C.x + C.w / 2, cy: HEAD + 32, w: Math.min(C.w - 8, NW), h: 8, head: true };
      }
      var chan = {}, taken = Object.keys(pos).map(function (k) {     // 标签不压节点、不压别的标签
        var p = pos[k]; return [p.cx - p.w / 2 - 2, p.cy - p.h / 2 - 2, p.cx + p.w / 2 + 2, p.cy + p.h / 2 + 2];
      });
      function freeAt(path, w) {
        var len = path.getTotalLength(), best = null;
        [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.18, 0.82].some(function (f) {
          var q = path.getPointAtLength(len * f), r = [q.x - w / 2, q.y - 13, q.x + w / 2, q.y - 1];
          if (!taken.some(function (b) { return r[0] < b[2] && r[2] > b[0] && r[1] < b[3] && r[3] > b[1]; })) { best = q; return true; }
          return false;
        });
        best = best || path.getPointAtLength(len / 2);
        taken.push([best.x - w / 2, best.y - 13, best.x + w / 2, best.y - 1]);
        return best;
      }
      // 起线程 / 回收线程的节点：像阶段的起点 / 终点那样描成绿 / 红，上面写起了 / 收了哪一列（标签也占位置，连线的标签让开）
      var marks = {};
      (L.links || []).forEach(function (k, i) {
        var at = k.kind === 'spawn' ? k.from : k.kind === 'join' ? k.to : null;
        if (!at || !at.node || !pos[at.lane + '|' + at.node]) return;
        var m = marks[at.lane + '|' + at.node] = marks[at.lane + '|' + at.node] || { start: [], end: [] };
        m[k.kind === 'spawn' ? 'start' : 'end'].push({ i: i, name: laneName((k.kind === 'spawn' ? k.to : k.from).lane), k: k });
      });
      var markEls = [];
      this.nodes.forEach(function (x) {
        var m = marks[x.lane + '|' + x.id];
        if (!m) return;
        var p = pos[x.lane + '|' + x.id], row = 0;
        x.g.classList.add(m.start.length ? 'pstart' : 'pend');
        [['start', '▶ 起 '], ['end', '■ 收 ']].forEach(function (z) {
          var xs = m[z[0]];
          if (!xs.length) return;
          var ids = xs.map(function (y) { return (z[0] === 'start' ? y.k.to : y.k.from).lane; })
            .filter(function (v, j, a) { return a.indexOf(v) === j; });
          // 一列写名字，几列写列数（名字在悬停提示和点开的详情里）；不出这一列
          var txt = z[1] + (ids.length > 1 ? ids.length + ' 列' : clip(xs[0].name, 14));
          var y = p.cy - p.h / 2 - 5 - 12 * row++, hw = 3.6 * txt.length + 4, C = laneOf[x.lane];
          var cx = Math.max(C.x + hw, Math.min(C.x + C.w - hw, p.cx));
          var tx = el('text', { x: cx, y: y, class: 'pmark ln-mark ' + z[0], 'text-anchor': 'middle', role: 'button' });
          tx.textContent = txt;
          var tt = el('title', {});
          tt.textContent = xs.map(function (y2) {
            var pr = (y2.k.pairs || [])[0] || {}, la = z[0] === 'start' ? pr.la : pr.lb, ta = z[0] === 'start' ? pr.ta : pr.tb;
            return (z[0] === 'start' ? '这里起了 ' : '这里收了 ') + y2.name + (y2.k.n > 1 ? ' ×' + y2.k.n : '')
              + (la ? '：' + short(z[0] === 'start' ? pr.a : pr.b) + ':' + la + (ta ? '  ' + ta : '') : '');
          }).join('\n') + '\n点击看那条连线';
          tx.appendChild(tt);
          x.g.appendChild(tx);
          taken.push([cx - hw, y - 10, cx + hw, y + 2]);
          markEls.push({ el: tx, xs: xs, kind: z[0], lane: x.lane, node: x.id });
        });
      });
      var byIdx = {};
      (L.links || []).forEach(function (k, i) {
        var a = end(k.from), b = end(k.to);
        if (!a || !b || (Math.abs(a.cx - b.cx) < 1 && Math.abs(a.cy - b.cy) < 1)) return;   // 收起的同一个进程里的
        var d = self.linkRoute(a, b, chan);
        var E = { kind: 'link', k: k, key: 'l:' + i, first: k.first, last: k.last, n: k.n, A: a, B: b };
        byIdx[i] = E;
        E.p = el('path', { d: d, class: 'ln-link ' + k.kind + ' via-' + k.via });
        E.x = el('path', { d: d, class: 'ln-hit lk' });
        var pr = (k.pairs || [])[0], ends = ENDS[k.kind] || ['从', '到'];
        function code(side, fn, ln, tx) {
          return '\n' + side + '：' + (fn ? short(fn) + (ln ? ':' + ln + (tx ? '  ' + tx : '') : '') : '仓库外的代码');
        }
        E.tipBase = KIND[k.kind] + '：' + (k.kind === 'handoff' ? '经 ' : '') + (VIA[k.via] || k.via)
          + '，' + k.n + ' 次\n' + laneName(k.from.lane) + (k.from.node ? '（' + k.from.node + '）' : '')
          + ' → ' + laneName(k.to.lane) + (k.to.node ? '（' + k.to.node + '）' : '')
          + (pr ? code(ends[0], pr.a, pr.la, pr.ta) + code(ends[1], pr.b, pr.lb, pr.tb) : '')
          + (k.first != null && L.window ? '\n第一次在 ' + when(k.first, w0) : '')
          + '\n点击在两头标出那一行代码、看每一对';
        E.tip = el('title', {}); E.tip.textContent = E.tipBase; E.x.appendChild(E.tip);
        lk.appendChild(E.p); xl.appendChild(E.x);
        var txt = (k.kind === 'handoff' ? k.via : k.kind === 'join' ? '收' : '起') + (k.n > 1 ? ' ×' + fmtN(k.n) : '');
        var pt = E.p.getTotalLength ? freeAt(E.p, 6.2 * txt.length + 6) : null;
        if (pt) {
          E.lab = el('text', { x: pt.x, y: pt.y - 4, class: 'ln-ltxt ' + k.kind, 'text-anchor': 'middle' });
          E.lab.textContent = txt;
          lt.appendChild(E.lab);
        }
        self.wire(E);
        self.links.push(E);
      });
      markEls.forEach(function (m) {                 // 点节点上的「▶ 起 / ■ 收」：只有一条就选中它，几条就都高亮、详情里逐条列出
        var Es = m.xs.map(function (y) { return byIdx[y.i]; }).filter(Boolean);
        if (!Es.length) return;
        m.el.onclick = Es.length === 1 ? Es[0].click : function (ev) { ev.stopPropagation(); CS.laneDetail.marks(m, Es); };
      });
      CS.graph.wireBox(svg.parentNode);
      CS.graph.fit();
      this.paint();
    },

    /* 一条边 / 连线的交互：悬停加粗，点了选中、开详情（再点一次取消） */
    wire: function (E) {
      var self = this;
      E.click = function (ev) {
        ev.stopPropagation();
        if (self.sel === E.key) { CS.graph.clear(); return; }
        self.select(E.key);
        if (E.kind === 'edge') { if (CS.graph.onPickEdge) CS.graph.onPickEdge(E.e.a, E.e.b); }
        else CS.laneDetail.link(E.k);
        CS.app.drawer(true);
      };
      [E.x, E.lab].forEach(function (x) { if (x) x.onclick = E.click; });
      E.x.onmouseenter = function () { E.p.classList.add('hover'); };
      E.x.onmouseleave = function () { E.p.classList.remove('hover'); };
    },

    /* 列之间的连线的路径：同一个节点的各份放在同一高度，直着连会从中间那几列的节点上穿过去（被节点挡住、点不到），所以
       从起点节点的侧边出来，爬到上面那条「通道」（两行节点之间的空隙，取两头里靠上的那个节点的顶边再往上）里横着走，再落进
       终点节点的侧边。同一条通道里的几条上下错开（chan：通道 → 已经用了几条） */
    linkRoute: function (a, b, chan) {
      var right = b.cx >= a.cx, d1 = right ? 1 : -1, r = 16;
      var sx = a.cx + d1 * a.w / 2, ex = b.cx - d1 * b.w / 2;
      var topy = Math.min(a.cy - a.h / 2, b.cy - b.h / 2), ck = Math.round(topy / 10);
      var i = chan[ck] = (chan[ck] || 0) + 1, cy = topy - 9 - 6 * ((i - 1) % 5);
      if (d1 * (ex - sx) < 4 * r)                    // 两头挨得很近：一段拱过去
        return 'M' + sx + ',' + a.cy + ' C' + (sx + d1 * r) + ',' + cy + ' ' + (ex - d1 * r) + ',' + cy + ' ' + ex + ',' + b.cy;
      return 'M' + sx + ',' + a.cy + ' C' + (sx + d1 * r) + ',' + a.cy + ' ' + (sx + d1 * r) + ',' + cy + ' ' + (sx + 2 * d1 * r) + ',' + cy
        + ' L' + (ex - 2 * d1 * r) + ',' + cy
        + ' C' + (ex - d1 * r) + ',' + cy + ' ' + (ex - d1 * r) + ',' + b.cy + ' ' + ex + ',' + b.cy;
    },

    /* a → b（同一列里）的路径，sx / ex 是两端的接点横坐标：b 在下面竖着下去，否则从 a 的顶边拱上去再落进 b 的顶边 */
    route: function (a, b, sx, ex) {
      var bt = b.cy - b.h / 2 - 3;
      if (b.cy > a.cy + 2) {
        var y1 = a.cy + a.h / 2, my = (y1 + bt) / 2;
        return 'M' + sx + ',' + y1 + ' C' + sx + ',' + my + ' ' + ex + ',' + my + ' ' + ex + ',' + bt;
      }
      var at = a.cy - a.h / 2, tp = Math.min(at, bt) - 26 - Math.abs(ex - sx) * 0.05;
      return 'M' + sx + ',' + at + ' C' + sx + ',' + tp + ' ' + ex + ',' + tp + ' ' + ex + ',' + bt;
    },

    /* 按开关上色、藏起来、排时间顺序（画完、开关变了时调） */
    paint: function () {
      if (!this.svg || !this.L) return;
      var s = CS.graph.state, self = this, cnt = { scan: 0, warm: 0, dyn: 0 };
      this.edges.forEach(function (E) {
        E.show = E.dashed ? s.hot !== false && s.dyn !== false : s.hot !== false;
        if (E.dashed) cnt.dyn++; else cnt.warm++;
        [E.p, E.x, E.lab].forEach(function (x) { if (x) x.style.display = E.show ? '' : 'none'; });
      });
      this.links.forEach(function (E) { E.show = true; });
      CS.graph.counts = cnt;
      // 时间顺序：看得见的列里的边 + 交接连线放在一起，按第一次发生的先后排名（跨线程），按名次上色、标序号
      var tm = !!(s.timeOrder && CS.app.canTimeOrder());
      var list = tm ? this.edges.concat(this.links.filter(function (E) { return E.k.kind === 'handoff'; }))
        .filter(function (E) { return E.show && E.first != null; }) : [];
      list.sort(function (p, q) { return p.first - q.first || (p.last || 0) - (q.last || 0) || (p.key < q.key ? -1 : 1); });
      var n = list.length, w = this.L.window || [0, 0], span = Math.max(1, w[1] - w[0]);
      this.edges.concat(this.links).forEach(function (E) { E._t = null; });
      list.forEach(function (E, i) {
        E._t = { k: i, n: n, repeat: E.n >= REPEAT && (E.last - E.first) > span / 2 };
      });
      function sec(us) { return '+' + ((us - w[0]) / 1e6).toFixed(3) + ' s'; }
      this.edges.concat(this.links).forEach(function (E) {
        var tc = E._t ? self.timeColor(E._t.k / Math.max(1, n - 1)) : null;
        E._tc = tc;
        E.p.style.stroke = tc || '';
        E.p.classList.toggle('tm', !!tc);
        E.p.classList.toggle('bg', tm && !tc);
        E.p.setAttribute('marker-end', 'url(#' + self.marker(tc, E.kind === 'link' ? E.k.kind : 'edge') + ')');
        if (E.lab) E.lab.classList.toggle('tm', !!tc);
        E.tip.textContent = E.tipBase + (E._t ? '\n时间顺序：第 ' + (E._t.k + 1) + ' / ' + n + ' 个开始的　首次 ' + sec(E.first)
          + (E.last != null ? '　最后 ' + sec(E.last) : '') + (E._t.repeat ? '\n↻ 这段时间里一直在反复：序号只说明它从什么时候开始' : '') : '');
      });
      this.badges(list);
      CS.graph.timed = n;
      CS.graph.times = tm ? { window: w, truncated: this.L.truncated || [] } : null;
      this.applySel();
    },

    /* 序号牌：上了色的边 / 连线上画一个同色的小牌子，先试中点、被节点或别的牌子挡住就沿路径挪 */
    badges: function (list) {
      var tg = this.tg, boxes = [], self = this;
      tg.textContent = '';
      Object.keys(this.pos).forEach(function (k) {
        var p = self.pos[k]; boxes.push([p.cx - p.w / 2 - 3, p.cy - p.h / 2 - 3, p.cx + p.w / 2 + 3, p.cy + p.h / 2 + 3]);
      });
      function free(p, w) {
        var r = [p.x - w / 2, p.y - 8, p.x + w / 2, p.y + 8];
        return !boxes.some(function (b) { return r[0] < b[2] && r[2] > b[0] && r[1] < b[3] && r[3] > b[1]; });
      }
      list.forEach(function (E) {
        var num = String(E._t.k + 1), w = 9 + 6.4 * num.length + (E._t.repeat ? 11 : 0);
        var len = E.p.getTotalLength(), at = null;
        [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8].some(function (f) {
          var p = E.p.getPointAtLength(len * f);
          if (free(p, w)) { at = p; return true; }
          return false;
        });
        at = at || E.p.getPointAtLength(len / 2);
        boxes.push([at.x - w / 2, at.y - 8, at.x + w / 2, at.y + 8]);
        var g = el('g', { class: 'tn', 'data-key': E.key });
        g.onclick = E.click;
        g.appendChild(el('rect', { x: at.x - w / 2, y: at.y - 7.5, width: w, height: 15, rx: 7.5, fill: E._tc }));
        var t = el('text', { x: at.x - (E._t.repeat ? 5 : 0), y: at.y + 3.5, 'text-anchor': 'middle' });
        t.textContent = num; g.appendChild(t);
        if (E._t.repeat) {
          var r = el('text', { x: at.x + w / 2 - 7, y: at.y + 4.2, 'text-anchor': 'middle', class: 'rep' });
          r.textContent = '↻'; g.appendChild(r);
        }
        var tt = el('title', {}); tt.textContent = E.tip.textContent; g.appendChild(tt);
        tg.appendChild(g);
      });
    },

    /* 名次 f（0 最早 … 1 最晚）→ 颜色：--tm0 → --tm1 → --tm2 三个色标之间线性插值（跟着亮 / 暗主题） */
    timeColor: function (f) {
      var cs = getComputedStyle(this.svg), stops = ['--tm0', '--tm1', '--tm2'].map(function (v) {
        var h = cs.getPropertyValue(v).trim().replace('#', '');
        return [0, 2, 4].map(function (i) { return parseInt(h.substr(i, 2), 16); });
      });
      var x = Math.max(0, Math.min(1, f)) * 2, i = Math.min(1, Math.floor(x)), u = x - i;
      var c = stops[i].map(function (a, j) { return Math.round(a + (stops[i + 1][j] - a) * u); });
      return 'rgb(' + c.join(',') + ')';
    },

    /* 箭头（marker 不跟着 stroke 变色）：按颜色 / 种类现做、缓存 */
    marker: function (color, kind) {
      var fill = color || (kind === 'handoff' ? 'var(--cool)' : kind === 'spawn' ? 'var(--pstart)' : kind === 'join' ? 'var(--pend)' : 'var(--hot)');
      var id = this._mk[fill];
      if (!id) {
        id = this._mk[fill] = 'lnmk' + Object.keys(this._mk).length;
        var m = el('marker', { id: id, viewBox: '0 0 8 8', refX: '7', refY: '4', markerUnits: 'userSpaceOnUse',
          markerWidth: '8', markerHeight: '8', orient: 'auto' });
        m.appendChild(el('path', { d: 'M0,0 L8,4 L0,8 z', fill: fill }));
        this.defs.appendChild(m);
      }
      return id;
    },

    /* 选中：节点 n:<id>、列里的边 e:<列>|<a>|<b>、连线 l:<下标>。模块图的状态里记一个非空的 selEdge，
       点图框空白处、按 Esc 时 graph.clear 才会来清（经 app 的 onClear → unselect） */
    select: function (key, many) {
      this.sel = key; this.selMany = many || null;
      CS.graph.state.selEdge = key; CS.graph.state.sel = CS.graph.state.selFrame = null;
      this.applySel();
    },

    unselect: function () { this.sel = this.selMany = null; this.applySel(); if (this.tw) this.twins(null, false); },

    /* 选中之后和模块图一样：选中的那一条（几条）和它两头的节点照常，其余的淡下去。选中节点：它在各列里的每一份、
       列里碰到它的边、列之间碰到它的连线都高亮，这些边和连线另一头的节点照常 */
    applySel: function () {
      var s = this.sel, many = this.selMany, id = s && s.indexOf('n:') === 0 ? s.slice(2) : null;
      var keep = null, hi = {};                      // 照常的节点（"列|节点"）、高亮的边 / 连线
      function ends(E) {
        return E.kind === 'edge' ? [E.lane.id + '|' + E.e.a, E.lane.id + '|' + E.e.b]
          : [E.k.from.lane + '|' + E.k.from.node, E.k.to.lane + '|' + E.k.to.node];
      }
      if (s) {
        keep = {};
        this.edges.concat(this.links).forEach(function (E) {
          var on = id ? (E.kind === 'edge' ? E.e.a === id || E.e.b === id : E.k.from.node === id || E.k.to.node === id)
            : s === E.key || (!!many && many.indexOf(E.key) >= 0);
          if (!on) return;
          hi[E.key] = 1;
          ends(E).forEach(function (k) { keep[k] = 1; });
        });
        if (id) this.nodes.forEach(function (x) { if (x.id === id) keep[x.lane + '|' + x.id] = 1; });
      }
      this.edges.concat(this.links).forEach(function (E) {
        var on = !!hi[E.key], dim = !!keep && !on;
        E.p.classList.toggle('sel', on && !id);
        E.p.classList.toggle('hi', on && !!id);
        E.p.classList.toggle('dim', dim);
        if (E.lab) E.lab.classList.toggle('dim', dim);
        if (on) [E.p, E.lab].forEach(function (x) { if (x) x.parentNode.appendChild(x); });
      });
      this.nodes.forEach(function (x) {
        x.g.classList.toggle('sel', !!id && x.id === id);
        x.g.classList.toggle('dim', !!keep && !keep[x.lane + '|' + x.id]);
      });
      if (this.tg) [].forEach.call(this.tg.childNodes, function (g) {
        g.classList.toggle('on', g.dataset.key === s);
        g.classList.toggle('dim', !!keep && !hi[g.dataset.key]);
      });
      this.codeTags(this.links.filter(function (E) { return E.key === s; })[0]);
    },

    /* 选中的连线：两头的节点下面标出那一行代码（次数最多的那一对）——起线程的那一行、放 / 取的那一行、join 的那一行；
       那一头是线程入口的，标入口函数。点了在代码窗口里看那一行 */
    codeTags: function (E) {
      var ct = this.ct, self = this;
      if (!ct) return;
      ct.textContent = '';
      var pr = E && (E.k.pairs || [])[0];
      if (!pr) return;
      var ends = ENDS[E.k.kind] || ['从', '到'];
      [[E.A, pr.a, pr.la, pr.ta, pr.da, ends[0], pr.xa], [E.B, pr.b, pr.lb, pr.tb, pr.db, ends[1], pr.xb]].forEach(function (z, i) {
        var p = z[0], fn = z[1];
        if (!p) return;
        var txt = z[5] + ' · ' + (fn ? short(fn) + (z[2] ? ':' + z[2] + (z[3] ? '  ' + z[3] : '') : '（入口函数）') : '仓库外的代码');
        txt = clip(txt, 56);
        var y = p.cy + p.h / 2 + 14 + (i && Math.abs(E.A.cy - E.B.cy) < 1 && Math.abs(E.A.cx - E.B.cx) < 200 ? 18 : 0);
        var w = 6.1 * txt.length + 14, cx = Math.max(w / 2 + 2, Math.min(self.W - w / 2 - 2, p.cx));   // 不出图框
        var g = el('g', { class: 'ln-code ' + E.k.kind + (i ? ' b' : ' a'), role: 'button', tabindex: '0' });
        g.appendChild(el('rect', { x: cx - w / 2, y: y - 11, width: w, height: 16, rx: 4 }));
        var t = el('text', { x: cx, y: y + 1, 'text-anchor': 'middle' });
        t.textContent = txt; g.appendChild(t);
        var tt = el('title', {});
        tt.textContent = (fn || '仓库外的代码') + (z[2] ? ' 第 ' + z[2] + ' 行' : '') + (z[3] ? '\n' + z[3] : '')
          + (z[6] ? '\n经仓库外的代码，在这个函数里面' : '') + (fn ? '\n点了在代码窗口里看这一行' : '');
        g.appendChild(tt);
        if (fn && z[4]) {
          var go = function (ev) { ev.stopPropagation(); CS.viewer.open(z[4].f, z[2] || z[4].l); };
          g.onclick = go;
          g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(ev); } };
        }
        ct.appendChild(g);
      });
    },

    pickNode: function (id) {
      var key = 'n:' + id;
      if (this.sel === key) { CS.graph.clear(); return; }
      this.select(key);
      this.twins(id, false);
      if (CS.graph.onPick) CS.graph.onPick(id);
      CS.app.drawer(true);
    },

    /* 同一个节点在别的列里的副本：高亮并连上（鼠标停着的，和选中的） */
    twins: function (id, on) {
      if (!this.svg) return;
      var keep = this.sel && this.sel.indexOf('n:') === 0 ? this.sel.slice(2) : null, self = this;
      this.tw.textContent = '';
      this.nodes.forEach(function (x) { x.g.classList.toggle('twin', (on && x.id === id) || x.id === keep); });
      [on ? id : null, keep].forEach(function (z) {
        if (!z) return;
        var ps = self.nodes.filter(function (x) { return x.id === z; }).map(function (x) { return self.pos[x.lane + '|' + z]; })
          .sort(function (p, q) { return p.cx - q.cx; });
        for (var i = 1; i < ps.length; i++)
          self.tw.appendChild(el('line', { x1: ps[i - 1].cx + ps[i - 1].w / 2, y1: ps[i - 1].cy,
                                           x2: ps[i].cx - ps[i].w / 2, y2: ps[i].cy, class: 'ln-twin' }));
      });
    }
  };
})(window.CS);
