/* 分列里高亮的一条链（视图描述的 chain 键：范围~起点~--link…，见 chainview.py；agent 用 links --follow 走出来、view set --chain 推过来）。
 * 后端按它在链自己的那一段里重走一遍：装着链上那次交接的连线带 chain（第几跳），推出来的 --link 那一跳多连一条（via link、inferred）。
 * 页面上：链上的线加粗、标「链 ①②」，推出来的画虚线、标「推断」；别的连线和边变淡（用户 10-10 定）。工具栏「链 N 跳 · 清掉」。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  CS.chain = {
    key: null,                     // chain 键的值；null 是没有高亮的链
    info: null,                    // 这一份数据里的链（/api/lanes 的 chain：hops、error）
    warned: null,

    /* /api/lanes 的参数 */
    query: function () { return this.key ? '&chain=' + encodeURIComponent(this.key) : ''; },

    /* 这一份分列数据是按哪条链取的（null：没带链） */
    drawnKey: function (L) { return (L && L.chain && L.chain.key) || null; },

    /* 画好之后（lanes.draw 末尾）：开 / 关「只亮链」，走不出来时说一声（每条链说一次） */
    paint: function (L, svg) {
      var c = L && L.chain && L.chain.key === this.key ? L.chain : null;
      this.info = c;
      svg.classList.toggle('chainmode', !!(c && !c.error));
      if (c && c.error && this.warned !== c.key) {
        this.warned = c.key;
        if (CS.viewer) CS.viewer.toast('地址里的链走不出来：' + c.error);
      }
    },

    /* 一条连线在链上：标签前面加「链 1、2」，提示里写第几跳、录到的还是推出来的 */
    label: function (k) { return k.chain ? '链 ' + k.chain.map(function (i) { return i + 1; }).join('、') + ' · ' : ''; },
    tip: function (k) {
      if (!k.chain) return '';
      return '链上的第 ' + k.chain.map(function (i) { return i + 1; }).join('、') + ' 跳：'
        + (k.inferred ? '推出来的（--link 按先后配，第 k 次配第 k 次）' : '录到的交接') + '\n';
    },

    set: function (key) { this.key = key || null; },

    /* 清掉：重取不带链的分列，写地址 */
    clear: function () {
      this.key = null;
      this.info = null;
      return CS.lanes.show().then(function () { if (CS.app.edgeChips) CS.app.edgeChips(); CS.view.changed('chain'); });
    },

    chip: function () {
      if (!this.key) return '';
      var c = this.info, hs = (c && c.hops) || [];
      var inf = hs.filter(function (h) { return h.kind === 'link'; }).length;
      var title = c && c.error ? '这条链走不出来：' + c.error : '链：从 ' + ((c && c.start) || '') + ' 起 ' + hs.length + ' 跳'
        + (inf ? '，其中 ' + inf + ' 跳是推出来的（虚线）' : '') + '；别的线淡下去了';
      return '<button class="chip chain" data-chain="clear" title="' + esc(title + '。点了清掉') + '">'
        + (c && c.error ? '链走不出来' : '链 ' + hs.length + ' 跳' + (inf ? '（推断 ' + inf + '）' : '')) + ' · 清掉</button>';
    }
  };
})(window.CS);
