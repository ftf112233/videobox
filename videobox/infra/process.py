"""转码进程封装。

用 QProcess 而不是裸 subprocess：
QProcess 是基于事件循环的异步封装，进度信号天然在 UI 线程回调，
不需要自己开线程，也不会把界面卡死。

取消策略（重要）：
给 ffmpeg 的 stdin 写 "q"，它会正常收尾并把 trailer 写进文件，
产物仍然是可播放的完整视频。直接 terminate() 只会留下一个
播不出来的截断 mp4。所以顺序是 q → 等 3 秒 → terminate → kill。
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal, QTimer

from ..core.models import ProgressUpdate, TranscodeResult
from ..core.progress import ProgressParser


class TranscodeRunner(QObject):
    """跑一次 ffmpeg 转码。一个实例负责一次任务。"""

    progressed = Signal(object)   # ProgressUpdate
    log_line = Signal(str)        # ffmpeg stderr 的一行
    finished = Signal(object)     # TranscodeResult

    def __init__(
        self,
        ffmpeg: str,
        args: list[str],
        input_path: str,
        output_path: str,
        duration_sec: float,
        used_codec: str,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self.args = args
        self.input_path = input_path
        self.output_path = output_path
        self.duration_sec = duration_sec
        self.used_codec = used_codec

        self._parser = ProgressParser(duration_sec)
        self._stderr_buf: list[str] = []
        self._cancelled = False
        self._started_at = 0.0
        self._expected_end = False
        self._process: QProcess | None = None

    # ---------- 生命周期 ----------
    def start(self) -> None:
        import time

        self._started_at = time.perf_counter()
        self._cleanup_stale_output()

        proc = QProcess(self)
        proc.setProgram(self.ffmpeg)
        proc.setArguments(self.args)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        # 不要合并通道：stdout 是结构化进度，stderr 是错误日志，混在一起没法解析
        env = QProcessEnvironment.systemEnvironment()
        env.insert("AV_LOG_FORCE_NOCOLOR", "1")  # 别让 ANSI 颜色码污染日志
        proc.setProcessEnvironment(env)

        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        self._process = proc
        proc.start()

    def cancel(self) -> None:
        """优雅取消：先请 ffmpeg 自己收尾。"""
        if not self._process or self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._cancelled = True
        try:
            self._process.write(b"q\n")
        except (OSError, RuntimeError):
            pass
        # 3 秒还不退就强杀，避免用户以为界面卡死
        QTimer.singleShot(3000, self._force_kill)

    def _force_kill(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            QTimer.singleShot(1500, self._kill)

    def _kill(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    # ---------- 数据回流 ----------
    def _on_stdout(self) -> None:
        if not self._process:
            return
        raw = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in raw.splitlines():
            update = self._parser.feed_line(line)
            if update is not None:
                if update.done:
                    self._expected_end = True
                self.progressed.emit(update)

    def _on_stderr(self) -> None:
        if not self._process:
            return
        raw = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        for line in raw.splitlines():
            if not line.strip():
                continue
            self._stderr_buf.append(line)
            # 只保留最近 200 行，长转码的报错可能刷屏
            if len(self._stderr_buf) > 200:
                self._stderr_buf.pop(0)
            self.log_line.emit(line)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.finished.emit(self._result(False, "无法启动 ffmpeg，请检查可执行文件路径"))

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        import time

        # 把管道里剩下的数据读完，否则最后几次进度会丢
        self._on_stdout()
        self._on_stderr()

        elapsed = time.perf_counter() - self._started_at
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        out_ok = Path(self.output_path).is_file() and Path(self.output_path).stat().st_size > 0

        # 判定标准：progress=end 之前见过 + 返回码 0 + 文件存在且非空
        # 只看返回码不够——某些错误 ffmpeg 也会返回 0
        success = (not crashed) and exit_code == 0 and out_ok and self._expected_end

        if self._cancelled and not success:
            self.finished.emit(self._result(False, "已取消", cancelled=True, elapsed=elapsed))
            return

        if success:
            self.finished.emit(self._result(True, "", elapsed=elapsed))
        else:
            tail = "\n".join(self._stderr_buf[-6:]) or f"ffmpeg 退出码 {exit_code}"
            self.finished.emit(self._result(False, tail, elapsed=elapsed))

    # ---------- 辅助 ----------
    def _result(
        self,
        ok: bool,
        message: str,
        cancelled: bool = False,
        elapsed: float = 0.0,
    ) -> TranscodeResult:
        out_size = 0
        if Path(self.output_path).is_file():
            out_size = Path(self.output_path).stat().st_size
        in_size = 0
        if Path(self.input_path).is_file():
            in_size = Path(self.input_path).stat().st_size
        speed = self._parser.speed
        return TranscodeResult(
            ok=ok,
            output_path=self.output_path,
            input_size_bytes=in_size,
            output_size_bytes=out_size,
            elapsed_sec=round(elapsed, 2),
            speed=speed,
            used_codec=self.used_codec,
            error_message=message,
            cancelled=cancelled,
        )

    def _cleanup_stale_output(self) -> None:
        """上一次留下的半截文件会让本次判成败失真。"""
        try:
            if Path(self.output_path).exists():
                os.unlink(self.output_path)
        except OSError:
            pass
