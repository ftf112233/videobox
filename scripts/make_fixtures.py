"""生成测试素材。

仓库里不放视频文件：一段 5 秒 1080p 素材就有 40MB+，
clone 体验会很差。所以改成用脚本现场生成，谁需要谁跑。

用法：
    python scripts/make_fixtures.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from videobox.infra.ffmpeg_bin import find_binaries  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def build(ffmpeg: str, name: str, args: list[str]) -> None:
    out = FIXTURES / name
    if out.exists():
        print(f"  已存在，跳过：{name}")
        return
    print(f"  生成 {name} …")
    subprocess.run([ffmpeg, "-v", "error", "-y", *args, str(out)], check=True)
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"    → {size_mb:.1f} MB")


def main() -> int:
    bins = find_binaries()
    if not bins.ok:
        print("找不到 ffmpeg，请先安装或参考 docs/SETUP.md")
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    print(f"使用 ffmpeg：{bins.ffmpeg}")

    # 演示主素材：1080p + 噪声。加噪声是为了让编码器有真实的压缩空间，
    # 纯色块/测试图案几乎没有冗余，压不动，看不出效果。
    build(bins.ffmpeg, "demo_1080p.mp4", [
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-vf", "noise=alls=16:allf=t+u",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
    ])

    # 小体积素材：跑单测和冒烟用，秒级完成
    build(bins.ffmpeg, "sample_720p.mp4", [
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
    ])

    # 无音轨素材：验证 -an 分支
    build(bins.ffmpeg, "sample_noaudio.mp4", [
        "-f", "lavfi", "-i", "testsrc=size=854x480:rate=25:duration=5",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
    ])

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
