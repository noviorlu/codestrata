/* 全文窗口里的查找（和 VS Code 的 Ctrl+F 一样）：在当前文件里找，可以区分大小写、全字匹配、用正则。
 * 匹配用 CSS Custom Highlight 标出——不改 DOM，Ctrl+点击的名字、高亮好的代码都不受影响——当前那个另一个颜色；
 * 只标视野附近的（滚动时重标），几万个匹配的大文件也不卡，跳转照样走遍全部。
 * Enter / Shift+Enter（F3 / Shift+F3、↑ ↓ 按钮）在匹配之间跳，Alt+C / Alt+W / Alt+R 切三个选项，Esc 关掉。
 * 转到定义、返回换了文件时查找栏留着，按新文件重找；关掉全文窗口时收起，下次 Ctrl+F 还是上次的词。
 * viewer.js 调 attach / detach / place，别的都在这里。find(行, 词, 选项) 是纯函数，测试直接调。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var SEP = '`~!@#$%^&*()-=+[{]}\\|;:\'",.<>/?';   // VS Code 默认的 editor.wordSeparators
  var MAX = 200000;                                 // 最多找这么多个（再多只说「200000+」，防一个字母搜巨型文件）
  var NEAR = 60;                                    // 视野上下各多标这么多行：滚一点不用等重标
  var st = { open: false, q: '', cs: false, ww: false, re: false };   // 换文件、关掉再开都留着
  var body = null, code = null, bar = null, input = null, hits = [], cur = -1, timer = null, last = {}, frame = 0;
  // 快捷键按 ev.code 认：Mac 上 Option+C 的 ev.key 是「ç」
  var OPTS = [['cs', 'Aa', '区分大小写（Alt+C）', 'KeyC'], ['ww', '<u>ab</u>', '全字匹配（Alt+W）', 'KeyW'],
              ['re', '.*', '正则表达式（Alt+R）', 'KeyR']];
  function escRe(q) { return q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function isSep(c) { return /\s/.test(c) || SEP.indexOf(c) >= 0; }
  /* 全字匹配的边界（和 VS Code 一样）：行首 / 行尾、挨着分隔符，或者匹配本身在这一头是分隔符 */
  function bound(s, a, b) {
    return (a === 0 || isSep(s[a - 1]) || isSep(s[a])) && (b === s.length || isSep(s[b]) || isSep(s[b - 1]));
  }

  /* 正则带 u（和 VS Code 一样：. 能配上一整个 emoji，\p{L} 能用）；老写法在 u 下不合法（\- 这种）就退回不带 u */
  function compile(q, o) {
    var src = o.re ? q : escRe(q), fl = 'g' + (o.cs ? '' : 'i');
    try { return new RegExp(src, fl + 'u'); } catch (e) { return new RegExp(src, fl); }
  }
  /* lines：每行的纯文本。→ {hits: [[行号（从 1 起）, 起, 止]…], error（正则写错了）, capped} */
  function find(lines, q, o) {
    if (!q) return { hits: [] };
    var rx;
    try { rx = compile(q, o); } catch (e) { return { hits: [], error: e.message }; }
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      var s = lines[i], m;
      rx.lastIndex = 0;
      while ((m = rx.exec(s))) {
        var a = m.index, b = a + m[0].length;
        if (b === a || (o.ww && !bound(s, a, b))) {                      // 空匹配（^、a*）不算；往后挪一个字符（不拆开 emoji）
          rx.lastIndex = a + (s.codePointAt(a) > 0xffff ? 2 : 1);
          continue;
        }
        out.push([i + 1, a, b]);
        if (out.length >= MAX) return { hits: out, capped: true };
      }
    }
    return { hits: out };
  }

  function lineTx(l) { var el = document.getElementById('vL' + l); return el && el.querySelector('.tx'); }
  /* 一个匹配 → 盖住它的 Range（一行里被高亮 span 拆成好几个文本节点） */
  function rangeOf(h) {
    var tx = lineTx(h[0]);
    if (!tx) return null;
    var w = document.createTreeWalker(tx, NodeFilter.SHOW_TEXT), n, pos = 0, r = document.createRange(), started = false;
    while ((n = w.nextNode())) {
      var end = pos + n.data.length;
      if (!started && h[1] < end) { r.setStart(n, h[1] - pos); started = true; }
      if (started && h[2] <= end) { r.setEnd(n, h[2] - pos); return r; }
      pos = end;
    }
    return null;
  }
  var canMark = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight === 'function';
  /* 代码里纵坐标 y 处是第几行：按行元素的实际位置二分。不能拿 y 除行高——带 emoji、中文的行会高一点，
     几千行下来差出十几行 */
  function lineAt(y) {
    var rows = code.children, lo = 0, hi = rows.length - 1;
    if (hi < 0) return 1;
    var base = rows[0].offsetTop;
    while (lo < hi) {
      var mid = (lo + hi) >> 1, el = rows[mid];
      if (el.offsetTop - base + el.offsetHeight <= y) lo = mid + 1; else hi = mid;
    }
    return lo + 1;
  }
  /* 第一个行号 ≥ l 的匹配（hits 按行排好） */
  function firstFrom(l) {
    var lo = 0, hi = hits.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (hits[mid][0] < l) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function paint() {
    frame = 0;
    if (!canMark) return;
    CSS.highlights.delete('cs-find'); CSS.highlights.delete('cs-find-cur');
    if (!code || !bar || !hits.length) return;
    var all = new Highlight(), from = lineAt(code.scrollTop) - NEAR, to = lineAt(code.scrollTop + code.clientHeight) + NEAR;
    for (var i = firstFrom(from); i < hits.length && hits[i][0] <= to; i++) {
      if (i !== cur) { var r = rangeOf(hits[i]); if (r) all.add(r); }
    }
    CSS.highlights.set('cs-find', all);
    var c = cur >= 0 && rangeOf(hits[cur]);
    if (c) CSS.highlights.set('cs-find-cur', new Highlight(c));
  }
  function repaint() { if (!frame) frame = requestAnimationFrame(paint); }
  /* 当前匹配不在视野里才滚：竖着滚到中间，横着滚到看得见 */
  function reveal() {
    var h = hits[cur], r = h && rangeOf(h);
    if (!r) return;
    var cr = code.getBoundingClientRect(), rr = r.getBoundingClientRect();
    if (rr.top < cr.top + 40 || rr.bottom > cr.top + code.clientHeight - 8)
      code.scrollTop += rr.top - cr.top - code.clientHeight / 2;
    if (rr.left < cr.left + 64 || rr.right > cr.left + code.clientWidth - 8)
      code.scrollLeft = Math.max(0, code.scrollLeft + rr.left - cr.left - code.clientWidth / 2);
  }
  /* 视野最上面那一行（从这里往下找第一个匹配：刚打开、换了词、换了文件时从这里接着看） */
  function topLine() { return lineAt(code.scrollTop); }

  function count() {
    var c = bar.querySelector('.fc'), res = last;
    bar.classList.toggle('bad', !!res.error || (!!st.q && !hits.length));
    input.title = res.error ? '正则写错了：' + res.error : '';
    c.textContent = res.error ? '正则有误' : !st.q ? '' : !hits.length ? '无结果'
      : (cur + 1) + ' / ' + hits.length + (res.capped ? '+' : '');
    [].forEach.call(bar.querySelectorAll('[data-d]'), function (b) { b.disabled = !hits.length; });
  }
  /* 按现在的词和选项重找。jump：把当前匹配定到视野里第一个（打字、换选项时）并滚过去；
     不 jump（换了文件）只标出来，不动滚动位置 */
  function run(jump) {
    if (!bar) return;                                // 查找栏已经关了（防抖的那一下晚到）
    // 空行在代码栏里画成一个空格（.tx.e），找的时候当空行
    var lines = [].map.call(code.querySelectorAll('.ln .tx'), function (t) { return t.classList.contains('e') ? '' : t.textContent; });
    var res = last = find(lines, st.q, st);
    hits = res.hits;
    cur = hits.length ? firstFrom(topLine()) % hits.length : -1;   // 视野里（往下）第一个；下面没有就绕回第一个
    if (jump) reveal();
    paint(); count();
  }
  function step(d) {
    if (!hits.length) return;
    cur = (cur + d + hits.length) % hits.length;
    reveal(); paint(); count();
  }

  function build() {
    bar = document.createElement('div');
    bar.className = 'vfind'; bar.setAttribute('role', 'search');
    bar.innerHTML = '<span class="fi"><input type="text" spellcheck="false" autocomplete="off" aria-label="在这个文件里查找" placeholder="查找">'
      + OPTS.map(function (o) {
          return '<button class="fo" data-o="' + o[0] + '" aria-pressed="' + st[o[0]] + '" title="' + o[2] + '">' + o[1] + '</button>';
        }).join('') + '</span>'
      + '<span class="fc" aria-live="polite"></span>'
      + '<button class="fb" data-d="-1" title="上一个（Shift+Enter）" aria-label="上一个">↑</button>'
      + '<button class="fb" data-d="1" title="下一个（Enter）" aria-label="下一个">↓</button>'
      + '<button class="fb" data-x title="关闭（Esc）" aria-label="关闭查找">×</button>';
    body.appendChild(bar);
    input = bar.querySelector('input');
    input.value = st.q;
    input.oninput = function () {
      st.q = input.value;
      clearTimeout(timer); timer = setTimeout(function () { timer = null; run(true); }, 60);
    };
    input.onkeydown = function (ev) {
      if (ev.key === 'Enter' || ev.key === 'F3') {
        ev.preventDefault();
        if (timer) { clearTimeout(timer); timer = null; run(false); }   // 打完字立刻回车：先按现在的词找
        step(ev.shiftKey ? -1 : 1);
      } else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); CS.findbar.hide(); }
    };
    bar.onkeydown = function (ev) {                  // Alt+C / W / R：焦点在查找栏里任何地方都行
      if (!ev.altKey || ev.ctrlKey || ev.metaKey) return;
      var o = OPTS.filter(function (x) { return x[3] === ev.code; })[0];
      if (o) { ev.preventDefault(); toggle(o[0]); }
    };
    [].forEach.call(bar.querySelectorAll('[data-o]'), function (b) { b.onclick = function () { toggle(b.dataset.o); input.focus(); }; });
    [].forEach.call(bar.querySelectorAll('[data-d]'), function (b) { b.onclick = function () { step(+b.dataset.d); }; });
    bar.querySelector('[data-x]').onclick = function () { CS.findbar.hide(); };
  }
  function toggle(k) {
    st[k] = !st[k];
    bar.querySelector('[data-o="' + k + '"]').setAttribute('aria-pressed', String(st[k]));
    run(true);
  }

  // Ctrl+F（Mac 上 ⌘F）：全文窗口开着时换成这里的查找；F3 / Shift+F3 在查找栏外面也能跳
  document.addEventListener('keydown', function (ev) {
    var v = document.getElementById('viewer');
    if (!v || v.hidden || !code) return;
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === 'f' || ev.key === 'F')) {
      ev.preventDefault(); CS.findbar.show();
    } else if (ev.key === 'F3' && st.open && ev.target !== input) { ev.preventDefault(); step(ev.shiftKey ? -1 : 1); }
  });
  window.addEventListener('resize', function () { CS.findbar.place(); });

  CS.findbar = {
    find: find,
    isOpen: function () { return st.open && !!bar && !bar.hidden; },

    /* 全文窗口画好一个文件后调：查找栏开着就按新文件重找（不滚动）。读取中、没有代码时传 null */
    attach: function (vbody, codeEl) {
      body = vbody; code = codeEl; bar = input = null; hits = []; cur = -1;
      clearTimeout(timer); timer = null;
      if (!st.open || !code) return paint();
      code.addEventListener('scroll', repaint);
      build(); this.place(); run(false);
    },
    /* 全文窗口关了：收起，清掉标记（词和选项留着） */
    detach: function () {
      st.open = false; body = code = bar = input = null; hits = []; cur = -1;
      clearTimeout(timer); timer = null;
      paint();
    },

    /* 打开（Ctrl+F / 头上的「查找」）：选中了一行里的一段字就拿它当词，全选输入框 */
    show: function () {
      if (!code) return;
      var sel = window.getSelection && window.getSelection(), t = sel && String(sel);
      if (t && t.indexOf('\n') < 0 && sel.anchorNode && code.contains(sel.anchorNode)) st.q = st.re ? escRe(t) : t;
      if (!st.open) code.addEventListener('scroll', repaint);
      st.open = true;
      if (!bar) { build(); this.place(); } else input.value = st.q;
      input.focus(); input.select();
      run(true);
    },
    hide: function () {
      if (!bar) return;
      clearTimeout(timer); timer = null;
      st.open = false; bar.remove(); bar = input = null; hits = []; cur = -1;
      if (code) code.removeEventListener('scroll', repaint);
      paint();
      if (code) code.focus({ preventScroll: true });
    },
    /* 浮在代码栏的右上角：旁边开着引用列表时让开它、也让开竖滚动条，不宽过代码栏；
       窄屏上引用列表把代码栏整个藏起来时，查找栏也藏起来（Esc 不去关一个看不见的东西） */
    place: function () {
      if (!bar || !code) return;
      bar.hidden = !code.clientWidth;
      if (bar.hidden) return;
      var b = body.getBoundingClientRect(), c = code.getBoundingClientRect();
      bar.style.right = Math.max(8, b.right - (c.left + code.clientWidth) + 8) + 'px';
      bar.style.maxWidth = Math.max(160, code.clientWidth - 16) + 'px';
    }
  };
})(window.CS);
