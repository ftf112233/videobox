"""LLM 输出的清洗与校验。

大模型很愿意帮忙，也很愿意编。这一层做两件事：
1. 把脏 JSON（```json 围栏、尾逗号、中文引号）洗成能解析的
2. 把每个字段钉死在自己的合法域里，越界一律回落到安全默认，
   并且把"改了什么"记进 warnings，用于在界面上标黄提示用户
"""

from __future__ import annotations

import json
import re
from typing import Any

from .models import CONTAINERS, CODEC_PREFS, SCALE_TARGETS, TranscodePlan
from .params import QUALITY_MAX, QUALITY_MIN

# 模型偶尔会输出"高/中/低"这种忽悠值，给个映射表兜底
_QUALITY_WORDS = {
    "高": 20, "高质量": 20, "highest": 18, "high": 20,
    "中": 26, "中等": 26, "medium": 26, "balanced": 26,
    "低": 32, "低质量": 32, "low": 32, "small": 32,
}

_AUDIO_MIN, _AUDIO_MAX = 32, 320


def strip_fences(text: str) -> str:
    """剥掉 ```json ... ``` 围栏，以及前后的寒暄。"""
    text = (text or "").strip()
    if m := re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S):
        text = m.group(1)
    # 模型有时会写"好的，这是参数：{...}"，抓第一个大括号到最后一个
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text.strip()


def repair(text: str) -> str:
    """修几个最常见的 JSON 语法病。修不好就原样返回，让上层走降级。"""
    # 尾逗号：{"a":1,}  /
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 中文引号当分隔符用
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # 单引号键名（危险但常见），只在形如 'key': 时替换
    text = re.sub(r"'([A-Za-z_][A-Za-z0-9_]*)'\s*:", r'"\1":', text)
    return text


def try_parse(text: str) -> dict[str, Any] | None:
    """尽力把一段文本解析成 dict。全失败返回 None。"""
    cleaned = strip_fences(text)
    for candidate in (cleaned, repair(cleaned)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _coerce_quality(raw: Any) -> tuple[int, str | None]:
    """质量值可能是数字、字符串数字，或"高/中/低"。返回 (值, 告警)。"""
    if isinstance(raw, str) and raw.strip() in _QUALITY_WORDS:
        return _QUALITY_WORDS[raw.strip()], f"质量值'{raw}'不是数字，已映射为 {_QUALITY_WORDS[raw.strip()]}"
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return 26, f"质量值 {raw!r} 无法识别，已回落为 26"
    if value < QUALITY_MIN:
        return QUALITY_MIN, f"质量值 {value} 低于安全下限，已提升到 {QUALITY_MIN}"
    if value > QUALITY_MAX:
        return QUALITY_MAX, f"质量值 {value} 高于安全上限，已限制为 {QUALITY_MAX}"
    return value, None


def _coerce_audio_kbps(raw: Any) -> tuple[int, str | None]:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return 128, f"音频码率 {raw!r} 非法，已回落为 128"
    if value < _AUDIO_MIN:
        return _AUDIO_MIN, f"音频码率 {value}k 过低，已提升到 {_AUDIO_MIN}k"
    if value > _AUDIO_MAX:
        return _AUDIO_MAX, f"音频码率 {value}k 过高，已限制为 {_AUDIO_MAX}k"
    return value, None


def plan_from_payload(
    data: dict[str, Any],
    available_codecs: list[str],
    source: str = "ai",
) -> tuple[TranscodePlan, list[str]]:
    """把模型吐出来的 dict 变成可信的 TranscodePlan。

    返回 (plan, warnings)。warnings 非空说明模型编了东西，UI 上要标出来。
    """
    warnings: list[str] = []
    data = data or {}

    container = str(data.get("container", "mp4")).lower().strip()
    if container not in CONTAINERS:
        warnings.append(f"容器 {container!r} 不在支持列表，已回落为 mp4")
        container = "mp4"

    video = data.get("video") if isinstance(data.get("video"), dict) else {}
    audio = data.get("audio") if isinstance(data.get("audio"), dict) else {}

    # --- 编码器：模型最多只能表达"想不想要硬件加速"，最终由实测决定 ---
    codec_raw = str(video.get("codec", "auto")).strip()
    if codec_raw not in CODEC_PREFS:
        warnings.append(f"编码器 {codec_raw!r} 不受支持，已交给本机实测决定")
        codec_raw = "auto"
    if codec_raw.startswith("h264_") and codec_raw not in available_codecs:
        warnings.append(f"本机实测不可用 {codec_raw}，已回落为软件编码")
        codec_raw = "auto"

    quality, q_warn = _coerce_quality(
        video.get("quality", video.get("crf", video.get("cq", 26)))
    )
    if q_warn:
        warnings.append(q_warn)

    scale_raw = str(video.get("scale", "原画")).strip()
    if scale_raw not in SCALE_TARGETS:
        # 常见变体：720P / 720 / 720p
        normalized = scale_raw.lower().replace("p", "") if scale_raw.lower().endswith("p") else scale_raw
        match = next((k for k in SCALE_TARGETS if k.lower().startswith(normalized.lower())), None)
        if match:
            scale_raw = match
        else:
            warnings.append(f"缩放档位 {scale_raw!r} 不受支持，已回落为原画")
            scale_raw = "原画"

    audio_codec = str(audio.get("codec", "aac")).strip().lower()
    if audio_codec not in ("aac", "mp3", "copy"):
        warnings.append(f"音频编码 {audio_codec!r} 不受支持，已回落为 aac")
        audio_codec = "aac"

    audio_kbps, a_warn = _coerce_audio_kbps(audio.get("bitrate", 128))
    if a_warn:
        warnings.append(a_warn)

    target_size_mb = None
    raw_target = data.get("target_size_mb")
    if raw_target not in (None, "", 0):
        try:
            value = float(raw_target)
            if 0.1 <= value <= 10240:
                target_size_mb = round(value, 1)
            else:
                warnings.append(f"目标体积 {value}MB 超出合理范围，已忽略")
        except (TypeError, ValueError):
            warnings.append(f"目标体积 {raw_target!r} 无法识别，已忽略")

    fps = "keep"
    raw_fps = video.get("fps", "keep")
    if raw_fps not in (None, "", "keep", "原帧率", "inherit"):
        try:
            fps_value = float(raw_fps)
            if 1 <= fps_value <= 120:
                fps = f"{fps_value:g}"
            else:
                warnings.append(f"帧率 {fps_value:g} 超出 1~120 范围，已保持原帧率")
        except (TypeError, ValueError):
            warnings.append(f"帧率 {raw_fps!r} 无法识别，已保持原帧率")

    reasons = []
    for item in data.get("reasons") or []:
        if not isinstance(item, dict) or not item.get("why"):
            continue
        try:
            conf = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            conf = 0.8
        reasons.append({
            "param": str(item.get("param", "")),
            "why": str(item.get("why", "")),
            "confidence": max(0.0, min(1.0, conf)),
        })

    risks = [str(r) for r in (data.get("risks") or []) if r]

    preset_name = str(data.get("preset") or data.get("preset_name") or "自定义").strip()[:40]

    plan = TranscodePlan(
        preset_name=preset_name or "自定义",
        container=container,
        video_codec=codec_raw,
        quality_mode="cq" if codec_raw == "h264_nvenc" else "crf",
        quality_value=quality,
        scale=scale_raw,
        fps=fps,
        audio_codec=audio_codec,
        audio_bitrate_kbps=audio_kbps,
        target_size_mb=target_size_mb,
        reasons=reasons,
        risks=risks,
        source=source,
    )
    return plan, warnings
