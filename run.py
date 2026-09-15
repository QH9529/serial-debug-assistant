"""PyInstaller 打包入口。

    pyinstaller --noconfirm --windowed --name SerialDebugAssistant run.py
"""
from serial_assistant.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
