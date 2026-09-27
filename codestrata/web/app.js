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
        CS.graph.draw(document.getElementById('g'), d.graph, d.hot);
        self.controls();
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
        + (d.hot ? ' 橙色是这次 <b>runtime</b> 真正跑到的部分。' : '')
        + '　右侧是<b>解读层</b>——机器给不出的那部分。';
      var st = [['文件', r.n_files], ['包', Object.keys(d.pkgs || {}).length],
                ['符号', r.n_symbols || 0], ['import 边', d.graph.edges.length],
                ['解析失败', r.n_parse_errors]];
      document.getElementById('stats').innerHTML =
        st.map(function (p) { return '<span>' + p[0] + ' <b>' + p[1] + '</b></span>'; }).join('')
        + '<span>模式 <b>' + CS.ds.mode + '</b></span>';
      if (d.hot && d.hotMeta) {
        var m = d.hotMeta;
        document.getElementById('hotbanner').innerHTML =
          '<div class="hotbanner"><div><b>hot 图</b>：case <b>' + esc(m.case) + '</b>　'
          + (m.n_procs ? '跨 ' + m.n_procs + ' 个进程　' : '')
          + (m.unmapped ? '未映射 ' + m.unmapped + '　' : '')
          + '<div class="cmd">' + esc((m.cmd || []).join(' ')) + '</div></div></div>';
      }
    },

    controls: function () {
      var s = CS.graph.state;
      [].forEach.call(document.querySelectorAll('[data-t]'), function (b) {
        var key = b.dataset.t === 'imports' ? 'imports' : b.dataset.t === 'hot' ? 'hot'
                : b.dataset.t === 'onlyhot' ? 'onlyHot' : 'onlyNoted';
        if ((key === 'hot' || key === 'onlyHot') && !CS.graph.hot) { b.style.display = 'none'; return; }
        b.onclick = function () {
          s[key] = b.getAttribute('aria-pressed') !== 'true';
          b.setAttribute('aria-pressed', s[key]); CS.graph.paint();
        };
      });
      var q = document.getElementById('q'), self = this;
      q.oninput = function () {
        var t = q.value.trim().toLowerCase();
        CS.graph.highlight(t ? function (n) {
          if ((n.id + ' ' + n.label).toLowerCase().indexOf(t) !== -1) return true;
          return ((self.data.pkgSyms || {})[n.id] || []).some(function (x) {
            return x.n.toLowerCase().indexOf(t) !== -1; });
        } : null);
      };
      document.getElementById('reset').onclick = function () {
        q.value = ''; CS.graph.highlight(null);
        CS.graph.state.sel = null; CS.graph.paint(); CS.panel.reset();
      };
    },

    /* 每个节点的解读状态：图上打 ✓ / ! 徽标，工具栏显示进度 */
    refreshStatus: function () {
      var ids = Object.keys(this.data.pkgs || {});
      var map = {}, self = this;
      Promise.all(ids.map(function (id) {
        return CS.ds.note(id).then(function (nt) {
          map[id] = !nt.present ? 'todo' : (nt.stale ? 'stale' : 'noted');
        }).catch(function () { map[id] = 'todo'; });
      })).then(function () {
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
