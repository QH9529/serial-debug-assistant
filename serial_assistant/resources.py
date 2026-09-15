"""应用资源（图标等）的路径解析与加载，兼容源码运行与 PyInstaller 打包。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def _base_dirs():
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "serial_assistant")
        dirs.append(Path(meipass))
    dirs.append(Path(__file__).resolve().parent)
    return dirs


def asset_path(name: str):
    """返回资源文件的真实路径；找不到返回 None。"""
    for base in _base_dirs():
        candidate = base / "assets" / name
        if candidate.exists():
            return candidate
    return None


def app_icon() -> QIcon:
    """应用图标；资源缺失时返回空图标（不会抛异常）。"""
    for name in ("app.ico", "app.png"):
        path = asset_path(name)
        if path is None:
            continue
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return QIcon()
