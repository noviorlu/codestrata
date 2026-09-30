/* 数据访问层。整套前端只通过这一层拿数据，于是同一份 UI 能跑两种模式：
 *   live      —— codestrata serve：fetch api/*，可跳编辑器。地址都是相对的：页面可能
 *                不在根上（经主菜单转发时在 /v/<端口>/ 下，见 app.py）
 *   embedded  —— 单文件导出：读内嵌 JSON，只读、离线、可分享
 * 这和「总图 / hot 图」是同一个思路：一套渲染，换数据源。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  var EMB = window.CS_EMBEDDED || null;

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

  CS.ds = EMB ? {
    mode: 'embedded',
    // graph --public 导出的：主目录写成了 ~、PATH 里项目以外的目录省略成了 …（帮助里的复刻命令旁边会说明）
    public: !!EMB.public,
    canOpenEditor: false,
    // 和 /api/graph 同形：整份 payload。导出版只有导出时的那个切面，展开 / 收起要靠 serve
    graph: function (open) {
      var same = !open || open.slice().sort().join(',') === (EMB.open || []).slice().sort().join(',');
      if (!same) return Promise.reject(new Error('导出的单文件是固定的切面，不能展开 / 收起；要交互请用 codestrata serve'));
      // 导出时带了别的 run（graph --hot A --hot B）：换成它只换叠加的次数，边详情里的调用明细只有主 run 的
      var alt = this.run && EMB.hotBy && EMB.hotBy[this.run];
      // 在导出里选了「静态图」：不叠任何 run
      if (!this.run && EMB.hot && this.canSwitchRun)
        return Promise.resolve(Object.assign({}, EMB, { hot: null, hotMeta: null, graphHot: null, runtimeOnlyEdges: [], dynOnlyEdges: [] }));
      if (!alt) return Promise.resolve(EMB);
      return Promise.resolve(Object.assign({}, EMB, {
        hot: { packages: alt.packages, edges: alt.edges, dyn: alt.dyn || {}, symbols: {}, files: {}, unmapped: alt.unmapped },
        hotMeta: alt.meta, graphHot: null, runtimeOnlyEdges: alt.runtimeOnlyEdges, dynOnlyEdges: alt.dynOnlyEdges || [],
        _alt: true }));
    },
    canCut: false,
    run: '',
    // 导出版能换的只有导出时带上的那几个 run
    canSwitchRun: !!(EMB.hotBy && Object.keys(EMB.hotBy).length),
    runs: function () {
      var m = EMB.hotMeta;
      function row(m) {
        return { id: m.run_id, ref: m.run_id + (m.phase ? '@' + m.phase : ''), case: m.case, status: m.status,
                 problems: m.problems || [], created: m.created, tags: m.tags || [], note: m.note || '',
                 git: (m.git || {}).commit, loadable: true,
                 phases: Object.keys(m.phases || {}).map(function (k) { return { name: k, n_funcs: m.phases[k] }; }) };
      }
      var rows = m ? [row(m)] : [];
      Object.keys(EMB.hotBy || {}).forEach(function (k) { rows.push(row(EMB.hotBy[k].meta)); });
      return Promise.resolve({ default: m ? m.run_id + (m.phase ? '@' + m.phase : '') : null, runs: rows, embedded: true });
    },
    seqEdges: function () { return Promise.reject(new Error('导出版没有时序数据')); },
    source: function (k) { return Promise.resolve(withTargets((EMB.sources || {})[k] || null)); },
    file: function (f) { return Promise.resolve(withTargets((EMB.files || {})[f] || null)); },
    // 导出版只内嵌了一部分文件：跳过去之前先问一声，免得落到「没内嵌」的页面上回不来
    hasFile: function (f) { return !!(EMB.files || {})[f]; },
    // 导出版：内嵌了全文的文件带着完整大纲；没内嵌的返回 null，前端退回只列顶层符号
    outline: function (f) { var x = (EMB.files || {})[f]; return Promise.resolve(x ? { file: f, symbols: x.symbols } : null); },
    edge: function (a, b) { return Promise.resolve(edgeFrom(EMB.edges || {}, a, b, this)); },
    searchIndex: function () { return Promise.resolve(EMB.search || null); },
    reveal: function () { return Promise.reject(new Error('导出的单文件是固定切面')); },
    // 谁引用了这个定义：导出版没有全仓的引用表，只在内嵌了全文的文件里找
    refs: function (t) { return Promise.resolve(embeddedRefs(t)); },
    openEditor: function () { return Promise.resolve(); },
    home: function () { return Promise.resolve(null); }
  } : {
    mode: 'live',
    canOpenEditor: true,
    graph: function (open, w) {
      var q = [];
      if (open) q.push('open=' + encodeURIComponent(open.join(',')));
      if (w) q.push('w=' + Math.round(w));
      if (this.run) q.push('run=' + encodeURIComponent(this.run));
      return j('api/graph' + (q.length ? '?' + q.join('&') : ''));
    },
    canCut: true,
    // 当前叠在图上的 run（「完整 id@阶段」，空 = 只看静态图）。叠加相关的请求（图、边、引用）
    // 都带上它，app 只管改这一个值
    run: '',
    canSwitchRun: true,
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
    hasFile: function () { return true; },
    searchIndex: function () { return j('api/search-index'); },
    reveal: function (node, open) {
      return j('api/reveal?node=' + encodeURIComponent(node) + '&open=' + encodeURIComponent(open.join(',')));
    },
    openEditor: function (f, l) {
      // 带 X-Codestrata 头：serve 只认我们自己的页面发的（别的网页触发不了本机编辑器）
      return fetch('api/open?f=' + encodeURIComponent(f) + '&l=' + l, { headers: { 'X-Codestrata': '1' } }).catch(function () {});
    }
  };

  // 源码不内嵌、从 GitHub 取的导出（graph --link github，见 site.py）：换掉取源码、大纲、边、搜索、引用这几样
  if (EMB && EMB.link) Object.assign(CS.ds, linkedDs(EMB.link));

  // 边详情：导出时算好的那张表里取；换成了导出时带上的别的 run，它的调用明细没带，只留静态的部分并说清楚
  function edgeFrom(edges, a, b, ds) {
    var E = edges[a + '|' + b] || null;
    var isStatic = !ds.run && EMB.hot && ds.canSwitchRun;       // 选了「静态图」：边详情里也不该有调用次数
    if (!E || !(isStatic || (ds.run && EMB.hotBy && EMB.hotBy[ds.run]))) return E;
    var items = E.items.filter(function (x) { return x.n_uses; }).map(function (x) {
      return Object.assign({}, x, { runtime: [], calls: 0, status: 'static' }); });
    return Object.assign({}, E, { has_runtime: false, import_exec: 0,
      note: isStatic ? '现在只看静态图，这里只列静态引用'
        : '导出的单文件只带了第一个 run 的调用明细：这个 run 在图上的次数是对的，这里只列静态引用',
      items: items, counts: { confirmed: 0, dynamic: 0, static: items.length, import_only: (E.import_only || []).length, calls: 0 } });
  }

  var RANK = { 1: 0, 0: 1, 2: 2 }, KNAME = { 1: 'call', 0: 'ref', 2: 'import' };   // xref 的种类：调用在前

  function embeddedRefs(t) {
    var out = [], files = EMB.files || {}, counts = {}, T = EMB.xrefTargets || {}, ids = {};
    Object.keys(T).forEach(function (k) { if (T[k][0] === t) ids[k] = 1; });
    Object.keys(files).forEach(function (f) {
      var fv = files[f], x = fv.xref;
      if (!x) return;
      var byLine = {};
      x.toks.forEach(function (tk) {
        if (!ids[tk[3]] || tk[4] === 3) return;
        var k = KNAME[tk[4]], r = byLine[tk[0]];
        counts[k] = (counts[k] || 0) + 1;
        if (r) { r.n++; if (RANK[tk[4]] < RANK[r.k]) r.k = tk[4]; return; }       // 同一行的几处合成一条
        byLine[tk[0]] = { f: f, l: tk[0], c: tk[1], k: tk[4], n: 1, text: plain(fv.lines[tk[0] - 1]).trim().slice(0, 200) };
        out.push(byLine[tk[0]]);
      });
    });
    out.sort(function (a, b) { return RANK[a.k] - RANK[b.k] || (a.f < b.f ? -1 : a.f > b.f ? 1 : a.l - b.l); });
    var total = 0; Object.keys(counts).forEach(function (k) { total += counts[k]; });
    var wh = null; Object.keys(ids).some(function (k) { wh = T[k][1]; return !!wh; });
    var dfv = wh && files[wh[0]];
    return { target: t, where: wh, total: total, lines: out.length, counts: counts, refs: out, partial: true,
             def: wh ? { f: wh[0], l: wh[1], text: dfv ? plain(dfv.lines[wh[1] - 1]).trim().slice(0, 200) : '' } : null };
  }

  /* 链接模式：源码按扫描时的提交号从 GitHub 取（K.code 里的几个地址按顺序试），在浏览器里高亮（hl.js）；
     codestrata 算出来的放在 K.data（data/）下按需取：f/<序号>.json 每个文件的大纲和跳转、edges.json、
     search.json、refs/<桶>.json 引用倒排、attrs/<桶>.json「同名的 .xxx」、src/<序号>.txt 本地改过的文件 */
  function linkedDs(K) {
    var at = {}, local = {}, held = {}, stale = {}, symIdx = null, cj = {}, ct = {}, cf = {};
    var own = Object.prototype.hasOwnProperty;
    K.files.forEach(function (f, i) { at[f] = i; });
    (K.local || []).forEach(function (i) { local[i] = 1; });
    (K.unpublished || []).forEach(function (i) { held[i] = 1; });
    (K.stale || []).forEach(function (i) { stale[i] = 1; });
    var FILE = location.protocol === 'file:';            // 浏览器不许 file:// 页面按需取 data/
    function once(cache, key, make) {                    // 同一个请求只发一次；失败了下次重试
      if (!cache[key]) { cache[key] = make(); cache[key].catch(function () { delete cache[key]; }); }
      return cache[key];
    }
    // 同时最多 6 个请求、每个 20 秒超时：引用列表一次要取很多文件的原文，不能一下子打出去几百个
    var active = 0, queue = [];
    function get(u) {
      return new Promise(function (res, rej) { queue.push([u, res, rej]); pump(); });
    }
    function pump() { while (active < 6 && queue.length) start(queue.shift()); }
    function start(q) {
      var ac = window.AbortController ? new AbortController() : null;
      var tm = ac ? setTimeout(function () { ac.abort(); }, 20000) : 0;
      active++;
      function done() { active--; clearTimeout(tm); pump(); }
      fetch(q[0], ac ? { signal: ac.signal } : undefined).then(function (r) { done(); q[1](r); }, function (e) { done(); q[2](e); });
    }
    function ok(r) { if (!r.ok) { var e = new Error(r.url + ' → ' + r.status); e.status = r.status; throw e; } return r; }
    function dj(p) {
      return once(cj, p, function () {
        return fetch(K.data + p).then(ok).then(function (r) { return r.json(); }).catch(function (e) {
          throw new Error(FILE ? '链接模式的导出要放到 http(s) 上看：浏览器不许 file:// 的页面按需取数据（' + e.message + '）'
            : e.status === 404 ? '这个页面的数据已经换了一版（重新部署过）：刷新一下（' + e.message + '）' : e.message);
        });
      });
    }
    function url(tpl, f) {
      var path = ((K.prefix ? K.prefix + '/' : '') + f).split('/').map(encodeURIComponent).join('/');
      return tpl.replace('{owner}', K.owner).replace('{name}', K.name).replace('{sha}', K.sha).replace('{path}', path);
    }
    function text(f) {                                   // 源码原文
      return once(ct, f, function () {
        var i = at[f];
        if (held[i]) return Promise.reject(new Error('公开页没带这个文件：它被 .gitignore 忽略（可能是本地配置），只在本地有'));
        if (local[i]) return get(K.data + 'src/' + i + '.txt').then(ok).then(function (r) { return r.text(); });
        var errs = [];
        return K.code.reduce(function (pr, tpl) {
          return pr.catch(function () {
            return get(url(tpl, f)).then(ok).then(function (r) { return r.text(); })
              .catch(function (e) { errs.push(e.name === 'AbortError' ? url(tpl, f) + ' → 超时' : e.message); throw e; });
          });
        }, Promise.reject(null)).catch(function () {
          throw new Error('从 GitHub 取不到 ' + f + '（' + errs.join('；') + '）');
        });
      });
    }
    function fnv(str) {                                  // 32 位 FNV-1a（UTF-8），和 site.fnv1a 一致：算桶号
      var b = new TextEncoder().encode(str), h = 0x811c9dc5;
      for (var i = 0; i < b.length; i++) { h ^= b[i]; h = Math.imul(h, 0x01000193) >>> 0; }
      return h >>> 0;
    }
    function fname(x) { return typeof x === 'number' ? K.files[x] : x; }
    function isStale(f) { return own.call(at, f) && !!stale[at[f]]; }
    function symOf(k) {
      if (!symIdx) {
        symIdx = {};
        Object.keys(EMB.pkgSyms || {}).forEach(function (p) { EMB.pkgSyms[p].forEach(function (s) { symIdx[s.key] = s; }); });
      }
      return own.call(symIdx, k) ? symIdx[k] : null;
    }
    // 没有 hl.js（老浏览器解析不了它的正则、那段脚本整个没跑）：退回不高亮，其余照常
    function hlLines(t, lang) {
      if (CS.hl) return CS.hl.lines(t, lang);
      return t.split('\n').map(function (x) { return x.replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' }[c]; }); });
    }
    function fill(rows) {                                // 引用列表每行的原文：按行去取，取到一行填一行
      return Promise.all(rows.map(function (r) {
        if (r.text != null) return null;
        r.text = '';
        return text(r.f).then(function (t) { r.text = (t.split('\n')[r.l - 1] || '').trim().slice(0, 200); }, function () {});
      }));
    }
    var TEXTS = 200;                                     // 引用列表最多给多少行取原文（每个文件取一次）
    return {
      linked: true,
      hasFile: function (f) { return own.call(at, f); },
      blobUrl: function (f, l) { return url(K.blob, f) + (l ? '#L' + l : ''); },
      file: function (f) {
        if (!own.call(at, f)) return Promise.resolve(null);
        return once(cf, f, function () {
          var i = at[f];
          return dj('f/' + i + '.json').then(function (m) {
            if (m.file !== f) throw new Error('数据和页面对不上（' + m.file + ' ≠ ' + f + '）：刷新一下');
            if (held[i]) return Object.assign({}, m, { lines: [], unpublished: true, linked: true });
            return text(f).then(function (t) {
              var lines = hlLines(t, m.lang), fv = Object.assign({}, m, { lines: lines, linked: true });
              if (lines.length !== m.n_lines) {          // GitHub 上的内容和扫描时不一样：行列号对不上，不给跳转
                fv.mismatch = { scanned: m.n_lines, fetched: lines.length };
                fv.n_lines = lines.length;
                fv.xref = { stale: true, toks: [], targets: {} };
              }
              return fv;
            });
          });
        });
      },
      // 和 serve 的 /api/symbol 一样：从定义那一行起 40 行，跳转只留这几行里的。包的符号表里只有顶层的；
      // 方法、嵌套函数从文件大纲里找（给了 where 时）
      source: function (k, where) {
        var self = this, s = symOf(k);
        var find = s ? Promise.resolve(s) : !where || !own.call(at, where.f) ? Promise.resolve(null)
          : dj('f/' + at[where.f] + '.json').then(function (m) {
            var x = (m.symbols || []).filter(function (y) { return y.key === k; })[0];
            return x ? { f: where.f, l: x.l, n: x.n, b: [] } : { f: where.f, l: where.l, n: k.split('#').pop(), b: [] };
          });
        return find.then(function (s) {
          if (!s) return null;
          return self.file(s.f).then(function (fv) {
            if (!fv || fv.unpublished) return null;
            var a = Math.max(0, s.l - 1), x = fv.xref;
            return { key: k, name: s.n, file: s.f, line: s.l, bases: s.b || [], lang: fv.lang, lang_label: fv.lang_label,
                     lines: fv.lines.slice(a, a + 40),
                     xref: !x || x.stale ? x : { toks: x.toks.filter(function (t) { return t[0] > a && t[0] <= a + 40; }), targets: x.targets } };
          });
        });
      },
      outline: function (f) {
        if (!own.call(at, f)) return Promise.resolve(null);
        return dj('f/' + at[f] + '.json').then(function (m) { return { file: f, symbols: m.symbols }; });
      },
      edge: function (a, b) { var self = this; return dj('edges.json').then(function (E) { return edgeFrom(E, a, b, self); }); },
      searchIndex: function () { return dj('search.json'); },
      // 和 serve 的 /api/refs 同一份数据、同样的合并和排序。列表先给出来，每行原文从 GitHub 取、取到一批
      // 更新一次（r.more）：一个被一百多个文件用到的名字，不能等一百多个文件都下完才显示
      refs: function (t) {
        var self = this;
        if (!K.refBuckets) return Promise.resolve(null);
        return dj('refs/' + (fnv(t) % K.refBuckets) + '.json').then(function (B) {
          var e = own.call(B, t) ? B[t] : { w: null, r: [] }, counts = {}, merged = {}, rows = [];
          e.r.forEach(function (x) {
            var f = fname(x[0]), key = f + ':' + x[1], m = merged[key];
            counts[KNAME[x[3]]] = (counts[KNAME[x[3]]] || 0) + 1;
            if (!m) { merged[key] = { f: f, l: x[1], c: x[2], k: x[3], n: 1 }; rows.push(merged[key]); }
            else { m.n++; if (RANK[x[3]] < RANK[m.k]) { m.k = x[3]; m.c = x[2]; } }
          });
          rows.sort(function (a, b) { return RANK[a.k] - RANK[b.k] || (a.f < b.f ? -1 : a.f > b.f ? 1 : a.l - b.l); });
          rows.forEach(function (r) { if (isStale(r.f)) r.stale = true; });
          var total = 0; Object.keys(counts).forEach(function (k) { total += counts[k]; });
          // 目标是 s:<路径>#<限定名>、v:…、m:<路径>、x:点分路径（仓库外）
          var kind = t.split(':')[0], key = t.slice(kind.length + 1), sk = CS.ids.splitSym(key), qual = sk ? sk[1] : '';
          // 调用次数只在看的是主 run 时给（和边详情一样：选了「静态图」或换了别的 run 都不给）
          var mref = ((EMB.hotMeta || {}).run_id || '') + ((EMB.hotMeta || {}).phase ? '@' + EMB.hotMeta.phase : '');
          var main = self.run ? self.run === mref : !(EMB.hot && self.canSwitchRun);
          var res = { target: t, where: e.w, total: total, lines: rows.length, counts: counts, refs: rows.slice(0, 500),
                      calls: kind === 's' && main && EMB.hot && EMB.hot.symbols ? EMB.hot.symbols[key] || 0 : 0,
                      def: e.w ? { f: e.w[0], l: e.w[1], text: null, stale: isStale(e.w[0]) || undefined } : null };
          var jobs = [fill((res.def ? [res.def] : []).concat(res.refs.slice(0, TEXTS)))];
          var maybe = null;
          if ((kind === 's' || kind === 'v') && qual.indexOf('.') >= 0 && K.attrBuckets) {
            var name = CS.ids.tail(qual);
            maybe = dj('attrs/' + (fnv(name) % K.attrBuckets) + '.json').then(function (A) {
              var a = own.call(A, name) ? A[name] : { same: 0, r: [] }, mm = {}, mrows = [];
              a.r.forEach(function (x) {
                var f = fname(x[0]), k2 = f + ':' + x[1];
                if (!mm[k2]) { mm[k2] = { f: f, l: x[1], c: x[2], k: x[4], n: 1 }; mrows.push(mm[k2]); } else mm[k2].n++;
              });
              mrows.sort(function (a, b) { return b.k - a.k || (a.f < b.f ? -1 : a.f > b.f ? 1 : a.l - b.l); });
              mrows.forEach(function (r) { if (isStale(r.f)) r.stale = true; });
              res.maybe = { name: name, same: a.same, total: a.r.length, lines: mrows.length, refs: mrows.slice(0, 500) };
              jobs.push(fill(res.maybe.refs.slice(0, TEXTS)));
            }, function () {});                           // 「同名」这一组取不到不影响上面的引用
          }
          return (maybe || Promise.resolve()).then(function () {
            res.more = Promise.all(jobs).then(function () { return res; });
            return res;
          });
        });
      }
    };
  }

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
})(window.CS);
