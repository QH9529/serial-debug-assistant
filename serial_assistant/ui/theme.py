"""界面主题：颜色令牌、QPalette 与 QSS。

单一强调色（铜橙），语义色仅用于状态；深色为默认，浅色可切换。
勾选/单选指示器图标在运行时生成到临时目录，供 QSS 引用。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

DARK = {
    "name": "dark",
    "label": "浅色",
    "bg": "#12141A",
    "surface": "#181B22",
    "surface_alt": "#1E222B",
    "surface_sunken": "#0E1015",
    "fg": "#E6E8EC",
    "muted": "#98A0AE",
    "border": "#2A2F3A",
    "border_strong": "#454C5C",
    "accent": "#D98A3D",
    "accent_hover": "#E39A50",
    "accent_pressed": "#C97C33",
    "accent_fg": "#14161B",
    "accent_soft": "#33281A",
    "success": "#4FA97A",
    "danger": "#D2605A",
    "warn": "#C9A227",
    "rx": "#E6E8EC",
    "tx": "#D98A3D",
    "sys": "#7F8896",
}

LIGHT = {
    "name": "light",
    "label": "深色",
    "bg": "#F4F4F2",
    "surface": "#FCFCFB",
    "surface_alt": "#F0F0ED",
    "surface_sunken": "#EDEDE9",
    "fg": "#171A1F",
    "muted": "#5B6472",
    "border": "#D7D7D2",
    "border_strong": "#A9AAA3",
    "accent": "#B4702A",
    "accent_hover": "#C07D34",
    "accent_pressed": "#9A5D20",
    "accent_fg": "#FFFFFF",
    "accent_soft": "#F1E2D0",
    "success": "#2F7D55",
    "danger": "#B4433D",
    "warn": "#8A6D14",
    "rx": "#171A1F",
    "tx": "#8A5514",
    "sys": "#6B7480",
}

THEMES = {"dark": DARK, "light": LIGHT}

_ICON_DIR = Path(tempfile.gettempdir()) / "serial_assistant_icons"


def _icon_dir() -> Path:
    _ICON_DIR.mkdir(parents=True, exist_ok=True)
    return _ICON_DIR


def _check_icon(color: str, size: int = 15) -> str:
    """生成勾选图标，返回给 QSS 用的正斜杠路径。"""
    path = _icon_dir() / f"check_{color.lstrip('#')}_{size}.png"
    if not path.exists():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(size * 0.24, size * 0.52), QPointF(size * 0.44, size * 0.72))
        painter.drawLine(QPointF(size * 0.44, size * 0.72), QPointF(size * 0.78, size * 0.28))
        painter.end()
        pixmap.save(str(path))
    return path.as_posix()


def _radio_icon(color: str, size: int = 15) -> str:
    """生成单选圆点图标。"""
    path = _icon_dir() / f"radio_{color.lstrip('#')}_{size}.png"
    if not path.exists():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(size / 2, size / 2), size * 0.22, size * 0.22)
        painter.end()
        pixmap.save(str(path))
    return path.as_posix()


_QSS = """
QWidget {{
    background-color: {bg};
    color: {fg};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QFrame#panel {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
}}
QLabel#panelTitle {{
    color: {muted};
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}}
QLabel#hint {{ color: {muted}; background: transparent; }}
QLabel#appName {{
    font-size: 14px;
    font-weight: 600;
    color: {fg};
    background: transparent;
}}
QLabel#appIcon {{ background: transparent; }}
QLabel#pill {{
    background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 1px 9px;
    color: {muted};
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 11px;
}}
QLabel#dotOn {{ background-color: {success}; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }}
QLabel#dotOff {{ background-color: {muted}; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }}

/* 勾选 / 单选指示器：显式描边与勾选图标，避免深色底上看不见 */
QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator,
QTableWidget::indicator, QTableView::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {border_strong};
    border-radius: 4px;
    background-color: {surface_sunken};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked, QTableWidget::indicator:checked, QTableView::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
    image: url({check_icon});
}}
QRadioButton::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
    image: url({radio_icon});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background-color: {surface};
    border-color: {border};
}}

QPushButton {{
    background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 5px 12px;
    color: {fg};
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background-color: {border}; }}
QPushButton:disabled {{ color: {muted}; border-color: {border}; background-color: transparent; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton#primary {{
    background-color: {accent};
    border: 1px solid {accent};
    color: {accent_fg};
    font-weight: 600;
    padding: 5px 16px;
}}
QPushButton#primary:hover {{ background-color: {accent_hover}; border-color: {accent_hover}; }}
QPushButton#primary:pressed {{ background-color: {accent_pressed}; }}
QPushButton#primary:disabled {{ background-color: {surface_alt}; color: {muted}; border-color: {border}; }}
QPushButton#ghost {{ background-color: transparent; padding: 5px 9px; }}
QPushButton#ghost:hover {{ border-color: {accent}; }}
QPushButton#rowDelete {{
    background-color: {surface_alt};
    border: 1px solid {border_strong};
    border-radius: 6px;
    color: {fg};
    padding: 3px 10px;
}}
QPushButton#rowDelete:hover {{ color: {danger}; border-color: {danger}; }}
QPushButton#rowDelete:pressed {{ background-color: {border}; }}

QComboBox, QLineEdit, QSpinBox {{
    background-color: {surface_sunken};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 4px 8px;
    color: {fg};
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: {accent}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; background: transparent; border: none; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {surface};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: {accent_fg};
    outline: none;
}}
QPlainTextEdit {{
    background-color: {surface_sunken};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 6px 8px;
    color: {fg};
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QPlainTextEdit:focus {{ border-color: {accent}; }}
QPlainTextEdit#log {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}

QTableWidget {{
    background-color: {surface_sunken};
    alternate-background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}}
QTableWidget::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected {{ background-color: {accent_soft}; color: {fg}; }}
QHeaderView::section {{
    background-color: {surface};
    color: {muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border_strong}; border-radius: 5px; min-height: 26px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border_strong}; border-radius: 5px; min-width: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QStatusBar {{ background-color: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background-color: {surface}; color: {fg}; border: 1px solid {border_strong}; padding: 4px 6px; }}
QDialog {{ background-color: {bg}; }}
"""


def build_qss(theme: dict) -> str:
    tokens = dict(theme)
    tokens["check_icon"] = _check_icon(theme["accent_fg"])
    tokens["radio_icon"] = _radio_icon(theme["accent_fg"])
    return _QSS.format(**tokens)


def build_palette(theme: dict) -> QPalette:
    palette = QPalette()
    bg = QColor(theme["bg"])
    surface = QColor(theme["surface"])
    fg = QColor(theme["fg"])
    muted = QColor(theme["muted"])
    accent = QColor(theme["accent"])
    accent_fg = QColor(theme["accent_fg"])
    palette.setColor(QPalette.Window, bg)
    palette.setColor(QPalette.WindowText, fg)
    palette.setColor(QPalette.Base, QColor(theme["surface_sunken"]))
    palette.setColor(QPalette.AlternateBase, QColor(theme["surface_alt"]))
    palette.setColor(QPalette.Text, fg)
    palette.setColor(QPalette.Button, QColor(theme["surface_alt"]))
    palette.setColor(QPalette.ButtonText, fg)
    palette.setColor(QPalette.Highlight, accent)
    palette.setColor(QPalette.HighlightedText, accent_fg)
    palette.setColor(QPalette.PlaceholderText, muted)
    palette.setColor(QPalette.ToolTipBase, surface)
    palette.setColor(QPalette.ToolTipText, fg)
    palette.setColor(QPalette.Disabled, QPalette.Text, muted)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, muted)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, muted)
    return palette


def apply_theme(app: QApplication, name: str) -> dict:
    """应用主题（深色 / 浅色），返回该主题的令牌字典。"""
    theme = THEMES.get(name, DARK)
    app.setStyle("Fusion")
    app.setPalette(build_palette(theme))
    app.setStyleSheet(build_qss(theme))
    return theme


def current_theme(name: str) -> dict:
    return THEMES.get(name, DARK)
