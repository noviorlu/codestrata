// GPU kernel（trace --gpu）：分列里 kernel 按 GPU 设备 · 流单独成列，从发起它的那一列的节点连过来（launch）；
// 仓库外的 kernel 落在虚拟节点「GPU · 仓库外」上，点它看每种 kernel 的次数和 GPU 时间；
// 边详情里被调方是 kernel 的标「GPU kernel」，仓库外的没有源码可跳
import { waitRun } from '../lib.mjs';

export default async function (t) {
  const { page, fx, ok } = t;
  await page.goto(fx.base4 + '#run=' + fx.gpu);
  ok(await waitRun(page, fx.gpu), '叠上手写了 GPU 日志的 run');
  const s = JSON.parse(await page.ev(`JSON.stringify({
    cols: [...document.querySelectorAll('#g .ln-col .ln-th')].map(x => x.textContent),
    gpuLane: (CS.lanes.L.lanes.filter(L => L.gpu)[0] || {}).id || null,
    gpuNodes: CS.lanes.nodes.filter(n => /GPU/.test(n.lane)).map(n => n.id).sort(),
    launch: CS.lanes.links.filter(E => E.k.kind === 'launch').map(E => [E.k.from.node, E.k.to.node, E.k.n, E.labTxt])
  })`));
  ok(s.cols.some(c => c.indexOf('GPU 0 · 流 7') === 0), 'kernel 单独成一列：GPU 0 · 流 7（' + s.cols.join('、') + '）');
  // 装了 tree-sitter（[native]）时 .cu 里的 k::scale 是仓库里的 kernel，落在放 .cu 的目录上；没装时它也在仓库外
  const nat = fx.gpu_native;
  ok(JSON.stringify(s.gpuNodes) === JSON.stringify(nat ? ['?gpu', 'dyn/csrc/'] : ['?gpu']),
     'GPU 列里是' + (nat ? '放 .cu 的目录和' : '') + '「GPU · 仓库外」：' + s.gpuNodes);
  ok(nat ? s.launch.length === 2 && s.launch.every(x => x[0] === 'dyn/models/net.py' && x[2] === 3 && /^GPU ×3 · 150 µs$/.test(x[3]))
         : s.launch.length === 1 && s.launch[0][0] === 'dyn/models/net.py' && s.launch[0][2] === 6 && /^GPU ×6 · 300 µs$/.test(s.launch[0][3]),
     '从发起它的 net.py 连过来（按真实的栈：forward 里发起的），线上写次数和 GPU 时间：' + JSON.stringify(s.launch));
  // GPU 列里的节点写 kernel 跑了几次、GPU 上一共多久（每个 50 µs）
  const ns = await page.ev(`CS.lanes.nodes.find(n => n.id === '?gpu').g.querySelector('.ns').textContent`);
  ok(ns === (nat ? '3 次 · 150 µs' : '6 次 · 300 µs'), 'GPU 列的节点写次数和 GPU 时间：' + ns);
  // 点 launch 连线：两头不写「线程的入口函数」，写 GPU 上共多久
  await page.ev(`CS.lanes.open(CS.lanes.links.find(E => E.k.kind === 'launch'))`);
  await page.wait(`/启动 GPU kernel/.test(document.getElementById('det').textContent)`, 5000);
  const lt = await page.ev(`document.getElementById('det').textContent`);
  ok(lt.indexOf('GPU 上共') !== -1 && lt.indexOf('线程的入口函数') === -1 && lt.indexOf('GPU 上跑的 kernel') !== -1,
     'launch 详情：写 GPU 上共多久，发起的那头写栈上最近的仓库函数、另一头写 kernel，不写线程的入口函数：' + lt.slice(0, 120));
  await page.key('Escape', 'Escape', 27);

  // 点虚拟节点：详情里没有文件 / 符号那些，只有 kernel 表
  await page.ev(`CS.lanes.nodes.filter(n => n.id === '?gpu')[0].g.dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  // kernel 表先按整个阶段画，这一份（这个流）的次数取回来再换
  await page.wait(`document.getElementById('det').dataset.pkg === '?gpu' && CS.panel._copy && CS.panel._copy.hot && !!document.querySelector('#det .krow')`, 5000);
  const d = JSON.parse(await page.ev(`JSON.stringify({
    title: document.getElementById('dsub').textContent,
    rows: [...document.querySelectorAll('#det .krow:not(.kcall)')].map(r => r.innerText.replace(/\\s+/g, ' ')),
    calls: [...document.querySelectorAll('#det .krow.kcall')].map(r => r.innerText.replace(/\\s+/g, ' ')),
    hint: (document.querySelector('#det .copyhint') || {}).textContent || '',
    tree: !!document.getElementById('tree')
  })`));
  ok(d.title === '仓库外的 GPU kernel（trace --gpu）', '抽屉标题下写它是什么，不写 0 个文件：' + d.title);
  ok(d.rows.length === (nat ? 1 : 2) && d.rows.some(r => /^at::native::foo ×3 150 µs$/.test(r)), 'kernel 表（只算这个流）：名字、次数、GPU 时间（3 × 50 µs）：' + d.rows);
  ok(d.hint.indexOf('这个 GPU 流') !== -1 && d.hint.indexOf('GPU 0 · 流 7') !== -1, '分列里的提示说是哪个 GPU 流，不说线程：' + d.hint);
  ok(d.calls.length === d.rows.length && d.calls.every(r => /^← net:Net\.forward ×3 150 µs$/.test(r)),
     'kernel 表里每种 kernel 下面写是谁发起的、几次、GPU 上多久：' + d.calls);
  ok(!d.tree, '没有文件树');

  // 仓库里的 kernel：放 .cu 的节点的详情里也列它（要 [native]）
  if (nat) {
  await page.ev(`CS.lanes.nodes.filter(n => n.id === 'dyn/csrc/' && /GPU/.test(n.lane))[0].g.dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  await page.wait(`document.getElementById('det').dataset.pkg === 'dyn/csrc/' && !!document.querySelector('#det .krow')`, 5000);
  await page.wait(`CS.panel._copy && CS.panel._copy.hot`, 5000);
  const r2 = await page.ev(`[...document.querySelectorAll('#det .krow:not(.kcall)')].map(r => r.innerText.replace(/\\s+/g, ' ')).join('|')`);
  ok(/^k::scale ×3 150 µs$/.test(r2), '.cu 的详情里列它定义的 kernel：' + r2);
  }

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
