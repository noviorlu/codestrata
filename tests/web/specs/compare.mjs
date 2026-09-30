// 对比两个 run：从工具栏选 B、三种颜色、横幅、边详情带 B 的次数、「不对比」、对比时没有「时间顺序」
import { clickEdge, hash, sleep, waitRun } from '../lib.mjs';

const side = (page, a, b) => page.ev(`(E => E ? E.p.getAttribute('class') : null)(CS.graph.edges.find(E => E.a === '${a}' && E.b === '${b}'))`);

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '打开 A');
  await page.click('#cmpbtn');
  ok(await page.wait(`!document.getElementById('cmppop').hidden && !!document.querySelector('#cmppop [data-cmp^="${fx.b}"]')`), '「对比」列表里有 B');
  await page.click(`#cmppop [data-cmp^="${fx.b}"]`);
  ok(await page.wait(`!!CS.app.data.cmp && CS.app.data.cmp.ref_b.startsWith('${fx.b}')`, 15000), '选 B：进入对比');
  ok((await hash(page)).includes('cmp=' + fx.b), '地址里记下 cmp=');
  const banner = await page.ev(`(document.querySelector('.cmpbanner') || {}).textContent || ''`);
  ok(banner.includes('A = truth') && banner.includes('B = offline'), '横幅写明 A、B 各是哪个 case');

  const onlyA = await side(page, 'fakesvc.truth', 'fakesvc.callee'), onlyB = await side(page, 'fakesvc.offline', 'fakesvc.work');
  ok(/\bwarm\b/.test(onlyA) && !/warmb/.test(onlyA), '只有 A 跑到的边是橙色 ' + onlyA);
  ok(/warmb/.test(onlyB), '只有 B 跑到的边是紫色 ' + onlyB);
  ok(!(await page.ev(`!!document.querySelector('#edgechips [data-t="timeorder"]')`)), '对比时没有「时间顺序」开关');

  await clickEdge(page, 'fakesvc.offline', 'fakesvc.work');
  ok(await page.wait(`/B/.test(document.getElementById('det').textContent)`), '只有 B 跑到的边：详情里带 B 的次数');

  await page.click('#cmpbtn');
  await page.wait(`!document.getElementById('cmppop').hidden`);
  await page.click('#cmppop [data-cmp=""]');
  ok(await page.wait(`!CS.app.data.cmp`, 15000), '「不对比」：回到只看 A');
  await sleep(200);
  ok(!(await hash(page)).includes('cmp='), '地址里去掉 cmp=');
}
