"""生成手工自测用的素材（三个最容易翻车的场景）。

刻意覆盖：
1. 中文名 + 空格（Windows 上 subprocess 参数传递的老坑）
2. 无音轨（音频流缺失时的参数拼装分支）
3. 竖屏（缩放逻辑不能想当然按宽度走）

用法：
    python scripts/make_manual_fixtures.py
产物：
    手工自测/*.mp4（已在 .gitignore 里，不入库）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from videobox.infra.ffmpeg_bin import find_binaries  # noqa: E402

OUT = ROOT / "手工自测"

CASES = [
    (
        "我的 旅行 视频 2026.mp4",
        ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=8",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
         "-vf", "noise=alls=12:allf=t+u",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-shortest"],
    ),
    (
        "无音轨 的 录屏.mp4",
        ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=6",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22"],
    ),
    (
        "竖屏 手机 拍的.mp4",
        ["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-c:a", "aac", "-b:a", "128k", "-shortest"],
    ),
]


def main() -> int:
    bins = find_binaries()
    if not bins.ok:
        print("找不到 ffmpeg，先看 docs/SETUP.md")
        return 1

    OUT.mkdir(exist_ok=True)
    for name, args in CASES:
        target = OUT / name
        print(f"生成 {name} …", end="", flush=True)
        subprocess.run([bins.ffmpeg, "-v", "error", "-y", *args, str(target)], check=True)
        print(f" {target.stat().st_size / 1048576:.1f} MB")
    print(f"\n完成，目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
