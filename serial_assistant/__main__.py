"""入口：python -m serial_assistant（或 python run.py）。"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from . import __version__, resources
    from .ui.main_window import APP_NAME, APP_VERSION_LABEL, MainWindow

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setApplicationDisplayName(f"{APP_NAME}-{APP_VERSION_LABEL}")
    icon = resources.app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()

    selftest = "--selftest" in argv
    if selftest:
        QTimer.singleShot(800, app.quit)

    exit_code = app.exec()
    if selftest:
        print("SELFTEST OK")
        return 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
