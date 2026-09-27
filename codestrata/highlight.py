"""源码高亮：Python、Triton、C++（含 CUDA）。

用 Pygments 在服务端做，前端只管塞 HTML。这样 serve 和单文件导出拿到的是同一份
结果，导出版离线也能看高亮，不用把 JS 高亮库塞进去。

- **Triton 不是一种文件类型。** kernel 就写在 .py 里（@triton.jit 装饰的函数），
  所以是 Python 词法器打底，再把 `tl.*` 原语和 `@triton.*` 装饰器重新标成 Triton 色。
- **CUDA 算 C++ 家族。** .cu/.cuh 用 Pygments 的 CudaLexer，再给执行空间限定符、
  线程索引、同步原语单独上色。
- **`.h` 强制按 C++ 处理。** Pygments 默认判成 C，会把 class/template/namespace 标错；
  而在 C++ 项目里 .h 基本都是 C++ 头文件。

输出按源码行对齐：跨行的 token（docstring、/* */ 块注释）在换行处拆开，
每行各自闭合 span。token 的颜色不用 Pygments 的主题，而是映射到页面自己的
CSS 变量（t-kw、t-str……），亮色/暗色跟着页面走。
"""
from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path

try:
    from pygments.lexers import get_lexer_by_name
    from pygments.token import (Comment, Keyword, Literal, Name, Operator,
                                String, Number)
    HAVE_PYGMENTS = True
except Exception:                                    # pragma: no cover
    HAVE_PYGMENTS = False

# 当前只聚焦这三类
EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".c": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".c++": "cpp",
    ".h": "cpp", ".hh": "cpp", ".hpp": "cpp", ".hxx": "cpp", ".inl": "cpp",
    ".cu": "cuda", ".cuh": "cuda",
}
SOURCE_EXTS = frozenset(EXT_LANG)
LABEL = {"python": "Python", "triton": "Python · Triton", "cpp": "C++",
         "c": "C", "cuda": "C++ · CUDA", "text": "文本"}
PYGMENTS_NAME = {"python": "python", "triton": "python", "cpp": "cpp",
                 "c": "c", "cuda": "cuda"}

TRITON_RE = re.compile(r"^\s*(?:import\s+triton\b|from\s+triton\b|@triton\.)", re.M)
CUDA_NAMES = frozenset("""
__global__ __device__ __host__ __shared__ __constant__ __managed__ __restrict__
__forceinline__ __noinline__ __launch_bounds__ __syncthreads __syncwarp __threadfence
threadIdx blockIdx blockDim gridDim warpSize dim3 cudaStream_t cudaError_t
atomicAdd atomicMax atomicMin atomicCAS atomicExch __shfl_sync __shfl_down_sync
__shfl_up_sync __shfl_xor_sync __ldg __half __nv_bfloat16 __float2half __half2float
""".split())


def detect(rel: str, text: str = "") -> str:
    lang = EXT_LANG.get(Path(rel).suffix.lower())
    if lang is None:
        return "text"
    if lang == "python" and TRITON_RE.search(text):
        return "triton"
    return lang


def _cls(tt) -> str:
    """Pygments token 类型 → 页面的 CSS 类（沿类型层级往上找第一个命中的）。"""
    if tt in Comment.Preproc or tt in Comment.PreprocFile:
        return "pre"
    if tt in Comment:
        return "com"
    if tt in String.Doc:
        return "doc"
    if tt in String or tt in Literal.String:
        return "str"
    if tt in Number or tt in Literal.Number:
        return "num"
    if tt in Keyword.Type:
        return "type"
    if tt in Keyword.Constant:
        return "const"
    if tt in Keyword:
        return "kw"
    if tt in Operator.Word:
        return "kw"
    if tt in Name.Builtin.Pseudo:
        return "self"
    if tt in Name.Builtin:
        return "bi"
    if tt in Name.Function:
        return "fn"
    if tt in Name.Class:
        return "cls"
    if tt in Name.Decorator:
        return "dec"
    if tt in Name.Namespace:
        return "ns"
    return ""


def _tokens(text: str, lang: str):
    """(类名, 文本) 流，已套上 Triton / CUDA 的专属重标。"""
    lexer = get_lexer_by_name(PYGMENTS_NAME[lang],
                              stripnl=False, stripall=False, ensurenl=False)
    toks = [(_cls(tt), v, tt) for tt, v in lexer.get_tokens(text)]

    if lang == "triton":
        # tl.load / tl.program_id / tl.constexpr：三段都染成 Triton 色
        out, i = [], 0
        while i < len(toks):
            c, v, tt = toks[i]
            if (v == "tl" and tt in Name and i + 2 < len(toks)
                    and toks[i + 1][1] == "." and toks[i + 2][2] in Name):
                out += [("tri", "tl", tt), ("tri", ".", tt), ("tri", toks[i + 2][1], tt)]
                i += 3
                continue
            if c == "dec" and v.startswith("@triton"):
                out.append(("tridec", v, tt))
            else:
                out.append((c, v, tt))
            i += 1
        toks = out
    elif lang == "cuda":
        toks = [("cuda" if v in CUDA_NAMES else c, v, tt) for c, v, tt in toks]
    return toks


def to_lines(text: str, lang: str) -> list[str]:
    """高亮后按源码行切开，保证第 N 个元素就是第 N 行（行号不会错位）。"""
    n_src = text.count("\n") + 1
    if not HAVE_PYGMENTS or lang not in PYGMENTS_NAME:
        return [html.escape(x) for x in text.split("\n")]
    lines, cur = [], []
    for c, v, _ in _tokens(text, lang):
        parts = v.split("\n")
        for k, part in enumerate(parts):
            if k:                                   # 跨行 token：在换行处闭合，下一行重开
                lines.append("".join(cur))
                cur = []
            if part:
                e = html.escape(part)
                cur.append(f'<span class="t-{c}">{e}</span>' if c else e)
    lines.append("".join(cur))
    # 词法器偶尔会多吐/少吐一个尾部空行；强制和源码行数对齐
    if len(lines) > n_src:
        lines = lines[:n_src]
    while len(lines) < n_src:
        lines.append("")
    return lines


def outline(text: str, lang: str) -> list[dict]:
    """C++ / CUDA 的大纲。没有 AST，只能从词法 token 里捡函数名和类名——
    是启发式的（声明和定义都会被捡到），前端会标注这一点。Python 走 ast，不用这个。"""
    if not HAVE_PYGMENTS or lang not in ("cpp", "c", "cuda"):
        return []
    out, line, seen = [], 1, set()
    prev_kw = ""
    for c, v, tt in _tokens(text, lang):
        if c in ("fn", "cls") and v.strip():
            key = (v, line)
            if key not in seen:
                seen.add(key)
                kind = "class" if c == "cls" else ("kernel" if prev_kw == "__global__" else "func")
                out.append({"n": v, "k": kind, "l": line})
        if v in ("__global__", "__device__", "__host__"):
            prev_kw = v
        elif v.strip() and v not in ("void", " ", "\t", "\n"):
            if c not in ("type", "kw") and v not in ("(",):
                prev_kw = prev_kw if c in ("fn",) else ""
        line += v.count("\n")
    return out


@lru_cache(maxsize=512)
def _cached(path: str, mtime: float, size: int, rel: str) -> dict:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lang = detect(rel, text)
    return {"lang": lang, "label": LABEL.get(lang, lang), "text": text,
            "lines": to_lines(text, lang), "outline": outline(text, lang)}


def highlight_file(root: Path, rel: str) -> dict:
    """带缓存：按 (路径, mtime, 大小) 失效，改了文件自动重算。"""
    p = root / rel
    st = p.stat()
    return _cached(str(p), st.st_mtime, st.st_size, rel)
