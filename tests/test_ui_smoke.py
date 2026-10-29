"""界面冒烟测试：不启动完整窗口，只验右栏的行为契约。

存在的理由很具体——这次改版时用脚本批量替换代码，有两个方法定义
被静默漏掉，单元测试全绿、界面一构造就崩。界面代码必须有能自动跑的断言，
哪怕只是"面板能建起来、空状态不该有内容"这种最粗的检查。

用 offscreen 平台，不需要真实桌面会话。
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from videobox.core.models import TranscodePlan  # noqa: E402
from videobox.ui.widgets.advisor_panel import AdvisorPanel  # noqa: E402

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    _APP = QApplication.instance() or QApplication([])


def make_plan(**overrides) -> TranscodePlan:
    plan = TranscodePlan(
        preset_name="微信朋友圈",
        container="mp4",
        quality_value=24,
        scale="720p",
        audio_bitrate_kbps=96,
        target_size_mb=20.0,
        reasons=["手机上看着够清晰", "上传也快"],
        risks=["横屏小字可能有点糊"],
        source="ai",
    )
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


class TestEmptyState(unittest.TestCase):
    def test_empty_state_has_no_plan_content(self):
        panel = AdvisorPanel()
        # 没有视频之前，参数改不了、说明区不该有内容
        self.assertFalse(panel.quality_box.isEnabled())
        self.assertFalse(panel.audio_box.isEnabled())
        self.assertFalse(panel.target_spin.isEnabled())
        self.assertTrue(panel.effect_title.isHidden())
        self.assertTrue(panel.effects_host.isHidden())
        self.assertTrue(panel.detail_toggle.isHidden())
        self.assertIn("载入", panel.preset_label.text())


class TestApplyPlan(unittest.TestCase):
    def setUp(self):
        self.panel = AdvisorPanel()
        self.panel.apply_plan(make_plan(), [], used_ai=True)

    def test_params_become_editable(self):
        self.assertTrue(self.panel.quality_box.isEnabled())
        self.assertTrue(self.panel.effects_host.isVisibleTo(self.panel))

    def test_values_are_shown_as_levels_not_numbers(self):
        # 24 应落到"高"这一档，界面上不该出现裸 CRF 数字
        self.assertEqual(self.panel.quality_box.currentText(), "高")
        self.assertEqual(self.panel.audio_box.currentText(), "标准")

    def test_effects_render_one_line_per_reason(self):
        labels = [
            self.panel.effects_box.itemAt(i).widget().text()
            for i in range(self.panel.effects_box.count())
        ]
        self.assertEqual(len(labels), 3)  # 2 条效果 + 1 条风险
        self.assertIn("手机上看着够清晰", labels[0])
        self.assertTrue(labels[-1].startswith("⚠"))

    def test_no_confidence_or_param_names_leak(self):
        """置信度和参数名不该出现在用户能读到的任何一行里。

        这条是这次改版的核心承诺，用测试钉住，防止以后有人加回来。
        """
        texts = [
            self.panel.effects_box.itemAt(i).widget().text()
            for i in range(self.panel.effects_box.count())
        ]
        texts.append(self.panel.preset_label.text())
        for text in texts:
            self.assertNotIn("置信度", text)
            for jargon in ("confidence", "quality", "kbps", "crf", "CRF"):
                self.assertNotIn(jargon, text)

    def test_overrides_map_levels_back_to_numbers(self):
        self.panel.quality_box.setCurrentText("省体积")
        self.panel.audio_box.setCurrentText("高音质")
        overrides = self.panel.current_overrides()
        self.assertEqual(overrides["quality_value"], 30)
        self.assertEqual(overrides["audio_bitrate_kbps"], 192)

    def test_editing_marks_explanation_as_stale(self):
        self.assertTrue(self.panel.stale_hint.isHidden())
        self.panel.quality_box.setCurrentText("省体积")
        self.assertFalse(self.panel.stale_hint.isHidden())

    def test_reset_returns_to_empty_state(self):
        self.panel.reset()
        self.assertFalse(self.panel.quality_box.isEnabled())
        self.assertTrue(self.panel.effect_title.isHidden())
        self.assertEqual(self.panel.effects_box.count(), 0)


class TestNotices(unittest.TestCase):
    def test_size_notice_shows_and_hides(self):
        panel = AdvisorPanel()
        self.assertTrue(panel.notice_label.isHidden())
        panel.show_notice("原片 59 MB，比 200 MB 的目标还小")
        self.assertFalse(panel.notice_label.isHidden())
        panel.show_notice("")
        self.assertTrue(panel.notice_label.isHidden())


class TestAdvancedSync(unittest.TestCase):
    """第一层档位和第二层数值必须始终一致。

    这两层是同一个东西的两种说法。哪一层不同步，用户改了 A 却发现
    实际跑的是 B，就是最坏的那种 bug——他做了操作、看到了反馈、结果不是他想的那样。
    """

    def setUp(self):
        self.panel = AdvisorPanel()
        self.panel.apply_plan(make_plan(), [], used_ai=True)

    def test_level_drives_number(self):
        self.panel.quality_box.setCurrentText("省体积")
        self.assertEqual(self.panel.quality_spin.value(), 30)

    def test_number_drives_level(self):
        self.panel.quality_spin.setValue(20)
        self.assertEqual(self.panel.quality_box.currentText(), "极佳")

    def test_precise_value_wins_over_level(self):
        # 25 落在"高"(23) 和"标准"(26) 之间，档位显示最近的一档，
        # 但真正生效的必须是 25 这个精调值
        self.panel.quality_spin.setValue(25)
        self.assertEqual(self.panel.current_overrides()["quality_value"], 25)

    def test_audio_levels_sync_too(self):
        self.panel.audio_box.setCurrentText("高音质")
        self.assertEqual(self.panel.audio_kbps_spin.value(), 192)
        self.panel.audio_kbps_spin.setValue(64)
        self.assertEqual(self.panel.audio_box.currentText(), "省流量")

    def test_advanced_defaults_do_not_interfere(self):
        overrides = self.panel.current_overrides()
        self.assertEqual(overrides["rotation"], 0)
        self.assertEqual(overrides["audio_sample_rate"], 0)
        self.assertFalse(overrides["strip_audio"])

    def test_advanced_choices_reach_overrides(self):
        self.panel.rotation_box.setCurrentIndex(self.panel.rotation_box.findData(90))
        self.panel.strip_audio_check.setChecked(True)
        self.panel.fps_box.setCurrentIndex(self.panel.fps_box.findData("30"))
        overrides = self.panel.current_overrides()
        self.assertEqual(overrides["rotation"], 90)
        self.assertTrue(overrides["strip_audio"])
        self.assertEqual(overrides["fps"], "30")

    def test_plan_lands_in_advanced_controls(self):
        from videobox.core.models import TranscodePlan

        plan = TranscodePlan(rotation=270, strip_audio=True, fps="24",
                             audio_sample_rate=44100, audio_channels=1,
                             audio_codec="mp3", quality_value=19)
        self.panel.apply_plan(plan, [], used_ai=False)
        self.assertEqual(self.panel.quality_spin.value(), 19)
        self.assertEqual(self.panel.quality_box.currentText(), "极佳")
        self.assertEqual(self.panel.rotation_box.currentData(), 270)
        self.assertTrue(self.panel.strip_audio_check.isChecked())
        self.assertEqual(self.panel.fps_box.currentData(), "24")
        self.assertEqual(self.panel.sample_rate_box.currentData(), 44100)
        self.assertEqual(self.panel.channels_box.currentData(), 1)
        self.assertEqual(self.panel.audio_codec_box.currentData(), "mp3")


class TestEmptyGuidance(unittest.TestCase):
    """空状态要给路径，不能给一堆点不动的控件。

    之前空态摆着六个灰掉的下拉框（里面还显示 mp4 / 原画 / 极佳），
    看着像"已经配好了"，实际一个都点不动。现在换成三步引导。
    """

    def test_empty_state_shows_steps_and_hides_params(self):
        panel = AdvisorPanel()
        self.assertTrue(panel.steps_host.isVisibleTo(panel))
        self.assertFalse(panel.params_host.isVisibleTo(panel))
        # 没有视频时问顾问没有意义：输入框该收起来，
        # 而不是让用户打一句话、点按钮、再被告知"请先打开视频"
        self.assertFalse(panel.input_host.isVisibleTo(panel))
        self.assertFalse(panel.badge.isVisibleTo(panel))

    def test_steps_mention_the_optional_shortcut(self):
        """第二步必须标"可以跳过"。

        不标的话，用户会以为"不说一句话就不能转"，卡在第一步。
        """
        from PySide6.QtWidgets import QLabel

        panel = AdvisorPanel()
        joined = "".join(w.text() for w in panel.steps_host.findChildren(QLabel))
        self.assertIn("跳过", joined)

    def test_plan_swaps_guidance_for_params(self):
        panel = AdvisorPanel()
        panel.apply_plan(make_plan(), [], used_ai=True)
        self.assertFalse(panel.steps_host.isVisibleTo(panel))
        self.assertTrue(panel.params_host.isVisibleTo(panel))
        self.assertTrue(panel.input_host.isVisibleTo(panel))
        self.assertTrue(panel.badge.isVisibleTo(panel))

    def test_reset_brings_guidance_back(self):
        panel = AdvisorPanel()
        panel.apply_plan(make_plan(), [], used_ai=True)
        panel.reset()
        self.assertTrue(panel.steps_host.isVisibleTo(panel))
        self.assertFalse(panel.params_host.isVisibleTo(panel))


if __name__ == "__main__":
    unittest.main()
