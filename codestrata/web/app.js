/* 入口：把数据源、图、两个面板串起来。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  CS.app = {
    data: null,

    boot: function () {
      var self = this;
      CS.ds.graph().then(function (d) {
        self.data = d;
        self.header(d);
        CS.panel.init(document.getElementById('det'), document.getElementById('side'), d);
        CS.graph.onPick = function (id) { CS.panel.showPkg(id); CS.panel.showNote(id); };
        CS.graph.onPickEdge = function (a, b) { CS.panel.showEdge(a, b); CS.panel.showEdgeSide(a, b); };
        CS.graph.onCollapse = function (f) { self.collapseFrame(f); };
        CS.graph.onClear = function () { CS.panel.reset(); };
        CS.graph.onExpand = function (id) {
          if (!CS.ds.canCut) { document.getElementById('prog').textContent = '导出的单文件不能展开，请用 codestrata serve'; return; }
          self.expand(id);
        };
        CS.graph.draw(document.getElementById('g'), d.graph, d.hot,
                      { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges });
        self.edgeChips();
        self.controls();
        self.cutBar();
        self.refreshStatus();
        self.footer(d);
      }).catch(function (e) {
        document.getElementById('h1').textContent = '加载失败';
        document.getElementById('lede').textContent = e.message;
      });
    },

    header: function (d) {
      var r = d.repo;
      document.getElementById('h1').textContent = r.name + ' 架构';
      document.getElementById('lede').innerHTML =
        '纵轴是<b>架构高度</b> <code>(出−入)/(出+入)</code>：最上面的泳道谁都不依赖它、它依赖一切，'
        + '最下面的只被依赖。横轴用重心排序减少交叉。'
        + ' 灰实线是真的用到了对方符号的 import，灰虚线是只 import 没用到的。'
        + (d.hot ? ' 橙色是这次 <b>runtime</b> 真正跑到的部分。' : '')
        + '　左上角带 <b>＋</b> 的节点可以就地展开：子模块出现在一个框里，框头的 <b>−</b> 收起；'
        + '展开 / 收起不会取消选中，再点一次选中的节点才取消。'
        + '　右侧是<b>解读层</b>——机器给不出的那部分。';
      var st = [['文件', r.n_files], ['模块', r.n_units || 0], ['图上节点', d.graph.nodes.length],
                ['符号', r.n_symbols || 0], ['图上的边', d.graph.edges.length],
                ['解析失败', r.n_parse_errors]];
      document.getElementById('stats').innerHTML =
        st.map(function (p) { return '<span>' + p[0] + ' <b>' + p[1] + '</b></span>'; }).join('')
        + '<span>模式 <b>' + CS.ds.mode + '</b></span>';
      if (d.hot && d.hotMeta) {
        var m = d.hotMeta;
        document.getElementById('hotbanner').innerHTML =
          '<div class="hotbanner"><div><b>hot 图</b>：case <b>' + esc(m.case) + '</b>　'
          + (m.phase ? '阶段 <b>' + esc(m.phase) + '</b>　' : '')
          + (m.phases && Object.keys(m.phases).length
             ? '<span class="lab">（这次 trace 分了阶段：' + Object.keys(m.phases).map(function (k) {
                 return esc(k) + ' ' + m.phases[k] + ' 个函数'; }).join(' / ')
               + (m.phase ? '' : '；现在显示的是全部') + '）</span>　' : '')
          + (m.n_procs ? '跨 ' + m.n_procs + ' 个进程　' : '')
          + (m.unmapped ? '<span title="lambda、闭包、生成器表达式和模块顶层执行没有自己的符号，'
             + '不计入符号的调用次数（闭包的调用在边详情里会归到外层函数）">未归到命名符号的调用 '
             + m.unmapped + '</span>　' : '')
          + (m.mapped_from ? '运行的是安装包 <code>' + esc(m.mapped_from) + '</code>，已映射回仓库 ' + m.n_mapped + ' 个文件'
             + (m.mapped_mismatch && m.mapped_mismatch.length
                ? '，<span style="color:var(--stale)">其中 ' + m.mapped_mismatch.length + ' 个与仓库内容不一致，行号不可信</span>'
                : '（逐文件与仓库一致 ✓）') + '　' : '')
          + (m.stale_files && m.stale_files.length ? '<span style="color:var(--stale)">⚠ 录制后有 '
             + m.stale_files.length + ' 个文件改动过，叠加可能不准，重跑 trace 即可</span>　' : '')
          + '<div class="cmd">' + esc((m.cmd || []).join(' ')) + '</div></div></div>';
      }
    },

    /* 边的开关兼图例：每个开关上画的线就是图上那种边的样子，数字是条数 */
    edgeChips: function () {
      var c = CS.graph.counts, hot = !!CS.graph.hot, s = CS.graph.state;
      var defs = [['refs', 'e ref', '引用', c.ref, 'import 了，并且真的用到了对方的符号', false],
                  ['imp', 'e imp', '只 import', c.imp,
                   '一个符号都没用到：再导出 / 只做类型标注 / 为了副作用 / 死 import', false]];
      if (hot) {
        defs.push(['hot', 'e ref warm', 'runtime', c.warm, '这次 case 真的调用过，粗细 ∝ 调用次数', true]);
        if (c.dyn) defs.push(['dyn', 'e dyn warm', '只在 runtime', c.dyn,
                              '静态 import 图里没有：插件 / getattr / 注册表这类动态分派', true]);
      }
      document.getElementById('edgechips').innerHTML = defs.map(function (x) {
        return '<button class="chip lg' + (x[5] ? ' rt' : '') + '" data-t="' + x[0] + '" aria-pressed="' + (s[x[0]] !== false) + '" title="'
          + esc(x[4]) + '"><svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" class="'
          + x[1] + '" style="stroke-width:1.8"/></svg>' + x[2] + ' <span class="n">' + x[3] + '</span></button>';
      }).join('');
    },

    /* ---- 切面：展开 / 收起 ---- */
    /* 当前（或正在路上的）切面：连着点几个 ＋ 时，后一次要在前一次的基础上改，而不是在旧图上改 */
    curOpen: function () { return (this._pending || this.data.open).slice(); },

    expand: function (id) {
      var open = this.curOpen();
      if (open.indexOf(id) < 0) open.push(id);
      this.setCut(open, id);
    },

    /* 收起一个节点 = 收起套着它的那个框 */
    collapse: function (id) {
      var v = (this.data.pkgs || {})[id] || {};
      if (v.collapsible) this.collapseFrame(v.parent);
    },

    /* 收起一个框：本层文件的框只去掉它自己；目录的框连同它底下所有展开的东西一起去掉 */
    collapseFrame: function (f) {
      var open = this.curOpen().filter(function (x) {
        return /\.\*$/.test(f) ? x !== f : !(x === f || x.indexOf(f + '.') === 0);
      });
      this.setCut(open, f);
    },

    resetCut: function () { this.setCut(this.data.defaultOpen.slice()); },

    /* 换一个切面。focus 是这次展开 / 收起的那个目录：新图画好后把它滚进图框里 */
    setCut: function (open, focus) {
      var self = this, before = {}, st = CS.graph.state;
      var seq = this._cutSeq = (this._cutSeq || 0) + 1;
      this._pending = open.slice();
      var was = { sel: st.sel, selEdge: st.selEdge, selFrame: st.selFrame, kind: {} };
      // 记下选中的东西是目录、本层文件还是单个文件：新图上找「谁装着它」时要用
      this.data.graph.nodes.concat(this.data.graph.frames || []).forEach(function (n) { was.kind[n.id] = n.kind; });
      this.data.graph.nodes.forEach(function (n) { before[n.id] = 1; });
      document.getElementById('prog').textContent = '重新汇总…';
      CS.ds.graph(open).then(function (d) {
        if (seq !== self._cutSeq) return;   // 连着点了几次：只认最后一次，先发出的请求晚回来也不能盖掉它
        self._pending = null;
        self.data = d;
        CS.panel.setData(d);
        self.header(d);
        st.sel = st.selEdge = st.selFrame = null;
        self.redraw();
        self.refreshStatus();
        self.keepSelection(was);
        if (focus) {
          CS.graph.reveal(focus);
          // 用键盘点的 ＋ / − 随着重画没了，焦点会掉回 body：交给刚展开的框（它的 −）或刚收回的节点
          var ae = document.activeElement;
          if (!ae || ae === document.body || !document.contains(ae)) CS.graph.focus(focus);
        }
        // 新出现的节点闪一下，好看出展开出来的是哪些
        CS.graph.flash(d.graph.nodes.filter(function (n) { return !before[n.id]; }).map(function (n) { return n.id; }));
        self.cutBar();
      }).catch(function (e) {
        if (seq !== self._cutSeq) return;
        self._pending = null;
        document.getElementById('prog').textContent = e.message;
      });
    },

    /* 展开 / 收起不取消选中。选中的节点还在就还选它（详情重画：它的邻居可能变了）；
       它被收进了某个节点就选那个节点；它自己被展开成了框，就选中那个框、详情面板不动。
       选中的边两头按同样的规则落到新节点上，新图上还有这条边就接着选它。 */
    keepSelection: function (was) {
      var g = this.data.graph, ids = {}, frames = {};
      g.nodes.forEach(function (n) { ids[n.id] = 1; });
      (g.frames || []).forEach(function (f) { frames[f.id] = 1; });
      // id 在新图上落在哪个节点：还是节点就是它自己；被收起了就是装着它的那个节点。
      // 目录节点装着它底下的一切；本层文件节点只装直接放在这个目录里的单个文件（不装子目录）
      function home(id) {
        if (ids[id]) return id;
        var best = null, unit = was.kind[id] === 'unit';
        g.nodes.forEach(function (n) {
          var res = /\.\*$/.test(n.id), base = res ? n.id.slice(0, -2) : n.id;
          var inside = id.indexOf(base + '.') === 0
            && (!res || (unit && id.slice(base.length + 1).indexOf('.') < 0));
          if (inside && (!best || n.id.length > best.length)) best = n.id;
        });
        return best;
      }
      var id = was.sel || was.selFrame;
      if (id) {
        if (frames[id]) { CS.graph.selectFrame(id); CS.panel.asFrame(id); }   // 自己被展开成了框
        else if (home(id)) CS.graph.pick(home(id), true);   // 不滚动：视线留在刚点的地方
        else CS.panel.reset();
      } else if (was.selEdge) {
        var ab = was.selEdge.split('|'), a = home(ab[0]), b = home(ab[1]);
        if (a && b && a !== b && CS.graph.edgeInfo(a, b)) CS.graph.pickEdge(a, b);
        // 否则边详情留在面板上（它讲的那两组代码没变），图上不再高亮
      }
    },

    cutBar: function () {
      var d = this.data, b = document.getElementById('resetcut');
      if (!b) return;
      var same = d.open.slice().sort().join(',') === (d.defaultOpen || []).slice().sort().join(',');
      b.style.display = same ? 'none' : '';
    },

    redraw: function () {
      var d = this.data, s = CS.graph.state;
      CS.graph.draw(document.getElementById('g'), s.onlyHot && d.graphHot ? d.graphHot : d.graph, d.hot,
                    { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges });
      if (CS.graph.noteStatus) CS.graph.setNoteStatus(CS.graph.noteStatus);
      // 重画会重建所有节点：图例上边的条数按这张图重数，搜索框里还有字就把高亮重新套上
      this.edgeChips();
      this.controls();
      var q = document.getElementById('q');
      if (q.value.trim()) q.oninput();
    },

    controls: function () {
      var s = CS.graph.state, self = this;
      var KEY = { refs: 'refs', imp: 'imp', hot: 'hot', dyn: 'dyn', onlyhot: 'onlyHot', noted: 'onlyNoted' };
      [].forEach.call(document.querySelectorAll('[data-t]'), function (b) {
        var key = KEY[b.dataset.t];
        if (key === 'onlyHot' && !CS.graph.hot) { b.style.display = 'none'; return; }
        b.onclick = function () {
          s[key] = b.getAttribute('aria-pressed') !== 'true';
          b.setAttribute('aria-pressed', s[key]);
          // 「只看跑到的」换成单独排版的 hot 图，而不是在总图上隐藏——隐藏的节点还占着位置
          if (key === 'onlyHot' && self.data.graphHot) self.redraw();
          else CS.graph.paint();
        };
      });
      var q = document.getElementById('q');
      q.oninput = function () {
        var t = q.value.trim().toLowerCase();
        CS.graph.highlight(t ? function (n) {
          if ((n.id + ' ' + n.label).toLowerCase().indexOf(t) !== -1) return true;
          return ((self.data.pkgSyms || {})[n.id] || []).some(function (x) {
            return x.n.toLowerCase().indexOf(t) !== -1; });
        } : null);
      };
      var rc = document.getElementById('resetcut');
      if (rc) rc.onclick = function () { self.resetCut(); };
      document.getElementById('reset').onclick = function () {
        q.value = ''; CS.graph.highlight(null); CS.graph.clear();
      };
      if (!this._esc) {
        this._esc = true;
        document.addEventListener('keydown', function (ev) {
          // Esc 取消选中（全文窗口开着时 Esc 先关窗口，那边自己处理）
          // 正在输入框里打字（搜索框、文件树过滤、贴解读的文本框）时 Esc 归输入框自己
          var s = CS.graph.state, t = ev.target;
          if (ev.isComposing || (t && t.closest && t.closest('input, textarea, select, [contenteditable]'))) return;
          if (ev.key === 'Escape' && document.getElementById('viewer').hidden
              && (s.sel || s.selEdge || s.selFrame)) CS.graph.clear();
        });
      }
    },

    /* 每个节点的解读状态：图上打 ✓ / ! 徽标，工具栏显示进度 */
    refreshStatus: function () {
      // 分母取图上的节点：空包（如空 __init__.py）不上图也不派活，不该算进进度
      var ids = this.data.graph.nodes.map(function (n) { return n.id; });
      var self = this, seq = this._cutSeq;
      CS.ds.status(ids).catch(function () { return {}; }).then(function (map) {
        if (seq !== self._cutSeq) return;      // 这期间切面又变了：这份状态是旧图的
        CS.graph.setNoteStatus(map);
        var n = 0, st = 0;
        ids.forEach(function (i) { if (map[i] === 'noted') n++; else if (map[i] === 'stale') st++; });
        document.getElementById('prog').innerHTML =
          '解读 <b>' + n + '</b>/' + ids.length + (st ? '（过期 ' + st + '）' : '');
      });
    },

    footer: function (d) {
      var r = d.repo;
      document.getElementById('foot').innerHTML =
        'codestrata · 结构由 <code>ast</code> 遍历 <code>' + esc((r.roots || []).join(', '))
        + '</code> 得出（' + r.n_files + ' 文件，解析失败 ' + r.n_parse_errors + '）'
        + (d.hot ? '；hot 部分来自 runtime hook' : '')
        + '。解读层存在仓库的 <code>notes/</code> 下，随代码一起进版本库。';
    }
  };
  // 内联进宿主页面时脚本可能在 DOMContentLoaded 之后才跑，那时再监听就永远等不到
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function () { CS.app.boot(); });
  else CS.app.boot();
})(window.CS);
