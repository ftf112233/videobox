"""PyInstaller 打包入口。

单独放一个顶层 main.py 而不是直接打 videobox/app.py，
是因为 PyInstaller 对包内入口的相对导入处理不稳。
"""

import sys

from videobox.app import main

if __name__ == "__main__":
    sys.exit(main())
