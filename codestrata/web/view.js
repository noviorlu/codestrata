/* 视图描述：页面此刻在看什么，写在地址栏的 # 后面，刷新不丢、复制就能复现；命令行（codestrata view url、explain 24）说同一种话。
 *
 *   run    RUN@范围（同命令行的 REF；阶段写错时退回 run 默认的阶段并提示）
 *   lanes  只看这几列（选择器，lanefocus.js）          fold  收起的进程（别名）
 *   cut    共用的切面（展开着的目录；和默认一样就不写） lcut  各列自己的切面：列~目录,目录;列~…
 *   sel    选中的（稳定写法：n:列|节点、f:列|框、e:列|a|b、l:种类|通道|起列|终列；模块图上 n:节点、e:a|b）
 *   mark   标记的文件 / 目录 / 函数                    order  时间顺序开着（1）
 *   hide   藏起的边（hot / dyn）                        panel  详情栏讲请求路径（path）
 *   不认识的键原样留着。
 *
 * 入口：启动、hashchange（把地址粘进同一个标签页）、popstate（后退）都走 apply；用户在页面上改了什么，改的地方调 changed，
 * 100 ms 内的几次合成一次，用 replaceState 写规范的地址（不多出历史记录：后退一次回到上一个视图描述）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  var KEYS = ['run', 'lanes', 'fold', 'cut', 'lcut', 'sel', 'mark', 'order', 'hide', 'panel'];

  /* 地址里的值：只按 %XX 解（不把 + 当空格：阶段 + 秒的写法里有 +）；写回时 @ , / ~ | : ; + * = 留着原样，好读（@t= 不写成 @t%3D） */
  function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
  function enc(s) {
    return encodeURIComponent(s).replace(/%(40|2C|2F|7E|7C|3A|3B|2B|2A|3D)/g, function (m) { return decodeURIComponent(m); });
  }
  function list(s) { return (s || '').split(',').filter(Boolean); }

  CS.view = {
    applying: false,

    parse: function (hash) {
      var v = { run: null, lanes: [], fold: [], cut: null, lcut: {}, sel: null, mark: [], order: false, hide: [], panel: null, rest: [] };
      (hash || '').replace(/^#/, '').split('&').forEach(function (part) {
        if (!part) return;
        var i = part.indexOf('='), k = dec(i < 0 ? part : part.slice(0, i)), val = i < 0 ? '' : dec(part.slice(i + 1));
        if (k === 'run') v.run = val;
        else if (k === 'lanes' || k === 'fold' || k === 'mark' || k === 'hide') v[k] = list(val);
        else if (k === 'cut') v.cut = list(val);
        else if (k === 'lcut') val.split(';').forEach(function (x) {
          var j = x.indexOf('~'); if (j > 0) v.lcut[x.slice(0, j)] = list(x.slice(j + 1));
        });
        else if (k === 'sel') v.sel = val || null;
        else if (k === 'order') v.order = val === '1' || val === 'on';
        else if (k === 'panel') v.panel = val || null;
        else if (k !== 'view' && k !== 'cmp') v.rest.push(part);      // view / cmp：老的键，去掉
      });
      return v;
    },

    format: function (v) {
      var out = [];
      if (v.run) out.push('run=' + enc(v.run));
      if (v.lanes.length) out.push('lanes=' + enc(v.lanes.join(',')));
      if (v.fold.length) out.push('fold=' + enc(v.fold.join(',')));
      if (v.cut) out.push('cut=' + enc(v.cut.join(',')));
      var lc = Object.keys(v.lcut).sort().map(function (l) { return l + '~' + v.lcut[l].join(','); });
      if (lc.length) out.push('lcut=' + enc(lc.join(';')));
      if (v.sel) out.push('sel=' + enc(v.sel));
      if (v.mark.length) out.push('mark=' + enc(v.mark.join(',')));
      if (v.order) out.push('order=1');
      if (v.hide.length) out.push('hide=' + enc(v.hide.join(',')));
      if (v.panel) out.push('panel=' + enc(v.panel));
      return out.concat(v.rest || []).join('&');
    },

    /* 页面此刻的视图描述 */
    current: function () {
      var app = CS.app, d = app.data, lanes = CS.lanes, L = lanes.L, s = CS.graph.state, lm = app.lanesMode();
      var al = (L && L.aliases) || {}, v = this.parse('');
      v.run = CS.ds.run || null;
      if (lm) {
        v.lanes = CS.focus.sels.slice();
        v.fold = Object.keys(lanes.collapsed).filter(function (p) { return lanes.collapsed[p]; }).map(function (p) { return lanes.procAlias(p); }).sort();
        Object.keys(CS.laneCut.cuts).forEach(function (id) { v.lcut[al[id] || id] = CS.laneCut.cuts[id].slice().sort(); });
        v.sel = this.stableSel(lanes.sel);
      } else if (d) {
        v.sel = s.sel ? 'n:' + s.sel : s.selEdge ? 'e:' + s.selEdge : null;
      }
      if (d && d.open && d.open.slice().sort().join(',') !== (d.defaultOpen || []).slice().sort().join(',')) v.cut = d.open.slice().sort();
      v.mark = CS.mark.items.slice();
      v.order = !!s.timeOrder;
      if (s.hot === false) v.hide.push('hot');
      if (s.dyn === false) v.hide.push('dyn');
      v.panel = CS.path && CS.path.isOpen && CS.path.isOpen() ? 'path' : null;
      v.rest = this._rest || [];
      return v;
    },

    /* 页面内部的选中 key → 稳定写法（列 id 换成别名，连线下标换成 种类|通道|起列|终列） */
    stableSel: function (key) {
      var lanes = CS.lanes, L = lanes.L, al = (L && L.aliases) || {};
      if (!key || !L) return null;
      var t = key.slice(0, 2), rest = key.slice(2);
      if (t === 'l:') {
        var E = lanes.byKey[key];
        return E ? 'l:' + E.k.kind + '|' + E.k.via + '|' + (al[E.k.from.lane] || E.k.from.lane) + '|' + (al[E.k.to.lane] || E.k.to.lane) : null;
      }
      if (t !== 'n:' && t !== 'f:' && t !== 'e:') return null;
      var lane = Object.keys(lanes.laneIx || {}).filter(function (id) { return rest.indexOf(id + '|') === 0; })
        .sort(function (a, b) { return b.length - a.length; })[0];
      return lane ? t + (al[lane] || lane) + rest.slice(lane.length) : null;
    },

    /* 稳定写法 → 页面内部的 key（连线组取次数最多的那一条） */
    innerSel: function (sel) {
      var lanes = CS.lanes, L = lanes.L, al = (L && L.aliases) || {}, inv = {};
      if (!sel || !L) return null;
      Object.keys(al).forEach(function (id) { inv[al[id]] = id; });
      var t = sel.slice(0, 2), p = sel.slice(2).split('|');
      if (t === 'l:') {
        var hit = lanes.links.filter(function (E) {
          return E.k.kind === p[0] && E.k.via === p[1] && (al[E.k.from.lane] || E.k.from.lane) === p[2] && (al[E.k.to.lane] || E.k.to.lane) === p[3];
        }).sort(function (a, b) { return (b.n || 0) - (a.n || 0); })[0];
        return hit ? hit.key : null;
      }
      var lane = inv[p[0]] || p[0];
      return t + lane + '|' + p.slice(1).join('|');
    },

    /* 用户改了什么：100 ms 内合成一次，写规范的地址（套用途中不写） */
    changed: function () {
      if (this.applying || !CS.app.data) return;
      var self = this;
      clearTimeout(this._t);
      this._t = setTimeout(function () { self.write(); }, 100);
    },
    write: function () {
      if (this.applying || !CS.app.data) return;
      var h = this.format(this.current()), url = location.pathname + location.search + (h ? '#' + h : '');
      this._last = h;
      if (location.hash.replace(/^#/, '') !== h) history.replaceState(null, '', url);
    },

    /* 套用一个视图描述（启动、粘进来的地址、后退）。按固定的顺序：run 和范围 → 共用切面 → 各列切面 → 只看列 + 收起 →
       开关 → 标记 → 选中 → 详情栏；每一步等分列画好。返回 promise */
    apply: function (v, why) {
      var self = this, app = CS.app, lanes = CS.lanes, s = CS.graph.state;
      this.applying = true;
      this._rest = v.rest || [];
      var p = Promise.resolve(true);
      var want = v.run || '', id = want.split('@')[0], ph = want.indexOf('@') >= 0 ? want.slice(want.indexOf('@') + 1) : '';
      if (want !== (CS.ds.run || '')) {
        var hit = (app.runList || []).filter(function (x) { return x.id === id || x.case === id; })[0];
        if (want && !hit) { CS.viewer.toast('地址里的 run ' + id + ' 找不到了：照旧看现在的'); }
        else {
          if (hit && ph && ph.indexOf('t=') !== 0 && ph.indexOf('+') < 0
              && !(hit.phases || []).some(function (x) { return x.name === ph; })) {
            CS.viewer.toast('run ' + hit.id + ' 里没有阶段 ' + ph + '：看' + (app._defaultPhase(hit) ? ' ' + app._defaultPhase(hit) : '整个 run'));
            ph = app._defaultPhase(hit);
          }
          p = p.then(function () { return want ? app.selectRun(hit.id, ph) : app.selectRun('', ''); });
        }
      }
      return p.then(function () { return lanes.settled(); }).then(function () {
        var d = app.data;
        if (!d) return;
        var cut = v.cut || (d.defaultOpen || []);
        if (cut.slice().sort().join(',') !== d.open.slice().sort().join(',')) return app.setCut(cut.slice()).then(function () { return lanes.settled(); });
      }).then(function () {
        if (!app.lanesMode()) return;
        var al = (lanes.L && lanes.L.aliases) || {}, inv = {}, cuts = {};
        Object.keys(al).forEach(function (lid) { inv[al[lid]] = lid; });
        Object.keys(v.lcut).forEach(function (a) { if (inv[a]) cuts[inv[a]] = v.lcut[a]; });
        var same = JSON.stringify(cuts) === JSON.stringify(CS.laneCut.cuts);
        if (!same) { CS.laneCut.cuts = cuts; return lanes.show(); }
      }).then(function () {
        if (app.lanesMode() && lanes.L) {
          var procs = {}, pa = lanes.L.proc_aliases || {};
          Object.keys(pa).forEach(function (pid) { procs[pa[pid]] = pid; });
          lanes.collapsed = {};
          v.fold.forEach(function (a) { if (procs[a]) lanes.collapsed[procs[a]] = true; });
          CS.focus.set(v.lanes, true);
          var a = lanes._args;
          if (a) lanes.draw(a[0], a[1], a[2], a[3]);
        }
        // 开关
        s.timeOrder = !!v.order && app.canTimeOrder();
        s.hot = v.hide.indexOf('hot') < 0;
        s.dyn = v.hide.indexOf('dyn') < 0;
        app.repaint(); app.applyTimes();
        CS.mark.set(v.mark);
        // 选中
        if (v.sel) {
          if (app.lanesMode()) {
            var k = self.innerSel(v.sel), E = k && lanes.byKey[k];
            if (E) lanes.open(E, true);
            else if (k && (k.indexOf('n:') === 0 || k.indexOf('f:') === 0)) {
              var rest = k.slice(2), j = rest.lastIndexOf('|'), lane = rest.slice(0, j), node = rest.slice(j + 1);
              if (k.indexOf('f:') === 0) lanes.pickFrame(node, lane, true); else lanes.pickNode(node, lane, true);
            }
          } else if (v.sel.indexOf('n:') === 0) CS.graph.pick(v.sel.slice(2), true);
          else if (v.sel.indexOf('e:') === 0) { var ab = v.sel.slice(2).split('|'); CS.graph.pickEdge(ab[0], ab[1]); }
        } else if (why !== 'boot') CS.graph.clear();
        if (v.panel === 'path' && CS.path) CS.path.show();
        app.edgeChips(); app.controls(); app.cutBar();
      }).catch(function (e) {
        if (CS.viewer) CS.viewer.toast('套用地址里的视图出错：' + e.message);
      }).then(function () {
        self.applying = false;
        self.write();
      });
    },

    init: function () {
      var self = this;
      this._last = location.hash.replace(/^#/, '');
      function outside() {
        var h = location.hash.replace(/^#/, '');
        if (h === self._last || self.applying) return;       // 自己写的
        self._last = h;
        self.apply(self.parse(h), 'url');
      }
      window.addEventListener('hashchange', outside);
      window.addEventListener('popstate', outside);
    }
  };
})(window.CS);
