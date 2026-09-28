"""web/hl.js（浏览器端高亮）对拍 highlight.py（Pygments）。

    .venv/bin/python tests/hl_parity.py              # 默认语料：vllm-omni 包 + codestrata 自己
    .venv/bin/python tests/hl_parity.py DIR [DIR…]   # 换语料（收 .py/.pyi 和 C/C++/CUDA 源文件）

要有 node。查四件事：
  1. 文本保真：每行去标签、反转义后必须和源码那一行一字不差（含 \\t、行尾空格、\\r、非 ASCII），
     且转义写法和 html.escape 完全一样——必须 100%，否则列出 文件:行 两个版本、退出码非 0；
  2. 行数：== text.count("\\n") + 1 == len(to_lines)；
  3. detect / label 和 Python 版一致；
  4. 类名一致率：逐个非空白字符比 CSS 类，按语言汇总；Python/Triton ≥ 95%，C/C++/CUDA ≥ 85%。
另外附一组手写的边角用例（CRLF、BOM、孤立 \\r、未闭合字符串、emoji……）：保真照样卡，一致率只报不卡。
不依赖 pytest；临时文件放 tempfile 目录（跟 TMPDIR 走），跑完删掉。
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from codestrata import highlight as H  # noqa: E402

HL_JS = ROOT / "codestrata" / "web" / "hl.js"
DEFAULT = [Path("/home/yc/projects/duplex-agents/vllm-omni/src/vllm-omni/vllm_omni"), ROOT / "codestrata"]
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
TARGET = {"python": 95.0, "triton": 95.0, "c": 85.0, "cpp": 85.0, "cuda": 85.0}

EDGE = {
    "edge/crlf.py": 'import os\r\n\r\ndef f(x):\r\n    """doc\r\n    more"""\r\n    return x  # c\r\n',
    "edge/bom.py": "\ufeff# -*- coding: utf-8 -*-\nclass A:\n    pass\n",
    "edge/lone_cr.py": "a = 1\rb = 2\nc = '\r'\n",
    "edge/tabs.py": "def f():\n\tif x:\t \n\t\treturn 'a\tb'   \n",
    "edge/unicode.py": "名字 = '你好 😀'\nclass Ünï:\n    def café(self): return \"é\" + 名字  # 注释 😀\n😀 = 1\n",
    "edge/unterminated.py": "x = 'abc\ny = \"\"\"never\nclosed\n",
    "edge/fstr.py": "f'{a!r:>{w}} {b[\"k\"]:{x}.{y}} {{lit}} {c=}'\nrb'\\x' Rb\"\" F'''{\n  z\n}'''\n",
    "edge/softkw.py": "match x:\n    case Point(x=0, y=_):\n        pass\n    case _:\n        match = 1\n",
    "edge/import.py": "from . import a\nfrom ..b.c import (d,\n    e)\nimport x.y as z, w\nraise E from None\nyield from g\n",
    "edge/empty.py": "",
    "edge/nl.py": "\n",
    "edge/noeol.py": "x = 1",
    "edge/esc.py": "s = '<&>\"\\''  # <tag> & \"q\"\n",
    "edge/macro.c": "#include <stdio.h>\n#define M(a, b) \\\n  ((a) + \\\n   (b))\n#if 0\nint dead;\n#endif\nint main(void) { return M(1, 2); }\n",
    "edge/crlf.cpp": "#include \"x.h\"\r\nnamespace n {\r\nclass A : public B {\r\n public:\r\n  int f() const { return 1; }  // c\r\n};\r\n}  // namespace n\r\n",
    "edge/raw.cpp": "auto s = R\"xy(a)\"b\n)xy\";\nauto c = u8'x';\n/* open comment\n",
    "edge/k.cu": "__global__ void k(float4* __restrict__ p) {\n  __shared__ float s[32];\n  p[threadIdx.x] = make_float4(0, 0, 0, 0);\n  __syncthreads_count(1);\n}\n",
    "edge/astral.cpp": "int x = 1; 😀 = 𝔘;\n\"😀\"\n",
    "edge/text.txt": "<b>&'\"\n",
    "edge/lazy.py": "lazy import a.b as c\nlazy from x import y\nz = lazy\nfrom_ = 1\n",
    "edge/types.c": "_Bool b; atomic_int ai; atomic_int8_t no; uint_fast16_t f; size_t s; sigval_t v;\n",
    "edge/vec.cu": "uchar4 a; longlong2 b; longlong3 c; __threadfence_block(); dim3 g; cudaStream_t st;\n",
}

DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const [hlPath, inPath, outPath] = process.argv.slice(2);
global.window = {};
vm.runInThisContext(fs.readFileSync(hlPath, 'utf8'), { filename: hlPath });
const hl = window.CS.hl;
const files = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const now = () => Number(process.hrtime.bigint()) / 1e6;
const res = files.map(f => {
  const lang = hl.detect(f.path, f.text);
  const t0 = now(), lines = hl.lines(f.text, lang);
  return { lang, label: hl.label(lang), lines, ms: now() - t0 };
});
// 最大的那个文件单独计时：预热后跑 7 次取中位数
let big = 0;
files.forEach((f, i) => { if (f.text.length > files[big].text.length) big = i; });
const lang = res[big].lang, ts = [];
for (let k = 0; k < 3; k++) hl.lines(files[big].text, lang);
for (let k = 0; k < 7; k++) { const t0 = now(); hl.lines(files[big].text, lang); ts.push(now() - t0); }
ts.sort((a, b) => a - b);
fs.writeFileSync(outPath, JSON.stringify({ res, big, cold: res[big].ms, warm: ts[3] }));
"""

PIECE = re.compile(r'<span class="t-([a-z]+)">([^<]+)</span>|([^<]+)')


def parse(h: str) -> tuple[str, list[str]]:
    """HTML 行 → (原文, 逐字符类名)。只认 <span class="t-x">…</span> 和裸文本；转义必须和 html.escape 一样。"""
    text, cls, pos = [], [], 0
    while pos < len(h):
        m = PIECE.match(h, pos)
        if not m:
            raise ValueError(f"认不出的标记 @{pos}: {h[pos:pos + 40]!r}")
        c, e = (m.group(1), m.group(2)) if m.group(1) else ("", m.group(3))
        raw = html.unescape(e)
        if html.escape(raw) != e:
            raise ValueError(f"转义和 html.escape 不一致: {e!r}")
        text.append(raw)
        cls += [c] * len(raw)
        pos = m.end()
    return "".join(text), cls


def collect(dirs: list[Path]) -> list[tuple[str, str]]:
    out = []
    for d in dirs:
        base = d.parent
        files = [d] if d.is_file() else sorted(
            p for p in d.rglob("*")
            if p.is_file() and p.suffix.lower() in H.SOURCE_EXTS and not (set(p.parts) & SKIP_DIRS))
        for p in files:
            out.append((str(p.relative_to(base)), p.read_text(encoding="utf-8", errors="replace")))
    return out


def run_node(items: list[tuple[str, str]], tmp: Path) -> dict:
    (tmp / "in.json").write_text(json.dumps([{"path": p, "text": t} for p, t in items]), encoding="utf-8")
    (tmp / "driver.js").write_text(DRIVER, encoding="utf-8")
    r = subprocess.run(["node", str(tmp / "driver.js"), str(HL_JS), str(tmp / "in.json"), str(tmp / "out.json")],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise SystemExit(f"node 跑挂了：\n{r.stdout}\n{r.stderr}")
    return json.loads((tmp / "out.json").read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    if not shutil.which("node"):
        print("没有 node，跑不了")
        return 2
    dirs = [Path(a).resolve() for a in argv] or DEFAULT
    corpus = collect(dirs)
    items = corpus + list(EDGE.items())
    n_corpus = len(corpus)
    tmp = Path(tempfile.mkdtemp(prefix="hl-parity-"))
    try:
        out = run_node(items, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad_fid, bad_misc = [], []
    agree = Counter()
    total = Counter()
    unaligned = Counter()
    n_files = Counter()
    n_lines = Counter()
    per_file = []
    confusion: dict[str, Counter] = defaultdict(Counter)
    example: dict[tuple, str] = {}
    for k, ((path, text), r) in enumerate(zip(items, out["res"])):
        lang = H.detect(path, text)
        if r["lang"] != lang or r["label"] != H.LABEL.get(lang, lang):
            bad_misc.append(f"{path}: detect/label  js={r['lang']}/{r['label']}  py={lang}/{H.LABEL.get(lang)}")
        raw = text.split("\n")
        js = r["lines"]
        if len(js) != len(raw):
            bad_fid.append(f"{path}: 行数 js={len(js)} 源码={len(raw)}")
            continue
        ref = H.to_lines(text, lang)
        if len(ref) != len(raw):
            bad_misc.append(f"{path}: to_lines 行数 {len(ref)} != {len(raw)}")
        is_edge = k >= n_corpus
        fa = ft = 0
        for i, h in enumerate(js):
            try:
                t, c = parse(h)
            except ValueError as e:
                bad_fid.append(f"{path}:{i + 1}: {e}\n    js : {h!r}")
                continue
            if t != raw[i]:
                bad_fid.append(f"{path}:{i + 1}: 文本不一致\n    src: {raw[i]!r}\n    js : {t!r}\n    html: {h!r}")
                continue
            if lang == "text" or i >= len(ref):
                continue
            rt, rc = parse(ref[i])
            if rt != t:
                # Pygments 去了 BOM、\r：把 js 这边的也去掉再对齐
                keep = [j for j, ch in enumerate(t) if ch != "\r" and not (i == 0 and j == 0 and ch == "\ufeff")]
                t2, c = "".join(t[j] for j in keep), [c[j] for j in keep]
                if t2 != rt:
                    unaligned["edge" if is_edge else lang] += sum(not ch.isspace() for ch in t)
                    continue
                t = t2
            for ch, a, b in zip(t, rc, c):
                if ch.isspace():
                    continue
                ft += 1
                if a == b:
                    fa += 1
                else:
                    key = "edge" if is_edge else lang
                    confusion[key][(a, b)] += 1
                    example.setdefault((key, a, b), f"{path}:{i + 1}: {raw[i].strip()[:90]}")
        if is_edge:
            agree["edge"] += fa
            total["edge"] += ft
        else:
            n_files[lang] += 1
            n_lines[lang] += len(raw)
            agree[lang] += fa
            total[lang] += ft
            if ft >= 200:
                per_file.append((fa / ft, fa, ft, path, lang))

    ok = True
    print(f"语料：{n_corpus} 个文件（{', '.join(str(d) for d in dirs)}）+ {len(EDGE)} 个边角用例")
    print(f"hl.js：{HL_JS.stat().st_size} 字节")
    big_path, big_text = items[out["big"]]
    print(f"最大文件：{big_path}（{big_text.count(chr(10)) + 1} 行，{len(big_text)} 字符）"
          f" 首次 {out['cold']:.1f} ms，预热后中位数 {out['warm']:.1f} ms")
    print()
    print("保真：" + ("100%，全部一致" if not bad_fid else f"{len(bad_fid)} 处不一致"))
    for b in bad_fid[:30]:
        print("  ✗ " + b)
    if bad_fid:
        ok = False
    for b in bad_misc[:30]:
        print("  ✗ " + b)
    if bad_misc:
        ok = False
    print()
    print(f"{'语言':8} {'文件':>6} {'行':>8} {'非空白字符':>12} {'一致率':>9} {'目标':>6}  对不齐的字符")
    for lang in ["python", "triton", "c", "cpp", "cuda"]:
        if not n_files[lang]:
            continue
        pct = 100.0 * agree[lang] / max(total[lang], 1)
        flag = "" if pct >= TARGET[lang] else "  ✗"
        if flag:
            ok = False
        print(f"{lang:8} {n_files[lang]:>6} {n_lines[lang]:>8} {total[lang]:>12} {pct:>8.3f}% {TARGET[lang]:>5.0f}%"
              f"  {unaligned[lang]}{flag}")
    print(f"边角用例（不计入门槛）：{agree['edge']}/{total['edge']} 个非空白字符同类，"
          f"{unaligned['edge']} 个对不齐（孤立 \\r 让 Pygments 多切了行）")
    print()
    for lang in confusion:
        top = confusion[lang].most_common(8)
        print(f"{lang} 分歧最多的（pygments → js）：")
        for (a, b), n in top:
            print(f"  {a or '·':6} → {b or '·':6} {n:>6}   例：{example[(lang, a, b)]}")
    per_file.sort()
    if per_file:
        print("\n一致率最低的文件：")
        for pct, fa, ft, path, lang in per_file[:10]:
            print(f"  {100 * pct:7.3f}%  {fa}/{ft}  [{lang}] {path}")
    print("\n" + ("通过" if ok else "未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
