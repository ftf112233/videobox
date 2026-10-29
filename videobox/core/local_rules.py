"""本地规则引擎 —— 无 API Key 时的参数顾问。

这不是"降级占位"，而是与 AI 走同一套 schema、同一个 UI 的完整功能。
差别只在于"大脑"：AI 读人话，这里读关键词。

设计原则：
- 每条规则给出的是"这样设会怎样"，不是"参数为什么这么填"。
  reasons 里不出现 CRF、码率、编码器型号——用户看不懂也管不着
- 规则覆盖不到时返回一个稳妥的默认值，而不是报错
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import TranscodePlan, VideoInfo


@dataclass(frozen=True)
class Rule:
    name: str
    keywords: tuple[str, ...]
    build: Callable[[VideoInfo], TranscodePlan]


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
            "手机上看着够清晰，上传等待也短",
            "朋友圈有体积上限，压到 20 MB 以内才能直接发出去",
            "声音主要是人说话，音质给到这一档就够",
        ],
        risks=["原片如果是横屏、画面里又有小字，放到 720p 后字可能有点糊"],
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
            "平台收到后还会再压一次，源头留点余量才不至于掉画质",
            "1080p 是平台推荐的清晰度，传更高也会被压回去",
            "mp4 各平台都认，直接上传就行",
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
            "邮箱附件上限通常是 10~25 MB，压到 10 MB 最保险",
            "邮件只要能看清内容，这个清晰度就够",
            "细节让一点，换更小的体积",
        ],
        risks=["画面里文字多的话可能看不清，这种情况发网盘链接更合适"],
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
            "录屏里静止画面多，保住文字边缘也不会让文件变大",
            "会议主要是人声，声音清楚比画面精细更值得",
            "这个清晰度下 PPT 上的字仍然认得出来，文件还能小一半",
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
            "尽量保住画质，接近看不出损失",
            "不缩小尺寸——缩了以后补不回来",
            "声音给到最高档，以后不用再处理一遍",
        ],
        risks=["文件可能和原片差不多大，压缩带来的收益有限"],
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
            "手机屏幕小，这个清晰度和 1080p 看着差不多",
            "画质让一点换更小的体积，适合流量紧张的时候",
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
            "画质和体积折中，肉眼几乎看不出差别",
            "绝大多数手机、电脑、电视都能正常播放",
            "mp4 兼容性最好，微信、网页、剪辑软件都认",
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
