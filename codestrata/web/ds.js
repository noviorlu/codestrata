/* 数据访问层。整套前端只通过这一层拿数据：codestrata serve 的 api/*。地址都是相对的：页面可能
 * 不在根上（经主菜单转发时在 /v/<端口>/ 下，见 app.py） */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  function j(url, opt) {
    return fetch(url, opt).then(function (r) {
      if (!r.ok) {
        // 服务端的错误说明（「没有叫 X 的 run」「盘没挂上」）比状态码有用：有就用它
        return r.json().catch(function () { return {}; }).then(function (b) {
          var e = new Error(b && b.error ? b.error : url + ' → ' + r.status);
          e.status = r.status;
          throw e;
        });
      }
      return r.status === 204 ? null : r.json();
    });
  }

  CS.ds = {
    graph: function (open, w) {
      var q = [];
      if (open) q.push('open=' + encodeURIComponent(open.join(',')));
      if (w) q.push('w=' + Math.round(w));
      if (this.run) q.push('run=' + encodeURIComponent(this.run));
      return j('api/graph' + (q.length ? '?' + q.join('&') : ''));
    },
    // 当前叠在图上的 run（「完整 id@阶段」，空 = 只看静态图）。叠加相关的请求（图、边、引用）
    // 都带上它，app 只管改这一个值
    run: '',
    runs: function () { return j('api/runs'); },
    // 从主菜单（codestrata app）打开的：主菜单的地址（页面上放回去的链接）；直接 serve 的是 null
    home: function () { return j('api/app').then(function (r) { return r.home; }); },
    // 切面上每条边在当前 run（选的阶段）里第一次 / 最后一次被调用的时刻和次数：「时间顺序」上色
    seqEdges: function (open) {
      return j('api/seq/edges?run=' + encodeURIComponent(this.run) + (open ? '&open=' + encodeURIComponent(open.join(',')) : ''));
    },
    source: function (k) { return j('api/symbol/' + encodeURIComponent(k)); },
    file: function (f) { return j('api/file?f=' + encodeURIComponent(f)); },
    outline: function (f) { return j('api/outline?f=' + encodeURIComponent(f)); },
    edge: function (a, b) {
      return j('api/edge?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b)
               + (this.run ? '&run=' + encodeURIComponent(this.run) : ''));
    },
    refs: function (t) { return j('api/refs?t=' + encodeURIComponent(t) + (this.run ? '&run=' + encodeURIComponent(this.run) : '')); },
    searchIndex: function () { return j('api/search-index'); },
    reveal: function (node, open) {
      return j('api/reveal?node=' + encodeURIComponent(node) + '&open=' + encodeURIComponent(open.join(',')));
    },
    openEditor: function (f, l) {
      // 带 X-Codestrata 头：serve 只认我们自己的页面发的（别的网页触发不了本机编辑器）
      return fetch('api/open?f=' + encodeURIComponent(f) + '&l=' + l, { headers: { 'X-Codestrata': '1' } }).catch(function () {});
    }
  };
})(window.CS);
