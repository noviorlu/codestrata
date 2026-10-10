/* 只看几列、标记——视图描述里的 lanes / mark 两个键在页面上的样子（view.js 读写它们）。
 *
 * 只看几列（CS.focus）：没选的列每个进程收成一窄列「其他 N 列」，连线照接（用户 10-09 定：信息不丢）；工具栏一个小签
 *   「只看 5 / 12 列 · 全部显示」随时退回。选择器和命令行同一套（laneid.py）：进程/线程、进程、带 * 的通配，不分大小写、按整段配。
 * 标记（CS.mark）：标在装着这些文件 / 目录 / 函数的节点上，各列按自己的切面算；节点描边，一次最多 20 个，
 *   工具栏「标记 N 个 · 清掉」（用户 10-10 定）。模块图上一样。 */
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

    /* 现在只看哪些列：{列 id: 1}；没设、或者一列都没配上就是 null（全部列） */
    lanes: function () {
      var L = CS.lanes.L, sels = this.sels;
      if (!sels.length || !L) return null;
      var al = L.aliases || {}, out = {}, n = 0;
      L.lanes.forEach(function (ln) {
        var a = al[ln.id] || ln.id;
        if (sels.some(function (s) { return matches(s, a, ln.id); })) { out[ln.id] = 1; n++; }
      });
      return n ? out : null;
    },
    hidden: function (id) { var f = this.lanes(); return !!f && !f[id]; },

    set: function (sels, quiet) {
      this.sels = (sels || []).filter(Boolean);
      if (!quiet) this.redraw();
    },
    clear: function () { this.set([]); },
    redraw: function () {
      var a = CS.lanes._args;
      if (a) CS.lanes.draw(a[0], a[1], a[2], a[3]);
      if (CS.app.lanesChanged) CS.app.lanesChanged();
    },

    /* 工具栏上的小签：只看 5 / 12 列 · 全部显示 */
    chip: function () {
      var L = CS.lanes.L, f = this.lanes();
      if (!f || !L || !CS.app.lanesMode()) return '';
      return '<button class="chip focus" data-focus="all" title="只看地址里 lanes= 选的列（' + esc(this.sels.join(', '))
        + '），别的列每个进程收成一窄列；点了全部显示">只看 ' + Object.keys(f).length + ' / ' + L.lanes.length + ' 列 · 全部显示</button>';
    }
  };

  var MAX = 20;
  CS.mark = {
    items: [],

    set: function (items, quiet) {
      var seen = {};
      this.items = (items || []).filter(function (x) { if (!x || seen[x]) return false; seen[x] = 1; return true; }).slice(0, MAX);
      if (!quiet) this.paint();
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

    /* 描边：分列里每一份、模块图上的节点。返回标上的个数 */
    paint: function () {
      var items = this.items, self = this, n = 0;
      function on(id) { return items.some(function (it) { return self.covers(id, it); }); }
      (CS.lanes.nodes || []).forEach(function (x) { var m = items.length > 0 && on(x.id); x.g.classList.toggle('mk', m); if (m) n++; });
      var gn = CS.graph.nodes || {};
      Object.keys(gn).forEach(function (id) { var m = items.length > 0 && on(id); gn[id].classList.toggle('mk', m); if (m) n++; });
      this.n = n;
      return n;
    },

    chip: function () {
      if (!this.items.length) return '';
      return '<button class="chip mark" data-mark="clear" title="标出了这些文件 / 目录 / 函数所在的节点：' + esc(this.items.join('、'))
        + '（各列按自己的切面算）；点了全部清掉">标记 ' + this.items.length + ' 个 · 清掉</button>';
    }
  };
})(window.CS);
