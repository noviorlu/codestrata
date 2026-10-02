/* 分列里每列各自的切面（用户 2026-10-02：「我点击一个thread的expand collapse不应该影响另外一个thread或者是进程」）。
 *
 * base 是共用的切面：模块图的那个（CS.app.curOpen()），没单独改过的列都用它；cuts[列 id] 是这一列单独的切面。
 * 换阶段 / 时间段（同一个 run）保留各列的，换 run 清掉、回到共用的切面；「重置切面」也清掉（用户 10-02）。
 * 改一列只重取 /api/lanes（模块图那份数据不动），画好后由 lanes.js 只在这一列里闪新节点、接着选。 */
window.CS = window.CS || {};
(function (CS) {
  'use strict';
  function key(open) { return (open || []).slice().sort().join(','); }

  CS.laneCut = {
    run: null, cuts: {},

    /* 一列现在的切面 */
    of: function (lane) { return (this.cuts[lane] || CS.app.curOpen()).slice(); },

    /* 改一列的切面：和共用的一样就去掉单独的那份。focus：这次展开 / 收起的那个目录（画好后滚到它） */
    set: function (lane, open, focus) {
      if (key(open) === key(CS.app.curOpen())) delete this.cuts[lane];
      else this.cuts[lane] = open.slice();
      // 画好之后的收尾：前一次（共用切面变了、或者别的列）还没画好就把它并进来，别盖掉——不然那几列不闪、详情不按新数据重画
      var lanes = CS.lanes, a = lanes.afterCut, now = lanes.beforeMap();
      if (!a) lanes.afterCut = a = { lane: lane, before: {}, kind: lanes.kinds() };
      else if (a.lane !== lane) a.lane = null;       // 不止一列（或者共用的）：所有列都算
      if (!a.before[lane]) a.before[lane] = now[lane] || {};
      a.focus = focus; a.focusLane = lane;
      document.getElementById('prog').textContent = '重新汇总…';
      return lanes.show();
    },

    /* 一个目录在这一列里：展开、收起（收起一个节点 = 收起套着它的那个框；框是本层文件的只去掉它自己，目录的连同底下展开的一起去掉） */
    expand: function (lane, id) {
      var open = this.of(lane);
      if (open.indexOf(id) < 0) open.push(id);
      return this.set(lane, open, id);
    },
    collapseFrame: function (lane, f) {
      return this.set(lane, this.of(lane).filter(function (x) {
        return CS.ids.isResidual(f) ? x !== f : !(x === f || CS.ids.within(x, f));
      }), f);
    },

    clear: function () { this.cuts = {}; },
    any: function () { return Object.keys(this.cuts).length > 0; },

    /* 换了数据（setCut 取回来的）：换了 run 就清掉各列单独的切面（换阶段、时间段不清） */
    adopt: function (d) {
      var r = d && d.hotMeta && d.hotMeta.run_id;
      if (r !== this.run) { this.cuts = {}; this.run = r; }
    },

    /* 服务端认的切面（规范化之后）和共用的一样：去掉单独的那份 */
    settle: function (L) {
      var base = key(CS.app.curOpen()), self = this;
      (L.lanes || []).forEach(function (ln) { if (self.cuts[ln.id] && key(ln.open) === base) delete self.cuts[ln.id]; });
    },

    /* 改了切面、画好之后（lanes.show 画完调；a 是 lanes.afterCut：lane 改的是哪一列，没有就是共用的切面变了、所有列都算；
       before {列: {节点: 1}} 改之前各列画着的；focus 展开 / 收起的那个目录；kind 节点是哪种；snap 画好那一刻选着的）：
       改过的列里新出来的节点闪一下、滚进图框；用键盘点的 ＋ / − 随着重画没了，焦点交给新框框头的 −（收起时是收回来的那个节点）；
       接着选原来选着的（restore） */
    after: function (a) {
      if (!a) return;
      var lanes = CS.lanes;
      function mine(x) { return !a.lane || x.lane === a.lane; }
      var fresh = lanes.nodes.filter(function (x) { var b = a.before[x.lane]; return mine(x) && b && !b[x.id]; });
      fresh.forEach(function (x) {
        x.g.classList.add('fresh');
        setTimeout(function () { x.g.classList.remove('fresh'); }, 1600);
      });
      var target = fresh[0] || lanes.nodes.filter(function (x) { return mine(x) && x.id === a.focus; })[0];
      // 展开的：焦点给新框框头的 −（再按一下就收起，同模块图）；收起的：给收回来的那个节点
      var fr = lanes.frames.filter(function (f) { return f.id === a.focus && f.lane === (a.focusLane || a.lane); })[0];
      this.restore(a);
      var el = fr ? fr.h.querySelector('.xp') : target && target.g;
      if (!el) return;
      CS.graph.showEl(fr ? fr.h : target.g);
      var ae = document.activeElement;
      if (!ae || ae === document.body || !document.contains(ae)) el.focus({ preventScroll: true });
    },

    /* 接着选画好那一刻选着的（同模块图的 app.keepSelection），各列按自己的切面：
       - 节点 / 框：这一份在这一列里展开着（展开成了框，或者本来就是框）就选中那个框；只改了别的列、或者这一份还画着，只重选、
         重写详情里分线程的那几行（文件树、打开的源码不动）；被收进了别的节点就选那个节点（同一列）。共用的切面变了（换阶段之类）
         数据也变了，整个详情重画；
       - 边：两头按同样的规则落到新节点上，这一列里还有这条边就接着选它；连线按种类、通道、两头的列认，几条都对得上时取第一次的
         时刻对得上的（连线的 key 是下标，换了切面会变）。
       认不出来的（起 / 收的标签那种一次选好几条的也算）取消选中，免得详情里留着点了会选错的按钮 */
    restore: function (a) {
      var lanes = CS.lanes, app = CS.app, snap = a.snap || {}, s = snap.sel || '';
      if (!s) return;
      function home(lane, id) { return lanes.pos[lane + '|' + id] ? id : app.homeOf(id, a.kind[id], lanes.asGraph(lane)); }
      function opened(lane, id) { var ln = lanes.laneIx[lane]; return !!(ln && (ln.open || []).indexOf(id) >= 0 && lanes.fpos[lane + '|' + id]); }
      var p = s.slice(2).split('|'), E = null;
      if (s.indexOf('n:') === 0 || s.indexOf('f:') === 0) {
        var id = p.pop(), lane = p.join('|');
        if (opened(lane, id)) { lanes.pickFrame(id, lane, true); return; }
        if (a.lane && s.indexOf('n:') === 0 && lanes.pos[lane + '|' + id]) { lanes.select(s); CS.laneDetail.node(id, lane); return; }
        var h = home(lane, id);
        if (h) { lanes.pickNode(h, lane, true); return; }
      } else if (s.indexOf('e:') === 0) {
        var b = p.pop(), a2 = p.pop(), ln = p.join('|'), A = home(ln, a2), B = home(ln, b);
        E = A && B && lanes.byKey['e:' + ln + '|' + A + '|' + B];
        if (E && E.key === s && a.lane) { lanes.select(s); return; }   // 还是那条边：边详情不分线程、没变
      } else if (s.indexOf('l:') === 0 && snap.link) {
        var K = snap.link, same = lanes.links.filter(function (x) {
          return x.k.kind === K.kind && x.k.via === K.via && x.k.from.lane === K.from && x.k.to.lane === K.to;
        });
        E = same.filter(function (x) { return x.k.first === K.first; })[0] || same[0];
      }
      if (E) lanes.open(E, true); else CS.graph.clear();
    },

    /* /api/lanes 的 cuts 参数：同样切面的列合在一起 [{lanes, open}] */
    query: function () {
      var by = {}, out = [], self = this;
      Object.keys(this.cuts).forEach(function (lane) {
        var k = key(self.cuts[lane]);
        if (!by[k]) out.push(by[k] = { lanes: [], open: self.cuts[lane].slice().sort() });
        by[k].lanes.push(lane);
      });
      return out;
    }
  };
})(window.CS);
