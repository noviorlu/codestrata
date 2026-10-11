/* 和 agent 同步视图：agent 用 codestrata view set 推来的视图在这里套上，页面的现状顺带报回去（serve 的 viewhub.py）。
 *
 * 通道：POST api/view/poll {tab, report, wait}。有焦点时挂着等（最多 20 s），看得见没焦点时每秒问一次，看不见时不问、回来马上问。
 *   页面上改了什么（view.js 写地址之后）立刻再问一次，把新的现状报回去。标签页 id 每次加载随机生成；关页面时说一声（bye）。
 * 推来一条：
 *   · 「跟随 agent」关着：出提示条「agent 想换到：… · 换过去 · 不用」，等用户点；
 *   · 用户正在操作（按着鼠标，或 1.2 s 内按过键 / 滚过轮；在输入框里打字不算）：等他松手约 1 s 再换，最多等 10 s，之后改成提示条问；
 *   · 否则直接换：图上先出一层「agent 接手」的过渡（让用户知道现在是 agent 在动页面），pushState 进历史（后退就是撤销；
 *     2 s 内连着推的几次合成一条），view.js 按固定顺序套上，再出横幅「agent 换了视图：<说明> · 撤销 · 跟随 agent ✓」，8 s 后缩成小签。
 *   撤销（view back）：当前这一步是 agent 推的就后退一条历史，否则不撤（用户自己改过）。
 * 跟随开关记在 localStorage（只是这个浏览器的偏好，默认开）。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';

  var WAIT = 20, IDLE_MS = 1200, DEFER_MAX = 10000, MERGE_MS = 2000, BANNER_MS = 8000, MIN_VEIL = 650;

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function rid() {
    var a = new Uint8Array(8);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return Array.prototype.map.call(a, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  var S = CS.viewsync = {
    tab: rid(),
    follow: store('cs.follow') !== '0',
    by: 'boot',                       // 最后是谁改的：boot / user / url / history / agent（报给 viewhub）
    state: null,                      // 处理 agent 那一条的结果 {v, state, error}，下一次问的时候报回去
    _down: false, _input: 0, _ctrl: null, _busyV: 0, _agentAt: 0,

    busy: function () { return this._down || Date.now() - this._input < IDLE_MS; },

    /* view.js 套完一次（启动、粘进来的地址、后退、agent 推的）之后的样子：之后页面再变成别的样子，就是用户自己改的
       （展开节点、拖时间段这些直接重写地址、不经 changed 的也算上） */
    settled: function (v) { this._settled = v; },

    report: function () {
      var v = this._view || '';
      if (CS.app && CS.app.data && CS.view && !CS.view.applying) v = this._view = CS.view.format(CS.view.current());   // 套到一半的不报
      if (this.by !== 'user' && this._settled != null && v && v !== this._settled) this.by = 'user';
      var o = CS.lanes && CS.lanes.order;
      return { view: v, url: location.href.split('#')[0], visible: document.visibilityState === 'visible', focused: document.hasFocus(),
               busy: this.busy(), follow: this.follow, by: this.by, state: this.state,
               n: CS.graph && CS.graph.state.timeOrder && o ? o.n : null };
    },

    /* 页面的现状变了：马上再问一次（挂着的那条先断掉） */
    kick: function () { if (this._ctrl) this._ctrl.abort(); else if (this._wake) this._wake(); },

    _post: function (path, body, signal) {
      return fetch(path, { method: 'POST', signal: signal, keepalive: !signal,
                           headers: { 'X-Codestrata': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.ok ? r.json() : null; });
    },

    loop: function () {
      var self = this;
      function nap(ms) { return new Promise(function (r) { var t = setTimeout(r, ms); self._wake = function () { clearTimeout(t); r(); }; }); }
      (function step() {
        var vis = document.visibilityState === 'visible', focused = vis && document.hasFocus();
        self._ctrl = window.AbortController ? new AbortController() : null;
        self._post('api/view/poll', { tab: self.tab, report: self.report(), wait: focused ? WAIT : 0 }, self._ctrl && self._ctrl.signal)
          .then(function (r) {
            self._ctrl = null;
            if (r && r.push) self.receive(r.push);
            if (!vis) return new Promise(function (res) { self._wake = res; });   // 看不见：不问，回来时（visibilitychange）叫醒
            return focused ? null : nap(1000);
          }, function (e) {
            self._ctrl = null;
            return e && e.name === 'AbortError' ? null : nap(3000);           // 断掉的是自己：马上再问；serve 关了：过一会再试
          })
          .then(function () { self._wake = null; step(); });
      })();
    },

    /* 收到 agent 的一条：{v, op, view, note}。没说收到之前 serve 每次都再交一遍：按版本号去重 */
    receive: function (p) {
      if (p.v <= (this._seen || 0)) return;
      this._seen = p.v;
      this._busyV = p.v;                                 // 后来的一条顶掉还在等的
      if (p.op === 'back') return this.back(p);
      if (!this.follow) return this.offer(p, 'agent 想换到：');
      if (this.busy()) return this.defer(p);
      return this.apply(p);
    },

    reply: function (v, state, error) { this.state = { v: v, state: state, error: error || null }; this.kick(); },

    defer: function (p) {
      var self = this, t0 = Date.now();
      this.reply(p.v, 'deferred');
      (function wait() {
        if (self._busyV !== p.v) return;                 // 被后来的顶掉了
        if (!self.busy()) return void setTimeout(function () { if (self._busyV === p.v) self.apply(p); }, 300);
        if (Date.now() - t0 > DEFER_MAX) return self.offer(p, 'agent 想换视图，现在换？');
        setTimeout(wait, 200);
      })();
    },

    offer: function (p, lead) {
      var self = this;
      this.reply(p.v, 'offered');
      this.bar('<span class="agk">agent</span><span>' + esc(lead) + '</span><b>' + esc(p.note || '一个新视图') + '</b>'
               + '<button class="chip" data-ag="go">换过去</button><button class="chip" data-ag="no">不用</button>', 'offer', {
        go: function () { self.apply(p); },
        no: function () { self.reply(p.v, 'declined'); self.hide(); }
      });
    },

    /* 套上 agent 推来的视图：一条一条来（前一条的过渡放完再套下一条），被后来的顶掉的不套 */
    apply: function (p) {
      var self = this;
      this._chain = (this._chain || Promise.resolve()).then(function () {
        if (self._busyV === p.v) return self._apply1(p);
      });
      return this._chain;
    },

    /* 一条：过渡 → 进历史 → view.js 套 → 横幅 */
    _apply1: function (p) {
      var self = this, t0 = Date.now(), n0 = CS.lanes && CS.lanes.order ? CS.lanes.order.n : null;
      this.reply(p.v, 'applying');                       // 先说收到了：serve 别再交这一条
      var v = CS.view.parse(p.view), url = location.pathname + location.search + '#' + CS.view.format(v);
      this.veil(true, p.note);
      var top = history.state && history.state.agent;
      if (top && Date.now() - (history.state.t || 0) < MERGE_MS) history.replaceState({ agent: p.v, t: Date.now() }, '', url);
      else history.pushState({ agent: p.v, t: Date.now() }, '', url);
      CS.view.own(location.hash.replace(/^#/, ''));
      this.by = 'agent';
      return CS.view.apply(v, 'agent').then(function () {
        return sleep(Math.max(0, MIN_VEIL - (Date.now() - t0)));
      }).then(function () {
        self.veil(false);
        var n1 = CS.lanes && CS.lanes.order ? CS.lanes.order.n : null;
        self.banner(p.note, n0 !== null && n1 !== null && n0 !== n1);
        self.reply(p.v, 'applied');
      }, function (e) {
        self.veil(false);
        self.reply(p.v, 'failed', e && e.message);
      });
    },

    back: function (p) {
      var self = this;
      if (!(history.state && history.state.agent)) return this.reply(p.v, 'failed', '页面上这一步不是 agent 推的（用户之后自己改过）');
      this.reply(p.v, 'applying');
      this.veil(true, '撤销 agent 刚才的那一步');
      var done = function () {
        window.removeEventListener('popstate', done);
        setTimeout(function () {                         // view.js 的 popstate 先跑（先登记的），它套的那一次等完再回话
          Promise.resolve(CS.view.done).then(function () {
            self.veil(false); self.hide(); self.reply(p.v, 'applied');
          });
        }, 50);
      };
      window.addEventListener('popstate', done);
      history.back();
    },

    // ---- 过渡和横幅 ----
    veil: function (on, note) {
      var w = document.getElementById('gwrap');
      if (!w) return;
      var el = document.getElementById('agveil');
      if (on) {
        if (!el) {
          el = document.createElement('div'); el.id = 'agveil'; el.className = 'agveil';
          el.innerHTML = '<div class="agcard" role="status" aria-live="polite"><span class="agk">agent</span>'
            + '<b>agent 接手：换视图</b><span class="agnote"></span><i class="agbarline"></i></div>';
          w.appendChild(el);
        }
        el.querySelector('.agnote').textContent = note || '';
        el.classList.remove('off');
        void el.offsetWidth;                             // 先落一帧再加 on：淡入的过渡才会走
        el.classList.add('on');
        w.classList.add('agent');
      } else if (el) {
        el.classList.remove('on'); el.classList.add('off');
        w.classList.remove('agent');
      }
    },

    banner: function (note, renum) {
      var self = this;
      this.bar('<span class="agk">agent</span><span>换了视图：</span><b>' + esc(note || '（没写说明）') + '</b>'
               + (renum ? '<span class="agrn">编号变了</span>' : '')
               + '<button class="chip" data-ag="undo" title="回到 agent 换之前的视图（浏览器后退也行）">撤销</button>'
               + '<button class="chip" data-ag="follow" aria-pressed="' + this.follow + '" title="关掉之后 agent 推来的视图要你点了才换">跟随 agent</button>'
               + '<button class="agx" data-ag="x" aria-label="收起">×</button>', 'done', {
        undo: function () { self.hide(); history.back(); },
        follow: function (b) { self.setFollow(!self.follow); b.setAttribute('aria-pressed', self.follow); },
        x: function () { self.mini(); }
      });
      clearTimeout(this._bt);
      this._bt = setTimeout(function () { self.mini(); }, BANNER_MS);
    },

    bar: function (html, kind, acts) {
      var w = document.getElementById('gwrap');
      if (!w) return;
      var el = document.getElementById('agbar');
      if (!el) { el = document.createElement('div'); el.id = 'agbar'; w.appendChild(el); }
      clearTimeout(this._bt);
      el.className = 'agbar ' + kind;
      el.innerHTML = html;
      el.hidden = false;
      el.onclick = function (ev) {
        var b = ev.target.closest('[data-ag]');
        if (el.classList.contains('mini') && !b) { el.classList.remove('mini'); return; }
        if (b && acts[b.dataset.ag]) acts[b.dataset.ag](b);
      };
    },
    mini: function () { var el = document.getElementById('agbar'); if (el && el.classList.contains('done')) el.classList.add('mini'); },
    hide: function () { var el = document.getElementById('agbar'); if (el) el.hidden = true; clearTimeout(this._bt); },

    setFollow: function (on) { this.follow = !!on; store('cs.follow', on ? '1' : '0'); this.kick(); },

    init: function () {
      var self = this;
      function input(ev) {
        var t = ev.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;   // 在输入框里打字不算
        self._input = Date.now();
      }
      window.addEventListener('pointerdown', function () { self._down = true; self._input = Date.now(); }, true);
      window.addEventListener('pointerup', function () { self._down = false; self._input = Date.now(); }, true);
      window.addEventListener('pointercancel', function () { self._down = false; }, true);
      window.addEventListener('keydown', input, true);
      window.addEventListener('wheel', input, { capture: true, passive: true });
      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') self._post('api/view/poll', { tab: self.tab, report: self.report(), wait: 0 }).catch(function () {});
        self.kick();
      });
      window.addEventListener('focus', function () { self.kick(); });
      window.addEventListener('blur', function () { self.kick(); });
      window.addEventListener('pagehide', function () { self._post('api/view/bye', { tab: self.tab }).catch(function () {}); });
      this.loop();
    }
  };
})(window.CS);
