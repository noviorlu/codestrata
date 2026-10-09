"""codestrata 的配置目录：$XDG_CONFIG_HOME/codestrata（默认 ~/.config/codestrata）。
主菜单的项目清单在这里；命令行按它找已知的仓库。单独一个轻模块：命令行查仓库时不用把主菜单那一套 import 进来。"""
from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "codestrata"


def known_repos() -> list[Path]:
    """主菜单打开过的仓库（projects.json），最近打开的在前；读不出来是空的"""
    try:
        d = json.loads((config_dir() / "projects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(p["path"]) for p in d.get("projects") or [] if isinstance(p, dict) and p.get("path")]
