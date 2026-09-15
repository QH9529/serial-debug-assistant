"""生成界面预览图（无显示器环境也能跑）。

    .venv\\Scripts\\python.exe tools/preview.py preview
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from serial_assistant.core.quicksend import QuickSlot  # noqa: E402
from serial_assistant.core.scheduler import MessageItem  # noqa: E402
from serial_assistant.ui.main_window import MainWindow  # noqa: E402

DEMO_ITEMS = [
    MessageItem(
        content="01 03 00 00 00 0A",
        is_hex=True,
        interval_ms=500,
        note="读保持寄存器",
        enabled=True,
        checksum="crc16",
    ),
    MessageItem(
        content=r"AT+GMR\r\n",
        is_hex=False,
        interval_ms=1000,
        note="查询固件版本",
        enabled=True,
        checksum="none",
    ),
    MessageItem(
        content="A5 5A 01 02",
        is_hex=True,
        interval_ms=200,
        note="心跳帧",
        enabled=False,
        checksum="sum8",
    ),
    MessageItem(
        content=r"PING\n",
        is_hex=False,
        interval_ms=3000,
        note="保活",
        enabled=True,
        checksum="lrc",
    ),
]

DEMO_QUICK = [
    QuickSlot(label="读寄存器", content="01 03 00 00 00 0A", is_hex=True, checksum="crc16", hotkey="F1"),
    QuickSlot(label="版本查询", content=r"AT+GMR\r\n", hotkey="F2"),
    QuickSlot(label="复位", content="RESET", hotkey="F3"),
    QuickSlot(label="心跳", content="A5 5A 01 02", is_hex=True, checksum="sum8", hotkey="F4"),
]

DEMO_LOG = [
    ("sys", "已打开 COM7 @ 115200"),
    ("tx", "01 03 00 00 00 0A C5 CD"),
    ("rx", "01 03 14 00 64 00 C8 00 32 01 2C 00 00 00 00 00 0F 00 1E 00 28 A1 3B"),
    ("tx", "AT+GMR"),
    ("rx", "AT version: 1.7.4.0"),
    ("rx", "SDK version: 3.0.4"),
    ("sys", "循环发送已启动：3 条，顺序轮询"),
    ("tx", "A5 5A 01 02 4C"),
]


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "preview")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    window = MainWindow()
    window.send_table.set_items(DEMO_ITEMS)
    window.quick_panel.set_slots(DEMO_QUICK)
    window.tx_text.setPlainText("01 03 00 00 00 0A")
    window.mode_combo.setCurrentText("HEX")
    window.rx_text.clear()
    for kind, text in DEMO_LOG:
        window._append_line(kind, text)
    window._set_conn_state(True, "COM7 @ 115200")
    window.resize(1280, 820)

    for name in ("dark", "light"):
        window._theme_name = name
        window._apply_theme()
        app.processEvents()
        path = out_dir / f"ui-{name}.png"
        window.grab().save(str(path))
        print("saved", path)

    window.close()
    print("PREVIEW_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
