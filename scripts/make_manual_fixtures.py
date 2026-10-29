"""生成手工自测用的素材（三个最容易翻车的场景）。

刻意覆盖：
1. 中文名 + 空格（Windows 上 subprocess 参数传递的老坑）
2. 无音轨（音频流缺失时的参数拼装分支）
3. 竖屏（缩放逻辑不能想当然按宽度走）

以前这三个都用 testsrc2 + 全屏噪声生成，画面是一屏雪花——测路径没问题，
但人打开一看会以为素材坏了。现在前两个直接取自演示短片，第三个用竖屏
画布现画一张带文字的，保证点开能看懂自己在看什么。

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
DEMO = ROOT / "tests" / "fixtures" / "demo_1080p.mp4"
FONT_BOLD = "C\\:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C\\:/Windows/Fonts/msyh.ttc"


def portrait_graph() -> str:
    """竖屏画布：1080×1920，标题居中偏上。"""
    return (
        "color=c=0x0B1220:s=1080x1920:r=30:d=6,"
        f"drawtext=fontfile='{FONT_BOLD}':text='竖屏 1080×1920'"
        ":fontcolor=0xF8FAFC:fontsize=78:x=(w-text_w)/2:y=760,"
        "drawbox=x='(iw-300)/2':y=900:w=300:h=4:color=0x60A5FA:t=fill,"
        f"drawtext=fontfile='{FONT_REG}':text='这条用来测竖屏缩放'"
        ":fontcolor=0x94A3B8:fontsize=40:x=(w-text_w)/2:y=940,"
        f"drawtext=fontfile='{FONT_REG}':text='不能被拉变形'"
        ":fontcolor=0x64748B:fontsize=34:x=(w-text_w)/2:y=1010,"
        "format=yuv420p"
    )


def main() -> int:
    bins = find_binaries()
    if not bins.ok:
        print("找不到 ffmpeg，先看 docs/SETUP.md")
        return 1

    if not DEMO.is_file():
        print("缺少演示素材，先跑：python scripts/make_fixtures.py")
        return 1

    OUT.mkdir(exist_ok=True)
    jobs: list[tuple[str, list[str]]] = [
        # 直接流拷贝：不重编码就不会把颗粒洗掉，体积与源一致（约 59MB），
        # 中文名这条测的是路径处理，画面得跟原片一样才看得出缩放/质量有没有问题
        ("我的 旅行 视频 2026.mp4", ["-i", str(DEMO), "-c", "copy"]),
        ("无音轨 的 录屏.mp4", [
            "-i", str(DEMO), "-an", "-vf", "scale=1280:-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        ]),
        ("竖屏 手机 拍的.mp4", [
            "-f", "lavfi", "-i", portrait_graph(),
            "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-shortest",
        ]),
    ]

    for name, args in jobs:
        target = OUT / name
        print(f"生成 {name} …", end="", flush=True)
        subprocess.run(
            [bins.ffmpeg, "-v", "error", "-y", *args, str(target)], check=True
        )
        print(f" {target.stat().st_size / 1048576:.1f} MB")

    print(f"\n完成，目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
