// 时间顺序：跑到的边按第一次被调用的先后编号、上色，反复调用的带 ↻；换阶段重排；关掉就撤色
import { sleep, waitRun } from '../lib.mjs';

const ranked = page => page.ev(`CS.graph.edges.filter(E => E._t).sort((x, y) => x._t.k - y._t.k).map(E => E.a + '|' + E.b)`);

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '打开 A（整个 run）');
  const chip = '#edgechips [data-t="timeorder"]';
  ok(await page.ev(`document.querySelector('${chip}').getAttribute('aria-pressed')`) === 'false', '默认关着');
  await page.click(chip);
  ok(await page.wait(`CS.graph.edges.filter(E => E._tc).length === 3`, 15000), '开：三条跑到的边都上了色');
  const order = await ranked(page);
  ok(JSON.stringify(order) === JSON.stringify(['fakesvc/truth.py|fakesvc/callee.py', 'fakesvc/callee.py|fakesvc/other.py', 'fakesvc/execd.py|fakesvc/work.py']),
     '按第一次被调用排：truth→callee、callee→other、最后是 exec 出来的进程 ' + JSON.stringify(order));
  const badges = await page.ev(`[...document.querySelectorAll('#g .tord .tn')].map(g => g.textContent)`);
  ok(badges.length === 3 && badges.some(b => b.includes('↻')), '边上有序号，反复调用的 truth→callee 带 ↻ ' + JSON.stringify(badges));
  ok(await page.ev(`new Set(CS.graph.edges.filter(E => E._tc).map(E => E._tc)).size`) === 3, '三种颜色（早 → 晚）');
  ok((await page.ev(`(document.querySelector('.tmleg') || {}).textContent || ''`)).includes('早'), '有图例');

  // 换阶段：按 loop 的时间窗重排（exec 那条不在）
  await page.click('.tph[data-ph="loop"]');
  ok(await waitRun(page, fx.a + '@loop'), '换到 loop');
  ok(await page.wait(`CS.graph.edges.filter(E => E._tc).length === 2`, 15000), 'loop 里只有两条边上色');

  // 关掉
  await page.click(chip);
  await sleep(300);
  ok(await page.ev(`CS.graph.edges.filter(E => E._tc).length === 0 && !document.querySelector('#g .tord .tn')`), '关：颜色和序号都撤掉');
}
