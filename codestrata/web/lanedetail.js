/* 按进程 · 线程分列的详情栏：点了列之间的连线（link），或者点了节点上起 / 收了好几列的「▶ 起 / ■ 收」（marks）。
 * 写清是哪种、经什么、几次、什么时候，两头各是哪一列的哪个节点，每一对函数两头的那一行代码（起线程、放 / 取、发 / 收、join 的那一行），
 * 点了在代码窗口里看那一行。图在 lanes.js（CS.lanes），写法和说法借它的 CS.lanes.fmt。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var F = CS.lanes.fmt, esc = F.esc, short = F.short, laneName = F.laneName, whenW = F.whenW, gpuT = F.gpuT;
  var VIA = F.VIA, KIND = F.KIND, ENDS = F.ENDS;

  /* 一头的节点名：这一列画着它就能点（选中这一列里的那一份）；进程收起了、或者这一段里这一列没画它，写明为什么点不了。
     node 是 null：那一头在仓库外的代码里 */
  function nodeChip(node, lane) {
    var lanes = CS.lanes;
    if (!node) return '<span class="chip off">仓库外的代码</span>';
    var nm = esc(CS.panel.short(node));
    if (lanes.pos[lane + '|' + node]) return '<button class="chip" data-node="' + esc(node) + '" data-lane="' + esc(lane) + '">' + nm + '</button>';
    var L0 = lanes.L.lanes.filter(function (x) { return x.id === lane; })[0];
    var why = L0 && lanes.collapsed[L0.pid] ? '这个进程收起了，展开后能点' : '这一段里这一列没画它';
    return '<span class="chip off" title="' + why + '">' + nm + '</span><span class="hint">（' + why + '）</span>';
  }

  CS.laneDetail = {
    /* 点了节点的一份：整个详情只讲这条线程里的这一份（用户 10-01：只列这条线程里这一份的）——顶上写明是哪一列，
       次数、文件树、kernel 表换成只算这一列的（panel.asCopy），「调用 → / ← 被调用」换成这一列里的边，
       代码里没写、这次跑了的单列，再列一头是它的连线。点名字选中这一列里的那个节点，点次数看那条边 / 连线 */
    node: function (id, lane) {
      var lanes = CS.lanes, det = document.getElementById('det'), slot = document.getElementById('nbslot');
      if (!slot || det.dataset.pkg !== id) return;
      det.dataset.lane = lane;                      // 详情里的展开 / 收起只改这一列（panel 的按钮读它）
      var T = lanes.touching(lane, id), L = lanes.L;
      var me = ((lanes.laneIx[lane] || {}).nodes || {})[id] || {};
      CS.panel.asCopy(id, lane, { label: lanes.laneLabel(lane), n: me.n || 0, gpu: !!(lanes.laneIx[lane] || {}).gpu });
      function byN(a, b) { return b.n - a.n; }
      function edges(list, label, out) {
        if (!list.length) return '';
        return '<div class="kv"><span>' + label + '</span>' + list.sort(byN).map(function (E) {
          var e = E.e, tag = e.n + ' 次' + (E.dashed ? ' · 代码里看不出' : e.only ? ' · 其中 ' + e.only + ' 次代码里看不出' : '');
          return '<span class="dep">' + nodeChip(out ? e.b : e.a, lane) + '<button class="eb2 warm" data-key="' + esc(E.key)
            + '" title="看这条边上具体是哪些函数在调用">' + tag + ' ⇢</button></span>';
        }).join('') + '</div>';
      }
      var out = T.out.filter(function (E) { return !E.dashed; }), inn = T.inn.filter(function (E) { return !E.dashed; });
      var dout = T.out.filter(function (E) { return E.dashed; }), dinn = T.inn.filter(function (E) { return E.dashed; });
      var h = edges(out, '调用 →', true) + edges(inn, '← 被调用', false)
        + edges(dout, '代码里没写、这次跑了 →', true) + edges(dinn, '← 代码里没写、这次跑了', false);
      if (T.links.length) h += '<div class="kv"><span>连线</span>' + T.links.sort(byN).map(function (E) {
        var k = E.k, from = k.from.lane === lane && k.from.node === id, o = from ? k.to : k.from;
        return '<span class="dep"><span class="hint">' + (from ? '→' : '←') + ' ' + esc(laneName(o.lane)) + '</span>' + nodeChip(o.node, o.lane)
          + '<button class="eb2 warm" data-key="' + esc(E.key) + '" title="看两头的代码">' + esc(KIND[k.kind] || k.kind) + ' · '
          + esc(VIA[k.via] || k.via) + ' ×' + k.n + (k.first != null ? ' ' + whenW(k.first, L, k.kind === 'join') : '') + ' ⇢</button></span>';
      }).join('') + '</div>';
      if (!T.out.length && !T.inn.length && !T.links.length) h += '<p class="hint">这条线程里它没调别的、也没被别的调，没有连线</p>';
      slot.innerHTML = h;
      [].forEach.call(slot.querySelectorAll('[data-node]'), function (b) {
        b.onclick = function () { lanes.pickNode(b.dataset.node, b.dataset.lane); };
      });
      [].forEach.call(slot.querySelectorAll('[data-key]'), function (b) {
        b.onclick = function () { var E = lanes.byKey[b.dataset.key]; if (E) lanes.open(E); };
      });
    },

    /* 选中了一列里的框（展开着的目录）、详情原来不在讲它：写它在哪一列里展开着、框着这条线程调到的哪几个，能在这一列里收起 */
    frame: function (f, lane) {
      var lanes = CS.lanes, ln = lanes.laneIx[lane] || {}, frs = ln.frames || {}, info = lanes.L.info || {};
      function inside(id) {
        for (var g = (info[id] || {}).frame, k = 0; g && k < 64; g = (frs[g] || {}).parent, k++) if (g === f) return true;
        return false;
      }
      var ids = Object.keys(ln.nodes || {}).filter(inside).sort();
      var h = '<p class="hint">在 <b>' + esc(laneName(lane)) + '</b> 这一列里展开着（只这一列；别的列里它可能还收着），'
        + '框着这条线程调到的 ' + ids.length + ' 个子模块：</p>'
        + '<div class="kv"><span>框里</span>' + ids.map(function (id) { return nodeChip(id, lane); }).join(' ') + '</div>'
        + '<div class="cutrow"><span class="kindtag">已在这一列里展开成框</span><button class="chip" data-fold="1" title="框里的子模块合回一个节点（别的列不变）">'
        + '收起</button></div>';
      CS.panel.claim(h);
      var det = document.getElementById('det'), t = document.getElementById('dtitle'), s = document.getElementById('dsub');
      det.dataset.lane = lane;
      if (t) { t.textContent = CS.panel.full(f); t.title = f; }
      if (s) s.textContent = '已在 ' + laneName(lane) + ' 这一列里展开成框（框头的 − 收起）';
      [].forEach.call(det.querySelectorAll('[data-node]'), function (b) {
        b.onclick = function () { lanes.pickNode(b.dataset.node, b.dataset.lane); };
      });
      det.querySelector('[data-fold]').onclick = function () { CS.app.collapseFrame(f, lane); };
    },

    /* 点了节点上的「▶ 起 / ■ 收」、这里起了 / 收了好几列：这几条连线都高亮，详情里逐条列出起 / 收的那一行代码，
       点名字选中那一条 */
    marks: function (m, Es) {
      var lanes = CS.lanes, L = lanes.L, start = m.kind === 'start', nm = CS.panel.short(m.node);
      var key = 'm:' + m.kind + ':' + m.lane + '|' + m.node;
      if (lanes.sel === key) { CS.graph.clear(); return; }
      lanes.select(key, Es.map(function (E) { return E.key; }));
      var h = '<p class="hint">' + esc(nm) + '（' + esc(laneName(m.lane)) + ' 里）' + (start ? '起' : '收') + '了 '
        + Es.length + ' 列' + (start ? '' : '：join / waitpid 等到它们结束') + '。点名字看那一条连线</p><div class="lk-pairs">'
        + Es.map(function (E) {
          var k = E.k, pr = (k.pairs || [])[0] || {}, other = start ? k.to : k.from;
          var fn = start ? pr.a : pr.b, ln = start ? pr.la : pr.lb, tx = start ? pr.ta : pr.tb, def = start ? pr.da : pr.db;
          return '<div class="lk-pair"><div class="lk-meta"><button class="chip" data-key="' + esc(E.key) + '">' + esc(laneName(other.lane))
            + '</button><span class="pn">×' + k.n + '</span><span class="ptime">' + whenW(k.first, L, !start) + '</span><span class="hint">'
            + esc(VIA[k.via] || k.via) + '</span></div>'
            + '<div class="lk-site"><span class="lk-lab2">' + (start ? '起' : '收') + '</span>'
            + (fn ? '<button class="lk-fn" data-f="' + esc(def && def.f) + '" data-l="' + (ln || (def ? def.l : 1)) + '">' + esc(short(fn))
                    + (ln ? ':' + ln : '') + '</button>'
                    + (tx ? '<code class="lk-code" data-f="' + esc(def && def.f) + '" data-l="' + ln + '">' + esc(tx) + '</code>' : '')
                  : '<span class="hint">仓库外的代码</span>') + '</div></div>';
        }).join('') + '</div>';
      CS.panel.claim(h);
      var t = document.getElementById('dtitle'), s = document.getElementById('dsub');
      if (t) { t.textContent = (start ? '这里起的线程 / 进程' : '这里回收的线程 / 进程'); t.title = ''; }
      if (s) s.textContent = nm + ' · ' + laneName(m.lane) + '，' + Es.length + ' 列';
      var det = document.getElementById('det');
      [].forEach.call(det.querySelectorAll('.lk-fn, .lk-code'), function (b) {
        b.onclick = function () { if (b.dataset.f) CS.viewer.open(b.dataset.f, +b.dataset.l); };
      });
      [].forEach.call(det.querySelectorAll('[data-key]'), function (b) {
        b.onclick = function () {
          var E = Es.filter(function (x) { return x.key === b.dataset.key; })[0];
          if (E) { lanes.select(E.key); CS.laneDetail.link(E.k); }
        };
      });
      CS.app.drawer(true);
    },

    /* 点了列之间的连线：详情里写清楚是哪种、经什么、几次、什么时候，两头各是哪一列的哪个节点；
       每一对函数列出两头的那一行代码（起线程、放 / 取、发 / 收、join 的那一行），点了在代码窗口里看那一行 */
    link: function (k) {
      var lanes = CS.lanes, L = lanes.L, late = k.kind === 'join', ends = ENDS[k.kind] || ['从', '到'];
      function laneOf(id) { return L.lanes.filter(function (x) { return x.id === id; })[0] || { proc: '', thread: laneName(id) }; }
      function side(e, label) {
        var ln = laneOf(e.lane);
        return '<div class="lk-end"><span class="lk-lab">' + label + '</span><b>' + esc(ln.proc) + '</b> · ' + esc(ln.thread)
          + (ln.n_threads > 1 ? ' ×' + ln.n_threads : '') + (ln.external ? '（只跑仓库外的代码）' : ln.idle ? '（这一段里没有调用）' : '')
          + (e.node ? '　' + nodeChip(e.node, e.lane) : '') + '</div>';
      }
      /* 一头的那一行代码。没有行的：交接是不知道是哪一行；起 / 收的那一头是线程的入口函数；
         启动 kernel 的发起那一头是发起它时栈上最近的仓库函数（经 PyTorch / 扩展转了几道，不知道是哪一行），另一头是 kernel */
      function bare(end) {
        return k.kind === 'handoff' ? '不知道是哪一行' : k.kind !== 'launch' ? '线程的入口函数'
          : end === 'a' ? '发起它时栈上最近的仓库函数，不知道是哪一行' : 'GPU 上跑的 kernel';
      }
      function site(label, name, def, line, code, ext, end) {
        var h = '<div class="lk-site"><span class="lk-lab2">' + esc(label) + '</span>';
        if (!name) return h + '<span class="hint">仓库外的代码</span></div>';
        var at = line || (def ? def.l : 1);
        return h + '<button class="lk-fn" data-f="' + esc(def && def.f) + '" data-l="' + at + '" title="' + esc(name)
          + (line ? ' 第 ' + line + ' 行' : '') + '（点了在代码窗口里看）">' + esc(short(name)) + (line ? ':' + line : '') + '</button>'
          + (code ? '<code class="lk-code" data-f="' + esc(def && def.f) + '" data-l="' + at + '" title="点了在代码窗口里看这一行">'
                    + esc(code) + '</code>'
             : line ? '' : '<span class="hint">（' + bare(end) + '）</span>')
          + (ext ? '<span class="hint">（经仓库外的代码，在它里面）</span>' : '') + '</div>';
      }
      var kind = KIND[k.kind] || k.kind;
      var h = '<p class="hint">' + kind + '：' + esc(VIA[k.via] || k.via) + '，<b>' + k.n + '</b> 次'
        + (k.gpu_us != null ? '，GPU 上共 <b>' + gpuT(k.gpu_us) + '</b>' : '')
        + (k.first != null ? '；第一次 ' + whenW(k.first, L, late) + (k.last != null && k.last !== k.first ? '，最后 ' + whenW(k.last, L, late) : '') : '')
        + '（从这一段的开头算）' + (k.out ? '；<b>整条发生在这一段' + (k.out === 'before' ? '开始之前' : '结束之后') + '</b>（这一段里跑过的线程）' : '') + '</p>'
        + side(k.from, '从') + side(k.to, '到')
        + '<h3>两头的代码</h3><div class="lk-pairs">' + (k.pairs || []).map(function (p) {
          return '<div class="lk-pair"><div class="lk-meta"><span class="pn">×' + p.n + '</span>'
            + (p.gpu_us != null ? '<span class="pn">GPU ' + gpuT(p.gpu_us) + '</span>' : '')
            + (p.first != null ? '<span class="ptime">' + whenW(p.first, L, late) + '</span>' : '') + '</div>'
            + site(ends[0], p.a, p.da, p.la, p.ta, p.xa, 'a') + '<div class="arr">↓</div>' + site(ends[1], p.b, p.db, p.lb, p.tb, p.xb, 'b') + '</div>';
        }).join('') + '</div>'
        + (k.n_pairs > (k.pairs || []).length ? '<p class="hint">还有 ' + (k.n_pairs - k.pairs.length) + ' 对（次数更少）</p>' : '')
        + (k.kind === 'handoff' ? '<p class="hint">配对：进程内的队列按「同一个队列里的同一个对象」，ZMQ 按消息内容的指纹；'
           + '代码是放 / 取、发 / 收那一刻最里层的仓库函数里正执行的那一行（经仓库外的代码转了一道的，是调进去的那一行）；'
           + '发生在仓库外的代码里时写那一刻这条线程最底下在跑的仓库函数，那一刻没有在跑的仓库函数就是仓库外的代码。</p>'
           : k.kind === 'join' ? '<p class="hint">线程从入口函数返回就结束了；收的那一行是 join（线程池的 shutdown 也是逐个 join）或 '
           + 'waitpid（Popen.wait、Process.join）等到它的那一行。</p>' : '');
      CS.panel.claim(h);
      var t = document.getElementById('dtitle'), s = document.getElementById('dsub');
      if (t) { t.textContent = kind + ' · ' + (VIA[k.via] || k.via); t.title = ''; }
      if (s) s.textContent = laneName(k.from.lane) + ' → ' + laneName(k.to.lane) + '，' + k.n + ' 次';
      var det = document.getElementById('det');
      [].forEach.call(det.querySelectorAll('.lk-fn, .lk-code'), function (b) {
        b.onclick = function () { if (b.dataset.f) CS.viewer.open(b.dataset.f, +b.dataset.l); };
      });
      [].forEach.call(det.querySelectorAll('[data-node]'), function (b) {
        b.onclick = function () { lanes.pickNode(b.dataset.node, b.dataset.lane); };
      });
    }
  };
})(window.CS);
