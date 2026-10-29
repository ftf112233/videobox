"""probe 层单测：全部基于真实 ffmpeg 输出样本，不 mock。"""

from __future__ import annotations

import json
import unittest

from videobox.core.probe import (
    parse_clock,
    parse_ffmpeg_stderr,
    parse_ffprobe_json,
    parse_fraction,
)

# 真实 ffprobe 输出（sample_720p.mp4，已裁剪到关键字段）
FFPROBE_SAMPLE = json.dumps({
    "streams": [
        {
            "index": 0, "codec_name": "h264", "codec_type": "video",
            "width": 1280, "height": 720, "pix_fmt": "yuv444p",
            "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
            "duration": "10.000000", "bit_rate": "70244",
        },
        {
            "index": 1, "codec_name": "aac", "codec_type": "audio",
            "channels": 1, "sample_rate": "44100", "bit_rate": "126000",
        },
    ],
    "format": {
        "filename": "sample_720p.mp4",
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "10.000000", "size": "259616", "bit_rate": "207692",
    },
})

# 真实 ffmpeg -i 输出（兜底路径）
FFMPEG_STDERR_SAMPLE = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'tests/fixtures/sample_720p.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:00:10.00, start: 0.000000, bitrate: 207 kb/s
  Stream #0:0[0x1](und): Video: h264 (High 4:4:4 Predictive) (avc1 / 0x31637661), yuv444p(progressive), 1280x720 [SAR 1:1 DAR 16:9], 70 kb/s, 30 fps, 30 tbr, 15360 tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 126 kb/s (default)
At least one output file must be specified
"""


class TestScalarParsers(unittest.TestCase):
    def test_parse_fraction(self):
        self.assertAlmostEqual(parse_fraction("30000/1001"), 29.97, places=2)
        self.assertEqual(parse_fraction("30"), 30.0)
        self.assertEqual(parse_fraction("0/0"), 0.0)
        self.assertEqual(parse_fraction(""), 0.0)

    def test_parse_clock(self):
        self.assertAlmostEqual(parse_clock("00:01:23.45"), 83.45, places=2)
        self.assertAlmostEqual(parse_clock("01:00:00"), 3600.0, places=2)
        self.assertAlmostEqual(parse_clock("00:00:10.00"), 10.0, places=2)
        self.assertEqual(parse_clock("N/A"), 0.0)
        self.assertEqual(parse_clock(""), 0.0)


class TestFfprobeJson(unittest.TestCase):
    def setUp(self):
        self.info = parse_ffprobe_json(FFPROBE_SAMPLE, size_bytes=259616)

    def test_video_fields(self):
        self.assertEqual(self.info.video_codec, "h264")
        self.assertEqual(self.info.width, 1280)
        self.assertEqual(self.info.height, 720)
        self.assertAlmostEqual(self.info.fps, 30.0)
        self.assertEqual(self.info.pix_fmt, "yuv444p")

    def test_audio_fields(self):
        self.assertEqual(self.info.audio_codec, "aac")
        self.assertEqual(self.info.audio_sample_rate, 44100)
        self.assertEqual(self.info.audio_bitrate_kbps, 126)

    def test_container_and_duration(self):
        self.assertEqual(self.info.container, "mov")  # format_name 取第一段
        self.assertAlmostEqual(self.info.duration_sec, 10.0)

    def test_derived_properties(self):
        self.assertTrue(self.info.has_video)
        self.assertTrue(self.info.has_audio)
        self.assertEqual(self.info.resolution_label, "1280×720")
        self.assertEqual(self.info.duration_label, "00:10")

    def test_missing_streams_does_not_crash(self):
        info = parse_ffprobe_json(json.dumps({"streams": [], "format": {}}))
        self.assertFalse(info.has_video)
        self.assertFalse(info.has_audio)
        self.assertEqual(info.duration_sec, 0.0)

    def test_duration_falls_back_to_bitrate_when_absent(self):
        payload = json.dumps({
            "streams": [{"codec_type": "video", "codec_name": "h264",
                         "width": 640, "height": 480}],
            "format": {"size": "1000000", "bit_rate": "1000000"},
        })
        info = parse_ffprobe_json(payload)
        self.assertAlmostEqual(info.duration_sec, 8.0, places=1)


class TestFfmpegStderrFallback(unittest.TestCase):
    """没有 ffprobe 时的兜底路径，正则很脆，必须单独钉死。"""

    def setUp(self):
        self.info = parse_ffmpeg_stderr(FFMPEG_STDERR_SAMPLE, size_bytes=259616)

    def test_duration(self):
        self.assertAlmostEqual(self.info.duration_sec, 10.0, places=2)

    def test_resolution_not_confused_by_hex(self):
        # 输出里有 '0x31637661' 这种十六进制，不能被误认成 '1280x720'
        self.assertEqual(self.info.width, 1280)
        self.assertEqual(self.info.height, 720)

    def test_codecs(self):
        self.assertEqual(self.info.video_codec, "h264")
        self.assertEqual(self.info.audio_codec, "aac")

    def test_fps_and_audio(self):
        self.assertAlmostEqual(self.info.fps, 30.0)
        self.assertEqual(self.info.audio_sample_rate, 44100)

    def test_garbage_input_yields_empty_info(self):
        info = parse_ffmpeg_stderr("这不是 ffmpeg 的输出")
        self.assertFalse(info.has_video)
        self.assertEqual(info.duration_sec, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
