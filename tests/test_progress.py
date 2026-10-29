"""progress 层单测：喂真实 ffmpeg -progress 的行序列。"""

from __future__ import annotations

import unittest

from videobox.core.progress import ProgressParser, format_eta


class TestProgressParser(unittest.TestCase):
    def test_typical_sequence(self):
        parser = ProgressParser(duration_sec=10.0)
        updates = [
            parser.feed_line("frame=30"),
            parser.feed_line("fps=30.0"),
            parser.feed_line("out_time_us=2000000"),
            parser.feed_line("speed=2.0x"),
            parser.feed_line("progress=continue"),
        ]
        last = updates[-1]
        self.assertAlmostEqual(last.percent, 0.2, places=3)
        self.assertAlmostEqual(last.out_time_sec, 2.0, places=3)
        self.assertAlmostEqual(last.speed, 2.0)
        self.assertFalse(last.done)

    def test_end_means_done(self):
        parser = ProgressParser(duration_sec=10.0)
        parser.feed_line("out_time_us=9000000")
        update = parser.feed_line("progress=end")
        self.assertTrue(update.done)
        self.assertEqual(update.percent, 1.0)
        self.assertEqual(update.eta_sec, 0.0)

    def test_na_value_is_ignored(self):
        """ffmpeg 开头会输出 out_time_us=N/A，不能当 0 也不算崩。"""
        parser = ProgressParser(duration_sec=10.0)
        self.assertIsNone(parser.feed_line("out_time_us=N/A"))
        parser.feed_line("out_time_us=5000000")
        self.assertAlmostEqual(parser.out_time_sec, 5.0)

    def test_out_time_ms_is_microseconds(self):
        """ffmpeg 的 out_time_ms 单位其实是微秒，这是有名的历史坑。"""
        parser = ProgressParser(duration_sec=10.0)
        parser.feed_line("out_time_ms=3000000")
        self.assertAlmostEqual(parser.out_time_sec, 3.0)

    def test_percent_clamped_when_overshoot(self):
        """音频比视频长时 out_time 会超出视频时长。"""
        parser = ProgressParser(duration_sec=10.0)
        parser.feed_line("out_time_us=15000000")
        update = parser.feed_line("progress=continue")
        self.assertEqual(update.percent, 1.0)

    def test_zero_duration_does_not_divide_by_zero(self):
        parser = ProgressParser(duration_sec=0.0)
        parser.feed_line("out_time_us=1000000")
        update = parser.feed_line("progress=continue")
        self.assertEqual(update.percent, 0.0)

    def test_eta_none_at_very_start(self):
        """开头速度还没稳，不给 ETA，免得数字乱跳吓人。"""
        parser = ProgressParser(duration_sec=100.0)
        parser.feed_line("out_time_us=500000")
        update = parser.feed_line("speed=1.0x")
        self.assertIsNone(update.eta_sec)

    def test_eta_reasonable_midway(self):
        parser = ProgressParser(duration_sec=100.0)
        parser.feed_line("out_time_us=40000000")
        update = parser.feed_line("speed=2.0x")
        # 剩 60 秒素材 / 2 倍速 = 30 秒
        self.assertAlmostEqual(update.eta_sec, 30.0, delta=1.0)

    def test_garbage_lines_ignored(self):
        parser = ProgressParser(duration_sec=10.0)
        self.assertIsNone(parser.feed_line(""))
        self.assertIsNone(parser.feed_line("这不是进度"))
        self.assertIsNone(parser.feed_line("some_random=value"))

    def test_value_with_equals_sign(self):
        """只切第一个等号，值里再有等号也不能切坏。"""
        parser = ProgressParser(duration_sec=10.0)
        parser.feed_line("out_time_us=2000000")
        update = parser.feed_line("metadata=a=b=c")
        self.assertIsNone(update)  # 未知键被忽略，且不崩


class TestFormatEta(unittest.TestCase):
    def test_units(self):
        self.assertEqual(format_eta(None), "计算中…")
        self.assertEqual(format_eta(0), "即将完成")
        self.assertEqual(format_eta(45), "剩余 45 秒")
        self.assertEqual(format_eta(90), "剩余 1 分 30 秒")
        self.assertEqual(format_eta(3700), "剩余 1 时 1 分")


if __name__ == "__main__":
    unittest.main(verbosity=2)
