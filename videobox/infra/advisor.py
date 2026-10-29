"""参数顾问：把「用户的一句话」变成「一份可信的 TranscodePlan」。

两条路，同一个出口：
- 有 API Key → 走大模型，再经 plan_schema 校验
- 无 Key 或调用失败 → 走本地规则引擎

关键是两条路产出的 TranscodePlan 结构完全一致，
所以界面、后续编辑、命令拼装都不用关心方案是哪来的。
"""

from __future__ import annotations

import logging

from ..core import local_rules
from ..core.models import SCALE_TARGETS, TranscodePlan, VideoInfo
from ..core.plan_schema import plan_from_payload, try_parse
from .llm_client import LLMClient, LLMError, build_plan_prompt

log = logging.getLogger(__name__)

SCALE_OPTIONS = "|".join(SCALE_TARGETS.keys())


class Advisor:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def mode_label(self) -> str:
        return "AI 顾问（DeepSeek）" if self.client.available else "本地规则引擎"

    def advise(
        self, text: str, info: VideoInfo, available_codecs: list[str]
    ) -> tuple[TranscodePlan, list[str], str]:
        """返回 (计划, 告警, 是否真的走了 AI)。

        任何一步出问题都静默降级到本地规则——用户要的是能转码，
        不是看一段报错。失败原因会写进日志。
        """
        if not self.client.available:
            plan, rule = local_rules.advise(text, info)
            log.info("无 API Key，使用本地规则：%s", rule)
            return plan, [], False

        # 让模型只在"本机实测可用"的编码器里选，从源头杜绝跑不动的参数
        usable = [c for c in available_codecs if c in ("h264_nvenc", "libx264")]
        if "libx264" not in usable:
            usable.append("libx264")
        codec_options = "|".join(usable)

        try:
            system, user = build_plan_prompt(
                user_text=text,
                info_summary=info.summary_line(),
                codec_options=codec_options,
                scale_options=SCALE_OPTIONS,
            )
            result = self.client.chat_json(system, user)
            payload = try_parse(result.content)
            if payload is None:
                raise LLMError("模型返回的不是合法 JSON")
            plan, warnings = plan_from_payload(payload, available_codecs, source="ai")
            log.info(
                "AI 顾问命中：%s，tokens=%d，耗时=%.2fs，告警=%d 条",
                plan.preset_name, result.total_tokens, result.elapsed_sec, len(warnings),
            )
            return plan, warnings, True
        except LLMError as exc:
            log.warning("AI 顾问失败，降级到本地规则：%s", exc)
            plan, _rule = local_rules.advise(text, info)
            return plan, [f"AI 调用失败，已切换到本地规则（{exc}）"], False
        except Exception as exc:  # noqa: BLE001 - 宁可降级也不能让主流程挂掉
            log.exception("AI 顾问异常，降级到本地规则")
            plan, _rule = local_rules.advise(text, info)
            return plan, [f"AI 出现异常，已切换到本地规则（{exc}）"], False
