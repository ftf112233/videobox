"""ffmpeg -progress 输出解析。

这是整个项目最容易出隐性 bug 的地方，所以单独抽出来做成纯逻辑：
不碰进程、不碰 Qt，可以拿手写样本喂到饱。

ffmpeg 的输出形如（每行 k=v）：
    frame=123
    fps=30.0
    out_time_us=4000000
    speed=1.5x
    progress=continue
    ...
    progress=end
"""

from __future__ import annotations

from .models import ProgressUpdate

# ETA 用最近 N 次采样做中位数，避免速度抖动导致数字乱跳
ETA_WINDOW = 7


def _to_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


class ProgressParser:
    """有状态的解析器：喂若干行，吐最新的进度快照。"""

    def __init__(self, duration_sec: float):
        self.duration_sec = max(0.0, float(duration_sec or 0.0))
        self.out_time_sec = 0.0
        self.speed = 0.0
        self.done = False
        # 每次 (out_time, speed) 采样，用来算更稳的 ETA
        self._samples: list[tuple[float, float]] = []

    def feed_line(self, line: str) -> ProgressUpdate | None:
        """喂一行；不是 k=v 的行直接忽略并返回 None。"""
        line = (line or "").strip()
        if not line or "=" not in line:
            return None

        # 只切第一个等号：值里可能出现 '='（例如某些 metadata）
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()

        if key == "out_time_us":
            # 老版本 ffmpeg 在开头会输出 "N/A"
            if value.upper().startswith("N/A"):
                return None
            self.out_time_sec = _to_float(value) / 1_000_000
        elif key == "out_time_ms":
            # 注意这个名字有坑：单位其实是微秒，跟 out_time_us 同值
            if value.upper().startswith("N/A"):
                return None
            self.out_time_sec = _to_float(value) / 1_000_000
        elif key == "speed":
            self.speed = _to_float(value.rstrip("x").strip())
        elif key == "progress":
            self.done = value == "end"
            return self._snapshot()
        else:
            return None

        return self._snapshot()

    def _snapshot(self) -> ProgressUpdate:
        percent = 0.0
        if self.duration_sec > 0:
            percent = self.out_time_sec / self.duration_sec
        percent = max(0.0, min(1.0, percent))
        if self.done:
            percent = 1.0

        return ProgressUpdate(
            percent=percent,
            out_time_sec=self.out_time_sec,
            speed=self.speed,
            eta_sec=self._eta(percent),
            done=self.done,
        )

    def _eta(self, percent: float) -> float | None:
        """剩余时间。前几秒不给值——开头速度还没稳，算出来纯属吓人。"""
        if self.done or percent <= 0.02 or percent >= 1.0:
            return 0.0 if self.done else None
        if self.speed <= 0.01:
            return None
        remaining = max(0.0, self.duration_sec - self.out_time_sec)
        eta = remaining / self.speed
        self._samples.append((self.out_time_sec, eta))
        if len(self._samples) > ETA_WINDOW:
            self._samples.pop(0)
        values = sorted(e for _, e in self._samples)
        return values[len(values) // 2]  # 中位数，比平均值抗抖动


def format_eta(seconds: float | None) -> str:
    """ETA 的人类可读形式。"""
    if seconds is None:
        return "计算中…"
    if seconds <= 0:
        return "即将完成"
    if seconds < 60:
        return f"剩余 {int(seconds)} 秒"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"剩余 {minutes} 分 {secs} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"剩余 {hours} 时 {minutes} 分"
