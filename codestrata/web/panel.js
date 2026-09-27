/* 详情面板（左：机器事实 + 源码）与解读面板（右：空槽 / 已写 / 过期）。
 * 「留给 llm agent 的空间」就是右边那块：没写时显示 task 输入包，
 * agent 从 PUT /api/notes 写回后这里立刻变成渲染好的解读。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var det, side, D;

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
    },

    /* ---- 左：机器事实 ---- */
    showPkg: function (id, symKey) {
      var v = (D.pkgs || {})[id] || {}, x = CS.graph.nb(id);
      var list = (D.pkgSyms || {})[id] || [];
      var hot = CS.graph.hot, hits = (hot && hot.packages[id]) || 0;
      function pills(a, l, out) {
        if (!a.length) return '';
        return '<div class="kv"><span>' + l + '</span>' + a.map(function (i) {
          var s = out ? id : i, t = out ? i : id, E = CS.graph.edgeInfo(s, t) || {}, inf = E.info || {};
          var tag = inf.uses ? inf.uses + ' 符号' : '只 import';
          return '<span class="dep"><button class="chip" data-go="' + esc(i) + '">' + esc(i.split('.').pop())
            + '</button><button class="eb2' + (inf.uses ? '' : ' imp') + (E.hits ? ' warm' : '')
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
        + '<span>函数 <b>' + (v.funcs || 0) + '</b></span></div>'
        + pills(x.o, '依赖 →', true) + pills(x.i, '← 被依赖', false)
        + this._files(id)
        + (list.length ? ('<div class="slist">' + list.slice(0, 40).map(function (s) {
            var h = (hot && hot.symbols[s.key]) || 0;
            return '<div class="si" data-sym="' + esc(s.key) + '" data-pkg="' + esc(id) + '">'
              + '<span class="k' + (s.k === 'class' ? ' c' : '') + '">' + (s.k === 'class' ? 'C' : 'f') + '</span>'
              + '<span class="n" title="' + esc(s.n) + '">' + esc(s.n) + '</span>'
              + (h ? '<span class="h">' + h + '</span>' : '') + '</div>';
          }).join('') + '</div>') : '')
        + '<div id="srcslot"></div>';
      this._wireDet(id);
      if (symKey) this.showSource(id, symKey);
    },

    _files: function (id) {
      var fs = (D.pkgFiles || {})[id] || [];
      if (!fs.length) return '';
      var LANG = { py: 'Python', pyi: 'Python', cu: 'CUDA', cuh: 'CUDA', c: 'C',
                   cc: 'C++', cpp: 'C++', cxx: 'C++', h: 'C++', hh: 'C++', hpp: 'C++', inl: 'C++' };
      var shown = fs.slice(0, 24);
      return '<div class="kv files"><span>全文</span>' + shown.map(function (f) {
        var ext = f.split('.').pop().toLowerCase();
        return '<button class="filebtn" data-view="' + esc(f) + '" title="' + esc(f) + '">'
          + '<span class="fl lang-' + (LANG[ext] || 'x').replace(/\W/g, '').toLowerCase() + '">'
          + (LANG[ext] || ext) + '</span>' + esc(f.split('/').pop()) + '</button>';
      }).join('') + (fs.length > shown.length ? '<span>…还有 ' + (fs.length - shown.length) + ' 个</span>' : '')
        + '</div>';
    },

    showSource: function (pkg, key) {
      var slot = document.getElementById('srcslot');
      if (!slot) return;
      slot.innerHTML = '<p class="hint" style="margin-top:10px">读取源码…</p>';
      var self = this;
      CS.ds.source(key).then(function (s) {
        if (!s) { slot.innerHTML = ''; return; }
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
        self._wireDet(pkg);
      }).catch(function () { slot.innerHTML = ''; });
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
        + (E.import_exec ? '<br>另有 ' + E.import_exec + ' 次是 import 触发的模块顶层执行，不算调用' : '');
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
      var short = id.split('.').pop();
      var tag = nt.present ? (nt.stale ? '<span class="tagpill stale">可能过期</span>'
                                       : '<span class="tagpill noted">已解读</span>')
                           : '<span class="tagpill">未解读</span>';
      var head = '<h3>' + esc(short) + ' 的解读 ' + tag + '</h3>';

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
