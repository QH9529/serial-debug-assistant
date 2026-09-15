import subprocess
import sys
from pathlib import Path

import pytest

from serial_assistant.core.profile import load_profile, save_profile
from serial_assistant.core.scheduler import MODE_PER_ITEM, MessageItem

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    qt = pytest.importorskip("PySide6.QtWidgets")
    app = qt.QApplication.instance() or qt.QApplication([])
    yield app


def _items():
    return [
        MessageItem(content="AA 55", is_hex=True, interval_ms=200, note="心跳", enabled=True, checksum="crc16"),
        MessageItem(content=r"HELLO\n", is_hex=False, interval_ms=1000, note="文本", enabled=True, checksum="none"),
        MessageItem(content="RESET", is_hex=False, interval_ms=3000, note="复位", enabled=False, checksum="lrc"),
    ]


def test_main_window_table_round_trip(qapp, tmp_path):
    from serial_assistant.ui.main_window import MainWindow

    window = MainWindow()
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
    window.close()


def test_main_window_move_and_remove(qapp):
    from serial_assistant.ui.main_window import MainWindow

    window = MainWindow()
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
    window.close()


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
