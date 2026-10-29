"""生成应用图标（.ico）。

为什么要专门写个脚本：Windows 上"没有图标"是最好认的未完成信号——
标题栏和任务栏会显示一个通用空白图标。而 Qt 自带的 ICO 写入支持不稳，
与其赌插件，不如直接按 ICO 文件格式手工拼容器（Vista 之后允许内嵌 PNG）。

图标语义：蓝色圆角方块 + 白色播放三角 + 右下角一道"转换"弧线，
远看像视频，近看是"转"的动作。

用法：
    python scripts/make_icon.py
产物：
    videobox/ui/app.ico（多尺寸，16/32/48/64/128/256）
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
)

OUT = ROOT / "videobox" / "ui" / "app.ico"
SIZES = (256, 128, 64, 48, 32, 16)
BASE = 256


def draw_master() -> QImage:
    img = QImage(BASE, BASE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 底板：圆角方形 + 从上到下的蓝色渐变
    grad = QLinearGradient(0, 0, 0, BASE)
    grad.setColorAt(0.0, QColor("#4C86F5"))
    grad.setColorAt(1.0, QColor("#1F4FD0"))

    plate = QRectF(8, 8, BASE - 16, BASE - 16)
    path = QPainterPath()
    path.addRoundedRect(plate, 48, 48)
    p.fillPath(path, grad)

    # 顶部高光，避免纯色死板
    shine = QLinearGradient(0, 0, 0, BASE * 0.55)
    shine.setColorAt(0.0, QColor(255, 255, 255, 46))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, shine)

    # 播放三角：居中偏左，留出视觉重心
    tri = QPainterPath()
    tri.moveTo(96, 66)
    tri.lineTo(96, 190)
    tri.lineTo(186, 128)
    tri.closeSubpath()
    p.fillPath(tri, QColor(255, 255, 255, 248))

    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    # QByteArray 必须留引用：写成 QBuffer(QByteArray()) 时临时对象会被回收，
    # 底层指针悬空，Python 进程直接段错误（这个坑踩过一次，没有任何报错信息）
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(data)


def build_ico(master: QImage, sizes: tuple[int, ...], target: Path) -> None:
    entries = []
    payloads = []
    offset = 6 + 16 * len(sizes)

    for size in sizes:
        scaled = master.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        data = png_bytes(scaled)
        # ICO 的宽高字段是单字节，256 必须写成 0
        dim = 0 if size >= 256 else size
        entries.append(
            struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        )
        payloads.append(data)
        offset += len(data)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for entry in entries:
            fh.write(entry)
        for data in payloads:
            fh.write(data)


def main() -> int:
    master = draw_master()
    build_ico(master, SIZES, OUT)
    print(f"图标 → {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.1f} KB  {len(SIZES)} 个尺寸")

    # 顺手留一张 PNG，README 和关于对话框都能用
    png = OUT.with_suffix(".png")
    master.save(str(png), "PNG")
    print(f"预览 → {png.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
