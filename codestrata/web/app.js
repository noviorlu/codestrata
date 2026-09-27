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
        + '　左上角带 <b>＋</b> 的节点可以在图上展开成子模块，展开后的节点能在详情里收起。'
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
    expand: function (id) { this.setCut(this.data.open.concat([id]), id); },

    collapse: function (id) {
      var p = ((this.data.pkgs || {})[id] || {}).parent;
      if (!p) return;
      var open = this.data.open.filter(function (x) {
        return /\.\*$/.test(p) ? x !== p : !(x === p || x.indexOf(p + '.') === 0);
      });
      this.setCut(open, p);
    },

    resetCut: function () { this.setCut(this.data.defaultOpen.slice(), null); },

    setCut: function (open, focus) {
      var self = this, before = {};
      this.data.graph.nodes.forEach(function (n) { before[n.id] = 1; });
      document.getElementById('prog').textContent = '重新汇总…';
      CS.ds.graph(open).then(function (d) {
        self.data = d;
        CS.panel.setData(d);
        self.header(d);
        CS.graph.state.sel = CS.graph.state.selEdge = null;
        self.redraw();
        self.edgeChips();              // 边的条数变了；开关状态沿用
        self.controls();
        self.refreshStatus();
        CS.panel.reset();
        // 新出现的节点闪一下，好看出展开出来的是哪些；收起时选中收回去的那个节点
        CS.graph.flash(d.graph.nodes.filter(function (n) { return !before[n.id]; }).map(function (n) { return n.id; }));
        if (focus && CS.graph.nodes[focus]) CS.graph.pick(focus);
        self.cutBar();
      }).catch(function (e) {
        document.getElementById('prog').textContent = e.message;
      });
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
        q.value = ''; CS.graph.highlight(null);
        CS.graph.state.sel = null; CS.graph.state.selEdge = null; CS.graph.paint(); CS.panel.reset();
      };
    },

    /* 每个节点的解读状态：图上打 ✓ / ! 徽标，工具栏显示进度 */
    refreshStatus: function () {
      // 分母取图上的节点：空包（如空 __init__.py）不上图也不派活，不该算进进度
      var ids = this.data.graph.nodes.map(function (n) { return n.id; });
      CS.ds.status(ids).catch(function () { return {}; }).then(function (map) {
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
