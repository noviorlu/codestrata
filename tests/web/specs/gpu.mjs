// GPU kernel（trace --gpu）：kernel 是发起它的那条线程那一列里的一个被调节点（不另成列、不画启动线、不写 GPU 时间）；
// 仓库外的 kernel 落在虚拟节点「GPU · 仓库外」上；边详情里被调方是 kernel 的标「GPU kernel」，仓库外的没有源码可跳
import { waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, fx, ok } = t;
  await page.goto(fx.base4 + '#run=' + fx.gpu);
  ok(await waitRun(page, fx.gpu), '叠上手写了 GPU 日志的 run');
  const s = JSON.parse(await page.ev(`JSON.stringify({
    cols: [...document.querySelectorAll('#g .ln-col .ln-th')].map(x => x.textContent),
    gpuLane: CS.lanes.L.lanes.some(L => L.gpu),
    kinds: [...new Set(CS.lanes.links.map(E => E.k.kind))],
    main: CS.lanes.L.lanes.filter(L => L.thread === 'MainThread').map(L => Object.keys(L.nodes).sort())[0] || [],
    edges: CS.lanes.edges.filter(E => /gpu|csrc/.test(E.e.b)).map(E => [E.e.a, E.e.b])
  })`));
  ok(!s.gpuLane && !s.cols.some(c => /gpu/.test(c)), '没有 GPU 的列：' + s.cols.join('、'));
  ok(s.kinds.indexOf('launch') === -1, '没有启动 kernel 的连线：' + s.kinds);
  const nat = fx.gpu_native;
  ok(s.main.indexOf('?gpu') !== -1, '「GPU · 仓库外」是 MainThread 那一列里的节点：' + s.main);
  ok(s.edges.length > 0 && s.edges.every(e => e[0] === 'dyn/models/net.py'), '从发起它的 net.py 连过去（按真实的栈：forward 里发起的）：' + JSON.stringify(s.edges));
  const ns = await page.ev(`CS.lanes.nodes.find(n => n.id === '?gpu').g.querySelector('.ns').textContent`);
  ok(/^被调 \d+ 次$/.test(ns) && ns.indexOf('µs') === -1, '节点只写次数，不写 GPU 时间：' + ns);

  // 边详情：被调方是 kernel 的标「GPU kernel」，仓库外的写没有源码
  await page.ev(`CS.panel.showEdge('dyn/models/net.py', '?gpu')`);
  await page.wait(`!!document.querySelector('#det .call')`, 5000);
  const e = JSON.parse(await page.ev(`JSON.stringify({
    tag: [...document.querySelectorAll('#det .call .dtag')].map(x => x.textContent),
    to: [...document.querySelectorAll('#det .call .cs')].map(x => x.textContent).filter(x => x.indexOf('to') === 0),
    via: [...document.querySelectorAll('#det .call .via')].map(x => x.textContent).join(' ')
  })`));
  ok(e.tag.length === (nat ? 1 : 2) && e.tag.every(x => x === 'GPU kernel'), '标「GPU kernel」，不标「代码里看不出」：' + e.tag);
  ok(e.to.length === (nat ? 1 : 2) && e.to.every(x => x.indexOf('仓库外，没有源码') !== -1), 'to 写仓库外、没有源码：' + e.to);
  ok(e.via.indexOf('GPU kernel：') !== -1, '说明调用方是怎么认的：' + e.via.slice(0, 60));
  ok(e.via.indexOf('文件改过') === -1, '不说「录制之后这个文件改过」（GPU 启动本来就没有调用行）：' + e.via.slice(0, 120));

  // 请求路径：kernel 挂在 Net.forward 下面，标 GPU kernel；仓库外的不是能点的按钮（没有源码）
  await page.ev(`CS.path.show()`);
  await page.wait(`document.querySelectorAll('#det .prow').length > 0`, 8000);
  const p = JSON.parse(await page.ev(`JSON.stringify([...document.querySelectorAll('#det .prow')].map(r => ({
    d: +r.dataset.d, fn: r.querySelector('.pfn').textContent, btn: r.querySelector('.pfn').tagName,
    tag: (r.querySelector('.dtag') || {}).textContent || '' })))`));
  const fwd = p.find(r => r.fn === 'Net.forward'), foo = p.find(r => r.fn === 'at::native::foo'), sc = p.find(r => r.fn === 'k::scale');
  ok(fwd && foo && sc && foo.d === fwd.d + 1 && sc.d === fwd.d + 1, 'kernel 在 Net.forward 下一层：' + JSON.stringify(p.slice(-4)));
  ok(foo && foo.tag === 'GPU kernel' && foo.btn === 'SPAN' && sc.btn === (nat ? 'BUTTON' : 'SPAN'),
     '标 GPU kernel；仓库外的不能点' + (nat ? '、仓库里的能跳到 .cu' : ''));
}
