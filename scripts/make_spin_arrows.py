"""生成数值框上下箭头的两张小图。

为什么不写在 QSS 里：
Qt 的 QSS 不支持用 border 拼三角形（浏览器里那套 width:0 + 透明边框）。
写下去 Qt 会把剩下的边框画成实心矩形——界面上就是两个灰色小方块。
而给 QSpinBox 设 NoButtons 去掉按钮、只靠 padding，会让输入区被算成 1px 宽：
框还在，字全没了。

所以绕开 QSS 画图形这件事，直接给两张 PNG。

用法：python scripts/make_spin_arrows.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "videobox" / "ui" / "assets"

# 画大一点再让 QSS 缩小显示：Qt 缩放时会平滑处理，
# 直接画 8x5 的话边缘是硬的，灰色三角看着会发毛
W, H = 16, 10
COLOR = "#86909C"


def build(kind: str, path: Path) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(COLOR))

    inset = 2
    if kind == "up":
        pts = [QPointF(inset, H - inset - 1),
               QPointF(W / 2, inset + 1),
               QPointF(W - inset, H - inset - 1)]
    else:
        pts = [QPointF(inset, inset + 1),
               QPointF(W / 2, H - inset - 1),
               QPointF(W - inset, inset + 1)]
    painter.drawPolygon(QPolygonF(pts))
    painter.end()

    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path)):
        raise SystemExit(f"写入失败：{path}")
    print(f"  → {path.relative_to(ROOT)}  {W}x{H}")


def main() -> int:
    print("生成数值框箭头…")
    build("up", OUT_DIR / "spin_up.png")
    build("down", OUT_DIR / "spin_down.png")
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
