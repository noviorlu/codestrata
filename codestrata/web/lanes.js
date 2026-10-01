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
      CS.lanePick.leave();                            // 上一次画的提示、手形、单子、监听都撤掉
      svg.textContent = '';
      this.names = names; this.sel = null;
      // 纵坐标：「只看跑到的」那张图的分层（同一个节点在各列里同一高度）
      var Y = {}, X = {}, H = {}, ys = [];
      (G.nodes || []).forEach(function (n) { Y[n.id] = n.cy; X[n.id] = n.x; H[n.id] = n.h; ys.push(n.cy); });
      var y1 = ys.length ? Math.max.apply(null, ys) : 0;
      var extra = y1 + 70;                           // 不在那张图上的节点（很少见）：放在最下面一层
      function yOf(id) { return Y[id] != null ? Y[id] : extra; }
      // 列：按进程分组，收起的进程合成一列；每列按层（「只看跑到的」那张图的纵坐标）放这条线程调到的节点
      var cols = [], pidCols = {}, procs = [], ySet = {};
      L.lanes.forEach(function (ln) {
        if (!pidCols[ln.pid]) { pidCols[ln.pid] = []; procs.push(ln.pid); }
        pidCols[ln.pid].push(ln);
      });
      procs = procs.map(function (pid) {
        var ls = pidCols[pid], c0 = cols.length;
        if (self.collapsed[pid]) cols.push({ fold: true, pid: pid, lns: ls, lanes: ls.map(function (l) { return l.id; }), rows: {}, gap: c0 ? 14 : 0 });
        else ls.forEach(function (ln, k) {
          var rows = {};
          Object.keys(ln.nodes).forEach(function (id) { var y = yOf(id); ySet[y] = 1; (rows[y] = rows[y] || []).push(id); });
          Object.keys(rows).forEach(function (y) { rows[y].sort(function (a, b) { return (X[a] || 0) - (X[b] || 0); }); });
          cols.push({ lane: ln, pid: pid, lanes: [ln.id], external: !!ln.external, rowsY: rows, gap: !cols.length ? 0 : k === 0 ? 14 : 8 });
        });
        return { pid: pid, c0: c0, c1: cols.length - 1, lanes: ls };
      });
      var layers = Object.keys(ySet).map(Number).sort(function (a, b) { return a - b; }), li = {}, layerOf = {}, nodeH = {};
      layers.forEach(function (y, i) { li[y] = i; });
      cols.forEach(function (C) {
        C.rows = {};
        Object.keys(C.rowsY || {}).forEach(function (y) {
          C.rows[li[y]] = C.rowsY[y];
          C.rowsY[y].forEach(function (id) { layerOf[id] = li[y]; nodeH[id] = H[id] || 34; });
        });
      });
      var open = {};                                  // 画出来的节点（"列|节点"）：收起的进程里的不算
      cols.forEach(function (C) { if (!C.fold) Object.keys(C.lane.nodes).forEach(function (id) { open[C.lane.id + '|' + id] = 1; }); });
      // 起线程 / 回收线程的节点：像阶段的起点 / 终点那样描成绿 / 红，上面写起了 / 收了哪一列（排线时给标签留出高度）
      var marks = {}, reserve = {};
      (L.links || []).forEach(function (k, i) {
        var at = k.kind === 'spawn' ? k.from : k.kind === 'join' ? k.to : null;
        if (!at || !at.node || !open[at.lane + '|' + at.node]) return;
        var m = marks[at.lane + '|' + at.node] = marks[at.lane + '|' + at.node] || { start: [], end: [] };
        m[k.kind === 'spawn' ? 'start' : 'end'].push({ i: i, name: laneName((k.kind === 'spawn' ? k.to : k.from).lane), k: k });
      });
      Object.keys(marks).forEach(function (k) { reserve[k] = 12 * ((marks[k].start.length ? 1 : 0) + (marks[k].end.length ? 1 : 0)) + 10; });
      var top = HEAD + 60;
      var Rt = CS.laneRoute.route({
        NW: NW, GAP: GAP, PAD: PAD, MINW: MINW, EXTW: EXTW, FOLDW: FOLDW, headY: HEAD + 30, top: top,
        layers: layers.length ? layers : [0], layerOf: layerOf, nodeH: nodeH, cols: cols, reserve: reserve, gapEnd: 8,
        edges: [].concat.apply([], cols.filter(function (C) { return !C.fold; }).map(function (C) {
          return C.lane.edges.filter(function (e) { return C.lane.nodes[e.a] && C.lane.nodes[e.b]; })
            .map(function (e) { return { key: 'e:' + C.lane.id + '|' + e.a + '|' + e.b, lane: C.lane.id, a: e.a, b: e.b }; });
        })),
        links: (L.links || []).map(function (k, i) { return { key: 'l:' + i, from: k.from, to: k.to }; })
      });
      var W = Math.max(Rt.W, 400), Hh = Rt.H;
      svg.setAttribute('viewBox', '0 0 ' + W + ' ' + Hh);
      // 让 graph.js 的图框（缩放、拖动、适应宽度）照样工作；模块图那边的节点 / 边清空，免得开关、搜索去动它们
      CS.graph.svg = svg; CS.graph.G = { width: W, height: Hh, nodes: [], edges: [] };
      CS.graph.nodes = {}; CS.graph.edges = []; CS.graph.N = {}; CS.graph.tg = null;
      cols.forEach(function (C, ci) { C.x = Rt.cols[ci].x; C.w = Rt.cols[ci].w; });
      procs.forEach(function (P) { P.x = cols[P.c0].x; P.w = cols[P.c1].x + cols[P.c1].w - P.x; });

      var bg = el('g', {}), eg = el('g', {}), ng = el('g', {}), lk = eg;   // 列里的边和连线在同一层：选中的挪到最后就压在所有线上面
      var tw = el('g', { class: 'ln-twins' }), lab = el('g', {}), tg = el('g', { class: 'tord' });
      var lt = el('g', { class: 'ln-ltxts' }), defs = el('defs', {}), ct = el('g', { class: 'ln-codes' });
      // 从下往上：列的底、列里的边、副本之间的虚线、列之间的连线、节点；连线的标签在节点上面（放在路径上不压节点的地方，
      // 当把手）；序号牌、选中连线时两头标的那一行代码（ct）在最上面。线本身没有命中区：点哪条按离鼠标最近的算（lanepick.js）
      [defs, bg, eg, tw, ng, lab, lt, tg, ct].forEach(function (g) { svg.appendChild(g); });
      this.defs = defs; this._mk = {}; this.tg = tg; this.tw = tw; this.ct = ct; this.svg = svg; this.L = L; this.W = W;
      var pos = Rt.pos, laneOf = {};                 // "列|节点" → 中心 {cx, cy, w, h}（排线算的）；列 id → 列的几何
      this.pos = pos; this.route = Rt;

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
      cols.forEach(function (C, ci) {
        var col = el('g', { class: 'ln-col' + (C.fold ? ' fold' : '') + (C.lane && C.lane.external ? ' ext' : '') });
        col.appendChild(el('rect', { x: C.x, y: TOP + 28, width: C.w, height: Hh - TOP - 32, rx: 8, class: 'ln-band' }));
        var head = el('text', { x: C.x + C.w / 2, y: TOP + 44, 'text-anchor': 'middle', class: 'ln-th' });
        col.appendChild(head);
        bg.appendChild(col);
        if (C.fold) {
          head.textContent = C.lns.length + ' 列（收起）';
          C.lns.forEach(function (ln) { laneOf[ln.id] = { x: C.x, w: C.w, fold: true, ci: ci }; });
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
        laneOf[ln.id] = { x: C.x, w: C.w, ci: ci };
        // 这一列的节点：同一高度上按「只看跑到的」图里的左右顺序排（位置是排线算的：给轨道留了地方）
        Object.keys(C.rows).forEach(function (k) {
          C.rows[k].forEach(function (id) {
            var P0 = pos[ln.id + '|' + id], cx = P0.cx, cy = P0.cy, h = P0.h;
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
            var pick = function (ev) { ev.stopPropagation(); self.pickNode(id, ln.id); };
            g.onclick = pick;
            g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } };
            ng.appendChild(g);
            self.nodes.push({ id: id, lane: ln.id, g: g });
          });
        });
        // 列里的边：这条线程里节点之间的调用（路径是排线算的：各有各的接点和轨道）
        ln.edges.forEach(function (e) {
          var key = 'e:' + ln.id + '|' + e.a + '|' + e.b, R = Rt.paths[key];
          if (!R) return;
          var dashed = e.n > 0 && e.only >= e.n;
          var E = { kind: 'edge', lane: ln, e: e, key: key, dashed: dashed, first: e.first, last: e.last, n: e.n };
          E.halo = el('path', { d: R.d, class: 'ln-halo' });          // 线底下垫一圈底色：交叉的地方看得出谁压着谁
          E.p = el('path', { d: R.d, class: 'ln-e' + (dashed ? ' dyn' : '') });
          E.tipBase = e.a + ' → ' + e.b + '\n' + ln.proc + ' · ' + ln.thread + ' 里调了 ' + e.n + ' 次'
            + (dashed ? '，全都是代码里看不出会调到的' : e.only ? '，其中约 ' + e.only + ' 次代码里看不出' : '')
            + '\n点击看具体是哪些函数（详情不分线程）';
          E.tip = el('title', {}); E.tip.textContent = E.tipBase;    // 不挂在线上：悬停提示按离鼠标最近的那条线出（pointAt）
          eg.appendChild(E.halo); eg.appendChild(E.p);
          E.R = R; E.labTxt = fmtN(e.n); E.labCls = 'ecnt';      // 次数标签等连线画完、和连线的标签一起排（labels）
          self.wire(E);
          self.edges.push(E);
        });
      });

      // 列之间的连线：一头是哪一列的哪个节点（收起的进程、没有节点的列：接在列头下面）
      function end(e) {
        var C = laneOf[e.lane];
        if (!C) return null;
        var p = !C.fold && e.node ? pos[e.lane + '|' + e.node] : null;
        return p || Rt.heads[C.ci];
      }
      var taken = Object.keys(pos).map(function (k) {     // 标签不压节点、不压别的标签、不压起 / 收标记
        var p = pos[k]; return [p.cx - p.w / 2 - 2, p.cy - p.h / 2 - 2, p.cx + p.w / 2 + 2, p.cy + p.h / 2 + 2];
      });
      /* 标签写在线上（文字的底色把那一小段线盖住，一看就知道是哪条的）：挑横着的一段（长的先试，中间先试），
         竖着的段两边隔 8 像素就是别的竖轨、放不下；没有横段的（S 形）放中间。都被占了就放第一个候选 */
      var pk = CS.laneRoute.picker(Rt.paths);
      function bare(key, q, w) {                       // 这个位置的标签底下没有别的线（别的线会被标签盖住一截、点到的是标签）
        for (var dx = -w / 2; dx <= w / 2; dx += 6)
          if (pk.near(q[0] + dx, q[1], 6).some(function (h) { return h.key !== key; })) return false;
        return true;
      }
      function spot(R, w, key) {
        var P = R.pts, segs = [], cand = [];
        for (var i = 1; i < P.length; i++)
          if (Math.abs(P[i][1] - P[i - 1][1]) < 0.5 && Math.abs(P[i][0] - P[i - 1][0]) >= w + 8) segs.push([P[i - 1], P[i]]);
        segs.sort(function (a, b) { return Math.abs(b[1][0] - b[0][0]) - Math.abs(a[1][0] - a[0][0]); });
        segs.forEach(function (s) {
          var x0 = Math.min(s[0][0], s[1][0]) + w / 2 + 4, x1 = Math.max(s[0][0], s[1][0]) - w / 2 - 4;
          [0.5, 0.3, 0.7, 0.15, 0.85, 0, 1].forEach(function (f) { cand.push([x0 + (x1 - x0) * f, s[0][1]]); });
        });
        if (!cand.length) cand.push(P[Math.floor(P.length / 2)]);
        var best = null, ok = cand.filter(function (q) {
          var r = [q[0] - w / 2, q[1] - 7, q[0] + w / 2, q[1] + 7];
          return !taken.some(function (b) { return r[0] < b[2] && r[2] > b[0] && r[1] < b[3] && r[3] > b[1]; });
        });
        ok.some(function (q) { if (bare(key, q, w)) { best = q; return true; } return false; });   // 先挑底下没有别的线的
        best = best || ok[0] || cand[0];
        taken.push([best[0] - w / 2, best[1] - 7, best[0] + w / 2, best[1] + 7]);
        return best;
      }
      // 起线程 / 回收线程的节点上的标签（marks 在排线之前算好了；标签也占位置，连线的标签让开）
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
          var y = p.cy - p.h / 2 - 12 - 12 * row++, hw = 3.6 * txt.length + 4, C = laneOf[x.lane];   // 在箭头上面
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
        var a = end(k.from), b = end(k.to), R = Rt.paths['l:' + i];
        if (!a || !b || !R) return;                  // 收起的同一个进程里的
        var E = { kind: 'link', k: k, key: 'l:' + i, first: k.first, last: k.last, n: k.n, A: a, B: b };
        byIdx[i] = E;
        E.halo = el('path', { d: R.d, class: 'ln-halo' });
        E.p = el('path', { d: R.d, class: 'ln-link ' + k.kind + ' via-' + k.via });
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
        E.tip = el('title', {}); E.tip.textContent = E.tipBase;
        lk.appendChild(E.halo); lk.appendChild(E.p);
        E.R = R; E.labCls = 'ln-ltxt ' + k.kind;
        E.labTxt = (k.kind === 'handoff' ? k.via : k.kind === 'join' ? '收' : '起') + (k.n > 1 ? ' ×' + fmtN(k.n) : '');
        self.wire(E);
        self.links.push(E);
      });
      // 标签：连线的先排（它们是把手），再排次数；都在最上面那层，是那条线的把手
      this.labs = new Map();
      this.links.concat(this.edges).forEach(function (E) {
        var q = spot(E.R, E.kind === 'link' ? 6.2 * E.labTxt.length + 6 : 6 * E.labTxt.length + 4, E.key);
        E.lab = el('text', { x: q[0], y: q[1] + 3.5, class: E.labCls, 'text-anchor': 'middle' });
        E.lab.textContent = E.labTxt;
        lt.appendChild(E.lab);
        E.lab.onclick = E.click;
        self.labs.set(E.lab, E);
      });
      markEls.forEach(function (m) {                 // 点节点上的「▶ 起 / ■ 收」：只有一条就选中它，几条就都高亮、详情里逐条列出
        var Es = m.xs.map(function (y) { return byIdx[y.i]; }).filter(Boolean);
        if (!Es.length) return;
        m.el.onclick = Es.length === 1 ? Es[0].click : function (ev) { ev.stopPropagation(); CS.laneDetail.marks(m, Es); };
      });
      this.byKey = {};
      this.edges.concat(this.links).forEach(function (E) { self.byKey[E.key] = E; });
      this.picker = pk;
      CS.lanePick.wire(this, svg);
      CS.graph.wireBox(svg.parentNode);
      CS.graph.fit();
      this.paint();
    },

    /* 屏幕上的一点附近的线（看得见的），按离它的距离从近到远 [{E, d（屏幕像素）}]（lanepick.js） */
    hitAt: function (cx, cy, r) { return CS.lanePick.hitAt(this, cx, cy, r); },

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
    },

    /* 按开关上色、藏起来、排时间顺序（画完、开关变了时调） */
    paint: function () {
      if (!this.svg || !this.L) return;
      var s = CS.graph.state, self = this, cnt = { scan: 0, warm: 0, dyn: 0 };
      this.edges.forEach(function (E) {
        E.show = E.dashed ? s.hot !== false && s.dyn !== false : s.hot !== false;
        if (E.dashed) cnt.dyn++; else cnt.warm++;
        [E.halo, E.p, E.lab].forEach(function (x) { if (x) x.style.display = E.show ? '' : 'none'; });
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
        E.halo.classList.toggle('bg', tm && !tc);
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

    /* 选中之后和模块图一样：选中的那一条（几条）和它两头的节点照常，其余的淡下去。选中节点只算点的那一份（用户 10-01：
       分列里只高亮这一个，不高亮它在别的列里的副本）：这一列里碰到它的边、碰到这一份的连线高亮，另一头的节点照常 */
    applySel: function () {
      var s = this.sel, many = this.selMany, nk = s && s.indexOf('n:') === 0 ? s.slice(2) : null;   // "列|节点"
      var id = nk && nk.slice(nk.lastIndexOf('|') + 1), lane = nk && nk.slice(0, nk.lastIndexOf('|'));
      var keep = null, hi = {};                      // 照常的节点（"列|节点"）、高亮的边 / 连线
      function ends(E) {
        return E.kind === 'edge' ? [E.lane.id + '|' + E.e.a, E.lane.id + '|' + E.e.b]
          : [E.k.from.lane + '|' + E.k.from.node, E.k.to.lane + '|' + E.k.to.node];
      }
      if (s) {
        keep = {};
        this.edges.concat(this.links).forEach(function (E) {
          var on = nk ? (E.kind === 'edge' ? E.lane.id === lane && (E.e.a === id || E.e.b === id)
                         : (E.k.from.lane === lane && E.k.from.node === id) || (E.k.to.lane === lane && E.k.to.node === id))
            : s === E.key || (!!many && many.indexOf(E.key) >= 0);
          if (!on) return;
          hi[E.key] = 1;
          ends(E).forEach(function (k) { keep[k] = 1; });
        });
        if (nk) keep[nk] = 1;
      }
      this.edges.concat(this.links).forEach(function (E) {
        var on = !!hi[E.key], dim = !!keep && !on;
        E.p.classList.toggle('sel', on && !nk);
        E.p.classList.toggle('hi', on && !!nk);
        E.p.classList.toggle('dim', dim);
        E.halo.classList.toggle('dim', dim);
        if (E.lab) E.lab.classList.toggle('dim', dim);
        if (on) [E.halo, E.p, E.lab].forEach(function (x) { if (x) x.parentNode.appendChild(x); });
      });
      this.nodes.forEach(function (x) {
        x.g.classList.toggle('sel', x.lane + '|' + x.id === nk);
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
        // 标在节点的另一边：走上面的连线标在节点下面，走下面的（往左的）标在节点上面，不压着它自己
        var dy = (i && Math.abs(E.A.cy - E.B.cy) < 1 && Math.abs(E.A.cx - E.B.cx) < 200 ? 18 : 0);
        var y = E.R && E.R.low && !p.head ? p.cy - p.h / 2 - 10 - dy : p.cy + p.h / 2 + 14 + dy;
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

    /* 选中节点的一份（lane：哪一列；不给就取它出现的第一列）。详情讲这个节点（不分线程） */
    pickNode: function (id, lane) {
      if (!lane) { var x = this.nodes.filter(function (y) { return y.id === id; })[0]; lane = x ? x.lane : ''; }
      var key = 'n:' + lane + '|' + id;
      if (this.sel === key) { CS.graph.clear(); return; }
      this.select(key);
      this.twins(id, false);
      if (CS.graph.onPick) CS.graph.onPick(id);
      CS.app.drawer(true);
    },

    /* 同一个节点在别的列里的副本：鼠标停着的时候高亮并连上（选中只高亮点的那一份，不连副本） */
    twins: function (id, on) {
      if (!this.svg) return;
      var self = this;
      this.tw.textContent = '';
      this.nodes.forEach(function (x) { x.g.classList.toggle('twin', on && x.id === id); });
      [on ? id : null].forEach(function (z) {
        if (!z) return;
        var ps = self.nodes.filter(function (x) { return x.id === z; }).map(function (x) { return self.pos[x.lane + '|' + z]; })
          .sort(function (p, q) { return p.cx - q.cx; });
        for (var i = 1; i < ps.length; i++)
          self.tw.appendChild(el('line', { x1: ps[i - 1].cx + ps[i - 1].w / 2, y1: ps[i - 1].cy - ps[i - 1].h / 2 + 3,   // 贴着顶边：侧面出来的边在中间
                                           x2: ps[i].cx - ps[i].w / 2, y2: ps[i].cy - ps[i].h / 2 + 3, class: 'ln-twin' }));
      });
    }
  };
})(window.CS);
