"""界面主题：颜色令牌、QPalette 与 QSS。

单一强调色（铜橙），语义色仅用于状态；深色为默认，浅色可切换。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
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
QPushButton#ghost {{ background-color: transparent; }}
QPushButton#ghost:hover {{ border-color: {accent}; }}
QComboBox, QLineEdit {{
    background-color: {surface_sunken};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {muted}; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {accent}; }}
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
    border: 1px solid {border};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {accent};
    selection-color: {accent_fg};
}}
QPlainTextEdit#log {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}
QTableWidget {{
    background-color: {surface_sunken};
    alternate-background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}}
QTableWidget::item {{ padding: 3px 6px; }}
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
QRadioButton, QCheckBox {{ spacing: 6px; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 26px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QStatusBar {{ background-color: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background-color: {surface}; color: {fg}; border: 1px solid {border}; padding: 4px 6px; }}
"""


def build_qss(theme: dict) -> str:
    return _QSS.format(**theme)


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
