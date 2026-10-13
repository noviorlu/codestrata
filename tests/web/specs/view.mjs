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
  ok(await page.wait(`!CS.focus.sels.length && !document.querySelector('#g .ln-col.fold:not(.part)') && !CS.view.applying`, 5000), '后退一次：回到没写 lanes= 的视图');
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
  ok(await page.wait(`document.querySelectorAll('#g .nd.mk').length >= 1`, 3000), '标记的文件所在的节点描了边');
  const ml = await (await fetch(base + 'api/marklanes?run=' + encodeURIComponent(fx.a) + '&mark=fakesvc/callee.py')).json();
  const ran = Object.keys(ml.lanes['fakesvc/callee.py'] || {});
  ok(ran.length && await page.ev(`CS.lanes.nodes.filter(x => x.g.classList.contains('mk')).every(x => ${JSON.stringify(ran)}.includes(x.lane))`),
     '只描在它这段时间里跑过的列里（' + ran.length + ' 列）');
  await page.goto(base + '#' + h);
  ok(await page.wait(`CS.lanes.ready && !CS.view.applying && document.querySelectorAll('#g .ln-col.fold:not(.part)').length === 1`, 15000), '刷新：收起的进程还收着');
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

  // 开着「只看几列」、收起了一个进程时，从「运行」里换 run（下拉里点另一个走的就是 selectRun）：图不空，收起按别名沿用，地址里不写 pid
  await page.goto(base + '#run=' + fx.a);
  await page.wait(`CS.lanes.ready && !CS.view.applying`, 15000);
  const pa = await page.ev(`[...new Set(CS.lanes.L.lanes.map(l => CS.lanes.procAlias(l.pid)))]`);
  await page.ev(`location.hash = 'run=${fx.a}&lanes=' + encodeURIComponent(${JSON.stringify(main)}) + '&fold=' + encodeURIComponent(${JSON.stringify(pa[pa.length - 1])}) + '&order=1'`);
  ok(await page.wait(`CS.focus.lanes() && CS.lanes.foldedAliases().length === 1 && !CS.view.applying`, 5000), '只看一列、收起一个进程');
  await page.ev(`CS.app.selectRun(${JSON.stringify(fx.b)}, '')`);
  ok(await waitRun(page, fx.b) && await page.wait(`CS.lanes.ready && !CS.view.applying && CS.lanes.nodes.length > 0`, 15000),
     '换 run 之后图不空 ' + await page.ev(`JSON.stringify([CS.lanes.nodes.length, CS.lanes.L && CS.lanes.L.lanes.length, CS.lanes.ready, CS.focus.sels, !!CS.focus.lanes(), CS.lanes.foldedAliases(), CS.app.lanesMode(), document.querySelectorAll('#g .ln-col').length, CS.view.applying])`));
  await sleep(400);
  ok(!/fold=\d/.test(await hashNow(page)), '地址里收起的进程写别名、不写 pid：' + await hashNow(page));
  ok(await page.ev(`document.querySelectorAll('#g .tord .tn').length === CS.lanes.order.n`), '号牌一个不缺（和后端的编号一样多）');

  // case 名写的地址：新开页面时别的键照样套上，run 换成完整 id
  await page.goto(base + '#run=truth@loop&order=1');
  ok(await page.wait(`CS.lanes.ready && !CS.view.applying && CS.graph.state.timeOrder`, 15000), 'case 名的地址：时间顺序照样开着');
  await sleep(300);
  const hc = await hashNow(page);
  ok(hc.startsWith('run=' + fx.a + '@loop') && /order=1/.test(hc), '地址里 run 换成完整 id、别的键还在：' + hc);

  // 没写 lanes=：转一手的列（线程池 req、只在交接两头出现的 stdlib-put）默认收进「其他 N 列」，小签「默认只看」；进程头写它在干什么；
  // 窄列悬停一列一列写为什么收；点窄列只展开这个进程；点「全部显示」写 lanes=*（不写就又是默认），小签留着「全部 N 列 · 回到默认」
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '整个 run');
  ok(await page.wait(`CS.lanes.ready && !CS.view.applying && !!CS.lanes.L.default_lanes`, 15000), '后端给了默认看的列');
  const d = await page.ev(`JSON.stringify({chip: (document.querySelector('#edgechips [data-focus]') || {}).textContent || '',
    hidden: CS.lanes.L.lanes.filter(l => CS.focus.hidden(l.id)).map(l => CS.lanes.L.aliases[l.id]),
    info: [...document.querySelectorAll('#g .ln-pinfo')].map(x => x.textContent)})`).then(JSON.parse);
  ok(d.chip.startsWith('默认只看') && d.hidden.includes('truth-1/req') && !d.hidden.includes('truth-1/MainThread') && d.info.length > 0,
     '默认收起转一手的列、进程头有那一句 ' + JSON.stringify(d));
  const tip = await page.ev(`(document.querySelector('#g .ln-col.part title') || {}).textContent || ''`);
  ok(tip.startsWith('默认收起') && tip.includes('——') && tip.includes('点一下展开'), '默认收起的窄列悬停写每列为什么收 ' + JSON.stringify(tip));
  // 窄列底上压着线的地方：真鼠标点下去选的是线，不展开（窄列的点击不能吞掉线）
  const near = await page.ev(`(() => {
    for (const c of document.querySelectorAll('#g .ln-col.part .ln-band')) {
      const r = c.getBoundingClientRect();
      for (let y = r.top + 60; y < Math.min(r.bottom, innerHeight) - 4; y += 3)
        for (let x = r.left + 4; x < r.right - 4; x += 3) {
          const h = CS.lanes.hitAt(x, y), t = document.elementFromPoint(x, y);
          if (h.length && h[0].d > 2 && h[0].d < 6 && t && t.closest('.ln-col.part') && !t.closest('.ln-th')) return { x, y, key: h[0].E.key };
        }
    }
    return null; })()`);
  ok(!!near, '找到了窄列底上压着线的点（这个 fixture 上有）');
  if (near) {
    await page.mouse('mouseMoved', near.x, near.y); await sleep(80);
    await page.mouse('mousePressed', near.x, near.y, 1); await page.mouse('mouseReleased', near.x, near.y);
    ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(near.key)} && !CS.focus.sels.length`, 5000),
       '窄列底上压着线的地方点下去选中那条线、不展开 ' + JSON.stringify([near, await page.ev(`CS.lanes.sel`), await page.ev(`CS.focus.sels`)]));
    await page.key('Escape', 'Escape', 27);
  }
  // 选中一个节点，再真鼠标点窄列的列头：只展开这个进程收起的列，选中还在、地址里还有 sel=
  const nAll = await page.ev(`CS.lanes.L.lanes.length`), nDef = await page.ev(`Object.keys(CS.focus.lanes()).length`);
  const pick = await page.ev(`(() => { const x = CS.lanes.nodes.find(n => !CS.focus.hidden(n.lane)); CS.lanes.pickNode(x.id, x.lane); return CS.lanes.sel; })()`);
  const want = await page.ev(`(() => { const c = document.querySelector('#g .ln-col.part');
    const ids = CS.lanes.L.lanes.filter(l => CS.focus.hidden(l.id)); const pid = ids.length ? ids[0].pid : null;
    return ids.filter(l => l.pid === pid).map(l => l.id); })()`);
  // 列头挪到看得见的地方；右上角的搜索栏挡着就先收起来（真鼠标点的是最上面那个元素）
  const reach = () => page.ev(`(() => { const h = document.querySelector('#g .ln-col.part .ln-th');
    h.scrollIntoView({ block: 'nearest', inline: 'center' });
    const r = h.getBoundingClientRect(), t = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
    return !!(t && t.closest('.ln-col.part')); })()`);
  if (!await reach()) { await page.click('#sbx'); await sleep(200); }
  ok(await reach(), '窄列的列头点得到（没被挡着）');
  await page.click('#g .ln-col.part .ln-th');
  ok(await page.wait(`!CS.view.applying && CS.focus.sels.length > 0 && CS.focus.lanes() && /lanes=/.test(location.hash)`, 5000)
     && await page.ev(`${JSON.stringify(want)}.every(id => !CS.focus.hidden(id)) && Object.keys(CS.focus.lanes()).length === ${nDef} + ${want.length}`)
     && await page.ev(`Object.keys(CS.focus.lanes()).length`) <= nAll,
     '点窄列的列头：只放出这个进程收起的列，地址里写 lanes= ' + await hashNow(page));
  ok(await page.wait(`CS.lanes.sel === ${JSON.stringify(pick)} && location.hash.includes('sel=')`, 5000), '点窄列之后选中还在、地址里有 sel= ' + await hashNow(page));
  ok((await page.ev(`(document.querySelector('#edgechips [data-focus]') || {}).textContent || ''`)).includes('全部显示'), '小签变成「只看 n / N 列 · 全部显示」');
  await page.click('#edgechips [data-focus]');
  ok(await page.wait(`!CS.focus.lanes() && decodeURIComponent(location.hash).includes('lanes=*')`, 5000), '点「全部显示」：全部列，地址里写 lanes=* ' + await hashNow(page));
  ok(await page.wait(`((document.querySelector('#edgechips [data-focus="default"]') || {}).textContent || '').includes('回到默认')`, 5000),
     '小签留着：「全部 N 列 · 回到默认」');
  await page.click('#edgechips [data-focus]');
  ok(await page.wait(`!CS.view.applying && !CS.focus.sels.length && !!CS.focus.lanes() && !/lanes=/.test(location.hash)`, 5000)
     && await page.ev(`CS.lanes.sel === ${JSON.stringify(pick)}`)
     && (await page.ev(`(document.querySelector('#edgechips [data-focus]') || {}).textContent || ''`)).startsWith('默认只看'),
     '点「回到默认」：又是默认收起、地址里没有 lanes= ' + await hashNow(page));
}
