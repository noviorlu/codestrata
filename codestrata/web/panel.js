/* 详情面板（左：机器事实 + 源码）与解读面板（右：空槽 / 已写 / 过期）。
 * 「留给 llm agent 的空间」就是右边那块：没写时显示 task 输入包，
 * agent 从 PUT /api/notes 写回后这里立刻变成渲染好的解读。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var det, side, D;

  CS.panel = {
    init: function (detEl, sideEl, data) { det = detEl; side = sideEl; D = data; this.reset(); },

    reset: function () {
      det.innerHTML = '<p class="hint"><b>怎么读：</b>每条泳道是一段架构高度区间，'
        + '越上面越靠入口、越下面越是被依赖的叶子；节点大小编码文件数。'
        + '点节点看它依赖谁、里面有什么符号，右边是这个模块的<b>解读</b>。</p>';
      side.innerHTML = '<h3>解读层</h3><p class="hint">机器只能给出结构；'
        + '「为什么这样切、算法为什么这么写、该按什么顺序读」需要人或 agent 补。'
        + '点一个节点看它的解读状态。</p>';
    },

    /* ---- 左：机器事实 ---- */
    showPkg: function (id, symKey) {
      var v = (D.pkgs || {})[id] || {}, x = CS.graph.nb(id);
      var list = (D.pkgSyms || {})[id] || [];
      var hot = CS.graph.hot, hits = (hot && hot.packages[id]) || 0;
      function pills(a, l) {
        if (!a.length) return '';
        return '<div class="kv"><span>' + l + '</span>' + a.map(function (i) {
          return '<button class="chip" data-go="' + esc(i) + '">' + esc(i.split('.').pop()) + '</button>';
        }).join('') + '</div>';
      }
      det.innerHTML = '<h2>' + esc(id) + '</h2>'
        + '<div class="sub">架构高度 ' + (v.alt >= 0 ? '+' : '') + (v.alt || 0).toFixed(2)
        + '　出 ' + (v.out || 0) + ' / 入 ' + (v.in || 0)
        + (hot ? ('　runtime ' + (hits ? hits + ' 次' : '未跑到')) : '') + '</div>'
        + '<div class="kv"><span>文件 <b>' + (v.files || 0) + '</b></span>'
        + '<span>行 <b>' + (v.loc || 0) + '</b></span>'
        + '<span>类 <b>' + (v.classes || 0) + '</b></span>'
        + '<span>函数 <b>' + (v.funcs || 0) + '</b></span></div>'
        + pills(x.o, '依赖 →') + pills(x.i, '← 被依赖')
        + (list.length ? ('<div class="slist">' + list.slice(0, 40).map(function (s) {
            var h = (hot && hot.symbols[s.key]) || 0;
            return '<div class="si" data-sym="' + esc(s.key) + '" data-pkg="' + esc(id) + '">'
              + '<span class="k' + (s.k === 'class' ? ' c' : '') + '">' + (s.k === 'class' ? 'C' : 'f') + '</span>'
              + '<span class="n" title="' + esc(s.n) + '">' + esc(s.n) + '</span>'
              + (h ? '<span class="h">' + h + '</span>' : '') + '</div>';
          }).join('') + '</div>') : '')
        + '<div id="srcslot"></div>';
      this._wireDet(id);
      if (symKey) this.showSource(id, symKey);
    },

    showSource: function (pkg, key) {
      var slot = document.getElementById('srcslot');
      if (!slot) return;
      slot.innerHTML = '<p class="hint" style="margin-top:10px">读取源码…</p>';
      var self = this;
      CS.ds.source(key).then(function (s) {
        if (!s) { slot.innerHTML = ''; return; }
        var g = [], n = (s.code || '').split('\n').length;
        for (var i = 0; i < n; i++) g.push(s.line + i);
        var hot = CS.graph.hot, h = (hot && hot.symbols[key]) || 0;
        slot.innerHTML = '<div class="srcbox"><div class="srchead">'
          + '<span class="p"><b>' + esc(s.name) + '</b>　' + esc(s.file + ':' + s.line)
          + (s.bases && s.bases.length ? '　继承 ' + esc(s.bases.join(', ')) : '')
          + (h ? '　<span style="color:var(--hot)">runtime ' + h + ' 次</span>' : '')
          + '</span>'
          + '<button data-copy="' + esc(s.file + ':' + s.line) + '">复制路径</button>'
          + (CS.ds.canOpenEditor ? '<button data-open="' + esc(s.file) + '" data-line="' + s.line + '">编辑器打开</button>' : '')
          + (CS.ds.mode === 'live' ? '<a href="/code/' + s.file + '?l=' + s.line + '" target="_blank">整个文件</a>' : '')
          + '</div><div class="srcscroll"><div class="srcgrid">'
          + '<div class="gut">' + g.join('\n') + '</div>'
          + '<pre class="code"><code>' + esc(s.code) + '</code></pre>'
          + '</div></div></div>';
        self._wireDet(pkg);
      }).catch(function () { slot.innerHTML = ''; });
    },

    _wireDet: function (pkg) {
      var self = this;
      [].forEach.call(det.querySelectorAll('[data-go]'), function (b) {
        b.onclick = function () { CS.graph.pick(b.dataset.go); };
      });
      [].forEach.call(det.querySelectorAll('[data-sym]'), function (b) {
        b.onclick = function () { self.showSource(b.dataset.pkg, b.dataset.sym); };
      });
      [].forEach.call(det.querySelectorAll('[data-copy]'), function (b) {
        b.onclick = function () {
          if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function () {
            b.textContent = '已复制'; setTimeout(function () { b.textContent = '复制路径'; }, 1200); }, function () {});
        };
      });
      [].forEach.call(det.querySelectorAll('[data-open]'), function (b) {
        b.onclick = function () { CS.ds.openEditor(b.dataset.open, b.dataset.line); };
      });
    },

    /* ---- 右：解读层 ---- */
    showNote: function (id) {
      side.innerHTML = '<h3>' + esc(id.split('.').pop()) + ' 的解读</h3>'
        + '<p class="hint">读取中…</p>';
      var self = this;
      CS.ds.note(id).then(function (nt) { self._renderNote(id, nt); })
                    .catch(function (e) { side.innerHTML = '<h3>解读</h3><p class="hint">读取失败：'
                      + esc(e.message) + '</p>'; });
    },

    _renderNote: function (id, nt) {
      var short = id.split('.').pop();
      var tag = nt.present ? (nt.stale ? '<span class="tagpill stale">可能过期</span>'
                                       : '<span class="tagpill noted">已解读</span>')
                           : '<span class="tagpill">未解读</span>';
      var head = '<h3>' + esc(short) + ' 的解读 ' + tag + '</h3>';

      if (!nt.present) {
        side.innerHTML = head
          + '<div class="empty-slot">'
          + '<p class="why">这里是留给人 / LLM agent 的空槽。</p>'
          + '<p>机器能给出结构，给不出「为什么这样切、算法为什么这么写、该按什么顺序读」。</p>'
          + '<div class="rowbtn"><button class="primary" id="genpack">生成输入包</button></div>'
          + '<div class="taskbox" id="taskbox"></div>'
          + '</div>';
        document.getElementById('genpack').onclick = function () { CS.panel._pack(id); };
        return;
      }
      side.innerHTML = head
        + (nt.stale ? '<div class="stalewarn">这份解读写于代码的另一个版本'
            + '（哈希 ' + esc((nt.code_sha_note || '').slice(0, 8)) + ' → 现在 '
            + esc((nt.code_sha_now || '').slice(0, 8)) + '）。内容可能已经不准。</div>' : '')
        + '<div class="note">' + (nt.html || '') + '</div>'
        + '<div class="rowbtn">'
        + (nt.stale && CS.ds.canWrite ? '<button class="primary" id="genpack">重写：生成输入包</button>' : '')
        + (nt.meta && nt.meta.written_by ? '<span class="tagpill">' + esc(nt.meta.written_by) + '</span>' : '')
        + (nt.path ? '<span class="tagpill">' + esc(nt.path) + '</span>' : '')
        + '</div><div class="taskbox" id="taskbox"></div>';
      var g = document.getElementById('genpack');
      if (g) g.onclick = function () { CS.panel._pack(id); };
    },

    _pack: function (id) {
      var box = document.getElementById('taskbox');
      box.innerHTML = '<p class="hint">生成中…</p>';
      CS.ds.pack(id).then(function (txt) {
        box.innerHTML = '<textarea id="packta" readonly></textarea>'
          + '<div class="rowbtn"><button id="copypack">复制给 agent</button>'
          + (CS.ds.canWrite ? '<button id="writenote">粘贴解读并保存</button>' : '') + '</div>';
        document.getElementById('packta').value = txt;
        document.getElementById('copypack').onclick = function () {
          var b = this;
          if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () {
            b.textContent = '已复制'; setTimeout(function () { b.textContent = '复制给 agent'; }, 1400); }, function () {});
        };
        var w = document.getElementById('writenote');
        if (w) w.onclick = function () {
          box.innerHTML = '<textarea id="noteta" placeholder="把 agent 产出的 Markdown 粘进来…"></textarea>'
            + '<div class="rowbtn"><button class="primary" id="savenote">保存</button></div>';
          document.getElementById('savenote').onclick = function () {
            var md = document.getElementById('noteta').value.trim();
            if (!md) return;
            this.textContent = '保存中…';
            CS.ds.saveNote(id, md).then(function (nt) {
              CS.panel._renderNote(id, nt);
              if (CS.app && CS.app.refreshStatus) CS.app.refreshStatus();
            }).catch(function (e) { alert('保存失败：' + e.message); });
          };
        };
      }).catch(function (e) { box.innerHTML = '<p class="hint">生成失败：' + esc(e.message) + '</p>'; });
    }
  };
})(window.CS);
