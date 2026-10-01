/* 详情面板：选中的节点（依赖、文件树、符号、源码片段）或箭头（这条依赖上实际调了哪些函数、次数、调用处）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var det, D;

  function short(id) {
    id = String(id);
    // 同一个切面上撞了名的（flask.app / flask.sansio.app）：数据里的 names 已经补过父目录段，和图上一致
    var r = CS.ids.isResidual(id), nm = (D && D.names) || {};
    var s = Object.prototype.hasOwnProperty.call(nm, id) ? nm[id] : CS.ids.last(id);
    return s + (r ? '/ 本层' : '');
  }
  /* 节点的完整显示名（vllm_omni.engine.core；本层文件写成 目录/ 本层）：标题用。id 是路径，放在悬停提示里 */
  function full(id) {
    id = String(id);
    var L = (D && D.labels) || {};
    return (Object.prototype.hasOwnProperty.call(L, id) ? L[id] : id) + (CS.ids.isResidual(id) ? '/ 本层' : '');
  }
  var KIND = { dir: '目录（整棵子树收成一个节点）', residual: '目录里直接放着的文件（不含子目录）', unit: '单个文件' };
  /* 符号键 codestrata/payload.py#Handler.do_GET → payload:Handler.do_GET（包的 __init__.py 写包名）；
     兜底键（文件:行、文件:<module>）写成 文件名:行 / 文件名 顶层 */
  function symLabel(k) {
    var sk = CS.ids.splitSym(k);
    if (sk) {
      var parts = sk[0].split('/'), stem = parts.pop().replace(/\.[^.]*$/, '');
      if (stem === '__init__' && parts.length) stem = parts.pop();
      return stem + ':' + sk[1];
    }
    var i = k.lastIndexOf(':'); if (i < 0) return k;
    var f = k.slice(0, i), q = k.slice(i + 1);
    return f.split('/').pop() + (q === '<module>' ? ' 顶层' : ':' + q);
  }
  function jump(d, text, cls) {
    return d ? '<button class="' + (cls || 'site') + '" data-view="' + esc(d.f) + '" data-line="' + d.l + '">'
      + esc(text) + '</button>' : '<span>' + esc(text) + '</span>';
  }

  /* 一小段代码：浏览器里有 hl.js 就高亮，没有就纯文本 */
  function code(lines) {
    if (!lines || !lines.length) return '';
    var t = lines.join('\n'), h = CS.hl ? CS.hl.lines(t, 'python') : null;
    return '<pre class="csnip"><code>' + (h ? h.join('\n') : esc(t)) + '</code></pre>';
  }
  function fname(f) { return f.split('/').pop(); }

  /* 调用方里没找到调它的那一行（sites 是空的）：为什么。payload 的 how 是怎么找的、form 是那种写法 */
  function via(c) {
    var f = esc(c.form || c.callee + '(…)');
    if (c.how === 'implicit') return f + ' 隐式调到它：看不出是调用方里的哪一行';
    // 按语法找也只认得出写在明面上的记号：说不准是哪种，两种可能都列出来
    if (c.how === 'syntax') return '调用方里没找到 ' + f + ' 这种写法：可能是仓库外的代码触发的（contextlib、sorted 之类），'
      + '也可能是没有记号的隐式触发（解包、当参数传进内置函数、容器里比较之类）';
    return '没直接写 ' + f + '：' + ({
      attr: '这个属性是经由 getattr、代理对象或仓库外的代码取的'
    }[c.how] || '是经由变量或别名（cls(…)）、__call__、装饰器、回调或仓库外的代码调到的');
  }

  /* 边详情的主体：每一对「谁调了谁」一张卡片——被调的函数、from（调用方里调它的那一行）、
     to（被调函数的签名）。按次数排。 */
  function callCards(E) {
    var pairs = [], by = {};
    E.items.forEach(function (x) {
      (x.runtime || []).forEach(function (r) {
        r.callers.forEach(function (c) {
          var k = r.sym + '|' + c.sym, P = by[k];
          if (!P) { P = by[k] = { r: r, c: c, n: 0, dyn: x.status === 'dynamic' }; pairs.push(P); }
          P.n += c.n;
          if (!P.c.sites && c.sites) P.c = c;
        });
      });
    });
    pairs.sort(function (p, q) { return q.n - p.n; });
    var MAX = 40;
    return { n: pairs.length, html: pairs.slice(0, MAX).map(function (P) {
      var r = P.r, c = P.c, q = r.sym.slice(r.sym.indexOf('#') + 1), parts = q.split('.');
      var site = c.sites && c.sites[0];
      var from = site ? jump(site, fname(site.f) + ':' + site.l) : jump(c.def, fname(c.def ? c.def.f : '') + ':' + (c.def ? c.def.l : ''));
      var more = site && c.sites.length > 1 ? c.sites.slice(1).map(function (t) { return jump(t, ':' + t.l); }).join('') : '';
      var cnt = '<span class="rt">×' + P.n + '</span>';
      return '<div class="call' + (P.dyn ? ' dyn' : '') + '">'
        + '<div class="ch">' + cnt + '<b>' + esc(parts.pop()) + '</b>'
        + (parts.length ? '<span class="cls">' + esc(parts.join('.')) + '</span>' : '')
        + (P.dyn ? '<span class="dtag" title="动态分派：调用方手里的对象要到运行时才知道是哪个类（self.model、注册表、getattr），'
            + '代码里没有 import 或引用这个类">动态</span>' : '') + '</div>'
        + '<div class="cs"><span class="lab">from</span>' + from + more
        + '<span class="who">' + esc(symLabel(c.sym)) + '</span></div>'
        + (site ? code([site.s]) : code(c.sig) + (c.sites ? '<div class="via">' + via(c) + '</div>' : ''))
        + '<div class="cs"><span class="lab">to</span>' + jump(r.def, r.def ? fname(r.def.f) + ':' + r.def.l : '（没找到定义）') + '</div>'
        + code(r.sig)
        + '</div>';
    }).join('') + (pairs.length > MAX ? '<p class="hint">…还有 ' + (pairs.length - MAX) + ' 对，调用次数更少</p>' : '') };
  }

  /* 引用了但没跑到（没有 runtime 数据时就是全部静态引用）：from 第一处引用，to 被引用的定义 */
  function refCards(items) {
    return items.map(function (x) {
      var u = x.uses[0];
      return '<div class="call ref">'
        + '<div class="ch"><b>' + esc(CS.ids.tail(x.name)) + '</b>'
        + (x.n_uses > 1 ? '<span class="cls">引用 ' + x.n_uses + ' 处</span>' : '') + '</div>'
        + (u ? '<div class="cs"><span class="lab">from</span>' + jump(u, fname(u.f) + ':' + u.l) + '</div>' + code(x.use_s ? [x.use_s] : null) : '')
        + '<div class="cs"><span class="lab">to</span>' + jump(x.def, x.def ? fname(x.def.f) + ':' + x.def.l : '（没找到定义）') + '</div>'
        + code(x.sig) + '</div>';
    }).join('');
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
    short: short,      // 节点的短名（撞名的用补过父目录段的别名，和图上一致）：抽屉标题也用它
    full: full,        // 节点的完整显示名
    _detTok: 0,                   // 面板每换一次内容加一：异步请求回来时据此判断还要不要画
    init: function (detEl, data) { det = detEl; D = data; this.reset(); },

    /* 展开 / 收起之后换一份切面数据 */
    setData: function (data) { D = data; },

    reset: function () {
      this._detTok++;
      delete det.dataset.pkg;
      det.innerHTML = '<p class="hint"><b>怎么读：</b>每条泳道是依赖的一层，箭头尽量从上指向下：'
        + '越上面越靠入口、越下面越是被调用的叶子；节点大小编码文件数。'
        + '点节点看它依赖谁、里面有什么符号；点箭头看这条依赖上实际调了哪些函数。</p>';
    },

    /* ---- 左：机器事实 ---- */
    showPkg: function (id, symKey) {
      this._detTok++;
      var v = (D.pkgs || {})[id] || {}, x = CS.graph.nb(id);
      // 静态 import 图里没有、只在 runtime 出现的依赖（按名字加载、注册表、鸭子类型）
      // 仅类型的（TYPE_CHECKING 里的 import）：图上默认不画，这里照样列出来
      var dyn = { i: [], o: [] }, typ = { i: [], o: [] };
      CS.graph.edges.forEach(function (E) {
        if (E.kind !== 'dyn') return;
        if (E.a === id) dyn.o.push(E.b); if (E.b === id) dyn.i.push(E.a);
      });
      (CS.graph.typeOnly || []).forEach(function (e) {
        if (e[0] === id) typ.o.push(e[1]); if (e[1] === id) typ.i.push(e[0]);
      });
      var list = (D.pkgSyms || {})[id] || [];
      var hot = CS.graph.hot, hits = (hot && hot.packages[id]) || 0;
      function pills(a, l, out, kind) {       // kind：图上没画出来的边（关着的仅类型）是哪种
        if (!a.length) return '';
        return '<div class="kv"><span>' + l + '</span>' + a.map(function (i) {
          var s = out ? id : i, t = out ? i : id, E = CS.graph.edgeInfo(s, t) || { kind: kind }, inf = E.info || {};
          var tone = E.hits ? ' warm' : '';
          var tag = E.kind === 'dyn' ? E.hits + ' 次'
                  : E.kind === 'type' ? '仅类型'
                  : (inf.uses ? inf.uses + ' 符号' : '只 import')
                    + (E.dynOnly ? ' · 动态分派 ' + E.hits + ' 次' : '');
          return '<span class="dep"><button class="chip" data-go="' + esc(i) + '">' + esc(short(i))
            + '</button><button class="eb2' + (inf.uses || E.kind === 'dyn' ? '' : ' imp') + tone
            + '" data-edge="' + esc(s + '|' + t) + '" title="看这条边具体用了什么">' + tag + ' ⇢</button></span>';
        }).join('') + '</div>';
      }
      det.dataset.pkg = id;
      det.innerHTML = '<h2 title="' + esc(id) + '">' + esc(full(id)) + '</h2>'
        + '<div class="sub">架构高度 ' + (v.alt >= 0 ? '+' : '') + (v.alt || 0).toFixed(2)
        + '　出 ' + (v.out || 0) + ' / 入 ' + (v.in || 0)
        + (hot ? ('　runtime ' + (hits ? hits + ' 次' : '未跑到')) : '') + '</div>'
        + '<div class="kv"><span>文件 <b>' + (v.files || 0) + '</b></span>'
        + '<span>行 <b>' + (v.loc || 0) + '</b></span>'
        + '<span>类 <b>' + (v.classes || 0) + '</b></span>'
        + '<span>函数（含方法）<b>' + (v.funcs || 0) + '</b></span></div>'
        + this._cutRow(id, v)
        + pills(x.o, '依赖 →', true) + pills(x.i, '← 被依赖', false)
        + pills(dyn.o, 'runtime 才出现 →', true) + pills(dyn.i, '← runtime 才出现', false)
        + pills(typ.o, '仅类型 →', true, 'type') + pills(typ.i, '← 仅类型', false, 'type')
        + this._docs(id)
        + '<div class="tree" id="tree"></div>'
        + '<div id="srcslot"></div>';
      this._wireDet(id);
      this._mountTree(id);
      if (symKey) this.showSource(id, symKey);
    },

    /* 详情里的节点刚被展开成了框：内容照旧，只把「展开」换成「收起」 */
    asFrame: function (id) {
      var row = det.querySelector('.cutrow');
      if (det.dataset.pkg !== id || !row) return;
      row.innerHTML = '<span class="kindtag">已在图上展开成框</span>'
        + '<button class="chip" title="框里的子模块合回一个节点">收起</button>';
      row.querySelector('button').onclick = function () { CS.app.collapseFrame(id); };
    },

    /* 这个节点在切面上是什么、能不能展开 / 收起 */
    _cutRow: function (id, v) {
      var h = '<div class="cutrow"><span class="kindtag">' + esc(KIND[v.kind] || '') + '</span>';
      if (v.expandable)
        h += '<button class="chip" data-cut="expand" title="在图上把它换成子模块">展开（' + v.fanout + ' 个子模块）</button>';
      if (v.collapsible)
        h += '<button class="chip" data-cut="collapse" title="连同框里的兄弟节点一起收回到上一级">收起到 '
          + esc(short(v.parent)) + '</button>';
      return h + '</div>';
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
     * 走 /api/outline（含方法），取不到就退回顶层符号。 */
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
      // hot 视图里默认只看调用到的文件和函数：点进一个模块，先看到的就是这次真正跑了哪些函数
      var hotF = (D.hot && D.hot.files) || {};
      var ran = files.some(function (f) { return hotF[f]; });
      var T = { id: id, files: files, byFile: byFile, pkg: id, onlyHot: ran };
      this._tree = T;
      box.innerHTML = '<div class="tree-tools"><input type="search" class="tree-q" placeholder="筛选文件 / 类 / 函数…">'
        + (ran ? '<button class="chip tree-hot" aria-pressed="true" title="只列这次 case 调用到的文件、类和函数">只看调用到的</button>' : '')
        + '<button class="linkbtn" data-tree="open">全部展开</button><button class="linkbtn" data-tree="close">全部折叠</button>'
        + '<span class="tree-sum"></span></div><div class="tree-body"></div>';
      var self = this, qEl = box.querySelector('.tree-q');
      qEl.oninput = function () { self._renderTree(this.value.trim().toLowerCase()); };
      var th = box.querySelector('.tree-hot');
      if (th) th.onclick = function () {
        T.onlyHot = !T.onlyHot; th.setAttribute('aria-pressed', String(T.onlyHot));
        self._renderTree(qEl.value.trim().toLowerCase());
      };
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
      var files = T.files.filter(function (f) { return match(f) && (!T.onlyHot || hotF[f]); });
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
      var openDirs = !!q || T.onlyHot || total.files <= 40, openFiles = !!q || total.files <= 3 || (T.onlyHot && total.files <= 6);
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
      box.querySelector('.tree-sum').textContent = files.length + (q || T.onlyHot ? ' / ' + T.files.length : '') + ' 个文件';
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
      return n._ready;
    },

    /* 从搜索栏过来：在当前模块的文件树里展开到这个文件（给了 key 就再展开到这个类 / 函数，
       在它下面放源码片段），标出来。返回标出来的那一行，调用方决定要不要滚过去 */
    focusIn: function (rel, key, line) {
      var self = this, box = document.getElementById('tree'), n = null, T0 = this._tree;
      // 要去的文件 / 函数这次没跑到：「只看调用到的」会把它藏起来，先关掉
      var hot0 = D.hot || {};
      if (T0 && T0.onlyHot && box && (!(hot0.files || {})[rel] || (key && !(hot0.symbols || {})[key]))) {
        T0.onlyHot = false;
        var th = box.querySelector('.tree-hot'); if (th) th.setAttribute('aria-pressed', 'false');
        var qe = box.querySelector('.tree-q'); this._renderTree(qe ? qe.value.trim().toLowerCase() : '');
      }
      [].forEach.call(box ? box.querySelectorAll('.tn.file') : [], function (x) { if (x.dataset.file === rel) n = x; });
      if (!n) {                                   // 这个模块的文件树里没有它（不该发生）：片段放在最下面
        if (key) this.showSource(this._tree && this._tree.pkg, key);
        return Promise.resolve(document.getElementById('srcslot'));
      }
      for (var p = n.parentNode; p && p !== box; p = p.parentNode)
        if (p.classList && p.classList.contains('dir')) p.classList.remove('closed');
      var ready = n.classList.contains('closed') ? this._toggleFile(n, '') : (n._ready || this._fillFile(n, ''));
      return Promise.resolve(ready).then(function () {
        var target = n.querySelector('.tr');
        if (key) {
          var b = null;
          [].forEach.call(n.querySelectorAll('[data-tsym]'), function (x) { if (x.dataset.tsym === key) b = x; });
          if (b) {
            // 方法：先把它所在的类展开
            var cls = b.parentNode.parentNode.parentNode.closest('.tn.sym');
            if (cls && cls.classList.contains('closed')) {
              cls.classList.remove('closed');
              var tg = cls.querySelector(':scope > .tr > .tg'); if (tg) tg.textContent = '▾';
            }
            var slot = b.parentNode.nextElementSibling;
            if (!slot.innerHTML) self.showSource(self._tree.pkg, key, slot);
            target = b.parentNode;
          } else {                                // 大纲里只有顶层和一层方法，更深的（嵌套函数）放在最下面
            self.showSource(self._tree.pkg, key);
            target = document.getElementById('srcslot') || target;   // 滚到片段那里，而不是文件那一行
          }
        }
        [].forEach.call(box.querySelectorAll('.tr.hit'), function (x) { x.classList.remove('hit'); });
        (target.classList.contains('tr') ? target : n.querySelector('.tr')).classList.add('hit');
        return target;
      });
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
        // 一个类跑了多少次：它自己加上它的方法。有方法被调到的类默认展开，被调到的名字标橙
        var hits = function (x) {
          return (hotS[x.key] || 0) + (kids[x.n] || []).reduce(function (a, m) { return a + (hotS[m.key] || 0); }, 0);
        };
        if (T.onlyHot) list = list.filter(function (x) { return hits(x) > 0; });
        if (q) {
          var hit = list.filter(function (x) { return x.n.toLowerCase().indexOf(q) !== -1; });
          if (hit.length) list = hit;
        }
        if (!list.length) { tc.innerHTML = '<div class="tr empty" style="--d:' + depth + '">（' + (T.onlyHot ? '这次没有调用到这里的类或函数' : '没有类或函数') + '）</div>'; return; }
        tc.innerHTML = list.map(function (x) {
          var ms = kids[x.n] || [], isC = x.k === 'class', hx = hits(x);
          var msHot = ms.filter(function (m) { return hotS[m.key]; });
          if (T.onlyHot) ms = msHot;
          var open = ms.length && msHot.length;
          return '<div class="tn sym' + (ms.length && !open ? ' closed' : '') + '">'
            + '<div class="tr' + (hx ? ' ran' : '') + '" style="--d:' + depth + '">'
            + (ms.length ? '<button class="tg" aria-label="展开方法">' + (open ? '▾' : '▸') + '</button>' : '<span class="tg sp"></span>')
            + '<span class="k' + (isC ? ' c' : '') + '">' + (isC ? 'C' : 'f') + '</span>'
            + '<button class="tn-name symname" data-tsym="' + esc(x.key) + '" data-f="' + esc(f) + '" data-l="' + x.l + '">' + esc(x.n) + '</button>'
            + '<span class="tn-meta">:' + x.l + (ms.length ? ' · ' + ms.length + (isC ? ' 个方法' : ' 个内部函数') + (T.onlyHot ? '被调到' : '') : '') + '</span>'
            + (hx ? '<span class="rt">' + hx + '</span>' : '') + '</div>'
            + '<div class="snip"></div>'
            + (ms.length ? '<div class="tc">' + ms.map(function (m) {
                var hm = hotS[m.key] || 0;
                return '<div class="tn sym"><div class="tr' + (hm ? ' ran' : '') + '" style="--d:' + (depth + 1) + '"><span class="tg sp"></span>'
                  + '<span class="k">' + (isC ? 'm' : 'f') + '</span><button class="tn-name symname" data-tsym="' + esc(m.key) + '" data-f="' + esc(f) + '" data-l="' + m.l + '">'
                  + esc(CS.ids.tail(m.n)) + '</button><span class="tn-meta">:' + m.l + '</span>'
                  + (hm ? '<span class="rt">' + hm + '</span>' : '') + '</div><div class="snip"></div></div>';
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
            self.showSource(T.pkg, b.dataset.tsym, slot);
          };
        });
      };
      tc.innerHTML = '<div class="tr empty" style="--d:' + depth + '">读取大纲…</div>';
      // 记下「大纲画好了」的 promise：搜索栏要在画好之后再定位到某个类 / 函数
      n._ready = CS.ds.outline(f).then(function (o) { draw(o && o.symbols && o.symbols.length ? o.symbols : null); },
                                       function () { draw(null); });
      return n._ready;
    },

    showSource: function (pkg, key, slotEl) {
      var slot = slotEl || document.getElementById('srcslot');
      if (!slot) return;
      slot.innerHTML = '<p class="hint" style="margin-top:10px">读取源码…</p>';
      var self = this;
      CS.ds.source(key).then(function (s) {
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
          + '<button data-open="' + esc(s.file) + '" data-line="' + s.line + '">编辑器打开</button>'
          + '<button data-view="' + esc(s.file) + '" data-line="' + s.line + '">整个文件</button>'
          + '</div><div class="srcscroll"><div class="srcgrid">'
          + '<div class="gut">' + g.join('\n') + '</div>'
          + '<pre class="code"><code>' + L.map(function (x, i) {
              return '<span class="cl" data-l="' + (s.line + i) + '">' + x + '</span>'; }).join('\n') + '</code></pre>'
          + '</div></div></div>';
        self._wireIn(slot);
        // 片段里也能 Ctrl+点击：跳到定义 / 列出引用（在全文窗口里打开）
        var code = slot.querySelector('pre.code');
        CS.xref.mark(code, s.xref, s.file, function (l) { return code.querySelector('.cl[data-l="' + l + '"]'); });
        code.addEventListener('click', function (ev) { CS.xref.click(ev); });
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
      [].forEach.call(det.querySelectorAll('[data-cut]'), function (b) {
        b.onclick = function () { CS.app[b.dataset.cut](pkg); };
      });
      [].forEach.call(det.querySelectorAll('[data-view]'), function (b) {
        b.onclick = function () { CS.viewer.open(b.dataset.view, b.dataset.line ? +b.dataset.line : 0); };
      });
    },

    /* ---- 左：一条边承载了什么 ---- */
    showEdge: function (a, b) {
      delete det.dataset.pkg;
      det.innerHTML = '<h2>' + esc(short(a)) + '<span class="arr">→</span>' + esc(short(b)) + '</h2>'
        + '<div class="sub">' + esc(full(a)) + ' → ' + esc(full(b)) + '</div><p class="hint">读取中…</p>';
      var self = this, tok = ++this._detTok;
      CS.ds.edge(a, b).then(function (E) {
        if (tok !== self._detTok) return;          // 这期间面板已经换了内容
        self._renderEdge(E);
      }).catch(function (e) { if (tok === self._detTok) det.querySelector('.hint').textContent = '读取失败：' + e.message; });
    },

    _renderEdge: function (E) {
      var c = E.counts, rt = E.has_runtime;
      // 「引用了，这次没跑到」
      var calls = callCards(E), stat = E.items.filter(function (x) { return x.status === 'static'; });
      var wired = E.items.filter(function (x) { return x.wiring; });
      // 两端之间只有 if TYPE_CHECKING: 里的 import：运行时不存在，不是依赖（图上的「仅类型」）
      var typeOnly = !E.static_edge && E.type_edge;
      var sub = rt ? 'runtime <b>' + c.calls + '</b> 次'
                     + ' · ' + calls.n + ' 对调用' + (E.static_edge ? '' : typeOnly ? ' · 只有 TYPE_CHECKING 里的 import' : ' · 没有 import')
                   : (E.note ? esc(E.note) : stat.length + ' 个被引用的符号 · 没有 runtime 数据');
      var h = '<h2>' + esc(short(E.a)) + '<span class="arr">→</span>' + esc(short(E.b)) + '</h2>'
        + '<div class="sub">' + sub
        + '<span class="dep" style="margin-left:10px"><button class="chip" data-go="' + esc(E.a) + '">' + esc(short(E.a))
        + '</button><button class="chip" data-go="' + esc(E.b) + '" style="border-radius:0 999px 999px 0">' + esc(short(E.b)) + '</button></span></div>';
      if (typeOnly && !calls.n)
        h += '<p class="hint">仅类型：只在 if TYPE_CHECKING: 里 import，给类型标注用，运行时不存在，不算依赖。import 语句在下面。</p>';
      else h += rt ? calls.html || '<p class="hint">这次运行没有跨这条边的调用</p>' : refCards(stat);
      // 次要的都折叠在下面；仅类型的边要看的就是 import 语句，那一栏直接展开
      function fold(title, n, body, open) {
        return n ? '<details class="efold"' + (open ? ' open' : '') + '><summary>' + esc(title) + '<span class="n">' + n + '</span></summary>'
          + body + '</details>' : '';
      }
      if (rt) h += fold('引用了，这次没跑到', stat.length, refCards(stat));
      h += fold('按名字登记', wired.length, wired.map(function (x) {
        return '<div class="call"><div class="ch"><b>' + esc(x.name) + '</b>'
          + (x.wiring.same_name > 1 ? '<span class="cls">仓库里有 ' + x.wiring.same_name + ' 个同名类</span>' : '') + '</div>'
          + x.wiring.refs.map(function (t) {
              return '<div class="cs">' + jump(t, fname(t.f) + ':' + t.l) + '</div>' + code([t.s]); }).join('') + '</div>';
      }).join(''));
      h += fold('只 import、没引用', E.import_only.length, deadSec(E));
      if (E.sites.length)
        h += fold('全部 import 语句', E.n_sites, E.sites.map(function (x) {
            return '<div class="cs">' + jump(x, fname(x.f) + ':' + x.l) + '</div>' + code([x.s]); }).join('')
          + (E.n_sites > E.sites.length ? '<p class="hint">…只列前 ' + E.sites.length + ' 条</p>' : ''), typeOnly && !calls.n);
      det.innerHTML = h;
      this._wireDet(E.a);
    }
  };
})(window.CS);
