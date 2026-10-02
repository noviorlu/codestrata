/* 右边的搜索栏：按名字找模块、文件、类 / 函数（含方法）。
 *
 * 名字全在前端搜：索引（/api/search-index）一次拿全，每敲一个字在几万个名字里
 * 打分排序，不来回请求。按**名字本身**找：函数 / 类看它自己的名字（方法也看它所在的类名），
 * 文件看文件名，模块看最后一段。搜「entrypoints」时，entrypoints 目录下的函数不算命中——
 * 名字里没有它；早先连路径一起匹配，按函数过滤出来的全是 entrypoints 下面的函数。
 * 想按路径找就在词里写上「.」或「/」（entrypoints/、engine.async），这时才看路径。
 * 打分：名字完全相等 > 名字开头 > 名字包含 > 方法所在的类名包含 > 路径包含（只在词里有 . 或 / 时）；
 * 同分时名字短的在前，这次 runtime 跑到过的符号稍微靠前。
 *
 * 点结果都先回到图上：展开到它所在的模块、选中并滚到屏幕中间；文件 / 类 / 函数再在下面的
 * 详情面板里展开到它（文件树里标出来，类 / 函数放出源码片段），稍后滚过去。
 * 旁边的「代码」按钮直接在全文窗口里打开到那一行。
 * 搜索框里有字时，图上包含命中项的节点一直高亮（换切面后也是）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var items = null, loading = null, q = '', only = 'all', rows = [], cur = -1, timer = 0;
  var GROUPS = [['mod', '模块'], ['file', '文件'], ['sym', '类 / 函数']];
  var PER_GROUP = 8, MAX = 300;
  var LS = 'codestrata.search.open';

  function rootLabel() {                      // 只有一个根时，显示名前面那段不用每行都写
    return (CS.app && CS.app.data && CS.app.data.rootLabel) || '';
  }

  function build(ix) {
    var out = [], root = rootLabel();
    ix.mods.forEach(function (m) {
      // m = [id, 种类, 文件数, 显示名, 分隔符]：id 是路径，显示名是点分的模块名（Python）或路径
      var id = m[0], lab = m[3] || id, sep = m[4] || '/', pre = root ? root + sep : '';
      var short = pre && lab.indexOf(pre) === 0 ? lab.slice(pre.length) : lab;
      var bare = id.replace(/\/$/, '');
      // 路径写成点号或斜杠都能找到（entrypoints.openai / entrypoints/openai/）
      out.push({ t: 'mod', id: id, kind: m[1], nf: m[2], name: lab.split(sep).pop(),
                 show: short + (m[1] === 'dir' ? '/' : ''),
                 path: id + ' ' + lab,
                 exact: [id, bare, lab, short].map(function (x) { return x.toLowerCase(); }) });
    });
    ix.files.forEach(function (f, i) {
      out.push({ t: 'file', f: f, unit: ix.units[i], name: f.split('/').pop(), path: f });
    });
    ix.syms.forEach(function (s) {
      var u = ix.units[s[2]], f = ix.files[s[2]];
      out.push({ t: 'sym', q: s[0], k: s[1], f: f, l: s[3], unit: u, key: f + '#' + s[0],     // 符号键 <路径>#<限定名>
                 name: CS.ids.tail(s[0]), path: s[0] + ' ' + f });
    });
    out.forEach(function (it) {
      it.ln = it.name.toLowerCase();                             // 名字本身
      it.lq = it.t === 'sym' ? it.q.toLowerCase() : '';          // 方法连同类名：Class.method
      it.lp = it.path.toLowerCase();                             // 路径：只有词里带 . 或 / 时才看
      // 同分时浅的在前：顶层的 request 模块排在 diffusion.diffusion_kv.request 前面
      it.depth = ((it.t === 'mod' ? it.id.replace(/\/$/, '') : it.t === 'file' ? it.f : it.q + ' ' + it.f).match(/[./]/g) || []).length;
      it.sortKey = it.t === 'mod' ? it.id : it.t === 'file' ? it.f : it.key;
    });
    return out;
  }

  function score(it, terms, hot) {
    var s = 0;
    for (var i = 0; i < terms.length; i++) {
      var w = terms[i];
      if (it.ln === w) s += 100;
      else if (it.ln.indexOf(w) === 0) s += 70;
      else if (it.ln.indexOf(w) >= 0) s += 45;
      else if (it.lq && it.lq.indexOf(w) >= 0) s += 30;
      else if (/[./]/.test(w) && it.lp.indexOf(w) >= 0) {
        // 路径完全对上（或以它结尾）的，比只是路径里包含它的排得靠前
        var ww = w.replace(/\/$/, '');
        s += it.exact && it.exact.indexOf(ww) >= 0 ? 90 : (it.lp.slice(-ww.length - 1).indexOf(ww) >= 0 ? 40 : 15);
      }
      else return -1;
    }
    s -= it.name.length * 0.15;
    if (it.t === 'sym' && hot && hot[it.key]) s += 6;
    if (it.t === 'mod' && it.kind === 'dir') s += 2;         // 同名时目录（整棵子树）在前
    return s;
  }

  /* 名字里命中的那段加粗 */
  function mark(text, terms) {
    var low = text.toLowerCase(), hit = [];
    terms.forEach(function (w) { var i = low.indexOf(w); if (i >= 0) hit.push([i, i + w.length]); });
    if (!hit.length) return esc(text);
    hit.sort(function (a, b) { return a[0] - b[0]; });
    var h = '', p = 0;
    hit.forEach(function (r) {
      if (r[0] < p) return;
      h += esc(text.slice(p, r[0])) + '<mark>' + esc(text.slice(r[0], r[1])) + '</mark>'; p = r[1];
    });
    return h + esc(text.slice(p));
  }

  CS.search = {
    init: function () {
      var self = this, input = document.getElementById('sq');
      if (!input) return;
      var on = true;
      try { var v = localStorage.getItem(LS); if (v !== null) on = v === '1'; } catch (e) { /* 隐私模式 */ }
      if (window.innerWidth < 900) on = false;              // 很窄的屏默认收起，要用时点右上角的「搜索」
      this.show(on);
      document.getElementById('sbar').classList.add('mini');
      // 只有用户自己点「收起 / 搜索」才记住；窄屏时的默认收起不算，免得宽屏回来也被收着
      document.getElementById('sbx').onclick = function () { self.show(false, true); };
      // 拖左边框改宽、拖下边框改高（左下角两个一起），记在浏览器里
      var bar = document.getElementById('sbar'), SZ = 'codestrata.search.size', sz = CS.app._load(SZ);
      if (sz.w) bar.style.width = sz.w + 'px';
      if (sz.h) bar.style.height = sz.h + 'px';
      CS.app.resizable(bar, ['l', 'b', 'lb'], function (e, r0, dx, dy) {
        var g = document.getElementById('gwrap').getBoundingClientRect();
        if (e !== 'b') bar.style.width = Math.max(260, Math.min(g.width - 20, r0.width - dx)) + 'px';
        if (e !== 'l') bar.style.height = Math.max(120, Math.min(g.height - 20, r0.height + dy)) + 'px';
      }, function () {
        CS.app._save(SZ, { w: parseFloat(bar.style.width) || undefined, h: parseFloat(bar.style.height) || undefined });
      });
      document.getElementById('sbtab').onclick = function () { self.show(true, true); input.focus(); };
      input.oninput = function () {
        document.getElementById('sbar').classList.remove('mini');     // 一打字就把结果列表放出来
        clearTimeout(timer);
        timer = setTimeout(function () { q = input.value.trim(); cur = -1; self.run(); }, 90);
      };
      input.onfocus = function () { self.load(); document.getElementById('sbar').classList.remove('mini'); };
      // 浮在图上：没在用（框里没字、焦点也不在这）时只留一个搜索框，别挡着图
      document.getElementById('sbar').addEventListener('focusout', function () {
        setTimeout(function () {
          var bar = document.getElementById('sbar');
          if (!input.value.trim() && !bar.contains(document.activeElement)) bar.classList.add('mini');
        }, 150);
      });
      input.onkeydown = function (ev) {
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          if (!rows.length) return;
          cur = Math.max(0, Math.min(rows.length - 1, cur + (ev.key === 'ArrowDown' ? 1 : -1)));
          self.paintCur();
        } else if (ev.key === 'Enter') {
          ev.preventDefault();
          // 打完字立刻回车：防抖的定时器还没到，结果列表还是上一次的——先按现在的字搜一遍
          if (input.value.trim() !== q) { clearTimeout(timer); q = input.value.trim(); cur = -1; self.run(); }
          if (!items) { var p = self.load(); if (p) p.then(function () { self.act(rows[0], false); }); return; }
          self.act(rows[cur >= 0 ? cur : 0], false);
        } else if (ev.key === 'Escape') {
          ev.preventDefault();
          if (input.value) { input.value = ''; q = ''; self.run(); } else input.blur();
        }
      };
      [].forEach.call(document.querySelectorAll('#sbf [data-only]'), function (b) {
        b.onclick = function () { only = b.dataset.only; cur = -1; self.run(); };
      });
      // 「/」或 Ctrl+K 跳到搜索框（正在别的输入框里打字时不抢）
      document.addEventListener('keydown', function (ev) {
        var t = ev.target;
        if (t && t.closest && t.closest('input, textarea, select, [contenteditable]')) return;
        if (!document.getElementById('viewer').hidden) return;
        if (ev.key === '/' || ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K'))) {
          ev.preventDefault(); self.show(true, !document.getElementById('sbar').hidden); input.focus(); input.select();
        }
      });
      this.run();
    },

    /* 搜索栏浮在图上（半透明），不占页面的宽度 */
    show: function (on, remember) {
      document.getElementById('sbar').hidden = !on;
      document.getElementById('sbtab').hidden = on;
      if (remember) try { localStorage.setItem(LS, on ? '1' : '0'); } catch (e) { /* 隐私模式 */ }
    },

    load: function () {
      if (items || loading) return loading;
      var self = this;
      document.getElementById('sbr').innerHTML = '<p class="hint">读取名字索引…</p>';
      loading = CS.ds.searchIndex().then(function (ix) {
        items = ix ? build(ix) : [];
        self.run();
      }).catch(function (e) {
        items = [];
        document.getElementById('sbr').innerHTML = '<p class="hint">索引读取失败：' + esc(e.message) + '</p>';
      });
      return loading;
    },

    query: function () { return q; },

    run: function () {
      var box = document.getElementById('sbr'), self = this;
      [].forEach.call(document.querySelectorAll('#sbf [data-only]'), function (b) {
        b.setAttribute('aria-pressed', b.dataset.only === only);
      });
      var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
      rows = [];
      if (!terms.length) {
        box.innerHTML = '<p class="hint">按名字找：函数 / 类看它自己的名字（方法也看类名），文件看文件名，'
          + '模块看最后一段。空格隔开多个词（都要命中）。'
          + '<br>想按路径找，词里写上 <code>.</code> 或 <code>/</code>，比如 <code>entrypoints/</code>、<code>engine.async</code>。'
          + '<br>按 <kbd>/</kbd> 或 <kbd>Ctrl</kbd>+<kbd>K</kbd> 随时回到这里；↑ ↓ 选，回车打开。</p>';
        this.hits = [];
        this.highlight([]);
        return;
      }
      if (!items) { this.load(); return; }
      var hot = CS.graph && CS.graph.hot && CS.graph.hot.symbols, by = { mod: [], file: [], sym: [] };
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if (only !== 'all' && it.t !== only) continue;
        var s = score(it, terms, hot);
        if (s >= 0) by[it.t].push([s, it]);
      }
      var h = '';
      GROUPS.forEach(function (g) {
        var L = by[g[0]];
        if (only !== 'all' && only !== g[0]) return;
        L.sort(function (a, b) {
          return b[0] - a[0] || a[1].depth - b[1].depth || a[1].sortKey.length - b[1].sortKey.length
            || (a[1].sortKey < b[1].sortKey ? -1 : a[1].sortKey > b[1].sortKey ? 1 : 0);
        });
        var cap = only === 'all' ? PER_GROUP : MAX;
        if (!L.length) return;
        h += '<div class="sg"><div class="sgh">' + g[1] + '<span class="n">' + L.length + '</span>'
          + (L.length > cap && only === 'all' ? '<button class="linkbtn" data-more="' + g[0] + '">全部 ' + L.length + ' 个</button>' : '')
          + '</div>';
        L.slice(0, cap).forEach(function (p) {
          var it = p[1], k = rows.length;
          rows.push(it);
          h += self.row(it, k, terms);
        });
        if (L.length > cap && only !== 'all') h += '<p class="hint">只列前 ' + cap + ' 个，再多打几个字缩小范围。</p>';
        h += '</div>';
      });
      if (!h) {
        // 名字里没有、路径里有（「entrypoints」下面一堆函数，但没有函数叫这个名字）：说清楚，给个按路径找的入口
        var alt = terms.map(function (w) { return /[./]/.test(w) ? w : w + '/'; }).join(' '), n = 0;
        var altTerms = alt.split(' ');
        for (var j = 0; j < items.length && !n; j++)
          if ((only === 'all' || items[j].t === only) && score(items[j], altTerms, null) >= 0) n = 1;
        h = '<p class="hint">没有' + (only === 'all' ? '模块、文件或函数' : ({ mod: '模块', file: '文件', sym: '类 / 函数' })[only])
          + '的名字里带「' + esc(q) + '」。'
          + (n ? '<br>要找路径在它下面的，<button class="linkbtn" data-alt="' + esc(alt) + '">按路径找「' + esc(alt) + '」</button>' : '')
          + '</p>';
      }
      box.innerHTML = h;
      var altBtn = box.querySelector('[data-alt]');
      if (altBtn) altBtn.onclick = function () {
        var input = document.getElementById('sq');
        input.value = altBtn.dataset.alt; q = input.value; cur = -1; self.run(); input.focus();
      };
      [].forEach.call(box.querySelectorAll('.sr'), function (b) {
        b.onclick = function (ev) { self.act(rows[+b.dataset.k], !!ev.target.closest('[data-code]')); };
      });
      [].forEach.call(box.querySelectorAll('[data-more]'), function (b) {
        b.onclick = function () { only = b.dataset.more; cur = -1; self.run(); };
      });
      this.paintCur();
      // 图上：包含命中的模块 / 文件 / 函数的节点都高亮
      this.hits = by.mod.map(function (p) { return [p[1].id, p[1].kind]; })
        .concat(by.file.concat(by.sym).filter(function (p) { return p[1].unit; })
          .map(function (p) { return [p[1].unit, 'unit']; }));
      this.highlight(this.hits);
    },

    row: function (it, k, terms) {
      var icon, main, sub, meta = '', loc = '';
      if (it.t === 'mod') {
        icon = '<span class="si m">' + (it.kind === 'dir' ? 'D' : 'M') + '</span>';
        main = mark(it.show, terms);
        meta = it.kind === 'dir' ? '目录 · ' + it.nf + ' 个文件' : '文件级模块';
        sub = '';
      } else if (it.t === 'file') {
        icon = '<span class="si f">F</span>';
        main = mark(it.name, terms);
        sub = esc(it.f.split('/').slice(0, -1).join('/'));
        loc = '<span class="sloc" data-code title="直接在全文窗口里打开">代码</span>';
      } else {
        icon = '<span class="si ' + (it.k === 'c' ? 'c' : 'fn') + '">' + (it.k === 'c' ? 'C' : 'f') + '</span>';
        main = mark(it.q, terms);
        sub = esc(it.f.split('/').pop() + ':' + it.l);
        loc = '<span class="sloc" data-code title="直接在全文窗口里打开到这一行">代码</span>';
      }
      return '<button class="sr" data-k="' + k + '" role="option">' + icon
        + '<span class="sm"><span class="sn">' + main + '</span>'
        + (sub ? '<span class="ss">' + sub + '</span>' : '') + (meta ? '<span class="ss">' + meta + '</span>' : '')
        + '</span>' + loc + '</button>';
    },

    paintCur: function () {
      [].forEach.call(document.querySelectorAll('#sbr .sr'), function (b) {
        var on = +b.dataset.k === cur;
        b.classList.toggle('cur', on);
        b.setAttribute('aria-selected', on);
        if (on) b.scrollIntoView({ block: 'nearest' });
      });
    },

    /* 打开一个结果：先在图上展开到它所在的模块并选中，再在下面的详情里展开到它。
       code：点的是「代码」——直接开全文窗口 */
    act: function (it, code) {
      if (!it) return;
      // 搜索栏浮在图上：选了一条之后只留搜索框，结果列表收起来，少挡住图（再点搜索框就回来）
      if (!code) document.getElementById('sbar').classList.add('mini');
      if (it.t === 'mod') { CS.app.revealNode(it.id, it.kind); return; }
      if (code || !it.unit) { CS.viewer.open(it.f, it.t === 'sym' ? it.l : 1); return; }   // C++ 文件不属于任何模块节点
      CS.app.revealNode(it.unit, 'unit').then(function (node) {
        // 图上没有它的节点（空的 __init__.py 之类）：详情面板没有它的文件树，只能开全文窗口
        if (!node) { CS.viewer.open(it.f, it.t === 'sym' ? it.l : 1); return null; }
        CS.app.drawer(true);                       // 文件 / 类 / 函数在下面的详情抽屉里展开
        return CS.panel.focusIn(it.f, it.t === 'sym' ? it.key : null, it.l);
      }).then(function (row) {
        // 先让人看到图上选中的是哪个模块，再往下滚到详情里的这一项
        if (row) setTimeout(function () { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 900);
      });
    },

    /* 图上高亮：命中项所在的节点。换了切面（重画）之后 app 会再调一次 */
    highlight: function (list) {
      if (!CS.graph || !CS.graph.highlight || !CS.app || !CS.app.data) return;
      var lanes = CS.app.lanesMode() && CS.lanes;   // 分列：每列按自己画着的节点找（各列切面不一样），描那一份
      if (!list.length) { if (lanes) CS.lanes.highlight(null); else CS.graph.highlight(null); return; }
      // 命中常有上万条，落到的模块只有一两千个：先去重再找节点（早先每条都找一遍，敲一个字要 200ms）
      var hit = {}, seen = {}, uniq = [];
      list.forEach(function (p) { if (!seen[p[0]]) { seen[p[0]] = 1; uniq.push(p); } });
      if (lanes) {
        Object.keys(CS.lanes.laneIx || {}).forEach(function (lane) {
          var g = CS.lanes.asGraph(lane);
          if (g.nodes.length) uniq.forEach(function (p) { var h = CS.app.homeOf(p[0], p[1], g); if (h) hit[lane + '|' + h] = 1; });
        });
        CS.lanes.highlight(function (id, lane) { return !!hit[lane + '|' + id]; });
        return;
      }
      uniq.forEach(function (p) { var h = CS.app.homeOf(p[0], p[1]); if (h) hit[h] = 1; });
      CS.graph.highlight(function (n) { return !!hit[n.id]; });
    },

    /* 图重画了（换切面、切 hot 视图）：高亮按新图重新套 */
    reapply: function () { if (q && this.hits) this.highlight(this.hits); },

    clear: function () {
      var input = document.getElementById('sq');
      if (input) input.value = '';
      q = ''; this.run();
    }
  };
})(window.CS);
