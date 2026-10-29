"""应用入口。

三件必做的事：
1. 装好日志（--noconsole 打包后异常不会弹窗，只能靠日志）
2. 装好全局异常钩子（否则未捕获异常会让窗口直接消失，用户以为程序坏了）
3. 加载 QSS（默认 Qt 控件长得像 1995 年，光这一项就决定"给人用"的第一印象）
"""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .infra.logging_setup import setup_logging
from .ui.main_window import MainWindow

log = logging.getLogger(__name__)

APP_NAME = "VideoBox"
APP_VERSION = "1.2.4"


def _resource_path(relative: str) -> Path:
    """兼容开发态与 PyInstaller 打包后的资源定位。

    这两种态的目录层级不一样，踩过一次：
      开发态  → videobox/ui/style.qss
      打包后  → _internal/videobox/ui/style.qss
    少一层 videobox 就会在打包后静默退回 Qt 默认外观（窗口还能开，
    但丑得认不出来），日志里只有一行 WARNING 很容易漏掉。
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "videobox" / relative
    return Path(__file__).resolve().parent / relative


def apply_light_palette(app: QApplication) -> None:
    """把调色板钉死成浅色，不跟随系统深色主题。

    界面颜色全部写在 QSS 里，但 QSS 只管它明确写了的部分。没写到的
    ——菜单栏、消息框、下拉列表的项、滚动条——走的是 palette。
    系统开深色主题时，这些地方会变成深底，而 QSS 里的文字色是深灰，
    结果就是"黑底深字"：控件还在，内容看不见。

    实际遇到过两次：下拉列表整片黑、菜单栏一条深灰。两次都不算崩溃，
    但都属于"程序没坏，就是用不了"。
    """
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    ink = QColor("#1F2329")
    paper = QColor("#FFFFFF")

    pal.setColor(QPalette.ColorRole.Window, QColor("#F5F6F7"))
    pal.setColor(QPalette.ColorRole.WindowText, ink)
    pal.setColor(QPalette.ColorRole.Base, paper)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F7F8FA"))
    pal.setColor(QPalette.ColorRole.Text, ink)
    pal.setColor(QPalette.ColorRole.Button, paper)
    pal.setColor(QPalette.ColorRole.ButtonText, ink)
    pal.setColor(QPalette.ColorRole.ToolTipBase, paper)
    pal.setColor(QPalette.ColorRole.ToolTipText, ink)
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#2F6FED"))
    pal.setColor(QPalette.ColorRole.HighlightedText, paper)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#A9AEB8"))
    app.setPalette(pal)


def load_stylesheet(app: QApplication) -> None:
    """装主题：调色板 + QSS。

    两件事绑在一起是有原因的——QSS 和 palette 必须同色调。只装 QSS
    的话，QSS 没写到的控件会跟系统主题走；只设 palette 的话，
    QSS 里的圆角、间距全没了。
    """
    apply_light_palette(app)

    qss_path = _resource_path("ui/style.qss")
    try:
        text = qss_path.read_text(encoding="utf-8")
    except OSError:
        log.warning("样式表未找到：%s（将使用 Qt 默认外观）", qss_path)
        return

    # QSS 里的 url() 相对的不是样式表所在目录，而是进程的工作目录。
    # 开发态碰巧对（cwd 就是仓库根），打包后双击 exe 时 cwd 是别处，
    # 图标会静默丢失。所以在这儿换成绝对路径（正斜杠，Qt 认）。
    ui_dir = qss_path.parent.as_posix()
    app.setStyleSheet(text.replace("__UI__", ui_dir))


def load_icon(app: QApplication) -> None:
    """应用级图标。窗口没单独设图标时会继承它，连消息框、任务栏也一起生效。"""
    ico = _resource_path("ui/app.ico")
    if not ico.exists():
        log.warning("图标未找到：%s", ico)
        return
    icon = QIcon(str(ico))
    if icon.isNull():
        log.warning("图标文件无法解析：%s", ico)
        return
    app.setWindowIcon(icon)


def install_excepthook(app: QApplication) -> None:
    """未捕获异常记日志并弹窗，而不是让窗口静默消失。"""

    def handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("未捕获异常：\n%s", detail)
        QMessageBox.critical(
            None, "程序出错",
            f"发生了未预期的错误：\n\n{exc_value}\n\n"
            "详细信息已写入日志（菜单 → 工具 → 打开日志目录）。",
        )

    sys.excepthook = handler


def main() -> int:
    setup_logging()
    log.info("=" * 50)
    log.info("%s v%s 启动，Python %s", APP_NAME, APP_VERSION, sys.version.split()[0])
    log.info("frozen=%s, cwd=%s", getattr(sys, "frozen", False), Path.cwd())

    # 高 DPI 屏上不设这个，界面会被系统缩放糊成一片
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    load_stylesheet(app)
    load_icon(app)
    install_excepthook(app)

    window = MainWindow()
    window.show()

    log.info("主窗口已显示")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
