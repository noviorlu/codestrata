"""解读层：人和 LLM agent 写的那部分。

分工是明确的：
  - 静态事实（包、边、高度、符号位置）由 scan.py 产出，随时可以删掉重建。
  - **为什么这样切、算法为什么这么写、该按什么顺序读** —— 机器给不出来，
    这部分留空，等人或 agent 填。

解读不放在 .codestrata/（那是可重建的缓存），而是放在仓库里的 notes/，
跟代码一起进版本库。一个目标一个文件，多个 agent 能并行写、git 能干净合并。

最关键的约束是**解读会腐烂**：代码一改，解读可能变成谎言，而且是静默的。
所以每份解读的 frontmatter 里存 `code_sha` —— 它所描述的那些源文件的内容哈希。
重扫时一比就知道过期没有，前端据此打黄标。
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
from pathlib import Path

NOTES_DIRNAME = "notes"


# ---------------------------------------------------------------- 路径与哈希

def notes_root(repo: Path) -> Path:
    return repo / NOTES_DIRNAME


def _safe_name(target: str) -> str:
    return re.sub(r"[^A-Za-z0-9._:-]", "_", target)


def note_path(repo: Path, target: str, kind: str = "package") -> Path:
    sub = {"package": "packages", "symbol": "symbols", "edge": "edges"}.get(kind, "packages")
    return notes_root(repo) / sub / (_safe_name(target) + ".md")


def code_sha(repo: Path, index: dict, target: str, kind: str = "package") -> str:
    """算出「这份解读所描述的代码」的哈希。

    package：该包下所有文件的内容；symbol：所属文件的内容。
    只要其中任何一个字节变了，哈希就变，解读被标记为可能过期。
    """
    h = hashlib.sha256()
    if kind == "package":
        rels = sorted(r for r, p in (index.get("files") or {}).items() if p == target)
    else:
        s = (index.get("symbols") or {}).get(target)
        rels = [s["f"]] if s else []
    for rel in rels:
        try:
            h.update(rel.encode())
            h.update((repo / rel).read_bytes())
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()[:16] if rels else ""


# ---------------------------------------------------------------- frontmatter

def parse(md: str) -> tuple[dict, str]:
    """拆出 YAML-ish frontmatter。只支持 `key: value` 一层，够用且不引依赖。"""
    if not md.startswith("---"):
        return {}, md
    end = md.find("\n---", 3)
    if end < 0:
        return {}, md
    head, body = md[3:end], md[end + 4:]
    meta: dict = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body.lstrip("\n")


def dump(meta: dict, body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


# ---------------------------------------------------------------- 读写

def load(repo: Path, index: dict, target: str, kind: str = "package") -> dict:
    """读一份解读。没有就返回空槽（present=False），前端据此显示 task 提示。"""
    p = note_path(repo, target, kind)
    now = code_sha(repo, index, target, kind)
    if not p.exists():
        return {"target": target, "kind": kind, "present": False,
                "code_sha_now": now, "stale": False, "md": "", "html": "", "meta": {}}
    md = p.read_text(encoding="utf-8")
    meta, body = parse(md)
    was = (meta.get("code_sha") or "").strip()
    return {"target": target, "kind": kind, "present": True,
            "path": str(p.relative_to(repo)),
            "code_sha_now": now, "code_sha_note": was,
            "stale": bool(was and now and was != now),
            "md": body, "html": md_to_html(body), "meta": meta}


def save(repo: Path, index: dict, target: str, body: str, *,
         kind: str = "package", meta: dict | None = None) -> dict:
    p = note_path(repo, target, kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    m = dict(meta or {})
    m.setdefault("target", target)
    m.setdefault("kind", kind)
    m["code_sha"] = code_sha(repo, index, target, kind)
    m.setdefault("status", "draft")
    p.write_text(dump(m, body), encoding="utf-8")
    return load(repo, index, target, kind)


# ---------------------------------------------------------------- 极简 Markdown

_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
)


def _inline(t: str) -> str:
    t = _html.escape(t)
    for pat, rep in _INLINE:
        t = pat.sub(rep, t)
    return t


def md_to_html(md: str) -> str:
    """只支持解读用得到的子集：标题、列表、代码块、行内码、粗体、链接。

    在 Python 侧渲染而不是前端，是为了不给单文件导出引一个 JS markdown 库
    （那样离线就得靠 CDN）。
    """
    out: list[str] = []
    in_code = False
    in_ul = in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in md.split("\n"):
        line = raw.rstrip()
        if line.startswith("```"):
            close_lists()
            out.append("</pre>" if in_code else '<pre class="note-code">')
            in_code = not in_code
            continue
        if in_code:
            out.append(_html.escape(raw))
            continue
        if not line.strip():
            close_lists()
            continue
        m = re.match(r"(#{1,4})\s+(.*)", line)
        if m:
            close_lists()
            lvl = min(6, len(m.group(1)) + 2)      # ## → h4，避免和页面 h2 打架
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"[-*]\s+(.*)", line)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        m = re.match(r"(\d+)[.)]\s+(.*)", line)
        if m:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(m.group(2))}</li>")
            continue
        close_lists()
        out.append(f"<p>{_inline(line)}</p>")
    close_lists()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


# ---------------------------------------------------------------- 任务派发

_QUESTIONS = [
    ("是什么", "一句话说清这个模块承担什么职责。"),
    ("为什么这样切", "它为什么独立成一块？边界为什么画在这里、和相邻模块的分界是什么？"),
    ("读法", "按什么顺序读它里面的符号，每一步为什么先读它。"),
    ("关键算法", "挑 1–3 处值得解释的实现：它做什么，以及**为什么这么写**"
                 "（性能、协议约束、上游 bug、历史包袱都算）。"),
]


def tasks(repo: Path, index: dict, *, include_stale: bool = True) -> list[dict]:
    """列出还需要解读的目标，**按架构高度从低到高**排。

    叶子模块没有内部依赖，可以孤立读懂；入口层必须先理解它依赖的东西。
    所以从底往上派活，写到上层时下层的解读已经存在、可以直接引用。
    """
    pkgs = index["packages"]
    out = []
    for name in sorted(pkgs, key=lambda n: pkgs[n]["alt"]):
        v = pkgs[name]
        # 跟图保持一致：既无符号又无连边的空包（典型是空 __init__.py）没有可解读的内容
        if v["out"] == 0 and v["in"] == 0 and v["classes"] == 0 and v["funcs"] == 0:
            continue
        st = load(repo, index, name, "package")
        if st["present"] and not (include_stale and st["stale"]):
            continue
        out.append({
            "target": name, "kind": "package",
            "reason": "stale" if st["present"] else "missing",
            "alt": pkgs[name]["alt"], "files": pkgs[name]["files"],
            "classes": pkgs[name]["classes"], "funcs": pkgs[name]["funcs"],
        })
    return out


def prompt_pack(repo: Path, index: dict, target: str, *,
                max_symbols: int = 12, hot: dict | None = None) -> str:
    """给 agent 的输入包：静态事实 + 要读哪些符号 + 邻居已有的解读 + 要回答什么。

    邻居的解读也一并给出，这样上层的解读能引用下层，而不是各说各话。
    """
    pkgs = index["packages"]
    v = pkgs.get(target, {})
    syms = [(k, s) for k, s in (index.get("symbols") or {}).items()
            if s["p"] == target and "." not in s["n"]]
    syms.sort(key=lambda kv: (kv[1]["k"] != "class", kv[1]["f"], kv[1]["l"]))
    dep = sorted({b for a, b, _ in index["edges"] if a == target})
    rdep = sorted({a for a, b, _ in index["edges"] if b == target})

    L: list[str] = []
    L.append(f"# 解读任务：{target}")
    L.append("")
    L.append("## 机器已知的事实（不用再查）")
    L.append(f"- 架构高度 {v.get('alt', 0):+.2f}"
             f"（出边 {v.get('out', 0)} / 入边 {v.get('in', 0)}；+1=入口，−1=叶子）")
    L.append(f"- {v.get('files', 0)} 个文件，{v.get('loc', 0)} 行，"
             f"{v.get('classes', 0)} 个类，{v.get('funcs', 0)} 个函数")
    L.append(f"- 依赖 → {', '.join(dep) or '（无内部依赖，是叶子）'}")
    L.append(f"- 被依赖 ← {', '.join(rdep) or '（无人依赖，是入口）'}")
    if hot and hot.get("packages", {}).get(target):
        L.append(f"- runtime：这个包在记录的 case 里被调用 {hot['packages'][target]} 次")
    L.append("")
    L.append("## 这个包里的符号（按建议阅读顺序）")
    for k, s in syms[:max_symbols]:
        h = (hot or {}).get("symbols", {}).get(k)
        L.append(f"- `{s['n']}` {'class' if s['k'] == 'class' else 'func'} "
                 f"— {s['f']}:{s['l']}"
                 + (f"，继承 {', '.join(s['b'])}" if s.get("b") else "")
                 + (f"，runtime {h} 次" if h else ""))
    if len(syms) > max_symbols:
        L.append(f"- …还有 {len(syms) - max_symbols} 个")
    L.append("")

    have = [(d, load(repo, index, d, "package")) for d in dep]
    have = [(d, st) for d, st in have if st["present"]]
    if have:
        L.append("## 它依赖的模块，已有的解读（请引用而不是重复）")
        for d, st in have:
            first = next((ln for ln in st["md"].splitlines()
                          if ln.strip() and not ln.startswith("#")), "")
            L.append(f"- **{d}**：{first.strip()[:160]}")
        L.append("")

    L.append("## 请产出（Markdown，不要 frontmatter，我会自动加）")
    for i, (h, q) in enumerate(_QUESTIONS, 1):
        L.append(f"### {h}")
        L.append(f"> {q}")
        L.append("")
    L.append("要求：读真源码再写，不要从命名猜。说不准的地方直接说不确定，"
             "不要编。能指出具体 file:line 的就指出来。")
    return "\n".join(L)
