// 跑浏览器测试：node run.mjs <chrome> <serve 地址> <fixture.json> [spec …]
// fixture.json 由 tests/test_browser.py 写：两个 run 的 id、阶段等。每个 spec 是 specs/<名字>.mjs，默认导出
// async (t) => {}，t 有 page、base、fx、ok(条件, 说明)。页面里抛的未捕获异常也算失败。
// 输出每条检查的 ✓ / ✗，最后一行「全部通过」或「N 个失败」；退出码 = 失败数（最多 1）。
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch } from './cdp.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const [chromeBin, base, fxPath, ...only] = process.argv.slice(2);
const fx = JSON.parse(readFileSync(fxPath, 'utf8'));
const specs = (only.length ? only : readdirSync(join(here, 'specs')).filter(f => f.endsWith('.mjs')).map(f => f.slice(0, -4))).sort();

let fails = 0;
const b = await launch(chromeBin);
process.on('uncaughtException', e => { console.log('  ✗ 中途出错：' + (e && e.stack || e)); b.close(); process.exit(1); });
for (const name of specs) {
  console.log('# ' + name);
  const mod = await import(join(here, 'specs', name + '.mjs'));
  const t = {
    page: b.page, base, fx,
    ok(cond, msg) { console.log((cond ? '  ✓ ' : '  ✗ ') + msg); if (!cond) fails++; },
  };
  b.page.errors.length = 0;
  try {
    await mod.default(t);
  } catch (e) {
    fails++;
    console.log('  ✗ 出错：' + (e && e.stack || e).toString().split('\n').slice(0, 4).join(' | '));
  }
  if (b.page.errors.length) { fails++; console.log('  ✗ 页面报错：' + b.page.errors.join(' || ')); }
  await b.page.size(0);
}
await b.close();
console.log(fails ? fails + ' 个失败' : '全部通过');
process.exit(fails ? 1 : 0);
