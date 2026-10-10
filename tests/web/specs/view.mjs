// 视图描述（view.js）：地址栏 # 后面写全页面在看什么——粘进同一个标签页就换过去（不用刷新），后退回到上一个，刷新不丢；
// 只看几列（没选的收成一窄列「其他 N 列」，连线照接）、收起、时间顺序、标记、选中都在地址里；阶段写错退回默认的并提示
import { sleep, waitRun } from '../lib.mjs';

const view = page => page.ev(`CS.view.format(CS.view.current())`);
const hashNow = page => page.ev(`location.hash.replace(/^#/, '')`);

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a + '@loop');
  ok(await waitRun(page, fx.a + '@loop'), '打开 A@loop（分列）');
  await page.wait(`CS.lanes.ready && !CS.view.applying`, 15000);
  const procs = await page.ev(`[...new Set(CS.lanes.L.lanes.map(l => CS.lanes.procAlias(l.pid)))]`);
  const main = await page.ev(`CS.lanes.L.aliases[CS.lanes.L.lanes.find(l => l.thread === 'MainThread').id]`);
  ok(main && main.endsWith('/MainThread'), '列有稳定写法 ' + main);
  await sleep(300);
  ok(await hashNow(page) === await view(page), '地址就是页面此刻的视图描述（规范写法）');

  // 把一个只看一列的地址粘进同一个标签页：不刷新就换过去
  const nav0 = await page.ev(`performance.getEntriesByType('navigation').length`);
  await page.ev(`location.hash = 'run=${fx.a}@loop&lanes=' + encodeURIComponent(${JSON.stringify(main)})`);
  ok(await page.wait(`CS.focus.lanes() && Object.keys(CS.focus.lanes()).length === 1 && !CS.view.applying
                      && document.querySelectorAll('#g .ln-col.fold').length >= 1`, 5000),
     '粘进只看一列的地址：只画这一列，别的收成窄列');
  ok(await page.ev(`[...document.querySelectorAll('#g .ln-col.fold .ln-th')].some(x => /^其他 \\d+ 列$/.test(x.textContent))`),
     '没选的列写「其他 N 列」');
  ok(await page.ev(`!!document.querySelector('#edgechips [data-focus]')`) &&
     (await page.ev(`document.querySelector('#edgechips [data-focus]').textContent`)).includes('全部显示'), '工具栏有「只看 1 / N 列 · 全部显示」');
  ok(await page.ev(`performance.getEntriesByType('navigation').length`) === nav0, '没有重新加载页面');
  ok(await page.ev(`CS.lanes.links.length > 0`), '连线照接（接到窄列上）');

  // 后退：回到上一个视图（全部列）
  await page.ev(`history.back()`);
  ok(await page.wait(`!CS.focus.lanes() && !document.querySelector('#g .ln-col.fold') && !CS.view.applying`, 5000), '后退一次：回到全部列');
  ok(await page.wait(`CS.lanes.ready && CS.lanes.nodes.length > 0`, 5000), '后退之后图画好了 ' + await page.ev(`JSON.stringify([CS.lanes.nodes.length, CS.lanes.ready, location.hash, CS.lanes.L && CS.lanes.L.lanes.length])`));

  // 收起一个进程、开时间顺序、标记一个文件、选中一个节点 → 地址里都有；刷新之后还在（整个 run：有好几个进程）
  await page.ev(`location.hash = 'run=${fx.a}'`);
  ok(await waitRun(page, fx.a) && await page.wait(`CS.lanes.ready && !CS.view.applying && new Set(CS.lanes.L.lanes.map(l => l.pid)).size > 1`, 15000),
     '粘进整个 run 的地址：换过去');
  await page.ev(`[...document.querySelectorAll('#g .ln-proc .ln-fold')].pop().dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  await page.click('#edgechips [data-t="timeorder"]');
  await page.ev(`CS.mark.set(['fakesvc/callee.py']); CS.app.edgeChips(); CS.view.changed()`);
  const nd = await page.ev(`(() => { const x = CS.lanes.nodes[0]; CS.lanes.pickNode(x.id, x.lane); return x.id; })()`);
  await sleep(400);
  const h = await hashNow(page);
  ok(/fold=/.test(h) && /order=1/.test(h) && /mark=fakesvc\/callee\.py/.test(h) && /sel=n:/.test(h), '地址里有收起、时间顺序、标记、选中：' + h);
  ok(await page.ev(`document.querySelectorAll('#g .nd.mk').length`) >= 1, '标记的文件所在的节点描了边');
  await page.goto(base + '#' + h);
  ok(await page.wait(`CS.lanes.ready && !CS.view.applying && document.querySelectorAll('#g .ln-col.fold').length === 1`, 15000), '刷新：收起的进程还收着');
  ok(await page.wait(`CS.graph.state.timeOrder && document.querySelectorAll('#g .tord .tn').length > 0`, 5000), '刷新：时间顺序还开着');
  ok(await page.ev(`CS.mark.items.join() === 'fakesvc/callee.py' && document.querySelectorAll('#g .nd.mk').length >= 1`), '刷新：标记还在');
  ok(await page.wait(`(CS.lanes.sel || '').indexOf('n:') === 0 && CS.lanes.sel.endsWith('|' + ${JSON.stringify(nd)})`, 5000), '刷新：选中还在');
  await sleep(300);
  ok(await hashNow(page) === h, '刷新后地址一字不差');
  await page.click('#edgechips [data-mark]');
  ok(await page.wait(`!CS.mark.items.length && !document.querySelector('#g .nd.mk') && !/mark=/.test(location.hash)`, 3000), '「标记 N 个 · 清掉」：清掉、地址里也去掉');

  // 地址里阶段写错：退回默认的阶段、提示，不再整页加载失败
  await page.goto(base + '#run=' + fx.a + '@nosuchphase');
  ok(await page.wait(`CS.lanes.ready && document.getElementById('h1').textContent !== '加载失败'`, 15000), '阶段写错：页面照样画出来');
  ok(await page.wait(`/没有阶段 nosuchphase/.test((document.querySelector('.vtoast') || {}).textContent || '')`, 5000), '提示阶段写错了');
  ok(!/nosuchphase/.test(await hashNow(page)), '地址改成了真的在看的');
}
