// 时间顺序（分列视图里）：列里的边和交接连线放在一起，跨线程按第一次发生的先后编号、上色，反复的带 ↻；
// 序号牌点了开它那一条；换阶段重排；关掉就撤色
import { sleep, waitRun } from '../lib.mjs';

const ranked = page => page.ev(`CS.lanes.edges.concat(CS.lanes.links).filter(E => E._t).sort((x, y) => x._t.k - y._t.k)
  .map(E => ({ key: E.key, first: E.first, kind: E.kind, via: E.k ? E.k.via : null }))`);

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '打开 A（整个 run，按线程分列）');
  const chip = '#edgechips [data-t="timeorder"]';
  ok(await page.ev(`!!document.querySelector('${chip}') && document.querySelector('${chip}').getAttribute('aria-pressed')`) === 'false',
     '分列里有「时间顺序」，默认关着');
  ok(await page.ev(`document.querySelector('${chip} linearGradient').getAttribute('gradientUnits')`) === 'userSpaceOnUse',
     '开关上的渐变线按用户坐标铺（按包围盒铺的话，水平线高 0，画不出来）');
  await page.click(chip);
  ok(await page.wait(`CS.lanes.edges.some(E => E._tc)`, 15000), '开：上了色');
  const r = await ranked(page);
  const n = await page.ev(`CS.lanes.edges.filter(E => E.show && E.first != null).length
    + CS.lanes.links.filter(E => E.k.kind === 'handoff' && E.first != null).length`);
  ok(r.length === n && n > 3, '列里的边和交接连线都排上了名次：' + r.length + ' / ' + n);
  ok(r.every((x, i) => i === 0 || r[i - 1].first <= x.first), '按第一次发生的先后排（跨线程）');
  ok(r.some(x => x.kind === 'link' && x.via === 'queue'), '线程之间的交接（queue）也排在里面');
  ok(await page.ev(`CS.lanes.links.filter(E => E.k.kind === 'spawn').every(E => !E._t)`), '「谁起了谁」不排名次');
  const badges = await page.ev(`[...document.querySelectorAll('#g .tord .tn')].map(g => g.textContent)`);
  ok(badges.length === n && new Set(badges.map(b => parseInt(b, 10))).size === n, '每一条都有序号牌，1…N 各一个');
  ok(badges.some(b => b.includes('↻')), '一直在反复的带 ↻ ' + JSON.stringify(badges.slice(0, 8)));
  ok(+(await page.ev(`document.querySelector('${chip} .n').textContent`)) === n, '开关上的数 = 排上名次的条数');
  ok((await page.ev(`(document.querySelector('.tmleg') || {}).textContent || ''`)).includes('早'), '有图例');
  ok(await page.ev(`new Set(CS.lanes.edges.concat(CS.lanes.links).filter(E => E._tc).map(E => E._tc)).size`) > 2, '颜色按名次从早到晚');

  // 点一个序号牌：选中它那一条、开详情
  const k0 = await page.ev(`document.querySelector('#g .tord .tn').dataset.key`);
  await page.ev(`document.querySelector('#g .tord .tn').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(k0)} && document.getElementById('drawer').classList.contains('open')`, 3000),
     '点序号牌：选中它那一条、详情栏打开');
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`!CS.lanes.sel`, 3000), 'Esc 取消选中');
  const chipN = () => page.ev(`+document.querySelector('${chip} .n').textContent`);
  ok(await chipN() === n, '取消选中之后开关上的数不变：' + n);
  // 选中列里的一条边，详情里点一头的名字：选中那个节点，开关上的数不变
  const ek = await page.ev(`CS.lanes.edges.find(E => E.show).key`);
  await page.ev(`CS.lanes.open(CS.lanes.byKey[${JSON.stringify(ek)}])`);
  ok(await page.wait(`!!document.querySelector('#det [data-go]')`, 5000), '选中一条边');
  await page.ev(`document.querySelector('#det [data-go]').click()`);
  ok(await page.wait(`(CS.lanes.sel || '').indexOf('n:') === 0`, 3000) && await chipN() === n, '详情里点节点名：选中它，开关上的数还是 ' + n);
  await page.key('Escape', 'Escape', 27);
  // 换主题：颜色按新主题重算，开关上的数不变
  const c0 = await page.ev(`CS.lanes.edges.find(E => E._tc).p.style.stroke`);
  await page.ev(`document.documentElement.dataset.theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'`);   // 换成和现在相反的
  const changed = await page.wait(`CS.lanes.edges.find(E => E._tc).p.style.stroke !== ${JSON.stringify(c0)}`, 3000);
  ok(changed && await chipN() === n,
     '换主题：时间顺序的颜色跟着变，开关上的数还是 ' + n + ' ' + JSON.stringify([c0, await page.ev(`CS.lanes.edges.find(E => E._tc).p.style.stroke`),
       await page.ev(`document.documentElement.dataset.theme`), await page.ev(`matchMedia('(prefers-color-scheme: dark)').matches`), await chipN()]));
  await page.ev(`delete document.documentElement.dataset.theme`);
  // 收起一个进程：开关上的数 = 剩下的序号牌
  await page.ev(`document.querySelector('#g .ln-proc .ln-fold').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  ok(await page.wait(`+document.querySelector('${chip} .n').textContent === document.querySelectorAll('#g .tord .tn').length
                      && document.querySelectorAll('#g .ln-col.fold').length === 1`, 3000),
     '收起一个进程：开关上的数跟着序号牌变 ' + await chipN());
  await page.ev(`document.querySelector('#g .ln-proc .ln-fold').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  ok(await page.wait(`document.querySelectorAll('#g .ln-col.fold').length === 0 && +document.querySelector('${chip} .n').textContent === ${n}`, 3000), '再展开：回到 ' + n);

  // 换阶段：按 loop 的时间窗重排
  await page.click('.tph[data-ph="loop"]');
  ok(await waitRun(page, fx.a + '@loop'), '换到 loop');
  ok(await page.wait(`CS.lanes.edges.some(E => E._tc)`, 15000), 'loop 里照样上色');
  const r2 = await ranked(page);
  ok(r2.length > 0 && r2.length < r.length, 'loop 里排上名次的少一些：' + r2.length + ' < ' + r.length);

  // 关掉
  await page.click(chip);
  await sleep(300);
  ok(await page.ev(`!CS.lanes.edges.concat(CS.lanes.links).some(E => E._tc) && !document.querySelector('#g .tord .tn')`),
     '关：颜色和序号都撤掉');
}
