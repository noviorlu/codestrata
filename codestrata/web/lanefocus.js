/* 默认收起、标记——分列里「看哪些列」和「描哪些节点」。
 *
 * 默认收起（CS.focus）：转一手的列（后端 lanedefault.py 的一句话规则给 default_lanes / default_folded）每个进程收成一窄列「其他 N 列」，
 *   连线照接。点窄列展开这个进程收起的列；工具栏一个小签：默认时「默认收起 N 列 · 全部显示」，展开过之后「回到默认」。不写进地址。
 * 标记（CS.mark）：标在装着这些文件 / 目录 / 函数的节点上，各列按自己的切面算，只描它这段时间里跑过的列（serve 的 /api/marklanes 给）；
 *   节点描边，一次最多 20 个，工具栏「标记 N 个 · 清掉」（用户 10-10 定）。模块图上（没有列）装着它就描。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  CS.focus = {
    all: false,                                     // 全部显示
    open: {},                                       // 展开了的进程 {pid: 1}

    /* 现在画哪些列：{列 id: 1}；全部画时 null */
    lanes: function (L) {
      L = L || CS.lanes.L;
      var d = L && L.default_lanes, open = this.open;
      if (!d || !d.length || this.all) return null;
      var out = {};
      d.forEach(function (id) { out[id] = 1; });
      L.lanes.forEach(function (ln) { if (open[ln.pid]) out[ln.id] = 1; });
      return Object.keys(out).length < L.lanes.length ? out : null;
    },
    hidden: function (id) { var f = this.lanes(); return !!f && !f[id]; },
    /* 展开过（全部显示，或者点开了某个进程） */
    changed: function () { return this.all || Object.keys(this.open).length > 0; },
    showAll: function () { this.all = true; this.redraw(); },
    clear: function () { this.all = false; this.open = {}; this.redraw(); },
    /* 点了「其他 N 列」：展开这个进程收起的列 */
    expand: function (pid) { this.open[pid] = 1; this.redraw(); },
    /* 默认收起的列为什么收（后端的 default_folded）；不是默认收起的是空串 */
    why: function (id) { var L = CS.lanes.L; return ((L && L.default_folded) || {})[id] || ''; },
    redraw: function () { CS.lanes.redrawKeep(); if (CS.app.edgeChips) CS.app.edgeChips(); },

    chip: function () {
      var L = CS.lanes.L, d = L && L.default_lanes;
      if (!L || !CS.app.lanesMode() || !d || !d.length) return '';
      if (this.changed())
        return '<button class="chip focus" data-focus="default" title="转一手的列（' + esc(Object.keys(L.default_folded || {}).length)
          + ' 列）重新每个进程收成一窄列">回到默认</button>';
      var n = L.lanes.length - d.length;
      return '<button class="chip focus" data-focus="all" title="转一手的列（收发 socket、轮询、线程池、这一段里几乎没调用的）默认每个进程收成一窄列'
        + '「其他 N 列」，线照连；点了全部显示">默认收起 ' + n + ' 列 · 全部显示</button>';
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
