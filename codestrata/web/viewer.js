/* 全文窗口：整个文件 + 左侧符号大纲。
 * 大纲随滚动高亮「当前所在的符号」，点大纲跳过去；从某个符号点进来时
 * 直接定位并高亮它的整段（到下一个同级或更外层的符号为止）。
 *
 * Ctrl（Mac 上是 ⌘）+ 点击一个名字跳到它的定义；点一个定义，列出所有引用它的地方。
 * 名字指向哪由 scan 时的交叉引用（xref.py）给出，这里只负责把能点的名字包上一层 span。
 * 跳转有「返回」栈，和编辑器里的「转到定义 / 返回」一样。
 * Ctrl+F（或头上的「查找」）在当前文件里查找，见 findbar.js。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var LH = 19.2;            // 行高：12px × 1.6，和 CSS 保持一致
  var root, lastFocus, syms = [], codeEl, outlineEl;
  var hist = [], curFile = null, curLine = 1, X = null, refsOpen = null;
  var KIND = { 0: '引用', 1: '调用', 2: 'import', 3: '定义' };

  /* 给一行代码（高亮好的 HTML）里能解析的名字包上 span.xr。Pygments 一个名字就是一个 span，
     所以名字总落在同一个文本节点里；从右往左包，前面的偏移量就不会因为拆分而变 */
  function markLine(el, toks) {
    if (!el) return;
    var nodes = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), n, pos = 0;
    while ((n = w.nextNode())) { nodes.push([n, pos]); pos += n.data.length; }
    toks.slice().sort(function (a, b) { return b[1] - a[1]; }).forEach(function (t) {
      for (var i = nodes.length - 1; i >= 0; i--) {
        var node = nodes[i][0], st = nodes[i][1];
        if (st <= t[1] && t[2] <= st + node.data.length) {
          var r = document.createRange(), sp = document.createElement('span');
          r.setStart(node, t[1] - st); r.setEnd(node, t[2] - st);
          sp.className = 'xr'; sp.dataset.x = t[3]; sp.dataset.k = t[4];
          try { r.surroundContents(sp); } catch (e) { /* 跨了高亮 span 的，不标 */ }
          return;
        }
      }
    });
  }
  function byLine(x, lo, hi) {
    var m = {};
    ((x && x.toks) || []).forEach(function (t) {
      if ((lo == null || t[0] >= lo) && (hi == null || t[0] <= hi)) (m[t[0]] = m[t[0]] || []).push(t);
    });
    return m;
  }
  function shortTarget(t) {                       // s:<路径>#<限定名> → 限定名；m:<路径>、x:点分路径 → 原样
    var r = t.slice(2), i = r.indexOf('#');
    return i < 0 ? r : r.slice(i + 1);
  }

  // Ctrl / ⌘ 按着的时候，能点的名字才显示成链接的样子
  function ctrlState(ev) { document.body.classList.toggle('xctrl', !!(ev.ctrlKey || ev.metaKey)); }
  document.addEventListener('keydown', ctrlState);
  document.addEventListener('keyup', ctrlState);
  document.addEventListener('mousemove', function (ev) {
    if (!!(ev.ctrlKey || ev.metaKey) !== document.body.classList.contains('xctrl')) ctrlState(ev);
  });
  window.addEventListener('blur', function () { document.body.classList.remove('xctrl'); });
  // 按着 Ctrl 悬停时，提示点下去会发生什么
  document.addEventListener('mouseover', function (ev) {
    var x = ev.target.closest && ev.target.closest('.xr');
    if (!x || x.title) return;
    var box = x.closest('[data-xfile]'), T = box && box._xref && box._xref.targets[x.dataset.x];
    if (!T) return;
    x.title = +x.dataset.k === 3 ? 'Ctrl+点击：列出所有引用它的地方'
      : !T[1] ? '定义不在仓库里：' + T[0].slice(2)
      : 'Ctrl+点击：跳到定义 ' + T[1][0] + ':' + T[1][1];
  });

  CS.xref = {
    /* 把一段代码（全文窗口，或详情面板里的片段）变成可 Ctrl+点击的。
       box 里每行是 [data-l] 的元素（全文窗口是 .ln 的 .tx），x 是 payload 给的 xref */
    mark: function (box, x, file, lineEl) {
      box._xref = x; box.dataset.xfile = file;
      if (!x || !x.toks || !x.toks.length) return;
      var m = byLine(x);
      Object.keys(m).forEach(function (l) { markLine(lineEl(+l), m[l]); });
    },
    /* 处理一次 Ctrl+点击；不是能点的名字就返回 false，让调用方照常处理 */
    click: function (ev) {
      if (!(ev.ctrlKey || ev.metaKey)) return false;
      var x = ev.target.closest && ev.target.closest('.xr');
      var box = x && x.closest('[data-xfile]');
      if (!x || !box || !box._xref) return false;
      ev.preventDefault(); ev.stopPropagation();
      var T = box._xref.targets[x.dataset.x];
      if (!T) return true;
      CS.viewer.here(x);                         // 「返回」要回到点的这一行，而不是上次定位的那一行
      // 定义和引用一起看：点一个名字跳到它的定义，旁边一栏列出定义（最上面）和所有引用；
      // 点定义本身就只打开这一栏。仓库外的名字没有定义可看，只提示
      if (!T[1]) CS.viewer.goto(T[0], T[1]);
      else CS.viewer.refs(T[0], T[1], x.textContent.split('.').pop(), +x.dataset.k !== 3);
      return true;
    }
  };

  function depth(n) { return (n.match(/\./g) || []).length; }

  // 符号的结束行：下一个「同级或更外层」符号的前一行
  function rangeOf(list, idx, nLines) {
    var d = depth(list[idx].n);
    for (var j = idx + 1; j < list.length; j++) if (depth(list[j].n) <= d) return list[j].l - 1;
    return nLines;
  }

  CS.viewer = {
    /* nav：是在窗口里跳转（转到定义 / 返回 / 点引用），不清掉返回栈。
       at：{top, col}——返回时恢复到跳走前的滚动位置；跳到某个引用时标出那一处 */
    open: function (rel, line, nav, at) {
      root = root || document.getElementById('viewer');
      if (root.hidden) lastFocus = document.activeElement;
      if (!nav) { hist = []; refsOpen = null; }
      root.hidden = false;
      document.body.style.overflow = 'hidden';
      root.innerHTML = '<div class="vbox"><div class="vhead"><b>' + esc(rel) + '</b>'
        + '<span class="vmeta">读取中…</span></div></div>';
      CS.findbar.attach(null, null);                     // 读取期间没有代码可找（查找栏开着的话，画好新文件再回来）
      var self = this, seq = this._seq = (this._seq || 0) + 1;
      CS.ds.file(rel).then(function (fv) {
        if (seq !== self._seq || root.hidden) return;     // 读取期间又开了别的文件，或者窗口已经关了
        self._render(fv, line, at);
      }).catch(function (e) {
        if (seq !== self._seq) return;
        root.innerHTML = '<div class="vbox"><p class="hint" style="padding:18px">读取失败：' + esc(e.message) + '</p></div>';
      });
    },

    _render: function (fv, line, at) {
      syms = fv.symbols || []; curFile = fv.file; curLine = line || 1; X = fv.xref || null;
      var hl = fv.lines || [], rows = [];   // 服务端（Pygments）已按行高亮好
      // 叠着 run 时：代码里看不出会调到谁、这次运行却调到了的那一行，行尾标出调到了谁，点了跳过去
      // 时间段的每行次数是按整个 run 的调用行比例摊的（seq.window_counts），标成约数
      var RT = fv.runtime || {}, nRT = 0, ap = CS.graph && CS.graph.hot && CS.graph.hot.lines_approx ? '≈' : '';
      var hm = CS.app && CS.app.data && CS.app.data.hotMeta;
      for (var i = 0; i < hl.length; i++) {
        var rt = RT[i + 1];
        if (rt) nRT++;
        rows.push('<div class="ln" id="vL' + (i + 1) + '"><span class="no">' + (i + 1)
          + '</span><span class="tx' + (hl[i] ? '' : ' e') + '">' + (hl[i] || ' ') + '</span>'   // 空行 .e：查找时当空行
          + (rt ? '<span class="rtj">' + rt.slice(0, 3).map(function (r) {
                var q = r.callee.slice(r.callee.indexOf('#') + 1);
                return '<button data-rf="' + esc(r.def.f) + '" data-rl="' + r.def.l + '" title="这一行代码里看不出会调到谁；这次运行调到了 '
                  + esc(r.callee) + '，' + ap + r.n + ' 次。点击跳过去">→ ' + esc(q) + ' ×' + ap + r.n + '</button>';
              }).join('') + (rt.length > 3 ? '<span>还有 ' + (rt.length - 3) + ' 个</span>' : '') + '</span>' : '')
          + '</div>');
      }
      var hot = CS.graph && CS.graph.hot;
      var outline = syms.map(function (s, k) {
        var h = (hot && hot.symbols && hot.symbols[s.key]) || 0;
        var tag = s.k === 'class' ? 'C' : (s.k === 'kernel' ? 'K' : 'f');
        return '<button class="osym d' + Math.min(depth(s.n), 3) + '" data-k="' + k + '">'
          + '<span class="ok' + (s.k === 'class' ? ' c' : (s.k === 'kernel' ? ' kn' : '')) + '">' + tag + '</span>'
          + '<span class="on">' + esc(CS.ids.tail(s.n)) + '</span>'
          + (h ? '<span class="oh">' + h + '</span>' : '')
          + '<span class="ol">' + s.l + '</span></button>';
      }).join('');
      root.innerHTML = '<div class="vbox">'
        + '<div class="vhead"><b>' + esc(fv.file) + '</b>'
        + '<span class="langtag lang-' + esc(fv.lang) + '">' + esc(fv.lang_label) + '</span>'
        + '<span class="vmeta">' + fv.n_lines + ' 行　' + syms.length + ' 个符号'
        + (fv.outline_kind === 'lexer' ? '（大纲为启发式）' : '') + '　包 ' + esc(fv.pkg) + '</span>'
        + '<span class="sp"></span>'
        + (hist.length ? '<button class="vbtn" data-back title="回到跳过来之前的位置">← 返回</button>' : '')
        + (X && X.stale ? '<span class="vhint stale" title="xref 是 scan 时的快照，文件改过之后行列号对不上，链接会指错地方">文件在 scan 之后改过：重新 scan 才能 Ctrl+点击</span>'
           : X && X.toks.length ? '<span class="vhint" title="Ctrl（Mac 上 ⌘）+ 点击名字跳到定义；点定义列出所有引用">Ctrl+点击：定义 / 引用</span>' : '')
        + (nRT ? '<span class="vhint rt" title="叠着的 run 里，这些行的调用代码里看不出会调到谁（多态、注册表、回调、框架转了一道）；行尾是这次运行实际调到的，点击跳过去">'
             + nRT + ' 行代码里看不出调到谁：行尾 → 是这次跑到的</span>'
           : fv.runtime && hm && hm.has_lines === false
             ? '<span class="vhint rt" title="2026-09-30 之前录的 run 只记了谁调了谁，没记调用写在哪一行；重新录一次就有">'
               + '这个 run 没记调用行：行尾不标运行时调到了谁</span>' : '')
        + '<button class="vbtn" data-find title="在这个文件里查找（Ctrl+F）">查找</button>'
        + '<button class="vbtn" data-copy="' + esc(fv.file) + '">复制路径</button>'
        + '<button class="vbtn" data-edit="1">编辑器打开</button>'
        + '<button class="vclose" aria-label="关闭">×</button></div>'
        + '<div class="vbody"><nav class="voutline" aria-label="符号大纲">'
        + (outline || '<p class="hint" style="padding:10px">这个文件里没有类或函数。</p>')
        + '</nav><div class="vcode" tabindex="0">' + rows.join('') + '</div>'
        + '<aside class="vrefs" hidden></aside></div></div>';
      codeEl = root.querySelector('.vcode'); outlineEl = root.querySelector('.voutline');
      var self = this, cur = line || 1;
      CS.xref.mark(codeEl, X, fv.file, function (l) {
        var el = document.getElementById('vL' + l); return el && el.querySelector('.tx');
      });
      var bk = root.querySelector('[data-back]');
      if (bk) bk.onclick = function () { self.back(); };
      [].forEach.call(root.querySelectorAll('.osym'), function (b) {
        b.onclick = function () { var k = +b.dataset.k; curLine = syms[k].l; self.focus(syms[k].l, rangeOf(syms, k, fv.n_lines)); };
      });
      var cp = root.querySelector('[data-copy]');
      if (cp) cp.onclick = function () {
        var t = fv.file + ':' + cur;
        if (navigator.clipboard) navigator.clipboard.writeText(t).then(function () {
          cp.textContent = '已复制'; setTimeout(function () { cp.textContent = '复制路径'; }, 1200); }, function () {});
      };
      var ed = root.querySelector('[data-edit]');
      if (ed) ed.onclick = function () { CS.ds.openEditor(fv.file, cur); };
      [].forEach.call(root.querySelectorAll('.rtj [data-rf]'), function (b) {
        b.onclick = function (ev) { ev.stopPropagation(); self.here(b); self.jump(b.dataset.rf, +b.dataset.rl); };
      });
      codeEl.onclick = function (ev) {                 // 点某行 → 记下来，复制/跳编辑器都用它
        if (CS.xref.click(ev)) return;                // Ctrl+点击名字：跳定义 / 列引用
        var ln = ev.target.closest && ev.target.closest('.ln'); if (!ln) return;
        cur = curLine = +ln.id.slice(2);
        [].forEach.call(codeEl.querySelectorAll('.ln.pick'), function (x) { x.classList.remove('pick'); });
        ln.classList.add('pick');
      };
      codeEl.onscroll = function () { self._syncOutline(); };
      this._wireClose();
      if (line) {
        var k = -1; for (var i2 = 0; i2 < syms.length; i2++) if (syms[i2].l === line) { k = i2; break; }
        this.focus(line, k >= 0 ? rangeOf(syms, k, fv.n_lines) : line);
      } else this._syncOutline();
      if (at && at.top != null) { codeEl.scrollTop = at.top; this._syncOutline(); }   // 返回：回到跳走前看到的位置
      if (at && at.col != null) this._markAt(line, at.col);
      if (refsOpen) this._renderRefs();
      root.querySelector('[data-find]').onclick = function () { CS.findbar.show(); };
      CS.findbar.attach(root.querySelector('.vbody'), codeEl);      // 查找栏开着：按这个文件重找
      if (!CS.findbar.isOpen()) root.querySelector('.vclose').focus({ preventScroll: true });
    },

    /* Ctrl+点击发生在全文窗口里的哪一行：记下来，「返回」回到这里 */
    here: function (el) {
      var ln = codeEl && el.closest && el.closest('.ln');
      if (ln && codeEl.contains(ln)) curLine = +ln.id.slice(2);
    },

    /* 转到定义。仓库外的名字没有定义可跳：说一声、留在原地 */
    goto: function (target, where) {
      if (!where) { this.toast('定义不在仓库里：' + target.slice(2)); return; }
      this.jump(where[0], where[1]);
    },

    /* 在窗口里跳到 f:l（col：标出这一行里的哪一处），记下当前位置供「返回」 */
    jump: function (f, l, col) {
      var shown = root && !root.hidden;
      if (curFile && shown) hist.push({ f: curFile, l: curLine, top: codeEl ? codeEl.scrollTop : 0 });
      if (f === curFile && codeEl && shown) {
        this._show(l); if (col != null) this._markAt(l, col); this._refreshBack(); return;
      }
      this.open(f, l, true, col != null ? { col: col } : null);
    },

    back: function () {
      var h = hist.pop(); if (!h) return;
      if (h.f === curFile && codeEl) {
        this._show(h.l); codeEl.scrollTop = h.top; this._syncOutline(); this._refreshBack(); return;
      }
      this.open(h.f, h.l, true, { top: h.top });
    },

    /* 跳到某个引用时，把那一处（行里第 col 列的名字）闪一下，不只高亮整行 */
    _markAt: function (l, col) {
      var ln = document.getElementById('vL' + l);
      if (!ln) return;
      [].forEach.call(codeEl.querySelectorAll('.xr.xhit'), function (x) { x.classList.remove('xhit'); });
      var tx = ln.querySelector('.tx'), pos = 0, hit = null;
      var w = document.createTreeWalker(tx, NodeFilter.SHOW_TEXT), n;
      while ((n = w.nextNode())) {
        if (pos <= col && col < pos + n.data.length) { hit = n.parentNode.closest('.xr'); break; }
        pos += n.data.length;
      }
      if (hit) {
        hit.classList.add('xhit');
        // 引用列表占着右边：这一处要是被挡住了，横向滚到看得见
        var r = hit.getBoundingClientRect(), c = codeEl.getBoundingClientRect();
        if (r.right > c.right - 12) codeEl.scrollLeft += r.right - c.right + 60;
      }
    },

    _refreshBack: function () {
      var bk = root.querySelector('[data-back]');
      if (hist.length && !bk) {
        var b = document.createElement('button'); b.className = 'vbtn'; b.dataset.back = '1';
        b.title = '回到跳过来之前的位置'; b.textContent = '← 返回';
        var self = this; b.onclick = function () { self.back(); };
        root.querySelector('.vhead .sp').after(b);
      } else if (!hist.length && bk) bk.remove();
    },

    /* 定位到一行：是某个符号的开头就高亮它整段，否则只高亮这一行 */
    _show: function (l) {
      curLine = l;
      var k = -1; for (var i = 0; i < syms.length; i++) if (syms[i].l === l) { k = i; break; }
      this.focus(l, k >= 0 ? rangeOf(syms, k, codeEl.querySelectorAll('.ln').length) : l);
    },

    /* 打开「定义 + 引用」一栏。go：先跳到定义（点的是一处引用时）。可以从别的地方（详情面板里的片段）调：
       窗口没开就先打开定义所在的文件 */
    refs: function (target, where, name, go) {
      var self = this, shown = root && !root.hidden;
      if (where && shown && (go || where[0] !== curFile)) {
        this.jump(where[0], where[1]);
      } else if (where && !shown) {
        this.open(where[0], where[1]);
      }
      // 窗口是异步画出来的：画好时会按它补上列表。scroll / sel：跳到别的文件再画时，列表停在原来的位置
      refsOpen = { target: target, name: name, data: null, scroll: 0, sel: where ? { f: where[0], l: where[1] } : null };
      this._renderRefs();
      CS.ds.refs(target).then(function (r) {
        if (!refsOpen || refsOpen.target !== target) return;
        refsOpen.data = r || { refs: [], total: 0, counts: {} };
        self._renderRefs();
      }).catch(function (e) { if (refsOpen && refsOpen.target === target) { refsOpen.data = { error: e.message }; self._renderRefs(); } });
    },

    _renderRefs: function () {
      var box = root && root.querySelector('.vrefs');
      if (!box || !refsOpen) return;
      box.hidden = false;
      root.querySelector('.vbody').classList.add('withrefs');       // 列表是代码旁边的一栏，不盖住代码
      CS.findbar.place();                                          // 查找栏让开它
      var r = refsOpen.data, self = this, isMember = /^[sv]:[^:]+:.+\./.test(refsOpen.target);
      var h = '<div class="rh"><b>' + esc(refsOpen.name || shortTarget(refsOpen.target)) + '</b> 被引用'
        + '<button class="vclose rx" aria-label="关闭引用列表">×</button></div>';
      function list(rows, cls) {
        var byF = {}, out = '';
        rows.forEach(function (x) { (byF[x.f] = byF[x.f] || []).push(x); });
        Object.keys(byF).forEach(function (f) {
          out += '<div class="rf' + (cls ? ' ' + cls : '') + '"><div class="rfn" title="' + esc(f) + '">'
            + esc(f.split('/').slice(-2).join('/')) + '<span class="n">' + byF[f].length + '</span></div>'
            + byF[f].map(function (x) {
              var on = refsOpen.sel && refsOpen.sel.f === f && refsOpen.sel.l === x.l;
              return '<button class="rr' + (on ? ' on' : '') + '" data-f="' + esc(f) + '" data-l="' + x.l + '" data-c="' + x.c + '">'
                + '<span class="rl">' + x.l + '</span><span class="rk k' + x.k + '">' + KIND[x.k] + '</span>'
                + '<code>' + esc(x.text) + '</code>'
                + (x.n > 1 ? '<span class="rn">×' + x.n + '</span>' : '')
                + (x.stale ? '<span class="rst" title="这个文件在 scan 之后改过，行号可能已经不对">改过</span>' : '')
                + '</button>';
            }).join('') + '</div>';
        });
        return out;
      }
      if (!r) { box.innerHTML = h + '<p class="hint">读取中…</p>'; }
      else if (r.error) { box.innerHTML = h + '<p class="hint">读取失败：' + esc(r.error) + '</p>'; }
      else {
        var c = r.counts || {};
        h += '<p class="rs">共 ' + r.total + ' 处'
          + (c.call ? '　调用 ' + c.call : '') + (c.ref ? '　引用 ' + c.ref : '') + (c['import'] ? '　import ' + c['import'] : '')
          + (r.calls ? '　<span class="rt">这次 runtime 调用 ' + r.calls + ' 次</span>' : '')
          + (r.refs.length < (r.lines || r.refs.length) ? '<br>只列前 ' + r.refs.length + ' 行' : '') + '</p>';
        if (r.def) {
          var don = refsOpen.sel && refsOpen.sel.f === r.def.f && refsOpen.sel.l === r.def.l;
          h += '<div class="rf rdef"><div class="rfn">定义<span class="n" title="' + esc(r.def.f) + '">'
            + esc(r.def.f.split('/').slice(-2).join('/')) + '</span></div>'
            + '<button class="rr' + (don ? ' on' : '') + '" data-f="' + esc(r.def.f) + '" data-l="' + r.def.l + '">'
            + '<span class="rl">' + r.def.l + '</span><span class="rk k3">定义</span><code>' + esc(r.def.text || '') + '</code>'
            + (r.def.stale ? '<span class="rst" title="这个文件在 scan 之后改过，行号可能已经不对">改过</span>' : '')
            + '</button></div>';
        }
        if (isMember)
          h += '<p class="rs note">静态分析只认得 <code>self.</code> / <code>cls.</code> / <code>类名.</code> / <code>super()</code> 这几种写法；'
            + '通过别的对象调用（<code>engine.' + esc(CS.ids.tail(shortTarget(refsOpen.target))) + '()</code>）不知道对象是什么类型，列在下面「同名」一组里。</p>';
        if (!r.refs.length)
          h += '<p class="hint">' + (isMember ? '按类型确认的引用一处也没有。' : '仓库里没有别的地方引用它（可能只经由字符串 / getattr / 注册表使用，静态分析看不到）。') + '</p>';
        h += list(r.refs, '');
        var m = r.maybe;
        if (m && m.lines) {
          h += '<div class="rmaybe"><div class="rmh">同名的 <code>.' + esc(m.name) + '</code>（没确认对象类型）<span class="n">' + m.total + ' 处</span></div>'
            + '<p class="rs">' + (m.same <= 1 ? '仓库里只有这一个成员叫 <code>' + esc(m.name) + '</code>，这些基本就是在用它。'
                                  : '仓库里有 ' + m.same + ' 个成员叫 <code>' + esc(m.name) + '</code>，这些不一定是它。') + '</p>'
            + list(m.refs, 'maybe') + '</div>';
        }
        box.innerHTML = h;
      }
      box.querySelector('.rx').onclick = function () { self._closeRefs(); };
      box.onscroll = function () { if (refsOpen) refsOpen.scroll = box.scrollTop; };
      [].forEach.call(box.querySelectorAll('.rr'), function (b) {
        b.onclick = function () {
          [].forEach.call(box.querySelectorAll('.rr.on'), function (x) { x.classList.remove('on'); });
          b.classList.add('on');
          refsOpen.sel = { f: b.dataset.f, l: +b.dataset.l };
          refsOpen.scroll = box.scrollTop;
          self.jump(b.dataset.f, +b.dataset.l, b.dataset.c != null ? +b.dataset.c : null);
        };
      });
      box.scrollTop = refsOpen.scroll || 0;
    },

    _closeRefs: function () {
      refsOpen = null;
      var box = root && root.querySelector('.vrefs');
      if (box) { box.hidden = true; box.innerHTML = ''; }
      var vb = root && root.querySelector('.vbody');
      if (vb) vb.classList.remove('withrefs');
      CS.findbar.place();
    },

    /* 提示：窗口开着就放在窗口里，没开（从详情面板的片段点的）就放在页面底部 */
    toast: function (msg) {
      var box = root && !root.hidden && root.querySelector('.vbox'), t;
      if (box) {
        t = box.querySelector('.vtoast');
        if (!t) { t = document.createElement('div'); t.className = 'vtoast'; box.appendChild(t); }
      } else {
        t = document.getElementById('gtoast');
        if (!t) { t = document.createElement('div'); t.id = 'gtoast'; t.className = 'vtoast page'; document.body.appendChild(t); }
      }
      t.textContent = msg; t.classList.add('on');
      clearTimeout(this._tt); this._tt = setTimeout(function () { t.classList.remove('on'); }, 2600);
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
      document.onkeydown = function (ev) {
        if (ev.key !== 'Escape' || root.hidden) return;
        // Esc 先关查找栏，再关引用列表，最后关窗口
        if (CS.findbar.isOpen()) { CS.findbar.hide(); return; }
        var rb = root.querySelector('.vrefs');
        if (rb && !rb.hidden) { self._closeRefs(); return; }
        self.close();
      };
    },

    close: function () {
      if (!root) return;
      root.hidden = true; root.innerHTML = '';
      hist = []; refsOpen = null; curFile = null;
      CS.findbar.detach();
      document.body.style.overflow = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
  };
})(window.CS);
