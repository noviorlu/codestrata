// 按进程 · 线程分列（lanes.js）：叠着录了时序事件的 run 就是它，没有切回一张图的开关（用户 10-01）；列按进程分组，
// 列里是这条线程调到的节点；鼠标停在节点上连上它在别的列里的副本；列里的边接点错开、点哪条开哪条；列之间的连线能点，
// 详情里是两头的函数；「这次跑了」管列里的边；进程能收起；没录时序事件的 run 照旧是一张图
import { sleep, waitRun } from '../lib.mjs';

/* 一条边 / 连线（CS.lanes 里的 E）上点得到它的一点（屏幕坐标）：先滚到看得见，从 f 处开始沿路径找最上面就是它（命中区或标签）的地方，
   都被盖住了就点它的标签 */
const at = (page, expr, f) => page.ev(`(E => {
  CS.graph.showEl(E.x);
  const L = E.x.getTotalLength(), m = E.x.getScreenCTM();
  for (const g of [${f}, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.15, 0.85]) {
    const p = E.x.getPointAtLength(L * g), x = p.x * m.a + p.y * m.c + m.e, y = p.x * m.b + p.y * m.d + m.f;
    const top = document.elementFromPoint(x, y);
    if (top === E.x || top === E.lab) return { x, y, key: E.key };
  }
  if (E.lab) {                             // 线叠在别的线下面：点它的标签（标签在节点上面、放在不挡东西的地方）
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
    const b = g.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2, id, ids[id]];
  })()`);
  await page.mouse('mouseMoved', r[0], r[1]);
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd.twin').length === ${r[3]} && document.querySelectorAll('#g .ln-twin').length === ${r[3] - 1}`, 3000),
     '悬停：' + r[2] + ' 的 ' + r[3] + ' 份都高亮、连上');
  // 点节点：选中、详情栏打开讲它
  await click(page, { x: r[0], y: r[1] });
  ok(await page.wait(`CS.lanes.sel === 'n:' + ${JSON.stringify(r[2])} && document.getElementById('drawer').classList.contains('open')
                      && document.getElementById('det').dataset.pkg === ${JSON.stringify(r[2])}`, 5000), '点节点：选中、详情栏打开讲它');

  // 列里的边：同一列里接点错开，每一条在自己路径的中点点下去，最上面的就是它（不会点到叠在一起的另一条）
  const stolen = await page.ev(`(() => {
    const out = [];
    for (const E of CS.lanes.edges) {
      if (!E.show) continue;
      CS.graph.showEl(E.x);
      const L = E.x.getTotalLength(), p = E.x.getPointAtLength(L * 0.5), m = E.x.getScreenCTM();
      const top = document.elementFromPoint(p.x * m.a + p.y * m.c + m.e, p.x * m.b + p.y * m.d + m.f);
      const T = CS.lanes.edges.concat(CS.lanes.links).find(G => G.x === top || G.lab === top);
      if (T && T !== E) out.push(E.key + ' → ' + T.key);
    }
    return out;
  })()`);
  ok(stolen.length === 0, '列里的边各点各的：' + JSON.stringify(stolen.slice(0, 4)));
  const ep = await at(page, `CS.lanes.edges.find(E => E.show && E.e.a === 'fakesvc/truth.py' && E.e.b === 'fakesvc/callee.py')`, 0.5);
  await click(page, ep);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(ep.key)} && /callee/.test(document.getElementById('dtitle').textContent)
                      && document.querySelector('#g .ln-e.sel')`, 5000), '点列里的边：它选中（变色）、详情讲这条边');
  await click(page, ep);
  ok(await page.wait(`!CS.lanes.sel && !document.querySelector('#g .ln-e.sel')`, 3000), '再点一次：取消选中');

  // 列之间的连线：点粗线开详情，写两头的函数
  const lp = await at(page, `CS.lanes.links.find(E => E.k.kind === 'handoff' && E.k.via === 'queue' && /consumer/.test(E.k.to.lane))`, 0.5);
  await click(page, lp);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(lp.key)} && document.getElementById('drawer').classList.contains('open')
                      && /两头的函数/.test(document.getElementById('det').textContent) && /put_job/.test(document.getElementById('det').textContent)
                      && /take_job/.test(document.getElementById('det').textContent)`, 5000), '点交接的连线：详情里是 put_job → take_job');
  ok(/queue/.test(await page.ev(`document.getElementById('dtitle').textContent`)), '详情的标题写通道');
  await page.ev(`document.querySelector('#det .lk-fn').click()`);
  ok(await page.wait(`!document.getElementById('viewer').hidden`, 5000), '点函数名：开代码窗口');
  await page.wait(`document.activeElement && document.activeElement.matches('#viewer .vclose')`, 3000);   // 窗口开好、焦点到了关闭按钮
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`document.getElementById('viewer').hidden`, 3000), 'Esc 关掉代码窗口');
  const sp = await at(page, `CS.lanes.links.find(E => E.k.kind === 'spawn')`, 0.5);
  await click(page, sp);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(sp.key)} && /谁起了谁/.test(document.getElementById('det').textContent)`, 5000),
     '点「谁起了谁」的细线也开详情');

  // 「这次跑了」关掉：列里的边藏起来；打开回来
  await page.click('#edgechips [data-t="hot"]');
  ok(await page.wait(`CS.lanes.edges.every(E => !E.show) && [...document.querySelectorAll('#g .ln-e')].every(p => p.style.display === 'none')`, 3000),
     '「这次跑了」关掉：列里的边藏起来');
  await page.click('#edgechips [data-t="hot"]');
  ok(await page.wait(`CS.lanes.edges.some(E => E.show)`, 3000), '再打开：回来');

  // 收起一个进程：它的几列合成一条；再点展开
  const n0 = await page.ev(`document.querySelectorAll('#g .ln-col:not(.fold)').length`);
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 1 && document.querySelectorAll('#g .ln-col:not(.fold)').length < ${n0}`, 3000), '收起一个进程');
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 0`, 3000), '再展开');

  // 没录时序事件的 run：一张模块图
  await page.goto(fx.base3 + '#run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上没录时序事件的 run');
  await sleep(300);
  ok(await page.ev(`!document.body.classList.contains('lanesmode') && document.querySelectorAll('#g .nd').length > 0`), '没录时序事件：一张模块图');
}
