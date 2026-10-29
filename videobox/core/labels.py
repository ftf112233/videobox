"""人话层：把工程参数翻译成用户能判断的说法。

这个模块存在的唯一理由，是让界面上尽量不出现裸数字和裸枚举值。
CRF 26、96 kbps、yuv420p 对做视频的人有意义，对"想把视频发到朋友圈"的人
只是噪音——他既不知道 26 算好还是差，也不知道 96 该不该调。

档位化还有一层好处：把 18~35 的连续值收成 4 个语义档，用户的选择成本从
"要不要调"变成"选哪一个"，而这两者他都能判断。

纯函数、零依赖，可以直接单测。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 画质
# (档位名, CRF 值)。CRF 越小画质越好、体积越大。
QUALITY_LEVELS: tuple[tuple[str, int], ...] = (
    ("极佳", 20),
    ("高", 23),
    ("标准", 26),
    ("省体积", 30),
)

QUALITY_LABELS: list[str] = [name for name, _ in QUALITY_LEVELS]
_QUALITY_BY_LABEL = {name: value for name, value in QUALITY_LEVELS}

QUALITY_TOOLTIP = (
    "「极佳」几乎看不出和原片的差别，体积最大；\n"
    "「省体积」细节会变软，但文件明显更小。\n"
    "拿不定就用「标准」。"
)

# ---------------------------------------------------------------- 音质
# (档位名, kbps)
AUDIO_LEVELS: tuple[tuple[str, int], ...] = (
    ("省流量", 64),
    ("标准", 96),
    ("清晰", 128),
    ("高音质", 192),
)

AUDIO_LABELS: list[str] = [name for name, _ in AUDIO_LEVELS]
_AUDIO_BY_LABEL = {name: value for name, value in AUDIO_LEVELS}

AUDIO_TOOLTIP = (
    "人声为主（会议、讲课）用「标准」就够，再高听不出差别；\n"
    "有音乐、需要保留细节时选「高音质」。"
)


def quality_label(crf: int | float | None, default: str = "标准") -> str:
    """CRF 数值 → 最接近的档位名。

    两档等距时取 CRF 更大（更省体积）的那一档：用户落在两个档之间，
    说明他本来就愿意在画质上让一步。
    """
    try:
        value = float(crf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    best = min(QUALITY_LEVELS, key=lambda item: (abs(item[1] - value), -item[1]))
    return best[0]


def quality_value(label: str | None, default: int = 26) -> int:
    """档位名 → CRF 数值。未知档位回落默认值，不抛异常。"""
    return _QUALITY_BY_LABEL.get(str(label or "").strip(), default)


def audio_label(kbps: int | float | None, default: str = "清晰") -> str:
    """kbps → 最接近的档位名。等距时取更省流量的一档。"""
    try:
        value = float(kbps)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    best = min(AUDIO_LEVELS, key=lambda item: (abs(item[1] - value), item[1]))
    return best[0]


def audio_value(label: str | None, default: int = 128) -> int:
    return _AUDIO_BY_LABEL.get(str(label or "").strip(), default)


# ---------------------------------------------------------------- 编码器
# 用户不关心 libx264 是什么，只关心"快不快、稳不稳"。
CODEC_FRIENDLY: dict[str, str] = {
    "h264_nvenc": "NVIDIA 显卡加速",
    "libx264": "CPU 编码",
}

CODEC_TOOLTIP = {
    "h264_nvenc": "用显卡转码，速度更快，同时占用显卡。失败会自动切回 CPU。",
    "libx264": "用 CPU 转码，速度慢一些，但不依赖显卡驱动，最稳。\n换台电脑也能得到一致的结果。",
}


def codec_label(codec: str, default: str = "自动选择") -> str:
    return CODEC_FRIENDLY.get(str(codec or "").strip(), default)


def codec_tooltip(codec: str) -> str:
    return CODEC_TOOLTIP.get(str(codec or "").strip(), "")


# ---------------------------------------------------------------- 专业参数
# 这些是"需要的人才去动"的选项，放在界面的第二层。文案仍然尽量说人话，
# 但保留工程含义——会打开这一层的人，本来就想要 CRF 和采样率。

# (界面文字, plan.fps 的值)
FPS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("跟随原片", "keep"),
    ("24 帧", "24"),
    ("25 帧", "25"),
    ("30 帧", "30"),
    ("60 帧", "60"),
)

# (界面文字, 采样率 Hz)；0 表示不干预
SAMPLE_RATE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("跟随原片", 0),
    ("48000 Hz", 48000),
    ("44100 Hz", 44100),
    ("32000 Hz", 32000),
    ("22050 Hz", 22050),
)

# (界面文字, 声道数)；0 表示不干预
CHANNEL_OPTIONS: tuple[tuple[str, int], ...] = (
    ("跟随原片", 0),
    ("单声道", 1),
    ("立体声", 2),
)

# (界面文字, 顺时针角度)
ROTATION_OPTIONS: tuple[tuple[str, int], ...] = (
    ("不旋转", 0),
    ("顺时针 90°", 90),
    ("180°", 180),
    ("逆时针 90°", 270),
)

# (界面文字, plan.audio_codec 的值)
AUDIO_CODEC_OPTIONS: tuple[tuple[str, str], ...] = (
    ("AAC（通用）", "aac"),
    ("MP3（老设备）", "mp3"),
    ("直接复制原音轨", "copy"),
)

FPS_TOOLTIP = "降帧能明显减小体积，但动作会变顿。24/25 适合口播，30/60 适合运动画面。"
SAMPLE_RATE_TOOLTIP = "人声 44100 足够；音乐类素材保留 48000 更稳。"
CHANNEL_TOOLTIP = "会议、口播这类单一人声场景，转单声道能省一半音频体积。"
ROTATION_TOOLTIP = (
    "把画面真的转过去，任何播放器都一致。\n"
    "注意：旋转后「清晰度」是按新的画面高度算的。"
)


# ---------------------------------------------------------------- 音视频编码名
# ffprobe 给的是 h264 / hevc / aac 这种标识符，展示时用行业通用写法。
VIDEO_CODEC_NAMES: dict[str, str] = {
    "h264": "H.264",
    "hevc": "H.265",
    "h265": "H.265",
    "vp8": "VP8",
    "vp9": "VP9",
    "av1": "AV1",
    "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2",
    "wmv3": "WMV",
    "vc1": "VC-1",
    "theora": "Theora",
}

AUDIO_CODEC_NAMES: dict[str, str] = {
    "aac": "AAC",
    "mp3": "MP3",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "flac": "FLAC",
    "alac": "ALAC",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM",
}


def video_codec_name(codec: str) -> str:
    raw = str(codec or "").strip()
    return VIDEO_CODEC_NAMES.get(raw.lower(), raw or "—")


def audio_codec_name(codec: str) -> str:
    raw = str(codec or "").strip()
    return AUDIO_CODEC_NAMES.get(raw.lower(), raw or "—")
