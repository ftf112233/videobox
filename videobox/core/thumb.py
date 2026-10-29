"""缩略图抽取与缓存。

只抽单帧（首帧后若干秒），不做九宫格——九宫格要真解码数秒素材，
在 18 小时的工时预算里性价比太低，已列入 README 的后续规划。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

THUMB_WIDTH = 480
CACHE_DIR_NAME = "thumbs"


def pick_thumb_time(duration_sec: float) -> float:
    """挑一个既避开片头黑场、又不超出片尾的时间点。

    取 10% 处但封顶 3 秒：短视频停在 10% 可能是黑帧，
    长视频在 3 秒内通常已经过片头。
    """
    if duration_sec <= 0:
        return 0.0
    return round(min(3.0, duration_sec * 0.1), 2)


def cache_key(path: str, mtime: float, at_sec: float) -> str:
    """缓存键由 路径 + 修改时间 + 抽帧点 决定。

    带上 mtime 是为了源文件被替换后缓存自动失效，不用手动清缓存。
    """
    raw = f"{path}|{mtime:.3f}|{at_sec:.2f}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def build_command(
    ffmpeg: str, input_path: str, output_path: str, at_sec: float
) -> list[str]:
    """抽帧命令。

    -ss 放在 -i 之前 = 输入 seek，走关键帧跳转，毫秒级；
    放到 -i 之后 = 输出 seek，逐帧解码才精准，1080p 上要秒级。
    缩略图不需要帧级精准，选快的。
    """
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-ss", f"{at_sec:.2f}",
        "-i", input_path,
        "-frames:v", "1",
        "-q:v", "2",
        "-vf", f"scale={THUMB_WIDTH}:-2",
        output_path,
    ]


def extract(
    ffmpeg: str,
    input_path: str,
    cache_dir: str | Path,
    at_sec: float,
    mtime: float,
) -> str | None:
    """抽一帧存进缓存目录，返回图片路径；失败返回 None。

    失败不该让整个应用崩掉——缩略图只是锦上添花，没有它照样能转码。
    """
    try:
        key = cache_key(input_path, mtime, at_sec)
        out_dir = Path(cache_dir) / CACHE_DIR_NAME
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{key}.jpg"
        if out_path.exists() and out_path.stat().st_size > 0:
            return str(out_path)

        cmd = build_command(ffmpeg, input_path, str(out_path), at_sec)
        kwargs: dict = {"capture_output": True, "timeout": 30}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return str(out_path)
        return None
    except (OSError, subprocess.SubprocessError):
        return None
