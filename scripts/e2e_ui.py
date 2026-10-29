"""UI 端到端自动化：载入 → 顾问 → 转码 → 截图 → 退出。

两个用途：
1. 回归验证：改完界面跑一遍，确认整条动线没断
2. 出图：自动截图存到 docs/screenshots/，README 直接用

用法：
    python scripts/e2e_ui.py [视频路径] [需求描述]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videobox.app import install_excepthook, load_stylesheet  # noqa: E402
from videobox.infra.logging_setup import setup_logging  # noqa: E402
from videobox.ui.main_window import MainWindow  # noqa: E402

SHOT_DIR = ROOT / "docs" / "screenshots"
REQUEST = "发微信朋友圈，别超过 20MB"


class Driver:
    """极简状态机：轮询窗口状态，按阶段推进。"""

    def __init__(self, window: MainWindow, video: str, request: str):
        self.w = window
        self.video = video
        self.request = request
        self.stage = "wait_env"
        self.ticks = 0
        self.max_ticks = 600  # 200ms * 600 = 120s 上限
        self.transcode_started_at = -1

    def tick(self) -> None:
        self.ticks += 1
        if self.ticks > self.max_ticks:
            print("!! 超时，当前阶段:", self.stage)
            self._finish(1)
            return

        if self.stage == "wait_env":
            if self.w.binaries.ok:
                print(f"[1/5] 环境就绪：{self.w.binaries.source}")
                print(f"      可用编码器：{self.w.available_codecs}")
                QTimer.singleShot(300, lambda: self._shot("01_empty"))
                self.stage = "load"
                self.advance_at = self.ticks + 3
            return

        if self.stage == "load":
            if self.ticks < getattr(self, "advance_at", 0):
                return
            print(f"[2/5] 载入 {Path(self.video).name}")
            self.w._load_video(self.video)
            self.stage = "wait_info"
            return

        if self.stage == "wait_info":
            # 还要等默认方案落地：载入后的第一帧应该是"可以开始转码"的状态，
            # 而不是参数区还灰着、按钮还没亮
            if self.w.info is not None and self.w.plan is not None:
                print(f"[3/5] 解析完成：{self.w.info.summary_line()}")
                QTimer.singleShot(600, lambda: self._shot("02_loaded"))
                self.stage = "advise"
                self.advance_at = self.ticks + 4
            return

        if self.stage == "advise":
            if self.ticks < getattr(self, "advance_at", 0):
                return
            print(f"[4/5] 请求方案：{self.request!r}")
            self.w.advisor_panel.request_edit.setText(self.request)
            # 不取消选中，截图里输入框会是一片蓝色高亮，看着像出错
            self.w.advisor_panel.request_edit.deselect()
            self.w._on_request_summary(self.request)
            self.stage = "wait_plan"
            self.advance_at = self.ticks + 6
            return

        if self.stage == "wait_plan":
            # 顾问可能是异步的（AI 模式），要等按钮恢复且方案真的落到窗口上
            busy = self.w.advisor_panel.ask_btn.text() != "获取建议"
            plan = self.w._current_plan()
            if busy or plan is None:
                return
            print(f"      方案：{plan.preset_name} / {plan.scale} / q={plan.quality_value}")
            # 先把"方案就绪、尚未开始"这一帧截下来，再启转码。
            # 反过来的话截到的是进度 0% + 取消按钮，看着像卡住了。
            QTimer.singleShot(400, lambda: self._shot("03_advised"))
            self.stage = "starting"
            self.advance_at = self.ticks + 5
            return

        if self.stage == "starting":
            if self.ticks < getattr(self, "advance_at", 0):
                return
            print("[5/5] 开始转码")
            self.w._start_transcode()
            self.stage = "wait_done"
            self.transcode_started_at = self.ticks
            return

        if self.stage == "wait_done":
            if self.w.runner is None:
                print("[完成] 转码结束，截图")
                QTimer.singleShot(500, self._final_shot)
                self.stage = "shooting"
            return

        if self.stage == "shooting":
            return

    def _shot(self, name: str) -> None:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"{name}.png"
        self.w.grab().save(str(path), "PNG")
        print(f"      截图 → {path.relative_to(ROOT)}")

    def _final_shot(self) -> None:
        self._shot("04_done")
        self._finish(0)

    def _finish(self, code: int) -> None:
        QApplication.instance().exit(code)


def main() -> int:
    video = sys.argv[1] if len(sys.argv) > 1 else str(
        ROOT / "tests" / "fixtures" / "sample_720p.mp4"
    )
    request = sys.argv[2] if len(sys.argv) > 2 else REQUEST

    setup_logging()
    app = QApplication(sys.argv)
    load_stylesheet(app)
    install_excepthook(app)

    # 截图要可复现：清掉上次运行留在输入框里的需求，
    # 否则空状态截图会带着一句历史文案，看着像没清干净
    QSettings("VideoBox", "VideoBox").remove("session/last_request")

    window = MainWindow()
    window.show()

    driver = Driver(window, video, request)
    timer = QTimer()
    timer.timeout.connect(driver.tick)
    timer.start(200)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
