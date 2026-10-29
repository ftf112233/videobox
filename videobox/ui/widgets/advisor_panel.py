"""右栏：需求输入 → 参数方案 → 效果说明 → 高级参数。

界面分两层，这是刻意的：

**第一层**只出现人能判断的东西。画质是「极佳 / 高 / 标准 / 省体积」，
音质是「省流量 / 标准 / 清晰 / 高音质」，说明只回答"我会得到什么"。
不懂视频编码的人走到这里就能把事办完。

**第二层**在「高级设置」里：编码器偏好、CRF、帧率、音频编码、码率、
采样率、声道、旋转。会打开这一层的人本来就想要这些——把数值框从他手里
拿走不叫体贴，叫阉割。两层是双向绑定的：改档位 CRF 跟着走，改 CRF
档位显示最近的一档。

说明区不出现参数名和置信度：用户拿这两样做不出任何决定。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from ...core import labels
from ...core.models import CONTAINERS, SCALE_TARGETS, TranscodePlan

# 编码器偏好。界面上不写 libx264 这种名字，但要让人能表达"我想用哪个"
CODEC_PREF_OPTIONS: tuple[tuple[str, str], ...] = (
    ("自动选择", "auto"),
    ("优先用显卡", "h264_nvenc"),
    ("只用 CPU", "libx264"),
)


def _fill_combo(box: QComboBox, options) -> None:
    for text, value in options:
        box.addItem(text, value)


def _select_data(box: QComboBox, value) -> None:
    index = box.findData(value)
    box.setCurrentIndex(index if index >= 0 else 0)


def _label_cell(text: str, widget: QWidget) -> QVBoxLayout:
    """一个「小标题 + 控件」的竖排单元，参数网格里反复用到。"""
    cell = QVBoxLayout()
    cell.setSpacing(4)
    name = QLabel(text)
    name.setObjectName("Hint")
    cell.addWidget(name)
    cell.addWidget(widget)
    return cell


def _step_row(no: str, text: str, optional: bool) -> QWidget:
    """空态里的一步：圆序号 + 一句话。

    序号独立成一个小圆，而不是写成"1."开头——
    扫视时圆圈是天然的锚点，段落里的字只能逐字读。
    """
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(10)

    badge = QLabel(no)
    badge.setObjectName("StepNo")
    badge.setFixedSize(22, 22)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    line.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)

    body = QLabel(text + (
        '<span style="color:#A9AEB8">　（可以跳过）</span>' if optional else ""
    ))
    body.setObjectName("Step")
    body.setTextFormat(Qt.TextFormat.RichText)
    body.setWordWrap(True)
    line.addWidget(body, 1)
    return row


class AdvisorPanel(QFrame):
    request_summary = Signal(str)   # 用户点了"获取建议"
    plan_changed = Signal()         # 参数被手动改动

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._has_plan = False
        self._stale = False

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
        self.input_hint = QLabel("用一句话说清你要拿这个视频干什么")
        self.input_hint.setObjectName("Hint")
        root.addWidget(self.input_hint)

        # 输入行包一层：空态要连它一起收起来。
        # 没有视频时问顾问是没有意义的（顾问要先读视频信息才能答），
        # 让输入框灰着等人、点一下再回"请先打开视频"，是把一句话的活
        # 拆成两次拒绝。
        self.input_host = QWidget()
        row = QHBoxLayout(self.input_host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.request_edit = QLineEdit()
        self.request_edit.setPlaceholderText("例如：发微信朋友圈，别超过 20MB")
        self.request_edit.returnPressed.connect(self._emit_request)
        row.addWidget(self.request_edit, 1)
        self.ask_btn = QPushButton("获取建议")
        self.ask_btn.clicked.connect(self._emit_request)
        row.addWidget(self.ask_btn)
        root.addWidget(self.input_host)

        self.preset_label = QLabel("载入视频后自动生成方案")
        self.preset_label.setObjectName("Muted")
        root.addWidget(self.preset_label)

        # 参数区上方的一行提示，只在"设置和目标冲突"这类情况下出现
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("Notice")
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        root.addWidget(self.notice_label)

        # ---- 第一层参数：全是档位，没有裸数字 ----
        # 包一层 host 是为了空态能整体收起。只在里面 setEnabled(False) 是不够的：
        # 六个灰框还摆在那儿，里面还显示着 mp4 / 原画 / 极佳，
        # 看上去像"已经配好了"，实际一个都点不动。
        self.params_host = QWidget()
        params_host_layout = QVBoxLayout(self.params_host)
        params_host_layout.setContentsMargins(0, 0, 0, 0)
        params_host_layout.setSpacing(0)

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
            params.addLayout(_label_cell(label, widget), r, c)
        params.setColumnStretch(0, 1)
        params.setColumnStretch(1, 1)
        params_host_layout.addLayout(params)
        root.addWidget(self.params_host)

        # ---- 空态：告诉用户从哪开始，而不是留一堆点不动的控件 ----
        # 参考的是"步骤引导"而不是"更详尽的说明"：用户此刻缺的不是知识，
        # 是下一步该做什么。
        self.steps_host = QWidget()
        steps_outer = QVBoxLayout(self.steps_host)
        steps_outer.setContentsMargins(0, 0, 0, 0)
        # 上下都留白、上少下多：卡片落在偏上三分之一处，
        # 视线从标题往下一扫就能撞上它，不需要在整屏空白里找
        steps_outer.addStretch(1)

        guide = QFrame()
        guide.setObjectName("EmptyGuide")
        steps = QVBoxLayout(guide)
        steps.setContentsMargins(28, 26, 28, 26)
        steps.setSpacing(15)

        steps_title = QLabel("从这三步开始")
        steps_title.setObjectName("StepTitle")
        steps.addWidget(steps_title)

        for no, text, optional in (
            ("1", "拖一个视频进来，或点左上角「打开文件」", False),
            ("2", "说一句你要拿去干什么，比如「发朋友圈，别超过 20MB」", True),
            ("3", "点「开始转码」，转好的文件就在原文件旁边", False),
        ):
            steps.addWidget(_step_row(no, text, optional))

        steps_foot = QLabel(
            "参数不用你算。载入后会自动给一个能用的方案，"
            "每一项都写着「这样设会得到什么」，随时能改。"
        )
        steps_foot.setObjectName("Hint")
        steps_foot.setWordWrap(True)
        steps.addSpacing(2)
        steps.addWidget(steps_foot)

        steps_outer.addWidget(guide)
        steps_outer.addStretch(2)
        root.addWidget(self.steps_host, 1)

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
        # 而列表控件会把剩余高度全吃掉，把下面的入口顶到窗口最底部。
        self.effects_host = QWidget()
        self.effects_box = QVBoxLayout(self.effects_host)
        self.effects_box.setContentsMargins(0, 0, 0, 0)
        self.effects_box.setSpacing(6)
        root.addWidget(self.effects_host)

        # ---- 第二层：高级设置（默认折叠） ----
        self.detail_toggle = QToolButton()
        self.detail_toggle.setObjectName("DetailToggle")
        # 文案直接列出点开能改什么，而不是给一个抽象分类名。
        # "高级设置"四个字说完，用户仍然不知道里面有没有他要找的东西；
        # 列出来他才能判断"要不要点"——不点也是一种正确的选择。
        self.detail_toggle.setText(
            "更多参数与命令（编码器 · CRF · 帧率 · 旋转 · ffmpeg 命令）"
        )
        self.detail_toggle.setToolTip(
            "想精调就在这里：CRF 具体数值、帧率、音频编码与采样率、旋转、"
            "以及将要执行的完整命令。日常使用不需要打开。"
        )
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
        detail_layout.setSpacing(9)

        pro = QGridLayout()
        pro.setHorizontalSpacing(10)
        pro.setVerticalSpacing(9)

        self.codec_pref_box = QComboBox()
        _fill_combo(self.codec_pref_box, CODEC_PREF_OPTIONS)
        self.codec_pref_box.setToolTip("自动选择会优先用显卡，跑不动再退回 CPU。")

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(18, 35)
        self.quality_spin.setToolTip(
            "CRF：越小画质越好、体积越大。18 接近无损，23 常用，28 以上肉眼可见损失。"
        )

        self.fps_box = QComboBox()
        _fill_combo(self.fps_box, labels.FPS_OPTIONS)
        self.fps_box.setToolTip(labels.FPS_TOOLTIP)

        self.audio_codec_box = QComboBox()
        _fill_combo(self.audio_codec_box, labels.AUDIO_CODEC_OPTIONS)

        self.audio_kbps_spin = QSpinBox()
        self.audio_kbps_spin.setRange(32, 320)
        self.audio_kbps_spin.setSingleStep(16)
        self.audio_kbps_spin.setSuffix(" kbps")

        self.sample_rate_box = QComboBox()
        _fill_combo(self.sample_rate_box, labels.SAMPLE_RATE_OPTIONS)
        self.sample_rate_box.setToolTip(labels.SAMPLE_RATE_TOOLTIP)

        self.channels_box = QComboBox()
        _fill_combo(self.channels_box, labels.CHANNEL_OPTIONS)
        self.channels_box.setToolTip(labels.CHANNEL_TOOLTIP)

        self.rotation_box = QComboBox()
        _fill_combo(self.rotation_box, labels.ROTATION_OPTIONS)
        self.rotation_box.setToolTip(labels.ROTATION_TOOLTIP)

        pro_specs = [
            ("编码器偏好", self.codec_pref_box), ("质量值 CRF", self.quality_spin),
            ("帧率", self.fps_box), ("音频编码", self.audio_codec_box),
            ("音频码率", self.audio_kbps_spin), ("采样率", self.sample_rate_box),
            ("声道", self.channels_box), ("旋转", self.rotation_box),
        ]
        for idx, (label, widget) in enumerate(pro_specs):
            r, c = divmod(idx, 3)
            pro.addLayout(_label_cell(label, widget), r, c)
        for col in range(3):
            pro.setColumnStretch(col, 1)
        detail_layout.addLayout(pro)

        self.strip_audio_check = QCheckBox("去掉声音（输出一个没有音轨的视频）")
        detail_layout.addWidget(self.strip_audio_check)

        # 两层之间的双向绑定：改档位数值跟着走，改数值档位显示最近的一档
        self.quality_box.currentIndexChanged.connect(self._sync_level_to_crf)
        self.quality_spin.valueChanged.connect(self._sync_crf_to_level)
        self.audio_box.currentIndexChanged.connect(self._sync_level_to_kbps)
        self.audio_kbps_spin.valueChanged.connect(self._sync_kbps_to_level)

        for widget in (self.codec_pref_box, self.fps_box, self.audio_codec_box,
                       self.sample_rate_box, self.channels_box, self.rotation_box):
            widget.currentIndexChanged.connect(lambda _: self._on_user_edit())
        self.audio_kbps_spin.valueChanged.connect(lambda _: self._on_user_edit())
        self.quality_spin.valueChanged.connect(lambda _: self._on_user_edit())
        self.strip_audio_check.toggled.connect(lambda _: self._on_user_edit())

        divider = QFrame()
        divider.setObjectName("HLine")
        divider.setFrameShape(QFrame.Shape.HLine)
        detail_layout.addWidget(divider)

        cmd_label = QLabel("将要执行的命令")
        cmd_label.setObjectName("Hint")
        detail_layout.addWidget(cmd_label)

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
        self._stale = True
        self._refresh_effect_visibility()
        self.plan_changed.emit()

    def _refresh_effect_visibility(self) -> None:
        """效果说明只在"看方案"的时候出现。

        展开高级设置意味着进入调参模式：这时方案解释既用不上，
        又会把右栏顶出窗口高度。所以两者互斥显示。
        """
        show = self._has_plan and not self.detail_toggle.isChecked()
        for widget in (self.effect_title, self.effects_host):
            widget.setVisible(show)
        self.stale_hint.setVisible(show and self._stale)

    def _on_detail_toggled(self, checked: bool) -> None:
        self.detail_box.setVisible(checked)
        self.detail_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        self._refresh_effect_visibility()

    # ---- 档位 ↔ 数值 双向同步 ----
    def _sync_level_to_crf(self, _index: int) -> None:
        value = labels.quality_value(self.quality_box.currentText())
        self.quality_spin.blockSignals(True)
        self.quality_spin.setValue(value)
        self.quality_spin.blockSignals(False)

    def _sync_crf_to_level(self, value: int) -> None:
        label = labels.quality_label(value)
        self.quality_box.blockSignals(True)
        self.quality_box.setCurrentText(label)
        self.quality_box.blockSignals(False)

    def _sync_level_to_kbps(self, _index: int) -> None:
        value = labels.audio_value(self.audio_box.currentText())
        self.audio_kbps_spin.blockSignals(True)
        self.audio_kbps_spin.setValue(value)
        self.audio_kbps_spin.blockSignals(False)

    def _sync_kbps_to_level(self, value: int) -> None:
        label = labels.audio_label(value)
        self.audio_box.blockSignals(True)
        self.audio_box.setCurrentText(label)
        self.audio_box.blockSignals(False)

    def _set_plan_area_visible(self, visible: bool) -> None:
        """有方案就显示参数与说明，没方案就显示三步引导，两者互斥。

        中间的"参数灰着、引导也在"是最差的一种：右栏被塞满，
        而且能看见却点不动，比看不见更让人以为界面坏了。
        """
        for widget in (self.input_hint, self.input_host, self.preset_label,
                       self.params_host, self.effect_title,
                       self.effects_host, self.detail_toggle):
            widget.setVisible(visible)
        # 还没方案时显示"AI 顾问 / 本地规则"是在描述一个不存在的东西
        self.badge.setVisible(visible)
        self.steps_host.setVisible(not visible)
        if not visible:
            self.notice_label.setVisible(False)
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
                       self.audio_box, self.target_spin, self.codec_pref_box,
                       self.quality_spin, self.fps_box, self.audio_codec_box,
                       self.audio_kbps_spin, self.sample_rate_box,
                       self.channels_box, self.rotation_box,
                       self.strip_audio_check):
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
        self._stale = False
        self.stale_hint.hide()

        # 更新控件时先断开，避免触发一串 plan_changed
        widgets = [
            self.container_box, self.scale_box, self.quality_box, self.audio_box,
            self.target_spin, self.codec_pref_box, self.quality_spin, self.fps_box,
            self.audio_codec_box, self.audio_kbps_spin, self.sample_rate_box,
            self.channels_box, self.rotation_box, self.strip_audio_check,
        ]
        for w in widgets:
            w.blockSignals(True)

        if plan.container in CONTAINERS:
            self.container_box.setCurrentText(plan.container)
        if plan.scale in SCALE_TARGETS:
            self.scale_box.setCurrentText(plan.scale)
        self.quality_box.setCurrentText(labels.quality_label(plan.quality_value))
        self.audio_box.setCurrentText(labels.audio_label(plan.audio_bitrate_kbps))
        self.target_spin.setValue(plan.target_size_mb or 0)

        _select_data(self.codec_pref_box, plan.video_codec)
        self.quality_spin.setValue(plan.quality_value)
        _select_data(self.fps_box, plan.fps if plan.fps else "keep")
        _select_data(self.audio_codec_box, plan.audio_codec)
        self.audio_kbps_spin.setValue(plan.audio_bitrate_kbps)
        _select_data(self.sample_rate_box, plan.audio_sample_rate)
        _select_data(self.channels_box, plan.audio_channels)
        _select_data(self.rotation_box, plan.rotation)
        self.strip_audio_check.setChecked(plan.strip_audio)

        for w in widgets:
            w.blockSignals(False)

        self._fill_effects(plan.reasons, plan.risks)
        self._refresh_effect_visibility()

        # 参数修正记录属于"程序替你改了什么"，收进高级设置
        if warnings:
            lines = ["·　" + w for w in warnings]
            self.fix_label.setText("参数被自动修正过：\n" + "\n".join(lines))
            self.fix_label.show()
        else:
            self.fix_label.hide()
            self.fix_label.setText("")

    def current_overrides(self) -> dict:
        """用户在界面上的手动修改，覆盖到 plan 上。

        精调值优先：改了 CRF 就用 CRF，档位只是它的快捷方式。
        """
        return {
            "container": self.container_box.currentText(),
            "scale": self.scale_box.currentText(),
            "quality_value": self.quality_spin.value(),
            "video_codec": self.codec_pref_box.currentData() or "auto",
            "fps": self.fps_box.currentData() or "keep",
            "audio_codec": self.audio_codec_box.currentData() or "aac",
            "audio_bitrate_kbps": self.audio_kbps_spin.value(),
            "audio_sample_rate": self.sample_rate_box.currentData() or 0,
            "audio_channels": self.channels_box.currentData() or 0,
            "rotation": self.rotation_box.currentData() or 0,
            "strip_audio": self.strip_audio_check.isChecked(),
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
        self._stale = False
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
