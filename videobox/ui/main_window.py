"""主窗口：把探测、顾问、转码、进度串成一条用户能走通的动线。

动线刻意模仿桌面转换器的常规布局（左侧看素材、右侧调参数、底部看进度），
因为笔试题第 7 条要求"设计目标是给人用"——用户对这类软件的肌肉记忆
比任何原创布局都值钱。

状态机只有四个：空 → 已载入 → 转码中 → 完成/失败。
转码中禁用所有会改变输入的控件，避免用户改到一半参数变了还不自知。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon, QImage,
)
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..core import labels, thumb as thumb_mod
from ..core.models import TranscodePlan, VideoInfo
from ..core.params import build_args, build_preview_command, choose_codec
from ..core.probe import probe as probe_video
from ..core.progress import format_eta
from ..infra.advisor import Advisor
from ..infra.ffmpeg_bin import (
    Binaries, CodecProbe, available_from, find_binaries, probe_all,
    summary_detail, summary_line,
)
from ..infra.llm_client import LLMClient
from ..infra.logging_setup import app_data_dir, log_dir
from ..infra.process import TranscodeRunner
from ..infra import taskbar as taskbar_mod
from . import tasks
from .widgets.advisor_panel import AdvisorPanel
from .widgets.info_panel import InfoPanel
from .widgets.progress_panel import ProgressPanel

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm",
    ".m4v", ".ts", ".mpg", ".mpeg", ".3gp", ".rmvb",
}

CONFIG_PATH = app_data_dir() / "config.json"

DEFAULT_TITLE = "VideoBox · AI 视频转码器"
MIN_SIZE = (1000, 660)
DEFAULT_SIZE = (1180, 900)


def load_config() -> dict:
    """读本地配置（API Key 等）。读不到就返回空，绝不抛错。"""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_api_key(cfg: dict) -> str:
    """环境变量优先于配置文件，方便临时切换。"""
    return (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or str(cfg.get("api_key", ""))
    ).strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(DEFAULT_TITLE)
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*DEFAULT_SIZE)
        self.setAcceptDrops(True)
        self._apply_icon()

        # 桌面程序该有的"记性"：窗口位置、上次目录、上次填的需求。
        # 不记这些，用户每次打开都从零开始，就是"用不明白"的开始。
        self.settings = QSettings("VideoBox", "VideoBox")
        self._restore_window_state()

        self.binaries = Binaries(ffmpeg="", ffprobe=None, source="未探测")
        self.probes: list[CodecProbe] = []
        self.available_codecs: list[str] = ["libx264"]
        self.info: VideoInfo | None = None
        self.plan: TranscodePlan | None = None
        self.runner: TranscodeRunner | None = None
        self.worker_refs: list = []
        self.retry_done = False
        # 顾问请求的序号。默认方案和用户主动提问可能同时在跑，
        # 只让最后发起的那一次落地，否则慢回来的旧结果会盖掉新的
        self._advice_token = 0
        self.taskbar = taskbar_mod.TaskbarProgress()

        cfg = load_config()
        self.client = LLMClient(api_key=resolve_api_key(cfg))
        self.advisor = Advisor(self.client)

        self._build_ui()
        self._build_menu()
        self._restore_last_request()
        self._boot_environment()

    # ================= 窗口状态 =================
    def _apply_icon(self) -> None:
        """窗口图标。不设的话 Windows 任务栏显示通用空白图标——最好认的未完成信号。"""
        try:
            from ..app import _resource_path

            path = _resource_path("ui/app.ico")
            if path.exists():
                self.setWindowIcon(QIcon(str(path)))
        except Exception as exc:  # noqa: BLE001 - 图标失败不该影响启动
            log.debug("图标加载失败：%s", exc)

    def _restore_window_state(self) -> None:
        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
            return
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                area.center().x() - DEFAULT_SIZE[0] // 2,
                area.center().y() - DEFAULT_SIZE[1] // 2,
            )

    def _restore_last_request(self) -> None:
        text = str(self.settings.value("session/last_request", "") or "")
        if text:
            self.advisor_panel.request_edit.setText(text)

    # ================= UI 组装 =================
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.info_panel = InfoPanel()
        body.addWidget(self.info_panel, 0)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.advisor_panel = AdvisorPanel()
        # 展开高级设置时右栏会比窗口高，套一层纵向滚动；
        # 不套的话窗口一压缩，最下面的命令预览就被裁掉
        self.advisor_scroll = QScrollArea()
        self.advisor_scroll.setWidgetResizable(True)
        self.advisor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.advisor_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.advisor_scroll.viewport().setStyleSheet("background: transparent;")
        self.advisor_scroll.setWidget(self.advisor_panel)
        right.addWidget(self.advisor_scroll, 1)
        body.addLayout(right, 1)

        outer.addLayout(body, 1)

        self.progress_panel = ProgressPanel()
        self.progress_panel.set_start_enabled(False)
        outer.addWidget(self.progress_panel)

        # ---- 信号 ----
        self.advisor_panel.request_summary.connect(self._on_request_summary)
        self.advisor_panel.plan_changed.connect(self._refresh_command)
        self.progress_panel.start_clicked.connect(self._start_transcode)
        self.progress_panel.cancel_clicked.connect(self._cancel_transcode)

        self.status_label = QLabel("正在初始化…")
        self.statusBar().addWidget(self.status_label, 1)

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("文件")
        open_action = QAction("打开视频…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._pick_file)
        file_menu.addAction(open_action)

        open_output = QAction("打开输出目录", self)
        open_output.triggered.connect(self._open_output_dir)
        file_menu.addAction(open_output)
        file_menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        tools_menu = bar.addMenu("工具")
        log_action = QAction("打开日志目录", self)
        log_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))
        )
        tools_menu.addAction(log_action)

        recheck = QAction("重新探测硬件编码器", self)
        recheck.triggered.connect(self._boot_environment)
        tools_menu.addAction(recheck)

        help_menu = bar.addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于 VideoBox",
            "VideoBox · AI 视频转码器\n\n"
            "基于 PySide6（Qt for Python）+ FFmpeg 命令行。\n"
            "AI 参数顾问：DeepSeek（可无 Key 降级为本地规则引擎）。\n\n"
            f"当前模式：{self.advisor.mode_label}",
        )

    # ================= 启动探测 =================
    def _boot_environment(self) -> None:
        self.status_label.setText("正在查找 ffmpeg 并实测编码器…")
        self.worker_refs.append(
            tasks.submit(
                self._probe_environment,
                on_done=self._on_environment_ready,
                on_error=lambda msg: self._fatal(f"环境检查失败：{msg}"),
            )
        )

    def _probe_environment(self):
        bins = find_binaries()
        if not bins.ok:
            return bins, []
        return bins, probe_all(bins.ffmpeg)

    def _on_environment_ready(self, payload) -> None:
        binarires, probes = payload
        self.binaries = binarires
        self.probes = probes

        if not binarires.ok:
            self._fatal(
                "找不到 ffmpeg。\n\n"
                "请把 ffmpeg.exe 放到以下任一位置后重试：\n"
                "  · 程序目录下的 resources\\ffmpeg\\\n"
                "  · D:\\develop\\ffmpeg\\bin\\\n"
                "  · 或加入系统 PATH"
            )
            return

        self.available_codecs = available_from(probes)
        self.advisor_panel.set_codec_text(choose_codec("auto", self.available_codecs))
        # 状态栏只留两条最短的信息。ffmpeg 从哪来、显卡为什么没启用，
        # 都属于"想问才看"的东西——挂在状态栏上，用户第一眼就是一句
        # 他既解决不了也不关心的报错。
        self.status_label.setText(
            f"{summary_line(probes)}　|　{self.advisor.mode_label}"
        )
        self.status_label.setToolTip(
            f"{summary_detail(probes)}\n\nffmpeg 来源：{self.binaries.source}"
        )
        log.info("环境就绪：%s；可用编码器 %s", binarires.source, self.available_codecs)

    def _fatal(self, message: str) -> None:
        log.error(message.replace("\n", " "))
        self.status_label.setText("环境异常")
        self.progress_panel.show_error(message)

    # ================= 打开文件 =================
    def _pick_file(self) -> None:
        start = str(self.settings.value("paths/last_dir", "") or "")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", start,
            "视频文件 (*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v *.3gp);;所有文件 (*.*)",
        )
        if path:
            self._load_video(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt 命名
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in VIDEO_SUFFIXES:
                    event.acceptProposedAction()
                    self.info_panel.set_drag_active(True)
                    return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.info_panel.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt 命名
        self.info_panel.set_drag_active(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in VIDEO_SUFFIXES:
                self._load_video(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def _load_video(self, path: str) -> None:
        if self.runner is not None:
            QMessageBox.information(self, "请稍等", "正在转码中，请先取消当前任务。")
            return

        self.settings.setValue("paths/last_dir", str(Path(path).parent))
        self.setWindowTitle(f"{Path(path).name} · VideoBox")

        self.info = None
        self.plan = None
        self.retry_done = False
        self.info_panel.reset()
        self.advisor_panel.reset()
        self.progress_panel.set_idle()
        self.progress_panel.set_start_enabled(False)
        self.progress_panel.show_note(f"正在读取 {Path(path).name}…")
        self.status_label.setText("正在解析视频信息…")

        self.worker_refs.append(
            tasks.submit(
                self._load_video_bg, path,
                on_done=lambda payload: self._on_video_loaded(path, payload),
                on_error=lambda msg: self.progress_panel.show_error(f"无法读取该文件：{msg}"),
            )
        )

    def _load_video_bg(self, path: str):
        """后台线程：解析信息 + 抽缩略图。返回 QImage（不能返回 QPixmap）。"""
        info = probe_video(path, self.binaries.ffprobe, self.binaries.ffmpeg)
        image: QImage | None = None
        if self.binaries.ffmpeg and info.has_video:
            at = thumb_mod.pick_thumb_time(info.duration_sec)
            mtime = Path(path).stat().st_mtime
            thumb_path = thumb_mod.extract(
                self.binaries.ffmpeg, path, app_data_dir() / "cache", at, mtime
            )
            if thumb_path:
                img = QImage(thumb_path)
                image = img if not img.isNull() else None
        return info, image

    def _on_video_loaded(self, path: str, payload) -> None:
        info, image = payload
        self.info = info
        self.info_panel.show_info(info)
        self.info_panel.show_thumbnail(image)
        self.status_label.setText(f"已载入：{Path(path).name}　|　{info.friendly_line()}")

        # 载入后立刻给一个默认方案，用户不填需求也能直接转。
        # 必须放后台：AI 模式下这一问要 2~5 秒，在主线程同步调会让窗口冻住，
        # 用户看到的是"拖进文件之后程序假死了一下"。
        self.progress_panel.show_note("正在准备一个默认方案…")
        token = self._next_advice_token()
        self.worker_refs.append(
            tasks.submit(
                self._default_plan_bg, path,
                on_done=lambda result: self._on_default_plan(path, token, result),
                on_error=lambda msg: self._on_default_plan_failed(token, msg),
            )
        )

    def _default_plan_bg(self, path: str):
        """后台线程：不带需求问一次，拿一个通用方案。

        顾问挂了不能连累"文件已载入"这件已经完成的事，所以异常在这里收口，
        回落成一个能直接用的默认计划。
        """
        try:
            return self.advisor.advise("", self.info, self.available_codecs)
        except Exception as exc:  # noqa: BLE001
            log.exception("默认方案生成失败，使用兜底计划")
            return TranscodePlan(), [f"默认方案生成失败：{exc}"], False

    def _next_advice_token(self) -> int:
        self._advice_token += 1
        return self._advice_token

    def _stale(self, token: int) -> bool:
        """这份结果是不是已经被更晚发起的请求取代了。"""
        return token != self._advice_token

    def _on_default_plan(self, path: str, token: int, payload) -> None:
        # 等待期间换了文件、或用户已经自己问过一次，这一份结果就过期了
        if self._stale(token) or not self.info or self.info.path != path:
            return
        plan, warnings, used_ai = payload
        self.plan = plan
        self.advisor_panel.apply_plan(plan, warnings, used_ai)
        self._refresh_command()
        self.progress_panel.set_start_enabled(True)
        self.progress_panel.show_note(
            "方案已就绪，可以直接开始转码；也可以在右侧输入你的用途来调整。"
        )

    def _on_default_plan_failed(self, token: int, message: str) -> None:
        if self._stale(token) or not self.info:
            return
        # 方案没出来也别让"开始转码"一直灰着：用一份兜底计划顶上
        self.plan = TranscodePlan()
        self.advisor_panel.apply_plan(
            self.plan, [f"自动方案生成失败（{message}），已使用安全默认值"], False
        )
        self._refresh_command()
        self.progress_panel.set_start_enabled(True)
        self.progress_panel.show_note("方案生成失败，已填入安全默认值，可以直接转码。")

    # ================= 方案 =================
    def _on_request_summary(self, text: str) -> None:
        if not self.info:
            self.progress_panel.show_note("请先打开一个视频文件。")
            return
        self.advisor_panel.set_busy(True)
        self.status_label.setText("参数顾问思考中…")
        token = self._next_advice_token()
        self.worker_refs.append(
            tasks.submit(
                self.advisor.advise, text, self.info, self.available_codecs,
                on_done=lambda payload: self._on_advice(token, payload),
                on_error=self._on_advice_error,
            )
        )

    def _on_advice(self, token: int, payload) -> None:
        plan, warnings, used_ai = payload
        self.advisor_panel.set_busy(False)
        if self._stale(token):
            log.debug("丢弃过期的顾问结果：%s", plan.preset_name)
            return
        self.plan = plan
        self.advisor_panel.apply_plan(plan, warnings, used_ai)
        self._refresh_command()
        self.status_label.setText(f"方案已更新：{plan.preset_name}")

    def _on_advice_error(self, message: str) -> None:
        self.advisor_panel.set_busy(False)
        self.progress_panel.show_note(f"顾问不可用，已保留原方案（{message}）")

    def _current_plan(self) -> TranscodePlan | None:
        """把界面上用户的手动修改合并进当前方案。"""
        if not self.plan:
            return None
        merged = TranscodePlan(**self.plan.to_dict())
        for key, value in self.advisor_panel.current_overrides().items():
            setattr(merged, key, value)
        return merged

    def _output_path(self) -> str:
        assert self.info
        src = Path(self.info.path)
        plan = self._current_plan()
        suffix = f".{plan.container}" if plan else ".mp4"
        return str(src.with_name(f"{src.stem}_converted{suffix}"))

    def _refresh_command(self) -> None:
        plan = self._current_plan()
        if not plan or not self.info:
            return
        try:
            cmd = build_preview_command(
                plan, self.info, self.info.path, self._output_path(),
                self.available_codecs,
            )
        except Exception as exc:  # noqa: BLE001 - 预览失败不该拦住用户
            log.warning("命令预览失败：%s", exc)
            return
        self.advisor_panel.show_command(cmd)
        codec = choose_codec(plan.video_codec, self.available_codecs)
        self.advisor_panel.set_codec_text(codec)
        self.advisor_panel.show_notice(self._size_notice(plan))

    def _size_notice(self, plan: TranscodePlan) -> str:
        """目标体积和源文件对不上时，提前说清楚会怎么处理。

        用户填了 20 MB，但原片只有 5 MB —— 程序会按画质优先走。
        什么都不说的话，他拿到一个 4 MB 的文件会以为哪里设错了。
        """
        if not plan.target_size_mb or not self.info or not self.info.size_bytes:
            return ""
        source_mb = self.info.size_bytes / (1024 * 1024)
        if plan.target_size_mb >= source_mb:
            return (
                f"原片 {source_mb:.1f} MB，比 {plan.target_size_mb:g} MB 的目标还小。"
                "这次按画质优先处理，不会把文件做大。"
            )
        return ""

    # ================= 转码 =================
    def _start_transcode(self) -> None:
        if not self.info or not self.binaries.ok:
            self.progress_panel.show_note("请先打开一个视频文件。")
            return
        plan = self._current_plan()
        if not plan:
            self.progress_panel.show_note("还没有可用方案，请先获取建议。")
            return

        self.retry_done = False
        self._launch(plan, force_codec=None)

    def _launch(self, plan: TranscodePlan, force_codec: str | None) -> None:
        assert self.info
        codec = force_codec or choose_codec(plan.video_codec, self.available_codecs)
        if force_codec:
            plan = TranscodePlan(**plan.to_dict())
            plan.video_codec = force_codec

        out_path = self._output_path()
        try:
            args = build_args(plan, self.info, self.info.path, out_path, [codec])
        except Exception as exc:  # noqa: BLE001
            self.progress_panel.show_error(f"参数构造失败：{exc}")
            return

        codec_label = labels.codec_label(codec)
        self.progress_panel.set_running(codec_label)
        self.status_label.setText(f"转码中… → {Path(out_path).name}")
        self.taskbar.set_state(int(self.winId()), taskbar_mod.STATE_NORMAL)
        self.taskbar.set_value(int(self.winId()), 0)

        runner = TranscodeRunner(
            ffmpeg=self.binaries.ffmpeg,
            args=args,
            input_path=self.info.path,
            output_path=out_path,
            duration_sec=self.info.duration_sec,
            used_codec=codec,
            parent=self,
        )
        runner.progressed.connect(self._on_progress)
        runner.log_line.connect(lambda line: log.debug("[ffmpeg] %s", line))
        runner.finished.connect(self._on_transcode_finished)
        self.runner = runner
        self._last_plan = plan
        runner.start()

    def _on_progress(self, update) -> None:
        self.progress_panel.update_progress(
            update.percent, format_eta(update.eta_sec), update.speed
        )
        # 任务栏同步进度：窗口在后台时也能看见还剩多少
        self.taskbar.set_value(int(self.winId()), update.percent)

    def _cancel_transcode(self) -> None:
        if self.runner:
            self.runner.cancel()
            self.progress_panel.cancel_btn.setEnabled(False)
            self.progress_panel.show_note("正在安全取消（等待 ffmpeg 收尾）…")
            self.taskbar.set_state(int(self.winId()), taskbar_mod.STATE_PAUSED)

    def _on_transcode_finished(self, result) -> None:
        codec = result.used_codec
        codec_label = labels.codec_label(codec)
        self.runner = None

        # 硬件编码失败自动降级重试一次——这是真实产品该有的容错
        if (
            not result.ok
            and not result.cancelled
            and codec != "libx264"
            and not self.retry_done
        ):
            self.retry_done = True
            log.warning("硬件编码失败，降级到 libx264 重试：%s", result.error_message)
            self.progress_panel.show_note("硬件编码失败，正在自动切换到 CPU 编码重试…")
            QTimer.singleShot(200, lambda: self._launch(self._last_plan, "libx264"))
            return

        self.progress_panel.show_result(result, codec_label)
        if result.ok:
            self.status_label.setText(f"转码完成：{result.output_path}")
            self.taskbar.clear()
            log.info(
                "转码成功 %s → %s，耗时 %.2fs，%s",
                result.input_size_bytes, result.output_size_bytes,
                result.elapsed_sec, result.size_delta_label,
            )
        elif result.cancelled:
            self.status_label.setText("已取消")
            self.taskbar.clear()
        else:
            self.status_label.setText("转码失败，详见底部提示或日志")
            # 任务栏变红：用户切到别的窗口也能知道这次跑挂了
            self.taskbar.set_state(int(self.winId()), taskbar_mod.STATE_ERROR)

    def _open_output_dir(self) -> None:
        if not self.info:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.info.path).parent)))

    # ================= 收尾 =================
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 记住窗口位置和这次填的需求，下次打开接着用
        try:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue(
                "session/last_request", self.advisor_panel.request_edit.text()
            )
            self.settings.sync()
        except Exception as exc:  # noqa: BLE001
            log.debug("保存窗口状态失败：%s", exc)
        self.taskbar.clear()

        if self.runner:
            self.runner.cancel()
        super().closeEvent(event)
