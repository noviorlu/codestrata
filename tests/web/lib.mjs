// spec 之间共用的页面操作（都经 page：真的鼠标 / 键盘，或者读页面状态）
import { sleep } from './cdp.mjs';
export { sleep };

export const hash = page => page.ev('decodeURIComponent(location.hash)');

/* 图上一条边的中点（屏幕坐标）：先把它滚到看得见的地方。分列视图（叠着录了时序事件的 run）里取第一条 a → b 的列里的边 */
export async function edgePoint(page, a, b) {
  return page.ev(`(() => {
    const A = ${JSON.stringify(a)}, B = ${JSON.stringify(b)};
    const E = document.body.classList.contains('lanesmode')
      ? CS.lanes.edges.find(E => E.e.a === A && E.e.b === B && E.show)
      : CS.graph.edges.find(E => E.a === A && E.b === B);
    if (!E) return null;
    CS.graph.showEl(E.x);
    const L = E.x.getTotalLength(), p = E.x.getPointAtLength(L / 2), m = E.x.getScreenCTM();
    return {x: p.x * m.a + p.y * m.c + m.e, y: p.x * m.b + p.y * m.d + m.f};
  })()`);
}

export async function clickEdge(page, a, b) {
  const p = await edgePoint(page, a, b);
  if (!p) throw new Error('图上没有边 ' + a + ' → ' + b);
  await sleep(200);
  await page.mouse('mouseMoved', p.x, p.y); await page.mouse('mousePressed', p.x, p.y, 1); await page.mouse('mouseReleased', p.x, p.y);
  await sleep(300);
}

export async function clickNode(page, id) {
  await page.ev(`CS.graph.showEl(document.querySelector('#g .nd[data-id="${id}"]'))`);
  await sleep(200);
  await page.click(`#g .nd[data-id="${id}"] rect`);
  await sleep(300);
}

/* 图上画出来的节点 id */
export const drawnNodes = page => page.ev(`[...document.querySelectorAll('#g .nd')].map(g => g.dataset.id)`);

/* 叠了 run 的图上跑到的边（a|b → 次数）。分列视图里是各列里的边加起来 */
export const hotEdges = page => page.ev(`document.body.classList.contains('lanesmode')
  ? CS.lanes.edges.reduce((o, E) => { const k = E.e.a + '|' + E.e.b; o[k] = (o[k] || 0) + E.e.n; return o; }, {})
  : Object.fromEntries(CS.graph.edges.filter(E => E.hits > 0).map(E => [E.a + '|' + E.b, E.hits]))`);

/* 等到页面上的 run 引用变成 ref（地址里已经写了、图也按它重画完；分列视图要等它取完数画好） */
export const waitRun = (page, ref) => page.wait(
  `CS.app.data.hotMeta && (CS.app.data.hotMeta.run_id + (CS.app.data.hotMeta.phase ? '@' + CS.app.data.hotMeta.phase : '')) === ${JSON.stringify(ref)}
   && (!CS.app.lanesMode() || CS.lanes.ready === ${JSON.stringify(ref)})`, 15000);
