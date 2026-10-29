# 环境与 FFmpeg 安装

## 一、为什么 FFmpeg 不在仓库里

`ffmpeg.exe` 静态构建单文件就有 139MB，`ffprobe.exe` 又 138MB。
放进 git 会让 clone 变成几百兆，所以仓库只放代码，二进制通过脚本或 Release 分发。

**如果你只是想看效果**：直接下 [Releases](../../releases) 里的 `VideoBox-win64.zip`，
里面已经包含 ffmpeg，双击即可，不用看这份文档。

**如果你要从源码跑或自己打包**：按下面的步骤装 ffmpeg。

## 二、装 FFmpeg（三选一）

### 方案 A：winget（Win10/11 自带，最省事）

```powershell
winget install Gyan.FFmpeg
```

装完新开一个终端，验证：

```powershell
ffmpeg -version
```

### 方案 B：手动下载（推荐，版本可控）

从 [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases) 下载
`ffmpeg-master-latest-win64-gpl.zip`。

> ⚠️ **必须选 `gpl` 版本，不要选 `lgpl`**。LGPL 构建不含 `libx264`，
> 到时候"回退到软件编码"会直接失败。

解压到 `D:\develop\ffmpeg\`，让路径变成：

```
D:\develop\ffmpeg\bin\ffmpeg.exe
D:\develop\ffmpeg\bin\ffprobe.exe
```

这个位置是程序会自动搜索的"常见安装路径"之一。

### 方案 C：已有别的软件自带

FFmpeg 常被打包在各种工具里（视频软件、录屏工具、某些开发工具）。
可以在磁盘上搜一下：

```powershell
where /r C:\ ffmpeg.exe
where /r D:\ ffmpeg.exe
```

找到后把 `ffmpeg.exe` 和 `ffprobe.exe` 复制到项目的 `vendor\` 目录即可用于打包。

## 三、验证安装（三步都要过）

```powershell
# 1. 能跑
ffmpeg -version

# 2. 有关键编码器（这条最容易被忽略，缺了 x264 整个回退链就断了）
ffmpeg -hide_banner -encoders | findstr 264
#    必须看到 libx264
#    h264_nvenc / h264_qsv / h264_amf 是硬件编码，有更好，不强制

# 3. ffprobe 能出 JSON
ffprobe -v error -print_format json -show_format -show_streams 某个视频.mp4
```

## 四、程序的 ffmpeg 搜索顺序

`infra/ffmpeg_bin.py` 按这个顺序找，第一个找到就用：

1. `resources/ffmpeg/`（打包后的随包资源）
2. `vendor/`（源码开发时）
3. `resources/ffmpeg/`（项目目录内）
4. `%LOCALAPPDATA%\VideoBox\bin`
5. `D:\develop\ffmpeg\bin` / `C:\ffmpeg\bin` / `D:\ffmpeg\bin`
6. 系统 `PATH`

都找不到时，界面会给出明确的引导文案，而不是一句"初始化失败"。

## 五、配置 AI 参数顾问（可选）

不配也能用——会走本地规则引擎，功能完整。

配了之后走 DeepSeek，能理解更自由的自然语言：

```powershell
# 临时（当前终端有效）
set DEEPSEEK_API_KEY=sk-xxxxxx
```

或写进 `%APPDATA%\VideoBox\config.json`：

```json
{"api_key": "sk-xxxxxx"}
```

## 六、常见问题

**Q：界面是灰扑扑的 Qt 默认样子，没有圆角和配色**
样式表没加载。看日志（菜单 → 工具 → 打开日志目录）里有没有
`样式表未找到`。源码运行时是 `videobox/ui/style.qss`，
打包后应该是 `_internal/videobox/ui/style.qss`。

**Q：提示"显卡驱动版本过低，需要更新到 610.00 或更高"**
你的显卡驱动低于当前 ffmpeg 构建要求的 NVENC API 版本。两个选择：
升级显卡驱动（推荐），或者就用 CPU 编码（程序已自动降级，功能不受影响）。

**Q：转码出来的视频在微信里放不出来**
检查是否带了 `-pix_fmt yuv420p`。程序默认带，但如果源是 10bit，
某些播放器/平台只认 8bit yuv420p。

**Q：双击 exe 没反应**
看 `%APPDATA%\VideoBox\logs\app.log`。`--noconsole` 打包后异常不会弹窗，
只有日志里有线索。
