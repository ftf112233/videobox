"""后台任务工人。

哪些活必须扔到线程里：
- ffprobe 解析（起子进程，几十到几百毫秒）
- 缩略图抽取（起子进程 + 写磁盘）
- 编码器实测（要跑 2 次 1 秒试编码，接近 1 秒）

哪些不需要：
- 转码本身（QProcess 天然异步，见 infra/process.py）

统一用 QRunnable + QThreadPool，避免到处 fork QThread。
"""

from __future__ import annotations

import logging
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    """把任意同步函数丢到线程池跑，结果通过信号回主线程。"""

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - 线程里的异常必须自己兜住，否则静默消失
            log.error("后台任务失败：%s\n%s", exc, traceback.format_exc())
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)


def submit(fn: Callable, *args, on_done=None, on_error=None, **kwargs) -> FunctionWorker:
    """提交一个后台任务，返回 worker 以便调用方保持引用防止被 GC。"""
    worker = FunctionWorker(fn, *args, **kwargs)
    if on_done:
        worker.signals.finished.connect(on_done)
    if on_error:
        worker.signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
