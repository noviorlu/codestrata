// 文件内查找：Ctrl+F、计数和页面上另数的一致、Enter / Shift+Enter、全字匹配、区分大小写、正则、Esc 先关查找栏
import { sleep } from '../lib.mjs';

const st = page => page.ev(`JSON.stringify({open: !!document.querySelector('.vfind'), count: (document.querySelector('.vfind .fc') || {}).textContent,
  bad: !!document.querySelector('.vfind.bad'), cur: CSS.highlights.get('cs-find-cur') ? String([...CSS.highlights.get('cs-find-cur')][0]) : null})`).then(JSON.parse);
const setQ = (page, q) => page.ev(`(i => { i.value = ${JSON.stringify(q)}; i.dispatchEvent(new Event('input')); })(document.querySelector('.vfind input'))`);
const countIn = (page, re) => page.ev(`[...document.querySelectorAll('#viewer .ln .tx')].map(t => (t.textContent.match(${re}) || []).length).reduce((a, b) => a + b, 0)`);

export default async function (t) {
  const { page, base, ok } = t;
  await page.goto(base);
  await page.ev(`CS.viewer.open('fakesvc/truth.py', 1)`);
  await page.wait(`document.querySelectorAll('#viewer .ln').length > 0`);
  await page.key('f', 'KeyF', 70, 2);                              // Ctrl+F
  ok(await page.wait(`!!document.querySelector('.vfind') && document.activeElement === document.querySelector('.vfind input')`), 'Ctrl+F 打开查找栏，焦点在输入框');
  await page.type('callee');
  const n = await countIn(page, '/callee/gi');
  ok(await page.wait(`(document.querySelector('.vfind .fc') || {}).textContent === '1 / ${n}'`), `找 callee：1 / ${n}（和页面上另数的一致）`);
  ok((await st(page)).cur.toLowerCase() === 'callee', '当前匹配另一个颜色标出来');
  await page.key('Enter', 'Enter', 13, 0, '\r');
  await sleep(150);
  ok((await st(page)).count === `2 / ${n}`, 'Enter：下一个');
  await page.key('Enter', 'Enter', 13, 8, '\r'); await page.key('Enter', 'Enter', 13, 8, '\r');
  await sleep(150);
  ok((await st(page)).count === `${n} / ${n}`, 'Shift+Enter 两下：绕回最后一个');

  await page.click('.vfind [data-o="ww"]');
  await sleep(200);
  const nw = await countIn(page, '/(?<![\\w])callee(?![\\w])/gi');
  ok((await st(page)).count.endsWith(' / ' + nw), `全字匹配：${nw} 个`);
  await page.click('.vfind [data-o="ww"]');
  await page.click('.vfind [data-o="cs"]');
  await setQ(page, 'CALLEE');
  ok(await page.wait(`(document.querySelector('.vfind .fc') || {}).textContent === '无结果' && !!document.querySelector('.vfind.bad')`), '区分大小写找 CALLEE：无结果、标红');
  await page.click('.vfind [data-o="cs"]');
  await page.click('.vfind [data-o="re"]');
  await setQ(page, 'callee\\.\\w+');
  await sleep(300);
  const nr = await countIn(page, '/callee\\.\\w+/gi');
  ok((await st(page)).count.endsWith(' / ' + nr), `正则 callee\\.\\w+：${nr} 个`);
  await setQ(page, 'callee(');
  await sleep(300);
  ok((await st(page)).count === '正则有误', '正则写错：说正则有误');
  await page.click('.vfind [data-o="re"]');

  await page.ev(`document.querySelector('.vfind input').focus()`);
  await page.key('Escape', 'Escape', 27);
  const s = await st(page);
  ok(!s.open && !s.cur && !(await page.ev(`document.getElementById('viewer').hidden`)), 'Esc：先关查找栏、清掉标记，窗口还开着');
  await page.key('Escape', 'Escape', 27);
  ok(await page.wait(`document.getElementById('viewer').hidden`), '再 Esc：关窗口');
}
