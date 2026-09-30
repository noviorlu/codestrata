// 代码窗口：打开整个文件、大纲、Ctrl+点击跳到定义并列出引用、「← 返回」、Esc 关
import { sleep } from '../lib.mjs';

export default async function (t) {
  const { page, base, ok } = t;
  await page.goto(base);
  const src = await page.ev(`fetch('api/file?f=fakesvc/truth.py').then(r => r.json())`);
  await page.ev(`CS.viewer.open('fakesvc/truth.py', 1)`);
  ok(await page.wait(`document.querySelectorAll('#viewer .ln').length > 0`), '打开 truth.py');
  ok(await page.ev(`document.querySelectorAll('#viewer .ln').length`) === src.n_lines, `行数和文件一致（${src.n_lines} 行）`);
  ok(await page.ev(`[...document.querySelectorAll('#viewer .osym')].some(b => b.textContent.includes('s_nest'))`), '大纲里有 s_nest');

  // Ctrl+点击 s_nest 里调到的 callee.mid：跳到 callee.py 的定义，旁边列出引用
  const xr = await page.ev(`(() => {
    const x = [...document.querySelectorAll('#viewer .xr')].find(e => e.textContent.endsWith('mid'));
    if (!x) return null;
    x.scrollIntoView({block: 'center'});
    const r = x.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};
  })()`);
  ok(!!xr, 'truth.py 里 callee.mid 是可以 Ctrl+点击的名字');
  if (xr) {
    await page.mouse('mouseMoved', xr.x, xr.y, 0, 2);
    await page.mouse('mousePressed', xr.x, xr.y, 1, 2);
    await page.mouse('mouseReleased', xr.x, xr.y, 0, 2);
    ok(await page.wait(`(document.querySelector('#viewer .vhead b') || {}).textContent === 'fakesvc/callee.py'`), 'Ctrl+点击：跳到 callee.py');
    ok(await page.wait(`!document.querySelector('#viewer .vrefs').hidden && document.querySelector('#viewer .vrefs').textContent.includes('truth.py')`),
       '旁边一栏列出引用，其中有 truth.py');
    await page.click('#viewer [data-back]');
    ok(await page.wait(`(document.querySelector('#viewer .vhead b') || {}).textContent === 'fakesvc/truth.py'`), '「← 返回」：回到 truth.py');
  }
  await page.key('Escape', 'Escape', 27);          // 先关引用栏（开着的话）
  await sleep(100);
  if (!(await page.ev(`document.getElementById('viewer').hidden`))) await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`document.getElementById('viewer').hidden`), 'Esc：关掉窗口');
}
