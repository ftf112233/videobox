"""ffmpeg 定位与编码器实测。

核心观点：`ffmpeg -encoders` 列表里有 h264_nvenc，**不代表这台机器能跑**。
本机就是活案例——RTX 5060 + 驱动 573.24，列表里有 NVENC，
实测却因为 "required nvenc API 13.1, found 13.0" 直接失败。

所以这里的探测一律真跑一次 1 秒试编码，并从失败日志里抠出人话原因。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

# 探测顺序：能用硬件就用硬件，跑不动就软编。
#
# 刻意只做两级（NVENC → libx264），不detect QSV/AMF：
# 1. QSV 在笔记本双显卡（Optimus）上失败率极高，探了也白探
# 2. AMF 在无 AMD 显卡的机器上会出现"初始化成功但输出无效"的假阳性，
#    实测本机（NVIDIA RTX 5060）就会误报可用，比不检测更糟
# 3. params 层只实现了 NVENC 与 x264 的参数，多探一个就多一个说谎的机会
CANDIDATE_CODECS = ("h264_nvenc", "libx264")

_DIAG_PATTERNS = (
    ("required nvenc api", "显卡驱动版本过低，需要更新到 610.00 或更高"),
    ("minimum required nvidia driver", "显卡驱动版本过低，需要更新 NVIDIA 驱动"),
    ("cannot load nvcuda", "未检测到可用的 NVIDIA 显卡或驱动未安装"),
    ("no capable devices found", "没有找到支持硬件编码的显卡"),
    ("no device available", "显卡被占用或不可用"),
    ("error initializing output stream", "硬件编码器初始化失败"),
    ("function not implemented", "当前显卡不支持该编码器"),
)


@dataclass(frozen=True)
class CodecProbe:
    """一次编码器实测的结果。"""

    codec: str
    ok: bool
    reason: str = ""
    elapsed_ms: int = 0

    @property
    def label(self) -> str:
        return {
            "h264_nvenc": "NVIDIA 显卡加速",
            "h264_qsv": "Intel 核显加速",
            "h264_amf": "AMD 显卡加速",
            "libx264": "CPU 编码",
        }.get(self.codec, self.codec)


@dataclass
class Binaries:
    """找到的可执行文件与其来源，用于在 UI/日志里说清楚"用的是哪个 ffmpeg"。"""

    ffmpeg: str
    ffprobe: str | None
    source: str

    @property
    def ok(self) -> bool:
        return bool(self.ffmpeg)


def _no_window() -> dict:
    return {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _candidate_dirs() -> list[tuple[Path, str]]:
    """按优先级列出可能的 ffmpeg 所在目录。"""
    dirs: list[tuple[Path, str]] = []

    # 1) 打包后的随包资源
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs.append((base / "resources" / "ffmpeg", "随包资源"))
        dirs.append((Path(sys.executable).parent / "resources" / "ffmpeg", "exe 同级资源"))

    # 2) 开发时的项目 vendor 目录
    project_root = Path(__file__).resolve().parents[2]
    dirs.append((project_root / "vendor", "项目 vendor 目录"))
    dirs.append((project_root / "resources" / "ffmpeg", "项目 resources 目录"))

    # 3) 用户级安装位置
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append((Path(local) / "VideoBox" / "bin", "用户目录"))

    # 4) 常见的手工安装位置
    for p in (r"D:\develop\ffmpeg\bin", r"C:\ffmpeg\bin", r"D:\ffmpeg\bin"):
        dirs.append((Path(p), "常见安装路径"))

    return dirs


def find_binaries() -> Binaries:
    """找 ffmpeg/ffprobe。顺序：随包 → vendor → 用户目录 → 常见路径 → PATH。"""
    for directory, source in _candidate_dirs():
        exe = directory / "ffmpeg.exe"
        if exe.is_file():
            probe = directory / "ffprobe.exe"
            return Binaries(
                ffmpeg=str(exe),
                ffprobe=str(probe) if probe.is_file() else None,
                source=f"{source}（{directory}）",
            )

    # 最后看 PATH：用户可能已经全局装过
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        ffprobe = shutil.which("ffprobe")
        return Binaries(ffmpeg=ffmpeg, ffprobe=ffprobe, source="系统 PATH")

    return Binaries(ffmpeg="", ffprobe=None, source="未找到")


def diagnose(stderr: str) -> str:
    """从 ffmpeg 的报错里抠出一句人话，用于 UI 展示。"""
    low = (stderr or "").lower()
    for needle, message in _DIAG_PATTERNS:
        if needle in low:
            return message
    return "该编码器在此机器上不可用"


def probe_codec(ffmpeg: str, codec: str) -> CodecProbe:
    """真跑一次 1 秒试编码。这是唯一可信的探测方式。

    注意用 testsrc2 而不是 testsrc：后者输出 RGB，硬件编码器只吃 yuv420p，
    会凭空造出一个 "-22 Invalid argument" 的假阴性。
    """
    if not ffmpeg:
        return CodecProbe(codec, False, "未找到 ffmpeg")

    started = time.perf_counter()
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="vb_probe_")
        os.close(fd)
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
            "-an", "-c:v", codec, "-pix_fmt", "yuv420p",
            tmp_path,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, timeout=25, **_no_window()
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode == 0 and Path(tmp_path).stat().st_size > 0:
            return CodecProbe(codec, True, "可用", elapsed)
        return CodecProbe(codec, False, diagnose(stderr), elapsed)
    except subprocess.TimeoutExpired:
        return CodecProbe(codec, False, "探测超时", 25000)
    except (OSError, ValueError) as exc:
        return CodecProbe(codec, False, f"探测异常：{exc}", 0)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def probe_all(ffmpeg: str) -> list[CodecProbe]:
    """依次实测所有候选编码器。libx264 一定在最后，它是兜底。"""
    return [probe_codec(ffmpeg, codec) for codec in CANDIDATE_CODECS]


def available_from(probes: list[CodecProbe]) -> list[str]:
    """从探测结果里筛出可用编码器，libx264 永远保底。"""
    ok = [p.codec for p in probes if p.ok]
    if "libx264" not in ok:
        ok.append("libx264")
    return ok


def summary_line(probes: list[CodecProbe]) -> str:
    """一行摘要，给状态栏用。

    只说到"用什么在转"，不解释为什么。上一版把失败原因整句塞进状态栏，
    空状态下用户第一眼看到的是「显卡驱动版本过低，需要更新到 610.00」——
    他既没法解决，也会以为软件有问题。原因挪到 summary_detail()，只在
    悬停时出现。
    """
    if not probes:
        return "未探测编码器"
    good = [p for p in probes if p.ok]
    if not good:
        return "无可用编码器"
    best = good[0]
    if best.codec == "libx264":
        return "CPU 编码"
    return best.label


def summary_detail(probes: list[CodecProbe]) -> str:
    """为什么选这个编码器——给悬停提示用。

    想问的人会悬停，不想知道的人不该被这句话挡住界面。
    """
    if not probes:
        return "还没有探测过编码器。"
    good = [p for p in probes if p.ok]
    if not good:
        return "没有找到能用的编码器，转码可能会失败。"
    best = good[0]
    if best.codec != "libx264":
        return f"正在用 {best.label}，速度比纯 CPU 快。"

    failed = [p for p in probes if not p.ok and p.codec != "libx264"]
    if failed:
        return (
            f"{failed[0].label} 没能启用：{failed[0].reason}\n"
            "改用 CPU 编码，速度慢一些，但任何机器上都能跑。"
        )
    return "这台机器没有可用的硬件编码，用 CPU 编码，最稳。"
