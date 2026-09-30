/* 主菜单（codestrata app）。分五块：
 *   api      —— fetch /api/*（带 X-Codestrata 头；口令在 cookie 里，浏览器自己带）
 *   cards    —— 项目卡片：状态、三个按钮（扫描 / 录制运行 / 打开图）、最近一个任务的输出
 *   jobs     —— 轮询在跑的任务，把新输出接到卡片上；结束后刷新卡片
 *   picker   —— 「打开文件夹」对话框：逐级浏览子目录
 *   scanner  —— 「静态扫描」对话框：勾选要扫描的目录（只列不挑，扫哪些由用户决定）
 *   recorder —— 「录制运行」对话框：表单 ↔ /api/template、/api/trace
 * 页面上的状态只有 projects（最近一次 /api/projects）和每个任务已经收到的行数。 */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function ago(ts) {
    var s = Date.now() / 1000 - ts;
    if (s < 60) return '刚刚';
    if (s < 3600) return Math.round(s / 60) + ' 分钟前';
    if (s < 86400) return Math.round(s / 3600) + ' 小时前';
    return Math.round(s / 86400) + ' 天前';
  }
  function showErr(el, msg) { el.textContent = msg || ''; el.hidden = !msg; }

  /* ---- api ---- */
  function api(path, method, body) {
    var opt = { method: method || 'GET', headers: { 'X-Codestrata': '1' } };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        if (!r.ok) throw new Error((b && b.error) || (path + ' → ' + r.status));
        return b;
      });
    });
  }
  function q(params) {
    return Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
  }

  /* ---- cards ---- */
  var projects = [];

  function refresh() {
    return api('/api/projects').then(function (ps) {
      projects = ps; render(); showErr($('err'), '');
      ps.forEach(function (p) { if (p.job && p.job.running) jobs.follow(p.path, p.job.id); });
    }).catch(function (e) { showErr($('err'), '读取项目失败：' + e.message); });
  }

  function facts(p) {
    if (!p.exists) return '<span class="warn">目录不在了</span>';
    var f = [];
    if (p.index) {
      f.push('<span class="ok">已扫描</span>', esc((p.index.roots || []).join('、')) + '：' + p.index.n_files + ' 个文件',
             '扫描于 ' + ago(p.index.scanned_at));
      if (p.index.outdated) f.push('<span class="warn">索引是旧版本的格式，要重新扫描才能看图</span>');
      else if (p.lag) f.push('<span class="warn">之后改过 ' + p.lag + ' 个文件，建议重新扫描</span>');
    } else f.push('<span class="warn">还没扫描</span>');
    if (p.runs_error) f.push('<span class="warn">' + esc(p.runs_error) + '</span>');
    else if (p.n_runs) {
      var r = p.runs[0];
      f.push(p.n_runs + ' 次录制', '最近：' + esc(r.case) + '（' + esc(r.status) + '）');
    }
    return f.map(function (x) { return '<span>' + x + '</span>'; }).join('');
  }

  function render() {
    var list = $('list');
    if (!projects.length) {
      list.innerHTML = '<div class="empty">还没有项目。点右上角「打开文件夹…」，选一个 Python 仓库。</div>';
      return;
    }
    list.innerHTML = projects.map(function (p) {
      var busy = !!(p.job && p.job.running), scanned = !!p.index && !p.index.outdated;
      return '<section class="card" data-path="' + esc(p.path) + '">'
        + '<div class="top"><span class="name">' + esc(p.name) + '</span><span class="path">' + esc(p.path) + '</span>'
        + '<button class="btn small ghost rm" data-act="remove" title="从清单里去掉（不动仓库里的任何文件）">移除</button></div>'
        + '<div class="facts">' + facts(p) + '</div>'
        + '<div class="btns">'
        + '<button class="btn" data-act="scan"' + (busy || !p.exists ? ' disabled' : '') + '>' + (scanned ? '重新扫描' : '静态扫描') + '</button>'
        + '<button class="btn" data-act="record"' + (busy || !p.exists ? ' disabled' : '') + '>录制运行…</button>'
        + '<button class="btn primary" data-act="open"' + (scanned ? '' : ' disabled title="先扫描"') + '>打开图</button>'
        + '</div>'
        + '<div class="job" hidden></div>'
        + '</section>';
    }).join('');
    projects.forEach(function (p) { if (p.job) jobs.show(p.path, p.job); });
  }

  function card(path) {
    var c = null;
    [].forEach.call(document.querySelectorAll('.card'), function (x) { if (x.dataset.path === path) c = x; });
    return c;
  }

  $('list').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-act]'); if (!b) return;
    var path = b.closest('.card').dataset.path, p = projects.find(function (x) { return x.path === path; });
    var act = b.dataset.act;
    if (act === 'scan') scanner.open(p);
    else if (act === 'record') recorder.open(p);
    else if (act === 'open') openGraph(p);
    else if (act === 'remove' && confirm('从清单里去掉 ' + path + '？\n（不会删仓库里的任何文件，录下的 run 也都还在）'))
      api('/api/projects?' + q({ path: path }), 'DELETE').then(refresh, function (e) { showErr($('err'), e.message); });
  });

  function start(url, body) {
    return api(url, 'POST', body).then(function (job) { jobs.follow(body.repo, job.id); return refresh(); });
  }

  function openGraph(p) {
    // 先同步开一个空白标签（异步回来再开会被弹窗拦截），拿到地址再跳过去
    var w = window.open('', '_blank');
    if (w) w.document.write('<p style="font:14px system-ui;padding:20px">正在启动图服务…（大仓库要几秒）</p>');
    // 录过的就直接叠最近一次录成的 run（刚录完点「打开图」，想看的就是它）
    var last = p.runs.filter(function (r) { return r.loadable; })[0];
    api('/api/open', 'POST', { repo: p.path }).then(function (r) {
      // 地址是 /v/<端口>/（经主菜单转发）：写成完整地址——新开的空白标签里相对地址不按主菜单解析
      var url = new URL(r.url, location.href).href + (last ? '#run=' + encodeURIComponent(last.id) : '');
      if (w) w.location.href = url; else location.href = url;
      refresh();
    }, function (e) {
      if (w) w.close();
      showErr($('err'), '打开图失败：' + e.message);
    });
  }

  /* ---- jobs ---- */
  // 卡片会整张重画（refresh），所以每个任务收到的输出存在这里，重画时放回去
  var jobs = (function () {
    var logs = {}, seen = {}, polling = {};   // job id → 已收到的输出；已收到的行数；正在轮询

    function title(j) {
      var what = j.kind === 'scan' ? '扫描' : '录制';
      if (j.running) return ['run', (j.stopping ? '正在停止' : what + '中') + '…'];
      if (j.returncode === 0) return ['good', what + '完成'];
      return ['bad', what + (j.stopping ? '已停止' : '失败') + '（退出码 ' + j.returncode + '）'];
    }

    function box(path) { var c = card(path); return c && c.querySelector('.job'); }

    function paint(path, j) {
      var b = box(path); if (!b) return;
      if (b.dataset.id !== j.id) {
        b.dataset.id = j.id;
        b.innerHTML = '<div class="jh"><span class="st"></span><span class="sub"></span>'
          + '<button class="btn small warn">停止</button></div>'
          + '<div class="cmd">' + esc(j.cmd) + '</div><pre></pre>';
        b.querySelector('button').onclick = function () { api('/api/jobs/' + j.id + '/stop', 'POST', {}); };
      }
      b.hidden = false;
      var t = title(j), st = b.querySelector('.st'), pre = b.querySelector('pre');
      st.className = 'st ' + t[0]; st.textContent = t[1];
      b.querySelector('.sub').textContent = j.running ? '开始于 ' + ago(j.started) : '';
      b.querySelector('button').hidden = !j.running;
      var stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
      pre.textContent = logs[j.id] || '';
      pre.hidden = !pre.textContent;
      if (stick) pre.scrollTop = pre.scrollHeight;
    }

    function take(j) {                          // 接上一次轮询拿到的新行
      if (j.lines.length) logs[j.id] = (logs[j.id] ? logs[j.id] + '\n' : '') + j.lines.join('\n');
      seen[j.id] = j.n;
    }

    function poll(path, id) {
      return api('/api/jobs/' + id + '?' + q({ since: seen[id] || 0 })).then(function (j) {
        take(j); paint(path, j);
        return j;
      });
    }

    /* 卡片重画时：放回这个任务的状态和已有输出；页面刚打开、还没拿过它的输出，就取一次全部 */
    function show(path, j) {
      paint(path, j);
      if (!(j.id in logs)) { logs[j.id] = ''; if (!j.running) poll(path, j.id); }
    }

    /* 跟着一个在跑的任务，直到结束，结束时刷新卡片（扫描完了「打开图」才能点、run 数会变） */
    function follow(path, id) {
      if (polling[id]) return;
      polling[id] = true;
      if (!(id in logs)) logs[id] = '';
      (function tick() {
        poll(path, id).then(function (j) {
          if (j.running) return setTimeout(tick, 700);
          delete polling[id]; refresh();
        }, function () { delete polling[id]; });
      })();
    }

    return { follow: follow, show: show };
  })();

  /* ---- picker ---- */
  var picker = (function () {
    var cur = null;

    function go(path) {
      showErr($('pickErr'), '');
      return api('/api/browse?' + q({ path: path || '' })).then(function (d) {
        cur = d;
        $('pickPath').value = d.path;
        $('pickUp').disabled = !d.parent;
        var h = d.here;
        $('pickHere').textContent = h.python || h.git ? '这个目录' + (h.python ? '有 Python 工程文件' : '是 git 仓库') + (h.scanned ? '，已扫描过' : '') : '';
        $('pickList').innerHTML = d.dirs.length ? d.dirs.map(function (x) {
          return '<li><button data-path="' + esc(x.path) + '">📁 ' + esc(x.name)
            + (x.python ? ' <span class="tag py">Python</span>' : '') + (x.git ? ' <span class="tag">git</span>' : '')
            + (x.scanned ? ' <span class="tag sc">已扫描</span>' : '') + '</button></li>';
        }).join('') + (d.more ? '<li class="none">…子目录太多，只列了前面的；可以直接在上面输入路径</li>' : '')
          : '<li class="none">没有子目录</li>';
      }, function (e) { showErr($('pickErr'), e.message); });
    }

    $('pickList').addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-path]'); if (b) go(b.dataset.path);
    });
    $('pickUp').onclick = function () { if (cur && cur.parent) go(cur.parent); };
    $('pickGo').onclick = function () { go($('pickPath').value.trim()); };
    $('pickPath').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); go(this.value.trim()); } });
    $('pickCancel').onclick = function () { $('pick').close(); };
    $('pickOk').onclick = function () {
      api('/api/projects', 'POST', { path: $('pickPath').value.trim() }).then(function () {
        $('pick').close(); refresh();
      }, function (e) { showErr($('pickErr'), e.message); });
    };

    return { open: function () { $('pick').showModal(); go(cur ? cur.path : ''); } };
  })();
  $('addBtn').onclick = picker.open;

  /* ---- scanner ---- */
  var scanner = (function () {
    var repo = null;

    function chosen() {
      return [].filter.call($('scanList').querySelectorAll('input'), function (i) { return i.checked; })
        .map(function (i) { return i.value; });
    }
    // 同名（最后一段一样）的目录一次只能扫一个：模块名按它起，会撞在一起（服务端 scan.root_clashes 也挡）
    function clashes() {
      var by = {};
      [].forEach.call($('scanList').querySelectorAll('input:checked'), function (i) {
        (by[i.dataset.name] = by[i.dataset.name] || []).push(i.value);
      });
      return Object.keys(by).filter(function (k) { return by[k].length > 1; }).map(function (k) { return by[k].join('、'); });
    }
    function sum() {
      var n = chosen().length, c = clashes();
      $('scanOk').disabled = !n || c.length > 0;
      $('scanSum').textContent = c.length ? '同名的一次只能选一个：' + c.join('；')
        : n ? '勾了 ' + n + ' 个目录' : '至少勾一个';
    }
    function setAll(on) {
      [].forEach.call($('scanList').querySelectorAll('input'), function (i) { i.checked = on; });
      sum();
    }

    $('scanList').addEventListener('change', sum);
    $('scanAll').onclick = function () { setAll(true); };
    $('scanNone').onclick = function () { setAll(false); };
    $('scanCancel').onclick = function () { $('scanDlg').close(); };
    $('scanOk').onclick = function () {
      start('/api/scan', { repo: repo, roots: chosen() }).then(function () { $('scanDlg').close(); },
        function (e) { showErr($('scanErr'), e.message); });
    };

    return {
      open: function (p) {
        repo = p.path;
        $('scanRepo').textContent = p.path;
        showErr($('scanErr'), '');
        api('/api/scan-roots?' + q({ repo: repo })).then(function (d) {
          var on = {};
          d.chosen.forEach(function (r) { on[r] = 1; });
          $('scanList').innerHTML = d.candidates.length ? d.candidates.map(function (c) {
            return '<li><label><input type="checkbox" value="' + esc(c.path) + '" data-name="' + esc(c.name) + '"'
              + (on[c.path] ? ' checked' : '') + '>'
              + (c.path === '.' ? '<code>./*.py</code> 仓库根目录直接放着的脚本（只取这一层）'
                                 : '<code>' + esc(c.path) + '/</code>') + (c.package ? ' <span class="tag py">Python 包</span>' : '')
              + (c.previous ? ' <span class="tag">上次选的</span>' : '')
              + '<span class="n">' + c.files + ' 个 .py</span></label></li>';
          }).join('') : '<li class="none">这个文件夹里没有 .py 文件</li>';
          sum();
          $('scanDlg').showModal();
        }, function (e) { showErr($('err'), '读取可扫描的目录失败：' + e.message); });
      }
    };
  })();

  /* ---- recorder ---- */
  var recorder = (function () {
    // current：最近一次填进表单的初始值。表单上不显示的字段（tags、roots、stop_grace）从它原样带回去，
    // 复刻出来的命令才和原来的一样
    var repo = null, symTimer = null, current = {};

    function phaseRow(name, func) {
      var row = $('phaseRow').content.firstElementChild.cloneNode(true);
      row.querySelector('.pname').value = name || '';
      row.querySelector('.pfunc').value = func || '';
      row.querySelector('button').onclick = function () { row.remove(); };
      $('recPhases').appendChild(row);
    }

    function fill(t) {
      current = t;
      $('recCase').value = t.case || '';
      $('recCmd').value = t.command || '';
      $('recTimeout').value = t.timeout == null ? '' : t.timeout;
      $('recEnv').value = Object.keys(t.env || {}).map(function (k) { return k + '=' + t.env[k]; }).join('\n');
      $('recNote').value = t.note || '';
      $('recCwd').value = t.cwd || '';
      $('recAttach').value = (t.attach || []).join('\n');
      $('recEvents').checked = t.events !== false;
      $('recPhases').innerHTML = '';
      (t.phases || []).forEach(function (p) { phaseRow(p[0], p[1]); });
    }

    function template(run) {
      showErr($('recErr'), '');
      return api('/api/template?' + q({ repo: repo, run: run || '' })).then(fill, function (e) { showErr($('recErr'), e.message); });
    }

    function lines(text) { return text.split('\n').map(function (s) { return s.trim(); }).filter(Boolean); }

    function collect() {
      var env = {}, bad = [];
      lines($('recEnv').value).forEach(function (l) {
        var i = l.indexOf('=');
        if (i <= 0) bad.push(l); else env[l.slice(0, i)] = l.slice(i + 1);
      });
      if (bad.length) throw new Error('环境变量要写成 K=V：' + bad.join('，'));
      return {
        repo: repo, case: $('recCase').value.trim(), command: $('recCmd').value.trim(),
        timeout: $('recTimeout').value.trim() || null, env: env, note: $('recNote').value.trim(),
        cwd: $('recCwd').value.trim() || null,
        attach: lines($('recAttach').value), events: $('recEvents').checked,
        tags: current.tags || [], roots: current.roots || null, stop_grace: current.stop_grace || null,
        phases: [].map.call($('recPhases').querySelectorAll('.phase'), function (r) {
          return [r.querySelector('.pname').value.trim(), r.querySelector('.pfunc').value.trim()];
        }).filter(function (p) { return p[0] || p[1]; })
      };
    }

    // 阶段的函数输入框：按输入去 /api/symbols 取候选，放进 <datalist>
    $('recPhases').addEventListener('input', function (ev) {
      if (!ev.target.classList.contains('pfunc')) return;
      var v = ev.target.value.split(':').pop().trim();
      clearTimeout(symTimer);
      if (v.length < 2) return;
      symTimer = setTimeout(function () {
        api('/api/symbols?' + q({ repo: repo, q: v })).then(function (ks) {
          $('symList').innerHTML = ks.map(function (k) { return '<option value="' + esc(k) + '">'; }).join('');
        }, function () {});
      }, 200);
    });
    $('recAddPhase').onclick = function () { phaseRow('', ''); };
    $('recFrom').onchange = function () { template(this.value); };   // 换一个 run：整张表照它重填
    $('recCancel').onclick = function () { $('rec').close(); };
    $('recForm').onsubmit = function (ev) {
      ev.preventDefault();
      var body;
      try { body = collect(); } catch (e) { return showErr($('recErr'), e.message); }
      api('/api/trace', 'POST', body).then(function (job) {
        $('rec').close(); jobs.follow(repo, job.id); refresh();
      }, function (e) { showErr($('recErr'), e.message); });
    };

    return {
      open: function (p) {
        repo = p.path;
        $('recRepo').textContent = p.path;
        $('recFrom').innerHTML = '<option value="">— 不用，从空白开始 —</option>' + p.runs.map(function (r) {
          return '<option value="' + esc(r.id) + '">' + esc(r.case) + ' · ' + esc(r.id) + '（' + esc(r.status) + '）</option>';
        }).join('');
        $('fromRow').hidden = !p.runs.length;
        // 有录过的就默认照最近一次填：大多数时候是「同样的命令再录一次」
        $('recFrom').value = p.runs.length ? p.runs[0].id : '';
        // 表填好了再弹出来：不然用户先打的字会被晚到的初始值盖掉
        template($('recFrom').value).then(function () { $('rec').showModal(); });
      }
    };
  })();

  refresh();
})();
