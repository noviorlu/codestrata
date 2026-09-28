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
    source: function (k) { return Promise.resolve(withTargets((EMB.sources || {})[k] || null)); },
    file: function (f) { return Promise.resolve(withTargets((EMB.files || {})[f] || null)); },
    // 导出版只内嵌了一部分文件：跳过去之前先问一声，免得落到「没内嵌」的页面上回不来
    hasFile: function (f) { return !!(EMB.files || {})[f]; },
    // 导出版：内嵌了全文的文件带着完整大纲；没内嵌的返回 null，前端退回只列顶层符号
    outline: function (f) { var x = (EMB.files || {})[f]; return Promise.resolve(x ? { file: f, symbols: x.symbols } : null); },
    edge: function (a, b) { return Promise.resolve((EMB.edges || {})[a + '|' + b] || null); },
    searchIndex: function () { return Promise.resolve(EMB.search || null); },
    reveal: function () { return Promise.reject(new Error('导出的单文件是固定切面')); },
    // 谁引用了这个定义：导出版没有全仓的引用表，只在内嵌了全文的文件里找
    refs: function (t) {
      var out = [], files = EMB.files || {}, rank = { 1: 0, 0: 1, 2: 2 }, counts = {}, T = EMB.xrefTargets || {}, ids = {};
      Object.keys(T).forEach(function (k) { if (T[k][0] === t) ids[k] = 1; });
      Object.keys(files).forEach(function (f) {
        var fv = files[f], x = fv.xref;
        if (!x) return;
        var byLine = {};
        x.toks.forEach(function (tk) {
          if (!ids[tk[3]] || tk[4] === 3) return;
          var k = { 1: 'call', 0: 'ref', 2: 'import' }[tk[4]], r = byLine[tk[0]];
          counts[k] = (counts[k] || 0) + 1;
          if (r) { r.n++; if (rank[tk[4]] < rank[r.k]) r.k = tk[4]; return; }       // 同一行的几处合成一条
          byLine[tk[0]] = { f: f, l: tk[0], c: tk[1], k: tk[4], n: 1, text: plain(fv.lines[tk[0] - 1]).trim().slice(0, 200) };
          out.push(byLine[tk[0]]);
        });
      });
      out.sort(function (a, b) { return rank[a.k] - rank[b.k] || (a.f < b.f ? -1 : a.f > b.f ? 1 : a.l - b.l); });
      var total = 0; Object.keys(counts).forEach(function (k) { total += counts[k]; });
      var wh = null; Object.keys(ids).some(function (k) { wh = T[k][1]; return !!wh; });
      var dfv = wh && files[wh[0]];
      return Promise.resolve({ target: t, where: wh, total: total, lines: out.length, counts: counts, refs: out, partial: true,
                               def: wh ? { f: wh[0], l: wh[1], text: dfv ? plain(dfv.lines[wh[1] - 1]).trim().slice(0, 200) : '' } : null });
    },
    openEditor: function () { return Promise.resolve(); }
  } : {
    mode: 'live',
    canWrite: true,
    canOpenEditor: true,
    graph: function (open, w) {
      var q = [];
      if (open) q.push('open=' + encodeURIComponent(open.join(',')));
      if (w) q.push('w=' + Math.round(w));
      return j('/api/graph' + (q.length ? '?' + q.join('&') : ''));
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
    refs: function (t) { return j('/api/refs?t=' + encodeURIComponent(t)); },
    hasFile: function () { return true; },
    searchIndex: function () { return j('/api/search-index'); },
    reveal: function (node, open) {
      return j('/api/reveal?node=' + encodeURIComponent(node) + '&open=' + encodeURIComponent(open.join(',')));
    },
    openEditor: function (f, l) {
      return fetch('/api/open?f=' + encodeURIComponent(f) + '&l=' + l).catch(function () {});
    }
  };

  // 导出版的 xref 只带 token，目标在共用表 EMB.xrefTargets 里：取出来时把用到的补上（前端其余部分照旧）
  function withTargets(v) {
    var x = v && v.xref, T = EMB.xrefTargets || {};
    if (x && !x.targets) {
      x.targets = {};
      (x.toks || []).forEach(function (t) { if (T[t[3]]) x.targets[t[3]] = T[t[3]]; });
    }
    return v;
  }

  // 高亮好的一行 HTML → 纯文本（导出版的引用列表要显示那一行）
  function plain(h) {
    return String(h || '').replace(/<[^>]*>/g, '').replace(/&(lt|gt|quot|#x27|#39|amp);/g, function (m, e) {
      return { lt: '<', gt: '>', quot: '"', '#x27': "'", '#39': "'", amp: '&' }[e]; });
  }

  function blank(t) {
    return { target: t, present: false, stale: false, html: '', md: '', meta: {} };
  }
  CS.blankNote = blank;
})(window.CS);
