"""录制演示 GIF：在应用内部按帧抓取窗口，再用 ffmpeg 合成动图。

为什么不用录屏工具：录桌面会带进任务栏、通知弹窗、其他窗口，
不同机器 DPI 缩放还会让偏移错位。直接在进程内 grab() 窗口，
拿到的是干净、可复现、尺寸固定的帧序列。

用法：
    python scripts/make_demo_gif.py [视频路径] [需求描述]
产物：
    docs/demo.gif（README 顶部用）
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videobox.app import install_excepthook, load_stylesheet  # noqa: E402
from videobox.infra.ffmpeg_bin import find_binaries  # noqa: E402
from videobox.infra.logging_setup import setup_logging  # noqa: E402
from videobox.ui.main_window import MainWindow  # noqa: E402

from e2e_ui import Driver  # noqa: E402  复用同一套状态机，保证录的就是真流程

FRAME_DIR = ROOT / "build" / "demo_frames"
OUT_GIF = ROOT / "docs" / "demo.gif"
CAPTURE_MS = 120  # 约 8fps，够表现进度条又不至于帧数爆炸
GIF_WIDTH = 880


class RecordingDriver(Driver):
    """在驱动流程的同时，每个 tick 抓一帧。"""

    def __init__(self, window: MainWindow, video: str, request: str):
        super().__init__(window, video, request)
        self.frames: list[str] = []
        self.frame_seq = 0

    def tick(self) -> None:
        # 先抓帧再推进状态，保证关键动作的前一帧也在
        self._capture()
        super().tick()

    def _capture(self) -> None:
        if self.stage == "shooting":
            return
        self.frame_seq += 1
        path = FRAME_DIR / f"f{self.frame_seq:05d}.png"
        self.w.grab().save(str(path), "PNG")
        self.frames.append(str(path))

    def _final_shot(self) -> None:
        # 收尾多停两秒，让结果行在 GIF 结尾有停留感
        self._capture()
        QTimer.singleShot(1500, lambda: (self._capture(), super(RecordingDriver, self)._final_shot()))


def encode_gif(ffmpeg: str, frames: int) -> None:
    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    capture_fps = max(1, round(1000 / CAPTURE_MS))
    # 真实流程 4~5 秒就跑完了，按原速播出来是一团糊。
    # 直接把「输入帧率」设成 3fps，等于让每帧停留 1/3 秒，
    # 总时长被拉到十几秒，人眼才跟得上（fps 滤镜只丢帧、不拉伸时间轴，不能用）。
    play_fps = 3
    palette = ROOT / "build" / "palette.png"
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error",
            "-framerate", str(play_fps), "-i", str(FRAME_DIR / "f%05d.png"),
            "-vf", f"scale={GIF_WIDTH}:-1:flags=lanczos,palettegen=stats_mode=diff",
            str(palette),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error",
            "-framerate", str(play_fps), "-i", str(FRAME_DIR / "f%05d.png"),
            "-i", str(palette),
            "-lavfi",
            f"scale={GIF_WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
            "-loop", "0", str(OUT_GIF),
        ],
        check=True,
    )
    size_mb = OUT_GIF.stat().st_size / 1048576
    print(f"GIF → {OUT_GIF.relative_to(ROOT)}  {frames} 帧  {size_mb:.1f} MB  {frames / play_fps:.0f}s")


def main() -> int:
    video = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "tests" / "fixtures" / "demo_1080p.mp4")
    request = sys.argv[2] if len(sys.argv) > 2 else "发微信朋友圈，别超过 20MB"

    if FRAME_DIR.exists():
        shutil.rmtree(FRAME_DIR)
    FRAME_DIR.mkdir(parents=True, exist_ok=True)

    setup_logging()
    app = QApplication(sys.argv)
    load_stylesheet(app)
    install_excepthook(app)

    QSettings("VideoBox", "VideoBox").remove("window/geometry")
    window = MainWindow()
    # 先退出最大化再 resize：最大化状态下 resize 会被忽略
    window.setWindowState(Qt.WindowState.WindowNoState)
    window.resize(1180, 900)
    window.show()

    driver = RecordingDriver(window, video, request)
    timer = QTimer()
    timer.timeout.connect(driver.tick)
    timer.start(CAPTURE_MS)

    code = app.exec()

    bins = find_binaries()
    if not bins.ok:
        print("找不到 ffmpeg，无法合成 GIF")
        return 2
    print(f"抓到 {len(driver.frames)} 帧，开始合成")
    encode_gif(bins.ffmpeg, len(driver.frames))
    return code


if __name__ == "__main__":
    sys.exit(main())
