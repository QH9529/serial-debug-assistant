import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from serial_assistant.core.profile import load_profile, save_profile
from serial_assistant.core.quicksend import QuickSlot
from serial_assistant.core.scheduler import MODE_PER_ITEM, MessageItem

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    qt = pytest.importorskip("PySide6.QtWidgets")
    app = qt.QApplication.instance() or qt.QApplication([])
    yield app


@pytest.fixture
def windows(qapp, tmp_path):
    """用独立的 ini 设置文件建窗口，测试结束统一关闭，避免线程残留。"""
    from serial_assistant.ui.main_window import MainWindow

    created = []

    def factory(name="settings.ini"):
        settings = QSettings(str(tmp_path / name), QSettings.IniFormat)
        window = MainWindow(settings=settings)
        created.append(window)
        return window

    yield factory

    for window in created:
        try:
            window.close()
        except Exception:
            pass


def _items():
    return [
        MessageItem(content="AA 55", is_hex=True, interval_ms=200, note="心跳", enabled=True, checksum="crc16"),
        MessageItem(content=r"HELLO\n", is_hex=False, interval_ms=1000, note="文本", enabled=True, checksum="none"),
        MessageItem(content="RESET", is_hex=False, interval_ms=3000, note="复位", enabled=False, checksum="lrc"),
    ]


def test_main_window_table_round_trip(windows, tmp_path):
    window = windows()
    window.send_table.set_items(_items())
    assert window.send_table.get_items() == _items()

    path = tmp_path / "scheme.json"
    save_profile(path, MODE_PER_ITEM, window.send_table.get_items())
    mode, loaded = load_profile(path)
    assert mode == MODE_PER_ITEM
    assert loaded == _items()

    window.send_table.clear_rows()
    window.send_table.set_items(loaded)
    assert window.send_table.get_items() == _items()


def test_main_window_move_and_remove(windows):
    window = windows()
    table = window.send_table
    table.set_items(_items())
    table.table.selectRow(0)
    table.move_current(1)
    items = table.get_items()
    assert items[0].content == "HELLO\\n"
    assert items[1].content == "AA 55"

    table.table.selectRow(0)
    table.remove_selected()
    assert len(table.get_items()) == 2


def test_quick_slots_and_shortcuts(windows):
    window = windows()
    panel = window.quick_panel
    assert panel.get_slots() == []

    assert panel.add_slot(
        QuickSlot(label="读寄存器", content="01 03 00 00 00 0A", is_hex=True, checksum="crc16", hotkey="F1")
    )
    panel.add_slot(QuickSlot(label="版本", content=r"AT+GMR\r\n", hotkey="Ctrl+1"))
    assert len(panel.get_slots()) == 2
    window._refresh_quick_shortcuts()
    assert len(window._quick_shortcuts) == 2

    window._save_settings()

    reopened = windows("settings2.ini")
    reopened._settings.clear()
    reopened._settings.setValue("quick_slots", window._settings.value("quick_slots"))
    reopened.quick_panel.set_slots(window.quick_panel.get_slots())
    reopened._refresh_quick_shortcuts()
    assert len(reopened.quick_panel.get_slots()) == 2
    assert reopened.quick_panel.get_slots()[0].content == "01 03 00 00 00 0A"
    assert len(reopened._quick_shortcuts) == 2

    # 非法快捷键不应注册
    reopened.quick_panel.set_slots([QuickSlot(content="A", hotkey="NotAKey++")])
    reopened._refresh_quick_shortcuts()
    assert len(reopened._quick_shortcuts) == 0

    # 合法快捷键应注册
    reopened.quick_panel.set_slots([QuickSlot(content="A", hotkey="F5")])
    reopened._refresh_quick_shortcuts()
    assert len(reopened._quick_shortcuts) == 1


def test_display_modes_encoding_and_history(windows):
    window = windows()

    # 对照模式：HEX 与文本同屏
    window._combo_set(window.display_combo, "both")
    window._on_data_received(b"\x01AB")
    assert "01 41 42" in window.rx_text.toPlainText()

    # 编码切换：GBK 中文
    window.rx_text.clear()
    window._combo_set(window.display_combo, "text")
    window._combo_set(window.encoding_combo, "gbk")
    window._on_data_received("中文".encode("gbk"))
    assert "中文" in window.rx_text.toPlainText()

    # 自动换行：先缓冲，flush 后才成行
    window.rx_text.clear()
    window.auto_wrap_cb.setChecked(True)
    window._on_data_received(b"AB")
    window._on_data_received(b"CD")
    assert "ABCD" not in window.rx_text.toPlainText()
    window._flush_pending()
    assert "ABCD" in window.rx_text.toPlainText()

    # 发送历史：去重且最新在前
    window._push_history("CMD1", False)
    window._push_history("CMD2", False)
    window._push_history("CMD1", False)
    assert window.history_combo.count() == 3
    window._on_history_selected(1)
    assert window.tx_text.toPlainText() == "CMD1"


def test_control_lines_and_payload_builder(windows):
    window = windows()
    assert window.rts_cb.isChecked() is True
    assert window.dtr_cb.isChecked() is True

    # 未打开串口时切换控制线只记录状态，不应抛异常
    window.rts_cb.setChecked(False)
    window.dtr_cb.setChecked(False)

    assert window._build_payload("A", False, False, "none", "crlf") == b"A\r\n"
    assert window._build_payload("A", False, False, "sum8", "none") == b"A\x41"
    assert window._build_payload("41 42", True, True, "none", "none") == b"AB"


def test_module_selftest_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "serial_assistant", "--selftest"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SELFTEST OK" in result.stdout
