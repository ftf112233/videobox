"""labels 层单测：档位映射决定界面上用户看到什么，改错一个字就是一次误操作。"""

from __future__ import annotations

import unittest

from videobox.core import labels


class TestQualityLevels(unittest.TestCase):
    def test_exact_values_round_trip(self):
        for name, value in labels.QUALITY_LEVELS:
            self.assertEqual(labels.quality_value(name), value)
            self.assertEqual(labels.quality_label(value), name)

    def test_nearest_level(self):
        # 模型常给 24，距 23 一格、距 26 两格
        self.assertEqual(labels.quality_label(24), "高")
        self.assertEqual(labels.quality_label(19), "极佳")
        self.assertEqual(labels.quality_label(34), "省体积")

    def test_tie_prefers_smaller_file(self):
        # 28 距 26 和 30 都是 2。等距时取省体积那一档：
        # 用户落在两档之间，说明他已经在画质上让过步了
        self.assertEqual(labels.quality_label(28), "省体积")

    def test_garbage_falls_back(self):
        self.assertEqual(labels.quality_label(None), "标准")
        self.assertEqual(labels.quality_label("高"), "标准")
        self.assertEqual(labels.quality_value("不存在的档位"), 26)
        self.assertEqual(labels.quality_value(None), 26)


class TestAudioLevels(unittest.TestCase):
    def test_exact_values_round_trip(self):
        for name, kbps in labels.AUDIO_LEVELS:
            self.assertEqual(labels.audio_value(name), kbps)
            self.assertEqual(labels.audio_label(kbps), name)

    def test_nearest_level(self):
        self.assertEqual(labels.audio_label(100), "标准")
        self.assertEqual(labels.audio_label(300), "高音质")

    def test_tie_prefers_less_data(self):
        # 80 距 64 和 96 都是 16，取省流量那一档
        self.assertEqual(labels.audio_label(80), "省流量")

    def test_garbage_falls_back(self):
        self.assertEqual(labels.audio_label(None), "清晰")
        self.assertEqual(labels.audio_value("胡说"), 128)


class TestFriendlyNames(unittest.TestCase):
    def test_codec_labels_are_human(self):
        self.assertEqual(labels.codec_label("h264_nvenc"), "NVIDIA 显卡加速")
        self.assertEqual(labels.codec_label("libx264"), "CPU 编码")
        self.assertEqual(labels.codec_label(""), "自动选择")
        self.assertTrue(labels.codec_tooltip("libx264"))

    def test_container_codec_names(self):
        self.assertEqual(labels.video_codec_name("h264"), "H.264")
        self.assertEqual(labels.video_codec_name("hevc"), "H.265")
        self.assertEqual(labels.audio_codec_name("aac"), "AAC")
        # 不认识的编码原样返回，不显示空白
        self.assertEqual(labels.video_codec_name("不认识"), "不认识")
        self.assertEqual(labels.video_codec_name(""), "—")
