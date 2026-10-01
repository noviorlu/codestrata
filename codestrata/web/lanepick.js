/* 分列里点线（lanes.js 用）：线没有隐形的命中区，按离鼠标最近的那条算（laneroute.js 的 picker），不是哪条叠在上面算哪条。
 * 鼠标附近最近的那条加粗、图上变手形，停一会儿在鼠标旁边出它的提示；点下去选中的就是正亮着的那条（提示说的那条）。
 * 正亮着的那条和别的线一样近（正好交叉、叠在一起）时，提示写「这里叠着几条」，点了弹一个小单子挑一条。
 * 悬停着的那条不轻易换：别的线要近 2 像素以上才换过去（两条挨着时不来回闪）。节点、序号牌、代码标签、起 / 收标记有自己的点击；
 * 线的标签是它那条线的把手。重画之前、离开分列（换成模块图）时 leave：撤掉 #g 上的监听、提示、手形和单子 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var R = 12, STICK = 2, TIE = 1.5;                 // 屏幕像素：选线半径（WCAG 的 24 px 目标）、悬停的粘性、算一样近
  var tip = null, svgEl = null, over = null, ties = [], timer = null, last = null, box = null;

  function esc(s) { return CS.lanes.fmt.esc(s); }
  function own(t) { return t && t.closest && t.closest('.ln-nd, .tn, .ln-code, .ln-mark, .ln-proc'); }

  /* 屏幕上的一点附近的线（看得见的），按离它的距离从近到远 [{E, d（屏幕像素）}] */
  function hitAt(lanes, cx, cy, r) {
    var m = lanes.picker && lanes.svg && lanes.svg.getScreenCTM();
    if (!m) return [];
    var inv = m.inverse(), x = inv.a * cx + inv.c * cy + inv.e, y = inv.b * cx + inv.d * cy + inv.f;
    var s = Math.sqrt(m.a * m.a + m.b * m.b) || 1, by = lanes.byKey;
    return lanes.picker.near(x, y, (r || R) / s).map(function (h) { return { E: by[h.key], d: h.d * s }; })
      .filter(function (h) { return h.E && h.E.show !== false; });
  }

  /* 鼠标在这一点时该亮哪条：悬停着的那条只要不比最近的远 2 像素以上就留着；和它一样近的几条（含它）一起返回 */
  function target(lanes, ev) {
    var h = hitAt(lanes, ev.clientX, ev.clientY);
    if (!h.length) return null;
    var keep = over && h.filter(function (x) { return x.E === over; })[0], T = keep && h[0].d > keep.d - STICK ? keep : h[0];
    return { E: T.E, ties: h.filter(function (x) { return Math.abs(x.d - T.d) < TIE; }).map(function (x) { return x.E; }) };
  }

  function tipEl() {
    if (!tip) { tip = document.createElement('div'); tip.className = 'ln-tip'; tip.hidden = true; document.body.appendChild(tip); }
    return tip;
  }
  function place() {                                 // 提示跟着鼠标（最后一次移动的位置）
    if (!tip || tip.hidden || !last) return;
    tip.style.left = Math.min(last.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = Math.min(last.clientY + 16, window.innerHeight - tip.offsetHeight - 8) + 'px';
  }
  function tipText(E, T) {
    if (T.length < 2) return E.tip.textContent;
    return '这里叠着 ' + T.length + ' 条线，点了挑一条：\n' + T.map(function (x) { return '· ' + x.tipBase.split('\n')[0]; }).join('\n');
  }
  function hover(E, T) {
    T = T || (E ? [E] : []);
    var same = over === E && ties.length === T.length;
    if (same) { place(); return; }
    if (over) over.p.classList.remove('hover');
    over = E; ties = T; clearTimeout(timer); tipEl().hidden = true;
    if (E) {
      E.p.classList.add('hover');
      timer = setTimeout(function () {
        if (over !== E) return;
        tip.textContent = tipText(E, ties); tip.hidden = false; place();
      }, 350);
    }
    if (svgEl) svgEl.classList.toggle('ln-over', !!E);
  }

  /* 几条线叠在鼠标下面一样近：列出来挑一条（Esc、点别处关掉） */
  function chooser(Es, ev) {
    closeChooser();
    box = document.createElement('div');
    box.className = 'ln-pick';
    box.innerHTML = '<div class="hint">这里叠着 ' + Es.length + ' 条线，选一条：</div>' + Es.map(function (E, i) {
      var t = E.tipBase.split('\n');
      return '<button data-i="' + i + '"><b>' + esc(t[0]) + '</b><span>' + esc(t[1] || '') + '</span></button>';
    }).join('');
    document.body.appendChild(box);
    box.style.left = Math.min(ev.clientX + 8, window.innerWidth - box.offsetWidth - 8) + 'px';
    box.style.top = Math.min(ev.clientY + 8, window.innerHeight - box.offsetHeight - 8) + 'px';
    box._Es = Es;
    document.addEventListener('mousedown', outside, true);
    document.addEventListener('keydown', key, true);
    [].forEach.call(box.querySelectorAll('button'), function (b) {
      var E = Es[+b.dataset.i];
      b.onmouseenter = function () { E.p.classList.add('hover'); };
      b.onmouseleave = function () { E.p.classList.remove('hover'); };
      b.onclick = function (e) { closeChooser(); E.click(e); };
    });
    box.querySelector('button').focus();
  }
  function outside(e) { if (box && !box.contains(e.target)) closeChooser(); }
  function key(e) { if (e.key === 'Escape' && box) { e.stopPropagation(); closeChooser(); } }
  function closeChooser() {
    if (!box) return;
    box._Es.forEach(function (E) { if (E !== over) E.p.classList.remove('hover'); });
    box.remove(); box = null;
    document.removeEventListener('mousedown', outside, true);
    document.removeEventListener('keydown', key, true);
  }

  CS.lanePick = {
    hitAt: hitAt,
    chooser: chooser,

    /* 画好之后接上 #g 的鼠标（先 leave 掉上一次的） */
    wire: function (lanes, svg) {
      this.leave();
      svgEl = svg;
      svg.onmousemove = function (ev) {
        last = ev;
        if (own(ev.target)) { hover(null); return; }
        var L = lanes.labs && lanes.labs.get(ev.target);
        if (L) { hover(L); return; }
        var t = target(lanes, ev);
        hover(t && t.E, t && t.ties);
      };
      svg.onmouseleave = function () { hover(null); };
      svg.onclick = function (ev) {
        if (own(ev.target) || (lanes.labs && lanes.labs.get(ev.target))) return;
        var t = target(lanes, ev);
        if (!t) return;                              // 空白处：交给图框（取消选中）
        hover(null);
        if (t.ties.length > 1) { ev.stopPropagation(); chooser(t.ties, ev); return; }
        t.E.click(ev);
      };
    },

    /* 重画之前、离开分列时：撤掉监听、提示、手形、单子 */
    leave: function () {
      hover(null); closeChooser();
      if (svgEl) { svgEl.onmousemove = svgEl.onmouseleave = svgEl.onclick = null; svgEl.classList.remove('ln-over'); }
      svgEl = null; last = null;
    }
  };
})(window.CS);
