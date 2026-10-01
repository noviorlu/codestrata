// 请求路径：叠着录了时序事件的 run 时有「请求路径」按钮；详情栏里一个线程一节，一行一个函数（缩进是调用的层次）；
// ▾ 收起下面几层；点函数名看定义、点「← 文件:行」看调用写在哪；没录时序事件的 run 点开说明为什么看不了
import { sleep, waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#view=graph&run=' + fx.a);
  ok(await waitRun(page, fx.a), '叠上 run A（录了时序事件）');
  ok(await page.ev(`!document.getElementById('pathbtn').hidden`), '有「请求路径」按钮');
  await page.click('#pathbtn');
  ok(await page.wait(`document.querySelectorAll('#det .prow').length > 0`, 15000), '详情栏里列出请求路径');
  const secs = await page.ev(`[...document.querySelectorAll('#det .pth > summary')].map(s => s.textContent)`);
  ok(secs.length >= 2 && secs.some(s => s.includes('MainThread')) && secs.some(s => s.includes('worker')),
     '按进程、线程分节（主线程、worker 线程）' + JSON.stringify(secs.slice(0, 4)));
  ok((await page.ev(`document.getElementById('dtitle').textContent`)).startsWith('请求路径'), '详情栏的标题是「请求路径」');
  // 收起：▾ 下面比它深的行藏起来，再点回来
  const r = await page.ev(`(() => {
    const b = document.querySelector('#det .pth[open] button.pt');
    const row = b.parentNode, d = +row.dataset.d;
    let n = 0; for (let x = row.nextElementSibling; x && +x.dataset.d > d; x = x.nextElementSibling) n++;
    b.click();
    let hid = 0; for (let x = row.nextElementSibling; x && +x.dataset.d > d; x = x.nextElementSibling) if (x.hidden) hid++;
    b.click();
    let back = 0; for (let x = row.nextElementSibling; x && +x.dataset.d > d; x = x.nextElementSibling) if (!x.hidden) back++;
    return [n, hid, back];
  })()`);
  ok(r[0] > 0 && r[1] === r[0] && r[2] === r[0], '▾ 收起下面 ' + r[0] + ' 行，再点展开回来');
  // 点函数名开定义，点「← 文件:行」开调用那一行
  const fn = await page.ev(`(b => [b.dataset.f, +b.dataset.l])(document.querySelector('#det .pth[open] .pfrom').closest('.prow').querySelector('.pfn'))`);
  await page.ev(`document.querySelector('#det .pth[open] .pfrom').closest('.prow').querySelector('.pfn').click()`);
  ok(await page.wait(`(document.querySelector('.vhead b') || {}).textContent === ${JSON.stringify(fn[0])} && !!document.querySelector('#vL${fn[1]}')`),
     '点函数名：打开它的定义 ' + fn.join(':'));
  await page.key('Escape', 'Escape', 27);
  const from = await page.ev(`(b => [b.dataset.f, +b.dataset.l])(document.querySelector('#det .pth[open] .pfrom'))`);
  await page.ev(`document.querySelector('#det .pth[open] .pfrom').click()`);
  ok(await page.wait(`(document.querySelector('.vhead b') || {}).textContent === ${JSON.stringify(from[0])} && !!document.querySelector('#vL${from[1]}.focus, #vL${from[1]}')`),
     '点「← 文件:行」：打开调用写在的那一行 ' + from.join(':'));
  await page.key('Escape', 'Escape', 27);

  // 边详情可以按第一次调用的先后排
  await page.goto(base + '#view=graph&run=' + fx.a);
  ok(await waitRun(page, fx.a), '回到 run A');
  const ds = await page.ev(`CS.ds.edge('fakesvc/truth.py', 'fakesvc/callee.py').then(E => [E.has_first, E.calls.filter(c => c.first != null).length, E.calls.length])`);
  ok(ds[0] === true && ds[1] > 1, '边详情带每个函数对第一次调用的时刻 ' + JSON.stringify(ds));
  await page.ev(`CS.app.drawer(true); CS.graph.pickEdge('fakesvc/truth.py', 'fakesvc/callee.py')`);
  ok(await page.wait(`!!document.querySelector('#det [data-sort="t"]')`), '有「按先后」');
  await page.click('#det [data-sort="t"]');
  ok(await page.wait(`document.querySelector('#det [data-sort="t"]').getAttribute('aria-pressed') === 'true'`), '按先后排了');
  const order = await page.ev(`CS.ds.edge('fakesvc/truth.py', 'fakesvc/callee.py').then(E => {
    const want = E.calls.slice().sort((p, q) => (p.first == null) - (q.first == null) || (p.first || 0) - (q.first || 0) || q.n - p.n).map(c => c.callee.split('#')[1].split('.').pop());
    const got = [...document.querySelectorAll('#det .call:not(.ref) .ch b')].map(b => b.textContent);
    return JSON.stringify(got) === JSON.stringify(want.slice(0, got.length));
  })`);
  ok(order, '卡片按第一次调用的先后');

  // 没录时序事件的 run：按钮照样在，点开说明为什么看不了
  await page.goto(fx.base3 + '#view=graph&run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上没录时序事件的 run');
  await sleep(300);
  ok(await page.ev(`!document.getElementById('pathbtn').hidden`), '照样有「请求路径」按钮');
  await page.click('#pathbtn');
  ok(await page.wait(`/没录时序事件/.test(document.getElementById('det').textContent)`, 5000), '点开说明没录时序事件');
}
