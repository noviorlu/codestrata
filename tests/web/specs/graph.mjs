// 静态图：节点和接口一致、分层、点节点看详情、Esc 取消、缩放、搜索栏
import { clickNode, drawnNodes, sleep } from '../lib.mjs';

export default async function (t) {
  const { page, base, ok } = t;
  await page.goto(base);
  const api = await page.ev(`fetch('api/graph').then(r => r.json()).then(g => g.graph.nodes.map(n => n.id))`);
  const drawn = await drawnNodes(page);
  ok(api.length >= 5 && JSON.stringify([...drawn].sort()) === JSON.stringify([...api].sort()), `图上的节点和 /api/graph 一致（${drawn.length} 个）`);
  ok(await page.ev(`document.getElementById('runbtn').textContent`) === '静态图', '没选 run：运行按钮写「静态图」');
  ok(!(await page.ev('!!CS.graph.hot')), '没有叠加');
  // 分层：被调的在下面（truth 调 callee，callee 调 other）
  const y = await page.ev(`Object.fromEntries([...document.querySelectorAll('#g .nd')].map(g => [g.dataset.id, g.getBoundingClientRect().top]))`);
  ok(y['fakesvc.truth'] < y['fakesvc.callee'] && y['fakesvc.callee'] < y['fakesvc.other'], '分层：依赖方在上、被依赖的在下');
  ok((await page.ev(`[...document.querySelectorAll('#g text')].map(x => x.textContent).join(' ')`)).includes('第'), '泳道有层号标签');

  // 点节点：选中，详情里是它的文件和函数
  await clickNode(page, 'fakesvc.callee');
  ok(await page.ev(`CS.graph.state.sel`) === 'fakesvc.callee', '点节点：选中它');
  ok(await page.wait(`document.getElementById('det').textContent.includes('callee')`), '详情里是这个模块');
  ok(await page.ev(`document.getElementById('dtitle').textContent`) === 'fakesvc.callee', '详情栏标题写这个节点');
  await page.key('Escape', 'Escape', 27);
  await sleep(200);
  ok(!(await page.ev('CS.graph.state.sel')), 'Esc：取消选中');

  // 缩放按钮
  const z0 = await page.ev('CS.graph.zoom');
  await page.click('.gctl [data-z="in"]');
  await sleep(200);
  ok(await page.ev('CS.graph.zoom') > z0, '放大');

  // 搜索栏：/ 打开，按名字找函数
  await page.key('/', 'Slash', 191, 0, '/');
  ok(await page.wait(`document.activeElement && document.activeElement.id === 'sq' || (document.activeElement && document.activeElement.closest && !!document.activeElement.closest('#sbar'))`), '/ 跳到搜索框');
  await page.type('deep');
  ok(await page.wait(`document.getElementById('sbar').textContent.includes('deep')`), '搜 deep：结果里有 other.deep');
}
