/* 入口：把数据源、图、两个面板串起来。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // 「2026-09-27T15:34:10-0400」→「09-27 15:34」
  /* 复制到剪贴板：serve 在 127.0.0.1 上是安全上下文，用 Clipboard API；导出的单文件（file://）
     或被拒绝时退回选中一个临时 textarea 再 execCommand('copy')。结果是 Promise<是否成功> */
  function copyText(t) {
    function legacy() {
      var ta = document.createElement('textarea');
      ta.value = t;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      return ok;
    }
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(t).then(function () { return true; }, function () { return legacy(); });
    }
    return Promise.resolve(legacy());
  }
  function shortTime(t) { var m = /^\d{4}-(\d\d-\d\d)T(\d\d:\d\d)/.exec(t || ''); return m ? m[1] + ' ' + m[2] : (t || ''); }

  CS.app = {
    data: null,

    boot: function () {
      var self = this;
      // 先定叠哪个 run（URL hash → serve --hot → 只看静态图），再取图
      this.initRuns().then(function () {
        return CS.ds.graph(null, CS.graph.boxWidth());
      }).then(function (d) {
        self.data = d;
        self.header(d);
        CS.panel.init(document.getElementById('det'), document.getElementById('side'), d);
        CS.graph.onPick = function (id) { CS.panel.showPkg(id); CS.panel.showNote(id); self.drawerTitle(id); };
        CS.graph.onPickEdge = function (a, b) { CS.panel.showEdge(a, b); CS.panel.showEdgeSide(a, b); self.drawerTitle(null, a, b); };
        CS.graph.onCollapse = function (f) { self.collapseFrame(f); };
        CS.graph.onClear = function () { CS.panel.reset(); self.drawerTitle(); };
        CS.graph.onSelectFrame = function (f) {
          var t = document.getElementById('dtitle'); if (t) t.textContent = f;
          var s = document.getElementById('dsub'); if (s) s.textContent = '已在图上展开成框（框头的 − 收起）';
        };
        self.wireDrawer();
        CS.graph.onExpand = function (id) {
          if (!CS.ds.canCut) { document.getElementById('prog').textContent = '导出的单文件不能展开，请用 codestrata serve'; return; }
          self.expand(id);
        };
        CS.graph.draw(document.getElementById('g'), d.graph, d.hot,
                      { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges, dynOnly: d.dynOnlyEdges, typeOnly: d.typeOnlyEdges, cmp: d.cmp });
        self.edgeChips();
        self.controls();
        self.cutBar();
        self.refreshStatus();
        self.footer(d);
        if (self._runMissing && CS.viewer) CS.viewer.toast(self._runMissing);
        else if (self._cmpMissing && CS.viewer) { CS.viewer.toast(self._cmpMissing); self._writeHash(); }   // 进度栏会被解读统计盖掉，用浮层提示
        // 选中从别处变了（Esc、点空白、搜索、抽屉里的链接、切面变了之后的保留选中）：时序图上的高亮跟着变
        ['onClear', 'onPick', 'onPickEdge', 'onSelectFrame'].forEach(function (h) {
          var orig = CS.graph[h];
          CS.graph[h] = function () {
            // 抽屉里写的「刚点的那条消息」：选了别的（或别的边）就不再是它了
            var pm = CS.seq && CS.seq.picked;
            if (pm && (h !== 'onPickEdge' || pm.a + '|' + pm.b !== CS.graph.state.selEdge)) CS.seq.picked = null;
            var r = orig.apply(this, arguments);
            if (self.view === 'seq' && CS.seq.data) CS.seq.render();
            return r;
          };
        });
        if (/(?:^#|&)view=seq(?:&|$)/.test(location.hash || '')) self.setView('seq');
        if (CS.search) CS.search.init();
        // 窗口宽度变了不少：按新的宽度重新排版（切面、选中、缩放都不变）
        self._w = CS.graph.boxWidth();
        var rt = 0;
        window.addEventListener('resize', function () {
          clearTimeout(rt);
          rt = setTimeout(function () {
            if (CS.ds.canCut && Math.abs(CS.graph.boxWidth() - self._w) >= 80) self.setCut(self.curOpen());
          }, 350);
        });
      }).catch(function (e) {
        document.getElementById('h1').textContent = '加载失败';
        document.getElementById('lede').textContent = e.message;
      });
    },

    /* 浮着的栏（搜索、详情）拖边框改大小。edges：l / r / t / b / lb；apply(edge, 起始矩形, dx, dy) 改尺寸，
       松开鼠标时 done() 记下来 */
    resizable: function (el, edges, apply, done) {
      edges.forEach(function (e) {
        var h = document.createElement('div');
        h.className = 'rz rz-' + e; h.title = '拖动改变大小';
        el.appendChild(h);
        h.addEventListener('mousedown', function (ev) {
          if (ev.button !== 0) return;
          ev.preventDefault(); ev.stopPropagation();
          var r0 = el.getBoundingClientRect(), x0 = ev.clientX, y0 = ev.clientY;
          document.body.classList.add('rzing');
          function mv(e2) { apply(e, r0, e2.clientX - x0, e2.clientY - y0); }
          function up() {
            window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up);
            document.body.classList.remove('rzing');
            if (done) done();
          }
          window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
        });
        h.addEventListener('click', function (ev) { ev.stopPropagation(); });
      });
    },

    _load: function (k) { try { return JSON.parse(localStorage.getItem(k) || '{}'); } catch (e) { return {}; } },
    _save: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 隐私模式 */ } },

    /* 详情栏：浮在图的下沿，展开 / 收起、拖边框改大小（都记在浏览器里）；收起时标题写着选中的是什么 */
    wireDrawer: function () {
      var dr = document.getElementById('drawer'), gw = document.getElementById('gwrap'), self = this;
      if (!dr || dr._wired) return;
      dr._wired = true;
      var st = this._load('codestrata.drawer');
      if (st.h) dr.style.setProperty('--dh', st.h + 'px');
      if (st.l != null) dr.style.setProperty('--dl', st.l + 'px');
      if (st.r != null) dr.style.setProperty('--dr', st.r + 'px');
      this.drawer(!!st.open, true);
      document.getElementById('dhead').onclick = function () { self.drawer(!dr.classList.contains('open')); };
      this.resizable(dr, ['t', 'l', 'r'], function (e, r0, dx, dy) {
        var g = gw.getBoundingClientRect();
        if (e === 't') {
          if (!dr.classList.contains('open')) self.drawer(true, true);
          dr.style.setProperty('--dh', Math.max(120, Math.min(g.height - 20, r0.height - dy)) + 'px');
        } else if (e === 'l') {
          dr.style.setProperty('--dl', Math.max(0, Math.min(r0.right - g.left - 320, r0.left - g.left + dx)) + 'px');
        } else {
          dr.style.setProperty('--dr', Math.max(0, Math.min(g.right - r0.left - 320, g.right - r0.right - dx)) + 'px');
        }
        self._roomForDrawer();
      }, function () { self._saveDrawer(); });
      window.addEventListener('resize', function () { self._roomForDrawer(); });
    },

    drawer: function (open, quiet) {
      var dr = document.getElementById('drawer');
      if (!dr) return;
      dr.classList.toggle('open', open);
      document.getElementById('dtog').setAttribute('aria-expanded', open);
      if (!quiet) this._saveDrawer();
      this._roomForDrawer();
    },

    /* 详情栏盖住了图的下沿：图框底下留出同样的空白，最下面的泳道能滚到它上面来；
       搜索栏的最大高度也让着它 */
    _roomForDrawer: function () {
      var dr = document.getElementById('drawer'), gw = document.getElementById('gwrap'), box = gw && gw.querySelector('.gbox');
      if (!dr || !box) return;
      var h = dr.getBoundingClientRect().height + 20;
      box.style.paddingBottom = h + 'px';
      gw.style.setProperty('--dnow', h + 'px');
    },

    _saveDrawer: function () {
      var dr = document.getElementById('drawer'), v = function (n) { var x = parseFloat(dr.style.getPropertyValue(n)); return isNaN(x) ? undefined : x; };
      this._save('codestrata.drawer', { open: dr.classList.contains('open'), h: v('--dh'), l: v('--dl'), r: v('--dr') });
    },

    drawerTitle: function (id, a, b) {
      var t = document.getElementById('dtitle'), s = document.getElementById('dsub');
      if (!t) return;
      var v = id && (this.data.pkgs || {})[id];
      if (id) {
        t.textContent = id;
        s.textContent = v ? v.files + ' 个文件 · ' + v.classes + ' 个类 · ' + v.funcs + ' 个函数' : '';
      } else if (a) {
        t.textContent = CS.panel.short(a) + ' → ' + CS.panel.short(b);
        s.textContent = (CS.graph.edgeInfo(a, b) || {}).kind === 'type' ? '只在 if TYPE_CHECKING: 里 import：运行时不存在，不算依赖'
                      : '这条依赖具体用了对方哪些函数 / 类';
        var pm = CS.seq && CS.seq.picked;
        if (this.view === 'seq' && pm && pm.a === a && pm.b === b) s.textContent = this._msgText(pm);
        if (this.view !== 'seq' && this._runHasEvents()) {
          var sb = document.createElement('button');
          sb.className = 'chip'; sb.style.marginLeft = '10px'; sb.textContent = '在时序图里看';
          sb.title = '跳到这个 run 里这条边第一次被调用的时刻';
          var self = this;
          sb.onclick = function (ev) { ev.stopPropagation(); self.seqFindEdge(a, b); };
          s.appendChild(sb);
        }
      } else {
        t.textContent = '详情';
        s.textContent = '点图上的节点或箭头，在这里看它的文件、类 / 函数和解读';
      }
    },

    /* 「?」帮助：说明、操作、这次 trace 的情况 */
    wireHelp: function () {
      var b = document.getElementById('helpBtn'), p = document.getElementById('help'), self = this;
      if (!b || b._wired) return;
      b._wired = true;
      b.onclick = function (ev) { ev.stopPropagation(); self.help(p.hidden); };
      document.getElementById('helpX').onclick = function () { self.help(false); };
      document.addEventListener('mousedown', function (ev) {         // 点别处关掉
        if (!p.hidden && !p.contains(ev.target) && ev.target !== b && !ev.target.closest('[data-help]')) self.help(false);
      });
    },

    help: function (on) {
      var p = document.getElementById('help');
      p.hidden = !on;
      document.getElementById('helpBtn').setAttribute('aria-expanded', on);
    },

    /* 帮助里「这次跑了什么」：复刻命令、阶段怎么切的、case 命令、脚本内容、被 trace 的进程
       （按命令合并，跑到仓库代码多的在前） */
    runHtml: function (m) {
      this._runMeta = m;
      var h = '<h3>这次跑了什么</h3><div class="run">';
      if (m.rerun) {
        var ev = m.env_inherited || {}, ks = Object.keys(ev);
        h += '<div class="rerun" id="rerun"><div class="rerun-h"><span class="lab">复刻这次录制</span>'
          + '<button class="chip copy" data-copy="rerun" title="复制这条命令（在终端里粘贴就能重录一次）">复制</button></div>'
          + '<pre class="rerun-cmd">' + esc(m.rerun) + '</pre>'
          + (m.rerun_exact ? '' : '<div class="lab warn">这个 run 录的时候还没存原始命令：上面是按 run 里存的参数拼的，'
             + 'codestrata 按 PATH 找，仓库路径是现在这个仓库的，执行目录不是仓库根目录的写成 --cwd</div>')
          + (CS.ds.public ? '<div class="lab warn">这是公开页：路径里的主目录写成了 ~，PATH 这类目录列表里项目以外的部分'
             + '省略成了 …，所以命令不能原样执行；原样的在录制的机器上用 <code>codestrata runs &lt;repo&gt; show '
             + esc(m.run_id) + '</code> 看</div>' : '')
          + (m.rerun_redacted ? '<div class="lab warn">命令里像密钥的值（--env 里的、--api-key 这类选项的）和 URL 里的账号密码'
             + '已隐去，写成 &lt;已隐去&gt;；下面的 case 命令和进程表也一样。完整的命令用 <code>codestrata runs &lt;repo&gt; show '
             + esc(m.run_id) + '</code> 看</div>' : '')
          + (ks.length ? '<details class="envinh"><summary><span class="lab">录制时 shell 里还有 ' + ks.length
             + ' 个相关的环境变量（不在命令里；被 trace 的命令会继承它们，复刻时要一样）</span></summary>'
             + '<div class="rerun-h"><span class="lab">连环境变量一起</span>'
             + (m.rerun_env ? '<button class="chip copy" data-copy="rerun_env" title="前面用 env 带上这些变量">复制</button>' : '')
             + '</div><pre>' + esc(ks.map(function (k) { return k + '=' + ev[k]; }).join('\n')) + '</pre></details>' : '')
          + '</div>';
      }
      h += this.phaseHtml(m);
      h += '<div class="cmdline"><span class="lab">case 命令</span><code>'
        + esc((m.cmd || []).join(' ')) + '</code></div>';
      var P = m.procs || [];
      if (P.length) {
        var n = 0; P.forEach(function (p) { n += p.n; });
        h += '<div class="lab">被 trace 的 ' + n + ' 个 Python 进程（同一条命令的合在一起；跑到仓库代码多的在前）</div><table class="procs">'
          + P.map(function (p) {
            var a = (p.argv || []).join(' ');
            return '<tr' + (p.funcs ? '' : ' class="idle"') + '><td class="pn">' + p.n + ' ×</td><td><code>' + esc(a || '（没记下命令）')
              + '</code>' + (p.cut ? ' <span class="lab">…（这份 trace 是老版本录的，只存了前 6 个参数；重新 trace 就是完整的）</span>' : '')
              + '</td><td class="pf">' + (p.funcs ? p.funcs + ' 个函数' : '没跑到仓库代码') + '</td></tr>';
          }).join('') + '</table>';
      }
      if (m.script) {
        h += '<details class="script"' + '><summary><span class="lab">case 脚本</span> <code>' + esc(m.script.path) + '</code>'
          + (m.script.saved ? '（录制时的内容）' : '（<span style="color:var(--stale)">录制时没存，这是现在的内容</span>）')
          + '</summary><pre>' + esc(m.script.text) + '</pre></details>';
      }
      return h + '</div>';
    },

    /* 各阶段从什么时候开始、怎么切的：--phase 的写「第一次进入某函数」，其余是 case 脚本写 PHASE 切的 */
    phaseHtml: function (m) {
      // 每一条是 [名字, t_us, 来源]：start / hook（--phase，第一次进入某个函数）/ sh（case 脚本写 PHASE）；
      // 老的 run 没有来源，一律当 case 脚本写的。表用 Object.create(null)：阶段名可能叫 constructor
      var log = m.phase_log || [], at = Object.create(null), fired = Object.create(null), byHook = Object.create(null);
      (m.phase_at || []).forEach(function (t) { at[t.name] = t; });
      log.forEach(function (x) { if (x[2] === 'hook') byHook[x[0]] = 1; });
      if (log.length < 2 && !(m.phase_at || []).length) return '';
      var rows = log.map(function (x) {
        var src = x[2] || (x[0] === 'start' ? 'start' : 'sh'), t = src === 'hook' ? at[x[0]] : null;
        fired[x[0]] = 1;
        return '<tr><td><b>' + esc(x[0]) + '</b></td><td class="pn">' + (x[1] == null ? '—' : (x[1] / 1e6).toFixed(2) + ' s')
          + '</td><td>' + (src === 'start' ? '<span class="lab">录制开始</span>'
             : t ? '第一次进入 <code>' + esc(t.qualname) + '</code> <span class="lab">' + esc(t.file) + ':' + esc(t.line) + '</span>'
             : src === 'hook' ? '<span class="lab">--phase</span>'
             : '<span class="lab">case 脚本写 PHASE</span>'
               + (at[x[0]] && !byHook[x[0]] ? '<span class="lab warn">（同名的 --phase 没起作用）</span>' : ''))
          + '</td></tr>';
      });
      (m.phase_at || []).forEach(function (t) {
        if (!fired[t.name]) rows.push('<tr class="idle"><td><b>' + esc(t.name) + '</b></td><td class="pn">—</td><td>没切到：<code>'
          + esc(t.qualname) + '</code> 这次没被调用</td></tr>');
      });
      return '<div class="lab">阶段（每段从这个时刻开始，直到下一段）</div><table class="procs phases">' + rows.join('') + '</table>';
    },

    wireRun: function () {
      var hb = document.getElementById('hotbanner'), self = this;
      if (!hb || hb._wiredCopy) return;
      hb._wiredCopy = 1;
      hb.addEventListener('click', function (ev) {
        var b = ev.target.closest('[data-copy]'), m = self._runMeta;
        if (!b || !m) return;
        copyText(m[b.dataset.copy] || '').then(function (ok) {
          b.textContent = ok ? '已复制' : '复制不了，请手动选中';
          setTimeout(function () { b.textContent = '复制'; }, 1600);
        });
      });
    },

    /* 「复刻」按钮：打开帮助、滚到复刻命令那里 */
    showRerun: function () {
      this.help(true);
      var r = document.getElementById('rerun');
      if (!r) return;
      r.scrollIntoView({ block: 'nearest' });
      r.classList.remove('flash');
      void r.offsetWidth;
      r.classList.add('flash');
    },

    /* ---- 叠哪个 run：静态图 / 某一次录下的运行，分了阶段的再选阶段。
       选中的是「完整 id@阶段」，放在 CS.ds.run（叠加相关的请求都带上它）和 URL hash 里 ---- */
    _hashRun: function () {
      var m = /(?:^#|&)run=([^&]*)/.exec(location.hash || '');
      return m ? decodeURIComponent(m[1]) : null;
    },

    _writeHash: function () {
      var rest = (location.hash || '').replace(/^#/, '').split('&').filter(function (x) { return x && !/^(run|view|cmp)=/.test(x); });
      if (this.view === 'seq') rest.unshift('view=seq');
      if (CS.ds.cmp && CS.ds.run) rest.unshift('cmp=' + encodeURIComponent(CS.ds.cmp).replace(/%40/g, '@'));
      if (CS.ds.run) rest.unshift('run=' + encodeURIComponent(CS.ds.run).replace(/%40/g, '@'));
      history.replaceState(null, '', location.pathname + location.search + (rest.length ? '#' + rest.join('&') : ''));
    },

    initRuns: function () {
      var self = this;
      return CS.ds.runs().then(function (r) {
        self.runList = r.runs || [];
        self.runListEmbedded = !!r.embedded;
        self._known = {};
        self.runList.forEach(function (x) { self._known[x.id] = 1; });
        var want = self._hashRun();
        if (want === null) want = r.default || '';
        if (want && CS.ds.canSwitchRun) {
          var id = want.split('@')[0];
          var hit = self.runList.filter(function (x) { return x.id === id || x.case === id; })[0];
          if (!hit || !hit.loadable) {
            self._runMissing = '地址里的 run ' + want + (hit ? ' 还没有计数（还在录，或录制中断了要 runs merge）'
                                                           : ' 找不到了（删了？）') + '，先只看静态图';
            want = '';
          }
        }
        if (CS.ds.canSwitchRun) CS.ds.run = want;
        var c = /(?:^#|&)cmp=([^&]*)/.exec(location.hash || '');
        if (c && want && CS.ds.canSwitchRun && !r.embedded) {
          // 地址里的对比 run 也要核一遍：找不到、还没有计数、和主 run 是同一个，都不带上（否则整张图出不来）
          var cr = decodeURIComponent(c[1]), cid = cr.split('@')[0], aid = want.split('@')[0];
          var ch = self.runList.filter(function (x) { return x.id === cid || x.case === cid; });
          var ah = self.runList.filter(function (x) { return x.id === aid || x.case === aid; })[0];
          var okc = ch.length && ch[0].loadable && !(ah && ch[0].id === ah.id && (cr.split('@')[1] || '') === (want.split('@')[1] || ''));
          if (okc) CS.ds.cmp = cr;
          else self._cmpMissing = '地址里对比的 run ' + cr + (ch.length ? ' 不能用来对比' : ' 找不到了') + '，只看 ' + want;
        }
        self.wireRunSel();
      }).catch(function () { self.runList = []; self._known = {}; self.wireRunSel(); });
    },

    /* 列表里某个 run 默认看哪个阶段：有 serving 就只看 serving（启动时的初始化会淹没请求本身） */
    _defaultPhase: function (x) {
      return (x.phases || []).some(function (p) { return p.name === 'serving'; }) ? 'serving' : '';
    },

    selectRun: function (id, phase) {
      var self = this, prev = CS.ds.run;
      if (CS.seq) CS.seq.reset();                     // 换了 run：时序图的窗口从新 run 的阶段起点重来
      var prevCmp = CS.ds.cmp;
      CS.ds.run = id ? id + (phase ? '@' + phase : '') : '';
      if (!id || (CS.ds.cmp && CS.ds.cmp.split('@')[0] === id)) CS.ds.cmp = '';   // 不能和自己比
      else if (CS.ds.cmp) {                          // 换了 A 的阶段：B 跟着换成同名的阶段（没有就全部）
        var bx = (this.runList || []).filter(function (x) { return x.id === CS.ds.cmp.split('@')[0]; })[0];
        if (bx) CS.ds.cmp = bx.id + this._cmpPhase(bx, phase || '');
      }
      this._writeHash();
      this.closeRunPop();
      var p = this.setCut(this.curOpen()), mine = this._cutSeq;
      document.getElementById('prog').textContent = id ? '叠加 run ' + id + (phase ? ' @' + phase : '') + '…' : '重新汇总…';
      return p.then(function (ok) {
        // 换不过去（run 被删了、还没有计数）：退回原来那个，免得之后取边、引用、输入包用的是另一个 run
        if (!ok && self._cutSeq === mine) {
          CS.ds.run = prev;
          CS.ds.cmp = prevCmp;
          self._writeHash();
          self.runBar();
          if (CS.viewer) CS.viewer.toast('换不过去：' + document.getElementById('prog').textContent);
        }
        return ok;
      });
    },

    /* ---- 对比：另一个 run，模块图上三种颜色 ---- */
    cmpBar: function () {
      var self = this, cb = document.getElementById('cmpchips');
      if (!cb) return;
      var d = this.data, m = d && d.hot && d.hotMeta;
      var c = d && d.cmp;
      if (m && c && this.runListEmbedded) {            // 导出版：对比是导出时定好的，只显示、不能换
        cb.innerHTML = '<span class="lbl">对比</span><span class="chip runbtn onb" title="导出时用 --compare 定好的对比；要换请用 codestrata serve">'
          + esc((c.meta_b || {}).case || '?') + ' · ' + esc(shortTime((c.meta_b || {}).created)) + '</span>';
        return;
      }
      var canCmp = m && CS.ds.canSwitchRun && !(this.runListEmbedded) && (this.runList || []).length > 1;
      if (!canCmp) { cb.innerHTML = ''; return; }
      cb.innerHTML = '<span class="lbl">对比</span><span class="runsel"><button class="chip runbtn' + (c ? ' onb' : '') + '" id="cmpbtn"'
        + ' title="和另一个 run 对比：只有这个 run 跑到的橙色，只有另一个跑到的紫色，两边都跑到的前景色">'
        + (c ? esc((c.meta_b || {}).case || '?') + ' · ' + esc(shortTime((c.meta_b || {}).created)) : '无') + '</button>'
        + '<div class="runpop" id="cmppop" role="menu" aria-label="选择对比的 run" hidden></div></span>';
      var b = document.getElementById('cmpbtn'), pop = document.getElementById('cmppop');
      b.onclick = function (e) {
        e.stopPropagation();
        if (!pop.hidden) { pop.hidden = true; return; }
        self.closeRunPop();
        self.refreshRuns(false).then(function () {
          self.renderCmpPop(pop); pop.hidden = false;
          var f = pop.querySelector('[aria-current=true]') || pop.querySelector('.rr');
          if (f) f.focus();
        });
      };
      if (!this._cmpWired) {
        this._cmpWired = true;
        document.addEventListener('click', function (e) {
          var p = document.getElementById('cmppop');
          if (p && !p.hidden && !p.contains(e.target)) p.hidden = true;
        });
        document.addEventListener('keydown', function (e) {
          var p = document.getElementById('cmppop');
          if (e.key === 'Escape' && p && !p.hidden) {
            e.stopPropagation(); e.preventDefault(); p.hidden = true;
            var b = document.getElementById('cmpbtn'); if (b) b.focus();
          }
        }, true);
      }
    },

    renderCmpPop: function (pop) {
      var self = this, m = this.data.hotMeta, cur = (this.data.cmp || {}).ref_b || '';
      var h = '<button class="rr" role="menuitem" data-cmp="" aria-current="' + !cur + '"><span class="rt">不对比</span><span class="rm">只看 '
        + esc(m.case) + '</span><span></span></button>';
      (this.runList || []).forEach(function (x) {
        if (x.id === m.run_id || !x.loadable) return;
        var suf = self._cmpPhase(x, m.phase || ''), p = suf.slice(1);
        var ref = x.id + suf;
        h += '<button class="rr" role="menuitem" data-cmp="' + esc(ref) + '" aria-current="' + (cur.split('@')[0] === x.id) + '">'
          + '<span class="rt">' + esc(shortTime(x.created)) + '</span><span class="rm"><b>' + esc(x.case) + '</b>' + (p ? ' @' + esc(p) : '')
          + (x.events ? '　<span class="ev">时序</span>' : '') + (x.tags || []).map(function (t) { return ' <span class="tag">' + esc(t) + '</span>'; }).join('')
          + '</span><span class="rs ' + (x.status === 'ok' ? 'ok' : 'bad') + '">' + esc(x.status || '') + '</span></button>';
      });
      pop.innerHTML = h;
      [].forEach.call(pop.querySelectorAll('[data-cmp]'), function (el) {
        el.onclick = function (e) { e.stopPropagation(); pop.hidden = true; self.selectCmp(el.dataset.cmp); };
      });
    },

    /* 对比的阶段跟着 A：A 看全部就比全部；A 看某个阶段、B 也有同名的就比它；B 没有就比 B 的全部 */
    _cmpPhase: function (x, phase) {
      if (!phase) return '';
      return (x.phases || []).some(function (p) { return p.name === phase; }) ? '@' + phase : '';
    },

    selectCmp: function (ref) {
      var self = this, prev = CS.ds.cmp;
      CS.ds.cmp = ref || '';
      this._writeHash();
      var p = this.setCut(this.curOpen()), mine = this._cutSeq;
      return p.then(function (ok) {
        if (!ok && self._cutSeq === mine) { CS.ds.cmp = prev; self._writeHash(); self.cmpBar(); }
        return ok;
      });
    },

    /* ---- 模块图 | 时序图 ---- */
    _runHasEvents: function () {
      var m = this.data && this.data.hot && this.data.hotMeta;
      var x = m && (this.runList || []).filter(function (r) { return r.id === m.run_id; })[0];
      return !!(x && x.events);
    },

    _runEventsError: function () {
      var m = this.data && this.data.hot && this.data.hotMeta;
      var x = m && (this.runList || []).filter(function (r) { return r.id === m.run_id; })[0];
      return !!(x && x.events_error);
    },

    viewBar: function () {
      var self = this, vc = document.getElementById('viewchips');
      if (!vc) return;
      var m = this.data && this.data.hot && this.data.hotMeta, ev = this._runHasEvents();
      if (!m || !CS.ds.canSwitchRun || this.runListEmbedded) { vc.innerHTML = ''; return; }
      vc.innerHTML = '<span class="lbl">图</span>'
        + '<button class="chip" data-view="graph" aria-pressed="' + (this.view !== 'seq') + '" title="模块之间的依赖，橙色是这个 run 跑到的">模块图</button>'
        + '<button class="chip" data-view="seq" aria-pressed="' + (this.view === 'seq') + '"' + (ev ? '' : ' disabled')
        + ' title="' + (ev ? '这个 run 里跨模块的调用按时间排开' : this._runEventsError()
            ? '这个 run 录了时序事件，但整理成 span 时失败了：codestrata runs <repo> merge <id> 重来'
            : '这个 run 没录时序事件：录的时候加 --events（codestrata trace … --events）') + '">时序图</button>';
      [].forEach.call(vc.querySelectorAll('[data-view]'), function (b) {
        b.onclick = function () { self.setView(b.dataset.view); };
      });
    },

    setView: function (v, opts) {
      if (v === 'seq' && !this._runHasEvents()) {
        // 说清楚为什么看不了：没选 run（或地址里的 run 找不到了，那句已经提示过）、导出版、这个 run 没录事件
        var m = this.data && this.data.hot && this.data.hotMeta;
        var why = CS.ds.mode === 'embedded' ? '导出的单文件没有带时序图；要看请用 codestrata serve'
          : this._runMissing && !m ? null
          : !m ? '先在上面「运行」里选一个录了时序事件的 run'
          : this._runEventsError() ? '这个 run 的时序事件整理失败了：codestrata runs <repo> merge <id> 重来'
          : '这个 run 没录时序事件：录的时候加 --events';
        if (why && CS.viewer) CS.viewer.toast(why);
        v = 'graph';
      }
      var was = this.view, box = document.querySelector('.gbox');
      if (was === v && v === 'graph') { this.viewBar(); return; }
      // 两张图共用一个图框：各记各的滚动位置，切回来时回到原处
      this._scroll = this._scroll || {};
      if (box && was) this._scroll[was] = [box.scrollLeft, box.scrollTop];
      this.view = v;
      var g = document.getElementById('g'), ctl = document.querySelector('.gctl');
      g.style.display = v === 'seq' ? 'none' : '';
      if (ctl) ctl.style.display = v === 'seq' ? 'none' : '';
      var back = this._scroll[v];
      if (v === 'seq') {
        if (box) { box.scrollLeft = 0; box.scrollTop = 0; }
        var p = CS.seq.show(Object.assign({}, CS.seq.req || {}, opts || {}));
        if (back && !(opts && opts.focusSel)) p.then(function () { box.scrollLeft = back[0]; box.scrollTop = back[1]; });
      } else {
        CS.seq.hide();
        if (was === 'seq') {                          // 回到模块图：时序图里选中的节点 / 边在图上也选着
          this.redraw();
          var st = CS.graph.state;
          if (st.sel) CS.graph.pick(st.sel, true);
          else if (st.selEdge) { var e = st.selEdge.split('|'); CS.graph.pickEdge(e[0], e[1]); }
          if (back && box) { box.scrollLeft = back[0]; box.scrollTop = back[1]; }
        }
      }
      this._writeHash();
      this.viewBar();
      this._retitle();
    },

    /* 抽屉标题按当前视图重写（边：模块图上给「在时序图里看」，时序图上写刚点的那条消息） */
    _retitle: function () {
      var st = CS.graph.state;
      if (st.selEdge) { var e = st.selEdge.split('|'); this.drawerTitle(null, e[0], e[1]); }
    },

    _msgText: function (r) {
      return r.fa + ' → ' + r.fb + '　' + (r.t / 1e6).toFixed(3) + 's 起，用时 '
        + (r.d < 0 ? '到进程结束都没返回' : (r.d / 1000).toFixed(2) + 'ms') + (r.rep > 1 ? '（连续 ' + r.rep + ' 次合在一起）' : '')
        + (r.async ? '，async 挂起 ' + r.susp + ' 次' : '') + '　pid ' + r.pid + ' 线程 ' + r.tid + '　' + r.f + ':' + r.l;
    },

    /* 时序图上点生命线头 = 选中这个模块；点消息 = 选中这条边，抽屉里再写上这条消息的时刻 */
    // 不强行打开抽屉：点的那一行会被盖住（抽屉的标题栏一直看得见，详情点开它看）
    seqPickNode: function (id) {
      var st = CS.graph.state;
      if (st.sel === id) { CS.graph.clear(); return; }
      CS.graph.pick(id, true);
    },

    seqPickMsg: function (r) {
      CS.seq.picked = r;
      CS.graph.pickEdge(r.a, r.b);
    },

    /* 模块图上选中一条边时，抽屉标题栏里给个「在时序图里看」：跳到这条边第一次出现的时刻 */
    seqFindEdge: function (a, b) {
      var self = this;
      CS.ds.seqFind(a, b, -1, this.curOpen()).then(function (hit) {
        CS.seq.req = { t0: Math.max(0, hit.t - 1) };
        if (self.view === 'seq') CS.seq.show({ t0: Math.max(0, hit.t - 1), focusSel: true });
        else self.setView('seq', { focusSel: true });
      }).catch(function (e) { if (CS.viewer) CS.viewer.toast(e.message); });
    },

    runBar: function () {
      var self = this, b = document.getElementById('runbtn'), pc = document.getElementById('phasechips');
      if (!b) return;
      var d = this.data, m = d && d.hot && d.hotMeta;
      if (!m && CS.graph.state.onlyHot) {       // 换成了静态图：「只看跑到的」没有意义了（不关掉会把节点全藏起来）
        CS.graph.state.onlyHot = false;
        var oh = document.querySelector('[data-t="onlyhot"]');
        if (oh) oh.setAttribute('aria-pressed', 'false');
      }
      b.classList.toggle('on', !!m);
      b.textContent = m ? m.case + ' · ' + shortTime(m.created) : '静态图';
      var rb = document.getElementById('rerunbtn');
      if (rb) {
        rb.hidden = !(m && m.rerun);
        rb.onclick = function () { self.showRerun(); };
      }
      b.title = !CS.ds.canSwitchRun ? '导出的单文件固定叠这一个（或不叠）；要换请用 codestrata serve'
        : m ? 'run ' + m.run_id + '（点开换一个）' : '现在只看静态图；点开选一次录下的运行叠上去';
      var run = m && (this.runList || []).filter(function (x) { return x.id === m.run_id; })[0];
      var phases = run ? run.phases : m ? Object.keys(m.phases || {}).map(function (k) { return { name: k, n_funcs: m.phases[k] }; }) : [];
      this.viewBar();
      this.cmpBar();
      if (!m || phases.length < 2 || !CS.ds.canSwitchRun || this.runListEmbedded) { pc.innerHTML = ''; return; }
      var at = Object.create(null), hook = Object.create(null);
      (m.phase_at || []).forEach(function (t) { at[t.name] = t; });
      (m.phase_log || []).forEach(function (x) { if (x[2] === 'hook') hook[x[0]] = 1; });
      pc.innerHTML = '<span class="lbl">阶段</span>' + [{ name: '' }].concat(phases).map(function (p) {
        return '<button class="chip" data-ph="' + esc(p.name) + '" aria-pressed="' + ((m.phase || '') === p.name) + '" title="'
          + (p.name ? '只看 ' + esc(p.name) + ' 这一段' + (p.n_funcs != null ? '（' + p.n_funcs + ' 个函数）' : '')
             + (at[p.name] && hook[p.name] ? '；从第一次进入 ' + esc(at[p.name].qualname) + ' 开始' : '') : '各阶段加在一起')
          + '">' + (p.name ? esc(p.name) : '全部') + '</button>';
      }).join('');
      [].forEach.call(pc.querySelectorAll('[data-ph]'), function (x) {
        x.onclick = function () { if ((m.phase || '') !== x.dataset.ph) self.selectRun(m.run_id, x.dataset.ph); };
      });
    },

    wireRunSel: function () {
      var self = this, b = document.getElementById('runbtn'), pop = document.getElementById('runpop');
      if (!b || b._wired) return;
      b._wired = 1;
      if (!CS.ds.canSwitchRun) { b.disabled = true; return; }
      b.onclick = function (e) { e.stopPropagation(); if (pop.hidden) self.openRunPop(); else self.closeRunPop(); };
      document.addEventListener('click', function (e) {
        if (!pop.hidden && !pop.contains(e.target) && e.target !== b) self.closeRunPop();
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !pop.hidden) { e.stopPropagation(); e.preventDefault(); self.closeRunPop(); b.focus(); }
      }, true);
      // serve 开着的时候又录了一个：回到页面时刷新列表，有新的只在按钮上加个点，不自动切过去
      window.addEventListener('focus', function () { self.refreshRuns(true); });
    },

    refreshRuns: function (quiet) {
      var self = this;
      if (!CS.ds.canSwitchRun) return Promise.resolve();
      return CS.ds.runs().then(function (r) {
        var fresh = (r.runs || []).some(function (x) { return !self._known[x.id]; });
        self.runList = r.runs || [];
        if (fresh && quiet) document.getElementById('rundot').hidden = false;
        if (!quiet) self.runList.forEach(function (x) { self._known[x.id] = 1; });
      }).catch(function () {});
    },

    openRunPop: function () {
      var self = this, pop = document.getElementById('runpop'), b = document.getElementById('runbtn');
      var cp = document.getElementById('cmppop'); if (cp) cp.hidden = true;   // 两个下拉不同时开
      document.getElementById('rundot').hidden = true;
      pop.hidden = false;
      b.setAttribute('aria-expanded', 'true');
      pop.innerHTML = '<div class="empty">读取 run 列表…</div>';
      this.refreshRuns(false).then(function () { if (!pop.hidden) self.renderRunPop(); });
    },

    closeRunPop: function () {
      var pop = document.getElementById('runpop'), b = document.getElementById('runbtn');
      if (!pop || pop.hidden) return;
      pop.hidden = true;
      b.setAttribute('aria-expanded', 'false');
    },

    renderRunPop: function () {
      var self = this, pop = document.getElementById('runpop'), list = this.runList || [];
      var hm = this.data && this.data.hot && this.data.hotMeta;
      // 导出版：同一个 run 的两个阶段可能是两行，按「id@阶段」认
      var cur = hm ? (this.runListEmbedded ? hm.run_id + (hm.phase ? '@' + hm.phase : '') : hm.run_id) : '';
      var keyOf = function (x) { return x.ref || x.id; };
      var h = '<button class="rr" role="menuitem" data-run="" aria-current="' + !cur + '"><span class="rt">静态图</span>'
        + '<span class="rm">不叠 runtime，只看 import 结构</span><span></span></button>';
      if (!list.length) {
        h += '<div class="empty">还没有录下的 run。录一个：<code>codestrata trace &lt;repo&gt; --case NAME -- 命令</code></div>';
      }
      var order = [], by = {};
      list.forEach(function (x) { if (!by[x.case]) { by[x.case] = []; order.push(x.case); } by[x.case].push(x); });
      order.forEach(function (c) {
        h += '<div class="rg">' + esc(c) + '</div>';
        by[c].forEach(function (x) {
          var ok = x.status === 'ok', ph = (x.phases || []).filter(function (p) { return p.name; });
          var meta = (x.tags || []).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')
            + (x.git ? 'git <b>' + esc(x.git.slice(0, 8)) + '</b>　' : '')
            + (x.n_procs_active != null ? x.n_procs_active + ' 个进程　' : '')
            + (ph.length > 1 ? ph.map(function (p) { return esc(p.name) + ' ' + p.n_funcs; }).join(' / ') + '　'
               : x.n_funcs != null ? x.n_funcs + ' 个函数　' : '')
            + (x.events ? '<span class="ev" title="录了时序事件">时序</span>　' : '')
            + (x.stale && x.stale.changed ? '<span style="color:var(--stale)">⚠ 录制后改过 ' + x.stale.changed + ' 个文件</span>　' : '')
            + (x.stale && x.stale.mismatch ? '<span style="color:var(--stale)">录制时安装包和仓库有 ' + x.stale.mismatch + ' 个文件不一致</span>　' : '')
            + (x.note ? '「' + esc(x.note) + '」' : '');
          h += '<button class="rr' + (ok ? '' : ' weak') + '" role="menuitem" data-run="' + esc(keyOf(x)) + '"'
            + (x.loadable ? '' : ' disabled title="还没有计数：还在录，或录制中断了（codestrata runs <repo> merge ' + esc(x.id) + '）"')
            + ' aria-current="' + (keyOf(x) === cur) + '">'
            + '<span class="rt" title="' + esc(keyOf(x)) + '">' + esc(shortTime(x.created)) + (x.ref && x.ref.indexOf('@') > 0 ? ' @' + esc(x.ref.split('@')[1]) : '') + '</span>'
            + '<span class="rm">' + meta + '</span>'
            + '<span class="rs ' + (ok ? 'ok' : 'bad') + '">' + esc(x.status || '') + '</span>'
            + (!ok && x.problems && x.problems.length ? '<span class="rx">' + esc(x.problems.join('；')) + '</span>' : '')
            + '</button>';
        });
      });
      pop.innerHTML = h;
      [].forEach.call(pop.querySelectorAll('[data-run]'), function (el) {
        el.onclick = function () {
          var id = el.dataset.run, x = list.filter(function (r) { return keyOf(r) === id; })[0];
          if (id === cur) { self.closeRunPop(); return; }
          // 导出版：只能换到导出时带上的那几个（它们的「id@阶段」就是 x.ref），不猜阶段
          if (x && x.ref) { var rp = x.ref.split('@'); self.selectRun(rp[0], rp[1] || ''); }
          else self.selectRun(id, x ? self._defaultPhase(x) : '');
        };
      });
      var first = pop.querySelector('[aria-current=true]') || pop.querySelector('.rr');
      if (first) first.focus();
    },

    /* 从主菜单打开的：标题前放一个回主菜单的链接（只放一次；header 每次换切面都会调） */
    homeLink: function () {
      if (this._homeAsked) return;                // 问一次就够：直接 serve 的（没有主菜单）也别每次都问
      this._homeAsked = true;
      CS.ds.home().then(function (url) {
        if (!url) return;
        var a = document.createElement('a');
        a.id = 'homeLink'; a.className = 'homelink'; a.href = url; a.textContent = '← 主菜单';
        var row = document.querySelector('.hrow');
        row.insertBefore(a, row.firstChild);
      }).catch(function () {});
    },

    header: function (d) {
      var r = d.repo, self = this;
      document.getElementById('h1').textContent = r.name + ' 架构';
      this.homeLink();
      this.wireHelp();
      document.getElementById('lede').innerHTML =
        '纵轴是<b>架构高度</b> <code>(出−入)/(出+入)</code>：最上面的泳道谁都不依赖它、它依赖一切，'
        + '最下面的只被依赖。横轴用重心排序减少交叉。'
        + ' 灰实线是真的用到了对方符号的 import，灰虚线是只 import 没用到的。'
        + (d.hot ? ' 橙色是这次 <b>runtime</b> 真正跑到的部分。' : '')
        + '　展开的目录画成一个框，框里的子模块仍按自己的高度落在各条泳道里。'
        + '　下面抽屉的右半边是<b>解读层</b>——机器给不出的那部分。';
      var st = [['文件', r.n_files], ['模块', r.n_units || 0], ['图上节点', d.graph.nodes.length],
                ['符号', r.n_symbols || 0], ['图上的边', d.graph.edges.length],
                ['解析失败', r.n_parse_errors]];
      var hm = d.hot && d.hotMeta;
      document.getElementById('stats').innerHTML =
        st.map(function (p) { return '<span>' + p[0] + ' <b>' + p[1] + '</b></span>'; }).join('')
        + '<span>模式 <b>' + CS.ds.mode + '</b></span>'
        // hot 图：上面只留一个标记，来历（阶段、进程、安装包映射、命令）在「?」里
        + (hm ? '<button class="hottag" data-help title="这次 trace 的情况在帮助里">hot <b>' + esc(hm.case)
                 + (hm.phase ? '@' + esc(hm.phase) : '') + '</b>'
                 + (hm.stale_files && hm.stale_files.length ? ' <span style="color:var(--stale)">⚠ 录制后有文件改过</span>' : '')
                 + '</button>' : '');
      var ht = document.querySelector('#stats [data-help]');
      if (ht) ht.onclick = function () { self.help(true); };
      this.runBar();
      if (!(d.hot && d.hotMeta)) document.getElementById('hotbanner').innerHTML = '';
      if (d.hot && d.hotMeta) {
        var m = d.hotMeta;
        // 地址里记完整的 id（case 名会随着重录指到别的 run 上），刷新页面还是同一个 run
        var ref = m.run_id + (m.phase ? '@' + m.phase : '');
        if (CS.ds.run !== ref && CS.ds.canSwitchRun) { CS.ds.run = ref; this._writeHash(); }
        // 对比的 run 也记完整 id（case 名会随重录指到别的 run 上，也可能解析成主 run 自己）
        if (d.cmp && CS.ds.cmp !== d.cmp.ref_b && !this.runListEmbedded) { CS.ds.cmp = d.cmp.ref_b; this._writeHash(); }
        if (d.cmpError) { CS.ds.cmp = ''; this._writeHash(); if (CS.viewer) CS.viewer.toast(d.cmpError); }
        var cmp = d.cmp, mb = cmp && cmp.meta_b;
        document.getElementById('hotbanner').innerHTML =
          (mb ? '<div class="hotbanner cmpbanner"><div><b>对比</b>：<span class="tA">A = ' + esc(m.case) + (m.phase ? '@' + esc(m.phase) : '')
            + '</span>　<span class="tB">B = ' + esc(mb.case) + (mb.phase ? '@' + esc(mb.phase) : '') + '</span>　'
            + '橙色只有 A 跑到，紫色只有 B 跑到，前景色两边都跑到；节点上的数是「A/B」。'
            + ((!!m.events) !== (!!mb.events) ? '<br><span style="color:var(--stale)">一个录了时序事件、一个没录：录事件本身有开销，调用次数和时长不完全可比。</span>' : '')
            + '</div></div>' : '')
          + '<div class="hotbanner"><div><b>hot 图</b>：case <b>' + esc(m.case) + '</b>　'
          + (m.run_id ? '<span class="lab">run ' + esc(m.run_id) + '</span>　' : '')
          + (m.phase ? '阶段 <b>' + esc(m.phase) + '</b>　' : '')
          + (m.status && m.status !== 'ok' ? '<span style="color:var(--stale)">⚠ 这次录制不完整'
             + (m.problems && m.problems.length ? '：' + esc(m.problems.join('；')) : '') + '</span>　' : '')
          + (m.phases && Object.keys(m.phases).length
             ? '<span class="lab">（这次 trace 分了阶段：' + Object.keys(m.phases).map(function (k) {
                 return esc(k) + ' ' + m.phases[k] + ' 个函数'; }).join(' / ')
               + (m.phase ? '' : '；现在显示的是全部') + '）</span>　' : '')
          + (m.n_procs ? '跨 ' + m.n_procs + ' 个进程　' : '')
          + (m.unmapped ? '<span title="lambda、闭包、生成器表达式没有自己的符号：算到文件上，'
             + '不计入符号的调用次数（闭包的调用在边详情里会归到外层函数）">未归到命名符号的调用 '
             + m.unmapped + '</span>　' : '')
          + (m.defs ? '<span title="import 时模块顶层的执行、class 语句跑类体：是定义，不算调用，'
             + '只定义过的类和只被 import 过的模块不算「跑到了」">定义时的执行 ' + m.defs + '（不算调用）</span>　' : '')
          + (m.mapped_from ? '运行的是安装包 <code>' + esc(m.mapped_from) + '</code>，已映射回仓库 ' + m.n_mapped + ' 个文件'
             + (m.mapped_mismatch && m.mapped_mismatch.length
                ? '，<span style="color:var(--stale)">其中 ' + m.mapped_mismatch.length + ' 个与仓库内容不一致（已按函数名对到仓库里的位置）</span>'
                : '（逐文件与仓库一致 ✓）') + '　' : '')
          + (m.stale_files && m.stale_files.length ? '<span style="color:var(--stale)" title="'
             + esc(m.stale_files.slice(0, 30).join('\n')) + '">⚠ 录制后有 '
             + m.stale_files.length + ' 个文件改过或删掉了；改过的已按函数名把次数挪到函数现在的位置</span>　' : '')
          + (m.unmatched ? '<span style="color:var(--stale)" title="lambda、生成器表达式没有名字；改了名、删了的函数找不到；'
             + '老的 run 没存函数名">⚠ ' + m.unmatched + ' 处按函数名对不上：这些调用只算到文件上，不算到函数上</span>　' : '')
          + '</div></div>' + self.runHtml(m);
        self.wireRun();
      }
    },

    /* 边的开关兼图例：每个开关上画的线就是图上那种边的样子，数字是条数 */
    edgeChips: function () {
      var DYN_TIP = '跑到的调用在代码里找不到对应的引用：插件 / getattr / 注册表 / self.model 这类接口分派。'
        + '两端之间可能没有 import，也可能有 import、但 import 的东西这次一次都没跑到';
      var c = CS.graph.counts, hot = !!CS.graph.hot, s = CS.graph.state;
      var defs = [['refs', 'e ref', '引用', c.ref, 'import 了，并且真的用到了对方的符号', false],
                  ['imp', 'e imp', '只 import', c.imp,
                   '一个符号都没用到：再导出 / 为了副作用 / 死 import', false]];
      if (c.type) defs.push(['type', 'e type', '仅类型', c.type,
                             '两端之间只有 if TYPE_CHECKING: 里的 import：只给类型标注用，运行时不存在，不算进架构高度', false]);
      if (hot && CS.graph.cmp) {
        defs.push(['hot', 'e ref warm', 'runtime', c.warm, '对比：橙色只有 A 跑到、紫色只有 B 跑到、前景色两边都跑到，粗细 ∝ 两边的较大值', true]);
        if (c.dyn) defs.push(['dyn', 'e dyn warm', '动态分派', c.dyn,
                              DYN_TIP + '（两个 run 任一跑到）', true]);
      } else if (hot) {
        defs.push(['hot', 'e ref warm', 'runtime', c.warm, '这次 case 真的调用过，粗细 ∝ 调用次数', true]);
        if (c.dyn) defs.push(['dyn', 'e dyn warm', '动态分派', c.dyn, DYN_TIP, true]);
      }
      document.getElementById('edgechips').innerHTML = defs.map(function (x) {
        return '<button class="chip lg' + (x[5] ? ' rt' : '') + '" data-t="' + x[0] + '" aria-pressed="' + (s[x[0]] !== false) + '" title="'
          + esc(x[4]) + '"><svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" class="'
          + x[1] + '" style="stroke-width:1.8"/></svg>' + x[2] + ' <span class="n">' + x[3] + '</span></button>';
      }).join('')
        + (CS.graph.cmp ? '<span class="cmpleg" title="对比两个 run"><i class="a"></i>只有 A<i class="b"></i>只有 B<i class="ab"></i>两边都有</span>' : '');
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
      this._w = CS.graph.boxWidth();
      return CS.ds.graph(open, this._w).then(function (d) {
        if (seq !== self._cutSeq) return false;   // 连着点了几次：只认最后一次，先发出的请求晚回来也不能盖掉它
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
        if (self.view === 'seq') {                    // 时序图跟着切面 / run 走：还有事件就重取，没有就退回模块图
          if (self._runHasEvents()) CS.seq.show(CS.seq.req); else self.setView('graph');
        }
        return true;
      }).catch(function (e) {
        if (seq !== self._cutSeq) return false;
        self._pending = null;
        document.getElementById('prog').textContent = e.message;
        return false;
      });
    },

    /* 展开 / 收起不取消选中。选中的节点还在就还选它（详情重画：它的邻居可能变了）；
       它被收进了某个节点就选那个节点；它自己被展开成了框，就选中那个框、详情面板不动。
       选中的边两头按同样的规则落到新节点上，新图上还有这条边就接着选它。 */
    /* id（目录 / 本层文件 / 单个文件）在当前图上落在哪个节点：是节点就是它自己；被收着就是
       装着它的那个节点。目录节点装着它底下的一切；本层文件节点只装直接放在这个目录里的
       单个文件（不装子目录），所以要知道 id 是不是单个文件（kind === 'unit'） */
    homeOf: function (id, kind, graph) {
      // 默认在画出来的那张图上找（hot 视图只画跑到的）
      var g = graph || CS.graph.G || this.data.graph, best = null, unit = kind === 'unit';
      for (var i = 0; i < g.nodes.length; i++) if (g.nodes[i].id === id) return id;
      g.nodes.forEach(function (n) {
        var res = /\.\*$/.test(n.id), base = res ? n.id.slice(0, -2) : n.id;
        var inside = id.indexOf(base + '.') === 0
          && (!res || (unit && id.slice(base.length + 1).indexOf('.') < 0));
        if (inside && (!best || n.id.length > best.length)) best = n.id;
      });
      return best;
    },

    /* 把一个模块在图上找出来并选中：它已经是节点就直接选；被收在某个目录里时，展开到它
       （serve 算要展开哪些目录）；导出版不能展开，就选中装着它的那个节点。
       已经展开成框的目录选中那个框（不能去收起它）；图上画不出来的模块（空的 __init__.py）
       选中装着它的框；hot 视图里没跑到的，先退出 hot 视图。选中后滚到屏幕中间、闪一下。
       返回最后选中的节点（选中的是框或什么都没选时返回 null） */
    revealNode: function (id, kind) {
      var self = this, st = CS.graph.state;
      function drawn(x) { return !!CS.graph.nodes[x]; }
      function frames() { return (CS.graph.G && CS.graph.G.frames) || []; }
      function show(x) {
        if (!x || !drawn(x)) return null;
        CS.graph.pick(x, true); CS.graph.focus(x); CS.graph.flash([x]);
        CS.graph.showEl(CS.graph.nodes[x], true);
        return x;
      }
      function showFrame(f, msg) {
        CS.graph.selectFrame(f);
        var g = CS.graph.frames[f];
        if (g && !CS.graph.inView(g)) CS.graph.showEl(g, true);
        if (msg) CS.viewer.toast(msg);
        return null;
      }
      function frameOf(x) {                      // 画不出来的单元：装着它的框（本层文件的框或目录的框）
        var d = kind === 'unit' ? x.replace(/\.[^.]+$/, '') : x, ids = frames().map(function (f) { return f.id; });
        return ids.indexOf(d + '.*') >= 0 ? d + '.*' : ids.indexOf(d) >= 0 ? d : null;
      }
      function exitHot() {                        // 「只看跑到的」里没有它：退出 hot 视图再找
        st.onlyHot = false;
        var b = document.querySelector('[data-t="onlyhot"]'); if (b) b.setAttribute('aria-pressed', 'false');
        self.redraw();
        CS.viewer.toast('它这次没跑到，已退出「只看跑到的」');
      }
      function finish() {
        var h = self.homeOf(id, kind);
        // hot 视图里没画它，但完整的图上有：它这次没跑到——退出 hot 视图再找
        if ((!h || !drawn(h)) && st.onlyHot && self.homeOf(id, kind, self.data.graph)) { exitHot(); h = self.homeOf(id, kind); }
        if (h && drawn(h)) return show(h);
        var f = frameOf(id);
        return f ? showFrame(f, '它在图上没有节点（没有类、函数，也没有依赖——比如空的 __init__.py）') : null;
      }
      if (frames().some(function (f) { return f.id === id; })) return Promise.resolve(showFrame(id));
      if (this.data.open.indexOf(id) >= 0) {       // 只有一个根时根就是整张图，不画框
        CS.graph.clear();
        var gb = document.querySelector('.gbox'); if (gb) gb.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return Promise.resolve(null);
      }
      var h0 = this.homeOf(id, kind);
      if (h0 === id || !CS.ds.canCut) return Promise.resolve(finish());
      return CS.ds.reveal(id, this.curOpen()).then(function (r) {
        return self.setCut(r.open, id).then(function (done) { return done ? finish() : null; });
      }).catch(function () { return finish(); });
    },

    keepSelection: function (was) {
      var g = this.data.graph, frames = {}, self = this;
      (g.frames || []).forEach(function (f) { frames[f.id] = 1; });
      function home(id) { return self.homeOf(id, was.kind[id]); }
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
                    { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges, dynOnly: d.dynOnlyEdges, typeOnly: d.typeOnlyEdges, cmp: d.cmp });
      if (CS.graph.noteStatus) CS.graph.setNoteStatus(CS.graph.noteStatus);
      // 重画会重建所有节点：图例上边的条数按这张图重数，搜索栏里还有字就把高亮重新套上
      this.edgeChips();
      this.controls();
      if (CS.search) CS.search.reapply();
    },

    controls: function () {
      var s = CS.graph.state, self = this;
      var KEY = { refs: 'refs', imp: 'imp', type: 'type', hot: 'hot', dyn: 'dyn', onlyhot: 'onlyHot', noted: 'onlyNoted' };
      [].forEach.call(document.querySelectorAll('[data-t]'), function (b) {
        var key = KEY[b.dataset.t];
        if (key === 'onlyHot') {                 // 换 run 时会来回切：没叠 runtime 就藏起来
          b.style.display = CS.graph.hot ? '' : 'none';
          if (!CS.graph.hot) return;
        }
        b.onclick = function () {
          s[key] = b.getAttribute('aria-pressed') !== 'true';
          b.setAttribute('aria-pressed', s[key]);
          // 「只看跑到的」换成单独排版的 hot 图，而不是在总图上隐藏——隐藏的节点还占着位置；
          // 仅类型的边关着时不画（不占接点），开关一动也要重画
          if ((key === 'onlyHot' && self.data.graphHot) || key === 'type') self.redraw();
          else CS.graph.paint();
        };
      });
      var rc = document.getElementById('resetcut');
      if (rc) rc.onclick = function () { self.resetCut(); };
      document.getElementById('reset').onclick = function () {
        if (CS.search) CS.search.clear();
        CS.graph.highlight(null); CS.graph.clear();
      };
      if (!this._esc) {
        this._esc = true;
        document.addEventListener('keydown', function (ev) {
          // Esc 取消选中（全文窗口开着时 Esc 先关窗口，那边自己处理）
          // 正在输入框里打字（搜索框、文件树过滤、贴解读的文本框）时 Esc 归输入框自己
          var s = CS.graph.state, t = ev.target;
          if (ev.isComposing || (t && t.closest && t.closest('input, textarea, select, [contenteditable]'))) return;
          if (ev.key === 'Escape' && !document.getElementById('help').hidden) { self.help(false); return; }
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
