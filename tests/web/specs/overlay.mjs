// 运行叠加：跑到的边、只看跑到的、点边看调了哪些函数、换阶段、阶段的起点标记
import { clickEdge, drawnNodes, hash, hotEdges, sleep, waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a);
  ok(await waitRun(page, fx.a), '按地址叠上 run A');
  ok((await page.ev(`document.getElementById('runbtn').textContent`)).startsWith('truth'), '运行按钮写 case 名');
  const he = await hotEdges(page);
  ok(JSON.stringify(Object.keys(he).sort()) === JSON.stringify(['fakesvc.callee|fakesvc.other', 'fakesvc.execd|fakesvc.work', 'fakesvc.truth|fakesvc.callee']),
     '跑到的边正好是三条 ' + JSON.stringify(he));
  ok(await page.ev(`CS.graph.edges.filter(E => E._warm).every(E => E.p.getAttribute('class').includes('warm'))`), '跑到的边画成橙色');
  ok(await page.ev(`CS.graph.edges.filter(E => E.hits === 0 && E._show).every(E => !E.p.getAttribute('class').includes('warm'))`), '没跑到的边不是橙色');

  // 只看跑到的：没跑到、也不在路径上的节点藏起来
  const all = (await drawnNodes(page)).length;
  await page.click('[data-t="onlyhot"]');
  await sleep(500);
  const only = await drawnNodes(page);
  ok(only.length < all && only.includes('fakesvc.truth') && only.includes('fakesvc.work') && !only.includes('fakesvc.race'),
     `只看跑到的：${all} → ${only.length} 个节点（race 这类没跑到的藏起来）`);
  await page.click('[data-t="onlyhot"]');
  await sleep(400);
  ok((await drawnNodes(page)).length === all, '再点一次：节点都回来');

  // 点一条跑到的边：详情里是调用的函数和次数
  await clickEdge(page, 'fakesvc.truth', 'fakesvc.callee');
  ok(await page.ev('CS.graph.state.selEdge') === 'fakesvc.truth|fakesvc.callee', '点边：选中它');
  ok(await page.wait(`/leaf|mid/.test(document.getElementById('det').textContent) && /\\d/.test(document.getElementById('det').textContent)`),
     '详情里列出调到的函数（callee 里的 leaf / mid）和次数');
  await page.key('Escape', 'Escape', 27);

  // 换阶段：点时间轴上的 loop
  await page.click('.tph[data-ph="loop"]');
  ok(await waitRun(page, fx.a + '@loop'), '点 loop：换成这个阶段');
  ok((await hash(page)).endsWith('@loop'), '地址里记下阶段');
  const hl = await hotEdges(page);
  ok(!hl['fakesvc.execd|fakesvc.work'] && hl['fakesvc.truth|fakesvc.callee'] > 0, 'loop 阶段：exec 那条边不在（它在 forks 阶段）');
  const marks = await page.ev(`[...document.querySelectorAll('#g .pmark')].map(x => x.textContent)`);
  ok(marks.some(m => m.includes('loop') && m.includes('起点')), '图上标出 loop 阶段的起点 ' + JSON.stringify(marks));
  ok((await page.ev(`(document.querySelector('.pbound') || {}).textContent || ''`)).includes('s_loop'), '工具栏写明从 s_loop 开始');
}
