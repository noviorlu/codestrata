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

    /* 画好之后（lanes.draw 末尾）：开 / 关「只亮链」——这一段里有链上的线才开（换了阶段、链不在这一段时不把整张图都淡掉）；
       走不出来时说一声（每条链说一次） */
    paint: function (L, svg) {
      var c = L && L.chain && L.chain.key === this.key ? L.chain : null;
      var has = !!c && !c.error && (L.links || []).some(function (k) { return !!k.chain; });
      this.info = c;
      this.absent = !!c && !c.error && !has;
      svg.classList.toggle('chainmode', has);
      document.body.classList.toggle('chainon', has);
      if (c && c.error && this.warned !== c.key) {
        this.warned = c.key;
        if (CS.viewer) CS.viewer.toast('地址里的链走不出来：' + c.error);
      }
    },

    /* 一条连线只装着链上的一跳时，那一跳（{i, kind, k, n, t_from, t_to…}）：标签、提示、详情写链上的那一次，不写整组的 */
    hop: function (k) {
      var hs = this.info && this.info.hops;
      return k.chain && k.chain.length === 1 && hs ? hs[k.chain[0]] : null;
    },
    /* 一条连线在链上：标签前面加「链 1、2」 */
    label: function (k) { return k.chain ? '链 ' + k.chain.map(function (i) { return i + 1; }).join('、') + ' · ' : ''; },
    /* 提示的第一行：链上的第几跳、录到的还是推出来的、第几次、什么时候（when：微秒 → 页面上的 +秒） */
    tip: function (k, when) {
      if (!k.chain) return '';
      var h = this.hop(k);
      return '链上的第 ' + k.chain.map(function (i) { return i + 1; }).join('、') + ' 跳：'
        + (k.inferred ? '推出来的（--link 按先后配，第 k 次配第 k 次）' : '录到的交接')
        + (h ? '，这一组的第 ' + h.k + ' / ' + h.n + ' 次，' + when(h.t_from) + ' → ' + when(h.t_to) : '') + '\n';
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
      var at = hs.length ? '链在 ' + (hs[0].t_from / 1e6).toFixed(3) + ' s → ' + (hs[hs.length - 1].t_to / 1e6).toFixed(3) + ' s（从 run 开头算）' : '';
      var title = c && c.error ? '这条链走不出来：' + c.error
        : this.absent ? '这一段里没有链上的线：' + at + '。换到那一段（或者打开链的 REF）就看得到'
        : '链：从 ' + ((c && c.start) || '') + ' 起 ' + hs.length + ' 跳' + (inf ? '，其中 ' + inf + ' 跳是推出来的（紫色虚线）' : '') + '；别的线淡下去了';
      return '<button class="chip chain" data-chain="clear" title="' + esc(title + '。点了清掉') + '">'
        + (c && c.error ? '链走不出来' : this.absent ? '链不在这一段' : '链 ' + hs.length + ' 跳' + (inf ? '（推断 ' + inf + '）' : '')) + ' · 清掉</button>';
    }
  };
})(window.CS);
