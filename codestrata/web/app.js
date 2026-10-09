/* 入口：把数据源、图、两个面板串起来。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  // 读图须知（界面上那一行和「?」里共用）：运行时的图最容易读错的几处
  var READ_NOTE = '调用方是栈上最近的仓库内函数——穿过框架、库、事件循环的调用，画成两个仓库函数之间的直接调用；'
    + '次数高的多半是轮询（时间顺序里带 ↻），不等于重要；import 时执行模块顶层不算调用。';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // 「2026-09-27T15:34:10-0400」→「09-27 15:34」
  /* 复制到剪贴板：serve 在 127.0.0.1 上是安全上下文，用 Clipboard API；
     被拒绝时退回选中一个临时 textarea 再 execCommand('copy')。结果是 Promise<是否成功> */
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
        CS.laneCut.adopt(d);
        self.header(d);
        CS.panel.init(document.getElementById('det'), d);
        CS.graph.onPick = function (id) { CS.panel.showPkg(id); self.drawerTitle(id); };
        CS.graph.onPickEdge = function (a, b) { CS.panel.showEdge(a, b); self.drawerTitle(null, a, b); };
        CS.graph.onCollapse = function (f) { self.collapseFrame(f); };
        CS.graph.onClear = function () { CS.panel.reset(); self.drawerTitle(); if (CS.lanes) CS.lanes.unselect(); };
        // 时间顺序的颜色是画的时候按当前主题的 --tm0/1/2 算好写死的：换了亮 / 暗（系统设置或页面上的切换）要重画
        var retint = function () { if (CS.graph.state.timeOrder) self.repaint(); };   // 分列或模块图
        if (window.matchMedia) {
          var mq = window.matchMedia('(prefers-color-scheme: dark)');
          if (mq.addEventListener) mq.addEventListener('change', retint);
        }
        if (window.MutationObserver)
          new MutationObserver(retint).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        CS.graph.onSelectFrame = function (f) {
          var t = document.getElementById('dtitle'); if (t) { t.textContent = CS.panel.full(f); t.title = f; }
          var s = document.getElementById('dsub'); if (s) s.textContent = '已在图上展开成框（框头的 − 收起）';
        };
        self.wireDrawer();
        CS.graph.onExpand = function (id) { self.expand(id); };
        CS.graph.phaseMarks = self.phaseMarks();
        self.drawMain();
        self.applyTimes();
        self.edgeChips();
        self.controls();
        self.cutBar();
        self.footer(d);
        if (self._runMissing && CS.viewer) CS.viewer.toast(self._runMissing);
        if (CS.search) CS.search.init();
        // 窗口宽度变了不少：按新的宽度重新排版（切面、选中、缩放都不变）
        self._w = CS.graph.boxWidth();
        var rt = 0;
        window.addEventListener('resize', function () {
          clearTimeout(rt);
          rt = setTimeout(function () {
            if (Math.abs(CS.graph.boxWidth() - self._w) >= 80) self.setCut(self.curOpen());
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
      var v = id && (CS.panel.data().pkgs || {})[id];
      t.title = id || '';
      if (id) {
        t.textContent = CS.panel.full(id);
        s.textContent = !v ? '' : v.kind === 'virtual' ? '仓库外的 GPU kernel（trace --gpu）'
          : v.files + ' 个文件 · ' + v.classes + ' 个类 · ' + v.funcs + ' 个函数';
      } else if (a) {
        t.textContent = CS.panel.short(a) + ' → ' + CS.panel.short(b);
        s.textContent = '这条边上是哪些函数在调用：代码里写的、这次跑到的';
      } else {
        t.textContent = '详情';
        s.textContent = '点图上的节点或箭头，在这里看它的文件、类 / 函数，或者这条边上是哪些函数在调用';
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

    /* 读图须知：叠着 run 时在图上面一行（关掉记在浏览器里，「?」的说明里一直有） */
    readNote: function (on) {
      var el = document.getElementById('readnote'), self = this;
      if (!el) return;
      el.hidden = !on || !!this._load('codestrata.readnote').off;
      if (el.hidden || el._done) return;
      el._done = true;
      el.innerHTML = '<b>读图须知</b><span>' + READ_NOTE + '</span>'
        + '<button class="chip" data-help>更多</button>'
        + '<button class="rnx" aria-label="不再显示读图须知" title="不再显示（「?」里一直有）">×</button>';
      el.querySelector('[data-help]').onclick = function () { self.help(true); };
      el.querySelector('.rnx').onclick = function () { el.hidden = true; self._save('codestrata.readnote', { off: 1 }); };
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
      if (CS.ds.run) rest.unshift('run=' + encodeURIComponent(CS.ds.run).replace(/%40/g, '@'));
      history.replaceState(null, '', location.pathname + location.search + (rest.length ? '#' + rest.join('&') : ''));
    },

    initRuns: function () {
      var self = this;
      return CS.ds.runs().then(function (r) {
        self.runList = r.runs || [];
        self._known = {};
        self.runList.forEach(function (x) { self._known[x.id] = 1; });
        var want = self._hashRun();
        if (want === null) want = r.default || '';
        if (want) {
          var id = want.split('@')[0];
          var hit = self.runList.filter(function (x) { return x.id === id || x.case === id; })[0];
          if (!hit || !hit.loadable) {
            self._runMissing = '地址里的 run ' + want + (hit ? ' 还没有计数（还在录，或录制中断了要 runs merge）'
                                                           : ' 找不到了（删了？）') + '，先只看静态图';
            want = '';
          }
        }
        CS.ds.run = want;
        self.wireRunSel();
      }).catch(function () { self.runList = []; self._known = {}; self.wireRunSel(); });
    },

    /* 列表里某个 run 默认看哪个阶段：有 serving 就只看 serving（启动时的初始化会淹没请求本身） */
    _defaultPhase: function (x) {
      return (x.phases || []).some(function (p) { return p.name === 'serving'; }) ? 'serving' : '';
    },

    selectRun: function (id, phase) {
      var self = this, prev = CS.ds.run;
      CS.ds.run = id ? id + (phase ? '@' + phase : '') : '';
      this._writeHash();
      this.closeRunPop();
      var p = this.setCut(this.curOpen()), mine = this._cutSeq;
      document.getElementById('prog').textContent = id ? '叠加 run ' + id + (phase ? ' @' + CS.timebar.label(phase) : '') + '…' : '重新汇总…';
      return p.then(function (ok) {
        // 换不过去（run 被删了、还没有计数）：退回原来那个，免得之后取边、引用用的是另一个 run
        if (!ok && self._cutSeq === mine) {
          CS.ds.run = prev;
          self._writeHash();
          self.runBar();
          self.applyTimes();                          // 退回原来的 run：时间顺序也按它重取
          if (CS.viewer) CS.viewer.toast('换不过去：' + document.getElementById('prog').textContent);
        }
        return ok;
      });
    },

    /* 这个 run 录了时序事件（trace 默认录，3.12+）：「时间顺序」、请求路径要用 */
    runHasEvents: function () {
      var m = this.data && this.data.hot && this.data.hotMeta;
      var x = m && (this.runList || []).filter(function (r) { return r.id === m.run_id; })[0];
      return !!(x && x.events);
    },

    runBar: function () {
      var self = this, b = document.getElementById('runbtn'), pc = document.getElementById('phasechips');
      if (!b) return;
      var d = this.data, m = d && d.hot && d.hotMeta;
      var oh = document.querySelector('[data-t="onlyhot"]');
      if (!m && CS.graph.state.onlyHot) {       // 换成了静态图：「只看跑到的」没有意义了（不关掉会把节点全藏起来）
        CS.graph.state.onlyHot = false;
        if (oh) oh.setAttribute('aria-pressed', 'false');
      } else if (m && !CS.graph.state.onlyHot && !this._onlyHotChosen && d.graphHot) {
        // 叠了 run 默认只看跑到的（用户 09-30 定的）：首屏就是这次走过的路；用户自己关过就不再替他打开
        CS.graph.state.onlyHot = true;
        if (oh) oh.setAttribute('aria-pressed', 'true');
      }
      b.classList.toggle('on', !!m);
      b.textContent = m ? m.case + ' · ' + shortTime(m.created) : '静态图';
      var rb = document.getElementById('rerunbtn');
      if (rb) {
        rb.hidden = !(m && m.rerun);
        rb.onclick = function () { self.showRerun(); };
      }
      b.title = m ? 'run ' + m.run_id + '（点开换一个）' : '现在只看静态图；点开选一次录下的运行叠上去';
      var run = m && (this.runList || []).filter(function (x) { return x.id === m.run_id; })[0];
      // 时间轴：阶段按钮 + 时间条（录了时序事件的还能在条上拖出任意一段时间；老 run 不知道多长就只有按钮）
      var phases = run ? run.phases : m ? Object.keys(m.phases || {}).map(function (k) { return { name: k, n_funcs: m.phases[k] }; }) : [];
      if (phases.length < 2) phases = [];                       // 没分阶段：只剩全部 / 拖时间段
      var canDrag = !!(m && m.end_us) && this.runHasEvents();
      if (!m || !(phases.length || canDrag)) { pc.innerHTML = ''; return; }
      var at = Object.create(null), hook = Object.create(null), tips = {};
      (m.phase_at || []).forEach(function (t) { at[t.name] = t; });
      (m.phase_log || []).forEach(function (x) { if (x[2] === 'hook') hook[x[0]] = 1; });
      phases.forEach(function (p) {
        tips[p.name] = (p.n_funcs != null ? '（' + p.n_funcs + ' 个函数）' : '')
          + (at[p.name] && hook[p.name] ? '；从第一次进入 ' + at[p.name].qualname + ' 开始' : '');
      });
      CS.timebar.render(pc, { run: m.run_id, names: phases.map(function (p) { return p.name; }),
                              segs: phases.length ? m.timeline || [] : [], end: m.end_us || 0,
                              phase: m.window ? '' : m.phase || '', window: m.window, canDrag: canDrag, tips: tips,
                              onSelect: function (ref) { self.selectRun(m.run_id, ref); } });
      // 选了阶段：写明从哪个函数开始、到哪个函数结束（图上对应的节点标成绿 ▶ / 红 ■）
      var bd = this.phaseBounds();
      if (m.phase && !m.window)
        pc.insertAdjacentHTML('beforeend', '<span class="pbound"><b class="ps">▶ 起点</b> ' + (bd.start ? esc(bd.start.qualname) : '程序开始')
          + '　<b class="pe">■ 终点</b> ' + (bd.end ? esc(bd.end.qualname) + '（切到 ' + esc(bd.end.name) + '）' : '程序结束') + '</span>');
    },

    /* 「时间顺序」开关只在：叠着一个 run、它录了时序事件 */
    canTimeOrder: function () {
      return !!(this.data && this.data.hot) && this.runHasEvents();
    },

    /* 时间顺序只在分列里有（叠着录了时序事件的 run 一律分列）：时刻在 /api/lanes 里已经有了，开关一变重新上色；
       模块图上（没叠 run、没录时序事件）没有这个开关 */
    applyTimes: function () {
      if (this.lanesMode()) CS.lanes.paint();
      else if (CS.graph.state.timeOrder) CS.graph.state.timeOrder = false;
      this.edgeChips(); this.controls();
    },

    /* 当前阶段从哪个函数开始、到哪个函数（下一个阶段的起点）结束：{start, end}，各是 phase_at 里的一项
       （带 node：落在当前切面的哪个节点上）或 null。没选阶段（全部）时 start / end 都是 null */
    phaseBounds: function () {
      var d = this.data, m = d && d.hot && d.hotMeta, marks = (d && d.phaseMarks) || [];
      if (!m || !m.phase || m.window) return { start: null, end: null };
      var by = Object.create(null), order = (m.phase_log || []).map(function (x) { return x[0]; });
      marks.forEach(function (x) { by[x.name] = x; if (order.indexOf(x.name) < 0) order.push(x.name); });
      var next = null;
      for (var j = order.indexOf(m.phase) + 1; j > 0 && j < order.length && !next; j++) next = by[order[j]] || null;
      return { start: by[m.phase] || null, end: next };
    },

    /* 图上要标的阶段起点 / 终点。选了阶段：它的起点（绿 ▶）和终点（红 ■，下一个阶段的触发函数）；
       全部：每个阶段的起点；时间段：在这段时间里开始的阶段的起点 */
    phaseMarks: function () {
      var d = this.data, m = d && d.hot && d.hotMeta;
      if (!m) return [];
      var out = [];
      function where(x) { return x.qualname + '（' + x.file + ':' + x.line + '）'; }
      if (!m.phase || m.window) {
        var t0 = Object.create(null);                 // 各阶段第一次开始的时刻
        (m.timeline || []).forEach(function (x) { if (!(x[0] in t0)) t0[x[0]] = x[1]; });
        ((d && d.phaseMarks) || []).forEach(function (x) {
          if (m.window && !(t0[x.name] >= m.window[0] && t0[x.name] <= m.window[1])) return;
          if (x.node) out.push({ node: x.node, kind: 'start', label: '▶ ' + x.name,
                                 title: x.name + ' 阶段从第一次进入 ' + where(x) + ' 开始' });
        });
        return out;
      }
      var b = this.phaseBounds();
      if (b.start && b.start.node) out.push({ node: b.start.node, kind: 'start', label: '▶ ' + m.phase + ' 起点',
                                              title: m.phase + ' 阶段从第一次进入 ' + where(b.start) + ' 开始' });
      if (b.end && b.end.node) out.push({ node: b.end.node, kind: 'end', label: '■ ' + m.phase + ' 终点',
                                          title: '第一次进入 ' + where(b.end) + ' 时切到 ' + b.end.name + ' 阶段：' + m.phase + ' 到这里结束' });
      return out;
    },

    wireRunSel: function () {
      var self = this, b = document.getElementById('runbtn'), pop = document.getElementById('runpop');
      if (!b || b._wired) return;
      b._wired = 1;
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
      return CS.ds.runs().then(function (r) {
        var fresh = (r.runs || []).some(function (x) { return !self._known[x.id]; });
        self.runList = r.runs || [];
        if (fresh && quiet) document.getElementById('rundot').hidden = false;
        if (!quiet) self.runList.forEach(function (x) { self._known[x.id] = 1; });
      }).catch(function () {});
    },

    openRunPop: function () {
      var self = this, pop = document.getElementById('runpop'), b = document.getElementById('runbtn');
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
      var cur = hm ? hm.run_id : '';
      var h = '<button class="rr" role="menuitem" data-run="" aria-current="' + !cur + '"><span class="rt">静态图</span>'
        + '<span class="rm">不叠 runtime，只看代码里写的调用</span><span></span></button>';
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
          h += '<button class="rr' + (ok ? '' : ' weak') + '" role="menuitem" data-run="' + esc(x.id) + '"'
            + (x.loadable ? '' : ' disabled title="还没有计数：还在录，或录制中断了（codestrata runs <repo> merge ' + esc(x.id) + '）"')
            + ' aria-current="' + (x.id === cur) + '">'
            + '<span class="rt" title="' + esc(x.id) + '">' + esc(shortTime(x.created)) + '</span>'
            + '<span class="rm">' + meta + '</span>'
            + '<span class="rs ' + (ok ? 'ok' : 'bad') + '">' + esc(x.status || '') + '</span>'
            + (!ok && x.problems && x.problems.length ? '<span class="rx">' + esc(x.problems.join('；')) + '</span>' : '')
            + '</button>';
        });
      });
      pop.innerHTML = h;
      [].forEach.call(pop.querySelectorAll('[data-run]'), function (el) {
        el.onclick = function () {
          var id = el.dataset.run, x = list.filter(function (r) { return r.id === id; })[0];
          if (id === cur) { self.closeRunPop(); return; }
          self.selectRun(id, x ? self._defaultPhase(x) : '');
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
      document.getElementById('h1').textContent = r.name;
      this.homeLink();
      this.wireHelp();
      document.getElementById('lede').innerHTML =
        // 叠着录了时序事件的 run 时是分列（body.lanesmode），说明换成分列的
        '<span class="lanesonly"><b>按进程 · 线程分列</b>：一列是一个进程里的一类线程（同名的合成一列，列头的 ×N 是几条），'
        + '列按进程分组，进程头的 ▾ 能把整个进程收起来。列里是这条线程调到的模块（文件 / 目录），同一个模块在几列里各有一份；'
        + '节点上的「被调 N 次」和点开的详情都只算这一列。列里的边和模块图一样：橙色是这次跑到的调用，橙虚线是代码里看不出会调到它的。'
        + '<br><b>列之间的线</b>（图例在工具栏）：青色实线是<b>交接数据</b>（queue / janus / asyncio 的队列、ZMQ，按放和取配对）；'
        + '绿虚线是<b>谁起了谁</b>（起线程、起子进程）；红虚线是<b>谁回收了谁</b>（join、waitpid）；橙细虚线是<b>启动 GPU kernel</b>（trace --gpu）。'
        + '节点上的「▶ 起」「■ 收」是线程 / 进程在这里起的、在这里被等到结束的。'
        + '分列里的次数来自时序事件：线程的入口函数（栈上它下面没有仓库里的函数）被调的那一次、递归调用自己的不算，所以会比模块图上的少一些。</span>'
        + '<span class="graphonly">纵轴是<b>调用的层次</b>：箭头尽量都从上指向下——调用方在上、被调用的在下（按 import 关系排，'
        + '叠了 run 时再按这次实际的调用排，所以换 run 时节点会上下挪）。横轴用重心排序减少交叉。'
        + ' 图上的边只有<b>调用</b>：灰实线是代码里写了的调用。'
        + (d.hot ? ' 橙色是这次 <b>runtime</b> 真正跑到的，边上是调用次数；橙虚线是代码里看不出会调到它的。' : '')
        + '　展开的目录画成一个框，框里的子模块仍按自己的高度落在各条泳道里。</span>'
        + (d.hot ? '<br><b>读图须知</b>：' + READ_NOTE + '「未归到命名符号的调用」是进 lambda、生成器表达式'
                   + '（3.12 之前还有推导式）这类没有名字的代码的次数：算到文件和模块上，不单列函数，边详情里写成「外层函数.&lt;L行&gt;」。' : '');
      var st = [['文件', r.n_files], ['模块', r.n_units || 0], ['图上节点', d.graph.nodes.length],
                ['符号', r.n_symbols || 0], ['图上的边', d.graph.edges.length],
                ['解析失败', r.n_parse_errors]];
      var hm = d.hot && d.hotMeta;
      document.getElementById('stats').innerHTML =
        st.map(function (p) { return '<span>' + p[0] + ' <b>' + p[1] + '</b></span>'; }).join('')
        // hot 图：上面只留一个标记，来历（阶段、进程、安装包映射、命令）在「?」里
        + (hm ? '<button class="hottag" data-help title="这次 trace 的情况在帮助里">hot <b>' + esc(hm.case)
                 + (hm.phase ? '@' + esc(CS.timebar.label(hm.phase)) : '') + '</b>'
                 + (hm.stale_files && hm.stale_files.length ? ' <span style="color:var(--stale)">⚠ 录制后有文件改过</span>' : '')
                 + '</button>' : '');
      var ht = document.querySelector('#stats [data-help]');
      if (ht) ht.onclick = function () { self.help(true); };
      this.runBar();
      this.readNote(!!(d.hot && d.hotMeta));
      if (!(d.hot && d.hotMeta)) document.getElementById('hotbanner').innerHTML = '';
      if (d.hot && d.hotMeta) {
        var m = d.hotMeta;
        // 地址里记完整的 id（case 名会随着重录指到别的 run 上），刷新页面还是同一个 run
        var ref = m.run_id + (m.phase ? '@' + m.phase : '');
        if (CS.ds.run !== ref) { CS.ds.run = ref; this._writeHash(); }
        document.getElementById('hotbanner').innerHTML =
          '<div class="hotbanner"><div><b>hot 图</b>：case <b>' + esc(m.case) + '</b>　'
          + (m.run_id ? '<span class="lab">run ' + esc(m.run_id) + '</span>　' : '')
          + (m.window ? '时间段 <b>' + esc(CS.timebar.label(m.phase)) + '</b>'
             + '<span class="lab">（次数按这段时间里的时序事件算；2026-10-01 之前录的 run 只记了跨文件的调用）</span>　'
             : m.phase ? '阶段 <b>' + esc(m.phase) + '</b>　' : '')
          + (m.status && m.status !== 'ok' ? '<span style="color:var(--stale)">⚠ 这次录制不完整'
             + (m.problems && m.problems.length ? '：' + esc(m.problems.join('；')) : '') + '</span>　' : '')
          + (m.phases && Object.keys(m.phases).length
             ? '<span class="lab">（这次 trace 分了阶段：' + Object.keys(m.phases).map(function (k) {
                 return esc(k) + ' ' + m.phases[k] + ' 个函数'; }).join(' / ')
               + (m.phase ? '' : '；现在显示的是全部') + '）</span>　' : '')
          + (m.n_procs ? '跨 ' + m.n_procs + ' 个进程　' : '')
          + (m.unmapped ? '<span title="lambda、生成器表达式没有自己的符号：算到文件上，'
             + '不计入符号的调用次数（边详情里写成「外层函数.<L行>」）">未归到命名符号的调用 '
             + m.unmapped + '（见上面的读图须知）</span>　' : '')
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
      var DYN_TIP = '这次跑了，但代码里看不出会调到它：多态（self.model 按配置挑的类）、注册表 / 插件 / getattr、回调、'
        + '框架转了一道。点边详情看调用写在哪一行、scan 在那一行看到的是什么';
      var c = CS.graph.counts, hot = !!CS.graph.hot, s = CS.graph.state;
      var defs = [['scan', 'e', '代码里的调用', c.scan, '代码里写了、scan 定下了被调方的调用（灰实线；跑到了的画成橙色）', false]];
      if (hot) {
        defs.push(['hot', 'e warm', '这次跑了', c.warm + c.dyn, '这次 case 真的调用过的边（橙色）；粗细不变，边上标调用次数。'
                   + (c.dyn ? '其中 ' + c.dyn + ' 条跑到的全是代码里看不出的，画虚线，后一个开关单独管它们' : ''), true]);
        if (c.dyn) defs.push(['dyn', 'e dyn warm', '其中代码里看不出', c.dyn, DYN_TIP + (s.hot === false ? '。要先开「这次跑了」' : ''), true]);
        if (this.canTimeOrder())
          defs.push(['timeorder', '', '时间顺序', CS.graph.state.timeOrder ? (this.lanesMode() ? CS.lanes.timed : 0) || 0 : '',
                     '跑到的边按第一次被调用的先后上色（早 → 晚）、在中点标序号；↻ 是整段时间里反复调用的。'
                     + '换阶段、展开收起都会按新的时间窗重算', true]);
      }
      // 整段重写会把键盘焦点丢到 body 上：记下焦点在哪个开关上，重写完放回去
      var fa = document.activeElement, ft = fa && fa.closest && fa.closest('#edgechips [data-t]') ? fa.dataset.t : null;
      document.getElementById('edgechips').innerHTML = defs.map(function (x) {
        var tm = x[0] === 'timeorder';            // 时间顺序：开关上画一段起点色 → 终点色的渐变线
        return '<button class="chip lg' + (x[5] ? ' rt' : '') + '" data-t="' + x[0] + '" aria-pressed="'
          + (tm ? !!s.timeOrder : s[x[0]] !== false) + '"' + (x[0] === 'dyn' && s.hot === false ? ' disabled' : '') + ' title="'
          + esc(x[4]) + '"><svg width="22" height="8" aria-hidden="true">'
          // 渐变按用户坐标铺：默认的 objectBoundingBox 在水平线上（包围盒高 0）不画，线就没了
          + (tm ? '<defs><linearGradient id="tmchip" gradientUnits="userSpaceOnUse" x1="0" y1="4" x2="22" y2="4">'
                  + '<stop offset="0" style="stop-color:var(--tm0)"/>'
                  + '<stop offset=".5" style="stop-color:var(--tm1)"/><stop offset="1" style="stop-color:var(--tm2)"/></linearGradient></defs>'
                  + '<line x1="0" y1="4" x2="22" y2="4" stroke="url(#tmchip)" style="stroke-width:2.4"/>'
                : '<line x1="0" y1="4" x2="22" y2="4" class="' + x[1] + '" style="stroke-width:1.8"/>')
          + '</svg>' + x[2] + ' <span class="n">' + x[3] + '</span></button>';
      }).join('')
        + (s.timeOrder && CS.graph.times ? '<span class="tmleg" title="颜色按第一次被调用的先后排名：最早的在左边那头，最晚的在右边那头">'
           + '早<i class="tmbar"></i>晚　<b class="tp" style="background:var(--tm0)">3</b> 第几个开始的　'
           + '<b class="tp" style="background:var(--tm1)">7<span class="rep">↻</span></b> 反复调用（至少 5 次，首末隔了这一段的一半以上）'
           + ((CS.graph.times.truncated || []).length ? '　<span class="warn">⚠ 有进程的时序事件录到了上限，之后的调用没有时间，照原来的颜色画</span>' : '')
           + '</span>' : '');
      if (ft) { var fb = document.querySelector('#edgechips [data-t="' + ft + '"]'); if (fb) fb.focus(); }
    },

    /* ---- 切面：展开 / 收起 ---- */
    /* 当前（或正在路上的）切面：连着点几个 ＋ 时，后一次要在前一次的基础上改，而不是在旧图上改 */
    curOpen: function () { return (this._pending || this.data.open).slice(); },

    /* 分列里展开 / 收起只改一列（lane；用户 10-02），见 lanecut.js；不给 lane 时取选中的那一份所在的列。模块图照旧改共用的切面 */
    expand: function (id, lane) {
      if (this.lanesMode()) return this._inLane(lane, function (l) { return CS.laneCut.expand(l, id); });
      var open = this.curOpen();
      if (open.indexOf(id) < 0) open.push(id);
      this.setCut(open, id);
    },

    /* 收起一个节点 = 收起套着它的那个框 */
    collapse: function (id, lane) {
      var v = (CS.panel.data().pkgs || {})[id] || {};
      if (v.collapsible) this.collapseFrame(v.parent, lane);
    },

    /* 收起一个框：本层文件的框只去掉它自己；目录的框连同它底下所有展开的东西一起去掉 */
    collapseFrame: function (f, lane) {
      if (this.lanesMode()) return this._inLane(lane, function (l) { return CS.laneCut.collapseFrame(l, f); });
      var open = this.curOpen().filter(function (x) {
        return CS.ids.isResidual(f) ? x !== f : !(x === f || CS.ids.within(x, f));
      });
      this.setCut(open, f);
    },
    _inLane: function (lane, go) {
      lane = lane || CS.lanes.selLane();
      return lane ? go(lane) : Promise.resolve(null);
    },

    /* 重置：共用的切面回到默认，分列里各列单独的切面也清掉（用户 10-02） */
    resetCut: function () { CS.laneCut.clear(); this.setCut(this.data.defaultOpen.slice()); },

    /* 换一个切面。focus 是这次展开 / 收起的那个目录：新图画好后把它滚进图框里 */
    setCut: function (open, focus) {
      var self = this, before = {}, st = CS.graph.state, wasLanes = this.lanesMode();
      var seq = this._cutSeq = (this._cutSeq || 0) + 1;
      this._pending = open.slice();
      var was = { sel: st.sel, selEdge: st.selEdge, selFrame: st.selFrame, kind: {} };
      // 记下选中的东西是目录、本层文件还是单个文件：新图上找「谁装着它」时要用
      this.data.graph.nodes.concat(this.data.graph.frames || []).forEach(function (n) { was.kind[n.id] = n.kind; });
      this.data.graph.nodes.forEach(function (n) { before[n.id] = 1; });
      // 分列：每列原来有哪些节点（画好后各列各自闪新出来的）、节点是哪种（找「谁装着它」）按画着的分列记
      var lanesBefore = wasLanes ? CS.lanes.beforeMap() : null, lanesKind = wasLanes ? CS.lanes.kinds() : null;
      document.getElementById('prog').textContent = '重新汇总…';
      this._w = CS.graph.boxWidth();
      return (this._cutP = CS.ds.graph(open, this._w).then(function (d) {
        if (seq !== self._cutSeq) return false;   // 连着点了几次：只认最后一次，先发出的请求晚回来也不能盖掉它
        self._pending = null;
        self.data = d;
        CS.laneCut.adopt(d);                        // 换了 run：清掉分列里各列单独的切面（用户 10-02），换阶段不清
        CS.panel.setData(d);
        self.header(d);
        st.sel = st.selEdge = st.selFrame = null;
        // 换了个 run，分列 / 模块图换了一种：选中的东西在新图上没法认，清掉。分列里什么都没选着时也照旧清掉详情（请求路径之类）
        var same = wasLanes === self.lanesMode(), lanes = self.lanesMode();
        var keep = same && (!lanes || !!CS.lanes.sel);
        // 分列是重画完再异步取数画的：画好之后由它自己滚到新节点、闪一下、接着选画好那一刻选着的（CS.laneCut.after / restore；
        // CS.graph 的 reveal / flash、keepSelection 只管模块图）。在这里（只认最后一次改切面之后）才交给它：先发的那次晚画好也拿不到
        if (lanes) CS.lanes.afterCut = { focus: focus, before: lanesBefore || {}, kind: lanesKind || was.kind };
        if (lanes && keep) {                        // 接着选着：模块图的状态也写上，取数的这几秒里 Esc、点空白处照样能取消
          st.selEdge = CS.lanes.sel || null;
        }
        self.redraw(keep);
        self.cutBar();
        if (self.lanesMode()) return true;          // 分列画好了自己收尾（laneCut.after），也是它清掉「重新汇总…」
        CS.lanes.afterCut = null;
        document.getElementById('prog').textContent = '';
        if (same) self.keepSelection(was); else CS.graph.clear();
        if (focus) {
          CS.graph.reveal(focus);
          // 用键盘点的 ＋ / − 随着重画没了，焦点会掉回 body：交给刚展开的框（它的 −）或刚收回的节点
          var ae = document.activeElement;
          if (!ae || ae === document.body || !document.contains(ae)) CS.graph.focus(focus);
        }
        // 新出现的节点闪一下，好看出展开出来的是哪些
        CS.graph.flash(d.graph.nodes.filter(function (n) { return !before[n.id]; }).map(function (n) { return n.id; }));
        return true;
      }).catch(function (e) {
        if (seq !== self._cutSeq) return false;
        self._pending = null;
        document.getElementById('prog').textContent = e.message;
        return false;
      }));
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
        var res = CS.ids.isResidual(n.id), base = CS.ids.base(n.id);
        var inside = CS.ids.within(id, base) && (!res || (unit && CS.ids.dirOf(id) === base));
        if (inside && (!best || n.id.length > best.length)) best = n.id;
      });
      return best;
    },

    /* 把一个模块在图上找出来并选中：它已经是节点就直接选；被收在某个目录里时，展开到它
       （serve 算要展开哪些目录）。
       已经展开成框的目录选中那个框（不能去收起它）；图上画不出来的模块（空的 __init__.py）
       选中装着它的框；hot 视图里没跑到的，先退出 hot 视图。选中后滚到屏幕中间、闪一下。
       返回最后选中的节点（选中的是框或什么都没选时返回 null） */
    revealNode: function (id, kind) {
      if (this.lanesMode()) return this.revealLane(id, kind);
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
        var d = kind === 'unit' ? CS.ids.dirOf(x) : x, ids = frames().map(function (f) { return f.id; });
        return ids.indexOf(CS.ids.residual(d)) >= 0 ? CS.ids.residual(d) : ids.indexOf(d) >= 0 ? d : null;
      }
      function exitHot() {                        // 「只看跑到的」里没有它：退出 hot 视图再找
        st.onlyHot = false;
        self._onlyHotChosen = true;               // 之后换阶段、展开收起不再替用户切回去
        var b = document.querySelector('[data-t="onlyhot"]'); if (b) b.setAttribute('aria-pressed', 'false');
        self.redraw();
        CS.viewer.toast('它这次没跑到，已退出「只看跑到的」');
      }
      function finish() {
        var h = self.homeOf(id, kind);
        // hot 视图里没画它，但完整的图上有：它这次没跑到——退出 hot 视图再找
        if ((!h || !drawn(h)) && st.onlyHot && !self.lanesMode() && self.homeOf(id, kind, self.data.graph)) { exitHot(); h = self.homeOf(id, kind); }
        if (h && drawn(h)) return show(h);
        var f = frameOf(id);
        return f ? showFrame(f, '它在图上没有节点（没有类、函数，也没有 import 关系——比如空的 __init__.py）') : null;
      }
      if (frames().some(function (f) { return f.id === id; })) return Promise.resolve(showFrame(id));
      if (this.data.open.indexOf(id) >= 0) {       // 只有一个根时根就是整张图，不画框
        CS.graph.clear();
        var gb = document.querySelector('.gbox'); if (gb) gb.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return Promise.resolve(null);
      }
      var h0 = this.homeOf(id, kind);
      if (h0 === id) return Promise.resolve(finish());
      return CS.ds.reveal(id, this.curOpen()).then(function (r) {
        return self.setCut(r.open, id).then(function (done) { return done ? finish() : null; });
      }).catch(function () { return finish(); });
    },

    /* 分列里把一个模块找出来并选中：选这一段里调到它的第一列里的那一份；它在那一列里被收在某个目录里时，只在那一列里展开到它
       （serve 算要展开哪些，用户 10-02：搜索只改一列），等分列画好再选。哪条线程都没调到它就说一声。不碰「只看跑到的」 */
    revealLane: function (id, kind) {
      var self = this;
      // 分列还在取数 / 改切面还在路上：等画好了再在新图上找（不然找的是旧图、或者还什么都没画）。
      // 等的时候换成了模块图（静态图、没录时序事件的 run）：照模块图找
      return CS.lanes.settled().then(function () { return self.lanesMode() ? self._revealLane(id, kind) : self.revealNode(id, kind); });
    },
    _revealLane: function (id, kind) {
      var self = this, lanes = CS.lanes, L = lanes.L;
      if (!self.lanesMode()) return Promise.resolve(self.revealNode(id, kind));
      if (!lanes.ready || !L) { CS.viewer.toast('按线程分列没画出来'); return Promise.resolve(null); }
      // 这一段里调到它的第一列（列的先后）：这一列调到的单元有在它里面的。只改这一列（用户 10-02），收着的进程先展开
      var units = L.units || [], under = { nodes: [{ id: id }] };
      var ln = L.lanes.filter(function (x) {
        return (x.u || []).some(function (i) { return units[i] === id || self.homeOf(units[i], 'unit', under) === id; });
      })[0];
      if (!ln) { CS.viewer.toast('这一段里哪条线程都没调到它'); return Promise.resolve(null); }
      if (lanes.collapsed[ln.pid]) lanes.fold(ln.pid, false);
      function home() { return self.homeOf(id, kind, lanes.asGraph(ln.id)); }
      function opened() { return CS.laneCut.of(ln.id).indexOf(id) >= 0; }
      function done() {
        if (!self.lanesMode()) return self.revealNode(id, kind);
        if (lanes.fpos[ln.id + '|' + id]) return lanes.revealFrame(id, ln.id);   // 这一列里它展开着：选中那个框
        if (opened()) {                             // 展开着、没有框（单根仓库的根就是整张图）：选它底下的第一个节点
          var x = lanes.nodes.filter(function (n) { return n.lane === ln.id && CS.ids.within(n.id, id); })[0];
          return x ? lanes.reveal(x.id, ln.id) : null;
        }
        var h = home();
        if (h) return lanes.reveal(h, ln.id);
        CS.viewer.toast('这一段里哪条线程都没调到它');
        return null;
      }
      if (opened() || home() === id) return Promise.resolve(done());   // 已经展开着的不要再去算（会把它收起来）
      return CS.ds.reveal(id, CS.laneCut.of(ln.id)).then(function (r) {   // 在这一列的切面上要展开哪些
        if (!self.lanesMode()) return self.revealNode(id, kind);
        var cur = CS.laneCut.of(ln.id).sort().join(','), want = (r.open || []).slice().sort().join(',');
        if (want === cur) return done();
        return CS.laneCut.set(ln.id, r.open, id).then(function () { return lanes.settled(); }).then(done);
      }).catch(function () { return done(); });
    },

    /* 详情里点了节点名 / 边上的次数：分列里选中同一列里的那一份（边、节点）；模块图照旧 */
    goNode: function (id) {
      if (this.lanesMode()) CS.lanes.pickNode(id, CS.lanes.selLane());
      else CS.graph.pick(id);
    },
    goEdge: function (a, b) {
      if (!this.lanesMode()) return CS.graph.pickEdge(a, b);
      var E = CS.lanes.byKey['e:' + CS.lanes.selLane() + '|' + a + '|' + b];
      if (E) CS.lanes.open(E); else CS.panel.showEdge(a, b);
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
      b.style.display = same && !(this.lanesMode() && CS.laneCut.any()) ? 'none' : '';
    },

    /* 叠着录了时序事件的 run：运行时的图一律按进程 · 线程分列（lanes.js；用户 10-01 定的，不要合成一张图的功能） */
    lanesMode: function () { return !!(this.data && this.data.hot && this.runHasEvents()); },

    /* 画中间那张图：分列（lanesMode）或模块图。keep：改切面来的，分列不清详情面板（画好后 laneCut.restore 接着选） */
    drawMain: function (keep) {
      var d = this.data, s = CS.graph.state, lanes = this.lanesMode();
      document.body.classList.toggle('lanesmode', lanes);
      // 分列也把当前 run 的叠加交给 CS.graph.hot：详情面板、搜索、代码窗口、开关都按它取运行时的次数
      if (lanes) { CS.graph.hot = d.hot; if (!keep) CS.graph.clear(); CS.lanes.show(); return; }
      CS.lanes.cancel();                              // 离开分列：还在路上的分列取数回来也不画，撤掉 #g 上点线的监听、提示、单子
      CS.lanePick.leave();
      CS.lanes.picker = null;
      CS.graph.draw(document.getElementById('g'), s.onlyHot && d.graphHot ? d.graphHot : d.graph, d.hot,
                    { rtOnly: d.runtimeOnlyEdges });
    },

    /* 分列画好了（取数是异步的）：开关上的条数、时间顺序的名次按它重数 */
    lanesDrawn: function () {
      // 「叠加 run …」「重新汇总…」：分列是这时才画好（后面还有一次改切面在路上的话留着）
      if (!this._pending) document.getElementById('prog').textContent = '';
      this.lanesChanged();
    },
    /* 分列重画了（取数画好，或者收起 / 展开一个进程）：开关上的条数、时间顺序的名次、搜索的高亮按它重来 */
    lanesChanged: function () { this.edgeChips(); this.controls(); this.cutBar(); if (CS.search) CS.search.reapply(); },

    /* 开关变了：重新上色（分列或模块图） */
    repaint: function () { if (this.lanesMode()) CS.lanes.paint(); else CS.graph.paint(); },

    redraw: function (keep) {
      CS.graph.phaseMarks = this.phaseMarks();
      this.drawMain(keep);
      this.applyTimes();
      // 重画会重建所有节点：图例上边的条数按这张图重数，搜索栏里还有字就把高亮重新套上
      this.edgeChips();
      this.controls();
      if (CS.search) CS.search.reapply();
    },

    controls: function () {
      var s = CS.graph.state, self = this;
      var KEY = { scan: 'scan', hot: 'hot', dyn: 'dyn', onlyhot: 'onlyHot',
                  timeorder: 'timeOrder' };
      [].forEach.call(document.querySelectorAll('[data-t]'), function (b) {
        var key = KEY[b.dataset.t];
        if (key === 'onlyHot') {                 // 换 run 时会来回切：没叠 runtime 就藏起来
          b.style.display = CS.graph.hot ? '' : 'none';
          if (!CS.graph.hot) return;
        }
        b.onclick = function () {
          s[key] = b.getAttribute('aria-pressed') !== 'true';
          b.setAttribute('aria-pressed', s[key]);
          if (key === 'onlyHot') self._onlyHotChosen = true;     // 用户自己点过：之后换 run 不再替他打开
          // 「只看跑到的」换成单独排版的 hot 图，而不是在总图上隐藏——隐藏的节点还占着位置
          if (key === 'onlyHot' && self.data.graphHot) self.redraw();
          else if (key === 'timeOrder') self.applyTimes();
          else if (key === 'hot') { self.repaint(); self.edgeChips(); self.controls(); }   // 「其中代码里看不出」跟着它能不能点
          else { self.repaint(); if (self.lanesMode()) { self.edgeChips(); self.controls(); } }
        };
      });
      var rc = document.getElementById('resetcut');
      if (rc) rc.onclick = function () { self.resetCut(); };
      var pb = document.getElementById('pathbtn');
      if (pb) {                                  // 叠着 run 就有；没录时序事件的 run 点开说明为什么看不了
        pb.hidden = !CS.graph.hot;
        pb.onclick = function () { CS.path.show(); };
      }
      // 「视图」下面的两个按钮（只看跑到的、请求路径）都只在叠着 run 时有：没叠时标签也藏，不留一个空标签
      document.getElementById('viewlbl').style.display = CS.graph.hot ? '' : 'none';
      document.getElementById('reset').onclick = function () {
        if (CS.search) CS.search.clear();
        CS.graph.highlight(null); CS.graph.clear();
      };
      if (!this._esc) {
        this._esc = true;
        document.addEventListener('keydown', function (ev) {
          // Esc 取消选中（全文窗口开着时 Esc 先关窗口，那边自己处理）
          // 正在输入框里打字（搜索框、文件树过滤）时 Esc 归输入框自己
          var s = CS.graph.state, t = ev.target;
          if (ev.isComposing || (t && t.closest && t.closest('input, textarea, select, [contenteditable]'))) return;
          if (ev.key === 'Escape' && !document.getElementById('help').hidden) { self.help(false); return; }
          if (ev.key === 'Escape' && document.getElementById('viewer').hidden
              && (s.sel || s.selEdge || s.selFrame)) CS.graph.clear();
        });
      }
    },

    footer: function (d) {
      var r = d.repo;
      document.getElementById('foot').innerHTML =
        'codestrata · 静态的调用图扫描自 <code>' + esc((r.roots || []).join(', '))
        + '</code>（' + r.n_files + ' 个文件，解析失败 ' + r.n_parse_errors + '）'
        + (d.hot ? '；运行时的部分是 trace 录下的 run ' + esc(d.hot.run || '') : '') + '。';
    }
  };
  // 内联进宿主页面时脚本可能在 DOMContentLoaded 之后才跑，那时再监听就永远等不到
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function () { CS.app.boot(); });
  else CS.app.boot();
})(window.CS);
