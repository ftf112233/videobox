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
# 比原来的 #86909C 深一档：浅灰在白色输入框里太淡，
# 缩到 8x5 之后只剩几个像素，看着像脏点而不是箭头
COLOR = "#5C636E"


def build(kind: str, path: Path, size: tuple[int, int] = (W, H),
          color: str = COLOR) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

    w, h = size
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))

    inset = max(1, w // 8)
    if kind == "up":
        pts = [QPointF(inset, h - inset - 1),
               QPointF(w / 2, inset + 1),
               QPointF(w - inset, h - inset - 1)]
    else:
        pts = [QPointF(inset, inset + 1),
               QPointF(w / 2, h - inset - 1),
               QPointF(w - inset, inset + 1)]
    painter.drawPolygon(QPolygonF(pts))
    painter.end()

    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path)):
        raise SystemExit(f"写入失败：{path}")
    print(f"  → {path.relative_to(ROOT)}  {w}x{h}  {color}")


def main() -> int:
    print("生成控件箭头…")
    build("up", OUT_DIR / "spin_up.png")
    build("down", OUT_DIR / "spin_down.png")
    # 下拉框用的三角比数值框的大一号、颜色也深一点：
    # 它常出现在白底上，浅灰会淡到看不出来，而"看不出能点"等于这个控件不存在
    build("down", OUT_DIR / "chevron_down.png", size=(20, 12), color="#5C636E")
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
