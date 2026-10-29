"""无 GUI 冒烟测试：把 probe → params → QProcess 转码全链路跑一遍。

存在意义：GUI 还没写好的时候就能验证底层是不是通的，
而且它不依赖界面，可以在任何机器上当作健康检查跑。

用法：
    python scripts/smoke_transcode.py <视频路径> [需求描述]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

from videobox.core import local_rules  # noqa: E402
from videobox.core.params import build_args, build_preview_command, choose_codec  # noqa: E402
from videobox.core.probe import probe  # noqa: E402
from videobox.core.progress import format_eta  # noqa: E402
from videobox.infra.ffmpeg_bin import (  # noqa: E402
    available_from, find_binaries, probe_all, summary_line,
)
from videobox.infra.process import TranscodeRunner  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/smoke_transcode.py <视频路径> [需求描述]")
        return 2

    video = sys.argv[1]
    request = sys.argv[2] if len(sys.argv) > 2 else "压缩一下发给朋友"

    app = QCoreApplication(sys.argv)

    print("=" * 64)
    bins = find_binaries()
    print(f"ffmpeg 来源 : {bins.source}")
    print(f"ffmpeg 路径 : {bins.ffmpeg}")
    print(f"ffprobe     : {bins.ffprobe or '（无，将走 ffmpeg -i 兜底）'}")
    if not bins.ok:
        print("!! 找不到 ffmpeg，无法继续")
        return 1

    print("-" * 64)
    print("实测编码器（真跑 1 秒试编码，而不是只看列表）：")
    probes = probe_all(bins.ffmpeg)
    for p in probes:
        mark = "✓" if p.ok else "✗"
        print(f"  {mark} {p.codec:<12} {p.elapsed_ms:>5}ms  {p.reason}")
    codecs = available_from(probes)
    print(f"  → 可用: {codecs}")
    print(f"  → {summary_line(probes)}")

    print("-" * 64)
    info = probe(video, bins.ffprobe, bins.ffmpeg)
    print(f"源文件 : {Path(video).name}")
    print(f"  摘要 : {info.summary_line()}")

    plan, rule = local_rules.advise(request, info)
    print(f"需求     : {request}")
    print(f"命中规则 : {rule} → {plan.preset_name}")
    print(f"参数     : {plan.container} / {plan.scale} / q={plan.quality_value} / "
          f"a={plan.audio_bitrate_kbps}k" + (f" / 目标 {plan.target_size_mb}MB" if plan.target_size_mb else ""))
    for r in plan.reasons:
        print(f"  · {r}")
    for risk in plan.risks:
        print(f"  ⚠ {risk}")

    codec = choose_codec(plan.video_codec, codecs)
    out_path = str(ROOT / "tests" / "fixtures" / f"out_{Path(video).stem}.mp4")
    print("-" * 64)
    print(build_preview_command(plan, info, video, out_path, codecs))
    print("-" * 64)

    runner = TranscodeRunner(
        ffmpeg=bins.ffmpeg,
        args=build_args(plan, info, video, out_path, codecs),
        input_path=video,
        output_path=out_path,
        duration_sec=info.duration_sec,
        used_codec=codec,
    )

    state = {"last": -1}

    def on_progress(update):
        pct = int(update.percent * 100)
        if pct // 10 != state["last"] // 10:
            state["last"] = pct
            print(f"  {pct:3d}%  {format_eta(update.eta_sec)}  speed={update.speed:.2f}x")

    def on_finished(result):
        print("-" * 64)
        if result.ok:
            print(f"✓ 转码成功  {result.elapsed_sec}s  {result.speed:.2f}x  "
                  f"{result.size_delta_label}  → {result.output_path}")
        else:
            print(f"✗ 转码失败：{result.error_message}")
        app.quit()

    runner.progressed.connect(on_progress)
    runner.log_line.connect(lambda s: print(f"    [ffmpeg] {s}"))
    runner.finished.connect(on_finished)

    QTimer.singleShot(0, runner.start)
    QTimer.singleShot(180_000, lambda: (print("超时"), app.quit()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
