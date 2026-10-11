// 分列里高亮的一条链（lanechain.js）：地址里带 chain=（links --follow 给的）——链上的线加粗、标「链 1」，推出来的 --link 那一跳画虚线、标「推断」，
// 别的线变淡（chainmode）；工具栏「链 N 跳 · 清掉」，点了取掉链、地址里也没了；写错的链：分列照画、说一声
import { hash, waitRun } from '../lib.mjs';

const st = page => page.ev(`JSON.stringify({mode: document.getElementById('g').classList.contains('chainmode'),
  chain: document.querySelectorAll('#g .ln-link.ln-chain').length, inferred: document.querySelectorAll('#g .ln-link.inferred').length,
  labs: [...document.querySelectorAll('#g .ln-ltxt.chain')].map(x => x.textContent),
  chip: (document.querySelector('[data-chain]') || {}).textContent || '', err: CS.chain.info && CS.chain.info.error,
  lanes: (CS.lanes.L && CS.lanes.L.lanes || []).length})`).then(JSON.parse);

/* 链的 REF（RUN@t=…/列,…）→ 页面地址：run= 和 lanes= 分开写 */
function url(base, ref, chain) {
  const i = ref.indexOf('/');
  return base + '#run=' + ref.slice(0, i) + '&lanes=' + ref.slice(i + 1) + '&chain=' + encodeURIComponent(chain);
}

export default async function (t) {
  const { page, base, fx, ok } = t;
  const run = r => r.slice(0, r.indexOf('/'));
  await page.goto(url(base, fx.chainref, fx.chain));
  ok(await waitRun(page, run(fx.chainref)), '打开链的 REF（几片 × 经过的列）');
  ok(await page.wait(`document.getElementById('g').classList.contains('chainmode')`, 15000), '只亮链：别的线淡下去');
  let s = await st(page);
  ok(s.chain >= 1 && s.inferred === 0 && s.labs.every(x => x.startsWith('链 1')) && s.chip.startsWith('链 1 跳') && !s.err,
     '链上的线加粗、标「链 1」，工具栏「链 1 跳 · 清掉」 ' + JSON.stringify(s));
  ok((await hash(page)).includes('chain='), '地址里带着链');

  await page.click('[data-chain]');
  ok(await page.wait(`!document.getElementById('g').classList.contains('chainmode') && !document.querySelector('[data-chain]')`, 15000),
     '点「清掉」：不再只亮链、小签没了');
  ok(await page.wait(`!decodeURIComponent(location.hash).includes('chain=')`, 5000), '地址里的链也没了 ' + await hash(page));

  // 加上 --link：推出来的那一跳多画一条虚线，标「推断」
  await page.goto(url(base, fx.chainref2, fx.chain2));
  ok(await waitRun(page, run(fx.chainref2)), '打开带 --link 的链');
  ok(await page.wait(`document.querySelectorAll('#g .ln-link.inferred').length > 0`, 15000), '推出来的那一跳画出来了');
  s = await st(page);
  ok(s.mode && s.inferred >= 1 && s.chip.includes('推断 1') && s.labs.some(x => x.includes('推断')),
     '虚线标「推断」，小签写「推断 1」 ' + JSON.stringify(s));

  // 写错的链：分列照画，不只亮链，说一声
  await page.goto(url(base, fx.chainref, 'serving~nosuch#1'));
  ok(await page.wait(`CS.chain.info && !!CS.chain.info.error`, 15000), '写错的链：后端说走不出来');
  s = await st(page);
  ok(!s.mode && s.lanes > 0 && s.chip.includes('走不出来'), '分列照画、不只亮链、小签写「链走不出来」 ' + JSON.stringify(s));
}
