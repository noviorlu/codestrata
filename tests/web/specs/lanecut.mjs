// 分列里每列各自的切面（用户 10-02：「我点击一个thread的expand collapse不应该影响另外一个thread或者是进程」）和展开的目录画框
// （「我需要类似于静态图里面的外边框include展开的所有内容」「而非现在直接换名字了」）。在有几层目录、两条线程的 cx 仓库上测：
// 主线程跑 run() 和 f00()，side 线程跑 s()；两列都调到 cx/ops/。
import { sleep, waitRun } from '../lib.mjs';

async function click(page, p) {
  await sleep(150);
  await page.mouse('mouseMoved', p.x, p.y); await page.mouse('mousePressed', p.x, p.y, 1); await page.mouse('mouseReleased', p.x, p.y);
  await sleep(300);
}

export default async function (t) {
  const { page, fx, ok } = t;
  const J = JSON.stringify;
  await page.goto(fx.base2 + '#run=' + fx.cutrun);
  ok(await waitRun(page, fx.cutrun), '叠上 cx 仓库录的 run（分列）');
  const M = await page.ev(`CS.lanes.L.lanes.find(l => l.thread === 'MainThread').id`);
  const S = await page.ev(`CS.lanes.L.lanes.find(l => l.thread === 'side').id`);
  const st = lane => page.ev(`JSON.stringify((() => { const l = CS.lanes.L.lanes.find(x => x.id === ${J(lane)});
    const ys = CS.lanes.nodes.filter(x => x.lane === l.id).map(x => [x.id, CS.lanes.pos[l.id + '|' + x.id].cy]).sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : 1));
    return { open: l.open, nodes: Object.keys(l.nodes).sort(), order: ys.map(y => y[0]) }; })())`).then(JSON.parse);
  const ready = `CS.lanes.ready && !CS.app._pending && document.getElementById('prog').textContent === ''`;
  // 屏幕上一个元素的中心（先滚到看得见）
  const at = sel => page.ev(`(() => { const e = ${sel}; CS.graph.showEl(e); const b = e.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`);
  const node = (id, lane) => `CS.lanes.nodes.find(x => x.id === ${J(id)} && x.lane === ${J(lane)}).g`;
  const plus = (id, lane) => `${node(id, lane)}.querySelector('.xp')`;
  const minus = (f, lane) => `document.querySelector('#g .ln-fh[data-frame="${f}"][data-lane="${lane}"] .xp')`;

  // 一开始：共用切面上展开着的目录在各列里画成框，框头写名字；节点只有 ＋，收起在框头的 −；名字照模块图（框里的写相对的）
  const c0 = JSON.parse(await page.ev(`JSON.stringify({
    plus: document.querySelectorAll('#g .ln-nd .xp').length,
    wantPlus: CS.lanes.nodes.filter(x => (CS.lanes.L.info[x.id] || {}).expandable).length,
    minus: document.querySelectorAll('#g .ln-fh .xp').length, frames: Object.keys(CS.lanes.fpos).length,
    names: CS.lanes.nodes.every(x => x.g.querySelector('.nl').textContent === CS.lanes.L.lanes.find(l => l.id === x.lane).names[x.id]),
    heads: [...document.querySelectorAll('#g .ln-fh')].map(h => [h.dataset.lane, h.dataset.frame, h.querySelector('.fl').textContent]) })`));
  ok(c0.plus === c0.wantPlus && c0.plus > 0 && c0.minus === c0.frames && c0.frames > 0 && c0.names, '节点只有 ＋、框头有 −、名字照模块图 ' + J(c0));
  ok(c0.heads.some(h => h[0] === M && h[1] === 'cx/big/*' && h[2] === '本层文件') && c0.heads.some(h => h[0] === S && h[1] === 'cx/big/' && h[2] === 'big/'),
     '框头：big/、本层文件 ' + J(c0.heads));
  // 框把它里面的节点框住，别的节点在框外
  const inside = await page.ev(`(() => { const L = CS.lanes, bad = [];
    for (const k of Object.keys(L.fpos)) {
      const F = L.fpos[k], lane = k.slice(0, k.lastIndexOf('|')), f = k.slice(k.lastIndexOf('|') + 1), ln = L.laneIx[lane];
      for (const x of L.nodes.filter(n => n.lane === lane)) {
        const p = L.pos[lane + '|' + x.id], inF = p.cx - p.w / 2 >= F.x && p.cx + p.w / 2 <= F.x + F.w && p.cy - p.h / 2 >= F.y && p.cy + p.h / 2 <= F.y + F.h;
        let mem = false; for (let g = (L.L.info[x.id] || {}).frame; g; g = (ln.frames[g] || {}).parent) if (g === f) mem = true;
        if (mem !== inF) bad.push([k, x.id, mem, inF]);
      }
    }
    return JSON.stringify(bad); })()`);
  ok(inside === '[]', '框里的节点在框里，别的在框外 ' + inside);

  // 在主线程那一列点 ops/ 的 ＋：只改这一列，框住展开出来的 util、kernels/，新的闪一下；side 那一列不变（节点、先后）
  const s0 = await st(S), m0 = await st(M);
  await click(page, await at(plus('cx/ops/', M)));
  ok(await page.wait(`${ready} && CS.lanes.L.lanes.find(l => l.id === ${J(M)}).open.includes('cx/ops/')`, 15000), '主线程那一列展开 ops/');
  const s1 = await st(S), m1 = await st(M);
  ok(J(s1) === J(s0), 'side 那一列不变 ' + J([s0, s1]));
  ok(m1.nodes.includes('cx/ops/util.py') && m1.nodes.includes('cx/ops/kernels/') && !m1.nodes.includes('cx/ops/')
     && J(m1.order.filter(x => m0.order.includes(x))) === J(m0.order.filter(x => m1.order.includes(x))), '主线程：ops/ 换成 util、kernels/，别的先后不变 ' + J([m0, m1]));
  ok(await page.ev(`!!CS.lanes.fpos[${J(M + '|cx/ops/')}] && document.querySelector('#g .ln-fh[data-frame="cx/ops/"][data-lane="${M}"] .fl').textContent === 'ops/'
                    && CS.lanes.nodes.filter(x => x.lane === ${J(M)} && x.id.startsWith('cx/ops/')).every(x => x.g.classList.contains('fresh'))`),
     'ops/ 画成框、框头写 ops/，展开出来的闪一下');
  ok(await page.ev(`CS.laneCut.any() && getComputedStyle(document.getElementById('resetcut')).display !== 'none'`), '有列单独展开着：「重置」出来');

  // 悬停主线程里的 util：side 那一列里装着它的 ops/ 也算它的一份，连上（用户 10-02）；悬停 side 的 ops/：主线程里展开成的框也连上
  await page.mouse('mouseMoved', ...Object.values(await at(node('cx/ops/util.py', M))));
  ok(await page.wait(`${node('cx/ops/', S)}.classList.contains('twin') && document.querySelectorAll('#g .ln-twin').length === 1`, 3000),
     '悬停主线程的 util：连上 side 的 ops/');
  await page.mouse('mouseMoved', ...Object.values(await at(node('cx/ops/', S))));
  ok(await page.wait(`document.querySelector('#g .ln-fr[data-frame="cx/ops/"][data-lane="${M}"]').classList.contains('twin')`, 3000),
     '悬停 side 的 ops/：连上主线程里它展开成的框');
  await page.mouse('mouseMoved', 5, 5);

  // 选中主线程的 util，点 ops/ 框头的 −：只收起主线程这一列，接着选装着它的 ops/（同一列）
  await click(page, await at(node('cx/ops/util.py', M)));
  ok(await page.wait(`CS.lanes.sel === ${J('n:' + M + '|cx/ops/util.py')}`, 3000), '选中主线程的 util');
  await click(page, await at(minus('cx/ops/', M)));
  ok(await page.wait(`${ready} && !CS.lanes.L.lanes.find(l => l.id === ${J(M)}).open.includes('cx/ops/')
                      && CS.lanes.sel === ${J('n:' + M + '|cx/ops/')} && document.getElementById('det').dataset.pkg === 'cx/ops/'`, 15000),
     '框头的 −：收起这一列，接着选 ops/');
  ok(J(await st(S)) === J(s0) && !(await page.ev(`CS.laneCut.any()`)), 'side 不变；和共用的一样了，不再算单独展开');

  // 详情里点「展开」：只展开选着的这一份所在的列；选中的变成那个框，详情照旧讲它、换成「收起」；再点「收起」选回它
  await page.ev(`document.querySelector('#det [data-cut="expand"]').click()`);
  ok(await page.wait(`${ready} && CS.lanes.L.lanes.find(l => l.id === ${J(M)}).open.includes('cx/ops/') && CS.lanes.sel === ${J('f:' + M + '|cx/ops/')}
                      && document.querySelector('#g .ln-fr.sel[data-frame="cx/ops/"]') && /收起/.test(document.querySelector('#det .cutrow').textContent)`, 15000),
     '详情里点展开：这一列展开，选中那个框，详情换成收起');
  ok(J(await st(S)) === J(s0), 'side 不变');
  await page.ev(`document.querySelector('#det .cutrow button').click()`);
  ok(await page.wait(`${ready} && !CS.lanes.L.lanes.find(l => l.id === ${J(M)}).open.includes('cx/ops/') && CS.lanes.sel === ${J('n:' + M + '|cx/ops/')}`, 15000),
     '再点收起：选回 ops/');
  // 点框头选中那个框：详情列出这一列里框着的节点
  await click(page, await at(plus('cx/ops/', S)));
  ok(await page.wait(`${ready} && CS.lanes.L.lanes.find(l => l.id === ${J(S)}).open.includes('cx/ops/')`, 15000), 'side 那一列展开 ops/');
  ok(J((await st(M)).open) === J(m0.open), '主线程不变');
  await click(page, await at(`document.querySelector('#g .ln-fh[data-frame="cx/ops/"][data-lane="${S}"] .fl')`));
  ok(await page.wait(`CS.lanes.sel === ${J('f:' + S + '|cx/ops/')} && document.getElementById('det').dataset.lane === ${J(S)}
                      && [...document.querySelectorAll('#det [data-node]')].map(b => b.dataset.node).join() === 'cx/ops/kernels/,cx/ops/util.py'`, 5000),
     '点框头：选中框，详情列出框着的 kernels/、util');
  await page.key('Escape', 'Escape', 27);

  // 搜一个只有 side 调到的（cx/big/sub/s.py）：只在 side 那一列里展开到它、选中
  const m2 = await st(M);
  await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
  await page.type('sub/s');
  ok(await page.wait(`!!document.querySelector('#sbar .sr') && [...document.querySelectorAll('#g .ln-nd.match')].map(g => g.dataset.lane + '|' + g.dataset.id).join() === ${J(S + '|cx/big/sub/')}`, 5000),
     '搜 sub/s：描出 side 里装着它的 sub/');
  await page.key('Enter', 'Enter', 13);
  ok(await page.wait(`${ready} && CS.lanes.sel === ${J('n:' + S + '|cx/big/sub/s.py')} && CS.lanes.L.lanes.find(l => l.id === ${J(S)}).open.includes('cx/big/sub/')`, 15000),
     '回车：只在 side 里展开到 s.py、选中它');
  ok(J(await st(M)) === J(m2), '主线程不变');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`CS.search.clear()`);
  // 搜 util：每列按自己的切面描——主线程里收着就描 ops/，side 里展开着就描 util
  await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
  await page.type('ops/util');
  ok(await page.wait(`[...document.querySelectorAll('#g .ln-nd.match')].map(g => g.dataset.lane + '|' + g.dataset.id).sort().join() === ${J([M + '|cx/ops/', S + '|cx/ops/util.py'].sort().join())}`, 5000),
     '搜 ops/util：主线程描 ops/、side 描 util');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`CS.search.clear()`);

  // 搜一个在这一列里已经展开着的目录：选中那个框（再回车还选着它），不会把它收起来；搜单根仓库的根（cx/）也不收起整列
  const m3 = await st(M);
  for (const q of ['cx.big', 'cx.big']) {
    await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
    await page.type(q);
    await page.wait(`!!document.querySelector('#sbar .sr')`, 5000);
    await page.key('Enter', 'Enter', 13);
    ok(await page.wait(`${ready} && CS.lanes.sel === ${J('f:' + M + '|cx/big/')}`, 10000), '搜 ' + q + ' 回车：选中主线程里 big/ 的框');
  }
  await page.ev(`CS.app.revealNode('cx/', 'dir')`);
  ok(await page.wait(`${ready} && (CS.lanes.sel || '').startsWith(${J('n:' + M + '|cx/')})`, 10000) && J(await st(M)) === J(m3),
     '搜根目录 cx/：选它底下的第一个节点，不收起整列');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`CS.search.clear()`);
  // 键盘上点 ＋：展开之后焦点在新框框头的 −（再按一下就收起）
  await page.ev(`(() => { const b = ${plus('cx/sansio/', M)}; CS.graph.showEl(b); b.focus(); })()`);
  await page.key('Enter', 'Enter', 13);
  ok(await page.wait(`${ready} && document.activeElement && document.activeElement.closest('.ln-fh[data-frame="cx/sansio/"][data-lane="${M}"]')`, 15000),
     '键盘点 ＋：焦点到新框框头的 −');
  await page.key('Enter', 'Enter', 13);
  ok(await page.wait(`${ready} && !CS.lanes.L.lanes.find(l => l.id === ${J(M)}).open.includes('cx/sansio/')`, 15000), '再按一下：收起');

  // 换阶段：各列单独的展开留着
  const kept = await page.ev(`JSON.stringify(CS.laneCut.cuts)`);
  await page.click('.tph[data-ph="two"]');
  ok(await waitRun(page, fx.cutrun + '@two'), '换到阶段 two');
  ok(await page.wait(`${ready} && JSON.stringify(CS.laneCut.cuts) === ${J(kept)}`, 15000), '换阶段：各列的展开留着 ' + kept);
  await page.click('.tph[data-ph=""]');
  ok(await waitRun(page, fx.cutrun), '回到整个 run');
  // 重置：所有列都回到默认
  await page.click('#resetcut');
  ok(await page.wait(`${ready} && !CS.laneCut.any() && CS.lanes.L.lanes.every(l => JSON.stringify(l.open) === JSON.stringify(CS.app.data.open))`, 15000),
     '重置：各列都回到共用的切面');
  // 换 run（这里切到静态图再回来）：各列单独的展开清掉
  await click(page, await at(plus('cx/ops/', M)));
  ok(await page.wait(`${ready} && CS.laneCut.any()`, 15000), '再在主线程展开 ops/');
  await page.ev(`CS.app.selectRun('')`);
  ok(await page.wait(`!document.body.classList.contains('lanesmode') && !CS.app._pending`, 15000), '换成静态图');
  await page.ev(`CS.app.selectRun(${J(fx.cutrun)})`);
  ok(await page.wait(`${ready} && document.body.classList.contains('lanesmode') && !CS.laneCut.any()
                      && CS.lanes.L.lanes.every(l => !l.open.includes('cx/ops/'))`, 15000), '换回来：各列单独的展开清掉了');
}
