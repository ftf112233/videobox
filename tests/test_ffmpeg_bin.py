"""环境探测的文案：状态栏该说什么、不该说什么。

这条规则被违反过一次：状态栏整句写着「使用 CPU 编码（NVIDIA 显卡加速：
显卡驱动版本过低，需要更新到 610.00 或更高）」。用户第一眼看到的是
一句他既解决不了、也不关心的报错。
"""

from __future__ import annotations

import unittest

from videobox.infra.ffmpeg_bin import (
    CodecProbe, available_from, summary_detail, summary_line,
)

NV_FAILED = CodecProbe(
    codec="h264_nvenc", ok=False,
    reason="显卡驱动版本过低，需要更新到 610.00 或更高",
)
X264_OK = CodecProbe(codec="libx264", ok=True)


class TestSummaryLine(unittest.TestCase):
    def test_falls_back_to_cpu_without_explaining(self):
        line = summary_line([NV_FAILED, X264_OK])
        self.assertEqual(line, "CPU 编码")
        # 原因不该出现在状态栏这一行里
        for word in ("驱动", "版本", "610.00", "NVIDIA"):
            self.assertNotIn(word, line)

    def test_hardware_encoder_is_named(self):
        nvenc = CodecProbe(codec="h264_nvenc", ok=True)
        self.assertEqual(summary_line([nvenc, X264_OK]), "NVIDIA 显卡加速")

    def test_no_probe_result(self):
        self.assertEqual(summary_line([]), "未探测编码器")

    def test_nothing_works(self):
        broken = CodecProbe(codec="h264_nvenc", ok=False, reason="失败")
        self.assertEqual(summary_line([broken]), "无可用编码器")


class TestSummaryDetail(unittest.TestCase):
    def test_explains_the_failure_for_people_who_ask(self):
        detail = summary_detail([NV_FAILED, X264_OK])
        self.assertIn("显卡驱动版本过低", detail)
        self.assertIn("CPU", detail)

    def test_no_failure_means_no_scary_text(self):
        detail = summary_detail([X264_OK])
        self.assertNotIn("失败", detail)
        self.assertIn("最稳", detail)

    def test_hardware_gets_a_short_note(self):
        nvenc = CodecProbe(codec="h264_nvenc", ok=True)
        self.assertIn("NVIDIA", summary_detail([nvenc, X264_OK]))


class TestAvailableFrom(unittest.TestCase):
    def test_libx264_is_always_available(self):
        # 保底：没有它，整个软件一句都转不了
        self.assertIn("libx264", available_from([NV_FAILED]))

    def test_failed_encoders_are_excluded(self):
        self.assertNotIn("h264_nvenc", available_from([NV_FAILED, X264_OK]))


if __name__ == "__main__":
    unittest.main()
