"""单文件导出：把 codestrata/web/ 的前端和数据内联成一个 HTML。

和 `codestrata serve` 用的是**同一套前端文件**，唯一的差别是数据源：
serve 时前端 fetch /api/*；导出时前端读内嵌的 window.CS_EMBEDDED。
切换由 web/ds.js 完成，UI 代码本身不感知。

导出的文件只读、离线、可以直接发给别人；要展开 / 收起、跳编辑器、看时间顺序，用 serve。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
# 顺序即依赖顺序：ds 被所有人用，app 最后启动
SCRIPTS = ("ds.js", "graph.js", "findbar.js", "viewer.js", "panel.js", "search.js", "timebar.js", "app.js")


def export(payload: dict, *, title: str | None = None, fragment: bool = False) -> str:
    """fragment=True 时去掉 doctype/meta 外壳，给需要自己包外壳的宿主（比如 artifact）用。"""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "app.css").read_text(encoding="utf-8")
    js = "\n".join(f"/* ---- {n} ---- */\n" + (WEB / n).read_text(encoding="utf-8")
                   for n in SCRIPTS)
    # hl.js：浏览器里高亮。源码从 GitHub 取的导出（site.py）靠它高亮全文；所有模式下边详情里的代码片段
    # （from 调用那一行、to 签名）也靠它——payload 只带纯文本，导出不会因为片段变大。
    # 单独一个 <script>：它用了正则的后行断言，老浏览器（Safari 16.4 之前）解析不了会整段报错——
    # 和别的放在一起就整页都没了；分开的话只是没高亮（退回纯文本）
    hl = f"<script>\n/* ---- hl.js ---- */\n{(WEB / 'hl.js').read_text(encoding='utf-8')}\n</script>\n"
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    html = html.replace('<link rel="stylesheet" href="app.css">', f"<style>\n{css}\n</style>")
    html = re.sub(r'\s*<script src="[^"]+"></script>', "", html)
    html = html.replace("</div>\n\n", "</div>\n\n", 1)
    boot = (f"<script>window.CS_EMBEDDED = {data};</script>\n" + hl
            + f"<script>\n{js}\n</script>\n")
    html = html.rstrip() + "\n" + boot
    if title:
        html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1)
    if fragment:
        html = re.sub(r"^<!doctype html>\s*", "", html)
        html = re.sub(r'<meta charset="utf-8">\s*', "", html)
        html = re.sub(r'<meta name="viewport"[^>]*>\s*', "", html)
    return html
