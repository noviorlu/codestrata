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
  ok(nat ? s.launch.length === 2 && s.launch.every(x => x[0] === 'dyn/models/net.py' && x[2] === 3 && /^GPU ×3/.test(x[3]))
         : s.launch.length === 1 && s.launch[0][0] === 'dyn/models/net.py' && s.launch[0][2] === 6,
     '从发起它的 net.py 连过来（按真实的栈：forward 里发起的）：' + JSON.stringify(s.launch));

  // 点虚拟节点：详情里没有文件 / 符号那些，只有 kernel 表
  await page.ev(`CS.lanes.nodes.filter(n => n.id === '?gpu')[0].g.dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  // kernel 表先按整个阶段画，这一份（这个流）的次数取回来再换
  await page.wait(`document.getElementById('det').dataset.pkg === '?gpu' && CS.panel._copy && CS.panel._copy.hot && !!document.querySelector('#det .krow')`, 5000);
  const d = JSON.parse(await page.ev(`JSON.stringify({
    title: document.getElementById('dsub').textContent,
    rows: [...document.querySelectorAll('#det .krow')].map(r => r.innerText.replace(/\\s+/g, ' ')),
    hint: (document.querySelector('#det .copyhint') || {}).textContent || '',
    tree: !!document.getElementById('tree')
  })`));
  ok(d.title === '仓库外的 GPU kernel（trace --gpu）', '抽屉标题下写它是什么，不写 0 个文件：' + d.title);
  ok(d.rows.length === (nat ? 1 : 2) && d.rows.some(r => /^at::native::foo ×3 150 µs$/.test(r)), 'kernel 表（只算这个流）：名字、次数、GPU 时间（3 × 50 µs）：' + d.rows);
  ok(d.hint.indexOf('这个 GPU 流') !== -1 && d.hint.indexOf('GPU 0 · 流 7') !== -1, '分列里的提示说是哪个 GPU 流，不说线程：' + d.hint);
  ok(!d.tree, '没有文件树');

  // 仓库里的 kernel：放 .cu 的节点的详情里也列它（要 [native]）
  if (nat) {
  await page.ev(`CS.lanes.nodes.filter(n => n.id === 'dyn/csrc/' && /GPU/.test(n.lane))[0].g.dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  await page.wait(`document.getElementById('det').dataset.pkg === 'dyn/csrc/' && !!document.querySelector('#det .krow')`, 5000);
  const r2 = await page.ev(`[...document.querySelectorAll('#det .krow')].map(r => r.innerText.replace(/\\s+/g, ' ')).join('|')`);
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
