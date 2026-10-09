// 运行叠加：跑到的边、读图须知、只看跑到的、点边看调了哪些函数、换阶段、阶段的起点标记、从运行菜单换 run
import { clickEdge, drawnNodes, hash, hotEdges, sleep, waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.an);
  ok(await waitRun(page, fx.an), '按地址叠上 run A');
  ok((await page.ev(`document.getElementById('runbtn').textContent`)).startsWith('truth'), '运行按钮写 case 名');
  const he = await hotEdges(page);
  ok(JSON.stringify(Object.keys(he).sort()) === JSON.stringify(['fakesvc/callee.py|fakesvc/other.py', 'fakesvc/execd.py|fakesvc/work.py', 'fakesvc/truth.py|fakesvc/callee.py']),
     '跑到的边正好是三条 ' + JSON.stringify(he));
  ok(await page.ev(`CS.graph.edges.filter(E => E._warm).every(E => E.p.getAttribute('class').includes('warm'))`), '跑到的边画成橙色');
  ok(await page.ev(`CS.graph.edges.filter(E => E.hits === 0 && E._show).every(E => !E.p.getAttribute('class').includes('warm'))`), '没跑到的边不是橙色');

  // 读图须知：叠着 run 时工具栏下面一行；「更多」打开帮助，里面也有；关掉记在浏览器里
  const note = await page.ev(`(n => !n.hidden && n.textContent)(document.getElementById('readnote'))`);
  ok(note && note.includes('最近的仓库内函数') && note.includes('轮询'), '图上面有读图须知：' + (note || '').slice(0, 40));
  await page.click('#readnote [data-help]');
  const lede = await page.ev(`!document.getElementById('help').hidden && document.getElementById('lede').textContent`);
  ok(lede && lede.includes('读图须知') && lede.includes('未归到命名符号的调用'), '「更多」打开帮助，说明里有读图须知和「未归到命名符号的调用」');
  await page.key('Escape', 'Escape', 27);
  await page.ev(`document.getElementById('helpX').click()`);
  await page.click('#readnote .rnx');
  ok(await page.ev(`document.getElementById('readnote').hidden`), '点 × 关掉');
  await page.goto(base + '#run=' + fx.an);
  ok(await waitRun(page, fx.an) && await page.ev(`document.getElementById('readnote').hidden`), '刷新之后还是关着');
  await page.ev(`localStorage.removeItem('codestrata.readnote')`);

  // 叠了 run 默认只看跑到的：没跑到、也不在路径上的节点藏起来；点一下回全图，再点回来
  ok(await page.ev(`document.querySelector('[data-t="onlyhot"]').getAttribute('aria-pressed')`) === 'true', '叠了 run 默认「只看跑到的」');
  ok(await page.ev(`getComputedStyle(document.getElementById('viewlbl')).display !== 'none'`), '叠了 run：工具栏上有「视图」');
  const only = await drawnNodes(page);
  ok(only.includes('fakesvc/truth.py') && only.includes('fakesvc/work.py') && !only.includes('fakesvc/race.py'),
     `只看跑到的：${only.length} 个节点（race 这类没跑到的藏起来）`);
  await page.click('[data-t="onlyhot"]');
  await sleep(500);
  const all = (await drawnNodes(page)).length;
  ok(all > only.length && (await drawnNodes(page)).includes('fakesvc/race.py'), `关掉：回到全图 ${all} 个节点`);
  await page.click('[data-t="onlyhot"]');
  await sleep(400);
  ok((await drawnNodes(page)).length === only.length, '再点一次：又只看跑到的');

  // 点一条跑到的边：详情里是调用的函数和次数
  await clickEdge(page, 'fakesvc/truth.py', 'fakesvc/callee.py');
  ok(await page.ev('CS.graph.state.selEdge') === 'fakesvc/truth.py|fakesvc/callee.py', '点边：选中它');
  ok(await page.wait(`/leaf|mid/.test(document.getElementById('det').textContent) && /\\d/.test(document.getElementById('det').textContent)`),
     '详情里列出调到的函数（callee 里的 leaf / mid）和次数');
  await page.key('Escape', 'Escape', 27);

  // 换阶段：点时间轴上的 loop
  await page.click('.tph[data-ph="loop"]');
  ok(await waitRun(page, fx.an + '@loop'), '点 loop：换成这个阶段');
  ok(/@loop(&|$)/.test(await hash(page)), '地址里记下阶段');
  const hl = await hotEdges(page);
  ok(!hl['fakesvc/execd.py|fakesvc/work.py'] && hl['fakesvc/truth.py|fakesvc/callee.py'] > 0, 'loop 阶段：exec 那条边不在（它在 forks 阶段）');
  const marks = await page.ev(`[...document.querySelectorAll('#g .pmark')].map(x => x.textContent)`);
  ok(marks.some(m => m.includes('loop') && m.includes('起点')), '图上标出 loop 阶段的起点 ' + JSON.stringify(marks));
  ok((await page.ev(`(document.querySelector('.pbound') || {}).textContent || ''`)).includes('s_loop'), '工具栏写明从 s_loop 开始');

  // 从「运行」菜单换成另一个 run（B = offline）：叠加跟着换，地址里记下它
  await page.click('#runbtn');
  ok(await page.wait(`!document.getElementById('runpop').hidden && !!document.querySelector('#runpop [data-run^="${fx.bn}"]')`), '运行菜单里有 B');
  await page.click(`#runpop [data-run^="${fx.bn}"]`);
  ok(await page.wait(`CS.app.data.hotMeta && CS.app.data.hotMeta.run_id === '${fx.bn}'`, 15000), '换成 B');
  const hb = await hotEdges(page);
  ok(hb['fakesvc/offline.py|fakesvc/work.py'] > 0 && !hb['fakesvc/truth.py|fakesvc/callee.py'], '图上换成 B 跑到的边 ' + JSON.stringify(hb));
  ok((await hash(page)).includes(fx.bn), '地址里记下 B');
  await page.click('#runbtn');
  ok(await page.wait(`!document.getElementById('runpop').hidden && !!document.querySelector('#runpop [data-run=""]')`), '再打开运行菜单');
  await page.click('#runpop [data-run=""]');
  ok(await page.wait(`!CS.graph.hot`, 15000), '选「静态图」：不叠任何 run');
  ok(await page.ev(`document.getElementById('readnote').hidden`), '静态图上没有读图须知（说的都是运行时的图）');
}
