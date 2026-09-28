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
      CS.ds.graph(null, CS.graph.boxWidth()).then(function (d) {
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
                      { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges });
        self.edgeChips();
        self.controls();
        self.cutBar();
        self.refreshStatus();
        self.footer(d);
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
        t.textContent = a.split('.').pop() + ' → ' + b.split('.').pop();
        s.textContent = '这条依赖具体用了对方哪些函数 / 类';
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

    /* 帮助里「这次跑了什么」：case 命令、脚本内容、被 trace 的进程（按命令合并，跑到仓库代码多的在前） */
    runHtml: function (m) {
      var h = '<h3>这次跑了什么</h3><div class="run"><div class="cmdline"><span class="lab">case 命令</span><code>'
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

    wireRun: function () { /* 目前只是静态内容；留个口子给以后的交互 */ },

    header: function (d) {
      var r = d.repo, self = this;
      document.getElementById('h1').textContent = r.name + ' 架构';
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
      if (d.hot && d.hotMeta) {
        var m = d.hotMeta;
        document.getElementById('hotbanner').innerHTML =
          '<div class="hotbanner"><div><b>hot 图</b>：case <b>' + esc(m.case) + '</b>　'
          + (m.run_id ? '<span class="lab">run ' + esc(m.run_id) + '</span>　' : '')
          + (m.phase ? '阶段 <b>' + esc(m.phase) + '</b>　' : '')
          + (m.status && m.status !== 'ok' ? '<span style="color:var(--stale)">⚠ 这次录制不完整'
             + (m.problems && m.problems.length ? '：' + esc(m.problems.join('；')) : '') + '</span>　' : '')
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
          + (m.stale_files && m.stale_files.length ? '<span style="color:var(--stale)" title="'
             + esc(m.stale_files.slice(0, 30).join('\n')) + '">⚠ 录制后有 '
             + m.stale_files.length + ' 个文件改过或删掉了，这些文件上的叠加可能偏</span>　' : '')
          + '</div></div>' + self.runHtml(m);
        self.wireRun();
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
                    { kinds: d.edgeKinds, rtOnly: d.runtimeOnlyEdges });
      if (CS.graph.noteStatus) CS.graph.setNoteStatus(CS.graph.noteStatus);
      // 重画会重建所有节点：图例上边的条数按这张图重数，搜索栏里还有字就把高亮重新套上
      this.edgeChips();
      this.controls();
      if (CS.search) CS.search.reapply();
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
