"""命令行和 agent 共用的错误：稳定的英文错误码 + 中文说明 + 候选 + 下一步。

库里抛 CodestrataError，命令行（cli/out.py）按错误码给退出码、渲染成文字或 JSON 信封。
老代码抛的 SystemExit（字符串）由命令行兜成 internal，以后逐个换成带码的。
"""
from __future__ import annotations

# 错误码 → 退出码（契约见 docs/design/agent-cli.md）
EXIT = {
    "internal": 1,
    "usage": 2,
    **dict.fromkeys(("repo_unknown", "run_not_found", "phase_not_found", "bad_window", "window_out_of_range",
                     "lane_not_found", "ambiguous_lane", "item_not_found", "ambiguous_item"), 3),
    **dict.fromkeys(("not_scanned", "index_old", "no_events", "recording", "interrupted_run", "failed_run",
                     "not_loadable", "spans_unreadable", "no_loop", "link_mismatch", "need_view"), 4),
    **dict.fromkeys(("no_live_page", "old_serve", "page_failed", "timeout", "interrupted", "superseded",
                     "refused"), 5),
    "pending": 6,
}


class CodestrataError(Exception):
    """code：EXIT 里的错误码；candidates：写错名字时的候选（字符串）；next：[{cmd, effect}] 下一步"""

    def __init__(self, code: str, msg: str, candidates: list[str] | None = None, next: list[dict] | None = None):
        assert code in EXIT, code
        super().__init__(msg)
        self.code, self.msg = code, msg
        self.candidates = list(candidates or [])
        self.next = list(next or [])

    @property
    def exit(self) -> int:
        return EXIT[self.code]
