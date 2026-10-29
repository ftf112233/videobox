"""底部：转码进度、取消、以及转码前后的对比结果。

前后对比是"可量化优化"的落点——用户不用听你吹压缩率，
他自己看得见 253KB → 231KB、耗时 0.9s、13.9 倍速。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ...core.models import TranscodeResult


class ProgressPanel(QFrame):
    start_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        # ---- 进度行 ----
        line = QHBoxLayout()
        line.setSpacing(14)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        line.addWidget(self.bar, 1)

        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("Value")
        self.percent_label.setFixedWidth(52)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(self.percent_label)

        self.eta_label = QLabel("—")
        self.eta_label.setObjectName("Hint")
        self.eta_label.setFixedWidth(96)
        line.addWidget(self.eta_label)

        self.start_btn = QPushButton("开始转码")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self.start_clicked.emit)
        line.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setMinimumWidth(88)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self.cancel_btn.hide()
        line.addWidget(self.cancel_btn)

        root.addLayout(line)

        # ---- 结果行 ----
        self.result_label = QLabel("")
        self.result_label.setObjectName("Hint")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.result_label)

    # ---------- 对外接口 ----------
    def set_start_enabled(self, enabled: bool) -> None:
        """没有视频、没有方案时按钮不可点。

        让按钮灰着，比让他点一下再弹"请先打开一个视频文件"要诚实。
        """
        self.start_btn.setEnabled(enabled)

    def set_idle(self) -> None:
        self.bar.setValue(0)
        self.percent_label.setText("0%")
        self.eta_label.setText("—")
        self.start_btn.show()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("开始转码")
        self.cancel_btn.hide()

    def set_running(self, codec_label: str) -> None:
        self.start_btn.hide()
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.result_label.setObjectName("Hint")
        self.result_label.setStyleSheet("color: #646A73;")
        self.result_label.setText(f"正在使用{codec_label}转码…")
        self._restyle(self.result_label)

    def update_progress(self, percent: float, eta_text: str, speed: float) -> None:
        self.bar.setValue(int(max(0.0, min(1.0, percent)) * 1000))
        self.percent_label.setText(f"{percent * 100:.0f}%")
        self.eta_label.setText(eta_text if speed > 0.01 else "测速中…")

    def show_result(self, result: TranscodeResult, codec_label: str) -> None:
        self.cancel_btn.hide()
        self.start_btn.show()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("再转一次")

        if result.cancelled:
            self.result_label.setStyleSheet("color: #D25F00;")
            self.result_label.setText("已取消。ffmpeg 已正常收尾，输出文件仍可播放。")
            return

        if result.ok:
            self.bar.setValue(1000)
            self.percent_label.setText("100%")
            self.eta_label.setText("完成")
            self.result_label.setStyleSheet("color: #00A55B;")
            name = Path(result.output_path).name
            parts = [
                "✓ 转码完成",
                f"{_fmt_size(result.input_size_bytes)} → {_fmt_size(result.output_size_bytes)}"
                f"（{result.size_delta_label}）",
                f"耗时 {result.elapsed_sec:.1f} 秒",
                f"{result.speed:.1f} 倍速" if result.speed > 0.01 else "",
                codec_label,
                f"已保存为 {name}（和原片在同一个文件夹）",
            ]
            self.result_label.setText("　·　".join(p for p in parts if p))
            self.result_label.setToolTip(result.output_path)
        else:
            self.result_label.setStyleSheet("color: #F53F3F;")
            self.result_label.setText(f"✗ 转码失败：{result.error_message}")

    def show_error(self, message: str) -> None:
        self.result_label.setStyleSheet("color: #F53F3F;")
        self.result_label.setText(message)

    def show_note(self, message: str) -> None:
        self.result_label.setStyleSheet("color: #646A73;")
        self.result_label.setText(message)

    def _restyle(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def _fmt_size(num_bytes: int) -> str:
    from ...core.models import format_size

    return format_size(num_bytes)
