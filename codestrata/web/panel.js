/* 详情面板（左：机器事实 + 源码）与解读面板（右：空槽 / 已写 / 过期）。
 * 「留给 llm agent 的空间」就是右边那块：没写时显示 task 输入包，
 * agent 从 PUT /api/notes 写回后这里立刻变成渲染好的解读。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var det, side, D, OVERVIEW = '_overview';

  function short(id) { return String(id).split('.').pop(); }
  /* 符号键 codestrata.payload:Handler.do_GET → payload:Handler.do_GET；兜底键（文件:行）原样显示 */
  function symLabel(k) {
    var i = k.indexOf(':'); if (i < 0) return k;
    var m = k.slice(0, i), q = k.slice(i + 1);
    if (m.indexOf('/') >= 0) return m.split('/').pop() + (q === '<module>' ? ' 顶层' : ':' + q);
    return short(m) + ':' + q;
  }
  function jump(d, text, cls) {
    return d ? '<button class="' + (cls || 'site') + '" data-view="' + esc(d.f) + '" data-line="' + d.l + '">'
      + esc(text) + '</button>' : '<span>' + esc(text) + '</span>';
  }

  function sec(title, items, why, E) {
    if (!items.length) return '';
    return '<div class="esec"><h4>' + esc(title) + '<span class="n">' + items.length + '</span></h4>'
      + '<p class="why">' + esc(why) + '</p>' + items.map(function (x) {
        var d = x.def, isC = d && d.k === 'class';
        var head = '<div class="eh"><span class="k' + (isC ? ' c' : '') + '">' + (isC ? 'C' : 'f') + '</span>'
          + jump(d, x.name, 'lk')
          + (d ? '<span class="loc">' + esc(d.f + ':' + d.l) + '</span>' : '<span class="loc">（没找到定义）</span>')
          + '<span class="cnt">' + (x.n_uses ? '引用 ' + x.n_uses + ' 处' : '') + '</span>'
          + (x.calls ? '<span class="rt">调用 ' + x.calls + '</span>' : '') + '</div>';
        var body = '';
        if (x.uses.length)
          body += '<div class="row"><span class="lab">在 ' + esc(short(E.a)) + ' 里：</span>'
            + x.uses.map(function (u) { return jump(u, u.f.split('/').pop() + ':' + u.l); }).join('')
            + (x.n_uses > x.uses.length ? '<span>…</span>' : '') + '</div>';
        x.runtime.forEach(function (r) {
          // 类被调用时，runtime 看到的是具体方法；把「哪个方法被谁调了几次」摊开
          var nm = r.sym === x.sym ? '直接调用' : r.sym.slice(r.sym.indexOf(':') + 1);
          body += '<div class="row"><span class="lab">runtime</span>'
            + (r.sym === x.sym ? '<span>' + esc(nm) + '</span>' : jump(r.def, nm))
            + '<span class="rt">×' + r.n + '</span><span class="lab">←</span>'
            + r.callers.map(function (c) { return jump(c.def, symLabel(c.sym)) + '<span class="lab">×' + c.n + '</span>'; }).join(' ')
            + '</div>';
        });
        return '<div class="ei ' + x.status + '">' + head + (body ? '<div class="eb">' + body + '</div>' : '') + '</div>';
      }).join('') + '</div>';
  }

  var WHY = {
    unused: ['没用到', '导入了但本文件从没引用——死 import，通常可以删。'],
    reexport: ['再导出', '写在 __init__.py 里，是给包外使用者的公开接口，本包自己不用。'],
    type: ['仅类型', '只在 TYPE_CHECKING 下导入，给类型标注用，运行时根本不存在。'],
    sideeffect: ['副作用', '导入即执行：要的是模块顶层代码（注册、打补丁），名字本身不用。'],
    intentional: ['故意保留', '标了 noqa: F401——作者明确说这个没用到的 import 是有意的。']
  };
  function deadSec(E) {
    var L = E.import_only;
    if (!L.length) return '';
    var by = {};
    L.forEach(function (x) { (by[x.why] = by[x.why] || []).push(x); });
    var h = '<div class="esec"><h4>只 import、没引用<span class="n">' + L.length + '</span></h4>'
      + '<p class="why">这些导入不承载任何调用。箭头上<b>不</b>应该算它们——除非它们是为了副作用。</p>';
    ['sideeffect', 'intentional', 'reexport', 'type', 'unused'].forEach(function (w) {
      (by[w] || []).forEach(function (x) {
        h += '<div class="ei import_only"><div class="eh"><span class="whytag ' + w + '">' + WHY[w][0] + '</span>'
          + '<span style="color:var(--ink)">' + esc(x.n) + '</span>'
          + jump(x, x.f.split('/').pop() + ':' + x.l)
          + (w === 'sideeffect' && E.has_runtime
             ? (x.module_ran ? '<span class="ran y">这次运行里它的顶层代码执行了</span>'
                             : '<span class="ran n">这次运行没执行到它</span>') : '')
          + '</div><div class="eb">' + esc(WHY[w][1]) + '</div></div>';
      });
    });
    return h + '</div>';
  }

  CS.panel = {
    init: function (detEl, sideEl, data) { det = detEl; side = sideEl; D = data; this.reset(); },

    reset: function () {
      det.innerHTML = '<p class="hint"><b>怎么读：</b>每条泳道是一段架构高度区间，'
        + '越上面越靠入口、越下面越是被依赖的叶子；节点大小编码文件数。'
        + '点节点看它依赖谁、里面有什么符号，右边是这个模块的<b>解读</b>。</p>';
      side.innerHTML = '<h3>解读层</h3><p class="hint">机器只能给出结构；'
        + '「为什么这样切、算法为什么这么写、该按什么顺序读」需要人或 agent 补。'
        + '点一个节点看它的解读状态。</p>';
      // 没选中任何东西时，右边放仓库总览——第一次打开页面最需要的就是它
      var self = this;
      CS.ds.note(OVERVIEW).then(function (nt) {
        if (nt && nt.present && !CS.graph.state.sel && !CS.graph.state.selEdge) self._renderNote(OVERVIEW, nt);
      }).catch(function () {});
    },

    /* ---- 左：机器事实 ---- */
    showPkg: function (id, symKey) {
      var v = (D.pkgs || {})[id] || {}, x = CS.graph.nb(id);
      // 静态 import 图里没有、只在 runtime 出现的依赖（按名字加载、注册表、鸭子类型）
      var dyn = { i: [], o: [] };
      CS.graph.edges.forEach(function (E) {
        if (E.kind !== 'dyn') return;
        if (E.a === id) dyn.o.push(E.b); if (E.b === id) dyn.i.push(E.a);
      });
      var list = (D.pkgSyms || {})[id] || [];
      var hot = CS.graph.hot, hits = (hot && hot.packages[id]) || 0;
      function pills(a, l, out) {
        if (!a.length) return '';
        return '<div class="kv"><span>' + l + '</span>' + a.map(function (i) {
          var s = out ? id : i, t = out ? i : id, E = CS.graph.edgeInfo(s, t) || {}, inf = E.info || {};
          var tag = E.kind === 'dyn' ? E.hits + ' 次' : (inf.uses ? inf.uses + ' 符号' : '只 import');
          return '<span class="dep"><button class="chip" data-go="' + esc(i) + '">' + esc(i.split('.').pop())
            + '</button><button class="eb2' + (inf.uses || E.kind === 'dyn' ? '' : ' imp') + (E.hits ? ' warm' : '')
            + '" data-edge="' + esc(s + '|' + t) + '" title="看这条边具体用了什么">' + tag + ' ⇢</button></span>';
        }).join('') + '</div>';
      }
      det.innerHTML = '<h2>' + esc(id) + '</h2>'
        + '<div class="sub">架构高度 ' + (v.alt >= 0 ? '+' : '') + (v.alt || 0).toFixed(2)
        + '　出 ' + (v.out || 0) + ' / 入 ' + (v.in || 0)
        + (hot ? ('　runtime ' + (hits ? hits + ' 次' : '未跑到')) : '') + '</div>'
        + '<div class="kv"><span>文件 <b>' + (v.files || 0) + '</b></span>'
        + '<span>行 <b>' + (v.loc || 0) + '</b></span>'
        + '<span>类 <b>' + (v.classes || 0) + '</b></span>'
        + '<span>函数（含方法）<b>' + (v.funcs || 0) + '</b></span></div>'
        + pills(x.o, '依赖 →', true) + pills(x.i, '← 被依赖', false)
        + pills(dyn.o, 'runtime 才出现 →', true) + pills(dyn.i, '← runtime 才出现', false)
        + this._docs(id)
        + '<div class="tree" id="tree"></div>'
        + '<div id="srcslot"></div>';
      this._wireDet(id);
      this._mountTree(id);
      if (symKey) this.showSource(id, symKey);
    },

    /* 作者写的文档：包内 README、frontmatter 声明了管这里的设计文档 */
    _docs: function (id) {
      var ds = (D.pkgDocs || {})[id] || [];
      if (!ds.length) return '';
      var K = { readme: 'README', primary: '设计', related: '相关', mentions: '提到' };
      return '<div class="kv files"><span>文档</span>' + ds.slice(0, 10).map(function (d) {
        return '<button class="filebtn" data-view="' + esc(d.f) + '" title="' + esc(d.f) + '">'
          + '<span class="fl lang-doc">' + K[d.kind] + '</span>' + esc(d.title) + '</button>';
      }).join('') + (ds.length > 10 ? '<span>…还有 ' + (ds.length - 10) + ' 份</span>' : '') + '</div>';
    },

    /* ---- 文件树：模块根目录 → 子目录（缩进）→ 文件 → 类 / 函数 → 方法 ----
     * 目录和文件一次性画出来（文件数是有限的），文件里的符号在展开时才取：
     * live 模式走 /api/outline（含方法），导出版用内嵌的全文大纲，都没有就退回顶层符号。 */
    _mountTree: function (id) {
      var box = document.getElementById('tree');
      if (!box) return;
      var ids = [id];
      var files = [], syms = [];
      ids.forEach(function (p) {
        files = files.concat((D.pkgFiles || {})[p] || []);
        syms = syms.concat((D.pkgSyms || {})[p] || []);
      });
      if (!files.length) { box.innerHTML = ''; return; }
      files.sort();
      var byFile = {};
      syms.forEach(function (x) { (byFile[x.f] = byFile[x.f] || []).push(x); });
      Object.keys(byFile).forEach(function (f) { byFile[f].sort(function (a, b) { return a.l - b.l; }); });
      var T = { id: id, files: files, byFile: byFile, pkg: id };
      this._tree = T;
      box.innerHTML = '<div class="tree-tools"><input type="search" class="tree-q" placeholder="筛选文件 / 类 / 函数…">'
        + '<button class="linkbtn" data-tree="open">全部展开</button><button class="linkbtn" data-tree="close">全部折叠</button>'
        + '<span class="tree-sum"></span></div><div class="tree-body"></div>';
      var self = this;
      box.querySelector('.tree-q').oninput = function () { self._renderTree(this.value.trim().toLowerCase()); };
      [].forEach.call(box.querySelectorAll('[data-tree]'), function (b) {
        b.onclick = function () {
          var open = b.dataset.tree === 'open';
          [].forEach.call(box.querySelectorAll('.tn.dir'), function (n) { n.classList.toggle('closed', !open); });
        };
      });
      this._renderTree('');
    },

    _renderTree: function (q) {
      var T = this._tree, box = document.getElementById('tree');
      if (!T || !box) return;
      var hotF = (D.hot && D.hot.files) || {}, hotS = (D.hot && D.hot.symbols) || {}, loc = D.fileLoc || {};
      var match = function (f) {
        if (!q) return true;
        if (f.toLowerCase().indexOf(q) !== -1) return true;
        return (T.byFile[f] || []).some(function (x) { return x.n.toLowerCase().indexOf(q) !== -1; });
      };
      var files = T.files.filter(match);
      // 目录树：以所有文件的最长公共目录为根
      var pre = null;
      files.forEach(function (f) {
        var d = f.split('/').slice(0, -1);
        if (pre === null) { pre = d; return; }
        var i = 0; while (i < pre.length && i < d.length && pre[i] === d[i]) i++;
        pre = pre.slice(0, i);
      });
      pre = pre || [];
      var root = { name: pre.join('/'), dirs: {}, files: [] };
      files.forEach(function (f) {
        var node = root;
        f.split('/').slice(pre.length, -1).forEach(function (seg) {
          node = node.dirs[seg] || (node.dirs[seg] = { name: seg, dirs: {}, files: [] });
        });
        node.files.push(f);
      });
      function agg(n) {
        var a = { files: n.files.length, loc: 0, cls: 0, fn: 0, hot: 0 };
        n.files.forEach(function (f) {
          a.loc += loc[f] || 0; a.hot += hotF[f] || 0;
          (T.byFile[f] || []).forEach(function (x) { if (x.k === 'class') a.cls++; else a.fn++; });
        });
        Object.keys(n.dirs).forEach(function (k) {
          var c = agg(n.dirs[k]);
          a.files += c.files; a.loc += c.loc; a.cls += c.cls; a.fn += c.fn; a.hot += c.hot;
        });
        n.agg = a;
        return a;
      }
      var total = agg(root);
      var kloc = function (n) { return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n); };
      var meta = function (a, isFile) {
        return (isFile ? '' : a.files + ' 文件 · ') + kloc(a.loc) + ' 行'
          + (a.cls ? ' · ' + a.cls + ' 类' : '') + (a.fn ? ' · ' + a.fn + ' 函数' : '');
      };
      var hotB = function (n) { return n ? '<span class="rt" title="这次 case 里的调用次数">' + n + '</span>' : ''; };
      var openDirs = !!q || total.files <= 40, openFiles = !!q || total.files <= 3;
      var LANG = { py: 'Py', pyi: 'Py', cu: 'CUDA', cuh: 'CUDA', c: 'C', cc: 'C++', cpp: 'C++', cxx: 'C++',
                   h: 'C++', hh: 'C++', hpp: 'C++', inl: 'C++', md: 'MD' };
      function fileRow(f, depth) {
        var ext = f.split('.').pop().toLowerCase(), a = { loc: loc[f] || 0, cls: 0, fn: 0 };
        (T.byFile[f] || []).forEach(function (x) { if (x.k === 'class') a.cls++; else a.fn++; });
        return '<div class="tn file' + (openFiles ? '' : ' closed') + '" data-file="' + esc(f) + '">'
          + '<div class="tr" style="--d:' + depth + '"><button class="tg" aria-label="展开">' + (openFiles ? '▾' : '▸') + '</button>'
          + '<span class="fl lang-' + (LANG[ext] || 'x').replace(/\W/g, '').toLowerCase() + '">' + (LANG[ext] || ext) + '</span>'
          + '<span class="tn-name">' + esc(f.split('/').pop()) + '</span>'
          + '<span class="tn-meta">' + meta(a, true) + '</span>' + hotB(hotF[f])
          + '<button class="linkbtn" data-view="' + esc(f) + '" title="打开整个文件">全文</button></div>'
          + '<div class="tc"></div></div>';
      }
      function dirHtml(n, depth, isRoot) {
        var h = '<div class="tn dir' + (isRoot || openDirs ? '' : ' closed') + '">'
          + '<div class="tr" style="--d:' + depth + '"><button class="tg" aria-label="展开">▾</button>'
          + '<span class="tn-name dirname">' + esc((isRoot ? (n.name || '.') : n.name) + '/') + '</span>'
          + '<span class="tn-meta">' + meta(n.agg) + '</span>' + hotB(n.agg.hot) + '</div><div class="tc">';
        Object.keys(n.dirs).sort().forEach(function (k) { h += dirHtml(n.dirs[k], depth + 1, false); });
        n.files.forEach(function (f) { h += fileRow(f, depth + 1); });
        return h + '</div></div>';
      }
      box.querySelector('.tree-sum').textContent = files.length + (q ? ' / ' + T.files.length : '') + ' 个文件';
      var body = box.querySelector('.tree-body');
      body.innerHTML = files.length ? dirHtml(root, 0, true) : '<p class="hint">没有匹配的文件或符号</p>';
      var self = this;
      [].forEach.call(body.querySelectorAll('.tn.dir > .tr'), function (r) {
        r.onclick = function () { r.parentNode.classList.toggle('closed'); };
      });
      [].forEach.call(body.querySelectorAll('.tn.file'), function (n) {
        var r = n.querySelector('.tr');
        r.onclick = function () { self._toggleFile(n, q); };
        if (!n.classList.contains('closed')) self._fillFile(n, q);
      });
      this._wireIn(body);
      // 目录行的三角形跟着折叠状态变
      [].forEach.call(body.querySelectorAll('.tn.dir'), function (n) {
        new MutationObserver(function () {
          n.querySelector('.tg').textContent = n.classList.contains('closed') ? '▸' : '▾';
        }).observe(n, { attributes: true, attributeFilter: ['class'] });
        n.querySelector('.tg').textContent = n.classList.contains('closed') ? '▸' : '▾';
      });
    },

    _toggleFile: function (n, q) {
      var closed = n.classList.toggle('closed');
      n.querySelector('.tg').textContent = closed ? '▸' : '▾';
      if (!closed && !n.dataset.filled) this._fillFile(n, q);
    },

    /* 展开一个文件：类（可再展开看方法）和函数，按行号排。点符号名在这一行下面展开源码片段 */
    _fillFile: function (n, q) {
      var T = this._tree, f = n.dataset.file, tc = n.querySelector('.tc'), self = this;
      var depth = +(n.querySelector('.tr').style.getPropertyValue('--d') || 0) + 1;
      var hotS = (D.hot && D.hot.symbols) || {};
      n.dataset.filled = '1';
      var top = T.byFile[f] || [];
      var draw = function (all) {
        // all：完整大纲（含方法）；拿不到就只有顶层
        var kids = {};
        (all || []).forEach(function (x) {
          var parts = x.n.split('.');
          if (parts.length === 2) (kids[parts[0]] = kids[parts[0]] || []).push(x);
        });
        var list = all ? all.filter(function (x) { return x.n.indexOf('.') === -1; }) : top;
        if (q) {
          var hit = list.filter(function (x) { return x.n.toLowerCase().indexOf(q) !== -1; });
          if (hit.length) list = hit;
        }
        if (!list.length) { tc.innerHTML = '<div class="tr empty" style="--d:' + depth + '">（没有类或函数）</div>'; return; }
        tc.innerHTML = list.map(function (x) {
          var ms = kids[x.n] || [], isC = x.k === 'class';
          return '<div class="tn sym' + (ms.length ? ' closed' : '') + '">'
            + '<div class="tr" style="--d:' + depth + '">'
            + (ms.length ? '<button class="tg" aria-label="展开方法">▸</button>' : '<span class="tg sp"></span>')
            + '<span class="k' + (isC ? ' c' : '') + '">' + (isC ? 'C' : 'f') + '</span>'
            + '<button class="tn-name symname" data-tsym="' + esc(x.key) + '" data-f="' + esc(f) + '" data-l="' + x.l + '">' + esc(x.n) + '</button>'
            + '<span class="tn-meta">:' + x.l + (ms.length ? ' · ' + ms.length + ' 方法' : '') + '</span>'
            + (hotS[x.key] ? '<span class="rt">' + hotS[x.key] + '</span>' : '') + '</div>'
            + '<div class="snip"></div>'
            + (ms.length ? '<div class="tc">' + ms.map(function (m) {
                return '<div class="tn sym"><div class="tr" style="--d:' + (depth + 1) + '"><span class="tg sp"></span>'
                  + '<span class="k">' + (isC ? 'm' : 'f') + '</span><button class="tn-name symname" data-tsym="' + esc(m.key) + '" data-f="' + esc(f) + '" data-l="' + m.l + '">'
                  + esc(m.n.split('.').pop()) + '</button><span class="tn-meta">:' + m.l + '</span>'
                  + (hotS[m.key] ? '<span class="rt">' + hotS[m.key] + '</span>' : '') + '</div><div class="snip"></div></div>';
              }).join('') + '</div>' : '')
            + '</div>';
        }).join('');
        [].forEach.call(tc.querySelectorAll('.tn.sym > .tr > .tg:not(.sp)'), function (b) {
          b.onclick = function (ev) {
            ev.stopPropagation();
            var c = b.parentNode.parentNode.classList.toggle('closed');
            b.textContent = c ? '▸' : '▾';
          };
        });
        [].forEach.call(tc.querySelectorAll('[data-tsym]'), function (b) {
          b.onclick = function (ev) {
            ev.stopPropagation();
            var slot = b.parentNode.nextElementSibling;
            if (slot.innerHTML) { slot.innerHTML = ''; return; }          // 再点一次收起
            self.showSource(T.pkg, b.dataset.tsym, slot, { f: b.dataset.f, l: +b.dataset.l });
          };
        });
      };
      tc.innerHTML = '<div class="tr empty" style="--d:' + depth + '">读取大纲…</div>';
      var lang = f.split('.').pop().toLowerCase();
      CS.ds.outline ? CS.ds.outline(f).then(function (o) { draw(o && o.symbols && o.symbols.length ? o.symbols : null); },
                                             function () { draw(null); }) : draw(null);
    },

    showSource: function (pkg, key, slotEl, where) {
      var slot = slotEl || document.getElementById('srcslot');
      if (!slot) return;
      slot.innerHTML = '<p class="hint" style="margin-top:10px">读取源码…</p>';
      var self = this;
      CS.ds.source(key).then(function (s) {
        if (!s) {
          // 导出版只内嵌了每个包前几个符号的片段；其他符号退回到全文窗口——前提是这个文件内嵌了
          if (!where) { slot.innerHTML = ''; return; }
          CS.ds.file(where.f).then(function (fv) {
            slot.innerHTML = '<p class="hint" style="margin:4px 0 6px">' + (fv
              ? '导出版里没有这个符号的片段。<button class="linkbtn" data-view="' + esc(where.f) + '" data-line="' + where.l + '">在全文里看（第 ' + where.l + ' 行）</button>'
              : '导出版的体积有上限，没带上这个文件。要看源码请用 <code>codestrata serve</code>。') + '</p>';
            self._wireIn(slot);
          });
          return;
        }
        var L = s.lines || [], g = [];
        for (var i = 0; i < L.length; i++) g.push(s.line + i);
        var hot = CS.graph.hot, h = (hot && hot.symbols[key]) || 0;
        slot.innerHTML = '<div class="srcbox"><div class="srchead">'
          + '<span class="p"><span class="langtag lang-' + esc(s.lang) + '">' + esc(s.lang_label || '') + '</span> '
          + '<b>' + esc(s.name) + '</b>　' + esc(s.file + ':' + s.line)
          + (s.bases && s.bases.length ? '　继承 ' + esc(s.bases.join(', ')) : '')
          + (h ? '　<span style="color:var(--hot)">runtime ' + h + ' 次</span>' : '')
          + '</span>'
          + '<button data-copy="' + esc(s.file + ':' + s.line) + '">复制路径</button>'
          + (CS.ds.canOpenEditor ? '<button data-open="' + esc(s.file) + '" data-line="' + s.line + '">编辑器打开</button>' : '')
          + '<button data-view="' + esc(s.file) + '" data-line="' + s.line + '">整个文件</button>'
          + '</div><div class="srcscroll"><div class="srcgrid">'
          + '<div class="gut">' + g.join('\n') + '</div>'
          + '<pre class="code"><code>' + L.join('\n') + '</code></pre>'
          + '</div></div></div>';
        self._wireIn(slot);
      }).catch(function () { slot.innerHTML = ''; });
    },

    /* 只给某个容器里的按钮绑事件（源码片段插在树里时用，免得把整个面板重绑一遍） */
    _wireIn: function (el) {
      [].forEach.call(el.querySelectorAll('[data-copy]'), function (b) {
        b.onclick = function () {
          if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function () {
            b.textContent = '已复制'; setTimeout(function () { b.textContent = '复制路径'; }, 1200); }, function () {});
        };
      });
      [].forEach.call(el.querySelectorAll('[data-open]'), function (b) {
        b.onclick = function () { CS.ds.openEditor(b.dataset.open, b.dataset.line); };
      });
      [].forEach.call(el.querySelectorAll('[data-view]'), function (b) {
        b.onclick = function (ev) { ev.stopPropagation(); CS.viewer.open(b.dataset.view, b.dataset.line ? +b.dataset.line : 0); };
      });
    },

    _wireDet: function (pkg) {
      var self = this;
      [].forEach.call(det.querySelectorAll('[data-go]'), function (b) {
        b.onclick = function () { CS.graph.pick(b.dataset.go); };
      });
      [].forEach.call(det.querySelectorAll('[data-sym]'), function (b) {
        b.onclick = function () { self.showSource(b.dataset.pkg, b.dataset.sym); };
      });
      [].forEach.call(det.querySelectorAll('[data-copy]'), function (b) {
        b.onclick = function () {
          if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(function () {
            b.textContent = '已复制'; setTimeout(function () { b.textContent = '复制路径'; }, 1200); }, function () {});
        };
      });
      [].forEach.call(det.querySelectorAll('[data-open]'), function (b) {
        b.onclick = function () { CS.ds.openEditor(b.dataset.open, b.dataset.line); };
      });
      [].forEach.call(det.querySelectorAll('[data-edge]'), function (b) {
        b.onclick = function () { var ab = b.dataset.edge.split('|'); CS.graph.pickEdge(ab[0], ab[1]); };
      });
      [].forEach.call(det.querySelectorAll('[data-view]'), function (b) {
        b.onclick = function () { CS.viewer.open(b.dataset.view, b.dataset.line ? +b.dataset.line : 0); };
      });
    },

    /* ---- 左：一条边承载了什么 ---- */
    showEdge: function (a, b) {
      det.innerHTML = '<h2>' + esc(short(a)) + '<span class="arr">→</span>' + esc(short(b)) + '</h2>'
        + '<div class="sub">' + esc(a) + ' → ' + esc(b) + '</div><p class="hint">读取中…</p>';
      var self = this;
      CS.ds.edge(a, b).then(function (E) {
        if (!E) { det.querySelector('.hint').textContent = '导出版里没有这条边的详情'; return; }
        self._renderEdge(E);
      }).catch(function (e) { det.querySelector('.hint').textContent = '读取失败：' + e.message; });
    },

    _renderEdge: function (E) {
      var c = E.counts, rt = E.has_runtime;
      var sub = (E.static_edge ? E.n_sites + ' 条 import 语句' : '静态 import 图里<b>没有</b>这条边')
        + (rt ? '　·　runtime 跨这条边调用 <b>' + c.calls + '</b> 次'
              : '　·　没有 runtime 数据：只能说「引用了」，不能说「调用了」')
        + (E.import_exec ? '<br>另有 ' + E.import_exec + ' 次是 import 触发的模块顶层执行，不算调用' : '')
        + (rt ? '<br><span class="lab">「调用方」是最近的仓库内的帧：中间经过仓库外的代码（比如 vLLM 内部）时，会显示成直接调用。</span>' : '');
      var pills = [];
      if (rt) {
        pills.push(['confirmed', '确认调用', c.confirmed]);
        if (c.dynamic) pills.push(['dynamic', '动态分派', c.dynamic]);
        pills.push(['static', '引用了没跑到', c.static]);
      } else pills.push(['static', '引用', c.static]);
      pills.push(['import_only', '只 import', c.import_only]);

      var groups = { confirmed: [], dynamic: [], static: [] };
      E.items.forEach(function (x) { groups[x.status].push(x); });
      var h = '<h2>' + esc(short(E.a)) + '<span class="arr">→</span>' + esc(short(E.b)) + '</h2>'
        + '<div class="sub">' + esc(E.a) + ' → ' + esc(E.b) + '</div>'
        + '<p class="hint" style="margin-bottom:9px">' + sub + '</p>'
        + '<div class="ecount">' + pills.map(function (p) {
            return '<span class="' + p[0] + (p[2] ? '' : ' z') + '">' + p[1] + '<b>' + p[2] + '</b></span>'; }).join('')
        + '<span class="dep" style="margin-left:auto"><button class="chip" data-go="' + esc(E.a) + '">'
        + esc(short(E.a)) + '</button><button class="chip" data-go="' + esc(E.b) + '" style="border-radius:0 999px 999px 0">'
        + esc(short(E.b)) + '</button></span></div>';

      h += sec('确认：引用了，这次也真的调到了', groups.confirmed,
               '代码里有静态引用，runtime 也走到了。这是这条边真正承载的调用。', E);
      h += sec('动态分派：调到了，但代码里看不到引用', groups.dynamic,
               '静态分析的盲区——经由 getattr、注册表、插件或基类方法走过来的调用。', E);
      h += sec(rt ? '引用了，但这次 case 没走到' : '静态引用', groups.static,
               rt ? '代码里写了，但记录的这次运行没有调用。可能是别的分支、错误处理，或只在别的 case 用到。'
                  : '代码里对 ' + short(E.b) + ' 的符号有引用。要知道会不会真的被调用，录一个 trace。', E);
      h += deadSec(E);
      if (E.sites.length)
        h += '<details class="esites"><summary>全部 import 语句（' + E.n_sites + '）</summary>'
          + E.sites.map(function (x) {
              return '<div class="ei"><button class="site" data-view="' + esc(x.f) + '" data-line="' + x.l + '">'
                + esc(x.f + ':' + x.l) + '</button><code class="src">' + esc(x.s) + '</code></div>';
            }).join('')
          + (E.n_sites > E.sites.length ? '<p class="hint">…只列前 ' + E.sites.length + ' 条</p>' : '')
          + '</details>';
      det.innerHTML = h;
      this._wireDet(E.a);
    },

    showEdgeSide: function (a, b) {
      side.innerHTML = '<h3>这条边的解读</h3>'
        + '<p class="hint">边本身不单独写解读：它为什么存在，由两端模块的解读回答'
        + '（「为什么这样切、和相邻模块的分界是什么」）。</p>'
        + '<div class="rowbtn"><button data-note="' + esc(a) + '">看 ' + esc(short(a)) + ' 的解读</button>'
        + '<button data-note="' + esc(b) + '">看 ' + esc(short(b)) + ' 的解读</button></div>';
      [].forEach.call(side.querySelectorAll('[data-note]'), function (x) {
        x.onclick = function () { CS.panel.showNote(x.dataset.note); };
      });
    },

    /* ---- 右：解读层 ---- */
    showNote: function (id) {
      side.innerHTML = '<h3>' + esc(id.split('.').pop()) + ' 的解读</h3>'
        + '<p class="hint">读取中…</p>';
      var self = this;
      CS.ds.note(id).then(function (nt) { self._renderNote(id, nt); })
                    .catch(function (e) { side.innerHTML = '<h3>解读</h3><p class="hint">读取失败：'
                      + esc(e.message) + '</p>'; });
    },

    _renderNote: function (id, nt) {
      var short = id === OVERVIEW ? '仓库总览' : id.split('.').pop();
      var tag = nt.present ? (nt.stale ? '<span class="tagpill stale">可能过期</span>'
                                       : '<span class="tagpill noted">已解读</span>')
                           : '<span class="tagpill">未解读</span>';
      var head = '<h3>' + esc(short) + (id === OVERVIEW ? ' ' : ' 的解读 ') + tag + '</h3>';
      var probs = (nt.problems || []);
      var check = probs.length ? '<div class="stalewarn">机器核对：这份解读里有 ' + probs.length
          + ' 处引用在代码里对不上<ul>' + probs.map(function (p) {
            return '<li><code>' + esc(p.text) + '</code> ' + esc(p.msg) + '</li>'; }).join('') + '</ul></div>'
        : (nt.present ? '<p class="checked">✓ 引用的文件行号和符号名都在代码里核对过</p>' : '');

      if (!nt.present) {
        side.innerHTML = head
          + '<div class="empty-slot">'
          + '<p class="why">这里是留给人 / LLM agent 的空槽。</p>'
          + '<p>机器能给出结构，给不出「为什么这样切、算法为什么这么写、该按什么顺序读」。</p>'
          + '<div class="rowbtn"><button class="primary" id="genpack">生成输入包</button></div>'
          + '<div class="taskbox" id="taskbox"></div>'
          + '</div>';
        document.getElementById('genpack').onclick = function () { CS.panel._pack(id); };
        return;
      }
      side.innerHTML = head
        + (nt.stale ? '<div class="stalewarn">这份解读写于代码的另一个版本'
            + '（哈希 ' + esc((nt.code_sha_note || '').slice(0, 8)) + ' → 现在 '
            + esc((nt.code_sha_now || '').slice(0, 8)) + '）。内容可能已经不准。</div>' : '')
        + check
        + '<div class="note">' + (nt.html || '') + '</div>'
        + '<div class="rowbtn">'
        + (nt.stale && CS.ds.canWrite ? '<button class="primary" id="genpack">重写：生成输入包</button>' : '')
        + (nt.meta && nt.meta.written_by ? '<span class="tagpill">' + esc(nt.meta.written_by) + '</span>' : '')
        + (nt.path ? '<span class="tagpill">' + esc(nt.path) + '</span>' : '')
        + '</div><div class="taskbox" id="taskbox"></div>';
      var g = document.getElementById('genpack');
      if (g) g.onclick = function () { CS.panel._pack(id); };
    },

    _pack: function (id) {
      var box = document.getElementById('taskbox');
      box.innerHTML = '<p class="hint">生成中…</p>';
      CS.ds.pack(id).then(function (txt) {
        box.innerHTML = '<textarea id="packta" readonly></textarea>'
          + '<div class="rowbtn"><button id="copypack">复制给 agent</button>'
          + (CS.ds.canWrite ? '<button id="writenote">粘贴解读并保存</button>' : '') + '</div>';
        document.getElementById('packta').value = txt;
        document.getElementById('copypack').onclick = function () {
          var b = this;
          if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () {
            b.textContent = '已复制'; setTimeout(function () { b.textContent = '复制给 agent'; }, 1400); }, function () {});
        };
        var w = document.getElementById('writenote');
        if (w) w.onclick = function () {
          box.innerHTML = '<textarea id="noteta" placeholder="把 agent 产出的 Markdown 粘进来…"></textarea>'
            + '<div class="rowbtn"><button class="primary" id="savenote">保存</button></div>';
          document.getElementById('savenote').onclick = function () {
            var md = document.getElementById('noteta').value.trim();
            if (!md) return;
            this.textContent = '保存中…';
            CS.ds.saveNote(id, md).then(function (nt) {
              CS.panel._renderNote(id, nt);
              if (CS.app && CS.app.refreshStatus) CS.app.refreshStatus();
            }).catch(function (e) { alert('保存失败：' + e.message); });
          };
        };
      }).catch(function (e) { box.innerHTML = '<p class="hint">生成失败：' + esc(e.message) + '</p>'; });
    }
  };
})(window.CS);
