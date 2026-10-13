/* 只看几列、标记——视图描述里的 lanes / mark 两个键在页面上的样子（view.js 读写它们）。
 *
 * 只看几列（CS.focus）：没选的列每个进程收成一窄列「其他 N 列」，连线照接（用户 10-09 定：信息不丢）；工具栏一个小签
 *   「只看 5 / 12 列 · 全部显示」随时退回。选择器和命令行同一套（laneid.py）：进程/线程、进程、带 * 的通配，不分大小写、按整段配。
 *   没写 lanes= 时按后端给的默认看（default_lanes，lanedefault.py；用户 10-10 定：转一手的列默认收起），小签写「默认只看」；
 *   「全部显示」这时写 lanes=*（不写就又是默认），小签留着写「全部 N 列 · 回到默认」；点「其他 N 列」只展开这个进程收起的列（用户 10-13 定）。
 * 标记（CS.mark）：标在装着这些文件 / 目录 / 函数的节点上，各列按自己的切面算，只描它这段时间里跑过的列（serve 的 /api/marklanes 给）；
 *   节点描边，一次最多 20 个，工具栏「标记 N 个 · 清掉」（用户 10-10 定）。模块图上（没有列）装着它就描。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function glob(pat, s) {
    var re = new RegExp('^' + pat.toLowerCase().replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*') + '$');
    return re.test(s.toLowerCase());
  }
  /* 一个选择器配不配这一列（列 id 是 pid:线程，alias 是 stage1/MainThread） */
  function matches(sel, alias, id) {
    if (sel.toLowerCase() === id.toLowerCase()) return true;
    var i = sel.indexOf('/'), a = alias.split('/');
    if (i < 0) return glob(sel, a[0]);
    return glob(sel.slice(0, i), a[0]) && glob(sel.slice(i + 1), a.slice(1).join('/'));
  }

  CS.focus = {
    sels: [],                                       // 视图里写的选择器（原样，写回地址用）

    /* 现在只看哪些列：{列 id: 1}；看全部列时 null——没写 lanes= 时按默认（没有要收的就是全部），写了但一列都没配上（missed）、
       或者配上了全部（lanes=*）。L：按哪一份分列认（缺省是画着的那份） */
    lanes: function (L) {
      L = L || CS.lanes.L;
      if (!L) return null;
      if (!this.sels.length) return this.byDefault(L);
      var m = this.match(L);
      return m.n && m.n < L.lanes.length ? m.out : null;
    },
    match: function (L) {
      var sels = this.sels, al = L.aliases || {}, out = {}, n = 0;
      L.lanes.forEach(function (ln) {
        var a = al[ln.id] || ln.id;
        if (sels.some(function (s) { return matches(s, a, ln.id); })) { out[ln.id] = 1; n++; }
      });
      return { out: out, n: n };
    },
    /* 默认看的列（后端算的 default_lanes）：没有要收的时 null */
    byDefault: function (L) {
      var d = L.default_lanes, out = {};
      if (!d || !d.length) return null;
      d.forEach(function (id) { out[id] = 1; });
      return out;
    },
    /* 写了 lanes= 但这一段里一列都没配上（画全部列，说一声） */
    missed: function (L) { return !!this.sels.length && !this.match(L).n; },
    hidden: function (id) { var f = this.lanes(); return !!f && !f[id]; },
    /* 全部显示：有默认收起的列时写 lanes=*，没有时清掉 */
    showAll: function () { this.set(CS.lanes.L && CS.lanes.L.default_lanes ? ['*'] : []); },
    /* 再多看这几列（点了「其他 N 列」：这个进程收起的列）：地址里写现在看的加上它们；加完是全部列时同「全部显示」 */
    expand: function (ids) {
      var L = CS.lanes.L, f = this.lanes();
      if (!L || !f) return;
      var want = {}, al = L.aliases || {};
      Object.keys(f).concat(ids).forEach(function (id) { want[id] = 1; });
      var keep = L.lanes.filter(function (ln) { return want[ln.id]; });
      if (keep.length >= L.lanes.length) this.showAll();
      else this.set(keep.map(function (ln) { return al[ln.id] || ln.id; }));
      if (CS.view) CS.view.changed('lanes');
    },
    /* 默认收起的列为什么收（后端的 default_folded）；不是默认收起的是空串 */
    why: function (id) { var L = CS.lanes.L; return ((L && L.default_folded) || {})[id] || ''; },

    set: function (sels, quiet) {
      this.sels = (sels || []).filter(Boolean);
      if (!quiet) this.redraw();
    },
    clear: function () { this.set([]); },
    redraw: function () {
      CS.lanes.redraw();
      if (CS.app.lanesChanged) CS.app.lanesChanged();
    },

    /* 工具栏上的小签：只看 5 / 12 列 · 全部显示（默认收起的：默认只看 8 / 19 列 · 全部显示；lanes=* 时：全部 19 列 · 回到默认） */
    chip: function () {
      var L = CS.lanes.L, f = this.lanes();
      if (!L || !CS.app.lanesMode()) return '';
      if (!f && this.sels.length && !this.missed(L) && L.default_lanes && L.default_lanes.length)
        return '<button class="chip focus" data-focus="default" title="地址里写了 lanes=*（或选的列配上了全部）：全部列都画着；'
          + '点了回到默认（转一手的列每个进程收成一窄列「其他 N 列」）">全部 ' + L.lanes.length + ' 列 · 回到默认</button>';
      if (!f) return '';
      if (!this.sels.length)
        return '<button class="chip focus" data-focus="all" title="转一手的列（收发 socket、只在轮询、线程池、这一段里没有调用的）默认每个进程收成一窄列'
          + '「其他 N 列」，线照连；点了全部显示（地址里写 lanes=*）">默认只看 ' + Object.keys(f).length + ' / ' + L.lanes.length + ' 列 · 全部显示</button>';
      return '<button class="chip focus" data-focus="all" title="只看地址里 lanes= 选的列（' + esc(this.sels.join(', '))
        + '），别的列每个进程收成一窄列；点了全部显示">只看 ' + Object.keys(f).length + ' / ' + L.lanes.length + ' 列 · 全部显示</button>';
    }
  };

  var MAX = 20;
  CS.mark = {
    items: [],
    where: null,                    // {东西: {列 id: 次数}}：它这段时间里跑过的列（serve 算的；按 run 和这几个东西取，换了就重取）
    whereKey: null,

    set: function (items, quiet) {
      var seen = {};
      this.items = (items || []).filter(function (x) { if (!x || seen[x]) return false; seen[x] = 1; return true; }).slice(0, MAX);
      if (!quiet) this.paint();
    },

    /* 分列里：取这几个东西跑过的列，到了再描一遍 */
    fetch: function (key) {
      var self = this;
      this.whereKey = key;
      this.where = null;
      CS.ds.markLanes(this.items).then(function (r) {
        if (self.whereKey !== key) return;          // 中间又换了 run / 标记
        self.where = r.lanes || {};
        self.paint();
      }, function () { if (self.whereKey === key) { self.where = {}; self.paint(); } });
    },
    clear: function () { this.set([]); if (CS.app.edgeChips) CS.app.edgeChips(); if (CS.view) CS.view.changed('mark'); },

    /* 节点 id（目录 x/、本层文件 x/*、单元 x.py）装不装着这一项（文件、目录 d/、函数 file#Q） */
    covers: function (node, item) {
      var file = item.split('#')[0];
      if (node === item || node === file) return true;
      if (/\/$/.test(item)) return node.indexOf(item) === 0 || item.indexOf(node) === 0 && /\/$/.test(node);
      if (CS.ids.isResidual(node)) return CS.ids.dirOf(file) === CS.ids.base(node);
      return /\/$/.test(node) && file.indexOf(node) === 0;
    },

    /* 描边：分列里每一份（只在它跑过的列里）、模块图上的节点。返回标上的个数 */
    paint: function () {
      var items = this.items, self = this, n = 0, lm = CS.app.lanesMode && CS.app.lanesMode();
      var key = (CS.ds.run || '') + '\n' + items.join(',');
      if (lm && items.length && this.whereKey !== key) this.fetch(key);
      var where = this.where || {};
      function on(id) { return items.some(function (it) { return self.covers(id, it); }); }
      function onLane(id, lane) { return items.some(function (it) { return self.covers(id, it) && !!(where[it] || {})[lane]; }); }
      (CS.lanes.nodes || []).forEach(function (x) { var m = items.length > 0 && onLane(x.id, x.lane); x.g.classList.toggle('mk', m); if (m) n++; });
      var gn = CS.graph.nodes || {};
      Object.keys(gn).forEach(function (id) { var m = items.length > 0 && on(id); gn[id].classList.toggle('mk', m); if (m) n++; });
      this.n = n;
      return n;
    },

    chip: function () {
      if (!this.items.length) return '';
      return '<button class="chip mark" data-mark="clear" title="标出了这些文件 / 目录 / 函数所在的节点：' + esc(this.items.join('、'))
        + '（只在它这段时间里跑过的列里，各列按自己的切面算）；点了全部清掉">标记 ' + this.items.length + ' 个 · 清掉</button>';
    }
  };
})(window.CS);
