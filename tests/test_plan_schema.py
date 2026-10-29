"""plan_schema 单测：重点是「模型给的说明文字」怎么变成用户能读的一句话。"""

from __future__ import annotations

import unittest

from videobox.core.plan_schema import _coerce_reasons, plan_from_payload


class TestCoerceReasons(unittest.TestCase):
    def test_plain_strings(self):
        out = _coerce_reasons(["手机上看着够清晰", "上传也快"])
        self.assertEqual(out, ["手机上看着够清晰", "上传也快"])

    def test_legacy_object_shape_still_works(self):
        # 老格式 {"param","why","confidence"} 不能让用户看到 param 和 confidence，
        # 但也不能因为模型没按新 schema 输出就整条丢掉
        out = _coerce_reasons([{"param": "quality", "why": "画质够用", "confidence": 0.9}])
        self.assertEqual(out, ["画质够用"])

    def test_confidence_note_is_stripped(self):
        out = _coerce_reasons(["手机上够清晰（置信度 85%）"])
        self.assertEqual(out, ["手机上够清晰"])

    def test_empty_and_limit(self):
        self.assertEqual(_coerce_reasons(None), [])
        self.assertEqual(_coerce_reasons(["", "  ", None]), [])
        self.assertEqual(len(_coerce_reasons([f"第{i}条" for i in range(9)])), 5)


class TestPlanReasons(unittest.TestCase):
    def test_plan_carries_reasons_as_strings(self):
        payload = {
            "preset": "微信朋友圈",
            "container": "mp4",
            "reasons": ["手机上看着够清晰", {"why": "体积能压到能发的程度"}],
            "risks": ["横屏小字可能有点糊"],
        }
        plan, _warnings = plan_from_payload(payload, ["libx264"])
        self.assertEqual(plan.reasons, ["手机上看着够清晰", "体积能压到能发的程度"])
        self.assertEqual(plan.risks, ["横屏小字可能有点糊"])

    def test_plan_tolerates_missing_reasons(self):
        plan, _warnings = plan_from_payload({"preset": "x"}, ["libx264"])
        self.assertEqual(plan.reasons, [])


if __name__ == "__main__":
    unittest.main()
