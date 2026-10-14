// 分列里高亮的一条链（lanechain.js）：地址里带 chain=（links --follow 给的）——链上的线加粗、标「链 1」，推出来的 --link 那一跳画紫色虚线、标「推断」，
// 别的线变淡（chainmode），但选中的那条不淡；工具栏「链 N 跳 · 清掉」，点了取掉链、地址里也没了；换到链不在的那一段：不淡、小签写「链不在这一段」；
// 自己换 run 时链清掉；推出来的那一跳的详情说怎么配的；写错的链：分列照画、说一声
import { hash, waitRun } from '../lib.mjs';

const st = page => page.ev(`JSON.stringify({mode: document.getElementById('g').classList.contains('chainmode'),
  chain: document.querySelectorAll('#g .ln-link.ln-chain').length, inferred: document.querySelectorAll('#g .ln-link.inferred').length,
  labs: [...document.querySelectorAll('#g .ln-ltxt.chain')].map(x => x.textContent),
  chip: (document.querySelector('[data-chain]') || {}).textContent || '', err: CS.chain.info && CS.chain.info.error,
  lanes: (CS.lanes.L && CS.lanes.L.lanes || []).length})`).then(JSON.parse);

/* 链的 REF（RUN@t=…/列,…）→ 页面地址：只要 run=（列不进地址） */
function url(base, ref, chain) {
  const i = ref.indexOf('/');
  return base + '#run=' + ref.slice(0, i) + '&chain=' + encodeURIComponent(chain);
}

export default async function (t) {
  const { page, base, fx, ok } = t;
  const run = r => r.slice(0, r.indexOf('/'));
  await page.goto(url(base, fx.chainref, fx.chain));
  ok(await waitRun(page, run(fx.chainref)), '打开链的 REF（几片 × 经过的列）');
  await page.ev(`CS.focus.showAll()`); await page.wait(`!CS.focus.lanes() && CS.lanes.ready`, 5000);   // 小程序的列默认收起大半
  ok(await page.wait(`document.getElementById('g').classList.contains('chainmode')`, 15000), '只亮链：别的线淡下去');
  let s = await st(page);
  ok(s.chain >= 1 && s.inferred === 0 && s.labs.every(x => x.startsWith('链 1')) && s.chip.startsWith('链 1 跳') && !s.err,
     '链上的线加粗、标「链 1」，工具栏「链 1 跳 · 清掉」 ' + JSON.stringify(s));
  ok((await hash(page)).includes('chain='), '地址里带着链');
  // 只亮链时选中一条不在链上的线：它不淡（原来被「只亮链」的规则压着）
  const opa = await page.ev(`(() => { const E = CS.lanes.links.find(x => !x.k.chain); if (!E) return 'none';
    CS.lanes.open(E, true); return getComputedStyle(E.p).opacity; })()`);
  ok(opa === 'none' || opa === '1', '只亮链时选中的线不淡 ' + opa);

  await page.click('[data-chain]');
  ok(await page.wait(`!document.getElementById('g').classList.contains('chainmode') && !document.querySelector('[data-chain]')`, 15000),
     '点「清掉」：不再只亮链、小签没了');
  ok(await page.wait(`!decodeURIComponent(location.hash).includes('chain=')`, 5000), '地址里的链也没了 ' + await hash(page));

  // 加上 --link：推出来的那一跳多画一条虚线，标「推断」
  await page.goto(url(base, fx.chainref2, fx.chain2));
  ok(await waitRun(page, run(fx.chainref2)), '打开带 --link 的链');
  await page.ev(`CS.focus.showAll()`); await page.wait(`!CS.focus.lanes() && CS.lanes.ready`, 5000);   // 小程序的列默认收起大半
  ok(await page.wait(`document.querySelectorAll('#g .ln-link.inferred').length > 0`, 15000), '推出来的那一跳画出来了');
  s = await st(page);
  ok(s.mode && s.inferred >= 1 && s.chip.includes('推断 1') && s.labs.some(x => x.includes('推断')),
     '虚线标「推断」，小签写「推断 1」 ' + JSON.stringify(s));
  const det = await page.ev(`(() => { const E = CS.lanes.links.find(x => x.k.inferred); CS.lanes.open(E, true);
    return document.getElementById('det').textContent; })()`);
  ok(det.includes('推出来的') && det.includes('A 边') && !det.includes('按消息内容的指纹'), '推出来的那一跳：详情说是 --link 按先后配的 ' + det.slice(0, 160));

  // 换到别的阶段：这一段里有链上的线才只亮链，没有时小签写「链不在这一段」
  await page.goto(base + '#run=' + fx.a + '@loop&chain=' + encodeURIComponent(fx.chain));   // loop 阶段只有 s_loop：没有那次队列交接
  ok(await waitRun(page, fx.a + '@loop'), '换到 loop 阶段（链还在地址里）');
  s = await st(page);
  const has = await page.ev(`CS.lanes.links.some(E => !!E.k.chain)`);
  ok(!has && !s.mode && s.chip.includes('链不在这一段'), '没有链上的线时不只亮链、小签说链不在这一段 ' + JSON.stringify([has, s]));

  // 自己换 run（不是套地址）：链是那个 run 的，清掉
  await page.ev(`CS.app.selectRun(${JSON.stringify(fx.b)}, '')`);
  ok(await page.wait(`!CS.chain.key && !decodeURIComponent(location.hash).includes('chain=')`, 15000), '换 run：链清掉 ' + await hash(page));

  // 写错的链：分列照画，不只亮链，说一声
  await page.goto(url(base, fx.chainref, 'serving~nosuch#1'));
  ok(await page.wait(`CS.chain.info && !!CS.chain.info.error`, 15000), '写错的链：后端说走不出来');
  s = await st(page);
  ok(!s.mode && s.lanes > 0 && s.chip.includes('走不出来'), '分列照画、不只亮链、小签写「链走不出来」 ' + JSON.stringify(s));
}
