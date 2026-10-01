/* 时间轴：阶段按钮 + 一条从 run 开头到结尾的时间条（阶段是条上一段段的颜色，切走又切回来的阶段有几段）。
 * 点按钮、点条上的一段 = 选这个阶段；拖两头的把手、拖中间平移、在空白处拖出一段 = 选一个时间段
 * （「t=起-止」，微秒，和阶段名放在同一个位置：run 引用的 @ 后面）。拖到和一个阶段、或者整个 run 对得上
 * 就当成它。没录时序事件的 run 只能选阶段（时间段要按事件现算）。
 * 条可以缩放：滚轮以鼠标处为中心缩放、Shift+滚轮平移；点阶段按钮时自动放大到这个阶段（前后各留一点）。
 * 用法：CS.timebar.render(容器, {run, names: 阶段名, segs: [[名字, 起, 止]…], end（0：不知道多长，只有按钮）,
 *                                 phase, window, canDrag, tips: {阶段名: 按钮提示}, onSelect(阶段名 | 't=起-止' | '')}) */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  /* 秒，小数位随要分辨的跨度走：几分钟的 run 一位，几毫秒的时间段到微秒 */
  function sec(us, span) {
    var d = Math.max(1, Math.min(6, Math.ceil(-Math.log10(Math.max(span, 1) / 1e6)) + 2));
    return (us / 1e6).toFixed(d) + ' s';
  }
  var FIT_PAD = 0.25, MIN_VIEW = 1000;          // 放大到一段时前后各留它长度的 25%；最多放大到 1 ms 宽
  var views = {};                               // run id → 条上看的范围 [起, 止]（换阶段、重画都保留）
  // 键盘挪把手：停手半秒才提交。等着的那一下在任何新的选择、重画时作废（不然会盖掉用户刚点的别的）；
  // 提交后重画时把焦点还给原来那个把手
  var pending = null, refocus = null;
  function cancel() { clearTimeout(pending); pending = null; }

  function parse(ref) {
    var m = /^t=(\d+)-(\d+)$/.exec(ref || '');
    return m ? [+m[1], +m[2]] : null;
  }

  CS.timebar = {
    parse: parse,

    /* 横幅、按钮上给人看的：阶段名原样；时间段写成「起 – 止 s」 */
    label: function (ref) {
      var w = parse(ref);
      return w ? sec(w[0], w[1] - w[0]) + ' – ' + sec(w[1], w[1] - w[0]) : ref || '';
    },

    /* 一个阶段（可能好几段）从哪到哪；'' 是整个 run */
    extent: function (segs, name, end) {
      if (!name) return [0, end];
      var mine = segs.filter(function (s) { return s[0] === name; });
      return mine.length ? [mine[0][1], mine[mine.length - 1][2]] : [0, end];
    },

    /* 拖出来的 [a, b] → 选什么：两头都和整个 run、或者只有一段的阶段差不到 tol 就当成它。
       names：能选的阶段（没录到调用的阶段加载不了，不往它上面吸） */
    snap: function (segs, a, b, end, tol, names) {
      if (a <= tol && b >= end - tol) return '';
      var n = {};
      segs.forEach(function (s) { n[s[0]] = (n[s[0]] || 0) + 1; });
      for (var i = 0; i < segs.length; i++) {
        var s = segs[i];
        if (n[s[0]] === 1 && (!names || names.indexOf(s[0]) >= 0)
            && Math.abs(s[1] - a) <= tol && Math.abs(s[2] - b) <= tol) return s[0];
      }
      return 't=' + Math.round(a) + '-' + Math.round(b);
    },

    /* 放大到 [a, b]：前后各留一点，至少 MIN_VIEW 宽，不超出 run；放大了也占六成以上就看整个 run */
    fit: function (a, b, end) {
      var pad = (b - a) * FIT_PAD, lo = a - pad, hi = b + pad;
      if (hi - lo < MIN_VIEW) { lo = (a + b - MIN_VIEW) / 2; hi = lo + MIN_VIEW; }
      if (lo < 0) { hi -= lo; lo = 0; }
      if (hi > end) { lo = Math.max(0, lo - (hi - end)); hi = end; }
      return hi - lo >= end * 0.6 ? [0, end] : [lo, hi];
    },

    render: function (box, o) {
      cancel();
      var focusTo = refocus;                          // 键盘提交之后的这次重画：焦点回到原来的把手上
      refocus = null;
      var self = this, segs = o.segs || [], names = o.names || [], tips = o.tips || {};
      // 地址里的时间段可能超出 run 的终点（手改的、run 重新整理过）：条放长到能画出它
      var end = o.end && Math.max(o.end, o.window ? o.window[1] : 0);
      var ref = o.window ? 't=' + o.window[0] + '-' + o.window[1] : o.phase || '';
      var cur = o.window ? o.window.slice() : this.extent(segs, o.phase, end);
      var view = views[o.run];
      if (!view || !(view[1] > view[0]) || view[1] > end) view = views[o.run] = this.fit(cur[0], cur[1], end);
      function select(r) { cancel(); o.onSelect(r); }
      box.innerHTML = '<span class="lbl">时间</span>'
        + [''].concat(names).map(function (n) {
            var ix = names.indexOf(n);
            return '<button class="chip tph" data-ph="' + esc(n) + '" aria-pressed="' + (!o.window && (o.phase || '') === n)
              + '" title="' + esc(n ? '只看 ' + n + ' 这一段' + (tips[n] || '') : '整个 run，各阶段加在一起') + '">'
              + (n ? '<i class="sw p' + (ix % 4) + '"></i>' + esc(n) : '全部') + '</button>';
          }).join('')
        + (!end ? '' : '<span class="tbar' + (o.canDrag ? ' drag' : '') + '" title="' + (o.canDrag
            ? '点一段看那个阶段；拖两头的把手、拖中间平移、在空白处拖出一段，看任意一段时间。滚轮缩放、Shift+滚轮平移'
            : '点一段看那个阶段（这个 run 没录时序事件，不能选任意时间段：录的时候用了 --no-events，或者被录的 Python 低于 3.12）。滚轮缩放、Shift+滚轮平移') + '">'
        + segs.map(function (s) {
            var ix = names.indexOf(s[0]), on = !o.window && o.phase === s[0];
            return '<span class="tseg ' + (ix < 0 ? 'nc' : 'p' + (ix % 4)) + (on ? ' on' : '') + '" data-seg="' + esc(s[0])
              + '" title="' + esc(s[0]) + '：' + sec(s[1], end) + ' – ' + sec(s[2], end)
              + (ix < 0 ? '（这个阶段没录到调用，不能单独选）' : '') + '"><i>' + esc(s[0]) + '</i></span>';
          }).join('')
        + (o.canDrag ? '<span class="tsel' + (o.window ? ' win' : '') + '"><span class="th l" tabindex="0" role="slider" aria-label="时间段的起点"></span>'
            + '<span class="th r" tabindex="0" role="slider" aria-label="时间段的终点"></span></span>' : '')
        + '</span><span class="tlab"></span>'
        + '<button class="chip tzoom" hidden title="时间条放大了：点这里看整个 run">全程</button>');
      [].forEach.call(box.querySelectorAll('.tph'), function (x) {
        x.onclick = function () {
          var e = self.extent(segs, x.dataset.ph, end);
          if (end) views[o.run] = self.fit(e[0], e[1], end);
          if (x.dataset.ph !== ref) return select(x.dataset.ph);
          if (end) { view = views[o.run]; layout(cur[0], cur[1]); }
        };
      });
      if (!end) return;
      var bar = box.querySelector('.tbar'), sel = box.querySelector('.tsel'), lab = box.querySelector('.tlab');
      var zoom = box.querySelector('.tzoom'), segEls = box.querySelectorAll('.tseg');

      function pct(t) { return 100 * (t - view[0]) / (view[1] - view[0]); }
      /* 按 view 摆条上的东西；a, b 是选中的范围（拖的时候跟着手走） */
      function layout(a, b) {
        [].forEach.call(segEls, function (el, i) {
          var s = segs[i], l = Math.max(s[1], view[0]), r = Math.min(s[2], view[1]);
          el.hidden = r <= l;
          el.style.left = pct(l) + '%'; el.style.width = (pct(r) - pct(l)) + '%';
        });
        var span = Math.max(0, b - a);
        if (sel) {
          var l = Math.max(a, view[0]), r = Math.min(b, view[1]);
          sel.hidden = r < l;
          sel.style.left = pct(l) + '%'; sel.style.width = Math.max(0.4, pct(r) - pct(l)) + '%';
          [[sel.querySelector('.l'), a], [sel.querySelector('.r'), b]].forEach(function (x) {
            x[0].hidden = x[1] < view[0] || x[1] > view[1];
            x[0].setAttribute('aria-valuemin', '0'); x[0].setAttribute('aria-valuemax', String(Math.round(end)));
            x[0].setAttribute('aria-valuenow', String(Math.round(x[1]))); x[0].setAttribute('aria-valuetext', sec(x[1], span));
          });
        }
        var full = a <= 0 && b >= end;
        lab.textContent = full ? '全程 ' + sec(end, end)
          : (o.phase && !o.window && a === cur[0] && b === cur[1] ? o.phase + '：' : '')
            + sec(a, span) + ' – ' + sec(b, span) + '（' + sec(span, span) + '）';
        lab.title = o.window ? '选的是一段时间：调用次数按这段时间里的时序事件算，只有跨文件的调用' : '';
        zoom.hidden = view[0] <= 0 && view[1] >= end;
      }
      function pick(r) { if (r !== ref) select(r); else layout(cur[0], cur[1]); }
      function pxTime() { return (view[1] - view[0]) / Math.max(1, bar.getBoundingClientRect().width); }
      function commit(a, b) {
        a = Math.max(0, Math.min(a, end)); b = Math.max(0, Math.min(b, end));
        if (b - a < 3 * pxTime()) return layout(cur[0], cur[1]);          // 窄到几个像素：当成没拖
        pick(self.snap(segs, a, b, end, 4 * pxTime(), names));
      }
      layout(cur[0], cur[1]);
      zoom.onclick = function () { view = views[o.run] = [0, end]; layout(cur[0], cur[1]); };
      var rf = focusTo && box.querySelector('.th.' + focusTo);
      if (rf && !rf.hidden) rf.focus({ preventScroll: true });

      // 滚轮：以鼠标处为中心缩放；Shift+滚轮（或触控板横向）平移
      bar.addEventListener('wheel', function (ev) {
        ev.preventDefault();
        var r = bar.getBoundingClientRect(), w = view[1] - view[0];
        var dx = ev.shiftKey ? ev.deltaY || ev.deltaX : ev.deltaX;
        if (Math.abs(dx) > Math.abs(ev.shiftKey ? 0 : ev.deltaY)) {
          var sh = Math.max(-view[0], Math.min(end - view[1], dx / r.width * w));
          view = [view[0] + sh, view[1] + sh];
        } else {
          var f = Math.exp(ev.deltaY * 0.002), t = view[0] + (ev.clientX - r.left) / r.width * w;
          var nw = Math.max(Math.min(MIN_VIEW, end), Math.min(end, w * f));
          var lo = Math.max(0, Math.min(end - nw, t - (t - view[0]) * nw / w));
          view = [lo, lo + nw];
        }
        views[o.run] = view;
        layout(cur[0], cur[1]);
      }, { passive: false });

      // 拖：把手改一头、中间平移、别处新拉一段。没动（< 4px）就是点击：点在哪一段就选那个阶段
      function at(ev) {
        var r = bar.getBoundingClientRect();
        return Math.max(0, Math.min(end, view[0] + (ev.clientX - r.left) / r.width * (view[1] - view[0])));
      }
      bar.onpointerdown = function (ev) {
        if (ev.button !== 0) return;
        var h = ev.target.closest('.th'), x0 = ev.clientX, t0 = at(ev), a = cur[0], b = cur[1], moved = false;
        var mode = h ? (h.classList.contains('l') ? 'l' : 'r') : sel && ev.target.closest('.tsel') ? 'move' : 'new';
        cancel();
        bar.setPointerCapture(ev.pointerId);
        bar.onpointermove = function (e) {
          if (!o.canDrag || !moved && Math.abs(e.clientX - x0) < 4) return;
          moved = true;
          var t = at(e);
          if (mode === 'l') a = Math.min(t, cur[1]);
          else if (mode === 'r') b = Math.max(t, cur[0]);
          else if (mode === 'move') { var w = cur[1] - cur[0]; a = Math.max(0, Math.min(end - w, cur[0] + t - t0)); b = a + w; }
          else { a = Math.min(t0, t); b = Math.max(t0, t); }
          layout(a, b);
        };
        bar.onpointerup = bar.onpointercancel = function (e) {
          bar.onpointermove = bar.onpointerup = bar.onpointercancel = null;
          if (e.type === 'pointercancel') return layout(cur[0], cur[1]);
          if (moved) return commit(a, b);
          var under = segs.filter(function (s) { return s[1] <= t0 && t0 < s[2]; })[0];
          if (under && !h && names.indexOf(under[0]) >= 0) pick(under[0]);   // 点把手、没录到调用的阶段不算
        };
      };

      // 键盘：把手上左右键挪条上看得到的范围的 1%（Shift 10%），停下来半秒后提交。按键时不动 cur（提交不成
      // 还要画回它），也不往阶段上吸（一下 1% 可能比吸附的 4 像素还小，按了会像没按）；把手挪出条的视野时条跟着平移
      var kb = cur.slice();
      function follow(t) {
        var w = view[1] - view[0], m = w * 0.05, d = t < view[0] + m ? t - m - view[0] : t > view[1] - m ? t + m - view[1] : 0;
        d = Math.max(-view[0], Math.min(end - view[1], d));
        if (d) view = views[o.run] = [view[0] + d, view[1] + d];
      }
      [].forEach.call(box.querySelectorAll('.th'), function (h) {
        h.onkeydown = function (ev) {
          if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
          ev.preventDefault();
          var left = h.classList.contains('l'), w = view[1] - view[0];
          var d = (ev.key === 'ArrowLeft' ? -1 : 1) * w * (ev.shiftKey ? 0.1 : 0.01);
          if (left) kb[0] = Math.max(0, Math.min(kb[1] - w * 0.01, kb[0] + d));
          else kb[1] = Math.min(end, Math.max(kb[0] + w * 0.01, kb[1] + d));
          follow(kb[left ? 0 : 1]);
          layout(kb[0], kb[1]);
          cancel();
          pending = setTimeout(function () {
            pending = null;
            refocus = left ? 'l' : 'r';
            var r = self.snap(segs, kb[0], kb[1], end, 0, names);
            if (r !== ref) o.onSelect(r); else { refocus = null; layout(cur[0], cur[1]); }
          }, 500);
        };
      });
    }
  };
})(window.CS);
