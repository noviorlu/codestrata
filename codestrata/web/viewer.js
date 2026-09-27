/* 全文窗口：整个文件 + 左侧符号大纲。
 * 大纲随滚动高亮「当前所在的符号」，点大纲跳过去；从某个符号点进来时
 * 直接定位并高亮它的整段（到下一个同级或更外层的符号为止）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var LH = 19.2;            // 行高：12px × 1.6，和 CSS 保持一致
  var root, lastFocus, syms = [], codeEl, outlineEl;

  function depth(n) { return (n.match(/\./g) || []).length; }

  // 符号的结束行：下一个「同级或更外层」符号的前一行
  function rangeOf(list, idx, nLines) {
    var d = depth(list[idx].n);
    for (var j = idx + 1; j < list.length; j++) if (depth(list[j].n) <= d) return list[j].l - 1;
    return nLines;
  }

  CS.viewer = {
    open: function (rel, line) {
      root = root || document.getElementById('viewer');
      lastFocus = document.activeElement;
      root.hidden = false;
      document.body.style.overflow = 'hidden';
      root.innerHTML = '<div class="vbox"><div class="vhead"><b>' + esc(rel) + '</b>'
        + '<span class="vmeta">读取中…</span></div></div>';
      var self = this;
      CS.ds.file(rel).then(function (fv) {
        if (!fv) {
          root.innerHTML = '<div class="vbox"><div class="vhead"><b>' + esc(rel) + '</b>'
            + '<span class="sp"></span><button class="vclose" aria-label="关闭">×</button></div>'
            + '<p class="hint" style="padding:18px">这个文件没有内嵌进导出版（体积上限）。'
            + '用 <code>codestrata serve</code> 本地打开就能看全文。</p></div>';
          self._wireClose(); return;
        }
        self._render(fv, line);
      }).catch(function (e) {
        root.innerHTML = '<div class="vbox"><p class="hint" style="padding:18px">读取失败：' + esc(e.message) + '</p></div>';
      });
    },

    _render: function (fv, line) {
      syms = fv.symbols || [];
      var hl = fv.lines || [], rows = [];   // 服务端（Pygments）已按行高亮好
      for (var i = 0; i < hl.length; i++)
        rows.push('<div class="ln" id="vL' + (i + 1) + '"><span class="no">' + (i + 1)
          + '</span><span class="tx">' + (hl[i] || ' ') + '</span></div>');
      var hot = CS.graph && CS.graph.hot;
      var outline = syms.map(function (s, k) {
        var h = (hot && hot.symbols && hot.symbols[s.key]) || 0;
        var tag = s.k === 'class' ? 'C' : (s.k === 'kernel' ? 'K' : 'f');
        return '<button class="osym d' + Math.min(depth(s.n), 3) + '" data-k="' + k + '">'
          + '<span class="ok' + (s.k === 'class' ? ' c' : (s.k === 'kernel' ? ' kn' : '')) + '">' + tag + '</span>'
          + '<span class="on">' + esc(s.n.split('.').pop()) + '</span>'
          + (h ? '<span class="oh">' + h + '</span>' : '')
          + '<span class="ol">' + s.l + '</span></button>';
      }).join('');
      root.innerHTML = '<div class="vbox">'
        + '<div class="vhead"><b>' + esc(fv.file) + '</b>'
        + '<span class="langtag lang-' + esc(fv.lang) + '">' + esc(fv.lang_label) + '</span>'
        + '<span class="vmeta">' + fv.n_lines + ' 行　' + syms.length + ' 个符号'
        + (fv.outline_kind === 'lexer' ? '（大纲为启发式）' : '') + '　包 ' + esc(fv.pkg) + '</span>'
        + '<span class="sp"></span>'
        + '<button class="vbtn" data-copy="' + esc(fv.file) + '">复制路径</button>'
        + (CS.ds.canOpenEditor ? '<button class="vbtn" data-edit="1">编辑器打开</button>' : '')
        + '<button class="vclose" aria-label="关闭">×</button></div>'
        + '<div class="vbody"><nav class="voutline" aria-label="符号大纲">'
        + (outline || '<p class="hint" style="padding:10px">这个文件里没有类或函数。</p>')
        + '</nav><div class="vcode" tabindex="0">' + rows.join('') + '</div></div></div>';
      codeEl = root.querySelector('.vcode'); outlineEl = root.querySelector('.voutline');
      var self = this, cur = line || 1;
      [].forEach.call(root.querySelectorAll('.osym'), function (b) {
        b.onclick = function () { var k = +b.dataset.k; self.focus(syms[k].l, rangeOf(syms, k, fv.n_lines)); };
      });
      var cp = root.querySelector('[data-copy]');
      if (cp) cp.onclick = function () {
        var t = fv.file + ':' + cur;
        if (navigator.clipboard) navigator.clipboard.writeText(t).then(function () {
          cp.textContent = '已复制'; setTimeout(function () { cp.textContent = '复制路径'; }, 1200); }, function () {});
      };
      var ed = root.querySelector('[data-edit]');
      if (ed) ed.onclick = function () { CS.ds.openEditor(fv.file, cur); };
      codeEl.onclick = function (ev) {                 // 点某行 → 记下来，复制/跳编辑器都用它
        var ln = ev.target.closest && ev.target.closest('.ln'); if (!ln) return;
        cur = +ln.id.slice(2);
        [].forEach.call(codeEl.querySelectorAll('.ln.pick'), function (x) { x.classList.remove('pick'); });
        ln.classList.add('pick');
      };
      codeEl.onscroll = function () { self._syncOutline(); };
      this._wireClose();
      if (line) {
        var k = -1; for (var i2 = 0; i2 < syms.length; i2++) if (syms[i2].l === line) { k = i2; break; }
        this.focus(line, k >= 0 ? rangeOf(syms, k, fv.n_lines) : line);
      } else this._syncOutline();
      root.querySelector('.vclose').focus();
    },

    focus: function (a, b) {
      [].forEach.call(codeEl.querySelectorAll('.ln.focus'), function (x) { x.classList.remove('focus'); });
      for (var i = a; i <= Math.min(b, a + 400); i++) {
        var el = document.getElementById('vL' + i); if (el) el.classList.add('focus');
      }
      codeEl.scrollTop = Math.max(0, (a - 4) * LH);
      this._syncOutline();
    },

    _syncOutline: function () {
      if (!outlineEl || !syms.length) return;
      var top = Math.floor(codeEl.scrollTop / LH) + 3, k = -1;
      for (var i = 0; i < syms.length; i++) { if (syms[i].l <= top) k = i; else break; }
      [].forEach.call(outlineEl.querySelectorAll('.osym.act'), function (x) { x.classList.remove('act'); });
      if (k >= 0) {
        var b = outlineEl.querySelector('[data-k="' + k + '"]');
        if (b) { b.classList.add('act');
          var r = b.offsetTop - outlineEl.scrollTop;
          if (r < 0 || r > outlineEl.clientHeight - 30) outlineEl.scrollTop = b.offsetTop - 60; }
      }
    },

    _wireClose: function () {
      var self = this, x = root.querySelector('.vclose');
      if (x) x.onclick = function () { self.close(); };
      root.onclick = function (ev) { if (ev.target === root) self.close(); };
      document.onkeydown = function (ev) { if (ev.key === 'Escape' && !root.hidden) self.close(); };
    },

    close: function () {
      if (!root) return;
      root.hidden = true; root.innerHTML = '';
      document.body.style.overflow = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
  };
})(window.CS);
