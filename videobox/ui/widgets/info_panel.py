"""左栏：大缩略图 + 源文件信息。

缩略图放在这里当视觉主角，是因为笔试题第 1 条明确要求"获取到视频的缩略图
显示出来"——把它做小做偏，等于把最直白的验收点藏起来。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.models import VideoInfo

THUMB_W, THUMB_H = 420, 236


class InfoPanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("源文件")
        title.setObjectName("CardTitle")
        root.addWidget(title)

        self.thumb = QLabel("拖一个视频到这里\n或点击「打开文件」")
        self.thumb.setObjectName("Thumb")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root.addWidget(self.thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.filename = QLabel("尚未选择文件")
        self.filename.setObjectName("Value")
        self.filename.setWordWrap(True)
        self.filename.setStyleSheet("font-weight: 600; font-size: 14px;")
        root.addWidget(self.filename)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)
        self._fields: dict[str, QLabel] = {}
        rows = [
            ("时长", "duration"), ("分辨率", "resolution"),
            ("帧率", "fps"), ("体积", "size"),
            ("视频编码", "vcodec"), ("音频编码", "acodec"),
        ]
        for idx, (label, key) in enumerate(rows):
            row = idx
            name = QLabel(label)
            name.setObjectName("Hint")
            value = QLabel("—")
            value.setObjectName("Value")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self._fields[key] = value
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addStretch(1)

    # ---------- 对外接口 ----------
    def set_drag_active(self, active: bool) -> None:
        """拖拽悬停时给视觉反馈。

        不做这一步的话，用户拖着文件停在窗口上方，界面毫无反应——
        他不知道能不能放、该放哪里，只能凭猜。这是"能感知"和"能猜"的区别。
        """
        if active:
            self.thumb.setStyleSheet(
                "background: #EAF1FE; border: 2px dashed #2F6FED;"
                " border-radius: 8px; color: #2F6FED; font-size: 14px;"
            )
            self.thumb.setText("松开鼠标即可载入")
            return

        if self.thumb.pixmap().isNull():
            self.thumb.setStyleSheet("")
            self.thumb.setText("拖一个视频到这里\n或点击「打开文件」")
        else:
            self.thumb.setStyleSheet(
                "background: #000; border: 1px solid #E5E6EB; border-radius: 8px;"
            )

    def show_info(self, info: VideoInfo) -> None:
        from pathlib import Path

        from ...core import labels

        self.filename.setText(Path(info.path).name)
        f = self._fields
        f["duration"].setText(info.duration_label)
        f["resolution"].setText(info.resolution_label)
        f["fps"].setText(f"{info.fps:.0f} 帧/秒" if info.fps else "—")
        f["size"].setText(info.size_label)
        # 只显示行业通用写法：h264 → H.264。
        # 像素格式（yuv420p）和采样率（48000 Hz）是给调试用的，
        # 放在这儿除了让面板显得专业，对用户没有任何用处。
        f["vcodec"].setText(labels.video_codec_name(info.video_codec))
        f["acodec"].setText(
            labels.audio_codec_name(info.audio_codec) if info.has_audio else "无音轨"
        )

    def show_thumbnail(self, image: QImage | None) -> None:
        """接收工作线程产出的 QImage，在这里转成 QPixmap。

        QPixmap 只能在 GUI 线程创建，跨线程使用会直接崩——所以线程里
        只允许产出 QImage。
        """
        if image is None or image.isNull():
            self.thumb.setText("缩略图抽取失败\n（不影响转码）")
            return
        pix = QPixmap.fromImage(image).scaled(
            self.thumb.width(), self.thumb.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb.setPixmap(pix)
        self.thumb.setStyleSheet(
            "background: #000; border: 1px solid #E5E6EB; border-radius: 8px;"
        )

    def reset(self) -> None:
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("拖一个视频到这里\n或点击「打开文件」")
        self.thumb.setStyleSheet("")
        self.filename.setText("尚未选择文件")
        for v in self._fields.values():
            v.setText("—")
