"""LLM 客户端（同步、零第三方依赖）。

只用标准库 urllib，理由有三：
1. 打包体积小，不用把 httpx/requests 塞进 exe
2. 没有依赖就不会"在审核人机器上缺包"
3. 重试与降级逻辑自己写，行为完全可控

接口刻意只暴露 chat_json()：参数顾问要的是结构化 JSON，
不是自由文本，把能力限制住，模型就没有发挥空间去编废话。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

MAX_RETRIES = 3
BACKOFF_BASE = 1.6


class LLMError(RuntimeError):
    """不可重试的失败（例如 Key 无效），调用方应直接降级到本地规则。"""


@dataclass
class LLMResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_sec: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = 60,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat_json(self, system_prompt: str, user_prompt: str) -> LLMResult:
        """要求模型返回 JSON 对象。失败抛 LLMError。"""
        if not self.available:
            raise LLMError("未配置 API Key")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,  # 参数推荐要稳定，不要创意
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/chat/completions"

        last_error = ""
        started = time.perf_counter()

        for attempt in range(MAX_RETRIES):
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                elapsed = time.perf_counter() - started
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                return LLMResult(
                    content=content,
                    model=data.get("model", self.model),
                    prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                    elapsed_sec=round(elapsed, 2),
                )
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:  # noqa: BLE001 - 读 body 失败不该盖住原始错误
                    pass
                # 4xx 是配置问题，重试没有意义
                if 400 <= exc.code < 500:
                    raise LLMError(f"接口返回 {exc.code}：{detail or exc.reason}") from exc
                last_error = f"HTTP {exc.code}：{detail or exc.reason}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)

            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** attempt
                log.warning("LLM 调用失败（第 %d 次）：%s，%.1fs 后重试", attempt + 1, last_error, wait)
                time.sleep(wait)

        raise LLMError(f"重试 {MAX_RETRIES} 次仍失败：{last_error}")


PLAN_SYSTEM_PROMPT = """你是一个视频转码参数顾问。用户会用自然语言描述他想怎么用这个视频，
你要输出一组 ffmpeg 转码参数。

严格只输出一个 JSON 对象，不要输出任何解释性文字、不要输出命令本身。

JSON 结构：
{
  "preset": "给这个方案起的中文短名，如'微信朋友圈'",
  "container": "mp4 或 mkv",
  "target_size_mb": 数字或 null,
  "video": {
    "codec": "__CODEC_OPTIONS__",
    "quality": 18-35 的整数（越小画质越好体积越大）,
    "scale": "__SCALE_OPTIONS__",
    "fps": "keep" 或 1-120 的数字
  },
  "audio": {"codec": "aac", "bitrate": 32-320 的整数},
  "reasons": [{"param": "参数名", "why": "为什么要这么设，一句人话", "confidence": 0到1}],
  "risks": ["这个方案可能的副作用"]
}

规则：
- codec 只能从给定选项里选，不要发明编码器名
- scale 只能从给定选项里选
- reasons 至少 2 条，每条说清"为什么"，不要复述参数值
- 如果用户没提体积要求，target_size_mb 给 null
- risks 里写用户可能没想到的副作用，没有就给空数组"""


def build_plan_prompt(
    user_text: str, info_summary: str, codec_options: str, scale_options: str
) -> tuple[str, str]:
    """把本机能力和视频概况注入提示词，避免模型给出跑不动的参数。

    这里刻意用 replace 而不是 str.format：提示词里包含 JSON 示例，
    大括号会被 format 当作占位符，一调用就 KeyError。
    """
    system = (
        PLAN_SYSTEM_PROMPT
        .replace("__CODEC_OPTIONS__", codec_options)
        .replace("__SCALE_OPTIONS__", scale_options)
    )
    user = (
        f"源视频信息：{info_summary}\n\n"
        f"用户的需求：{user_text or '用户没有特别说明，请给一个均衡的通用方案'}\n\n"
        "请给出参数方案。"
    )
    return system, user
