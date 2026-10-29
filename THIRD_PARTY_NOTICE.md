# 第三方组件声明

本项目代码以 MIT 许可证发布（见 [LICENSE](LICENSE)）。
以下是运行时依赖的第三方组件及其许可证。

---

## 1. FFmpeg

- **版本**：9.0.1（构建标识 `n9.0.1-11-ge47273f4d9-20260831`）
- **来源**：随包分发的 `ffmpeg.exe` / `ffprobe.exe` 为 Windows x64 静态构建
- **许可证**：**GPL v3**（构建配置含 `--enable-gpl --enable-version3`，
  并启用 `libx264`、`libx265`、`libxvid` 等 GPL 组件）

### 关于 GPL 与本项目的关系

本项目与 FFmpeg 的关系是**「独立可执行文件的进程调用」**：

- 本项目的 Python 代码**不链接** FFmpeg 的任何库（不 import libav*，不做 ctypes 绑定）
- 程序通过 `subprocess` / `QProcess` 以命令行方式启动 `ffmpeg.exe`，
  两者之间只通过标准输入输出与退出码通信
- `ffmpeg.exe` 作为独立程序原样分发，未做任何修改

这种"聚合（aggregation）"关系在 GPL 的通行解释下不要求主程序一并采用 GPL。
因此本项目代码保持 MIT，FFmpeg 保持其 GPL 授权。

**如果分发方希望规避 GPL 的全部争议**，可以：
1. 不分发 ffmpeg，改为要求用户自行安装（程序支持从 PATH 读取），或
2. 换用 LGPL 构建（注意：LGPL 构建**不含 libx264**，需要相应调整编码器策略）

### FFmpeg 源码获取

GPL 要求分发二进制时提供对应源码的获取方式。FFmpeg 源码：

- 官方仓库：https://git.ffmpeg.org/ffmpeg.git
- 对应版本标签：`n9.0.1`
- 构建脚本参考：https://github.com/BtbN/FFmpeg-Builds

---

## 2. PySide6 / Qt for Python

- **版本**：6.12.0
- **许可证**：LGPL v3（Qt 公司同时提供商业许可）
- **使用方式**：以动态链接方式使用，未修改 Qt 源码
- **合规说明**：LGPL 要求允许用户替换该库。PyInstaller 的 onedir 模式下
  Qt 的动态库以独立 `.dll` 文件存在于 `_internal` 目录，用户可自行替换，
  满足 LGPL 的"可替换"要求

---

## 3. Shiboken6

- **版本**：随 PySide6 6.12.0
- **许可证**：LGPL v3
- **用途**：PySide6 的 C++ 绑定层

---

## 4. Python

- **版本**：3.13.9（开发与打包环境）
- **许可证**：PSF License
- **说明**：PyInstaller 打包时会将 Python 解释器一并分发，符合 PSF 许可

---

## 5. PyInstaller

- **版本**：6.22.3
- **许可证**：GPL v2 with bootloader exception
- **说明**：其 bootloader 例外条款明确允许打包专有/其它许可的应用程序

---

## 6. DeepSeek API（可选，非捆绑）

- 本项目**不包含**任何 DeepSeek 的代码或模型权重
- 仅在用户自行配置 API Key 时，通过 HTTPS 调用其公开 API
- 未配置时程序使用本地规则引擎，完全不联网

---

## 测试素材说明

`tests/fixtures/` 下的视频**不在仓库中**，由 `scripts/make_fixtures.py`
使用 FFmpeg 的 `testsrc2` / `sine` 滤镜现场生成，不涉及任何第三方版权素材。
