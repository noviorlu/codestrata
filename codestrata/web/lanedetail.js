/* 按进程 · 线程分列的详情栏：点了列之间的连线（link），或者点了节点上起 / 收了好几列的「▶ 起 / ■ 收」（marks）。
 * 写清是哪种、经什么、几次、什么时候，两头各是哪一列的哪个节点，每一对函数两头的那一行代码（起线程、放 / 取、发 / 收、join 的那一行），
 * 点了在代码窗口里看那一行。图在 lanes.js（CS.lanes），写法和说法借它的 CS.lanes.fmt。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var F = CS.lanes.fmt, esc = F.esc, short = F.short, laneName = F.laneName, when = F.when;
  var VIA = F.VIA, KIND = F.KIND, ENDS = F.ENDS;

  CS.laneDetail = {
    /* 点了节点上的「▶ 起 / ■ 收」、这里起了 / 收了好几列：这几条连线都高亮，详情里逐条列出起 / 收的那一行代码，
       点名字选中那一条 */
    marks: function (m, Es) {
      var lanes = CS.lanes, w0 = (lanes.L.window || [0])[0], start = m.kind === 'start', names = lanes.names || {};
      var key = 'm:' + m.kind + ':' + m.lane + '|' + m.node;
      if (lanes.sel === key) { CS.graph.clear(); return; }
      lanes.select(key, Es.map(function (E) { return E.key; }));
      var h = '<p class="hint">' + esc(names[m.node] || m.node) + '（' + esc(laneName(m.lane)) + ' 里）' + (start ? '起' : '收') + '了 '
        + Es.length + ' 列' + (start ? '' : '：join / waitpid 等到它们结束') + '。点名字看那一条连线</p><div class="lk-pairs">'
        + Es.map(function (E) {
          var k = E.k, pr = (k.pairs || [])[0] || {}, other = start ? k.to : k.from;
          var fn = start ? pr.a : pr.b, ln = start ? pr.la : pr.lb, tx = start ? pr.ta : pr.tb, def = start ? pr.da : pr.db;
          return '<div class="lk-pair"><div class="lk-meta"><button class="chip" data-key="' + esc(E.key) + '">' + esc(laneName(other.lane))
            + '</button><span class="pn">×' + k.n + '</span><span class="ptime">' + when(k.first, w0) + '</span><span class="hint">'
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
      if (s) s.textContent = (names[m.node] || m.node) + ' · ' + laneName(m.lane) + '，' + Es.length + ' 列';
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
      var lanes = CS.lanes, L = lanes.L, w0 = (L.window || [0])[0], names = lanes.names || {}, ends = ENDS[k.kind] || ['从', '到'];
      function laneOf(id) { return L.lanes.filter(function (x) { return x.id === id; })[0] || { proc: '', thread: laneName(id) }; }
      function side(e, label) {
        var ln = laneOf(e.lane);
        return '<div class="lk-end"><span class="lk-lab">' + label + '</span><b>' + esc(ln.proc) + '</b> · ' + esc(ln.thread)
          + (ln.n_threads > 1 ? ' ×' + ln.n_threads : '') + (ln.external ? '（只跑仓库外的代码）' : '')
          + (e.node ? '　<button class="chip" data-node="' + esc(e.node) + '" data-lane="' + esc(e.lane) + '">' + esc(names[e.node] || e.node) + '</button>' : '')
          + '</div>';
      }
      function site(label, name, def, line, code, ext) {
        var h = '<div class="lk-site"><span class="lk-lab2">' + esc(label) + '</span>';
        if (!name) return h + '<span class="hint">仓库外的代码</span></div>';
        var at = line || (def ? def.l : 1);
        return h + '<button class="lk-fn" data-f="' + esc(def && def.f) + '" data-l="' + at + '" title="' + esc(name)
          + (line ? ' 第 ' + line + ' 行' : '') + '（点了在代码窗口里看）">' + esc(short(name)) + (line ? ':' + line : '') + '</button>'
          + (code ? '<code class="lk-code" data-f="' + esc(def && def.f) + '" data-l="' + at + '" title="点了在代码窗口里看这一行">'
                    + esc(code) + '</code>'
             : line ? '' : '<span class="hint">（' + (k.kind === 'handoff' ? '不知道是哪一行' : '线程的入口函数') + '）</span>')
          + (ext ? '<span class="hint">（经仓库外的代码，在它里面）</span>' : '') + '</div>';
      }
      var kind = KIND[k.kind] || k.kind;
      var h = '<p class="hint">' + kind + '：' + esc(VIA[k.via] || k.via) + '，<b>' + k.n + '</b> 次'
        + (k.first != null ? '；第一次 ' + when(k.first, w0) + (k.last != null && k.last !== k.first ? '，最后 ' + when(k.last, w0) : '') : '')
        + '（从这一段的开头算）</p>'
        + side(k.from, '从') + side(k.to, '到')
        + '<h3>两头的代码</h3><div class="lk-pairs">' + (k.pairs || []).map(function (p) {
          return '<div class="lk-pair"><div class="lk-meta"><span class="pn">×' + p.n + '</span>'
            + (p.first != null ? '<span class="ptime">' + when(p.first, w0) + '</span>' : '') + '</div>'
            + site(ends[0], p.a, p.da, p.la, p.ta, p.xa) + '<div class="arr">↓</div>' + site(ends[1], p.b, p.db, p.lb, p.tb, p.xb) + '</div>';
        }).join('') + '</div>'
        + (k.n_pairs > (k.pairs || []).length ? '<p class="hint">还有 ' + (k.n_pairs - k.pairs.length) + ' 对（次数更少）</p>' : '')
        + (k.kind === 'handoff' ? '<p class="hint">配对：进程内的队列按「同一个队列里的同一个对象」，ZMQ 按消息内容的指纹；'
           + '代码是放 / 取、发 / 收那一刻最里层的仓库函数里正执行的那一行（经仓库外的代码转了一道的，是调进去的那一行）；'
           + '发生在仓库外的代码里时写这条线程入口的那个函数。</p>'
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
