/* 详情面板：选中的节点（调用谁 / 被谁调用、文件树、符号、源码片段）或箭头（这条边上哪个函数调了哪个、次数、写在哪一行）。 */
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
  var KIND = { dir: '目录（整棵子树收成一个节点）', residual: '目录里直接放着的文件（不含子目录）', unit: '单个文件',
               virtual: '不是仓库里的文件：定义不在仓库里的 GPU kernel 都在这' };
  /* 符号键 codestrata/payload.py#Handler.do_GET → payload:Handler.do_GET（包的 __init__.py 写包名）；
     兜底键（文件:行、文件:<module>）写成 文件名:行 / 文件名 顶层 */
  function symLabel(k) {
    var sk = CS.ids.splitSym(k);
    if (sk) {
      var parts = sk[0].split('/'), stem = parts.pop().replace(/\.[^.]*$/, '');
      if (stem === '__init__' && parts.length) stem = parts.pop();
      if (sk[1].indexOf('<module>') === 0) return stem + ' 顶层' + sk[1].slice(8);   // 模块顶层的代码（和它里面的 lambda）
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

  /* 和 scan 怎么对上的说明（align.judge / classify 的 note）：只有 trace 的为什么、构造跑的是哪个方法 */
  function nameList(ns) {
    var named = ns.filter(function (n) { return n; });
    if (!named.length) return '';
    return named.join('、') + (named.length < ns.length ? '（还有调一个表达式的结果的）' : '');
  }
  function noteText(nt) {
    if (!nt) return '';
    switch (nt.k) {
      case 'ctor': return '代码里写的是构造，跑的是 ' + nt.via.map(symLabel).join('、') + '（沿继承找到的）';
      case 'deferred': return '代码里写在第 ' + nt.at.join('、') + ' 行；生成器 / 协程 / with 到这一行才真正开始跑';
      case 'prop': return '这一行读了属性 ' + nt.name + '（property），接收者的类型 scan 定不下';
      case 'getattr': return '这一行读的属性在类里没有定义，走了 __getattr__（接收者的类型 scan 定不下）';
      case 'override': return '代码里写的是 ' + symLabel(nt.w) + '，跑的是这个（子类覆盖了它，或者同名的别的方法）';
      case 'name': return '代码里只知道名字 ' + nt.names.join('、') + '，定不下调到谁';
      case 'line':
        var c = nt.c || [], ext = nt.ext || [], ns = nt.names || [];
        var kinds = (c.length ? 1 : 0) + (ext.length ? 1 : 0) + (ns.length ? 1 : 0);
        if (kinds === 1 && c.length) return '这一行代码里调的是 ' + c.map(symLabel).join('、') + '，经它转了一道才到这里';
        if (kinds === 1 && ext.length) return '这一行调的是仓库外的 ' + (nameList(ext) || '函数') + '，经它回调到这里';
        if (kinds === 1) return nameList(ns) ? '这一行调了 ' + nameList(ns) + '（scan 定不下它是谁），经它转了一道才到这里'
                                             : '这一行调的是一个表达式的结果（f()()、fs[i]() 这类），scan 定不下它是谁，经它转了一道才到这里';
        return '这一行 scan 看到的调用：' + [c.length ? '仓库里的 ' + c.map(symLabel).join('、') : '',
          ext.length ? '仓库外的 ' + (nameList(ext) || '函数') : '',
          ns.length ? '定不下的 ' + (nameList(ns) || '表达式的结果') : ''].filter(function (x) { return x; }).join('；')
          + '——经其中一个转了一道才到这里';
      case 'none': return '这一行 scan 没看到调用（取属性、框架或仓库外的代码触发的）';
      case 'gpu': return 'GPU kernel：发起它（cudaLaunchKernel 这类）时栈上最近的仓库函数是调用方，不知道是哪一行——'
                         + 'Python 经扩展、PyTorch 这类仓库外的代码转了几道才启动它';
      case 'nomatch': return '调用方里没有同名的调用：多半是经仓库外的代码（框架、引擎循环、回调）转了一道——'
                             + '调用方只是栈上最近的仓库内函数';
    }
    return '';
  }
  var SCAN_KIND = ['调用', '构造', '装饰器', 'property', '语法触发', 'getattr', '仓库外', '启动 kernel'];

  /* 边详情的主体：每一对「谁调了谁」一张卡片——被调的函数、from（调用写在调用方的哪一行）、
     to（被调函数的签名）。只有 trace 的（代码里看不出会调到它）在前，再按次数排 */
  function callCards(E) {
    return E.calls.map(function (P) {
      var q = P.callee.slice(P.callee.indexOf('#') + 1), parts = CS.ids.qparts(q), qsep = CS.ids.qsep(q);
      var name = parts.pop(), only = P.status === 'trace', mixed = P.status === 'mixed';
      var lines = P.lines || P.guessed || [];
      var first = lines.filter(function (x) { return x.l; })[0];
      var from = first ? jump(first, fname(first.f) + ':' + first.l) : jump(P.caller_def, fname(P.caller_def.f) + ':' + P.caller_def.l);
      var more = lines.filter(function (x) { return x.l && x !== first; }).map(function (x) {
        return jump(x, ':' + x.l + (x.n ? ' ×' + x.n : '')); }).join('');
      var notes = {}, unk = 0;
      (P.lines || []).forEach(function (x) { if (x.note) notes[noteText(x.note)] = 1; if (!x.l) unk += x.n; });
      if (!P.lines && P.note) notes[noteText(P.note)] = 1;
      var gpu = (P.lines || []).some(function (x) { return x.note && x.note.k === 'gpu'; });
      var tag = gpu ? '<span class="dtag" title="GPU 上跑的 kernel（trace --gpu 录的），Python 代码里本来就不会直接写">GPU kernel</span>'
              : only ? '<span class="dtag" title="这次跑了，但代码里看不出会调到它：多态、注册表、回调、框架转了一道">代码里看不出</span>'
              : mixed ? '<span class="dtag" title="有的调用处代码里看得出，有的看不出">其中 ' + P.only + ' 次代码里看不出</span>' : '';
      return '<div class="call' + (only ? ' dyn' : '') + '">'
        + '<div class="ch"><span class="rt">×' + P.n + '</span><b>' + esc(name) + '</b>'
        + (parts.length ? '<span class="cls">' + esc(parts.join(qsep)) + '</span>' : '') + tag + '</div>'
        + '<div class="cs"><span class="lab">from</span>' + from + more
        + '<span class="who">' + esc(symLabel(P.caller)) + '</span></div>'
        + (first && first.s ? code([first.s]) : '')
        + (P.guessed ? '<div class="via">' + (P.guessed.length ? '这个 run 没记调用行：上面是在调用方里按名字找到的，不一定是这一处'
                                                               : '这个 run 没记调用行，不知道是哪一行') + '</div>' : '')
        + (unk ? '<div class="via">其中 ' + unk + ' 次不知道是哪一行（录制之后这个文件改过，调用行挪不过来），按调用方整个函数比</div>' : '')
        + Object.keys(notes).map(function (t) { return '<div class="via">' + esc(t) + '</div>'; }).join('')
        + '<div class="cs"><span class="lab">to</span>' + (P.def && P.def.virtual ? '<span>仓库外，没有源码</span>'
             : jump(P.def, P.def ? fname(P.def.f) + ':' + P.def.l : '（没找到定义）')) + '</div>'
        + code(P.sig)
        + (P.wiring ? '<div class="via">仓库里按名字提到 ' + esc(symLabel(P.wiring.cls)) + ' 的地方（注册表、插件表，接线多半在这）'
             + (P.wiring.same_name > 1 ? '；仓库里有 ' + P.wiring.same_name + ' 个同名类，不一定指它' : '') + '：'
             + P.wiring.refs.map(function (t) { return jump(t, fname(t.f) + ':' + t.l); }).join(' ') + '</div>' : '')
        + '</div>';
    }).join('');
  }

  /* 代码里写了、这次没录到的调用（没叠 run 时就是全部）：from 调用那一行，to 被调的定义 */
  function scanCards(items) {
    return items.map(function (x) {
      var q = x.callee.slice(x.callee.indexOf('#') + 1), parts = CS.ids.qparts(q), u = x.lines[0];
      return '<div class="call ref">'
        + '<div class="ch"><b>' + esc(parts.pop()) + '</b>'
        + (parts.length ? '<span class="cls">' + esc(parts.join(CS.ids.qsep(q))) + '</span>' : '')
        + (u && u.k ? '<span class="cls">' + esc(SCAN_KIND[u.k] || '') + '</span>' : '')
        + (x.approx ? '<span class="cls" title="C / C++ / CUDA 的调用按名字对上（tree-sitter，没有编译器的名字解析）">近似</span>' : '')
        + (x.n_lines > 1 ? '<span class="cls">' + x.n_lines + ' 处</span>' : '') + '</div>'
        + (x.unseen ? '<div class="via">构造这个类不跑仓库里的代码（dataclass 生成的 __init__、仓库外基类的），'
                      + '跑没跑 trace 都看不到</div>' : '')
        + (u ? '<div class="cs"><span class="lab">from</span>' + jump(u, fname(u.f) + ':' + u.l)
             + x.lines.slice(1).map(function (t) { return jump(t, ':' + t.l); }).join('')
             + '<span class="who">' + esc(symLabel(x.caller)) + '</span></div>' + code(u.s ? [u.s] : null) : '')
        + '<div class="cs"><span class="lab">to</span>' + jump(x.def, x.def ? fname(x.def.f) + ':' + x.def.l : '（没找到定义）') + '</div>'
        + code(x.sig) + '</div>';
    }).join('');
  }

  CS.panel = {
    short: short,      // 节点的短名（撞名的用补过父目录段的别名，和图上一致）：抽屉标题也用它
    full: full,        // 节点的完整显示名
    _detTok: 0,                   // 面板每换一次内容加一：异步请求回来时据此判断还要不要画
    noteText: noteText,           // 和 scan 怎么对上的说明（请求路径的行上也用）
    /* 别的模块（请求路径）要用下面的详情区：换一个令牌、放进 html，返回令牌；异步回来时用 mine 判断还要不要画 */
    claim: function (html) {
      var tok = ++this._detTok;
      delete det.dataset.pkg;
      det.innerHTML = html;
      return tok;
    },
    mine: function (tok) { return tok === this._detTok; },
    init: function (detEl, data) { det = detEl; D = data; this.reset(); },

    /* 展开 / 收起之后换一份切面数据 */
    setData: function (data) { D = data; },

    reset: function () {
      this._detTok++;
      delete det.dataset.pkg;
      det.innerHTML = '<p class="hint"><b>怎么读：</b>每条泳道是一层，箭头尽量从上指向下：'
        + '越上面越靠入口、越下面越是被调用的叶子；节点大小编码文件数。图上的边只有调用。'
        + '点节点看它调用谁、里面有什么符号；点箭头看这条边上是哪些函数在调用。</p>';
    },

    /* ---- 左：机器事实 ---- */
    showPkg: function (id, symKey) {
      this._detTok++;
      var v = (D.pkgs || {})[id] || {}, x = CS.graph.nb(id);
      // 代码里没写、这次运行才出现的调用（按名字加载、注册表、回调、self.model 这类）
      var dyn = { i: [], o: [] };
      CS.graph.edges.forEach(function (E) {
        if (E.scan || !E.hits) return;
        if (E.a === id) dyn.o.push(E.b); if (E.b === id) dyn.i.push(E.a);
      });
      var list = (D.pkgSyms || {})[id] || [];
      var hot = CS.graph.hot, hits = (hot && hot.packages[id]) || 0;
      function pills(a, l, out) {
        if (!a.length) return '';
        return '<div class="kv"><span>' + l + '</span>' + a.map(function (i) {
          var s = out ? id : i, t = out ? i : id, E = CS.graph.edgeInfo(s, t) || {};
          var tag = E.hits ? E.hits + ' 次' + (E.dashed ? ' · 代码里看不出' : E.only ? ' · 其中 ' + E.only + ' 次代码里看不出' : '')
                           : (E.scan || 0) + ' 处调用';
          return '<span class="dep"><button class="chip" data-go="' + esc(i) + '">' + esc(short(i))
            + '</button><button class="eb2' + (E.hits ? ' warm' : '')
            + '" data-edge="' + esc(s + '|' + t) + '" title="看这条边上具体是哪些函数在调用">' + tag + ' ⇢</button></span>';
        }).join('') + '</div>';
      }
      det.dataset.pkg = id;
      if (v.kind === 'virtual') {                 // 「GPU · 仓库外」：没有文件、符号、import，只有叠着的 run 里的 kernel
        det.innerHTML = '<h2 title="' + esc(id) + '">' + esc(full(id)) + '</h2>'
          + '<div class="sub">trace --gpu 录到的、定义不在仓库里的 kernel（PyTorch、cuBLAS、Triton 生成的……）。'
          + '调用方是发起它时栈上最近的仓库函数</div>' + this._cutRow(id, v)
          + '<div id="nbslot">' + pills(x.i, '← 被调用', false) + pills(dyn.i, '← 代码里没写、这次跑了', false) + '</div>'
          + this._kernels(id, v);
        this._wireDet(id);
        return;
      }
      det.innerHTML = '<h2 title="' + esc(id) + '">' + esc(full(id)) + '</h2>'
        + '<div class="sub" title="按 import 算：(出 − 入) / (出 + 入)，+1 靠入口、−1 是叶子">架构高度 ' + (v.alt >= 0 ? '+' : '') + (v.alt || 0).toFixed(2)
        + '　import 出 ' + (v.out || 0) + ' / 入 ' + (v.in || 0)
        + (hot ? ('　runtime ' + (hits ? hits + ' 次' : '未跑到')) : '') + '</div>'
        + '<div class="kv"><span>文件 <b>' + (v.files || 0) + '</b></span>'
        + '<span>行 <b>' + (v.loc || 0) + '</b></span>'
        + '<span>类 <b>' + (v.classes || 0) + '</b></span>'
        + '<span>函数（含方法）<b>' + (v.funcs || 0) + '</b></span></div>'
        + this._cutRow(id, v)
        // 分列里这一块换成这条线程里这一份的（CS.laneDetail.node）
        + '<div id="nbslot">' + pills(x.o, '调用 →', true) + pills(x.i, '← 被调用', false)
        + pills(dyn.o, '代码里没写、这次跑了 →', true) + pills(dyn.i, '← 代码里没写、这次跑了', false) + '</div>'
        + this._docs(id) + this._kernels(id, v)
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

    /* 这个节点上的 GPU kernel（trace --gpu）：叠着的 run（阶段）里每种跑了几次、在 GPU 上一共跑了多久，按时间排。
       虚拟节点是 ?gpu#… 的那些，别的节点是定义在它的文件里的 */
    _kernels: function (id, v) {
      var K = (D.hot && D.hot.kernels) || {}, files = {};
      ((D.pkgFiles || {})[id] || []).forEach(function (f) { files[f] = 1; });
      var ks = Object.keys(K).filter(function (k) {
        var f = k.slice(0, k.indexOf('#'));
        return v.kind === 'virtual' ? f === id : files[f];
      });
      if (!ks.length) return '';
      ks.sort(function (a, b) { return K[b].gpu_us - K[a].gpu_us; });
      var ms = function (us) { return us >= 1000 ? (us / 1000).toFixed(1) + ' ms' : us + ' µs'; };
      var tot = ks.reduce(function (s, k) { return s + K[k].gpu_us; }, 0);
      return '<div class="kv"><span>GPU kernel <b>' + ks.length + '</b> 种</span><span>GPU 上共 <b>' + ms(tot) + '</b></span></div>'
        + '<div class="ktab">' + ks.map(function (k) {
          var q = k.slice(k.indexOf('#') + 1);
          return '<div class="krow" title="' + esc(q) + '"><span class="kn">' + esc(q) + '</span><span class="kc">×' + K[k].n
            + '</span><span class="kt">' + ms(K[k].gpu_us) + '</span></div>';
        }).join('') + '</div>';
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
        // 方法挂在类下面：Python 是 Cls.m（只看一层）；C++ 是 ns::Cls::m，前缀是一个类才算方法（命名空间里的函数算顶层）
        var kids = {}, cls = {};
        (all || []).forEach(function (x) { if (x.k === 'class') cls[x.n] = 1; });
        var owner = function (x) {
          if (CS.ids.qsep(x.n) === '::') { var pre = x.n.slice(0, x.n.lastIndexOf('::')); return cls[pre] ? pre : null; }
          var parts = x.n.split('.');
          return parts.length === 2 ? parts[0] : null;
        };
        (all || []).forEach(function (x) { var o = owner(x); if (o) (kids[o] = kids[o] || []).push(x); });
        var list = all ? all.filter(function (x) {
          return CS.ids.qsep(x.n) === '::' ? !owner(x) : x.n.indexOf('.') === -1;
        }) : top;
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
            + '<span class="k' + (isC ? ' c' : '') + '"' + (x.k === 'kernel' ? ' title="GPU kernel"' : '') + '>'
            + (isC ? 'C' : x.k === 'kernel' ? 'K' : 'f') + '</span>'
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
        b.onclick = function () { CS.app.goNode(b.dataset.go); };
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
        b.onclick = function () { var ab = b.dataset.edge.split('|'); CS.app.goEdge(ab[0], ab[1]); };
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
      var c = E.counts, rt = E.has_runtime, self = this;
      // 录了时序事件的 run：函数对可以按第一次调用的先后排（默认按次数）
      var byTime = E.has_first && this._edgeSort === 't';
      var shown = !byTime ? E : Object.assign({}, E, { calls: E.calls.slice().sort(function (p, q) {
        return (p.first == null) - (q.first == null) || (p.first || 0) - (q.first || 0) || q.n - p.n; }) });
      var sub = rt ? 'trace <b>' + c.calls + '</b> 次 · ' + c.pairs + ' 对调用'
                     + (c.only ? ' · 其中 <b>' + c.only + '</b> 次代码里看不出' : '')
                   : c.scan_only + ' 对调用 · 没有叠 run（只看代码里写的）';
      var h = '<h2>' + esc(short(E.a)) + '<span class="arr">→</span>' + esc(short(E.b)) + '</h2>'
        + '<div class="sub">' + sub
        + '<span class="dep" style="margin-left:10px"><button class="chip" data-go="' + esc(E.a) + '">' + esc(short(E.a))
        + '</button><button class="chip" data-go="' + esc(E.b) + '" style="border-radius:0 999px 999px 0">' + esc(short(E.b)) + '</button></span>'
        + (rt && E.has_first && E.calls.length > 1 ? '<span class="esort">排序 <button class="chip" data-sort="n" aria-pressed="' + !byTime + '">按次数</button>'
           + '<button class="chip" data-sort="t" aria-pressed="' + byTime + '" title="按这一段里第一次调用的先后">按先后</button></span>' : '')
        + '</div>';
      function more(shown, all) {
        return all > shown ? '<p class="hint more">只列了前 ' + shown + ' 对，还有 ' + (all - shown) + ' 对（次数 / 调用处更少）</p>' : '';
      }
      if (E.lines_approx)
        h += '<p class="hint">时间段的次数来自时序事件，不带调用行：每一行的次数是按整个 run 记的调用行比例摊的</p>';
      h += rt ? (callCards(shown) || '<p class="hint">这次运行没有跨这条边的调用</p>') + more(E.calls.length, c.pairs)
              : scanCards(E.scan_only) + more(E.scan_only.length, c.scan_only);
      if (rt && E.scan_only.length)
        h += '<details class="efold"><summary>代码里写了，这次没录到<span class="n">' + c.scan_only + '</span></summary>'
          + scanCards(E.scan_only) + more(E.scan_only.length, c.scan_only) + '</details>';
      det.innerHTML = h;
      this._wireDet(E.a);
      [].forEach.call(det.querySelectorAll('[data-sort]'), function (b) {
        b.onclick = function () { self._edgeSort = b.dataset.sort; self._renderEdge(E); };
      });
    }
  };
})(window.CS);
