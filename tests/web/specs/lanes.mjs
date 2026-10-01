// 按进程 · 线程分列（lanes.js）：叠着录了时序事件的 run 默认分列；列按进程分组，列里是这条线程调到的节点，
// 列之间有「谁起了谁」「谁交给谁」的连线；鼠标停在节点上连上它在别的列里的副本；进程能收起；开关切回模块图；
// 链接里带 view=graph 就是模块图；没录时序事件的 run 没有这个开关
import { sleep, waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '叠上 run A（录了时序事件）');
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd').length > 0`, 15000), '默认按线程分列');
  ok(await page.ev(`document.querySelector('[data-t="lanes"]').getAttribute('aria-pressed') === 'true'
                    && document.body.classList.contains('lanesmode')`), '「按线程分列」开着');
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
    g.scrollIntoView({ block: 'center', inline: 'center' });
    const b = g.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2, id, ids[id]];
  })()`);
  await page.mouse('mouseMoved', r[0], r[1]);
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd.twin').length === ${r[3]} && document.querySelectorAll('#g .ln-twin').length === ${r[3] - 1}`, 3000),
     '悬停：' + r[2] + ' 的 ' + r[3] + ' 份都高亮、连上');
  // 点节点：详情栏开它
  await page.click(`#g .ln-nd[data-id="${r[2]}"]`);
  ok(await page.wait(`document.getElementById('dtitle').textContent.length > 0 && !document.getElementById('dtitle').textContent.startsWith('详情')`, 5000), '点节点开详情');
  // 收起一个进程：它的几列合成一条；再点展开
  const n0 = await page.ev(`document.querySelectorAll('#g .ln-col:not(.fold)').length`);
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 1 && document.querySelectorAll('#g .ln-col:not(.fold)').length < ${n0}`, 3000), '收起一个进程');
  await page.click('#g .ln-proc .ln-fold');
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 0`, 3000), '再展开');
  // 开关关掉：回到模块图；再打开
  await page.click('[data-t="lanes"]');
  ok(await page.wait(`!document.body.classList.contains('lanesmode') && document.querySelectorAll('#g .nd').length > 0 && !document.querySelector('#g .ln-col')`, 8000), '关掉：回到模块图');
  await page.click('[data-t="lanes"]');
  ok(await page.wait(`document.querySelectorAll('#g .ln-nd').length > 0`, 8000), '再打开：又分列');
  // 链接里带 view=graph：模块图
  await page.goto(base + '#view=graph&run=' + fx.a);
  ok(await waitRun(page, fx.a), '叠上 run A');
  await sleep(500);
  ok(await page.ev(`!document.body.classList.contains('lanesmode') && document.querySelector('[data-t="lanes"]').getAttribute('aria-pressed') === 'false'`), 'view=graph：模块图');
  // 没录时序事件的 run：没有这个开关，是模块图
  await page.goto(fx.base3 + '#run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上没录时序事件的 run');
  await sleep(500);
  ok(await page.ev(`document.querySelector('[data-t="lanes"]').hidden && !document.body.classList.contains('lanesmode')`), '没录时序事件：没有分列开关');
}
