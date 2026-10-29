"""右栏：需求输入 → 参数方案 → 效果说明。

设计上有过一版是给每个参数附上「理由 + 置信度」，界面渲染成
「（quality，置信度 85%）」这种东西。它回答了"AI 为什么这么选"，
但用户真正要的是"这样设我会得到什么"——前者是开发者的好奇心，
后者才是使用者的决策依据。所以这一版：

- 参数全部档位化：画质是高/标准/省体积，不是 24；音质是标准/清晰，不是 96 kbps
- 说明区只留一句人话的效果与风险，不带参数名、不带置信度
- 命令和参数修正记录收进「技术细节」，默认折叠——想验的人能验，
  不想看的人不会被一整行 ffmpeg 参数糊脸
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from ...core import labels
from ...core.models import CONTAINERS, SCALE_TARGETS, TranscodePlan


class AdvisorPanel(QFrame):
    request_summary = Signal(str)   # 用户点了"获取建议"
    plan_changed = Signal()         # 参数被手动改动

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._has_plan = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

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

        self.preset_label = QLabel("载入视频后自动生成方案")
        self.preset_label.setObjectName("Muted")
        root.addWidget(self.preset_label)

        # 参数区上方的一行提示，只在"设置和目标冲突"这类情况下出现
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("Notice")
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        root.addWidget(self.notice_label)

        # ---- 参数区（全部是选档位，没有裸数字） ----
        params = QGridLayout()
        params.setHorizontalSpacing(10)
        params.setVerticalSpacing(9)

        self.container_box = QComboBox()
        self.container_box.addItems(CONTAINERS)
        self.container_box.setToolTip("决定文件后缀。mp4 处处都能放，拿不准就选它。")

        self.scale_box = QComboBox()
        self.scale_box.addItems(list(SCALE_TARGETS.keys()))
        self.scale_box.setToolTip("原画不缩放；往下选能明显减小体积，但文字会变糊。")

        self.quality_box = QComboBox()
        self.quality_box.addItems(labels.QUALITY_LABELS)
        self.quality_box.setToolTip(labels.QUALITY_TOOLTIP)

        self.audio_box = QComboBox()
        self.audio_box.addItems(labels.AUDIO_LABELS)
        self.audio_box.setToolTip(labels.AUDIO_TOOLTIP)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0, 10240)
        self.target_spin.setDecimals(1)
        self.target_spin.setSuffix(" MB")
        self.target_spin.setSpecialValueText("不限")
        self.target_spin.setToolTip("填了就按这个体积压；留「不限」则由画质档位决定大小。")

        self.codec_label = QLabel("待检测")
        self.codec_label.setObjectName("Value")

        specs = [
            ("格式", self.container_box), ("清晰度", self.scale_box),
            ("画质", self.quality_box), ("音质", self.audio_box),
            ("文件大小", self.target_spin), ("转码方式", self.codec_label),
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

        for widget in (self.container_box, self.scale_box,
                       self.quality_box, self.audio_box):
            widget.currentIndexChanged.connect(lambda _: self._on_user_edit())
        self.target_spin.valueChanged.connect(lambda _: self._on_user_edit())

        # ---- 效果说明 ----
        self.effect_title = QLabel("这样设置的效果")
        self.effect_title.setObjectName("Hint")
        root.addWidget(self.effect_title)

        self.stale_hint = QLabel("你调过参数了，下面的说明对应的是最初的建议")
        self.stale_hint.setObjectName("Hint")
        self.stale_hint.hide()
        root.addWidget(self.stale_hint)

        # 用一列 QLabel 而不是 QListWidget：条数最多五六条，不需要滚动，
        # 而列表控件会把剩余高度全吃掉，把下面的"技术细节"顶到窗口最底部。
        self.effects_host = QWidget()
        self.effects_box = QVBoxLayout(self.effects_host)
        self.effects_box.setContentsMargins(0, 0, 0, 0)
        self.effects_box.setSpacing(7)
        root.addWidget(self.effects_host)

        # ---- 技术细节（默认折叠） ----
        self.detail_toggle = QToolButton()
        self.detail_toggle.setObjectName("DetailToggle")
        self.detail_toggle.setText("技术细节：将要执行的命令")
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.detail_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.detail_toggle.toggled.connect(self._on_detail_toggled)
        root.addWidget(self.detail_toggle)

        self.detail_box = QWidget()
        detail_layout = QVBoxLayout(self.detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)

        self.fix_label = QLabel("")
        self.fix_label.setObjectName("Hint")
        self.fix_label.setWordWrap(True)
        self.fix_label.hide()
        detail_layout.addWidget(self.fix_label)

        self.command_label = QLabel("—")
        self.command_label.setObjectName("CommandBox")
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self.command_label)

        self.detail_box.hide()
        root.addWidget(self.detail_box)

        # 留白放在最后：内容整体往上靠，用户从上往下读不会先撞见一大片空
        root.addStretch(1)

        # 初始就是空状态：没有视频之前，参数没有意义
        self._set_params_enabled(False)
        self._set_plan_area_visible(False)

    # ---------- 内部 ----------
    def _emit_request(self) -> None:
        self.request_summary.emit(self.request_edit.text().strip())

    def _on_user_edit(self) -> None:
        if not self._has_plan:
            return
        self.stale_hint.show()
        self.plan_changed.emit()

    def _on_detail_toggled(self, checked: bool) -> None:
        self.detail_box.setVisible(checked)
        self.detail_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )

    def _set_plan_area_visible(self, visible: bool) -> None:
        """空状态把整个方案区收起来。

        留着"这样设置的效果"标题和折叠按钮、下面却没有内容，
        比什么都不显示更让人以为界面坏了。
        """
        for widget in (self.effect_title, self.effects_host, self.detail_toggle):
            widget.setVisible(visible)
        if not visible:
            self.detail_box.setVisible(False)
            self.stale_hint.setVisible(False)

    def _style_preset(self, has_plan: bool) -> None:
        self.preset_label.setObjectName("PlanName" if has_plan else "Muted")
        self.preset_label.style().unpolish(self.preset_label)
        self.preset_label.style().polish(self.preset_label)

    def _set_badge(self, text: str, ai: bool) -> None:
        self.badge.setText(text)
        self.badge.setObjectName("BadgeAI" if ai else "BadgeLocal")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

    def _set_params_enabled(self, enabled: bool) -> None:
        """没有方案时把参数区置灰。

        空状态下留着一堆能点但点了没用的下拉框，是"看起来能用、其实不知道
        从哪开始"的典型来源。置灰等于明说：先给我一个视频。
        """
        for widget in (self.container_box, self.scale_box, self.quality_box,
                       self.audio_box, self.target_spin):
            widget.setEnabled(enabled)

    def _clear_effects(self) -> None:
        while self.effects_box.count():
            item = self.effects_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_effect(self, text: str, warn: bool) -> None:
        label = QLabel(("⚠  " if warn else "✓  ") + text)
        label.setObjectName("EffectWarn" if warn else "EffectOk")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.effects_box.addWidget(label)

    def _fill_effects(self, reasons: list[str], risks: list[str]) -> None:
        self._clear_effects()
        for reason in reasons:
            self._add_effect(reason, warn=False)
        for risk in risks:
            self._add_effect(risk, warn=True)
        if not reasons and not risks:
            self._add_effect("按上面的设置直接转就行", warn=False)

    # ---------- 对外接口 ----------
    def set_busy(self, busy: bool) -> None:
        self.ask_btn.setEnabled(not busy)
        self.ask_btn.setText("思考中…" if busy else "获取建议")

    def apply_plan(self, plan: TranscodePlan, warnings: list[str], used_ai: bool) -> None:
        self._has_plan = True
        self._set_badge("AI 顾问" if used_ai else "本地规则", used_ai)
        self._set_params_enabled(True)
        self._set_plan_area_visible(True)
        self.detail_toggle.setChecked(False)

        self.preset_label.setText(plan.preset_name)
        self._style_preset(True)
        self.stale_hint.hide()

        # 更新控件时先断开，避免触发一串 plan_changed
        widgets = (self.container_box, self.scale_box,
                   self.quality_box, self.audio_box, self.target_spin)
        for w in widgets:
            w.blockSignals(True)

        if plan.container in CONTAINERS:
            self.container_box.setCurrentText(plan.container)
        if plan.scale in SCALE_TARGETS:
            self.scale_box.setCurrentText(plan.scale)
        self.quality_box.setCurrentText(labels.quality_label(plan.quality_value))
        self.audio_box.setCurrentText(labels.audio_label(plan.audio_bitrate_kbps))
        self.target_spin.setValue(plan.target_size_mb or 0)

        for w in widgets:
            w.blockSignals(False)

        self._fill_effects(plan.reasons, plan.risks)

        # 参数修正记录属于"程序替你改了什么"，收进技术细节
        if warnings:
            lines = ["·　" + w for w in warnings]
            self.fix_label.setText("参数被自动修正过：\n" + "\n".join(lines))
            self.fix_label.show()
        else:
            self.fix_label.hide()
            self.fix_label.setText("")

    def current_overrides(self) -> dict:
        """用户在界面上的手动修改，覆盖到 plan 上。"""
        return {
            "container": self.container_box.currentText(),
            "scale": self.scale_box.currentText(),
            "quality_value": labels.quality_value(self.quality_box.currentText()),
            "audio_bitrate_kbps": labels.audio_value(self.audio_box.currentText()),
            "target_size_mb": self.target_spin.value() or None,
        }

    def show_command(self, command: str) -> None:
        self.command_label.setText(command)

    def show_notice(self, text: str) -> None:
        """参数区上方的一行提醒。text 为空则收起。"""
        self.notice_label.setText(text)
        self.notice_label.setVisible(bool(text))

    def set_codec_text(self, codec: str) -> None:
        self.codec_label.setText(labels.codec_label(codec))
        self.codec_label.setToolTip(labels.codec_tooltip(codec))

    def reset(self) -> None:
        self._has_plan = False
        self.request_edit.clear()
        self.preset_label.setText("载入视频后自动生成方案")
        self._style_preset(False)
        self.stale_hint.hide()
        self.show_notice("")
        self._clear_effects()
        self.command_label.setText("—")
        self.fix_label.hide()
        self.detail_toggle.setChecked(False)
        self._set_badge("本地规则", False)
        self._set_params_enabled(False)
        self._set_plan_area_visible(False)
        self.codec_label.setText("待检测")
        self.codec_label.setToolTip("")
