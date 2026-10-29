"""params 层单测：命令拼装是纯函数，用 golden string 钉住。"""

from __future__ import annotations

import unittest

from videobox.core.models import TranscodePlan, VideoInfo
from videobox.core.params import (
    QUALITY_MAX,
    QUALITY_MIN,
    build_args,
    build_audio_args,
    build_video_args,
    choose_codec,
    clamp_quality,
    estimate_bitrate_kbps,
    resolve_scale,
)

INFO_1080P = VideoInfo(
    path="in.mp4", duration_sec=60.0, size_bytes=100_000_000,
    container="mov", video_codec="h264", width=1920, height=1080,
    fps=30.0, audio_codec="aac", audio_sample_rate=44100,
)

INFO_NO_AUDIO = VideoInfo(
    path="in.mp4", duration_sec=10.0, size_bytes=1_000_000,
    video_codec="h264", width=854, height=480, fps=25.0,
)


class TestChooseCodec(unittest.TestCase):
    def test_prefers_requested_when_available(self):
        self.assertEqual(choose_codec("h264_nvenc", ["h264_nvenc", "libx264"]), "h264_nvenc")

    def test_falls_back_when_requested_unavailable(self):
        # 这台机器实测 NVENC 不可用（驱动 573.24 < 要求的 610.00）
        self.assertEqual(choose_codec("h264_nvenc", ["libx264"]), "libx264")

    def test_auto_prefers_hardware(self):
        self.assertEqual(choose_codec("auto", ["h264_nvenc", "libx264"]), "h264_nvenc")

    def test_auto_without_hardware(self):
        self.assertEqual(choose_codec("auto", ["libx264"]), "libx264")

    def test_empty_available_is_safe(self):
        self.assertEqual(choose_codec("auto", []), "libx264")


class TestClampQuality(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(clamp_quality(5), QUALITY_MIN)
        self.assertEqual(clamp_quality(99), QUALITY_MAX)
        self.assertEqual(clamp_quality(26), 26)


class TestEstimateBitrate(unittest.TestCase):
    def test_20mb_over_60s(self):
        # 20MB * 8 * 1024 / 60s = 2730 kbps 总，减去音频 128 → 2602
        self.assertEqual(estimate_bitrate_kbps(20.0, 60.0, 128), 2602)

    def test_impossible_target_returns_zero(self):
        self.assertEqual(estimate_bitrate_kbps(0.1, 600.0, 128), 0)

    def test_zero_duration_returns_zero(self):
        self.assertEqual(estimate_bitrate_kbps(20.0, 0.0, 128), 0)


class TestResolveScale(unittest.TestCase):
    def test_downscale(self):
        plan = TranscodePlan(scale="720p")
        self.assertEqual(resolve_scale(plan, INFO_1080P), 720)

    def test_never_upscales(self):
        plan = TranscodePlan(scale="1080p")
        self.assertEqual(resolve_scale(plan, INFO_NO_AUDIO), None)  # 480p 源不放大

    def test_original_passthrough(self):
        plan = TranscodePlan(scale="原画")
        self.assertEqual(resolve_scale(plan, INFO_1080P), None)


class TestBuildArgs(unittest.TestCase):
    def test_software_encoding_baseline(self):
        plan = TranscodePlan(video_codec="libx264", quality_value=26, scale="原画")
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-c:v", args)
        self.assertEqual(args[args.index("-c:v") + 1], "libx264")
        self.assertEqual(args[args.index("-crf") + 1], "26")
        self.assertEqual(args[args.index("-preset") + 1], "veryfast")
        # 这两条是硬要求，缺一个就会产出别人打不开的视频
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(args[args.index("-movflags") + 1], "+faststart")

    def test_nvenc_includes_bitrate_zero(self):
        # -b:v 0 不加的话 NVENC 会走固定码率，体积失控
        plan = TranscodePlan(video_codec="h264_nvenc", quality_value=24)
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["h264_nvenc"])
        self.assertEqual(args[args.index("-c:v") + 1], "h264_nvenc")
        self.assertIn("-b:v", args)
        self.assertEqual(args[args.index("-b:v") + 1], "0")
        self.assertEqual(args[args.index("-cq") + 1], "24")

    def test_falls_back_to_software_when_nvenc_unavailable(self):
        plan = TranscodePlan(video_codec="h264_nvenc")
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertEqual(args[args.index("-c:v") + 1], "libx264")

    def test_scale_applied(self):
        plan = TranscodePlan(scale="720p")
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-vf", args)
        self.assertEqual(args[args.index("-vf") + 1], "scale=-2:720")

    def test_no_audio_stream_gets_an(self):
        plan = TranscodePlan()
        args = build_args(plan, INFO_NO_AUDIO, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-an", args)
        self.assertNotIn("-c:a", args)

    def test_target_size_overrides_quality(self):
        plan = TranscodePlan(target_size_mb=20.0, audio_bitrate_kbps=128)
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-b:v", args)
        self.assertNotIn("-crf", args)

    def test_bitrate_mode_constrains_peak(self):
        """只给 -b:v 管不住体积：短视频 ABR 收敛不了，实测会超目标近一倍。"""
        plan = TranscodePlan(target_size_mb=20.0)
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-maxrate", args)
        self.assertIn("-bufsize", args)
        maxrate = args[args.index("-maxrate") + 1]
        self.assertTrue(maxrate.endswith("k"))

    def test_quality_mode_has_no_bitrate_caps(self):
        plan = TranscodePlan(video_codec="libx264", quality_value=26)
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertNotIn("-maxrate", args)
        self.assertIn("-crf", args)

    def test_target_larger_than_source_falls_back_to_quality(self):
        """源文件只有 253KB 却要求压到 20MB——这是要求变大，不是压缩。

        冒烟测试里踩到过：码率被反推成 16288k，结果文件涨了 659%。
        """
        tiny = VideoInfo(
            path="in.mp4", duration_sec=10.0, size_bytes=253_000,
            video_codec="h264", width=1280, height=720, audio_codec="aac",
        )
        plan = TranscodePlan(target_size_mb=20.0)
        args = build_args(plan, tiny, "in.mp4", "out.mp4", ["libx264"])
        self.assertIn("-crf", args)
        self.assertNotIn("-b:v", args)

    def test_progress_flags_present(self):
        plan = TranscodePlan()
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertEqual(args[args.index("-progress") + 1], "pipe:1")
        # 绝对不能出现 -nostdin，否则写 q 取消会失效
        self.assertNotIn("-nostdin", args)

    def test_illegal_container_falls_back_to_mp4(self):
        plan = TranscodePlan(container="avi")
        args = build_args(plan, INFO_1080P, "in.mp4", "out.mp4", ["libx264"])
        self.assertTrue(args[-1].endswith(".mp4") or args[-1] == "out.mp4")

    def test_input_output_positions(self):
        plan = TranscodePlan()
        args = build_args(plan, INFO_1080P, "我的 视频.mp4", "输出.mp4", ["libx264"])
        self.assertEqual(args[args.index("-i") + 1], "我的 视频.mp4")
        self.assertEqual(args[-1], "输出.mp4")

    def test_audio_args_respects_plan(self):
        plan = TranscodePlan(audio_bitrate_kbps=96)
        args = build_audio_args(plan, INFO_1080P)
        self.assertEqual(args, ["-c:a", "aac", "-b:a", "96k"])

    def test_audio_bitrate_clamped(self):
        plan = TranscodePlan(audio_bitrate_kbps=9999)
        args = build_audio_args(plan, INFO_1080P)
        self.assertEqual(args[args.index("-b:a") + 1], "320k")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestProfessionalParams(unittest.TestCase):
    """高级设置里的参数：转正、静音、音轨处理。

    这些是"会打开那一层的人才用"的选项，但拼错了就是坏文件，必须钉住。
    """

    def test_rotation_runs_before_scale(self):
        plan = TranscodePlan(rotation=90, scale="720p")
        args = build_video_args(plan, INFO_1080P, "libx264")
        vf = args[args.index("-vf") + 1]
        # 先转正再缩放。反过来的话缩放会按歪的宽高算，尺寸差一倍
        self.assertEqual(vf, "transpose=1,scale=-2:720")

    def test_rotation_alone_needs_no_scale(self):
        args = build_video_args(TranscodePlan(rotation=270), INFO_1080P, "libx264")
        self.assertEqual(args[args.index("-vf") + 1], "transpose=2")

    def test_rotation_180_uses_flip(self):
        args = build_video_args(TranscodePlan(rotation=180), INFO_1080P, "libx264")
        self.assertEqual(args[args.index("-vf") + 1], "hflip,vflip")

    def test_illegal_rotation_is_ignored(self):
        args = build_video_args(TranscodePlan(rotation=45), INFO_1080P, "libx264")
        self.assertNotIn("-vf", args)

    def test_strip_audio_wins_over_everything(self):
        plan = TranscodePlan(strip_audio=True, audio_codec="copy", audio_sample_rate=48000)
        self.assertEqual(build_audio_args(plan, INFO_1080P), ["-an"])

    def test_no_source_audio_still_an(self):
        self.assertEqual(build_audio_args(TranscodePlan(), INFO_NO_AUDIO), ["-an"])

    def test_stream_copy_drops_every_other_audio_flag(self):
        # 复制音轨时再给 -b:a / -ar / -ac，ffmpeg 会直接报错
        plan = TranscodePlan(audio_codec="copy", audio_bitrate_kbps=192,
                             audio_sample_rate=48000, audio_channels=1)
        self.assertEqual(build_audio_args(plan, INFO_1080P), ["-c:a", "copy"])

    def test_mp3_maps_to_real_encoder_name(self):
        plan = TranscodePlan(audio_codec="mp3")
        self.assertEqual(build_audio_args(plan, INFO_1080P)[:2], ["-c:a", "libmp3lame"])

    def test_sample_rate_and_channels(self):
        plan = TranscodePlan(audio_sample_rate=44100, audio_channels=1)
        args = build_audio_args(plan, INFO_1080P)
        self.assertEqual(args[args.index("-ar") + 1], "44100")
        self.assertEqual(args[args.index("-ac") + 1], "1")

    def test_zero_means_leave_alone(self):
        args = build_audio_args(TranscodePlan(), INFO_1080P)
        self.assertNotIn("-ar", args)
        self.assertNotIn("-ac", args)


if __name__ == "__main__":
    unittest.main()
