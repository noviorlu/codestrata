/* 按进程 · 线程分列（P0，用户 2026-10-01 定的展示；数据是 /api/lanes，见 lanes.py）。
 *
 * 叠了录了时序事件的 run，运行时的图就是它（用户 10-01：运行时一律按线程分，不要合成一张图的功能）：模块图按
 * 进程 · 线程分成并排的几列，按进程分组；每列只放这条线程调到的节点，列里的边是这条线程里的调用。同一个节点在几列里
 * 各有一份，放在同一高度（纵坐标沿用「只看跑到的」那张图的分层）；鼠标停在一份上（或选中它）时高亮别的列里的副本并连上。
 * 列之间的连线：谁把数据交给谁（handoff，粗线，标通道和次数）、谁起了谁（spawn，绿色细虚线）、谁回收了谁（join，红色细虚线：
 * join / waitpid 等到它结束）。起线程、回收线程的那个节点像阶段的起点 / 终点那样描成绿 / 红、上面写「▶ 起 …」「■ 收 …」；
 * 列头写这一列的线程什么时候起、什么时候收（或者没人收）。选中一条连线，两头的节点下面标出那一行代码（起线程、放 / 取、
 * 发 / 收、join 的那一行），详情里列出每一对的代码（lanedetail.js），点了在代码窗口里看那一行。
 * 切面每列各自的（用户 10-02，lanecut.js）：能展开的节点左上角一个 ＋，只在这一列里展开；展开着的目录像模块图那样画成框，
 * 框头写名字、这一列里框着几个、−（只收起这一列里的它）。节点放在哪一行由 lanepack.js 排：一列展开不动别的列的层和先后。
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
  /* 段外的时刻（选了阶段 / 时间段时，起 / 收、交接发生在这一段之外）：每个时刻按它自己在不在这一段里标段前 / 段后（用户 10-01）。
     L：/api/lanes 的结果（window、segs）；落在阶段的两个时间片之间的，late（收）算段后，否则算段前（同 lanes.py 的 out_of） */
  var OUT = { before: '段前', after: '段后' };
  function outOf(us, L, late) {
    var w = (L && L.window) || null, segs = (L && L.segs) || (w ? [w] : []);
    if (us == null || !w || segs.some(function (s) { return us >= s[0] && us <= s[1]; })) return null;
    return us < w[0] ? 'before' : us > w[1] ? 'after' : late ? 'after' : 'before';
  }
  function whenW(us, L, late) {
    var o = outOf(us, L, late);
    return when(us, ((L && L.window) || [0])[0]) + (o ? '（' + OUT[o] + '）' : '');
  }
  /* has(列 id)：这一列画着没有（起 / 收它的线程这一段里没跑就没有列，照样写名字） */
  function life(ln, L, has) {
    var out = [], s = ln.start, e = ln.stop, proc = !!ln.proc_main || ln.thread === 'MainThread';   // 这一列代表整个子进程
    function who(id) { return id ? laneName(id) + (has(id) ? '' : '（这一段里没跑）') : '不在任何一列里的线程'; }
    if (s) out.push({ kind: 'start', out: !!(s.out), text: '▶ 起 ' + (s.n > 1 ? '×' + s.n + ' ' : '') + whenW(s.t, L),
      title: '▶ 起：' + (s.n > 1 ? s.n + ' 个' + (proc ? '进程' : '线程') + '，第一个' : '') + '在 ' + whenW(s.t, L) + ' 由 ' + who(s.lane) + ' 起'
        + (s.daemon ? '（其中守护线程 ' + s.daemon + ' 个）' : '') });
    if (e) {
      var tot = e.joined + e.exited + e.running, how = proc ? 'waitpid 等到退出' : 'join 等到结束', txt, tt;
      if (e.joined === tot) {
        txt = '■ 收 ' + (tot > 1 ? '×' + tot + ' ' : '') + whenW(e.t, L, true);
        tt = '■ 收：' + (tot > 1 ? '全部 ' + tot + ' 个都被等到了，最后一个' : '') + '在 ' + whenW(e.t, L, true) + ' 被 ' + who(e.lane) + ' ' + how;
      } else if (proc) {
        txt = '■ 没看到谁收'; tt = '■ 没看到谁 waitpid 等它退出（可能是轮询 poll() 收的，或者到录制结束还在跑）';
      } else {
        txt = e.joined ? '■ 收 ' + e.joined + '/' + tot : e.running ? '■ 没收 · 还在跑' : '■ 没收 · 跑完了';
        tt = '■ ' + (e.joined ? e.joined + ' 个被 ' + who(e.lane) + ' ' + how + '（最后一个在 ' + whenW(e.t, L, true) + '）；' : '')
          + (e.exited ? e.exited + ' 个自己跑完了、没人 join；' : '') + (e.running ? e.running + ' 个到录制结束还在跑；' : '')
          + '\n没人 join 的：非守护线程进程退出时解释器会等它，守护线程直接丢下';
      }
      out.push({ kind: 'end', out: !!(e.out), text: txt, title: tt });
    }
    return out;
  }

  CS.lanes = {
    // 详情栏（lanedetail.js）也用的写法和说法
    fmt: { esc: esc, short: short, laneName: laneName, when: when, whenW: whenW, VIA: VIA, KIND: KIND, ENDS: ENDS },
    data: null, collapsed: {}, sel: null, edges: [], links: [], nodes: [], frames: [], fpos: {}, laneIx: {},

    /* 取数并画（app.drawMain 在叠着录了时序事件的 run 时调） */
    show: function () {
      var self = this, svg = document.getElementById('g');
      var d = CS.app.data, tok = (this._tok = (this._tok || 0) + 1), ref = CS.ds.run;
      this.ready = null;
      // drawn：这次取数画完（搜索选中、改切面之后要等它画好再找节点）
      // 共用的切面 + 各列单独的切面（lanecut.js）
      return (this.drawn = CS.ds.lanes(d.open, CS.laneCut.query()).then(function (L) {
        if (tok !== self._tok) return;
        // 改切面画好之后接着选的，是这一刻选着的（取数可能要好几秒，这期间在旧图上点的那个算数）
        if (self.afterCut) self.afterCut.snap = self.snapshot();
        self.data = L;
        CS.laneCut.settle(L);
        self.panelData(L);
        self.draw(svg, L, d.graphHot || d.graph, d.names || {});
        CS.laneCut.after(self.afterCut);
        self.afterCut = null;
        self.ready = ref;                          // 画好了的是哪个 run（@阶段）
        if (CS.app.lanesDrawn) CS.app.lanesDrawn();
      }).catch(function (e) {
        if (tok !== self._tok) return;
        document.getElementById('prog').textContent = '';
        // 旧的那张图的模型不能留着：详情里的按钮、搜索、收起进程都会拿它去选看不见的东西
        self.nodes = self.edges = self.links = self.frames = []; self.byKey = {}; self.pos = {}; self.fpos = {}; self.laneIx = {};
        self.L = self._args = self.afterCut = null;
        CS.graph.clear();
        svg.textContent = '';
        svg.setAttribute('viewBox', '0 0 600 60');
        var t = el('text', { x: 12, y: 30, class: 'ln-err' });
        t.textContent = '按线程分列读取失败：' + e.message;
        svg.appendChild(t);
      }));
    },

    /* 各列单独的切面上的节点（展开 / 收起之后不是共用切面上的节点）：面板（文件、符号、文档、名字）和运行时的次数要它们的数据。
       模块图那份（CS.app.data）不改，给面板一份加上它们的（lanesview.py 的 info / more） */
    panelData: function (L) {
      var d = CS.app.data, info = L.info || {}, more = L.more || {};
      function ext(o) { return Object.assign({}, o || {}); }
      var m = Object.assign({}, d, { pkgs: ext(d.pkgs), names: ext(d.names), labels: ext(d.labels),
                                     pkgSyms: ext(d.pkgSyms), pkgFiles: ext(d.pkgFiles), pkgDocs: ext(d.pkgDocs) });
      var hot = d.hot ? Object.assign({}, d.hot, { packages: ext(d.hot.packages) }) : null;
      Object.keys(info).forEach(function (id) {
        var v = info[id];
        if (!m.pkgs[id] && v.files != null) m.pkgs[id] = v;              // 只是框的（没有文件数）不当节点
        if (m.names[id] == null) m.names[id] = v.name;
        if (m.labels[id] == null) m.labels[id] = v.label;
        if (hot && hot.packages[id] == null && v.hits) hot.packages[id] = v.hits;
      });
      Object.keys(more).forEach(function (id) {
        m.pkgSyms[id] = more[id].syms; m.pkgFiles[id] = more[id].files; m.pkgDocs[id] = more[id].docs;
      });
      m.hot = hot;
      CS.panel.setData(m);
      CS.graph.hot = hot;
    },

    /* 每列现在画着哪些节点（改切面之前记下，画好后各列各自闪新出来的）、节点是哪种（app.homeOf 找「谁装着它」） */
    beforeMap: function () {
      var out = {};
      this.nodes.forEach(function (x) { (out[x.lane] = out[x.lane] || {})[x.id] = 1; });
      return out;
    },
    kinds: function () {
      var info = (this.L || {}).info || {}, out = {};
      Object.keys(info).forEach(function (id) { out[id] = info[id].kind; });
      return out;
    },

    /* 作废还在路上的取数（换成模块图了）：它回来时不再画 */
    cancel: function () { this._tok = (this._tok || 0) + 1; this.afterCut = null; this.drawn = null; },

    /* 最近一次取数画完（改切面还在路上的话先等它）：搜索选中之类要在新图上找节点的，等它 */
    settled: function () {
      var self = this, cut = CS.app._pending && CS.app._cutP;
      return Promise.resolve(cut).then(function () {
        var d = self.drawn;
        return d ? d.then(function () { return self.drawn === d ? null : self.settled(); }) : null;
      });
    },

    /* 现在选着的：节点 / 框 / 边 / 连线的 key；连线的 key 是下标，换了切面会变，记下它是哪一条 */
    snapshot: function () {
      var s = this.sel, E = s && s.indexOf('l:') === 0 && this.byKey[s];
      return { sel: s, link: E ? { kind: E.k.kind, via: E.k.via, from: E.k.from.lane, to: E.k.to.lane, first: E.k.first } : null };
    },

    /* 节点 / 框在图上写的字：同模块图在这一列的切面上写的（框里的写相对于框的名字；lanesview.py 算好的每列 names） */
    label: function (id, lane) {
      var ln = (this.laneIx || {})[lane], nm = ln && ln.names && ln.names[id];
      return nm || CS.panel.short(id);
    },

    /* 画着的节点（每个节点 id 一个，不分列）：app.homeOf 按它找一个模块落在哪个节点上 */
    asGraph: function (lane) {                       // lane：只算这一列画着的（各列切面不一样，一个模块在各列里落在不同的节点上）
      var seen = {}, nodes = [];
      this.nodes.forEach(function (x) { if ((!lane || x.lane === lane) && !seen[x.id]) { seen[x.id] = 1; nodes.push({ id: x.id }); } });
      return { nodes: nodes };
    },

    /* 搜索选中一个节点：选中这一列里的那一份（不给列就是它的第一份：列的先后是进程启动先后、进程里按交接顺序），滚过去、闪一下。
       没画它返回 null */
    reveal: function (id, lane) {
      var x = this.nodes.filter(function (y) { return y.id === id && (!lane || y.lane === lane); })[0];
      if (!x) return null;
      if (this.sel !== 'n:' + x.lane + '|' + id) this.pickNode(id, x.lane);
      CS.graph.showEl(x.g, true);
      x.g.classList.add('fresh');
      setTimeout(function () { x.g.classList.remove('fresh'); }, 1600);
      return id;
    },

    /* 搜索高亮：pred(节点, 列) 为真的那一份描出来（各列按自己的切面算，见 search.highlight），同模块图的 .nd.match */
    highlight: function (pred) {
      this.nodes.forEach(function (x) { x.g.classList.toggle('match', !!pred && pred(x.id, x.lane)); });
    },

    /* 搜索选中一列里的框：已经选着就不动（pickFrame 再点一次是取消），不在图框里就滚过去，闪一下 */
    revealFrame: function (f, lane) {
      if (this.sel !== 'f:' + lane + '|' + f) this.pickFrame(f, lane);
      var x = this.frames.filter(function (y) { return y.lane === lane && y.id === f; })[0];
      if (!x) return null;
      if (!CS.graph.inView(x.h)) CS.graph.showEl(x.h, true);
      x.g.classList.add('fresh');
      setTimeout(function () { x.g.classList.remove('fresh'); }, 1600);
      return f;
    },

    /* 选中一列里的框（展开着的目录；key f:列|目录）：框描粗，不淡别的；详情正讲着它（刚在这一份上点了展开）就照旧、换成「收起」，
       不然列出这一列里框着的节点（lanedetail.frame）。quiet：改切面之后接着选，不去打开用户关上的详情栏 */
    pickFrame: function (f, lane, quiet) {
      var key = 'f:' + lane + '|' + f, det = document.getElementById('det');
      if (this.sel === key && !quiet) { CS.graph.clear(); return null; }
      this.select(key);
      if (det.dataset.pkg === f && det.dataset.lane === lane) {   // 详情正讲着这一列里的这一份（刚在它上面点了展开）
        CS.panel.asFrame(f, '已在这一列里展开成框');
        var slot = document.getElementById('nbslot'); if (slot) slot.textContent = '';
        var s = document.getElementById('dsub'); if (s) s.textContent = '已在 ' + laneName(lane) + ' 这一列里展开成框（框头的 − 收起）';
      } else CS.laneDetail.frame(f, lane);
      if (!quiet) CS.app.drawer(true);
      return f;
    },

    draw: function (svg, L, G, names) {
      var self = this, meta = L.info || {};          // 节点的信息（lanesview.py 的 info：哪种、能不能展开、在哪个框里）
      CS.lanePick.leave();                            // 上一次画的提示、手形、单子、监听都撤掉
      svg.textContent = '';
      this.names = names; this.sel = null; this._args = [svg, L, G, names];
      // 纵坐标：共用切面上「只看跑到的」那张图的分层（同一个节点在各列里同一高度）；各列单独展开出来的节点排在装着它的那个节点
      // 那一层下面的子行里，收起来的排在它装着的那几个里最高的一层（lanepack.keys）——一个节点在哪一行只看它自己，
      // 一列展开 / 收起不动别的列的层和先后（用户 10-02）
      var kindOf = {};
      (G.nodes || []).forEach(function (n) { kindOf[n.id] = n.kind; });
      function contains(X, n) { return X === n || CS.app.homeOf(n, kindOf[n], { nodes: [{ id: X }] }) === X; }
      var ids = [];
      L.lanes.forEach(function (ln) { if (!self.collapsed[ln.pid]) ids.push.apply(ids, Object.keys(ln.nodes)); });
      var K = CS.lanePack.keys(G, ids, L.place || {}, contains), Rk = CS.lanePack.rows(K), nodeH = {};
      Object.keys(K).forEach(function (id) { nodeH[id] = K[id].h; });
      // 列：按进程分组，收起的进程合成一列；每列放这条线程调到的节点，展开着的目录画成框（frames：这一列自己的切面上的）
      var cols = [], pidCols = {}, procs = [];
      L.lanes.forEach(function (ln) {
        if (!pidCols[ln.pid]) { pidCols[ln.pid] = []; procs.push(ln.pid); }
        pidCols[ln.pid].push(ln);
      });
      procs = procs.map(function (pid) {
        var ls = pidCols[pid], c0 = cols.length;
        if (self.collapsed[pid]) cols.push({ fold: true, pid: pid, lns: ls, lanes: ls.map(function (l) { return l.id; }), rows: {}, gap: c0 ? 14 : 0 });
        else ls.forEach(function (ln, k) {
          var frames = {}, frameOf = {}, fr = ln.frames || {};
          Object.keys(fr).forEach(function (f) { frames[f] = { parent: fr[f].parent, minw: fr[f].minw }; });
          Object.keys(ln.nodes).forEach(function (id) { var f = (meta[id] || {}).frame; frameOf[id] = f && fr[f] ? f : null; });
          cols.push({ lane: ln, pid: pid, lanes: [ln.id], external: !!ln.external, rows: CS.lanePack.colRows(Object.keys(ln.nodes), Rk),
                      frames: frames, frameOf: frameOf, gap: !cols.length ? 0 : k === 0 ? 14 : 8 });
        });
        return { pid: pid, c0: c0, c1: cols.length - 1, lanes: ls };
      });
      var layers = Rk.layers, layerOf = Rk.layerOf;
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
      var fg = el('g', {}), fhg = el('g', { class: 'ln-fheads' });
      // 从下往上：列的底、展开的目录的框、列里的边、副本之间的虚线、框头、节点；连线的标签在节点上面（放在路径上不压节点的地方，
      // 当把手）；序号牌、选中连线时两头标的那一行代码（ct）在最上面。线本身没有命中区：点哪条按离鼠标最近的算（lanepick.js）
      [defs, bg, fg, eg, tw, fhg, ng, lab, lt, tg, ct].forEach(function (g) { svg.appendChild(g); });
      this.defs = defs; this._mk = {}; this.tg = tg; this.tw = tw; this.ct = ct; this.svg = svg; this.L = L; this.W = W;
      var pos = Rt.pos, laneOf = {};                 // "列|节点" → 中心 {cx, cy, w, h}（排线算的）；列 id → 列的几何
      this.pos = pos; this.route = Rt; this.fpos = Rt.fpos || {}; this.frames = [];
      this.laneIx = {};
      L.lanes.forEach(function (ln) { self.laneIx[ln.id] = ln; });

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
        var go = function (ev) { ev.stopPropagation(); self.fold(P.pid, !fold); };
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
          + (ln.thread_names && ln.thread_names.length && (ln.thread_names.length > 1 || ln.thread_names[0] !== ln.thread)
             ? '\n原名：' + ln.thread_names.join('、') + (ln.n_threads > ln.thread_names.length ? ' …' : '') : '')
          + (ln.external ? '\n只跑仓库外的代码（这里没有节点），是交接的一头才列出来' : '')
          + (ln.idle ? '\n这一段里这条线程没有调用，是交接的一头才列出来（只放交接的那个节点），起 / 收不算它' : '');
        col.appendChild(tip);                     // 悬停提示挂在整列上（挂在列头的 text 里会混进它的文字）
        if (ln.external) {
          var sub = el('text', { x: C.x + C.w / 2, y: TOP + 58, 'text-anchor': 'middle', class: 'ln-ext' });
          sub.textContent = '仓库外的代码'; col.appendChild(sub);
        }
        life(ln, L, function (id) { return L.lanes.some(function (x) { return x.id === id; }); }).forEach(function (x, i) {   // 起 / 收：像阶段的起点 / 终点
          var lt2 = el('text', { x: C.x + C.w / 2, y: TOP + (ln.external ? 71 : 58) + 13 * i, 'text-anchor': 'middle',
                                 class: 'ln-life ' + x.kind + (x.out ? ' out' : '') });
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
            var nm = self.label(id, ln.id);
            t.textContent = nm.length > 18 ? nm.slice(0, 17) + '…' : nm; g.appendChild(t);
            var s = el('text', { x: cx, y: cy + 9, class: 'ns', 'text-anchor': 'middle' });
            s.textContent = info.n ? '被调 ' + fmtN(info.n) + ' 次' : info.handoff ? '只在这里交接' : '只往外调'; g.appendChild(s);
            var tp = el('title', {});
            tp.textContent = id + '\n' + ln.thread + ' 里' + (info.n ? '被调了 ' + info.n + ' 次' : info.handoff
              ? '这一段里没调到它，只是在这里放 / 取（交接在这一段里）' : '只当调用方')
              + '\n别的列里也有它的话，鼠标停在这里会连上；点了看详情';
            g.appendChild(tp);
            g.onmouseenter = function () { self.twins(id, true); };
            g.onmouseleave = function () { self.twins(id, false); };
            var pick = function (ev) { ev.stopPropagation(); self.pickNode(id, ln.id); };
            g.onclick = pick;
            g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } };
            var pk = meta[id] || {};
            if (pk.expandable)                        // 和模块图同一个 ＋（graph.js 的 .xp）；收起在框头的 −
              g.appendChild(self.cutBtn(cx - NW / 2 + 1, cy - h / 2 + 1, '+', '展开 ' + nm + '：在 ' + ln.thread + ' 这一列里换成它的 '
                                        + pk.fanout + ' 个子模块（别的列不变）', function () { CS.app.expand(id, ln.id); }));
            ng.appendChild(g);
            self.nodes.push({ id: id, lane: ln.id, g: g });
          });
        });
        self.drawFrames(ln, fg, fhg);
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
      var taken = Object.keys(pos).map(function (k) {     // 标签不压节点、框头、别的标签、起 / 收标记
        var p = pos[k]; return [p.cx - p.w / 2 - 2, p.cy - p.h / 2 - 2, p.cx + p.w / 2 + 2, p.cy + p.h / 2 + 2];
      }).concat(this.headBoxes());
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
        if (!cand.length)                            // S 形：沿曲线从中间往两头试（中间常压在框头、别的标签上）
          [0.5, 0.38, 0.62, 0.26, 0.74, 0.15, 0.85].forEach(function (f) { cand.push(P[Math.round((P.length - 1) * f)]); });
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
          var allOut = xs.every(function (y2) { return y2.k.out; });   // 起 / 收全在段外：淡一点
          var tx = el('text', { x: cx, y: y, class: 'pmark ln-mark ' + z[0] + (allOut ? ' out' : ''), 'text-anchor': 'middle', role: 'button' });
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
        E.p = el('path', { d: R.d, class: 'ln-link ' + k.kind + ' via-' + k.via + (k.out ? ' out' : '') });
        var pr = (k.pairs || [])[0], ends = ENDS[k.kind] || ['从', '到'];
        function code(side, fn, ln, tx) {
          return '\n' + side + '：' + (fn ? short(fn) + (ln ? ':' + ln + (tx ? '  ' + tx : '') : '') : '仓库外的代码');
        }
        E.tipBase = KIND[k.kind] + '：' + (k.kind === 'handoff' ? '经 ' : '') + (VIA[k.via] || k.via)
          + '，' + k.n + ' 次\n' + laneName(k.from.lane) + (k.from.node ? '（' + k.from.node + '）' : '')
          + ' → ' + laneName(k.to.lane) + (k.to.node ? '（' + k.to.node + '）' : '')
          + (pr ? code(ends[0], pr.a, pr.la, pr.ta) + code(ends[1], pr.b, pr.lb, pr.tb) : '')
          + (k.first != null && L.window ? '\n第一次在 ' + whenW(k.first, L, k.kind === 'join')
             + (k.last != null && k.last !== k.first ? '，最后在 ' + whenW(k.last, L, k.kind === 'join') : '') : '')
          + (k.out ? '\n整条发生在这一段' + (k.out === 'before' ? '开始之前' : '结束之后') + '（这一段里跑过的线程）' : '')
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
      if (!L.lanes.length) {                         // 这一段里哪条线程都没调到仓库里的代码：说一声，别留一张白图
        var w = L.window, msg = el('text', { x: 12, y: 30, class: 'ln-empty' });
        msg.textContent = '这一段' + (w ? '（长 ' + ((w[1] - w[0]) / 1e6).toFixed(3) + ' s）' : '')
          + '里哪条线程都没调到仓库里的代码：把时间段拖长一点，或者选一个阶段';
        svg.appendChild(msg);
        svg.setAttribute('viewBox', '0 0 720 60'); CS.graph.G.width = 720; CS.graph.G.height = 60;
      }
      this.byKey = {};
      this.edges.concat(this.links).forEach(function (E) { self.byKey[E.key] = E; });
      this.picker = pk;
      CS.lanePick.wire(this, svg);
      CS.graph.wireBox(svg.parentNode);
      CS.graph.fit();
      this.paint();
    },

    /* 一列里展开着的目录：框把这一列里它底下的节点框在一起（同模块图），框头写名字、这一列里框着几个、−（只收起这一列里的它，
       用户 10-02）。点框头选中这个框（详情里讲它），鼠标停在框头上连上别的列里的它 */
    drawFrames: function (ln, fg, fhg) {
      var self = this;
      Object.keys(ln.frames || {}).forEach(function (f) {
        var F = self.fpos[ln.id + '|' + f];
        if (!F) return;
        var fr = ln.frames[f], nm = self.label(f, ln.id);
        var g = el('g', { class: 'frame ln-fr', 'data-frame': f, 'data-lane': ln.id });
        g.appendChild(el('rect', { x: F.x, y: F.y, width: F.w, height: F.h, rx: 10 }));
        fg.appendChild(g);
        var h = el('g', { class: 'fh ln-fh', 'data-frame': f, 'data-lane': ln.id, role: 'button', tabindex: '0',
                          'aria-label': nm + '（' + ln.thread + ' 里展开着）' });
        h.appendChild(el('rect', { x: F.head.x, y: F.head.y, width: F.head.w, height: F.head.h, class: 'ln-fhit' }));
        fhg.appendChild(h);
        var t = el('text', { x: F.btn.x + 13, y: F.btn.y + 4, class: 'fl' });
        t.textContent = clip(nm, Math.max(4, Math.floor((F.w - 64) / 7)));
        h.appendChild(t);
        var c = el('text', { x: F.btn.x + 13 + (t.getComputedTextLength ? t.getComputedTextLength() : 7 * t.textContent.length) + 8,
                             y: F.btn.y + 4, class: 'fn' });
        c.textContent = '· ' + fr.n; h.appendChild(c);
        var tip = el('title', {});
        tip.textContent = f + '\n' + ln.thread + ' 这一列里展开着，框着它调到的 ' + fr.n + ' 个子模块\n点框头看它；点 − 收起（只收这一列）';
        h.appendChild(tip);
        h.appendChild(self.cutBtn(F.btn.x, F.btn.y, '−', '收起 ' + nm + '：在 ' + ln.thread + ' 这一列里合回一个（别的列不变）',
                                  function () { CS.app.collapseFrame(f, ln.id); }));
        var pick = function (ev) { ev.stopPropagation(); self.pickFrame(f, ln.id); };
        h.onclick = pick;
        h.onkeydown = function (ev) { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target === h) { ev.preventDefault(); pick(ev); } };
        h.onmouseenter = function () { self.twins(f, true); };
        h.onmouseleave = function () { self.twins(f, false); };
        self.frames.push({ id: f, lane: ln.id, g: g, h: h });
      });
    },

    /* 框头占的地方：连线的标签、时间顺序的序号牌不压它 */
    headBoxes: function () {
      var fp = this.fpos || {};
      return Object.keys(fp).map(function (k) { var H = fp[k].head; return [H.x, H.y, H.x + H.w, H.y + H.h]; });
    },

    /* 节点角上的 ＋ / − 按钮（改切面） */
    cutBtn: function (x, y, sign, tip, go) {
      var b = el('g', { class: 'xp', role: 'button', tabindex: '0', 'aria-label': tip });
      b.appendChild(el('circle', { cx: x, cy: y, r: 7 }));
      var t = el('text', { x: x, y: y + 3.5, 'text-anchor': 'middle' });
      t.textContent = sign; b.appendChild(t);
      var tt = el('title', {}); tt.textContent = tip; b.appendChild(tt);
      var run = function (ev) { ev.preventDefault(); ev.stopPropagation(); go(); };
      b.onclick = run;
      b.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') run(ev); };
      return b;
    },

    /* 收起 / 展开一个进程（▾ / ▸）：数据不变，重画；选着的还画着就接着选它（详情按新图重画：里面能点的节点跟着变），
       收进去了就取消选中，免得详情里留着点了没反应、或者会选到别的线程里去的按钮 */
    fold: function (pid, on) {
      var was = this.sel, many = this.selMany, a = this._args;
      if (!a) return;
      this.collapsed[pid] = on;
      this.draw(a[0], a[1], a[2], a[3]);
      var E = was && this.byKey[was], nk = was && was.indexOf('n:') === 0 ? was.slice(2) : null;
      var fk = was && was.indexOf('f:') === 0 ? was.slice(2) : null;
      if (E) this.open(E, true);
      else if (nk && this.pos[nk]) {               // 节点的这一份还画着：只重写详情里分线程的那几行（文件树、打开的源码不动）
        this.select(was);
        CS.laneDetail.node(nk.slice(nk.lastIndexOf('|') + 1), nk.slice(0, nk.lastIndexOf('|')));
      } else if (fk && this.fpos[fk]) this.select(was);   // 框还画着
      else if (was && was.indexOf('m:') === 0 && many && many.every(function (k) { return this.byKey[k]; }, this)) this.select(was, many);
      else if (was) CS.graph.clear();
      if (CS.app.lanesChanged) CS.app.lanesChanged();
    },

    /* 屏幕上的一点附近的线（看得见的），按离它的距离从近到远 [{E, d（屏幕像素）}]（lanepick.js） */
    hitAt: function (cx, cy, r) { return CS.lanePick.hitAt(this, cx, cy, r); },

    /* 一条边 / 连线的交互：悬停加粗，点了选中、开详情（再点一次取消） */
    wire: function (E) {
      var self = this;
      E.click = function (ev) {
        ev.stopPropagation();
        if (self.sel === E.key) { CS.graph.clear(); return; }
        self.open(E);
      };
    },

    /* 选中一条边 / 连线、开详情（点了线，或者详情里点了它那一行） */
    open: function (E, quiet) {                       // quiet：改切面、收起进程之后接着选，不去打开用户关上的详情栏
      this.select(E.key);
      if (E.kind === 'edge') { if (CS.graph.onPickEdge) CS.graph.onPickEdge(E.e.a, E.e.b); }
      else CS.laneDetail.link(E.k);
      if (!quiet) CS.app.drawer(true);
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
      var w = this.L.window || [0, 0];
      var list = tm ? this.edges.concat(this.links.filter(function (E) { return E.k.kind === 'handoff'; }))
        .filter(function (E) { return E.show && E.first != null && E.first >= w[0] && E.first <= w[1]; }) : [];
      list.sort(function (p, q) { return p.first - q.first || (p.last || 0) - (q.last || 0) || (p.key < q.key ? -1 : 1); });
      var n = list.length, span = Math.max(1, w[1] - w[0]);
      this.edges.concat(this.links).forEach(function (E) { E._t = null; });
      list.forEach(function (E, i) {
        E._t = { k: i, n: n, repeat: E.n >= REPEAT && (E.last - E.first) > span / 2 };
      });
      function sec(us) { return when(us, w[0]); }
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
      this.timed = n;                                // 开关上的数（app.edgeChips 在分列下读它）
      CS.graph.times = tm ? { window: w, truncated: this.L.truncated || [] } : null;
      this.applySel();
    },

    /* 序号牌：上了色的边 / 连线上画一个同色的小牌子，先试中点、被节点或别的牌子挡住就沿路径挪 */
    badges: function (list) {
      var tg = this.tg, boxes = this.headBoxes(), self = this;
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
      var s0 = this.sel, many = this.selMany, nk = s0 && s0.indexOf('n:') === 0 ? s0.slice(2) : null;   // "列|节点"
      var fk = s0 && s0.indexOf('f:') === 0 ? s0.slice(2) : null, s = fk ? null : s0;   // 选中的是框：只描它，别的不淡
      this.frames.forEach(function (x) { x.g.classList.toggle('sel', x.lane + '|' + x.id === fk); });
      var id = nk && nk.slice(nk.lastIndexOf('|') + 1), lane = nk && nk.slice(0, nk.lastIndexOf('|'));
      var keep = null, hi = {}, touch = {};          // 照常的节点（"列|节点"）、高亮的边 / 连线、碰到选中的这一份的
      if (nk) { var T = this.touching(lane, id); T.out.concat(T.inn, T.links).forEach(function (E) { touch[E.key] = 1; }); }
      function ends(E) {
        return E.kind === 'edge' ? [E.lane.id + '|' + E.e.a, E.lane.id + '|' + E.e.b]
          : [E.k.from.lane + '|' + E.k.from.node, E.k.to.lane + '|' + E.k.to.node];
      }
      if (s) {
        keep = {};
        this.edges.concat(this.links).forEach(function (E) {
          var on = nk ? !!touch[E.key] : s === E.key || (!!many && many.indexOf(E.key) >= 0);
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

    /* 碰到一个节点的这一份（lane 这一列里的 id）的：out 这一列里它调出去的边、inn 调进来的边、links 一头是它的连线。
       选中节点时高亮的和详情里列的都是这些 */
    touching: function (lane, id) {
      var r = { out: [], inn: [], links: [] };
      this.edges.forEach(function (E) {
        if (E.lane.id !== lane) return;
        if (E.e.a === id) r.out.push(E);
        if (E.e.b === id) r.inn.push(E);
      });
      this.links.forEach(function (E) {
        var k = E.k;
        if ((k.from.lane === lane && k.from.node === id) || (k.to.lane === lane && k.to.node === id)) r.links.push(E);
      });
      return r;
    },

    /* 选中的东西在哪一列：节点的那一份、列里的边；选中的是连线或者什么都没选时 null */
    selLane: function () {
      var s = this.sel || '';
      if (s.indexOf('e:') === 0) return this.byKey[s] ? this.byKey[s].lane.id : null;
      if (s.indexOf('n:') === 0 || s.indexOf('f:') === 0) return s.slice(2, s.lastIndexOf('|'));
      return null;
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
          + (z[6] && fn ? '\n经仓库外的代码，在这个函数里面' : '') + (fn ? '\n点了在代码窗口里看这一行' : '');
        g.appendChild(tt);
        if (fn && z[4]) {
          var go = function (ev) { ev.stopPropagation(); CS.viewer.open(z[4].f, z[2] || z[4].l); };
          g.onclick = go;
          g.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(ev); } };
        }
        ct.appendChild(g);
      });
    },

    /* 选中节点的一份（lane：哪一列；不给或者这一列没画它就取它出现的第一列）。详情讲这个节点，
       调用 / 被调用 / 连线只列这一份的（lanedetail.node，用户 10-01） */
    pickNode: function (id, lane, quiet) {
      if (lane && !this.pos[lane + '|' + id]) lane = '';   // 这一列没画它：选它画着的第一份
      if (!lane) { var x = this.nodes.filter(function (y) { return y.id === id; })[0]; lane = x ? x.lane : ''; }
      if (!lane) {                                   // 哪一列都没画它（只在收起的进程里）
        CS.graph.clear();
        CS.viewer.toast(this.foldedHome(id) != null ? '它只在收起的进程里，展开那个进程才看得到' : '这一段里哪条线程都没画它');
        return;
      }
      var key = 'n:' + lane + '|' + id;
      if (this.sel === key) { CS.graph.clear(); return; }
      this.select(key);
      this.twins(id, false);
      if (CS.graph.onPick) CS.graph.onPick(id);
      CS.laneDetail.node(id, lane);
      if (!quiet) CS.app.drawer(true);
    },

    /* id（目录 / 单个文件，kind 同 app.homeOf）只在收起的进程里有：那个进程的 pid；没有是 null */
    foldedHome: function (id, kind) {
      var self = this, hit = null;
      ((this.L || {}).lanes || []).forEach(function (ln) {
        if (hit != null || !self.collapsed[ln.pid]) return;
        var g = { nodes: Object.keys(ln.nodes).map(function (x) { return { id: x }; }) };
        if (CS.app.homeOf(id, kind, g)) hit = ln.pid;
      });
      return hit;
    },

    /* 同一个节点在别的列里的副本：鼠标停着的时候高亮并连上（选中只高亮点的那一份，不连副本） */
    /* 每一列里的「它」（节点或展开着的框 id）：同一个节点；那一列里它展开着就是那个框；它收在别的节点里就是装着它的那个节点
       （用户 10-02：一列展开了、别的列还收着，悬停子节点也连到装着它的那个目录）。[{el, l, r, y}]，按左右排好 */
    copies: function (id) {
      var self = this, kind = ((this.L.info || {})[id] || {}).kind, out = [];
      Object.keys(this.laneIx || {}).forEach(function (lane) {
        var x = self.nodes.filter(function (n) { return n.lane === lane && n.id === id; })[0];
        var f = !x && self.frames.filter(function (n) { return n.lane === lane && n.id === id; })[0];
        if (!x && !f) {
          var h = CS.app.homeOf(id, kind, self.asGraph(lane));
          x = h && self.nodes.filter(function (n) { return n.lane === lane && n.id === h; })[0];
        }
        if (x) {
          var p = self.pos[lane + '|' + x.id];
          out.push({ el: x.g, l: p.cx - p.w / 2, r: p.cx + p.w / 2, y: p.cy - p.h / 2 + 3 });   // 贴着顶边：侧面出来的边在中间
        } else if (f) {
          var F = self.fpos[lane + '|' + id];
          out.push({ el: f.g, l: F.x, r: F.x + F.w, y: F.head.y + F.head.h / 2 });
        }
      });
      return out.sort(function (a, b) { return a.l - b.l; });
    },

    /* 鼠标停在一份上：各列里的它高亮、用虚线连上（选中只高亮点的那一份，不连） */
    twins: function (id, on) {
      if (!this.svg) return;
      var self = this;
      this.tw.textContent = '';
      this.nodes.concat(this.frames).forEach(function (x) { x.g.classList.remove('twin'); });
      if (!on || !id) return;
      var cs = this.copies(id);
      cs.forEach(function (c) { c.el.classList.add('twin'); });
      for (var i = 1; i < cs.length; i++)
        self.tw.appendChild(el('line', { x1: cs[i - 1].r, y1: cs[i - 1].y, x2: cs[i].l, y2: cs[i].y, class: 'ln-twin' }));
    }
  };
})(window.CS);
