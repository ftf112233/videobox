"""后台任务工人的边界测试。

重点不是"能不能跑"，而是"接收方已经销毁时会不会把异常冒到 Qt 层"——
这个 bug 是在验证窗口状态记忆时偶然撞出来的：程序刚启动就关闭，
环境探测线程仍在跑，结果回来时窗口没了，emit 直接抛
`RuntimeError: Signal source has been deleted`。
"""

from __future__ import annotations

import unittest

from videobox.ui.tasks import FunctionWorker


class _DeadSignal:
    """模拟已被销毁的信号对象。"""

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, value) -> None:  # noqa: ANN001
        self.calls += 1
        raise RuntimeError("Signal source has been deleted")


class _LiveSignal:
    def __init__(self) -> None:
        self.values = []

    def emit(self, value) -> None:  # noqa: ANN001
        self.values.append(value)


class _FakeSignals:
    """替换掉真的 WorkerSignals，好在主线程里同步断言。"""

    def __init__(self) -> None:
        self.finished = _LiveSignal()
        self.failed = _LiveSignal()


class EmitGuardTest(unittest.TestCase):
    def test_dead_receiver_does_not_raise(self):
        # 接收方已销毁时，emit 必须被吞掉，而不是把异常抛到 QRunnable::run
        FunctionWorker._emit(_DeadSignal(), 42)  # 不抛即通过

    def test_live_receiver_still_gets_value(self):
        live = _LiveSignal()
        FunctionWorker._emit(live, "ok")
        self.assertEqual(live.values, ["ok"])


class WorkerRunTest(unittest.TestCase):
    def test_success_emits_result(self):
        worker = FunctionWorker(lambda a, b: a + b, 2, 3)
        fake = _FakeSignals()
        worker.signals = fake  # type: ignore[assignment]
        worker.run()
        self.assertEqual(fake.finished.values, [5])

    def test_exception_emits_failure_and_swallows(self):
        def boom():
            raise ValueError("坏的输入")

        worker = FunctionWorker(boom)
        fake = _FakeSignals()
        worker.signals = fake  # type: ignore[assignment]
        worker.run()  # 不能把异常抛出去，否则线程静默死掉
        self.assertEqual(len(fake.failed.values), 1)
        self.assertIn("坏的输入", fake.failed.values[0])


if __name__ == "__main__":
    unittest.main()
