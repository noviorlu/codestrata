/* 数据访问层。整套前端只通过这一层拿数据，于是同一份 UI 能跑两种模式：
 *   live      —— codestrata serve：fetch /api/*，可写解读、可跳编辑器
 *   embedded  —— 单文件导出：读内嵌 JSON，只读、离线、可分享
 * 这和「总图 / hot 图」是同一个思路：一套渲染，换数据源。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var EMB = window.CS_EMBEDDED || null;

  function j(url, opt) {
    return fetch(url, opt).then(function (r) {
      if (!r.ok) throw new Error(url + ' → ' + r.status);
      return r.status === 204 ? null : r.json();
    });
  }

  CS.ds = EMB ? {
    mode: 'embedded',
    canWrite: false,
    canOpenEditor: false,
    // 和 /api/graph 同形：整份 payload。导出版只有导出时的那个切面，展开 / 收起要靠 serve
    graph: function (open) {
      var same = !open || open.slice().sort().join(',') === (EMB.open || []).slice().sort().join(',');
      return same ? Promise.resolve(EMB)
                  : Promise.reject(new Error('导出的单文件是固定的切面，不能展开 / 收起；要交互请用 codestrata serve'));
    },
    canCut: false,
    note: function (t) { return Promise.resolve((EMB.notes || {})[t] || blank(t)); },
    status: function (ids) {
      var out = {};
      ids.forEach(function (t) { var nt = (EMB.notes || {})[t]; out[t] = !nt || !nt.present ? 'todo' : (nt.stale ? 'stale' : 'noted'); });
      return Promise.resolve(out);
    },
    saveNote: function () { return Promise.reject(new Error('导出的单文件是只读的')); },
    tasks: function () { return Promise.resolve(EMB.tasks || []); },
    pack: function (t) { return Promise.resolve((EMB.packs || {})[t] || ''); },
    source: function (k) { return Promise.resolve((EMB.sources || {})[k] || null); },
    file: function (f) { return Promise.resolve((EMB.files || {})[f] || null); },
    // 导出版：内嵌了全文的文件带着完整大纲；没内嵌的返回 null，前端退回只列顶层符号
    outline: function (f) { var x = (EMB.files || {})[f]; return Promise.resolve(x ? { file: f, symbols: x.symbols } : null); },
    edge: function (a, b) { return Promise.resolve((EMB.edges || {})[a + '|' + b] || null); },
    openEditor: function () { return Promise.resolve(); }
  } : {
    mode: 'live',
    canWrite: true,
    canOpenEditor: true,
    graph: function (open) {
      return j('/api/graph' + (open ? '?open=' + encodeURIComponent(open.join(',')) : ''));
    },
    canCut: true,
    note: function (t) { return j('/api/notes/' + encodeURIComponent(t)); },
    // 一批节点的解读状态（noted / stale / todo），不核对内容，给图上的徽标用
    status: function (ids) { return j('/api/status?ids=' + encodeURIComponent(ids.join(','))); },
    saveNote: function (t, md) {
      return j('/api/notes/' + encodeURIComponent(t),
        { method: 'PUT', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ md: md }) });
    },
    tasks: function () { return j('/api/tasks'); },
    pack: function (t) {
      return fetch('/api/pack/' + encodeURIComponent(t)).then(function (r) { return r.text(); });
    },
    source: function (k) { return j('/api/symbol/' + encodeURIComponent(k)); },
    file: function (f) { return j('/api/file?f=' + encodeURIComponent(f)); },
    outline: function (f) { return j('/api/outline?f=' + encodeURIComponent(f)); },
    edge: function (a, b) { return j('/api/edge?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b)); },
    openEditor: function (f, l) {
      return fetch('/api/open?f=' + encodeURIComponent(f) + '&l=' + l).catch(function () {});
    }
  };

  function blank(t) {
    return { target: t, present: false, stale: false, html: '', md: '', meta: {} };
  }
  CS.blankNote = blank;
})(window.CS);
