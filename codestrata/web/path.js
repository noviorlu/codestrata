/* 请求路径：叠着的 run 在选的阶段里，每个进程、每个线程按第一次调用的先后排出来的函数级调用树（/api/path，见 path.py）。
   放在下面的详情栏里：一个线程一节（各进程的主线程展开），一行一个函数，缩进是调用的层次；
   点函数名开它的定义，点「← 文件:行」开调用写在哪一行，点 ▾ 收起它下面那几层。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function short(k) { return k ? k.slice(k.indexOf('#') + 1) : ''; }
  function fname(f) { return f.split('/').pop(); }

  function rowHtml(r, next, t0) {
    var ln = r.line, kids = next && next.d > r.d;
    var why = ln && ln.status === 'trace'
      ? '<span class="dtag" title="' + esc((CS.panel.noteText(ln.note) || '代码里看不出会调到它')
          + (ln.guessed ? '（这个 run 没记调用行，调用处是按名字猜的）' : '')) + '">代码里看不出</span>' : '';
    return '<div class="prow" data-d="' + r.d + '" style="--d:' + r.d + '">'
      + (kids ? '<button class="pt" aria-expanded="true" title="收起 / 展开它下面的调用">▾</button>' : '<span class="pt"></span>')
      + '<span class="ptime">+' + ((r.t - t0) / 1e6).toFixed(3) + 's</span>'
      + '<button class="pfn" data-f="' + esc(r.def.f) + '" data-l="' + r.def.l + '" title="' + esc(r.fn) + '（点了看定义）">'
      + esc(short(r.fn)) + '</button>'
      + (r.n ? '<span class="pn">×' + r.n + '</span>' : '')
      + (r.rep ? '<span class="prep" title="反复调用：轮询、每个 token 都走一遍">↻</span>' : '')
      + (r.untimed ? '<span class="pun" title="同一个文件里调过来的：时序事件只记跨文件的调用，这一跳没有时刻，排的位置按它自己第一次往外调的时刻">同文件</span>' : '')
      + why
      + (ln && ln.l ? '<button class="pfrom" data-f="' + esc(ln.f) + '" data-l="' + ln.l + '" title="调用写在 '
          + esc(short(r.from)) + ' 的这一行（点了看）">← ' + esc(fname(ln.f)) + ':' + ln.l + '</button>' : '')
      + '</div>';
  }

  CS.path = {
    /* 打开请求路径（叠着 run 时的「请求路径」按钮） */
    show: function () {
      var tok = CS.panel.claim('<p class="hint">读取中…</p>'), self = this;
      var m = CS.app.data && CS.app.data.hotMeta;
      document.getElementById('dtitle').textContent = '请求路径' + (m && m.phase ? ' · ' + CS.timebar.label(m.phase) : '');
      document.getElementById('dsub').textContent = '每个进程、每个线程按第一次调用的先后排的函数级调用';
      CS.app.drawer(true);
      if (!CS.app.runHasEvents()) {
        document.getElementById('det').innerHTML = '<p class="hint">这个 run 没录时序事件，看不了请求路径：录的时候用了 '
          + '<code>--no-events</code>，或者被录的 Python 低于 3.12。重新录一次就有（3.12+ 默认录）。</p>';
        return;
      }
      CS.ds.path().then(function (P) {
        if (CS.panel.mine(tok)) self.render(P);
      }).catch(function (e) {
        if (CS.panel.mine(tok)) document.getElementById('det').innerHTML = '<p class="hint">读取失败：' + esc(e.message) + '</p>';
      });
    },

    render: function (P) {
      var t0 = P.window[0], nrows = 0;
      var h = '<p class="hint">时刻从这一段（' + ((P.window[1] - t0) / 1e6).toFixed(2) + ' s）的开头算。只有跨文件的调用有时刻：'
        + '同一个文件里调过来的标「同文件」。↻ 是反复调用。点函数名看定义，点「← 文件:行」看调用写在哪；'
        + '没有调用方的是根（线程的入口、经仓库外的代码调进来的）。</p>';
      P.procs.forEach(function (p) {
        p.threads.forEach(function (th) {
          nrows += th.rows.length;
          h += '<details class="pth"' + (th.name === 'MainThread' ? ' open' : '') + '><summary><b>' + esc(p.name) + '</b>'
            + '<span class="lab">pid ' + p.pid + ' · ' + esc(th.name) + (th.n > 1 ? '（' + th.n + ' 个线程）' : '') + '</span>'
            + '<span class="n">' + th.rows.length + ' 个函数</span></summary><div class="prows">'
            + th.rows.map(function (r, i) { return rowHtml(r, th.rows[i + 1], t0); }).join('') + '</div></details>';
        });
      });
      if (!nrows) h += '<p class="hint">这一段里没有跨文件的调用。</p>';
      if (P.rows_cut) h += '<p class="hint">还有 ' + P.rows_cut + ' 行没列出（命令行 codestrata path 能看全）。</p>';
      if (P.truncated && P.truncated.length)
        h += '<p class="hint warn">进程 ' + P.truncated.join('、') + ' 的时序事件录到了上限，之后的调用不在这里。</p>';
      var det = document.getElementById('det');
      det.innerHTML = h;
      [].forEach.call(det.querySelectorAll('.pfn, .pfrom'), function (b) {
        b.onclick = function () { CS.viewer.open(b.dataset.f, +b.dataset.l); };
      });
      [].forEach.call(det.querySelectorAll('button.pt'), function (b) {
        b.onclick = function () { CS.path.toggle(b); };
      });
    },

    /* ▾ / ▸：收起 / 展开一行下面比它深的那几行 */
    toggle: function (b) {
      var row = b.parentNode, d = +row.dataset.d, open = b.getAttribute('aria-expanded') !== 'true';
      b.setAttribute('aria-expanded', open);
      b.textContent = open ? '▾' : '▸';
      for (var n = row.nextElementSibling; n && +n.dataset.d > d; n = n.nextElementSibling) {
        n.hidden = !open;
        var t = n.querySelector('button.pt');
        if (open && t) { t.setAttribute('aria-expanded', 'true'); t.textContent = '▾'; }
      }
    }
  };
})(window.CS);
