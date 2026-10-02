// 按进程 · 线程分列（lanes.js）：叠着录了时序事件的 run 就是它，没有切回一张图的开关（用户 10-01）；列按进程分组，
// 列里是这条线程调到的节点；鼠标停在节点上连上它在别的列里的副本；每条线各有各的接点和轨道，点哪条按离鼠标最近的算，
// 悬停的提示和会选中的是同一条，叠着几条时弹单子挑；列之间的连线能点，
// 详情里是两头的代码，选中时两头的节点下面标出那一行；起线程 / 回收线程的节点描绿 / 红、列头写起 / 收；「这次跑了」管列里的边；
// 进程能收起；没录时序事件的 run 照旧是一张图
import { sleep, waitRun } from '../lib.mjs';

/* 一条边 / 连线（CS.lanes 里的 E）上点下去会选中它的一点（屏幕坐标）：先滚到看得见，从 f 处开始沿路径找离鼠标最近的就是它
   （CS.lanes.hitAt，点击用的同一个判断）、没被节点 / 牌子盖住的地方；都不行就点它的标签 */
const at = (page, expr, f) => page.ev(`(E => {
  CS.graph.showEl(E.p);
  const L = E.p.getTotalLength(), m = E.p.getScreenCTM();
  for (const g of [${f}, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.15, 0.85, 0.1, 0.9]) {
    const p = E.p.getPointAtLength(L * g), x = p.x * m.a + p.y * m.c + m.e, y = p.x * m.b + p.y * m.d + m.f;
    const top = document.elementFromPoint(x, y), h = CS.lanes.hitAt(x, y);
    if (top && top.closest('.ln-nd, .tn, .ln-code, .ln-mark, .ln-proc')) continue;
    if (top === E.lab || (h.length && h[0].E === E && !(h[1] && h[1].d - h[0].d < 1.5))) return { x, y, key: E.key };
  }
  if (E.lab) {
    const b = E.lab.getBoundingClientRect(), x = b.left + b.width / 2, y = b.top + b.height / 2;
    if (document.elementFromPoint(x, y) === E.lab) return { x, y, key: E.key };
  }
  return null;
})(${expr})`);

async function click(page, p) {
  await sleep(150);
  await page.mouse('mouseMoved', p.x, p.y); await page.mouse('mousePressed', p.x, p.y, 1); await page.mouse('mouseReleased', p.x, p.y);
  await sleep(300);
}

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '叠上 run A（录了时序事件）');
  ok(await page.ev(`document.body.classList.contains('lanesmode') && document.querySelectorAll('#g .ln-nd').length > 0`), '按线程分列');
  ok(await page.ev(`!document.querySelector('[data-t="lanes"]') && getComputedStyle(document.querySelector('[data-t="onlyhot"]')).display === 'none'`),
     '没有切回一张图的开关，「只看跑到的」也藏起来');
  const s = JSON.parse(await page.ev(`JSON.stringify({
    cols: [...document.querySelectorAll('#g .ln-col .ln-th')].map(x => x.textContent),
    procs: document.querySelectorAll('#g .ln-proc').length,
    hand: document.querySelectorAll('#g .ln-link.handoff').length, spawn: document.querySelectorAll('#g .ln-link.spawn').length })`));
  ok(s.cols.includes('MainThread') && s.cols.includes('consumer') && s.cols.some(c => /^worker ×2$/.test(c)), '列：主线程、consumer、worker ×2 ' + JSON.stringify(s.cols));
  ok(s.procs >= 2, '按进程分组（fork 出来的进程各一组）' + s.procs);
  ok(s.hand >= 1 && s.spawn >= 1, '列之间有交接、谁起了谁的连线 ' + JSON.stringify(s));

  // 鼠标停在一个在几列里都有的节点上：副本高亮、连上
  const r = await page.ev(`(() => {
    const ids = {}; document.querySelectorAll('#g .ln-nd').forEach(g => { ids[g.dataset.id] = (ids[g.dataset.id] || 0) + 1; });
    const id = Object.keys(ids).find(k => ids[k] > 1);
    const g = [...document.querySelectorAll('#g .ln-nd')].find(x => x.dataset.id === id);
    CS.graph.showEl(g);
    const b = g.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2, id, ids[id], g.dataset.lane];
  })()`);
  await page.mouse('mouseMoved', r[0], r[1]);
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd.twin').length === ${r[3]} && document.querySelectorAll('#g .ln-twin').length === ${r[3] - 1}`, 3000),
     '悬停：' + r[2] + ' 的 ' + r[3] + ' 份都高亮、连上');
  // 点节点：选中、详情栏打开讲它
  await click(page, { x: r[0], y: r[1] });
  ok(await page.wait(`CS.lanes.sel === 'n:' + ${JSON.stringify(r[4] + '|' + r[2])} && document.getElementById('drawer').classList.contains('open')
                      && document.getElementById('det').dataset.pkg === ${JSON.stringify(r[2])}`, 5000), '点节点：选中、详情栏打开讲它');
  // 和模块图一样：碰到它的边、连线高亮，它们另一头的节点照常，别的淡下去。只算点的这一份（这一列），别的列里的副本也淡下去
  const nb = JSON.parse(await page.ev(`JSON.stringify((() => {
    const id = ${JSON.stringify(r[2])}, lane = ${JSON.stringify(r[4])}, keep = new Set([lane + '|' + id]), bad = [];
    const touch = E => E.kind === 'edge' ? E.lane.id === lane && (E.e.a === id || E.e.b === id)
      : (E.k.from.lane === lane && E.k.from.node === id) || (E.k.to.lane === lane && E.k.to.node === id);
    const ends = E => E.kind === 'edge' ? [E.lane.id + '|' + E.e.a, E.lane.id + '|' + E.e.b]
      : [E.k.from.lane + '|' + E.k.from.node, E.k.to.lane + '|' + E.k.to.node];
    let hi = 0, dim = 0;
    CS.lanes.edges.concat(CS.lanes.links).forEach(E => {
      const t = touch(E), c = E.p.classList;
      if (t) { hi++; ends(E).forEach(k => keep.add(k)); }
      if (t !== c.contains('hi') || t === c.contains('dim')) bad.push(E.key);
      if (c.contains('dim')) dim++;
    });
    let nd = 0;
    CS.lanes.nodes.forEach(x => {
      const k = x.lane + '|' + x.id, want = keep.has(k), d = x.g.classList.contains('dim');
      if (want === d) bad.push(k);
      if (d) nd++;
    });
    const sel = CS.lanes.nodes.filter(x => x.g.classList.contains('sel')).map(x => x.lane + '|' + x.id);
    const otherCopies = CS.lanes.nodes.filter(x => x.id === id && x.lane !== lane && !keep.has(x.lane + '|' + x.id) && !x.g.classList.contains('dim')).length;
    return { hi, dim, nd, sel, otherCopies, bad: bad.slice(0, 5) };
  })())`));
  ok(nb.hi > 0 && nb.dim > 0 && nb.nd > 0 && nb.bad.length === 0 && nb.sel.length === 1 && nb.sel[0] === r[4] + '|' + r[2] && nb.otherCopies === 0,
     '选中节点：只有点的这一份选中，这一列里碰到它的 ' + nb.hi + ' 条边 / 连线高亮、另一头的节点照常，别的（包括别的列里的副本）淡下去（'
     + nb.dim + ' 条线、' + nb.nd + ' 个节点）' + JSON.stringify(nb.bad));

  // 排线：每条线的路径都不一样；每一条线沿路径取点，离鼠标最近的就是它（点下去选中它）的地方占大多数，没有一条点不到
  const sp0 = JSON.parse(await page.ev(`JSON.stringify((() => {
    const all = CS.lanes.edges.concat(CS.lanes.links).filter(E => E.show !== false), zero = [];
    let tot = 0, own = 0, wrong = 0;
    for (const E of all) {
      const L = E.p.getTotalLength(), m = () => E.p.getScreenCTM();
      let o = 0;
      for (let i = 1; i < 12; i++) {
        const p = E.p.getPointAtLength(L * i / 12);
        CS.graph.showEl(E.p);
        const M = m(), x = p.x * M.a + p.y * M.c + M.e, y = p.x * M.b + p.y * M.d + M.f, h = CS.lanes.hitAt(x, y);
        if (!h.length) continue;
        tot++;
        if (h[0].E === E || (h[1] && h[1].d - h[0].d < 1.5 && h.some(z => z.E === E))) { own++; o++; } else wrong++;
      }
      if (!o) zero.push(E.key);
    }
    return { n: all.length, uniq: new Set(all.map(E => E.p.getAttribute('d'))).size, tot, own, wrong, zero };
  })())`));
  ok(sp0.uniq === sp0.n, '每条线的路径都不一样（' + sp0.n + ' 条）');
  ok(sp0.zero.length === 0 && sp0.wrong === 0 && sp0.own === sp0.tot,
     '沿每条线取点，离鼠标最近的都是它自己（或一样近、会弹单子）：' + sp0.own + ' / ' + sp0.tot + ' ' + JSON.stringify(sp0.zero.slice(0, 4)));
  // 悬停：最近的那条加粗，停一会儿出的提示就是它的
  const hp = await at(page, `CS.lanes.links.find(E => E.k.kind === 'handoff')`, 0.5);
  await page.mouse('mouseMoved', hp.x, hp.y);
  ok(await page.wait(`CS.lanes.byKey[${JSON.stringify(hp.key)}].p.classList.contains('hover') && !document.querySelector('.ln-tip').hidden
                      && document.querySelector('.ln-tip').textContent === CS.lanes.byKey[${JSON.stringify(hp.key)}].tip.textContent
                      && document.getElementById('g').classList.contains('ln-over')`, 3000), '悬停：那条线加粗、手形、提示是它的');
  await page.mouse('mouseMoved', 5, 5);
  ok(await page.wait(`document.querySelector('.ln-tip').hidden && !document.querySelector('#g .hover')`, 3000), '移开：提示收起');
  // 叠着几条一样近：弹单子挑一条
  await page.ev(`(() => { const r = CS.graph.svg.getBoundingClientRect(); CS.lanePick.chooser([CS.lanes.edges[0], CS.lanes.links[0]], { clientX: r.left + 200, clientY: r.top + 200 }); })()`);
  ok(await page.ev(`document.querySelectorAll('.ln-pick button').length === 2`), '单子里列出两条');
  const pb = await page.rect('.ln-pick button:nth-of-type(2)');
  await page.mouse('mouseMoved', pb.x, pb.y); await page.mouse('mousePressed', pb.x, pb.y, 1); await page.mouse('mouseReleased', pb.x, pb.y);
  ok(await page.wait(`CS.lanes.sel === CS.lanes.links[0].key && !document.querySelector('.ln-pick')`, 3000), '点单子里的第二条：选中它、单子关掉');
  await page.key('Escape', 'Escape', 27);
  await page.wait(`!CS.lanes.sel`, 3000);
  const ep = await at(page, `CS.lanes.edges.find(E => E.show && E.e.a === 'fakesvc/truth.py' && E.e.b === 'fakesvc/callee.py')`, 0.5);
  await click(page, ep);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(ep.key)} && /callee/.test(document.getElementById('dtitle').textContent)
                      && document.querySelector('#g .ln-e.sel')`, 5000), '点列里的边：它选中（变色）、详情讲这条边');
  await click(page, ep);
  ok(await page.wait(`!CS.lanes.sel && !document.querySelector('#g .ln-e.sel')`, 3000), '再点一次：取消选中');

  // 列之间的连线：点粗线开详情，写两头的代码；图上两头的节点下面标出那一行
  const lp = await at(page, `CS.lanes.links.find(E => E.k.kind === 'handoff' && E.k.via === 'queue' && /consumer/.test(E.k.to.lane))`, 0.5);
  await click(page, lp);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(lp.key)} && document.getElementById('drawer').classList.contains('open')
                      && /两头的代码/.test(document.getElementById('det').textContent) && /put_job/.test(document.getElementById('det').textContent)
                      && /take_job/.test(document.getElementById('det').textContent)`, 5000), '点交接的连线：详情里是 put_job → take_job');
  ok(/queue/.test(await page.ev(`document.getElementById('dtitle').textContent`)), '详情的标题写通道');
  const codes = await page.ev(`[...document.querySelectorAll('#det .lk-code')].map(c => c.textContent)`);
  ok(JSON.stringify(codes) === JSON.stringify(['q.put(job)', 'return q.get()']), '详情里两头的那一行代码：' + JSON.stringify(codes));
  const tags = await page.ev(`[...document.querySelectorAll('#g .ln-code text')].map(g => g.textContent)`);
  ok(tags.length === 2 && /^放 \/ 发 · put_job:\d+ {2}q\.put\(job\)$/.test(tags[0]) && /^取 \/ 收 · take_job:\d+ {2}return q\.get\(\)$/.test(tags[1]),
     '图上两头的节点下面标出那一行 ' + JSON.stringify(tags));
  const putLine = +(await page.ev(`document.querySelector('#det .lk-code').dataset.l`));
  await page.ev(`document.querySelector('#det .lk-code').click()`);
  ok(await page.wait(`!document.getElementById('viewer').hidden && (document.querySelector('.vhead b') || {}).textContent === 'fakesvc/callee.py'
                      && !!document.querySelector('#vL${putLine}.focus') && document.querySelectorAll('#viewer .ln.focus').length === 1`, 5000),
     '点那一行代码：开代码窗口、只标出那一行（第 ' + putLine + ' 行）');
  await page.wait(`document.activeElement && document.activeElement.matches('#viewer .vclose')`, 3000);   // 窗口开好、焦点到了关闭按钮
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`document.getElementById('viewer').hidden`, 3000), 'Esc 关掉代码窗口');
  await page.ev(`document.querySelector('#det .lk-fn').click()`);
  ok(await page.wait(`!document.getElementById('viewer').hidden`, 5000), '点函数名：也开代码窗口');
  await page.wait(`document.activeElement && document.activeElement.matches('#viewer .vclose')`, 3000);
  await page.key('Escape', 'Escape', 27);
  await page.wait(`document.getElementById('viewer').hidden`, 3000);

  // 谁起了谁：绿色细线，起线程的那一头标出 t.start() 那一行；点图上的代码标签开代码窗口
  const sp = await at(page, `CS.lanes.links.find(E => E.k.kind === 'spawn' && /:worker$/.test(E.k.to.lane))`, 0.5);
  await click(page, sp);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(sp.key)} && /谁起了谁/.test(document.getElementById('det').textContent)`, 5000),
     '点「谁起了谁」的细线也开详情');
  const st = await page.ev(`[...document.querySelectorAll('#g .ln-code text')].map(g => g.textContent)`);
  ok(/^起 · s_threads:\d+ {2}t\.start\(\)$/.test(st[0]) && /^入口 · in_thread（入口函数）$/.test(st[1]), '起线程的那一行、被起的入口函数 ' + JSON.stringify(st));
  ok(await page.ev(`getComputedStyle(document.querySelector('#g .ln-link.spawn')).strokeDasharray !== 'none'`), '起线程的连线是虚线');
  await page.ev(`document.querySelector('#g .ln-code.a').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  ok(await page.wait(`!document.getElementById('viewer').hidden && document.querySelectorAll('#viewer .ln.focus').length === 1
                      && document.querySelector('#viewer .ln.focus').textContent.includes('t.start()')`, 5000), '点图上的代码标签：代码窗口标出 t.start() 那一行');
  await page.wait(`document.activeElement && document.activeElement.matches('#viewer .vclose')`, 3000);
  await page.key('Escape', 'Escape', 27);
  await page.wait(`document.getElementById('viewer').hidden`, 3000);
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`!CS.lanes.sel && !document.querySelector('#g .ln-code')`, 3000), 'Esc 取消选中：代码标签撤掉');

  // 起 / 收：起线程、回收线程的节点描绿 / 红、上面写「▶ 起 worker」「■ 收 worker」；列头写起 / 收的时刻，没人收的写明
  const cols = JSON.parse(await page.ev(`JSON.stringify([...document.querySelectorAll('#g .ln-col')].filter(c => c.querySelector('.ln-th'))
    .map(c => [c.querySelector('.ln-th').textContent, [...c.querySelectorAll('.ln-life')].map(x => x.textContent)]))`));
  const lf = {};
  cols.forEach(([k, v]) => { (lf[k] = lf[k] || []).push(v); });
  for (const k in lf) if (k !== 'MainThread') lf[k] = lf[k][0];
  ok(/^▶ 起 ×2 \+\d+\.\d{3} s$/.test(lf['worker ×2'][0]) && /^■ 收 ×2 \+\d+\.\d{3} s$/.test(lf['worker ×2'][1]), '列头：worker ×2 起、收的时刻 ' + JSON.stringify(lf['worker ×2']));
  ok(lf['bg-done'][1] === '■ 没收 · 跑完了' && lf['bg-stuck'][1] === '■ 没收 · 还在跑', '没人 join 的守护线程写明 ' + JSON.stringify([lf['bg-done'], lf['bg-stuck']]));
  ok(lf['MainThread'][0].length === 0 && lf['MainThread'].slice(1).some(v => /^▶ 起 \+\d/.test(v[0]) && /^■ 收 \+\d/.test(v[1])),
     '程序的主线程没有起 / 收；fork 出来的进程有（waitpid 收的）' + JSON.stringify(lf['MainThread']));
  // 节点上的标签：主线程在 truth.py 里起了 / 收了好几列（文件这一层看是同一个节点）
  const mk = await page.ev(`[...document.querySelectorAll('#g .ln-nd.pstart .ln-mark, #g .ln-nd.pend .ln-mark')].map(x => x.firstChild.textContent)`);
  const nk = await page.ev(`(() => {
    const main = CS.lanes.L.lanes[0].id, at = 'fakesvc/truth.py';
    const sp = CS.lanes.links.filter(E => E.k.kind === 'spawn' && E.k.from.lane === main && E.k.from.node === at).map(E => E.k.to.lane);
    const jn = CS.lanes.links.filter(E => E.k.kind === 'join' && E.k.to.lane === main && E.k.to.node === at).map(E => E.k.from.lane);
    return [new Set(sp).size, new Set(jn).size]; })()`);
  ok(nk[0] > 2 && nk[1] > 2 && mk.includes('▶ 起 ' + nk[0] + ' 列') && mk.includes('■ 收 ' + nk[1] + ' 列'),
     '主线程的 truth.py 上标「▶ 起 ' + nk[0] + ' 列」「■ 收 ' + nk[1] + ' 列」（几列写列数） ' + JSON.stringify(mk));
  ok(await page.ev(`document.querySelectorAll('#g .ln-link.join').length`) >= 3, '谁回收了谁：红色细线（线程的 join、子进程的 waitpid）');
  // 点「■ 收」：这里收了好几列——都高亮，详情里逐条列出 join / waitpid 的那一行；点 worker 看那一条
  await page.ev(`document.querySelector('#g .ln-mark.end').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  ok(await page.wait(`/^m:end:/.test(CS.lanes.sel || '') && document.querySelectorAll('#g .ln-link.join.sel').length >= 3
                      && /这里回收的/.test(document.getElementById('dtitle').textContent)
                      && [...document.querySelectorAll('#det .lk-code')].some(c => c.textContent === 't.join()')
                      && [...document.querySelectorAll('#det .lk-code')].some(c => c.textContent === 'os.waitpid(pid, 0)')`, 5000),
     '点「■ 收」：这里收的几条都高亮，详情里是 join / waitpid 的那几行');
  await page.ev(`[...document.querySelectorAll('#det [data-key]')].find(b => b.textContent === 'worker').click()`);
  ok(await page.wait(`/^l:/.test(CS.lanes.sel || '') && document.querySelectorAll('#g .ln-link.sel').length === 1
                      && /谁回收了谁/.test(document.getElementById('det').textContent)
                      && [...document.querySelectorAll('#g .ln-code text')].some(x => /^收 · s_threads:\\d+ {2}t\\.join\\(\\)$/.test(x.textContent))`, 5000),
     '点 worker：只选中它那一条，图上标出 t.join() 那一行');
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`!CS.lanes.sel && !document.querySelector('#g .ln-link.sel')`, 3000), 'Esc 全部取消');

  // 「这次跑了」关掉：列里的边藏起来；打开回来
  await page.click('#edgechips [data-t="hot"]');
  ok(await page.wait(`CS.lanes.edges.every(E => !E.show) && [...document.querySelectorAll('#g .ln-e')].every(p => p.style.display === 'none')`, 3000),
     '「这次跑了」关掉：列里的边藏起来');
  await page.click('#edgechips [data-t="hot"]');
  ok(await page.wait(`CS.lanes.edges.some(E => E.show)`, 3000), '再打开：回来');

  // 收起一个进程：它的几列合成一条；再点展开
  const n0 = await page.ev(`document.querySelectorAll('#g .ln-col:not(.fold)').length`);
  await page.ev(`CS.graph.showEl(document.querySelector('#g .ln-proc .ln-fold'))`); await sleep(150);   // 图宽了，先滚到看得见
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 1 && document.querySelectorAll('#g .ln-col:not(.fold)').length < ${n0}`, 3000), '收起一个进程');
  await page.ev(`CS.graph.showEl(document.querySelector('#g .ln-proc .ln-fold'))`); await sleep(150);   // 图宽了，先滚到看得见
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 0`, 3000), '再展开');

  // 切面：节点角上的 ＋（能展开的）/ −（展开出来的，收起到上一级），和模块图一样；所有列一起变，新出来的节点闪一下。
  // 在有几层目录的 cx 仓库上测（truth 只有一层）
  await page.goto(fx.base2 + '#run=' + fx.cutrun);
  ok(await waitRun(page, fx.cutrun), '叠上 cx 仓库录的 run（分列）');
  const xpOf = s => `[...document.querySelectorAll('#g .ln-nd')].filter(g => [...g.querySelectorAll('.xp text')].some(t => t.textContent === '${s}'))`;
  const c0 = JSON.parse(await page.ev(`JSON.stringify((() => { const P = CS.app.data.pkgs; return {
    plus: ${xpOf('+')}.length, wantPlus: CS.lanes.nodes.filter(x => (P[x.id] || {}).expandable).length,
    minus: ${xpOf('−')}.length, wantMinus: CS.lanes.nodes.filter(x => (P[x.id] || {}).collapsible).length }; })())`));
  ok(c0.plus === c0.wantPlus && c0.minus === c0.wantMinus && c0.minus > 0,
     '节点角上有 ＋ / −：' + JSON.stringify(c0));
  const kid = JSON.parse(await page.ev(`JSON.stringify((() => { const P = CS.app.data.pkgs;
    const x = CS.lanes.nodes.find(x => (P[x.id] || {}).collapsible); return { id: x.id, lane: x.lane, parent: P[x.id].parent }; })())`));
  const btn = async (id, lane, s) => {
    await page.ev(`(() => { const x = CS.lanes.nodes.find(x => x.id === ${JSON.stringify(id)} && x.lane === ${JSON.stringify(lane)});
      CS.graph.showEl(x.g); })()`);
    await sleep(150);
    return page.ev(`(() => { const x = CS.lanes.nodes.find(x => x.id === ${JSON.stringify(id)} && x.lane === ${JSON.stringify(lane)});
      const b = [...x.g.querySelectorAll('.xp')].find(b => b.querySelector('text').textContent === '${s}').getBoundingClientRect();
      return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`);
  };
  await click(page, await btn(kid.id, kid.lane, '−'));
  ok(await page.wait(`!CS.app.data.open.includes(${JSON.stringify(kid.parent)}) && CS.lanes.ready
                      && CS.lanes.nodes.some(x => x.id === ${JSON.stringify(kid.parent)}) && !CS.lanes.nodes.some(x => x.id === ${JSON.stringify(kid.id)})`, 15000),
     '点 −：收起到 ' + kid.parent + '，所有列里 ' + kid.id + ' 都合回去了');
  ok(await page.ev(`CS.lanes.nodes.filter(x => x.id === ${JSON.stringify(kid.parent)}).every(x => x.g.classList.contains('fresh'))`),
     '收回来的节点闪一下');
  const back = await page.ev(`(() => { const x = CS.lanes.nodes.find(x => x.id === ${JSON.stringify(kid.parent)}); return x.lane; })()`);
  await sleep(300);
  await click(page, await btn(kid.parent, back, '+'));
  ok(await page.wait(`CS.app.data.open.includes(${JSON.stringify(kid.parent)}) && CS.lanes.ready
                      && CS.lanes.nodes.some(x => x.id === ${JSON.stringify(kid.id)}) && !CS.lanes.nodes.some(x => x.id === ${JSON.stringify(kid.parent)})`, 15000),
     '点 ＋：' + kid.parent + ' 又展开了');
  ok(await page.ev(`CS.lanes.nodes.filter(x => x.id === ${JSON.stringify(kid.id)}).every(x => x.g.classList.contains('fresh'))`),
     '展开出来的节点闪一下');
  // 名字：分列里没有框，目录带 /、本层文件写成「目录/ 本层」，同名的目录和本层分得出
  const labs = JSON.parse(await page.ev(`JSON.stringify(CS.lanes.nodes.map(x => [CS.app.data.pkgs[x.id].kind, x.g.querySelector('.nl').textContent]))`));
  ok(labs.some(l => l[0] === 'dir') && labs.every(l => l[0] === 'dir' ? l[1].endsWith('/') : l[0] === 'residual' ? l[1].endsWith('/ 本层') : !l[1].endsWith('/')),
     '目录带 /、本层写「/ 本层」 ' + JSON.stringify(labs));

  // 没录时序事件的 run：一张模块图
  await page.goto(fx.base3 + '#run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上没录时序事件的 run');
  await sleep(300);
  ok(await page.ev(`!document.body.classList.contains('lanesmode') && document.querySelectorAll('#g .nd').length > 0`), '没录时序事件：一张模块图');
}
