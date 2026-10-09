// 按进程 · 线程分列（lanes.js）：叠着录了时序事件的 run 就是它，没有切回一张图的开关（用户 10-01）；列按进程分组，
// 列里是这条线程调到的节点；鼠标停在节点上连上它在别的列里的副本；每条线各有各的接点和轨道，点哪条按离鼠标最近的算，
// 悬停的提示和会选中的是同一条，叠着几条时弹单子挑；列之间的连线能点，
// 详情里是两头的代码，选中时两头的节点下面标出那一行；起线程 / 回收线程的节点描绿 / 红、列头写起 / 收；「这次跑了」管列里的边；
// 进程能收起；没录时序事件的 run 照旧是一张图（每列各自的切面在 lanecut.mjs）
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
  // 详情里的调用 / 被调用 / 连线只列这一份的（用户 10-01）：就是图上高亮的那些
  const dk = JSON.parse(await page.ev(`JSON.stringify({
    got: [...new Set([...document.querySelectorAll('#nbslot [data-key]')].map(b => b.dataset.key))].sort(),
    hi: CS.lanes.edges.concat(CS.lanes.links).filter(E => E.p.classList.contains('hi')).map(E => E.key).sort() })`));
  ok(dk.got.length > 0 && JSON.stringify(dk.got) === JSON.stringify(dk.hi), '详情里列的就是高亮的 ' + dk.got.length + ' 条 ' + JSON.stringify(dk));
  // 主线程里的 truth.py：「调用 →」里有 callee.py，次数是这一列里那条边的；点连线那一行选中那条连线，点名字选中这一列里的 callee.py
  const real = async sel => { await page.ev(`document.querySelector(${JSON.stringify(sel)}).scrollIntoView({ block: 'center' })`); await sleep(150); await page.click(sel); await sleep(200); };
  const tl = await page.ev(`CS.lanes.nodes.find(x => x.id === 'fakesvc/truth.py' && /:MainThread$/.test(x.lane)).lane`);
  await page.key('Escape', 'Escape', 27);
  await click(page, JSON.parse(await page.ev(`JSON.stringify((() => { const x = CS.lanes.nodes.find(x => x.id === 'fakesvc/truth.py' && x.lane === ${JSON.stringify(tl)});
    CS.graph.showEl(x.g); const b = x.g.querySelector('rect').getBoundingClientRect(); return { x: b.left + 12, y: b.top + b.height / 2 }; })())`)));
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify('n:' + tl + '|fakesvc/truth.py')} && !!document.querySelector('#nbslot .dep')`, 5000), '点主线程里的 truth.py');
  const cr = JSON.parse(await page.ev(`JSON.stringify((() => {
    const kv = [...document.querySelectorAll('#nbslot .kv')].find(k => k.firstElementChild.textContent === '调用 →');
    const c = kv && kv.querySelector('[data-node="fakesvc/callee.py"]'), E = CS.lanes.byKey[${JSON.stringify('e:' + tl + '|fakesvc/truth.py|fakesvc/callee.py')}];
    return { lane: c && c.dataset.lane, txt: c && c.nextElementSibling.textContent, n: E && E.e.n }; })())`));
  ok(cr.lane === tl && cr.n > 0 && cr.txt.startsWith(cr.n + ' 次'), '「调用 →」里有 callee.py，次数是这一列里的 ' + JSON.stringify(cr));
  const lk = await page.ev(`(document.querySelector('#nbslot [data-key^="l:"]') || {}).dataset.key`);
  ok(!!lk, '主线程的 truth.py 有连线那一行');
  await real(`#nbslot [data-key="${lk}"]`);
  ok(await page.wait(`CS.lanes.sel === '${lk}' && document.querySelectorAll('#g .ln-link.sel').length === 1
                      && document.getElementById('dtitle').textContent.includes(CS.lanes.fmt.VIA[CS.lanes.byKey['${lk}'].k.via] || CS.lanes.byKey['${lk}'].k.via)`, 5000),
     '点连线那一行：选中那条连线，详情讲它');
  ok(await page.ev(`[...document.querySelectorAll('#det [data-node]')].every(b => CS.lanes.pos[b.dataset.lane + '|' + b.dataset.node])`),
     '连线详情里能点的节点名都画着');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`CS.lanes.pickNode('fakesvc/truth.py', ${JSON.stringify(tl)})`);
  await real(`#nbslot [data-node="fakesvc/callee.py"]`);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify('n:' + tl + '|fakesvc/callee.py')}
                      && [...document.querySelectorAll('#g .ln-nd.sel')].map(g => g.dataset.lane + '|' + g.dataset.id).join() === ${JSON.stringify(tl + '|fakesvc/callee.py')}
                      && document.getElementById('det').dataset.pkg === 'fakesvc/callee.py'`, 5000), '点名字：选中这一列里的 callee.py');
  // 整个详情只算这一份（用户 10-01）：顶上写明是哪一列；次数、文件树里的次数是这一列的（callee.py 好几条线程都调，整个阶段的更多）
  ok(await page.wait(`CS.panel._copy && CS.panel._copy.hot && !!document.querySelector('#tree .tn.file')`, 8000), '这一份的次数取回来了');
  const cp = JSON.parse(await page.ev(`JSON.stringify((() => {
    const n = CS.lanes.laneIx[${JSON.stringify(tl)}].nodes['fakesvc/callee.py'].n, row = document.querySelector('#tree .tn.file[data-file="fakesvc/callee.py"] > .tr .rt');
    return { n, hint: (document.querySelector('#det .copyhint') || {}).textContent || '', label: CS.lanes.laneLabel(${JSON.stringify(tl)}),
             rtc: document.querySelector('#det .rtc').textContent, tree: row ? +row.textContent : null, all: CS.app.data.hot.files['fakesvc/callee.py'] };
  })())`));
  ok(cp.n > 0 && cp.hint.includes(cp.label) && cp.rtc.includes('这一份 被调 ' + cp.n + ' 次') && cp.tree === cp.n && cp.all > cp.n,
     '详情只算这一份：顶上写明哪一列，次数和文件树里都是这一列的 ' + cp.n + '（整个阶段 ' + cp.all + '）' + JSON.stringify(cp));
  // 列里的边：详情也只算这一列里的调用，次数和图上那条边一样
  const ek = 'e:' + tl + '|fakesvc/truth.py|fakesvc/callee.py';
  await page.ev(`CS.lanes.open(CS.lanes.byKey[${JSON.stringify(ek)}])`);
  ok(await page.wait(`document.querySelector('#det .copyhint') && /trace \\d+ 次/.test(document.querySelector('#det .sub').textContent)`, 8000), '点列里的边');
  const ec = JSON.parse(await page.ev(`JSON.stringify({ n: CS.lanes.byKey[${JSON.stringify(ek)}].e.n, sub: document.querySelector('#det .sub').textContent,
    hint: document.querySelector('#det .copyhint').textContent, lane: document.getElementById('det').dataset.lane })`));
  ok(ec.sub.includes('trace ' + ec.n + ' 次') && ec.lane === tl && ec.hint.includes('这一列'), '列里的边：只算这一列里的调用 ' + JSON.stringify(ec));
  // 分列时帮助讲分列、工具栏有连线的图例
  ok(await page.ev(`(() => { const v = el => !!el && getComputedStyle(el).display !== 'none';
    return v(document.querySelector('#lede .lanesonly')) && !v(document.querySelector('#lede .graphonly')) && v(document.getElementById('lnlegend'))
      && document.getElementById('lnlegend').querySelectorAll('line.ln-link').length === 4; })()`), '分列时帮助讲分列、工具栏有四种连线的图例');
  await page.key('Escape', 'Escape', 27);

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
  // 边的详情里点一头的名字：选中这一列里的那一份，边不再选中；再点那条边是选中它（不是取消）
  const el0 = await page.ev(`CS.lanes.byKey[${JSON.stringify(ep.key)}].lane.id`);
  await real(`#det [data-go="fakesvc/callee.py"]`);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify('n:' + el0 + '|fakesvc/callee.py')} && !document.querySelector('#g .ln-e.sel')
                      && [...document.querySelectorAll('#g .ln-nd.sel')].map(g => g.dataset.lane + '|' + g.dataset.id).join() === ${JSON.stringify(el0 + '|fakesvc/callee.py')}
                      && document.getElementById('det').dataset.pkg === 'fakesvc/callee.py'`, 5000), '边的详情里点 callee.py：选中这一列里的那一份');
  await click(page, await at(page, `CS.lanes.byKey[${JSON.stringify(ep.key)}]`, 0.5));
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(ep.key)} && !!document.querySelector('#g .ln-e.sel')`, 3000), '再点那条边：选中它');
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
  // 选着主线程里的 truth.py，收起一个子进程：还选着它、详情还讲它；收起主线程所在的进程：取消选中、详情清掉
  const mainLane = await page.ev(`CS.lanes.nodes.find(x => x.id === 'fakesvc/truth.py' && /:MainThread$/.test(x.lane)).lane`);
  const kidPid = await page.ev(`CS.lanes.L.lanes.find(l => l.pid !== CS.lanes.L.lanes[0].pid && l.thread === 'MainThread').pid`);
  const mainPid = await page.ev(`CS.lanes.L.lanes[0].pid`);
  await page.ev(`CS.lanes.pickNode('fakesvc/truth.py', ${JSON.stringify(mainLane)})`);
  await page.ev(`document.getElementById('tree').dataset.mark = 'kept'`);    // 详情里的文件树不该重画（筛选、打开的源码都在里面）
  await page.ev(`CS.lanes.fold(${kidPid}, true)`);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify('n:' + mainLane + '|fakesvc/truth.py')} && document.getElementById('det').dataset.pkg === 'fakesvc/truth.py'
                      && document.querySelectorAll('#g .ln-nd.sel').length === 1 && document.getElementById('tree').dataset.mark === 'kept'`, 3000),
     '收起别的进程：还选着这一份，文件树不重画');
  // 连到收起的进程的那条连线：那一头的节点不能点，写明是进程收起了
  const fk = await page.ev(`CS.lanes.links.find(E => E.k.kind === 'spawn' && E.k.via === 'fork' && CS.lanes.L.lanes.some(l => l.id === E.k.to.lane && l.pid === ${kidPid})).key`);
  await page.ev(`CS.lanes.open(CS.lanes.byKey[${JSON.stringify(fk)}])`);
  const fd = JSON.parse(await page.ev(`JSON.stringify({ txt: document.getElementById('det').textContent,
    nodes: [...document.querySelectorAll('#det [data-node]')].map(b => b.dataset.lane) })`));
  ok(/这个进程收起了，展开后能点/.test(fd.txt) && !fd.nodes.some(l => l.startsWith(kidPid + ':')),
     '连线一头在收起的进程里：不能点，写明进程收起了 ' + JSON.stringify(fd.nodes));
  await page.ev(`CS.lanes.fold(${kidPid}, false)`);
  await page.ev(`CS.lanes.pickNode('fakesvc/truth.py', ${JSON.stringify(mainLane)})`);
  await page.ev(`CS.lanes.fold(${mainPid}, true)`);
  ok(await page.wait(`!CS.lanes.sel && !document.getElementById('det').dataset.pkg && !document.querySelector('#g .ln-nd.sel')`, 3000),
     '收起选着的那一份所在的进程：取消选中、详情清掉');
  await page.ev(`CS.lanes.fold(${mainPid}, false)`);

  // 搜索：命中的节点每一份都描出来；回车选中它的第一份、开详情，不说「没跑到」、不碰「只看跑到的」
  await page.key('Escape', 'Escape', 27);
  const tgt = 'fakesvc/callee.py', hot0 = await page.ev(`CS.graph.state.onlyHot`);
  const copies = await page.ev(`CS.lanes.nodes.filter(x => x.id === '${tgt}').length`);
  await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
  await page.type('callee');
  ok(await page.wait(`!!document.querySelector('#sbar .sr') && document.querySelectorAll('#g .ln-nd.match').length > 0`, 5000), '搜 callee：有结果，图上有描出来的');
  const m = JSON.parse(await page.ev(`JSON.stringify([...document.querySelectorAll('#g .ln-nd.match')].map(g => g.dataset.id))`));
  ok(copies > 0 && m.length === copies && m.every(id => id === tgt), `${tgt} 的 ${copies} 份都描出来、别的不描 ` + JSON.stringify(m));
  await page.key('Enter', 'Enter', 13);
  const first = await page.ev(`CS.lanes.nodes.find(x => x.id === '${tgt}').lane`);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify('n:' + first + '|' + tgt)} && document.getElementById('drawer').classList.contains('open')
                      && document.getElementById('det').dataset.pkg === '${tgt}'`, 5000), '回车：选中第一份、详情讲它');
  ok(await page.ev(`!/没跑到|没调到/.test((document.getElementById('gtoast') || {}).textContent || '') && CS.graph.state.onlyHot === ${hot0}`),
     '不说没跑到，「只看跑到的」不动');
  await page.key('Escape', 'Escape', 27);
  // 搜函数：选中它所在的节点，详情里展开到它（不开代码窗口）。先取消选中，详情里没有 callee.py 的文件树
  await page.ev(`CS.graph.clear()`);
  ok(await page.wait(`!CS.lanes.sel && document.getElementById('det').dataset.pkg !== '${tgt}'`, 3000), '先取消选中');
  await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
  await page.type('child_work');
  ok(await page.wait(`!!document.querySelector('#sbar .sr')`, 5000), '搜 child_work：有结果');
  await page.key('Enter', 'Enter', 13);
  ok(await page.wait(`(CS.lanes.sel || '').endsWith('|${tgt}') && !!document.querySelector('#det .tr.hit [data-tsym$="child_work"]')`, 8000),
     '搜函数：选中 callee.py，详情里展开到 child_work、标出来');
  await sleep(500);
  ok(await page.ev(`document.getElementById('viewer').hidden`), '代码窗口没开');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`CS.search.clear()`);
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd.match').length === 0`, 3000), '清掉搜索：描的撤掉');

  // 时间段：起 / 收只算这一段里跑过的线程；起在段前的连线淡一点、标「段前」，时间顺序不给它排名次（用户 10-01）
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '回到整个 run A');
  const req = JSON.parse(await page.ev(`JSON.stringify((() => { const E = CS.lanes.links.find(E => E.k.kind === 'spawn' && /:req$/.test(E.k.to.lane));
    return { last: E.k.last, end: CS.app.data.hotMeta.end_us }; })())`));
  const win = (req.last + 1) + '-' + req.end;
  await page.goto(base + '#run=' + fx.a + '@t=' + win);
  ok(await waitRun(page, fx.a + '@t=' + win), '时间段从起 req-3 之后 1 µs 开始 ' + win);
  const rq = JSON.parse(await page.ev(`JSON.stringify((() => { const E = CS.lanes.links.find(E => E.k.kind === 'spawn' && /:req$/.test(E.k.to.lane));
    const col = [...document.querySelectorAll('#g .ln-col')].find(c => (c.querySelector('.ln-th') || {}).textContent === 'req');
    return { out: E && E.k.out, n: E && E.k.n, cls: E && E.p.classList.contains('out'), tip: E && E.tip.textContent,
             life: col ? [...col.querySelectorAll('.ln-life')].map(x => x.textContent) : null }; })())`));
  ok(rq.out === 'before' && rq.n === 1 && rq.cls && /开始之前/.test(rq.tip) && /第一次在 −[\d.]+ s（段前）/.test(rq.tip)
     && rq.life && /−[\d.]+ s（段前）/.test(rq.life[0]),
     '这一段里只有 req-3 在跑：起它的连线 ×1、标段前、画淡，时刻写成 −x s（段前） ' + JSON.stringify(rq));
  // consumer 刚开始取的那 2 µs：起它在段前、收它在段后，列头两个时刻各自标出来；起它、收它的主线程这一段里没跑，照样写是它
  const cf = await page.ev(`CS.lanes.L.lanes.find(l => l.thread === 'consumer').first`);
  const cw = (cf - 1) + '-' + (cf + 1);
  await page.goto(base + '#run=' + fx.a + '@t=' + cw);
  ok(await waitRun(page, fx.a + '@t=' + cw), '时间段：consumer 开始取的那一刻 ' + cw);
  const cl = JSON.parse(await page.ev(`JSON.stringify((() => {
    const col = [...document.querySelectorAll('#g .ln-col')].find(c => (c.querySelector('.ln-th') || {}).textContent === 'consumer');
    return { life: [...col.querySelectorAll('.ln-life')].map(x => x.textContent), tip: col.querySelector('title').textContent,
             main: CS.lanes.L.lanes.some(l => l.thread === 'MainThread' && l.pid === CS.lanes.L.lanes.find(x => x.thread === 'consumer').pid) }; })())`));
  ok(/^▶ 起 −[\d.]+ s（段前）$/.test(cl.life[0]) && /^■ 收 \+[\d.]+ s（段后）$/.test(cl.life[1]) && /由 MainThread/.test(cl.tip)
     && (cl.main || /MainThread（这一段里没跑）/.test(cl.tip)), '起在段前、收在段后，各自标出来 ' + JSON.stringify(cl));

  // 一段里一个调用都没有（run 结束很久之后的 1 µs；时间从 run 开始算）：不留一张白图，说清楚为什么空、怎么办；「叠加 run …」清掉
  const empty = '100000000000-100000000001';
  await page.goto(base + '#run=' + fx.a + '@t=' + empty);
  ok(await waitRun(page, fx.a + '@t=' + empty), '时间段 ' + empty + '（run 结束之后）');
  ok(await page.wait(`CS.lanes.ready && document.querySelectorAll('#g .ln-nd').length === 0
                      && /没调到仓库里的代码/.test((document.querySelector('#g .ln-empty') || {}).textContent || '')
                      && document.getElementById('prog').textContent === ''`, 15000), '空的一段：图上写着这一段里没调到仓库里的代码');

  // 切面（每列各自的、展开的目录画框）在 lanecut.mjs 里测

  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '回到 run A');
  // 取数慢的时候：进度一直在，收起进程不清掉它；Esc 照样取消选中（画好之后不再选回来）
  await page.ev(`(() => { const orig = CS.ds.lanes; window.__lanes = orig;
    CS.ds.lanes = function (o) { const p = orig.call(CS.ds, o); return new Promise(r => setTimeout(() => r(p), 1200)); }; })()`);
  await page.ev(`CS.lanes.pickNode('fakesvc/truth.py', CS.lanes.nodes.find(x => x.id === 'fakesvc/truth.py').lane)`);
  await page.ev(`CS.app.selectRun(${JSON.stringify(fx.a)}, 'loop')`);
  ok(await page.wait(`!CS.app._pending && /叠加/.test(document.getElementById('prog').textContent)`, 5000), '换阶段：取数的时候写着叠加…');
  await page.ev(`CS.lanes.fold(CS.lanes.L.lanes[CS.lanes.L.lanes.length - 1].pid, true)`);
  ok(await page.ev(`/叠加/.test(document.getElementById('prog').textContent)`), '取数的时候收起一个进程：进度还在');
  await page.ev(`document.body.focus()`);
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`!CS.lanes.sel`, 2000), '取数的时候 Esc：取消选中');
  ok(await page.wait(`CS.lanes.ready && document.getElementById('prog').textContent === ''`, 10000) && await page.ev(`!CS.lanes.sel`),
     '画好了：进度清掉，没有再选回来');
  // 取数失败：写明失败，旧图的模型丢掉（详情、搜索不会去选看不见的东西）
  await page.ev(`CS.lanes.pickNode('fakesvc/truth.py', CS.lanes.nodes.find(x => x.id === 'fakesvc/truth.py').lane)`);
  await page.ev(`CS.ds.lanes = function () { return Promise.reject(new Error('测试里故意的')); }`);
  await page.ev(`CS.app.selectRun(${JSON.stringify(fx.a)})`);
  ok(await page.wait(`/读取失败/.test((document.querySelector('#g .ln-err') || {}).textContent || '') && !CS.lanes.nodes.length && !CS.lanes.sel
                      && !document.getElementById('det').dataset.pkg`, 10000), '取数失败：写明失败，旧图的模型和选中都丢掉');
  await page.ev(`CS.ds.lanes = window.__lanes`);

  // 分列还在取数时换成静态图：分列取回来也不画到模块图上
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '回到 run A');
  await page.ev(`(() => { const orig = CS.ds.lanes; window.__lanes = orig;
    CS.ds.lanes = function (o) { const p = orig.call(CS.ds, o); return new Promise(r => setTimeout(() => r(p), 800)); }; })()`);
  await page.ev(`CS.app.selectRun(${JSON.stringify(fx.a)}, 'loop').then(() => CS.app.selectRun(''))`);
  await sleep(1800);
  ok(await page.ev(`!document.body.classList.contains('lanesmode') && CS.graph.G.nodes.length > 0 && !!document.querySelector('#g .nd:not(.ln-nd)')
                    && !document.querySelector('#g .ln-nd')`), '换成静态图：晚回来的分列不画');
  await page.ev(`CS.ds.lanes = window.__lanes`);

  // 没录时序事件的 run：一张模块图
  await page.goto(fx.base3 + '#run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上没录时序事件的 run');
  await sleep(300);
  ok(await page.ev(`!document.body.classList.contains('lanesmode') && document.querySelectorAll('#g .nd').length > 0`), '没录时序事件：一张模块图');
}
