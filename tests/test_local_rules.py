"""local_rules 单测：它是无 API Key 时的主力功能，不能靠"跑起来没报错"验收。"""

from __future__ import annotations

import re
import unittest

from videobox.core import local_rules
from videobox.core.models import CONTAINERS, SCALE_TARGETS, VideoInfo
from videobox.core.params import QUALITY_MAX, QUALITY_MIN

INFO = VideoInfo(
    path="in.mp4", duration_sec=60.0, size_bytes=100_000_000,
    video_codec="h264", width=1920, height=1080, fps=30.0, audio_codec="aac",
)

# 界面上不该出现的词。它们对用户没有意义，出现在说明里就是没翻译干净。
JARGON = re.compile(r"CRF|crf|kbps|libx264|nvenc|NVENC|faststart|yuv420p|码率|像素格式")


class TestMatching(unittest.TestCase):
    def test_keywords_hit_expected_preset(self):
        cases = {
            "发朋友圈": "微信朋友圈",
            "传抖音": "短视频平台",
            "发邮件给同事": "邮件附件",
            "会议录屏要能看清PPT": "会议录屏",
            "这个要存档": "高质量存档",
            "手机上看看就行": "移动端省流量",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                plan, rule = local_rules.advise(text, INFO)
                self.assertEqual(plan.preset_name, expected)
                self.assertNotEqual(rule, "通用")

    def test_empty_request_falls_back_to_default(self):
        plan, rule = local_rules.advise("", INFO)
        self.assertEqual(rule, "通用")
        self.assertEqual(plan.preset_name, "通用压缩")


class TestPlanValues(unittest.TestCase):
    def test_all_presets_are_legal(self):
        for text in ("朋友圈", "抖音", "邮件", "会议", "存档", "手机", ""):
            with self.subTest(text=text):
                plan, _ = local_rules.advise(text, INFO)
                self.assertIn(plan.container, CONTAINERS)
                self.assertIn(plan.scale, SCALE_TARGETS)
                self.assertGreaterEqual(plan.quality_value, QUALITY_MIN)
                self.assertLessEqual(plan.quality_value, QUALITY_MAX)
                self.assertGreaterEqual(plan.audio_bitrate_kbps, 32)
                self.assertLessEqual(plan.audio_bitrate_kbps, 320)

    def test_every_preset_explains_itself(self):
        for text in ("朋友圈", "抖音", "邮件", "会议", "存档", "手机", ""):
            with self.subTest(text=text):
                plan, _ = local_rules.advise(text, INFO)
                self.assertGreaterEqual(len(plan.reasons), 2)
                for reason in plan.reasons:
                    self.assertIsInstance(reason, str)
                    self.assertTrue(reason.strip())


class TestReasonsAreHuman(unittest.TestCase):
    def test_no_jargon_leaks_into_user_facing_text(self):
        """说明文字是给普通用户看的，混进参数名或单位就算失败。

        这条测试是防回退用的：以后想加一条"取 CRF 26 保证体积"很容易，
        但那正是这次要清掉的东西。
        """
        for text in ("朋友圈", "抖音", "邮件", "会议", "存档", "手机", ""):
            plan, _ = local_rules.advise(text, INFO)
            for line in plan.reasons + plan.risks:
                with self.subTest(text=text, line=line):
                    self.assertIsNone(JARGON.search(line), f"说明里有技术黑话：{line}")


if __name__ == "__main__":
    unittest.main()
