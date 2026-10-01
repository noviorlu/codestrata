// 图上只有调用：边上标次数、粗细不变；全是代码里看不出的画虚线；三个图例开关；
// 边详情按「谁调了谁、写在哪一行」（构造、老 run、不叠 run）；代码窗口在代码里看不出调到谁的那一行行尾标出这次调到了谁，点了跳过去、能返回
import { clickEdge, sleep, waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '叠上 run A');
  const chips = await page.ev(`[...document.querySelectorAll('#edgechips [data-t]')].map(b => b.dataset.t)`);
  ok(chips.includes('scan') && chips.includes('hot') && !chips.includes('imp') && !chips.includes('type'),
     '图例：代码里的调用、这次跑了，没有「只 import」「仅类型」 ' + JSON.stringify(chips));
  const TC = `CS.graph.edgeInfo('fakesvc/truth.py', 'fakesvc/callee.py')`;
  const lab = await page.ev(`(E => E && E.lab && E.lab.textContent)(${TC})`);
  const n = await page.ev(`${TC}.hits`);
  ok(lab === String(n) && n > 0, `truth → callee 的边上标着次数 ${lab}（${n}）`);
  const widths = await page.ev(`[...new Set(CS.graph.edges.filter(E => E._warm && E._show && !E._mine).map(E => E.p.style.strokeWidth))]`);
  ok(widths.length === 1, '跑到的边一样粗（次数标在边上，不靠粗细） ' + JSON.stringify(widths));
  const only = await page.ev(`${TC}.only`);
  ok(only > 0 && only < n && (await page.ev(`${TC}.tip.textContent`)).includes('其中 ' + only + ' 次代码里看不出'),
     `部分代码里看不出：画实线，悬停写明其中 ${only} 次`);

  // 边详情：卡片按「谁调了谁」；代码里看不出的带标记、from 是调用写在哪一行
  await clickEdge(page, 'fakesvc/truth.py', 'fakesvc/callee.py');
  ok(await page.wait(`document.querySelectorAll('#det .call').length > 0`), '详情里有调用卡片');
  const det = await page.ev(`document.getElementById('det').textContent`);
  ok(await page.ev(`!!document.querySelector('#det .call.dyn .dtag')`) && /truth\.py:\d+/.test(det), '代码里看不出的卡片带标记，from 是 truth.py 的某一行');
  const why = await page.ev(`[...document.querySelectorAll('#det .call.dyn .via')].map(x => x.textContent).join('｜')`);
  ok(/这一行|代码里只知道名字|代码里写的是/.test(why), '说明 scan 在那一行看到的是什么：' + why.slice(0, 120));
  ok(!/只 import|import 语句|仅类型/.test(det), '没有「只 import」「import 语句」「仅类型」');
  await page.key('Escape', 'Escape', 27);

  // 代码窗口：带上 run 取文件，行尾标出这次调到了谁，点了跳过去
  // 挑一行调到别的文件的：点了要换到那个文件
  const line = await page.ev(`fetch('api/file?f=fakesvc/truth.py&run=' + encodeURIComponent(CS.ds.run)).then(r => r.json())
    .then(j => +Object.keys(j.runtime || {}).find(l => j.runtime[l][0].def && j.runtime[l][0].def.f !== 'fakesvc/truth.py'))`);
  ok(line > 0, '这个 run 里 truth.py 有代码里看不出调到谁、调到别的文件的行：第 ' + line + ' 行');
  await page.ev(`CS.viewer.open('fakesvc/truth.py', 1)`);
  await page.wait(`!!document.querySelector('#vL${line}')`);
  await page.ev(`document.getElementById('vL${line}').scrollIntoView({block: 'center'})`);
  ok(await page.wait(`!!document.querySelector('#vL${line} .rtj button')`), '那一行行尾标出这次调到了谁');
  ok(await page.ev(`!!document.querySelector('.vhint.rt')`), '窗口头上说明有几行代码里看不出调到谁');
  const target = await page.ev(`document.querySelector('#vL${line} .rtj button').dataset.rf`);
  await page.click(`#vL${line} .rtj button`);
  ok(target !== 'fakesvc/truth.py' && await page.wait(`(document.querySelector('.vhead b') || {}).textContent === ${JSON.stringify(target)}`),
     '点它跳到 ' + target);
  ok(await page.wait(`!!document.querySelector('#viewer [data-back]')`), '跳过去之后有「返回」');
  await page.click('#viewer [data-back]');
  ok(await page.wait(`(document.querySelector('.ln.focus') || {}).id === 'vL${line}'`), '「返回」回到点标记的那一行');
  await page.key('Escape', 'Escape', 27);

  // 全是代码里看不出的边：橙虚线，代码里写了调用的（scan 边）也一样；关掉「代码里看不出」就不画它，和「这次跑了」各管各的
  await page.goto(fx.base3 + '#run=' + fx.dyn);
  ok(await waitRun(page, fx.dyn), '第三个小仓库叠上它的 run');
  const d = await page.ev(`(E => E && [E.a, E.b, E.p.getAttribute('class'), E.lab && E.lab.textContent, E.scan])(CS.graph.edges.find(E => E.dashed))`);
  ok(d && d[0] === 'dyn/runner.py' && d[2].includes('dyn') && d[2].includes('warm') && d[3] === '3' && d[4] > 0,
     'runner → net 代码里写了一处调用、跑到的 3 次全是代码里看不出的：橙虚线、标着 3 ' + JSON.stringify(d));
  const rto = await page.ev(`(E => E && [E.dashed, E.scan, E.hits])(CS.graph.edgeInfo('dyn/main.py', 'dyn/models/net.py'))`);
  ok(rto && rto[0] && rto[1] === 0 && rto[2] === 1, '代码里没写的 main → net（getattr 取到的类）也是虚线 ' + JSON.stringify(rto));
  ok(await page.ev(`!!document.querySelector('#edgechips [data-t="dyn"]')`), '有虚线边时有「代码里看不出」开关');
  await page.click('#edgechips [data-t="dyn"]');
  await sleep(300);
  ok(await page.ev(`CS.graph.edges.filter(E => E.dashed).every(E => !E._dyn && (E.scan ? E._show : !E._show))`),
     '关掉它：不画虚线了，代码里写了调用的退回灰实线，没写的整条不画');
  await page.click('#edgechips [data-t="dyn"]');
  await sleep(300);
  ok(await page.ev(`CS.graph.edges.filter(E => E.dashed).every(E => E._show)`), '再打开：回来了');
  await page.click('#edgechips [data-t="hot"]');
  await sleep(300);
  ok(await page.ev(`CS.graph.edges.filter(E => E.dashed).every(E => E._show && E._dyn) && !CS.graph.edges.some(E => E._warm)`),
     '关掉「这次跑了」：橙实线退回去，虚线还在');
  await page.click('#edgechips [data-t="hot"]');
  await sleep(300);

  // 构造：代码里写的 Runner(…)，跑的是 Runner.__init__，卡片上说明
  await clickEdge(page, 'dyn/main.py', 'dyn/runner.py');
  ok(await page.wait(`document.querySelectorAll('#det .call').length > 0`), 'main → runner 的详情');
  ok((await page.ev(`document.getElementById('det').textContent`)).includes('代码里写的是构造，跑的是'), '构造的卡片写明跑的是哪个方法');
  await page.key('Escape', 'Escape', 27);

  // 老 run（没有调用行）：调用处是按名字找到的，写明
  await page.goto(fx.base3 + '#run=' + fx.dynold);
  ok(await waitRun(page, fx.dynold), '叠上老 run');
  await clickEdge(page, 'dyn/runner.py', 'dyn/models/net.py');
  ok(await page.wait(`document.getElementById('det').textContent.includes('这个 run 没记调用行')`), '老 run 的卡片写明没记调用行、调用处是猜的');
  await page.key('Escape', 'Escape', 27);

  // 不叠 run：边详情是代码里写的调用（from 写在哪一行、to 被调的定义）
  await page.goto(fx.base3);
  ok(await page.wait(`!CS.app.data.hot && CS.graph.edges.length > 0`, 15000), '静态图');
  await clickEdge(page, 'dyn/runner.py', 'dyn/models/net.py');
  ok(await page.wait(`document.querySelectorAll('#det .call.ref').length === 1`), '一张代码里写的调用卡片');
  const st = await page.ev(`document.getElementById('det').textContent`);
  ok(st.includes('没有叠 run') && /runner\.py:\d+/.test(st) && st.includes('helper'), 'runner.py 的哪一行调了 helper');
}
