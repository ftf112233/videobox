"""把 TranscodePlan 翻译成 ffmpeg 参数列表。

这一层是纯函数，不碰进程，因此可以拿 golden string 做单测。
所有"LLM 可能会瞎编"的风险都在这里收敛：非法值一律回落到安全默认。
"""

from __future__ import annotations

from .models import CONTAINERS, SCALE_TARGETS, TranscodePlan, VideoInfo

# 质量区间。低于 18 画质收益极小但体积暴涨；高于 35 肉眼可见糊。
QUALITY_MIN = 18
QUALITY_MAX = 35

# NVENC 与 x264 的质量刻度不同，但共用一套 clamp 区间已足够安全
NVENC_PRESET = "p4"
X264_PRESET = "veryfast"

CODEC_LABEL = {
    "h264_nvenc": "NVIDIA 硬件编码 (NVENC)",
    "libx264": "CPU 软件编码 (libx264)",
}

# mp4/mov 需要 faststart 才能边下边播
_FASTSTART_CONTAINERS = ("mp4", "mov")


def clamp_quality(value: int) -> int:
    return max(QUALITY_MIN, min(QUALITY_MAX, int(value)))


def choose_codec(pref: str, available: list[str]) -> str:
    """按用户偏好挑编码器，拿不到就退到软编。

    available 来自实测（不是 `ffmpeg -encoders` 的列表），
    因为"列出来有"不等于"这台机器真能跑"。
    """
    available = available or []
    if pref in ("h264_nvenc", "libx264") and pref in available:
        return pref
    if "h264_nvenc" in available:
        return "h264_nvenc"
    return "libx264"


def estimate_bitrate_kbps(target_mb: float, duration_sec: float, audio_kbps: int) -> int:
    """按目标体积反推视频码率。体积不可达时返回 0，由调用方退回质量模式。"""
    if target_mb <= 0 or duration_sec <= 0:
        return 0
    total_kbits = target_mb * 8 * 1024
    total_kbps = total_kbits / duration_sec
    video_kbps = total_kbps - audio_kbps
    return int(max(0, video_kbps))


def resolve_scale(plan: TranscodePlan, info: VideoInfo) -> int | None:
    """算出目标高度。只降不升——把 480p 放大到 1080p 纯属浪费体积。"""
    target = SCALE_TARGETS.get(plan.scale)
    if target is None:
        return None
    if info.height and target >= info.height:
        return None
    return target


def build_video_args(
    plan: TranscodePlan, info: VideoInfo, codec: str, bitrate_kbps: int = 0
) -> list[str]:
    """视频流参数。"""
    args = ["-c:v", codec]
    q = clamp_quality(plan.quality_value)

    if bitrate_kbps > 0:
        # 有明确体积目标时走码率模式。
        # 只给 -b:v 是不够的：x264/NVENC 的 ABR 在短视频上还没收敛就结束了，
        # 实测 5 秒素材目标 20MB 却出了 38MB。加 maxrate + bufsize 把峰值钉住，
        # 体积才靠得住。
        maxrate = int(bitrate_kbps * 1.2)
        bufsize = int(bitrate_kbps * 2)
        args += [
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{maxrate}k",
            "-bufsize", f"{bufsize}k",
        ]
        if codec == "h264_nvenc":
            args += ["-preset", NVENC_PRESET, "-rc", "vbr"]
        else:
            args += ["-preset", X264_PRESET]
    else:
        if codec == "h264_nvenc":
            # -b:v 0 必须给，否则 NVENC 会落到固定码率模式，体积失控
            args += ["-preset", NVENC_PRESET, "-rc", "vbr", "-cq", str(q), "-b:v", "0"]
        else:
            args += ["-preset", X264_PRESET, "-crf", str(q)]

    if (height := resolve_scale(plan, info)) is not None:
        # -2 保证宽度按比例取偶数，h264 要求偶数尺寸
        args += ["-vf", f"scale=-2:{height}"]

    if plan.fps and plan.fps not in ("keep", "原帧率", ""):
        try:
            fps_value = float(plan.fps)
            if 1 <= fps_value <= 120:
                args += ["-r", f"{fps_value:g}"]
        except (TypeError, ValueError):
            pass  # 非法 fps 就保持原样，不报错也不乱改

    # 10bit 源默认会输出 yuv420p10le，微信/浏览器放不出来，必须显式压回 8bit
    args += ["-pix_fmt", "yuv420p"]
    return args


def build_audio_args(plan: TranscodePlan, info: VideoInfo) -> list[str]:
    """音频流参数。没有音轨就明确 -an，别让 ffmpeg 自己猜。"""
    if not info.has_audio:
        return ["-an"]
    audio_kbps = max(32, min(320, int(plan.audio_bitrate_kbps or 128)))
    return ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]


def build_args(
    plan: TranscodePlan,
    info: VideoInfo,
    input_path: str,
    output_path: str,
    available_codecs: list[str] | None = None,
) -> list[str]:
    """组装完整的 ffmpeg 命令行（不含 ffmpeg 可执行文件本身）。"""
    container = plan.container if plan.container in CONTAINERS else "mp4"
    codec = choose_codec(plan.video_codec, available_codecs or ["libx264"])
    audio_kbps = max(32, min(320, int(plan.audio_bitrate_kbps or 128)))

    bitrate = 0
    if plan.target_size_mb:
        target_bytes = plan.target_size_mb * 1024 * 1024
        # 目标体积比源文件还大时，"压缩"变成了"注水"——只会让文件白白变大。
        # 这种情况退回质量模式，至少画质不会倒退。
        if not info.size_bytes or target_bytes < info.size_bytes:
            bitrate = estimate_bitrate_kbps(
                plan.target_size_mb, info.duration_sec, audio_kbps
            )

    args = [
        "-y",
        "-hide_banner",
        "-progress", "pipe:1",   # 进度从 stdout 走，好解析
        "-nostats",
        "-loglevel", "error",
        "-i", input_path,
    ]
    args += build_video_args(plan, info, codec, bitrate)
    args += build_audio_args(plan, info)
    if container in _FASTSTART_CONTAINERS:
        args += ["-movflags", "+faststart"]
    args.append(output_path)
    return args


def build_preview_command(
    plan: TranscodePlan,
    info: VideoInfo,
    input_path: str,
    output_path: str,
    available_codecs: list[str] | None = None,
) -> str:
    """给 UI 展示用的一行命令，让用户知道程序到底在干什么。"""
    args = build_args(plan, info, input_path, output_path, available_codecs)
    quoted = []
    for a in args:
        quoted.append(f'"{a}"' if " " in a else a)
    return "ffmpeg " + " ".join(quoted)
