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
    graph: function () { return Promise.resolve(EMB.graph); },
    note: function (t) { return Promise.resolve((EMB.notes || {})[t] || blank(t)); },
    saveNote: function () { return Promise.reject(new Error('导出的单文件是只读的')); },
    tasks: function () { return Promise.resolve(EMB.tasks || []); },
    pack: function (t) { return Promise.resolve((EMB.packs || {})[t] || ''); },
    source: function (k) { return Promise.resolve((EMB.sources || {})[k] || null); },
    openEditor: function () { return Promise.resolve(); }
  } : {
    mode: 'live',
    canWrite: true,
    canOpenEditor: true,
    graph: function () { return j('/api/graph'); },
    note: function (t) { return j('/api/notes/' + encodeURIComponent(t)); },
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
    openEditor: function (f, l) {
      return fetch('/api/open?f=' + encodeURIComponent(f) + '&l=' + l).catch(function () {});
    }
  };

  function blank(t) {
    return { target: t, present: false, stale: false, html: '', md: '', meta: {} };
  }
  CS.blankNote = blank;
})(window.CS);
