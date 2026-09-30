"""静态站点导出：graph --link github --out 目录。源码不内嵌，页面运行时按扫描时的提交号从 GitHub 取。

单文件导出要把源码塞进 HTML，受单文件宿主的体积上限所限（artifact 这类 16 MB）：vllm-omni 1600 多个
文件只装得下两百多个。而扫的仓库基本都在 GitHub 上——源码不必自己带：jsDelivr 和
raw.githubusercontent.com 都允许跨域取，按提交号钉住的地址内容不会变。codestrata 自己算出来的东西
（依赖图、边的调用明细、Ctrl+点击的跳转、引用倒排、解读、runtime）放在旁边的 data/ 里按需加载，
于是也没有体积上限了，GitHub Pages 这种静态站点直接放。

    <out>/index.html                  页面：图、解读、run 这些小的内嵌；EMB.link 说从哪取源码、数据在哪
    <out>/data/<版本>/edges.json       边详情（第一次点边时取）
    <out>/data/<版本>/search.json      搜索索引（第一次搜时取）
    <out>/data/<版本>/f/<序号>.json     每个文件：语言、行数（取回来的源码按它核对）、大纲、Ctrl+点击的 token 和目标
    <out>/data/<版本>/refs/<桶>.json   引用倒排：目标串 → 定义位置 + [[文件序号, 行, 列, 种类], …]，按 FNV-1a 分桶；
                                     没被引用的定义也在（r 为空），好让引用栏照样给出「定义」那一行
    <out>/data/<版本>/attrs/<桶>.json  「同名的 .xxx」：成员名 → 仓库里同名成员有几个 + 用到它的地方
    <out>/data/<版本>/src/<序号>.txt    本地版本：GitHub 上那个提交里没有、或内容不一样的文件（没进 git、
                                     改了没提交、skip-worktree、软链接），随页面带上；--public 时被 .gitignore
                                     忽略的不带（可能是本地配置、密钥）
    <out>/.codestrata-site            标记：再导出到同一个目录时，只清理带着它的目录

<版本> 是提交号前缀加上这次数据的哈希：再部署之后，还开着的旧页面取到的是 404（提示刷新），不会拿
新数据的序号去对旧页面的文件表、悄悄显示成别的文件。

序号是文件在 EMB.link.files 里的下标。不用路径做文件名：Hexo 会丢掉 source/ 下以 _ 开头的文件
（__init__.py 的数据块会在部署时悄悄没了），路径里的特殊字符也省得转义。

钉版本：地址里是提交号，不是分支名——行号、Ctrl+点击的列号都是扫描时的，只对得上扫描时的内容。
页面取回源码后按行数核对，对不上就不给 Ctrl+点击并说明。
"""
from __future__ import annotations

import html as _html
import json
import math
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import highlight as _hl
from . import payload as _payload
from . import render as _render

MARK = ".codestrata-site"
CODE_BASES = ("https://cdn.jsdelivr.net/gh/{owner}/{name}@{sha}/{path}",
              "https://raw.githubusercontent.com/{owner}/{name}/{sha}/{path}")
BLOB = "https://github.com/{owner}/{name}/blob/{sha}/{path}"
_GH_RE = re.compile(r"^(?:https?://(?:[^@/]+@)?|ssh://git@|git@)github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
BUCKET_BYTES = 200_000                      # 引用倒排每个桶大约多大（一次点击取一个桶）


def fnv1a(s: str) -> int:
    """32 位 FNV-1a（UTF-8 字节）：前端用同一个算法算桶号（Math.imul）。"""
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _git(top: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(top), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"--link github：git {' '.join(args)} 失败：{r.stderr.strip()[:200]}")
    return r.stdout


def github_origin(repo: Path) -> dict:
    """仓库的 GitHub 来源：{owner, name, sha, prefix, tracked, dirty}。prefix 是扫描的目录在 git 仓库里的
    相对路径（扫的是子目录时源码地址要带上它）；tracked / dirty 是相对扫描目录的路径集合。"""
    repo = Path(repo).resolve()
    top = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    url = _git(top, "remote", "get-url", "origin").strip()
    m = _GH_RE.match(url)
    if not m:
        raise SystemExit(f"--link github：origin 不是 github.com 上的仓库（{url}）；用不带 --link 的单文件导出")
    sha = _git(top, "rev-parse", "HEAD").strip()
    prefix = repo.relative_to(top).as_posix() if repo != top else ""
    pre = prefix + "/" if prefix else ""

    def rel(p: str) -> str | None:
        return p[len(pre):] if p.startswith(pre) else None
    staged: dict[str, tuple[str, str]] = {}           # 相对扫描目录的路径 → (文件模式, HEAD 里的 blob)
    for e in _git(top, "ls-files", "-s", "-z").split("\0"):
        if not e:
            continue
        head, _, path = e.partition("\t")
        mode, blob = head.split()[:2]
        if (r := rel(path)) is not None:
            staged[r] = (mode, blob)
    tracked = set(staged)
    ignored = {r for p in _git(top, "ls-files", "-z", "-o", "-i", "--exclude-standard").split("\0")
               if p and (r := rel(p)) is not None}
    dirty = set()
    ent = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    i = 0
    while i < len(ent):
        e = ent[i]
        i += 1
        if len(e) < 4:
            continue
        if e[0] in "RC":                             # 改名 / 复制：-z 下原路径跟在后面
            i += 1
        r = rel(e[3:])
        if r is not None:
            dirty.add(r)
    return {"owner": m.group(1), "name": m.group(2), "sha": sha, "prefix": prefix, "top": top,
            "tracked": tracked, "staged": staged, "dirty": dirty, "ignored": ignored}


def _differs(info: dict, rels: list[str]) -> set[str]:
    """内容和 HEAD 里的 blob 不一样的已跟踪文件——git status 看不出来的也算：skip-worktree /
    assume-unchanged 的本地改动、软链接（GitHub 上给的是链接指向的路径，不是源码）。"""
    pre = info["prefix"] + "/" if info["prefix"] else ""
    cand = [r for r in rels if r in info["staged"]]
    out = {r for r in cand if info["staged"][r][0] == "120000"}
    todo = [r for r in cand if r not in out]
    if todo:
        r = subprocess.run(["git", "-C", str(info["top"]), "hash-object", "--no-filters", "--stdin-paths"],
                           input="\n".join(pre + x for x in todo) + "\n", capture_output=True, text=True)
        if r.returncode == 0:
            for x, h in zip(todo, r.stdout.split()):
                if h != info["staged"][x][1]:
                    out.add(x)
    return out


def _url(tpl: str, info: dict, rel: str) -> str:
    from urllib.parse import quote
    path = "/".join(quote(p) for p in ((info["prefix"] + "/" if info["prefix"] else "") + rel).split("/"))
    return tpl.format(owner=info["owner"], name=info["name"], sha=info["sha"], path=path)


def _reachable(info: dict, rel: str, bases) -> tuple[bool | None, str]:
    """导出时试取一个文件：提交号在 GitHub 上找不到（没推上去）就不导出——页面上会全是 404。
    没网（取不到任何回应）返回 None：照样导出，只提醒。"""
    msgs, all404 = [], True
    for tpl in bases:
        u = _url(tpl, info, rel)
        if not u.startswith(("http://", "https://")):
            all404 = False                           # 相对地址（测试时指到站点自己的镜像）：导出时试不了
            continue
        try:
            req = urllib.request.Request(u, method="GET", headers={"User-Agent": "codestrata", "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=15):
                return True, u
        except urllib.error.HTTPError as e:
            msgs.append(f"{u} → {e.code}")
            if e.code == 416:                        # 范围不对，但文件在
                return True, u
            if e.code != 404:
                all404 = False
        except Exception as e:  # noqa: BLE001
            msgs.append(f"{u} → {type(e).__name__}")
            all404 = False
    return (False if all404 and msgs else None), "；".join(msgs)


def _file_meta(repo: Path, idx: dict, rel: str, syms_of: dict, pkg: str | None) -> dict | None:
    """一个文件要带的（不带源码）：和 file_view 同形，只是 lines 由页面取回源码后自己高亮。"""
    p = repo / rel
    try:
        text = p.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None
    lang = _hl.detect(rel, text)
    if lang in ("python", "triton"):
        syms, kind = syms_of.get(rel, []), "ast"
    else:
        syms = [{"key": "", "n": o["n"], "k": o["k"], "l": o["l"]} for o in _hl.outline(text, lang)]
        kind = "lexer"
    # 行数按扫描器的口径（read_text 的通用换行：\r\n、\r 都算换行）。浏览器只按 \n 切：有单独 \r 的文件
    # 两边对不上，页面会说「和扫描时不一样」、不给跳转——否则 \r 之后的行号全错一行
    n = text.replace("\r\n", "\n").replace("\r", "\n").count("\n") + 1
    return {"file": rel, "pkg": pkg, "lang": lang, "lang_label": _hl.LABEL.get(lang, lang),
            "n_lines": n, "symbols": syms, "outline_kind": kind,
            "xref": _payload.xref_for(repo, rel), "_text": text}


def _check_out(out: Path) -> None:
    """导出之前先看输出目录：不是 codestrata 导出的目录（没有标记）而又不是空的，拒绝，免得删错。
    在最前面做（大仓库算一遍要几分钟，不能算完才说目录不对）。"""
    if out.exists() and not out.is_dir():
        raise SystemExit(f"--out {out} 不是目录")
    if out.exists() and any(out.iterdir()) and not (out / MARK).exists():
        raise SystemExit(f"--out {out} 不是空目录，也不是 codestrata 导出过的（没有 {MARK}）：换一个目录，或者先清空它")


def _clear(out: Path) -> None:
    """再导出前清掉上一次的产物。标记先写上：这次中途断了，下次还认得出是自己的目录。"""
    _check_out(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARK).write_text("codestrata graph --link github 的产物；再导出到这里时整个 data/ 会被换掉\n", encoding="utf-8")
    shutil.rmtree(out / "data", ignore_errors=True)
    (out / "index.html").unlink(missing_ok=True)


def export_site(repo: Path, idx: dict, out: Path, *, hot=None, hot_meta=None, others=None, compare=False,
                per_pkg: int = 10, public: bool = False, home: str = "", keep: list[str] | None = None,
                code_bases: list[str] | None = None, check_remote: bool = True, title: str = "") -> dict:
    """导出成一个目录（index.html + data/<版本>/）。返回摘要（给命令行打印）。"""
    repo = Path(repo).resolve()
    out = Path(out)
    _check_out(out)
    info = github_origin(repo)
    bases = list(code_bases or CODE_BASES)
    pl = _payload.export_payload(repo, idx, hot=hot, hot_meta=hot_meta, per_pkg=per_pkg,
                                 others=others, compare=compare, code=False)
    cand = sorted(set(idx.get("files") or {}) | set(idx.get("aux") or {})
                  | {d["f"] for ds in (idx.get("docs") or {}).values() for d in ds})

    # 每个文件：读不出来的（scan 之后删了）不进文件表——页面上就不会以为它能打开
    syms_of: dict[str, list] = {}
    for k, sy in (idx.get("symbols") or {}).items():
        syms_of.setdefault(sy["f"], []).append({"key": k, "n": sy["n"], "k": sy["k"], "l": sy["l"]})
    for v in syms_of.values():
        v.sort(key=lambda d: d["l"])
    metas: dict[str, dict] = {}
    for rel in cand:
        meta = _file_meta(repo, idx, rel, syms_of, _payload.known_file(idx, rel))
        if meta is not None:
            metas[rel] = meta
    every = [r for r in cand if r in metas]
    at = {r: i for i, r in enumerate(every)}

    # 本地版本：GitHub 上那个提交里没有、或内容不一样的。--public 时被 .gitignore 忽略的不发出去
    differs = _differs(info, every)
    local = [r for r in every if r not in info["tracked"] or r in info["dirty"] or r in differs]
    held = [r for r in local if public and r in info["ignored"]]
    reach, probe_msg = None, "skipped"
    if check_remote:
        lset = set(local)
        probe = next((r for r in every if r not in lset and (repo / r).stat().st_size > 0), None)
        if probe:
            reach, probe_msg = _reachable(info, probe, bases)
            if reach is False:
                raise SystemExit(f"--link github：GitHub 上取不到提交 {info['sha'][:12]} 的文件（{probe_msg}）——"
                                 "这个提交推上去了吗？没推的提交页面上会全是 404")
    if public:
        pl = _payload.publicize(pl, home, keep or [])
    edges, search = pl.pop("edges", {}), pl.pop("search", None)

    X = _payload.load_xref(repo)
    files_out: dict[int, dict] = {}
    src_out: dict[int, str] = {}
    stale: list[int] = []
    for rel in every:
        meta = metas[rel]
        text = meta.pop("_text")
        if (meta.get("xref") or {}).get("stale"):
            stale.append(at[rel])
        if rel in local:
            meta["local"] = True
            if rel in held:
                meta["unpublished"] = True           # 公开页不带：被 .gitignore 忽略的本地文件
            else:
                src_out[at[rel]] = text
        files_out[at[rel]] = meta

    # 引用倒排（和 serve 的 /api/refs 同一份数据：xref.invert）；没被引用的定义也带上，引用栏要给「定义」
    refs_b: dict = {}
    attrs_b: dict = {}
    nb = na = 0
    if X:
        inv = _payload.xref_inverted(X)
        tg, wh = X["x"]["targets"], X["x"]["where"]
        rows = {}
        for tid, t in enumerate(tg):
            lst = inv.get(tid)
            if lst or wh[tid]:
                rows[t] = {"w": wh[tid], "r": [[at.get(f, f), l, c, k] for f, l, c, k in lst or []]}
        if rows:
            nb = max(1, math.ceil(len(json.dumps(rows, ensure_ascii=False)) / BUCKET_BYTES))
            refs_b = {b: {} for b in range(nb)}      # 空桶也写：页面按桶号取，不能 404
            for t, v in rows.items():
                refs_b[fnv1a(t) % nb][t] = v
        same: dict[str, int] = {}
        for t in tg:
            qual = t.partition(":")[2].partition(":")[2]
            if t[:1] in "sv" and "." in qual:
                n = t.rsplit(".", 1)[-1]
                same[n] = same.get(n, 0) + 1
        attrs = {n: {"same": same.get(n, 0), "r": [[at.get(f, f), l, c, e, k] for f, l, c, e, k in lst]}
                 for n, lst in (X["x"].get("attrs") or {}).items()}
        if attrs:
            na = max(1, math.ceil(len(json.dumps(attrs, ensure_ascii=False)) / BUCKET_BYTES))
            attrs_b = {b: {} for b in range(na)}
            for n, v in attrs.items():
                attrs_b[fnv1a(n) % na][n] = v

    # 公开导出：本地带上的源码里若有主目录也要换（xref 的列号跟着挪）。转成 HTML 转义的行交给
    # publicize——它按「去掉标签、反转义」算列号，纯文本里的 < 不能被当成标签
    if public and src_out:
        for i in list(src_out):
            lines = src_out[i].split("\n")
            if not any(home and home in ln for ln in lines):
                continue
            fake = {"files": {"x": {"lines": [_html.escape(ln, quote=False) for ln in lines],
                                    "xref": {"toks": ((files_out[i].get("xref") or {}).get("toks") or [])}}}}
            fx = _payload.publicize(fake, home, keep or [])["files"]["x"]
            src_out[i] = "\n".join(_html.unescape(ln) for ln in fx["lines"])
            if files_out[i].get("xref"):
                files_out[i]["xref"] = {**files_out[i]["xref"], "toks": fx["xref"]["toks"]}

    # 版本：提交号前缀 + 这次数据的哈希（同样的输入导出两次得到同一个目录名）
    digest = fnv1a(json.dumps([info["sha"], every, sorted(src_out), json.dumps(pl, ensure_ascii=False, sort_keys=True)[:2_000_000]],
                              ensure_ascii=False))
    ver = f"{info['sha'][:10]}-{digest:08x}"
    pl["link"] = {"provider": "github", "owner": info["owner"], "name": info["name"], "sha": info["sha"],
                  "prefix": info["prefix"], "code": bases, "blob": BLOB, "data": f"data/{ver}/",
                  "files": every, "local": [at[r] for r in local if at[r] in src_out],
                  "unpublished": [at[r] for r in held], "stale": stale,
                  "refBuckets": nb, "attrBuckets": na}

    _clear(out)
    d = out / "data" / ver
    written: list[Path] = []

    def put(rel_path: str, obj=None, text: str | None = None):
        p = d / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if text is not None else json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
        written.append(p)
    put("edges.json", edges)
    put("search.json", search)
    for i, meta in files_out.items():
        put(f"f/{i}.json", meta)
    for i, text in src_out.items():
        put(f"src/{i}.txt", text=text)
    for b, v in refs_b.items():
        put(f"refs/{b}.json", v)
    for b, v in attrs_b.items():
        put(f"attrs/{b}.json", v)
    html = _render.export(pl, title=title or f"{idx['repo']['name']} · codestrata")
    (out / "index.html").write_text(html, encoding="utf-8")
    written.append(out / "index.html")
    if public and home and home != "/":              # 最后兜一道：所有写出去的文件里都不能有主目录
        home_re = re.compile(re.escape(home.rstrip("/")) + r"(?![\w-]|\.[\w-])")
        for p in written:
            if home_re.search(p.read_text(encoding="utf-8", errors="replace")):
                shutil.rmtree(out / "data", ignore_errors=True)
                (out / "index.html").unlink(missing_ok=True)
                raise SystemExit(f"--public：{p.relative_to(out)} 里还有主目录 {home}，已删掉导出结果，没有写出")
    return {"out": out, "files": len(files_out), "local": sorted(r for r in local if at[r] in src_out),
            "held": held, "refBuckets": nb, "attrBuckets": na, "ver": ver,
            "index_bytes": len(html.encode("utf-8")),
            "data_bytes": sum(p.stat().st_size for p in written) - len(html.encode("utf-8")),
            "reach": reach, "probe": probe_msg, "info": info, "bases": bases}
