"""生成测试与演示素材。

仓库里不放视频文件：一段 10 秒 1080p 素材就有 40MB+，
clone 体验会很差。所以改成用脚本现场生成，谁需要谁跑。

用法：
    python scripts/make_fixtures.py            # 缺什么补什么
    python scripts/make_fixtures.py --force    # 全部重新生成

演示素材的早期版本用 testsrc2 + 全屏噪声，本意是"给编码器真实的压缩空间"，
结果生成出来是一屏雪花——人眼看就是"乱码的视频"，拿去做 GIF 演示反而像
程序坏了。现在换成三幕式短片（深色底 + 中文标题 + 缓慢渐显），画面是给人
看的；压缩空间靠轻微胶片颗粒保留，不至于压成几百 KB。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from videobox.infra.ffmpeg_bin import find_binaries  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

# Windows 自带的微软雅黑。TTC 里含多字重，ffmpeg 取第一个。
FONT_BOLD = "C\\:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C\\:/Windows/Fonts/msyh.ttc"


def _run(ffmpeg: str, args: list[str], out: Path) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", *args, str(out)], check=True)


def build_demo(ffmpeg: str, out: Path, height: int = 1080, crf: int = 14) -> None:
    """三幕短片：标题卡 → 内容卡 → 结尾卡，中间交叉淡化。

    每一幕单独编码再 xfade 拼，比一条巨型 filtergraph 好调试：
    画面不对时能直接看出是哪一幕的问题。

    height/crf 收成参数，是为了用同一套画面产出两种素材：
    1080p 高码率版给演示 GIF 用（源文件要够大才压得动），
    720p 低码率版放仓库里当试用样片（体积要够小才进得了 git）。
    """
    tmp = ROOT / "build" / "demo_scenes"
    tmp.mkdir(parents=True, exist_ok=True)

    scenes: list[tuple[str, str]] = []

    # ---- 第一幕：标题卡 ----
    s1 = (
        "color=c=0x0B1220:s=1920x1080:r=30:d=4,"
        f"drawtext=fontfile='{FONT_BOLD}':text='旅行记录 · 2026 春'"
        ":fontcolor=0xF8FAFC:fontsize=92:x=(w-text_w)/2:y=390"
        ":alpha='min(1,t/0.7)',"
        "drawbox=x='(iw-420*min(1,max(0,(t-0.6)/0.9)))/2':y=530"
        ":w='420*min(1,max(0,(t-0.6)/0.9))':h=4:color=0x60A5FA:t=fill,"
        f"drawtext=fontfile='{FONT_REG}':text='青岛 · 四天三夜 · 一路向海'"
        ":fontcolor=0x94A3B8:fontsize=38:x=(w-text_w)/2:y=570"
        ":alpha='min(1,max(0,(t-1.0)/0.8))',"
        # 页脚：让片头看起来是"做过设计"的，而不是一块空黑底
        f"drawtext=fontfile='{FONT_REG}':text='{height}p · 30fps · H.264'"
        ":fontcolor=0x475569:fontsize=26:x=(w-text_w)/2:y=930"
        ":alpha='min(1,max(0,(t-1.4)/0.8))',"
        "format=yuv420p"
    )
    scenes.append(("scene1.mp4", s1))

    # ---- 第二幕：内容卡（卡片宽度随时间生长，模拟"展开"）----
    s2 = (
        "color=c=0x111827:s=1920x1080:r=30:d=4,"
        f"drawtext=fontfile='{FONT_BOLD}':text='第一天 · 栈桥'"
        ":fontcolor=0xF8FAFC:fontsize=64:x=150:y=110:alpha='min(1,t/0.5)',"
        # 卡片铺满宽度，右侧放一个大号序号——一开始只做 760 宽，
        # 右半边全空，看着像没做完
        "drawbox=x=150:y=250:w='1620*min(1,max(0,(t-0.2)/0.8))':h=470"
        ":color=0x1F2937:t=fill,"
        "drawbox=x=150:y=250:w='1620*min(1,max(0,(t-0.2)/0.8))':h=470"
        ":color=0x3B82F6:t=3,"
        f"drawtext=fontfile='{FONT_BOLD}':text='01'"
        ":fontcolor=0x1E3A8A:fontsize=210:x=1440:y=330"
        ":alpha='min(1,max(0,(t-0.9)/0.6))',"
        f"drawtext=fontfile='{FONT_BOLD}':text='海浪 与 海鸥'"
        ":fontcolor=0xE5E7EB:fontsize=56:x=210:y=400"
        ":alpha='min(1,max(0,(t-1.0)/0.6))',"
        f"drawtext=fontfile='{FONT_REG}':text='早上六点 风很大 但天很蓝'"
        ":fontcolor=0x9CA3AF:fontsize=36:x=210:y=505"
        ":alpha='min(1,max(0,(t-1.3)/0.6))',"
        "format=yuv420p"
    )
    scenes.append(("scene2.mp4", s2))

    # ---- 第三幕：结尾卡（一道光带缓慢扫过）----
    s3 = (
        "color=c=0x1E1B4B:s=1920x1080:r=30:d=4,"
        f"drawtext=fontfile='{FONT_REG}':text='接下来'"
        ":fontcolor=0x818CF8:fontsize=40:x=(w-text_w)/2:y=360"
        ":alpha='min(1,t/0.6)',"
        # 文字里的冒号必须转义，否则会被当成滤镜参数分隔符，
        # 报出来的错还错位到下一个滤镜上（"drawtext 没有 drawbox 选项"）
        f"drawtext=fontfile='{FONT_BOLD}':text='崂山日出 · 05\\:12'"
        ":fontcolor=0xF8FAFC:fontsize=96:x=(w-text_w)/2:y=430"
        ":alpha='min(1,max(0,(t-0.4)/0.7))',"
        "drawbox=x='mod(t*520,iw+600)-300':y=700:w=280:h=3"
        ":color=0xA78BFA:t=fill,"
        f"drawtext=fontfile='{FONT_REG}':text='旅行记录 · 2026 春'"
        ":fontcolor=0x4C1D95:fontsize=30:x=(w-text_w)/2:y=960,"
        "format=yuv420p"
    )
    scenes.append(("scene3.mp4", s3))

    paths: list[Path] = []
    for name, graph in scenes:
        p = tmp / name
        _run(
            ffmpeg,
            ["-f", "lavfi", "-i", graph, "-c:v", "libx264",
             "-preset", "medium", "-crf", "14"],
            p,
        )
        paths.append(p)

    # 交叉淡化：offset 要减去前一次转场吃掉的时间
    graph = (
        "[0:v][1:v]xfade=transition=fade:duration=0.6:offset=3.4[v01];"
        "[v01][2:v]xfade=transition=fade:duration=0.6:offset=6.8[vx];"
        # 轻微胶片颗粒：让码率贴近真实拍摄素材，否则纯色块压出来小得不像话
        f"[vx]noise=alls=5:allf=t+u,scale=-2:{height},format=yuv420p[v]"
    )
    _run(
        ffmpeg,
        [
            "-i", str(paths[0]), "-i", str(paths[1]), "-i", str(paths[2]),
            "-f", "lavfi", "-i",
            # 柔和的三音垫底音，避免"有画面没声音"被当成坏文件
            "aevalsrc=0.05*sin(2*PI*196*t)+0.04*sin(2*PI*246.94*t)"
            "+0.035*sin(2*PI*293.66*t):s=48000:d=11",
            "-filter_complex", graph,
            "-map", "[v]", "-map", "3:a",
            "-af", "afade=t=in:st=0:d=1,afade=t=out:st=9.5:d=1.5",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-shortest",
        ],
        out,
    )


def build(ffmpeg: str, name: str, args: list[str], force: bool) -> None:
    out = FIXTURES / name
    if out.exists() and not force:
        print(f"  已存在，跳过：{name}")
        return
    print(f"  生成 {name} …")
    _run(ffmpeg, args, out)
    print(f"    → {out.stat().st_size / 1024 / 1024:.1f} MB")


def main() -> int:
    force = "--force" in sys.argv
    bins = find_binaries()
    if not bins.ok:
        print("找不到 ffmpeg，请先安装或参考 docs/SETUP.md")
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    print(f"使用 ffmpeg：{bins.ffmpeg}")

    # 演示主素材：11 秒 1080p。源文件必须大于 20MB，否则 GIF 里
    # "别超过 20MB"这个场景会落到"目标比源文件还大"的分支上。
    demo = FIXTURES / "demo_1080p.mp4"
    if demo.exists() and not force:
        print("  已存在，跳过：demo_1080p.mp4")
    else:
        print("  生成 demo_1080p.mp4 …")
        build_demo(bins.ffmpeg, demo)
        print(f"    → {demo.stat().st_size / 1024 / 1024:.1f} MB")

    # 小体积素材：跑单测和冒烟用，秒级完成
    build(bins.ffmpeg, "sample_720p.mp4", [
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
    ], force)

    # 无音轨素材：验证 -an 分支
    build(bins.ffmpeg, "sample_noaudio.mp4", [
        "-f", "lavfi", "-i", "testsrc=size=854x480:rate=25:duration=5",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
    ], force)

    # 仓库自带的试用样片：同一段画面，720p + 较低码率，控制在 10MB 以内。
    # 码率不能压太狠：太小的源文件会让"压到 20MB"落到"目标比源还大"的分支，
    # 主力场景反而演示不出来。
    # 有了它，clone 下来不装 ffmpeg 也能立刻拖个真视频进软件试。
    portable = ROOT / "docs" / "sample.mp4"
    if portable.exists() and not force:
        print("  已存在，跳过：docs/sample.mp4")
    else:
        print("  生成 docs/sample.mp4 …")
        build_demo(bins.ffmpeg, portable, height=720, crf=17)
        print(f"    → {portable.stat().st_size / 1024 / 1024:.1f} MB")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
