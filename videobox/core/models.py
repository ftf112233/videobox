"""领域模型：纯数据，不依赖 Qt、不依赖 ffmpeg。

这一层存在的意义是让 core/ 下的所有逻辑都能被单元测试覆盖，
无需真实视频文件、无需启动 GUI。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class VideoInfo:
    """一个输入视频的可展示信息。"""

    path: str
    duration_sec: float = 0.0
    size_bytes: int = 0
    container: str = ""
    video_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_bitrate_kbps: int = 0
    pix_fmt: str = ""
    audio_codec: str = ""
    audio_channels: int = 0
    audio_sample_rate: int = 0
    audio_bitrate_kbps: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---- 派生属性 ----
    @property
    def has_video(self) -> bool:
        return self.width > 0 and self.height > 0

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)

    @property
    def resolution_label(self) -> str:
        if not self.has_video:
            return "无视频轨"
        return f"{self.width}×{self.height}"

    @property
    def duration_label(self) -> str:
        return format_duration(self.duration_sec)

    @property
    def size_label(self) -> str:
        return format_size(self.size_bytes)

    def summary_line(self) -> str:
        """单行摘要，给 UI 的状态栏用。"""
        parts = [self.container or "未知容器", self.video_codec or "无编码"]
        if self.has_video:
            parts.append(self.resolution_label)
        if self.fps:
            parts.append(f"{self.fps:.2f}fps")
        parts.append(self.duration_label)
        parts.append(self.size_label)
        return " · ".join(p for p in parts if p)


def format_duration(seconds: float) -> str:
    """秒 → HH:MM:SS / MM:SS。非法值返回 '--:--'。"""
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_size(num_bytes: int) -> str:
    """字节 → 人类可读。1 位小数，单位自动进位。"""
    if num_bytes is None or num_bytes < 0:
        return "—"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


# 允许的目标缩放档位。超出这个集合的值一律视为非法（LLM 可能胡编）。
SCALE_TARGETS: dict[str, int | None] = {
    "原画": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}

# 容器白名单
CONTAINERS = ("mp4", "mkv", "mov", "webm")

# 编码器偏好（auto 由 params 层实测后决定）
CODEC_PREFS = ("auto", "h264_nvenc", "libx264")


@dataclass
class TranscodePlan:
    """一次转码的完整参数意图。

    由 AI 顾问产出，或由本地规则引擎产出，或用户手动调整。
    两种来源共用同一 schema —— 这是"无 Key 时功能仍完整"的技术前提。
    """

    preset_name: str = "自定义"
    container: str = "mp4"
    # auto 表示"让 params 层按实测结果挑"，其余为强制指定
    video_codec: str = "auto"
    # cq（NVENC 恒定质量）/ crf（x264 恒定质量）
    quality_mode: str = "crf"
    quality_value: int = 26
    scale: str = "原画"
    fps: str = "keep"
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 128
    target_size_mb: float | None = None

    reasons: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    # "ai" | "local_rules" | "manual"
    source: str = "local_rules"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def scale_height(self) -> int | None:
        return SCALE_TARGETS.get(self.scale)

    @property
    def source_label(self) -> str:
        return {
            "ai": "AI 顾问",
            "local_rules": "本地规则",
            "manual": "手动调整",
        }.get(self.source, self.source)


@dataclass
class TranscodeResult:
    """一次转码结束后的结果，用于前后对比。"""

    ok: bool
    output_path: str = ""
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    elapsed_sec: float = 0.0
    speed: float = 0.0
    used_codec: str = ""
    error_message: str = ""
    cancelled: bool = False

    @property
    def size_delta_label(self) -> str:
        if not self.input_size_bytes or not self.output_size_bytes:
            return "—"
        ratio = self.output_size_bytes / self.input_size_bytes
        pct = (1 - ratio) * 100
        arrow = "↓" if pct >= 0 else "↑"
        return f"{arrow} {abs(pct):.1f}%"


@dataclass
class ProgressUpdate:
    """ffmpeg -progress 解析后的一次进度快照。"""

    percent: float = 0.0          # 0.0 ~ 1.0
    out_time_sec: float = 0.0
    speed: float = 0.0            # 1.2 表示 1.2x
    eta_sec: float | None = None
    done: bool = False
