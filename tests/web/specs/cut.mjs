// 切面：节点 id 按路径写（cx/ops/、cx/big/*、cx/app.py），图上、标题上照旧是点分的模块名；
// 展开成框、本层文件、收起框（连同底下展开的一起）、搜索栏按点分名 / 路径找到模块并展开到它
import { clickNode, drawnNodes } from '../lib.mjs';

export default async function (t) {
  const { page, fx, ok } = t;
  const clickXp = async (sel, owner) => {       // 节点左上角的 ＋ / 框头的 −：先滚进视野再点
    await page.ev(`CS.graph.showEl(document.querySelector('${owner}'))`);
    await page.click(sel);
  };
  await page.goto(fx.base2);
  ok(await page.wait(`!!(CS.app && CS.app.data && CS.graph.G)`), '打开切面用的仓库');
  await page.ev(`CS.app.setCut(['cx/'])`);                 // 从只展开根开始，不依赖默认切面
  ok(await page.wait(`JSON.stringify(CS.app.data.open) === '["cx/"]' && !!CS.graph.nodes['cx/ops/']`), '只展开根 cx/');
  let nodes = await drawnNodes(page);
  ok(['cx/app.py', 'cx/ops/', 'cx/sansio/', 'cx/big/'].every(x => nodes.includes(x)), '节点 id 是路径：文件、收起的目录 ' + JSON.stringify(nodes));
  const labels = await page.ev(`Object.fromEntries(CS.graph.G.nodes.map(n => [n.id, n.label]))`);
  ok(labels['cx/ops/'] === 'ops/' && labels['cx/app.py'] === 'app', '图上的名字照旧：ops/、app ' + JSON.stringify(labels));

  // ops/ 的 ＋：展开成框，框里是它的孩子
  await clickXp(`#g .nd[data-id="cx/ops/"] .xp`, `#g .nd[data-id="cx/ops/"]`);
  ok(await page.wait(`CS.app.data.open.indexOf('cx/ops/') >= 0 && !!CS.graph.frames['cx/ops/']`), '点 ＋：ops/ 展开成框');
  ok(await page.wait(`document.getElementById('prog').textContent === ''`, 3000), '画好了：「重新汇总…」清掉');
  nodes = await drawnNodes(page);
  ok(nodes.includes('cx/ops/util.py') && nodes.includes('cx/ops/kernels/') && !nodes.includes('cx/ops/'),
     '框里是 util 和 kernels/ ' + JSON.stringify(nodes));

  // big/ 直接放着 14 个文件又有子目录：展开后是本层文件节点 cx/big/*，再展开它摊到文件
  await clickXp(`#g .nd[data-id="cx/big/"] .xp`, `#g .nd[data-id="cx/big/"]`);
  ok(await page.wait(`!!CS.graph.nodes['cx/big/*']`), '展开 big/：出现本层文件节点 cx/big/*');
  ok(await page.ev(`CS.graph.G.nodes.find(n => n.id === 'cx/big/*').label`) === '本层文件', '框里的本层文件节点写「本层文件」');
  await clickXp(`#g .nd[data-id="cx/big/*"] .xp`, `#g .nd[data-id="cx/big/*"]`);
  ok(await page.wait(`!!CS.graph.nodes['cx/big/f00.py'] && !!CS.graph.frames['cx/big/*']`), '展开本层文件：摊开到文件，外面一个框');

  // 收起 big/ 的框：它底下展开着的（本层文件）一起收回去
  await clickXp(`#g .fh[data-frame="cx/big/"] .xp`, `#g .frame[data-frame="cx/big/"]`);
  ok(await page.wait(`!!CS.graph.nodes['cx/big/'] && CS.app.data.open.every(x => x.indexOf('cx/big/') !== 0)`),
     '收起 big/ 的框：连同本层文件一起收回');

  // 选中一个文件：标题是点分的完整名字，悬停提示是路径
  await clickNode(page, 'cx/ops/util.py');
  ok(await page.wait(`document.getElementById('dtitle').textContent === 'cx.ops.util'`), '标题写点分名 cx.ops.util');
  ok(await page.ev(`document.getElementById('dtitle').title`) === 'cx/ops/util.py', '标题的悬停提示是路径');
  await page.key('Escape', 'Escape', 27);

  // 搜索栏：点分名、路径都找得到收着的模块；回车后展开到它并选中
  for (const [q, want] of [['ops.kernels.k', 'cx/ops/kernels/k.py'], ['sansio/app', 'cx/sansio/app.py']]) {
    await page.ev(`CS.app.setCut(['cx/'])`);
    await page.wait(`JSON.stringify(CS.app.data.open) === '["cx/"]' && !!CS.graph.nodes['cx/ops/']`);
    await page.ev(`(() => { const i = document.getElementById('sq'); i.value = ''; i.focus(); })()`);
    await page.type(q);
    ok(await page.wait(`!!document.querySelector('#sbar .sr')`), `搜 ${q}：有结果`);
    await page.key('Enter', 'Enter', 13);
    ok(await page.wait(`CS.graph.state.sel === '${want}'`, 15000), `搜 ${q} 回车：展开到 ${want} 并选中它`);
    await page.key('Escape', 'Escape', 27);
  }
}
