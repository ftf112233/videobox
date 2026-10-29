"""一键打包。

把那条又长又容易出错的 pyinstaller 命令固化下来，顺便做前置检查——
打包最怕的是等了 3 分钟才发现 vendor 目录里没放 ffmpeg。

用法：
    python scripts/build.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
DIST = ROOT / "dist" / "VideoBox"

# 这些 Qt 模块本项目一个都不用，但 PySide6 会默认打进去，
# 不打掉的话包会从 120MB 涨到 400MB+
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtQuick3D", "PySide6.QtMultimedia",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
    "tkinter", "matplotlib", "numpy", "pandas", "scipy",
]


def check_vendor() -> bool:
    ffmpeg = VENDOR / "ffmpeg.exe"
    if not ffmpeg.is_file():
        print("✗ vendor/ffmpeg.exe 不存在。")
        print("  请按 docs/SETUP.md 获取 ffmpeg，把 ffmpeg.exe 和 ffprobe.exe 放进 vendor/ 目录。")
        return False

    # 没有 libx264 的话，"回退到软件编码"这条链会直接断掉
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-encoders"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if "libx264" not in proc.stdout:
        print("✗ vendor/ffmpeg.exe 不含 libx264 —— 多半是误用了 LGPL 构建。")
        print("  请换用 GPL 构建（详见 docs/SETUP.md）。")
        return False

    print(f"✓ vendor/ffmpeg.exe 就绪（{ffmpeg.stat().st_size / 1024 / 1024:.0f} MB）")
    if not (VENDOR / "ffprobe.exe").is_file():
        print("! 没有 ffprobe.exe，将只能走 ffmpeg -i 兜底解析")
    return True


def main() -> int:
    if not check_vendor():
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed", "--onedir", "--name", "VideoBox",
        "--add-data", "videobox/ui/style.qss;videobox/ui",
        "--add-binary", "vendor/ffmpeg.exe;resources/ffmpeg",
    ]
    if (VENDOR / "ffprobe.exe").is_file():
        cmd += ["--add-binary", "vendor/ffprobe.exe;resources/ffmpeg"]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    cmd.append("main.py")

    print("开始打包…")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("✗ 打包失败")
        return result.returncode

    exe = DIST / "VideoBox.exe"
    if not exe.is_file():
        print("✗ 没找到产物 dist/VideoBox/VideoBox.exe")
        return 1

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"\n✓ 打包完成：{exe}")
    print(f"  目录体积：{total:.0f} MB")

    # 顺便打个 zip 方便分发
    archive = shutil.make_archive(
        str(ROOT / "dist" / "VideoBox-win64"), "zip", str(DIST)
    )
    size_mb = Path(archive).stat().st_size / 1024 / 1024
    print(f"  分发包：{archive}（{size_mb:.0f} MB）")
    print("\n提醒：交付前请在干净环境（或临时移走本机 ffmpeg）双击验证一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
