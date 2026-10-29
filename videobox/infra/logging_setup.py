"""日志落盘。

打包成 --noconsole 之后，异常不会弹任何窗口，
没有日志文件的话排查问题等于盲人摸象。所以这里负责把日志写进
%APPDATA%\\VideoBox\\logs\\app.log，并在界面上提供"打开日志目录"。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "VideoBox"


def app_data_dir() -> Path:
    """Windows 走 APPDATA，其它平台走 XDG 约定。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging(level: int = logging.INFO) -> Path:
    """配置根 logger，返回日志文件路径。重复调用无副作用。"""
    log_file = log_dir() / "app.log"
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return log_file

    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 有控制台时同时输出，方便开发期看
    if sys.stderr is not None and sys.stderr.isatty():
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    return log_file
