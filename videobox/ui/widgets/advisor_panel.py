"""右栏：需求输入 → 参数方案 → 理由说明。

设计要点：AI 产出的参数必须"可看、可改、可解释"。
- 可看：每个参数是一个明确控件，不是一段散文
- 可改：用户改完能直接转码，不必回头再问一次 AI
- 可解释：每条建议附一句理由和置信度，用户能判断该不该信
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...core.models import CONTAINERS, SCALE_TARGETS, TranscodePlan


class AdvisorPanel(QFrame):
    request_summary = Signal(str)   # 用户点了"获取建议"
    plan_changed = Signal()         # 参数被手动改动

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ---- 标题行 + 模式徽章 ----
        head = QHBoxLayout()
        title = QLabel("转码方案")
        title.setObjectName("CardTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.badge = QLabel("本地规则")
        self.badge.setObjectName("BadgeLocal")
        head.addWidget(self.badge)
        root.addLayout(head)

        # ---- 人话输入 ----
        hint = QLabel("用一句话说清你要拿这个视频干什么")
        hint.setObjectName("Hint")
        root.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.request_edit = QLineEdit()
        self.request_edit.setPlaceholderText("例如：发微信朋友圈，别超过 20MB")
        self.request_edit.returnPressed.connect(self._emit_request)
        row.addWidget(self.request_edit, 1)
        self.ask_btn = QPushButton("获取建议")
        self.ask_btn.clicked.connect(self._emit_request)
        row.addWidget(self.ask_btn)
        root.addLayout(row)

        self.preset_label = QLabel("尚无方案")
        self.preset_label.setObjectName("Muted")
        root.addWidget(self.preset_label)

        # ---- 参数区 ----
        params = QGridLayout()
        params.setHorizontalSpacing(10)
        params.setVerticalSpacing(9)

        self.container_box = QComboBox()
        self.container_box.addItems(CONTAINERS)
        self.scale_box = QComboBox()
        self.scale_box.addItems(list(SCALE_TARGETS.keys()))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(18, 35)
        self.quality_spin.setToolTip("数值越小画质越好、体积越大。18~35 是安全区间。")
        self.audio_spin = QSpinBox()
        self.audio_spin.setRange(32, 320)
        self.audio_spin.setSingleStep(16)
        self.audio_spin.setSuffix(" kbps")
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0, 10240)
        self.target_spin.setDecimals(1)
        self.target_spin.setSuffix(" MB")
        self.target_spin.setSpecialValueText("不限")
        self.codec_label = QLabel("待探测")
        self.codec_label.setObjectName("Value")

        specs = [
            ("容器", self.container_box), ("分辨率", self.scale_box),
            ("质量", self.quality_spin), ("音频码率", self.audio_spin),
            ("目标体积", self.target_spin), ("编码器", self.codec_label),
        ]
        for idx, (label, widget) in enumerate(specs):
            r, c = divmod(idx, 2)
            cell = QVBoxLayout()
            cell.setSpacing(4)
            name = QLabel(label)
            name.setObjectName("Hint")
            cell.addWidget(name)
            cell.addWidget(widget)
            params.addLayout(cell, r, c)
        params.setColumnStretch(0, 1)
        params.setColumnStretch(1, 1)
        root.addLayout(params)

        for widget in (self.container_box, self.scale_box):
            widget.currentIndexChanged.connect(lambda _: self.plan_changed.emit())
        for widget in (self.quality_spin, self.audio_spin, self.target_spin):
            widget.valueChanged.connect(lambda _: self.plan_changed.emit())

        # ---- 理由 ----
        reason_label = QLabel("为什么这么选")
        reason_label.setObjectName("Hint")
        root.addWidget(reason_label)

        self.reason_list = QListWidget()
        self.reason_list.setMinimumHeight(150)
        # 理由往往是一整句话，不换行会被截断成"...置信"，等于白写
        self.reason_list.setWordWrap(True)
        root.addWidget(self.reason_list, 1)

        # ---- 命令预览 ----
        cmd_label = QLabel("将要执行的命令")
        cmd_label.setObjectName("Hint")
        root.addWidget(cmd_label)
        self.command_label = QLabel("—")
        self.command_label.setObjectName("CommandBox")
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.command_label)

    # ---------- 内部 ----------
    def _emit_request(self) -> None:
        self.request_summary.emit(self.request_edit.text().strip())

    # ---------- 对外接口 ----------
    def set_busy(self, busy: bool) -> None:
        self.ask_btn.setEnabled(not busy)
        self.ask_btn.setText("思考中…" if busy else "获取建议")

    def apply_plan(self, plan: TranscodePlan, warnings: list[str], used_ai: bool) -> None:
        self.badge.setText("AI 顾问" if used_ai else "本地规则")
        self.badge.setObjectName("BadgeAI" if used_ai else "BadgeLocal")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

        self.preset_label.setText(f"当前方案：{plan.preset_name}（来源：{plan.source_label}）")

        # 更新控件时先断开，避免触发一串 plan_changed
        for w in (self.container_box, self.scale_box):
            w.blockSignals(True)
        for w in (self.quality_spin, self.audio_spin, self.target_spin):
            w.blockSignals(True)

        if plan.container in CONTAINERS:
            self.container_box.setCurrentText(plan.container)
        if plan.scale in SCALE_TARGETS:
            self.scale_box.setCurrentText(plan.scale)
        self.quality_spin.setValue(plan.quality_value)
        self.audio_spin.setValue(plan.audio_bitrate_kbps)
        self.target_spin.setValue(plan.target_size_mb or 0)

        for w in (self.container_box, self.scale_box):
            w.blockSignals(False)
        for w in (self.quality_spin, self.audio_spin, self.target_spin):
            w.blockSignals(False)

        self.reason_list.clear()
        for item in plan.reasons:
            conf = item.get("confidence", 0.0)
            text = f"{item.get('why', '')}　（{item.get('param', '')}，置信度 {conf:.0%}）"
            entry = QListWidgetItem(f"·  {text}")
            entry.setToolTip(text)
            self.reason_list.addItem(entry)
        for risk in plan.risks:
            entry = QListWidgetItem(f"⚠  {risk}")
            entry.setForeground(Qt.GlobalColor.darkYellow)
            self.reason_list.addItem(entry)
        for warning in warnings:
            entry = QListWidgetItem(f"⚠  已修正：{warning}")
            entry.setForeground(Qt.GlobalColor.darkYellow)
            self.reason_list.addItem(entry)

        if not self.reason_list.count():
            self.reason_list.addItem("（本地方案没有附加说明）")

    def current_overrides(self) -> dict:
        """用户在界面上的手动修改，覆盖到 plan 上。"""
        return {
            "container": self.container_box.currentText(),
            "scale": self.scale_box.currentText(),
            "quality_value": self.quality_spin.value(),
            "audio_bitrate_kbps": self.audio_spin.value(),
            "target_size_mb": self.target_spin.value() or None,
        }

    def show_command(self, command: str) -> None:
        self.command_label.setText(command)

    def set_codec_text(self, text: str) -> None:
        self.codec_label.setText(text)

    def reset(self) -> None:
        self.request_edit.clear()
        self.preset_label.setText("尚无方案")
        self.reason_list.clear()
        self.command_label.setText("—")
        self.badge.setText("本地规则")
        self.badge.setObjectName("BadgeLocal")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
