// 时间轴：阶段按钮、条上的色段、拖把手 / 平移出时间段、键盘、滚轮缩放、「全程」、点色段、超出终点的时间段
import { hash, hotEdges, sleep, waitRun } from '../lib.mjs';

const st = page => page.ev(`JSON.stringify({pressed: [...document.querySelectorAll('.tph[aria-pressed=true]')].map(b => b.dataset.ph),
  lab: (document.querySelector('.tlab') || {}).textContent, zoomed: !document.querySelector('.tzoom').hidden,
  win: CS.app.data.hotMeta.window, banner: document.getElementById('hotbanner').textContent})`).then(JSON.parse);

export default async function (t) {
  const { page, base, fx, ok } = t;
  await page.goto(base + '#run=' + fx.a + '@loop');
  ok(await waitRun(page, fx.a + '@loop'), '打开 A@loop');
  ok(JSON.stringify(await page.ev(`[...document.querySelectorAll('.tph')].map(b => b.dataset.ph)`)) === JSON.stringify(['', 'start', 'loop', 'forks']),
     '阶段按钮：全部 + start / loop / forks');
  let s = await st(page);
  ok(s.pressed.join() === 'loop' && s.lab.startsWith('loop：'), 'loop 按下，标签写 loop 的起止 ' + s.lab);
  const seg = await page.rect('.tseg[data-seg="loop"]'), sel = await page.rect('.tsel');
  ok(Math.abs(seg.l - sel.l) < 2 && Math.abs(seg.r - sel.r) < 2, '选中框和 loop 色段对齐');

  // 拖左把手往右：变成 loop 的后半段（前半段刚切阶段、还没有调用：切阶段时触发的进程会停 0.1 s）。
  // 拖的半路上条的宽度定住（标签随时间段变宽会把条挤窄，手下对应的时间就跳），松手放开
  const x0 = sel.l + 2, x1 = sel.l + sel.w * 0.5, bw = Math.round((await page.rect('.tbar')).w);
  await page.mouse('mouseMoved', x0, sel.y); await page.mouse('mousePressed', x0, sel.y, 1);
  for (let i = 1; i <= 4; i++) await page.mouse('mouseMoved', x0 + (x1 - x0) * i / 8, sel.y, 1);
  const frozen = await page.ev(`(c => [c.flexGrow, c.flexShrink, Math.round(parseFloat(c.flexBasis))])(getComputedStyle(document.querySelector('.tbar')))`);
  for (let i = 5; i <= 8; i++) await page.mouse('mouseMoved', x0 + (x1 - x0) * i / 8, sel.y, 1);
  await page.mouse('mouseReleased', x1, sel.y);
  ok(JSON.stringify(frozen) === JSON.stringify(['0', '0', bw]) && await page.ev(`!document.querySelector('.tbar').style.flex`),
     '拖的半路上条的宽度定住、松手放开 ' + JSON.stringify([frozen, bw]));
  ok(await page.wait(`/@t=\\d+-\\d+(&|$)/.test(decodeURIComponent(location.hash)) && !!CS.app.data.hotMeta.window`, 15000), '拖左把手：地址变成 @t=起-止 ' + await hash(page));
  ok(await page.wait(`document.getElementById('prog').textContent === ''`, 15000), '画好了：「叠加 run …」清掉');
  s = await st(page);
  const tl = await page.ev(`CS.app.data.hotMeta.timeline.find(x => x[0] === 'loop')`);
  ok(s.win[1] === tl[2] && s.win[0] > tl[1], '终点不变、起点往后 ' + JSON.stringify([s.win, tl]));
  ok(s.pressed.length === 0 && s.banner.includes('时间段') && s.banner.includes('跨文件'), '没有阶段按下，横幅写明时间段、只算跨文件的调用');
  const he = await hotEdges(page);
  ok(Object.keys(he).length >= 1 && !he['fakesvc/execd.py|fakesvc/work.py'], '时间段里跑到的边 ' + JSON.stringify(he));

  // 拖中间：平移，宽度不变
  const w0 = s.win, sel2 = await page.rect('.tsel');
  await page.drag(sel2.x, sel2.y, sel2.x - sel2.w * 0.3);
  ok(await page.wait(`CS.app.data.hotMeta.window && CS.app.data.hotMeta.window[0] !== ${w0[0]}`, 15000), '拖中间：时间段挪了');
  s = await st(page);
  ok(Math.abs((s.win[1] - s.win[0]) - (w0[1] - w0[0])) <= 2 && s.win[0] < w0[0], '平移：宽度不变、往前挪');

  // 键盘：右把手左移一下，提交后焦点还在
  const w1 = s.win;
  await page.ev(`document.querySelector('.th.r').focus()`);
  await page.key('ArrowLeft', 'ArrowLeft', 37);
  const kbHeld = await page.ev(`document.querySelector('.tbar').style.flex`);
  ok(await page.wait(`CS.app.data.hotMeta.window && CS.app.data.hotMeta.window[1] < ${w1[1]}`, 15000), '键盘 ←：终点前移');
  ok(/^0 0 [\d.]+px$/.test(kbHeld) && await page.wait(`!document.querySelector('.tbar').style.flex`, 3000),
     '键盘挪的时候条宽也定住，提交后放开 ' + JSON.stringify(kbHeld));
  await sleep(300);
  ok(await page.ev(`!!document.activeElement && document.activeElement.matches('.th.r')`), '提交重画之后焦点还在右把手上');
  ok(/^\d+$/.test(await page.ev(`document.querySelector('.th.r').getAttribute('aria-valuenow')`)), '把手有 aria-valuenow');

  // 滚轮缩放、「全程」
  await page.click('.tph[data-ph="loop"]');
  ok(await waitRun(page, fx.a + '@loop'), '点 loop 按钮：回到 loop');
  ok(await page.wait(`document.getElementById('prog').textContent === ''`, 15000), '换阶段画好了：「叠加 run …」清掉');
  const bw0 = (await page.rect('.tseg[data-seg="loop"]')).w, bar = await page.rect('.tbar');
  for (let i = 0; i < 4; i++) { await page.wheel(bar.x, bar.y, 300); await sleep(60); }
  ok((await page.rect('.tseg[data-seg="loop"]')).w < bw0 * 0.8, '滚轮往下：缩小（loop 色段变窄）');
  if ((await st(page)).zoomed) { await page.click('.tzoom'); await sleep(200); }
  ok(!(await st(page)).zoomed, '「全程」：看整个 run');

  // 点色段：选 forks；点「全部」
  const fk = await page.rect('.tseg[data-seg="forks"]');
  await page.mouse('mouseMoved', fk.x, fk.y); await page.mouse('mousePressed', fk.x, fk.y, 1); await page.mouse('mouseReleased', fk.x, fk.y);
  ok(await waitRun(page, fx.a + '@forks'), '点 forks 色段：选 forks');
  ok((await hotEdges(page))['fakesvc/execd.py|fakesvc/work.py'] === 1, 'forks 阶段里有 exec 那条边');
  await page.click('.tph[data-ph=""]');
  ok(await waitRun(page, fx.a), '点「全部」：整个 run');
  ok(!(await hash(page)).includes('@'), '地址里没有 @');

  // 地址里的时间段超出终点：条放长，选中框照样画出来
  const end = await page.ev('CS.app.data.hotMeta.end_us');
  await page.goto(base + '#run=' + fx.a + '@t=' + (end + 1000) + '-' + (end + 5000));
  ok(await page.ev(`!!CS.app.data.hotMeta.window && !document.querySelector('.tsel').hidden && document.querySelector('.tsel').getBoundingClientRect().width > 0`),
     '超出终点的时间段：选中框照样画出来');
}
