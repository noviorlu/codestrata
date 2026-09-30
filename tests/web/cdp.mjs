// 浏览器测试的驱动：起一个 headless Chrome（自己的临时配置目录、随机调试端口），经 CDP 操作页面。
// 不管怎么退出（包括中途抛错）都关掉 Chrome、删掉临时目录——不能留下占着端口的浏览器。
// 用法见 run.mjs；每个 spec 拿到的 page 有：goto / ev / wait / click / key / type / mouse / drag / wheel / shot / errors。
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function launch(chromeBin, { width = 1600, height = 1000 } = {}) {
  const port = 9300 + Math.floor(Math.random() * 600);
  const prof = mkdtempSync(join(tmpdir(), 'cs-chrome-'));
  const chrome = spawn(chromeBin, [`--user-data-dir=${prof}`, '--headless=new', '--disable-gpu', '--no-sandbox',
    '--no-first-run', `--remote-debugging-port=${port}`, `--window-size=${width},${height}`, 'about:blank'], { stdio: 'ignore' });
  const cleanup = () => {
    try { chrome.kill('SIGKILL'); } catch {}
    try { rmSync(prof, { recursive: true, force: true }); } catch {}
  };
  process.on('exit', cleanup);
  let ws = null;
  for (let i = 0; i < 100 && !ws; i++) {
    try {
      const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const pg = t.find(x => x.type === 'page');
      if (pg) ws = new WebSocket(pg.webSocketDebuggerUrl);
    } catch {}
    if (!ws) await sleep(100);
  }
  if (!ws) { cleanup(); throw new Error('Chrome 没起来（调试端口 ' + port + '）'); }
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pend = new Map(), errors = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push((d.exception && d.exception.description || d.text || '').split('\n').slice(0, 3).join(' | '));
    }
  };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send('Page.enable'); await send('Runtime.enable');

  const page = {
    errors,
    send,
    /* 在页面里算一个表达式（可以是 Promise），拿回 JSON 能表示的值；页面里抛错就在这里抛 */
    async ev(expr) {
      const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      const res = r.result || {};
      if (res.exceptionDetails) throw new Error('页面里出错：' + (res.exceptionDetails.exception || {}).description + '\n  表达式：' + expr.slice(0, 200));
      return (res.result || {}).value;
    },
    async goto(url, settle = 'CS.app && CS.app.data && CS.app.data.graph') {
      await send('Page.navigate', { url: 'about:blank' });
      await sleep(100);
      await send('Page.navigate', { url });
      if (settle && !(await page.wait(`!!(${settle})`, 20000))) throw new Error('页面没加载好：' + url);
      await sleep(300);
    },
    /* 等到页面里的表达式为真；返回是否等到了 */
    async wait(expr, ms = 10000) {
      for (let t = 0; t < ms; t += 100) {
        try { if (await page.ev(expr)) return true; } catch {}
        await sleep(100);
      }
      return false;
    },
    async rect(sel) {
      const r = await page.ev(`(e => e && (r => ({l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height, x: r.left + r.width / 2, y: r.top + r.height / 2}))(e.getBoundingClientRect()))(document.querySelector(${JSON.stringify(sel)}))`);
      if (!r) throw new Error('页面上没有 ' + sel);
      return r;
    },
    async mouse(type, x, y, buttons = 0, modifiers = 0) {
      await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons, modifiers, clickCount: type === 'mouseMoved' ? 0 : 1 });
    },
    /* 真的鼠标点击（经浏览器的输入管线，会触发 pointer 事件） */
    async click(sel, modifiers = 0) {
      const r = await page.rect(sel);
      await page.mouse('mouseMoved', r.x, r.y, 0, modifiers);
      await page.mouse('mousePressed', r.x, r.y, 1, modifiers);
      await page.mouse('mouseReleased', r.x, r.y, 0, modifiers);
    },
    async drag(x0, y, x1, steps = 8) {
      await page.mouse('mouseMoved', x0, y); await page.mouse('mousePressed', x0, y, 1);
      for (let i = 1; i <= steps; i++) await page.mouse('mouseMoved', x0 + (x1 - x0) * i / steps, y, 1);
      await page.mouse('mouseReleased', x1, y);
    },
    async wheel(x, y, deltaY, modifiers = 0) {
      await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY, modifiers });
    },
    /* 按键：key / code / keyCode；modifiers 1=Alt 2=Ctrl 4=Meta 8=Shift；text 给了就当成会输入字符的键 */
    async key(key, code, keyCode, modifiers = 0, text) {
      await send('Input.dispatchKeyEvent', { type: text ? 'keyDown' : 'rawKeyDown', key, code, windowsVirtualKeyCode: keyCode, modifiers, text });
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: keyCode, modifiers });
    },
    async type(s) { for (const ch of s) await send('Input.insertText', { text: ch }); },
    async size(width, height) {
      if (width) await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      else await send('Emulation.clearDeviceMetricsOverride');
    },
    async shot(path) {
      const b = await send('Page.captureScreenshot', { format: 'png' });
      writeFileSync(path, Buffer.from(b.result.data, 'base64'));
    },
  };
  // 正常结束：等 Chrome 真的退出了再删配置目录（它退出前还在往里写，删早了删不干净）
  async function close() {
    try { ws.close(); } catch {}
    const gone = new Promise(r => chrome.exitCode !== null ? r() : chrome.once('exit', r));
    try { chrome.kill('SIGKILL'); } catch {}
    await Promise.race([gone, sleep(5000)]);
    try { rmSync(prof, { recursive: true, force: true }); } catch {}
  }
  return { page, close };
}
