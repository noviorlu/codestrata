// agent 推视图（viewsync.js，serve 的 viewhub.py）：推过来直接换——先出「agent 接手」的过渡、再出横幅，进历史（后退就是撤销）；
// 用户之后自己改过就不让撤；用户按着鼠标时等他松手再换；关了跟随出提示条、点了才换；后台标签页回来时只换最后一条；
// 等用户点一下（view wait）拿到选中的稳定写法
import { sleep, waitRun } from '../lib.mjs';

const H = { 'X-Codestrata': '1', 'Content-Type': 'application/json' };
let TAB = null;                                               // 推给这个 spec 自己的标签页（前面的 spec 留下的标签页 30 s 后才算不在）
const push = (base, view, note, timeout = 6) =>
  fetch(base + 'api/view', { method: 'POST', headers: H, body: JSON.stringify({ view, note, timeout, tab: TAB }) }).then(r => r.json());
const back = base => fetch(base + 'api/view/back', { method: 'POST', headers: H, body: JSON.stringify({ timeout: 4, tab: TAB }) }).then(r => r.json());
const tabs = base => fetch(base + 'api/view', { headers: { 'X-Codestrata': '1' } }).then(r => r.json());
async function lastIs(base, tab, state, ms = 4000) {           // 页面换完还要把「agent 接手」的过渡放完才回话
  for (const t0 = Date.now(); Date.now() - t0 < ms; await sleep(100)) {
    const x = (await tabs(base)).tabs.find(x => x.tab === tab);
    if (x && x.last && x.last.state === state) return true;
  }
  return false;
}

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a + '@loop');
  ok(await waitRun(page, fx.a + '@loop'), '打开 A@loop（分列）');
  await page.wait(`CS.lanes.ready && !CS.view.applying`, 15000);
  const tab = TAB = await page.ev(`CS.viewsync.tab`);
  let seen = false;
  for (let i = 0; i < 40 && !seen; i++) { seen = (await tabs(base)).tabs.some(x => x.tab === tab); if (!seen) await sleep(100); }
  ok(seen, '页面来问了：serve 认得这个标签页');
  ok(await page.ev(`CS.viewsync.follow`), '「跟随 agent」默认开着');
  await page.ev(`window.__veil = false; window.__rep = [];
    new MutationObserver(() => { if (document.querySelector('#agveil.on')) window.__veil = true; })
      .observe(document.body, { subtree: true, attributes: true, childList: true });
    const r0 = CS.viewsync.reply; CS.viewsync.reply = function (v, s, e) { window.__rep.push([v, s]); return r0.call(this, v, s, e); };`);

  // 推一个收起了一个进程的视图：直接换，先出过渡再出横幅，进历史，不刷新
  const proc = await page.ev(`CS.lanes.procAlias(CS.lanes.L.lanes[0].pid)`);
  const one = `run=${fx.a}@loop&fold=${encodeURIComponent(proc)}`;
  const nav0 = await page.ev(`performance.getEntriesByType('navigation').length`);
  let r = await push(base, one, '收起一个进程');
  ok(r.state === 'applied', 'agent 推过来：换好了（applied） ' + JSON.stringify(r).slice(0, 160));
  ok(await page.ev(`window.__veil`), '换之前图上出了「agent 接手」的过渡');
  ok(await page.ev(`CS.lanes.foldedAliases().length === 1`), '换到了收起一个进程');
  await lastIs(base, tab, 'applied');
  ok(await page.wait(`!!document.querySelector('#agbar.done:not([hidden])') && document.querySelector('#agbar').textContent.includes('收起一个进程')`, 3000),
     '横幅：agent 换了视图 + 说明');
  ok(await page.ev(`!!(history.state && history.state.agent)`), 'agent 推的这一步进了历史（pushState）');
  ok(await page.ev(`performance.getEntriesByType('navigation').length`) === nav0, '没有重新加载页面');
  const st = (await tabs(base)).tabs.find(x => x.tab === tab);
  ok(st.by === 'agent' && st.view.includes('fold='), 'serve 那边：最后是 agent 改的，视图带 fold');

  // 浏览器后退就是撤销
  await page.ev(`history.back()`);
  ok(await page.wait(`!CS.lanes.foldedAliases().length && !CS.view.applying`, 5000), '后退一次：回到没收起（撤销了 agent 那一步）');

  // 再推一次，用户自己改了（开时间顺序）：view back 拒绝
  r = await push(base, one, '再收起');
  ok(r.state === 'applied', '再推一次：applied');
  await lastIs(base, tab, 'applied');
  await sleep(300);
  await page.click('#edgechips [data-t="timeorder"]');
  await sleep(600);
  const b = await back(base);
  ok(b.state === 'refused', '用户之后自己改过：view back 拒绝（refused） ' + (b.error || ''));

  // 用户按着鼠标：deferred，松手约 1 s 后换
  await page.ev(`window.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))`);
  r = await push(base, `run=${fx.a}@loop`, '回到没收起', 2);
  ok(r.state === 'deferred', '用户正按着鼠标：先不换（deferred） ' + JSON.stringify(r).slice(0, 120));
  ok(await page.ev(`CS.lanes.foldedAliases().length === 1`), '按着的时候页面没动');
  await page.ev(`window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))`);
  ok(await page.wait(`!CS.lanes.foldedAliases().length && !CS.view.applying`, 5000), '松手之后换了');
  ok(await lastIs(base, tab, 'applied'), 'serve 那边：这一条换好了');

  // 关了跟随：提示条，点「换过去」才换
  await page.ev(`CS.viewsync.setFollow(false)`);
  await sleep(300);
  r = await push(base, one, '收起一个进程（问一下）', 3);
  ok(r.state === 'offered', '跟随关着：出提示条等用户点（offered） ' + JSON.stringify(r).slice(0, 200));
  ok(await page.wait(`!!document.querySelector('#agbar.offer:not([hidden])')`, 2000) && await page.ev(`!CS.lanes.foldedAliases().length`), '提示条出来了，页面还没换');
  await page.click('#agbar [data-ag="go"]');
  ok(await page.wait(`CS.lanes.foldedAliases().length === 1 && !CS.view.applying`, 5000), '点「换过去」：换了');
  ok(await lastIs(base, tab, 'applied'), 'serve 那边：换好了');
  await page.ev(`CS.viewsync.setFollow(true)`);

  // 后台标签页：queued，回来时只换最后一条
  await page.ev(`Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
                 document.dispatchEvent(new Event('visibilitychange'))`);
  await sleep(400);
  const n0 = await page.ev(`window.__rep.length`);
  const r1 = await push(base, `run=${fx.a}@loop&order=1`, '第一条', 2);
  const r2 = await push(base, `run=${fx.a}@loop`, '第二条', 2);
  ok(r1.state === 'queued' && r2.state === 'queued', '标签页在后台：两条都排着（queued）');
  await page.ev(`Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
                 document.dispatchEvent(new Event('visibilitychange'))`);
  ok(await page.wait(`!CS.lanes.foldedAliases().length && !CS.view.applying && !CS.graph.state.timeOrder`, 6000), '回来：换成最后一条（没收起、时间顺序关）');
  ok(await lastIs(base, tab, 'applied'), 'serve 那边：最后一条换好了');
  const reps = JSON.parse(await page.ev(`JSON.stringify(window.__rep.slice(${n0}))`));
  ok(reps.length && reps.every(x => x[0] === r2.v) && reps.filter(x => x[1] === 'applied').length === 1,
     '只换了最后一条（第一条被顶掉了，页面没收到过）' + JSON.stringify(reps));

  // 等用户点一下：view wait 拿到选中的连线
  const w = fetch(base + 'api/view/wait?for=select&timeout=8&tab=' + tab, { headers: { 'X-Codestrata': '1' } }).then(r => r.json());
  await sleep(400);
  await page.ev(`(() => { const E = CS.lanes.links.find(E => E.k.kind === 'handoff') || CS.lanes.links[0]; CS.lanes.open(E); })()`);
  const wr = await w;
  ok(wr.changed && /sel=l:/.test(wr.tab.view) && wr.tab.by === 'user', 'view wait：用户点了一条线，拿到它的稳定写法 ' + (wr.tab && wr.tab.view || '').slice(0, 120));
}
