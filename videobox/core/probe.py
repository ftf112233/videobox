"""视频信息探测。

两条路：
1. ffprobe -print_format json —— 首选，结构化、字段全
2. ffmpeg -i 的 stderr —— 兜底，某些精简构建不带 ffprobe

解析函数（parse_*）是纯函数，全部可单测；probe() 才真的起进程。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .models import VideoInfo

# Windows 下双击 exe 不要弹黑色控制台
CREATE_NO_WINDOW = 0x08000000


def _run_kwargs() -> dict:
    """跨平台的"别弹窗"参数。"""
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


def _safe_float(value) -> float:
    try:
        f = float(value)
        return f if f == f else 0.0  # 过滤 NaN
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_fraction(text: str) -> float:
    """'30000/1001' → 29.97；'30' → 30.0；'0/0' → 0.0"""
    if not text:
        return 0.0
    text = str(text).strip()
    if "/" in text:
        num, _, den = text.partition("/")
        d = _safe_float(den)
        return _safe_float(num) / d if d else 0.0
    return _safe_float(text)


def parse_clock(text: str) -> float:
    """'00:01:23.45' → 83.45；'N/A' → 0.0"""
    if not text:
        return 0.0
    text = str(text).strip()
    if not text or text.upper().startswith("N/A"):
        return 0.0
    parts = text.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return 0.0
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def parse_ffprobe_json(payload: str, path: str = "", size_bytes: int = 0) -> VideoInfo:
    """解析 ffprobe -print_format json 的输出。字段缺失时全部降级为 0/空串。"""
    data = json.loads(payload)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

    duration = _safe_float(fmt.get("duration")) or _safe_float(video.get("duration"))
    # 部分流式封装（如某些 mkv）format.duration 缺失，退回用码率/大小估算
    if not duration and _safe_int(fmt.get("bit_rate")) and _safe_int(fmt.get("size")):
        duration = _safe_int(fmt["size"]) * 8 / _safe_int(fmt["bit_rate"])

    fps = parse_fraction(video.get("avg_frame_rate", "")) or parse_fraction(
        video.get("r_frame_rate", "")
    )

    return VideoInfo(
        path=path or fmt.get("filename", ""),
        duration_sec=duration,
        size_bytes=_safe_int(fmt.get("size")) or size_bytes,
        container=(fmt.get("format_name", "") or "").split(",")[0],
        video_codec=video.get("codec_name", "") or "",
        width=_safe_int(video.get("width")),
        height=_safe_int(video.get("height")),
        fps=fps,
        video_bitrate_kbps=_safe_int(video.get("bit_rate")) // 1000,
        pix_fmt=video.get("pix_fmt", "") or "",
        audio_codec=audio.get("codec_name", "") or "",
        audio_channels=_safe_int(audio.get("channels")),
        audio_sample_rate=_safe_int(audio.get("sample_rate")),
        audio_bitrate_kbps=_safe_int(audio.get("bit_rate")) // 1000,
        raw=data,
    )


_RE_DURATION = re.compile(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)")
_RE_BITRATE = re.compile(r"bitrate:\s*(\d+)\s*kb/s")
_RE_VIDEO = re.compile(
    r"Stream #\d+:\d+.*?: Video:\s*([A-Za-z0-9_\-]+).*?(\d{2,5})x(\d{2,5})"
)
_RE_FPS = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_RE_AUDIO = re.compile(
    r"Stream #\d+:\d+.*?: Audio:\s*([A-Za-z0-9_\-]+).*?(\d{4,6})\s*Hz"
)
_RE_AUDIO_BR = re.compile(r"Audio:.*?(\d+)\s*kb/s")


def parse_ffmpeg_stderr(stderr_text: str, path: str = "", size_bytes: int = 0) -> VideoInfo:
    """从 `ffmpeg -i xxx` 的 stderr 里抠信息。

    注意：ffmpeg 找不到输出文件时会以非 0 退出，这是预期行为，
    调用方不要把它当失败处理。
    """
    text = stderr_text or ""

    duration = 0.0
    if m := _RE_DURATION.search(text):
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    width = height = 0
    video_codec = ""
    if m := _RE_VIDEO.search(text):
        video_codec = m.group(1)
        width, height = int(m.group(2)), int(m.group(3))

    fps = 0.0
    if width and (m := _RE_FPS.search(text)):
        fps = _safe_float(m.group(1))

    audio_codec = ""
    sample_rate = 0
    if m := _RE_AUDIO.search(text):
        audio_codec = m.group(1)
        sample_rate = int(m.group(2))

    audio_br = 0
    if audio_codec and (m := _RE_AUDIO_BR.search(text)):
        audio_br = int(m.group(1))

    container = ""
    if m := re.search(r"Input #0,\s*([^,]+),", text):
        container = m.group(1).strip().split(",")[0]

    total_br = 0
    if m := _RE_BITRATE.search(text):
        total_br = int(m.group(1))

    return VideoInfo(
        path=path,
        duration_sec=duration,
        size_bytes=size_bytes,
        container=container,
        video_codec=video_codec,
        width=width,
        height=height,
        fps=fps,
        video_bitrate_kbps=total_br,
        audio_codec=audio_codec,
        audio_sample_rate=sample_rate,
        audio_bitrate_kbps=audio_br,
    )


def probe(path: str | Path, ffprobe: str | None, ffmpeg: str | None) -> VideoInfo:
    """真的去问 ffmpeg。ffprobe 优先，失败或不可用时退回 ffmpeg -i。"""
    path = str(path)
    file_size = 0
    try:
        file_size = Path(path).stat().st_size
    except OSError:
        pass

    if ffprobe:
        cmd = [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=30, **_run_kwargs()
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return parse_ffprobe_json(
                    proc.stdout.decode("utf-8", errors="replace"),
                    path=path,
                    size_bytes=file_size,
                )
        except (OSError, subprocess.SubprocessError):
            pass  # 落到下面的兜底

    if not ffmpeg:
        raise RuntimeError("既没有可用的 ffprobe，也没有 ffmpeg，无法读取视频信息")

    # 兜底：ffmpeg -i 不给输出参数，会打印头信息后报错退出，几乎零耗时
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, timeout=30, **_run_kwargs(),
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    # Windows 上 ffmpeg 的中文输出常是 GBK，UTF-8 解不出来时再试一次
    if "\ufffd" in stderr:
        try:
            stderr = proc.stderr.decode("gbk", errors="replace")
        except LookupError:
            pass
    info = parse_ffmpeg_stderr(stderr, path=path, size_bytes=file_size)
    if not info.has_video and not info.has_audio and info.duration_sec == 0:
        raise RuntimeError(f"无法识别的媒体文件：{Path(path).name}")
    return info
