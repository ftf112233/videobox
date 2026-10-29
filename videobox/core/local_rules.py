"""本地规则引擎 —— 无 API Key 时的参数顾问。

这不是"降级占位"，而是与 AI 走同一套 schema、同一个 UI 的完整功能。
差别只在于"大脑"：AI 读人话，这里读关键词。

设计原则：
- 每条规则都要给出人类能看懂的理由（reasons），跟 AI 的输出结构一致
- 规则覆盖不到时，返回一个稳妥的默认值，而不是报错
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .models import TranscodePlan, VideoInfo


@dataclass(frozen=True)
class Rule:
    name: str
    keywords: tuple[str, ...]
    build: Callable[[VideoInfo], TranscodePlan]


def _reason(param: str, why: str, confidence: float = 0.85) -> dict:
    return {"param": param, "why": why, "confidence": confidence}


def _wechat(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="微信朋友圈",
        container="mp4",
        video_codec="auto",
        quality_value=26,
        scale="720p",
        audio_bitrate_kbps=96,
        target_size_mb=20.0,
        reasons=[
            _reason("scale", "手机竖屏观看，720p 已足够清晰，且大幅缩短上传等待"),
            _reason("target_size_mb", "朋友圈视频有体积上限，压到 20MB 内可直接发送"),
            _reason("audio.bitrate", "语音和人声为主，96k 足够，再高听不出来"),
        ],
        risks=["如果原片是横屏且有小字，720p 下文字可能略糊"],
        source="local_rules",
    )


def _douyin(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="短视频平台",
        container="mp4",
        video_codec="auto",
        quality_value=23,
        scale="1080p",
        audio_bitrate_kbps=128,
        reasons=[
            _reason("quality", "平台会二次压缩，源头质量要留余量，取较高质量值"),
            _reason("scale", "1080p 是主流平台推荐的清晰度，再高会被压回去"),
            _reason("container", "mp4 + faststart 才能被平台正常解析"),
        ],
        source="local_rules",
    )


def _email(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="邮件附件",
        container="mp4",
        video_codec="auto",
        quality_value=30,
        scale="480p",
        audio_bitrate_kbps=64,
        target_size_mb=10.0,
        reasons=[
            _reason("target_size_mb", "常见的附件上限是 10~25MB，先压到 10MB 最稳"),
            _reason("scale", "邮件场景只求看清内容，480p 可以把体积压到最低"),
            _reason("quality", "为了提高压缩率放宽质量值，牺牲细节换体积"),
        ],
        risks=["有大量文字的画面可能看不清，建议改用网盘链接"],
        source="local_rules",
    )


def _meeting(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="会议录屏",
        container="mp4",
        video_codec="auto",
        quality_value=24,
        scale="720p",
        audio_bitrate_kbps=128,
        reasons=[
            _reason("quality", "录屏画面静止区域多，高质量值不会让体积暴涨，却能保住文字边缘"),
            _reason("audio.bitrate", "会议以人声为主，给足音频码率比给画面更值"),
            _reason("scale", "720p 下 PPT 文字仍可辨认，同时体积减半"),
        ],
        source="local_rules",
    )


def _archive(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="高质量存档",
        container="mp4",
        video_codec="auto",
        quality_value=19,
        scale="原画",
        audio_bitrate_kbps=192,
        reasons=[
            _reason("quality", "存档优先保画质，取接近视觉无损的质量值"),
            _reason("scale", "保持原分辨率，任何缩放都是不可逆的信息损失"),
            _reason("audio.bitrate", "音频给到 192k，避免日后需要重新压制"),
        ],
        risks=["体积可能接近原始文件，压缩收益有限"],
        source="local_rules",
    )


def _mobile(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="移动端省流量",
        container="mp4",
        video_codec="auto",
        quality_value=28,
        scale="720p",
        audio_bitrate_kbps=96,
        reasons=[
            _reason("scale", "手机屏幕小，720p 与 1080p 观感差异很小"),
            _reason("quality", "放宽质量值换取更小体积，适合流量受限场景"),
        ],
        source="local_rules",
    )


def _default(info: VideoInfo) -> TranscodePlan:
    return TranscodePlan(
        preset_name="通用压缩",
        container="mp4",
        video_codec="auto",
        quality_value=26,
        scale="1080p",
        audio_bitrate_kbps=128,
        reasons=[
            _reason("quality", "26 是画质与体积的常见平衡点，肉眼几乎无差"),
            _reason("scale", "1080p 兼顾清晰度与兼容性，绝大多数设备都能放"),
            _reason("container", "mp4 兼容性最好，Windows/手机/网页通吃"),
        ],
        source="local_rules",
    )


RULES: tuple[Rule, ...] = (
    Rule("微信", ("微信", "朋友圈", "发朋友", "发给家人", "群里"), _wechat),
    Rule("短视频", ("抖音", "快手", "小红书", "视频号", "短视频", "B站", "bilibili"), _douyin),
    Rule("邮件", ("邮件", "附件", "email", "发邮件", "上传到系统"), _email),
    Rule("会议录屏", ("会议", "录屏", "课件", "讲课", "网课", "PPT", "ppt", "屏幕录制"), _meeting),
    Rule("存档", ("存档", "备份", "归档", "无损", "原画质", "收藏"), _archive),
    Rule("移动端", ("手机", "移动端", "省流量", "流量", "平板"), _mobile),
)


def advise(text: str, info: VideoInfo) -> tuple[TranscodePlan, str]:
    """根据一句话需求给出计划。返回 (plan, 命中的规则名)。

    没有命中任何规则时用默认值，规则名为"通用"。
    """
    text = (text or "").strip().lower()
    if text:
        for rule in RULES:
            if any(kw.lower() in text for kw in rule.keywords):
                return rule.build(info), rule.name
    return _default(info), "通用"


def available_presets() -> list[str]:
    """UI 下拉框用的预设名。"""
    return ["通用"] + [r.name for r in RULES]
