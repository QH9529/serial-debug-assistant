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
    """独立 ini 设置 + 非交互模式（不弹对话框），测试结束统一关闭。"""
    from serial_assistant.ui.main_window import MainWindow

    created = []

    def factory(name="settings.ini"):
        settings = QSettings(str(tmp_path / name), QSettings.IniFormat)
        window = MainWindow(settings=settings, interactive=False)
        created.append(window)
        return window

    yield factory

    for window in created:
        try:
            # 测试中窗口未 show()，close() 不会触发 closeEvent；显式关闭会话以免线程堆积
            for session in window.sessions():
                session.shutdown()
            window.close()
            window.setParent(None)
            window.deleteLater()
        except Exception:
            pass
    # 没有事件循环时 deleteLater 不会执行，手动冲刷，避免控件堆积拖慢后续用例
    qapp.processEvents()


def _items():
    return [
        MessageItem(content="AA 55", is_hex=False, interval_ms=200, note="心跳", enabled=True, checksum="none"),
        MessageItem(content=r"HELLO\n", is_hex=False, interval_ms=1000, note="文本", enabled=True, checksum="none"),
        MessageItem(content="RESET", is_hex=False, interval_ms=3000, note="复位", enabled=False, checksum="none"),
    ]


# ---------- 会话隔离 ----------
def test_sessions_are_isolated(windows):
    window = windows()
    first = window.current_session()
    second = window.add_session()

    assert window.tabs.count() == 2
    assert first is not second
    assert first.session_id != second.session_id

    first.send_table.set_items(_items())
    assert len(first.send_table.get_items()) == 3
    assert second.send_table.get_items() == []

    first.tx_text.setPlainText("AAA")
    assert second.tx_text.toPlainText() == ""

    first.mode_combo.setCurrentText("HEX")
    assert second.mode_combo.currentText() == "文本"

    first.quick_panel.add_slot(QuickSlot(label="A1", content="AA"))
    assert len(first.quick_panel.get_slots()) == 1
    assert second.quick_panel.get_slots() == []

    first._push_history("CMD", False)
    assert first.history_combo.count() == 2
    assert second.history_combo.count() == 1


def test_session_settings_are_per_session(windows):
    window = windows()
    first = window.current_session()
    second = window.add_session()
    first.quick_panel.add_slot(QuickSlot(label="A1", content="AA"))
    second.quick_panel.add_slot(QuickSlot(label="B1", content="BB"))
    first.baud_combo.setCurrentText("9600")
    second.baud_combo.setCurrentText("19200")
    window._save_settings()

    reopened = windows("settings.ini")
    sessions = reopened.sessions()
    assert len(sessions) == 2
    assert sessions[0].quick_panel.get_slots()[0].content == "AA"
    assert sessions[1].quick_panel.get_slots()[0].content == "BB"
    assert sessions[0].baud_combo.currentText() == "9600"
    assert sessions[1].baud_combo.currentText() == "19200"


def test_session_custom_name(windows):
    window = windows()
    session = window.current_session()
    session.port_combo.addItem("COM7")
    session.port_combo.setCurrentText("COM7")

    session.set_alias("温湿度模块")
    assert session.alias == "温湿度模块"
    assert "温湿度模块" in session.tab_text()
    assert "COM7" in session.tab_text()  # 串口名保留
    assert "温湿度模块" in session.label()
    assert "COM7" in session.label()
    assert "温湿度模块" in window.tabs.tabText(0)

    session.set_alias("")
    assert "COM7" in session.tab_text()
    assert "温湿度模块" not in session.tab_text()


def test_session_name_persists(windows):
    window = windows()
    session = window.current_session()
    session.set_alias("网关模块")
    window._save_settings()

    reopened = windows("settings.ini")
    assert reopened.sessions()[0].alias == "网关模块"
    assert "网关模块" in reopened.tabs.tabText(0)


def test_close_session_keeps_at_least_one(windows):
    window = windows()
    assert window.tabs.count() == 1
    window.close_session(0)
    assert window.tabs.count() == 1
    window.add_session()
    assert window.tabs.count() == 2
    window.close_session(1)
    assert window.tabs.count() == 1


# ---------- 串口占用与参数提示 ----------
def test_port_exclusivity_guard(windows):
    window = windows()
    first = window.current_session()
    second = window.add_session()
    for session in (first, second):
        session.port_combo.addItem("COM9")
        session.port_combo.setCurrentText("COM9")

    first._port_open = True  # 模拟第一个会话已占用 COM9
    assert window._port_in_use("COM9", first) is None
    assert window._port_in_use("COM9", second) == first.label()

    second._toggle_port()  # 应被拦截（非交互模式，不弹窗）
    assert second.is_open is False


def test_param_change_hint(windows):
    window = windows()
    session = window.current_session()
    session.baud_combo.setCurrentText("9600")
    assert session.param_hint.text() == ""

    session._port_open = True
    session.baud_combo.setCurrentText("19200")
    assert "重开" in session.param_hint.text()


# ---------- 广播 ----------
def test_broadcast_all_sessions(windows, monkeypatch):
    window = windows()
    first = window.current_session()
    second = window.add_session()
    records = []

    def recorder(session):
        def deliver(payload, echo=True, origin=None):
            records.append((session.session_id, bytes(payload)))
            return True

        return deliver

    monkeypatch.setattr(first, "deliver", recorder(first))
    monkeypatch.setattr(second, "deliver", recorder(second))

    window._broadcast_mode = "all"
    first._dispatch(b"AB")
    assert records == [(first.session_id, b"AB"), (second.session_id, b"AB")]

    records.clear()
    window._broadcast_mode = "current"
    first._dispatch(b"CD")
    assert records == [(first.session_id, b"CD")]


def test_broadcast_custom_selection(windows, monkeypatch):
    window = windows()
    first = window.current_session()
    second = window.add_session()
    third = window.add_session()
    records = []
    for session in (first, second, third):
        monkeypatch.setattr(
            session,
            "deliver",
            lambda payload, echo=True, origin=None, _s=session: records.append(_s.session_id) or True,
        )

    window._broadcast_mode = "custom"
    window._broadcast_ids = [second.session_id, third.session_id]
    first._dispatch(b"XY")
    assert records == [first.session_id, second.session_id, third.session_id]


# ---------- 转发 ----------
def test_forward_rule_relays_to_target(windows, monkeypatch):
    window = windows()
    first = window.current_session()
    second = window.add_session()
    records = []
    monkeypatch.setattr(
        second,
        "deliver",
        lambda payload, echo=True, origin=None: records.append((origin, bytes(payload))) or True,
    )

    first.refresh_forward_targets(window.sessions())
    index = first.forward_combo.findData(second.session_id)
    assert index > 0
    first.forward_combo.setCurrentIndex(index)
    assert first.forward_target_id == second.session_id

    first._on_data_received(b"\x01\x02")
    assert len(records) == 1
    assert records[0][1] == b"\x01\x02"
    assert records[0][0]

    # 关掉转发后不再转发
    first.forward_combo.setCurrentIndex(0)
    first._on_data_received(b"\x03")
    assert len(records) == 1


# ---------- 原有功能（改为按会话访问） ----------
def test_session_table_round_trip(windows, tmp_path):
    window = windows()
    session = window.current_session()
    session.send_table.set_items(_items())
    assert session.send_table.get_items() == _items()

    path = tmp_path / "scheme.json"
    save_profile(path, MODE_PER_ITEM, session.send_table.get_items())
    mode, loaded = load_profile(path)
    assert mode == MODE_PER_ITEM
    assert loaded == _items()

    session.send_table.clear_rows()
    session.send_table.set_items(loaded)
    assert session.send_table.get_items() == _items()


def test_session_move_and_remove(windows):
    window = windows()
    table = window.current_session().send_table
    table.set_items(_items())
    table.table.selectRow(0)
    table.move_current(1)
    items = table.get_items()
    assert items[0].content == "HELLO\\n"
    assert items[1].content == "AA 55"

    table.table.selectRow(0)
    table.remove_selected()
    assert len(table.get_items()) == 2


def test_row_delete_button(windows):
    window = windows()
    table = window.current_session().send_table
    table.set_items(_items())
    assert table.table.rowCount() == 3
    table.table.cellWidget(0, table.COL_DELETE).click()
    assert table.table.rowCount() == 2
    assert table.get_items()[0].content == "HELLO\\n"


def test_quick_slots_and_shortcuts(windows):
    window = windows()
    session = window.current_session()
    panel = session.quick_panel
    assert panel.get_slots() == []

    assert panel.add_slot(QuickSlot(label="读寄存器", content="AA 55", hotkey="F1"))
    panel.add_slot(QuickSlot(label="版本", content=r"AT+GMR\r\n", hotkey="Ctrl+1"))
    session._refresh_quick_shortcuts()
    assert len(session._quick_shortcuts) == 2

    session.quick_panel.set_slots([QuickSlot(content="A", hotkey="NotAKey++")])
    session._refresh_quick_shortcuts()
    assert len(session._quick_shortcuts) == 0


def test_display_modes_encoding_and_history(windows):
    window = windows()
    session = window.current_session()

    session._combo_set(session.display_combo, "both")
    session._on_data_received(b"\x01AB")
    assert "01 41 42" in session.rx_text.toPlainText()

    session.rx_text.clear()
    session._combo_set(session.display_combo, "text")
    session._combo_set(session.encoding_combo, "gbk")
    session._on_data_received("中文".encode("gbk"))
    assert "中文" in session.rx_text.toPlainText()

    session.rx_text.clear()
    session.auto_wrap_cb.setChecked(True)
    session._on_data_received(b"AB")
    session._on_data_received(b"CD")
    assert "ABCD" not in session.rx_text.toPlainText()
    session._flush_pending()
    assert "ABCD" in session.rx_text.toPlainText()

    session._push_history("CMD1", False)
    session._push_history("CMD2", False)
    session._push_history("CMD1", False)
    assert session.history_combo.count() == 3
    session._on_history_selected(1)
    assert session.tx_text.toPlainText() == "CMD1"


def test_control_lines_and_payload_builder(windows):
    window = windows()
    session = window.current_session()
    assert session.rts_cb.isChecked() is True
    assert session.dtr_cb.isChecked() is True
    session.rts_cb.setChecked(False)
    session.dtr_cb.setChecked(False)

    assert session._build_payload("A", False, False, "none", "crlf") == b"A\r\n"
    assert session._build_payload("A", False, False, "sum8", "none") == b"A\x41"
    assert session._build_payload("41 42", True, True, "none", "none") == b"AB"


def test_uniform_period_loop_payloads(windows):
    window = windows()
    session = window.current_session()
    session.send_table.set_items(_items())
    assert [p["interval_ms"] for p in session._collect_loop_payloads()] == [200, 1000]

    session.uniform_cb.setChecked(True)
    session.period_spin.setValue(500)
    assert [p["interval_ms"] for p in session._collect_loop_payloads()] == [500, 500]
    assert len(session._collect_loop_payloads()) == 2


def test_global_checksum_applies_to_all_sending(windows):
    from serial_assistant.core.checksum import append_checksum

    window = windows()
    session = window.current_session()
    session.send_table.set_items(
        [
            MessageItem(content="AA 55", interval_ms=200, enabled=True),
            MessageItem(content="DE AD", interval_ms=500, enabled=False),
        ]
    )
    session.mode_combo.setCurrentText("HEX")
    session.checksum_combo.setCurrentText("CRC16")

    payloads = session._collect_loop_payloads()
    assert len(payloads) == 1
    assert payloads[0]["payload"] == append_checksum(bytes.fromhex("AA55"), "crc16")

    single = session._build_payload("AA 55", True, True, "crc16", "none")
    assert single == payloads[0]["payload"]

    session.checksum_combo.setCurrentText("无")
    assert session._collect_loop_payloads()[0]["payload"] == bytes.fromhex("AA55")


def test_send_stats_and_clear(windows):
    window = windows()
    session = window.current_session()
    session.tx_text.setPlainText("AB")
    session._refresh_send_stats()
    assert session.send_stats_label.text() == "2 字节"
    assert session._compute_send_size() == 2

    session.mode_combo.setCurrentText("HEX")
    session.tx_text.setPlainText("41 42")
    session._refresh_send_stats()
    assert session.send_stats_label.text() == "2 字节"

    session.tx_text.setPlainText("ZZ")
    session._refresh_send_stats()
    assert session.send_stats_label.text() == "编码错误"
    assert session._compute_send_size() is None

    session.mode_combo.setCurrentText("文本")
    session.tx_text.setPlainText("hello")
    session._clear_send()
    assert session.tx_text.toPlainText() == ""


def test_auto_send_requires_open_port(windows):
    window = windows()
    session = window.current_session()
    session.auto_send_cb.setChecked(True)
    assert session.auto_send_cb.isChecked() is False
    assert session._auto_send_timer.isActive() is False


def test_timestamp_has_milliseconds(windows):
    import re

    window = windows()
    session = window.current_session()
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{3}", session._timestamp())
    session._append_line("rx", "AB")
    assert re.search(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\]", session.rx_text.toPlainText())


def test_loop_echoes_sent_frames(windows):
    window = windows()
    session = window.current_session()
    session.echo_cb.setChecked(True)
    session._on_loop_sent(1, bytes.fromhex("A55A0102"))
    text = session.rx_text.toPlainText()
    assert "A5 5A 01 02" in text
    assert "TX" in text

    session.rx_text.clear()
    session.echo_cb.setChecked(False)
    session._on_loop_sent(0, bytes.fromhex("A55A"))
    assert "A5 5A" not in session.rx_text.toPlainText()


def test_log_writes_batched_txt(windows, tmp_path):
    window = windows()
    session = window.current_session()
    session.log_dir = str(tmp_path)
    session.log_cb.setChecked(True)

    session._write_log("RX", "AA BB")
    session._flush_log()
    files = list(tmp_path.glob("serial_*.txt"))
    assert len(files) == 1
    assert "RX AA BB" in files[0].read_text(encoding="utf-8")

    session._write_log("TX", "01 02")
    session._flush_log()
    assert len(list(tmp_path.glob("serial_*.txt"))) == 1
    assert "TX 01 02" in files[0].read_text(encoding="utf-8")

    session.log_cb.setChecked(False)
    session._write_log("RX", "FFFF")
    session._flush_log()
    assert "FFFF" not in files[0].read_text(encoding="utf-8")


def test_port_combo_rebuilt_only_on_change(windows, monkeypatch):
    import serial_assistant.ui.session_widget as sw

    window = windows()
    session = window.current_session()
    monkeypatch.setattr(sw, "list_available_ports", lambda: ["COM1", "COM2"])
    session.refresh_ports()
    assert session.port_combo.count() == 2
    assert session._ports_cache == ["COM1", "COM2"]

    session.refresh_ports()
    assert session.port_combo.count() == 2

    monkeypatch.setattr(sw, "list_available_ports", lambda: ["COM1", "COM2", "COM3"])
    session.refresh_ports()
    assert session.port_combo.count() == 3


def test_quick_panel_empty_hint_not_duplicated(windows):
    window = windows()
    session = window.current_session()

    def hint_count():
        return len(
            [
                label
                for label in session.quick_panel.findChildren(type(session.quick_panel.hint))
                if label.text().startswith("还没有快捷指令")
            ]
        )

    assert hint_count() == 1
    session.quick_panel.set_slots([QuickSlot(content="A")])
    assert hint_count() == 0
    session.quick_panel.set_slots([])
    assert hint_count() == 1


def test_app_title_icon_and_version(windows):
    from PySide6.QtWidgets import QLabel

    from serial_assistant import __version__, resources
    from serial_assistant.ui.main_window import APP_VERSION_LABEL

    window = windows()
    assert APP_VERSION_LABEL == f"V{__version__}"
    assert window.windowTitle() == f"串口调试助手-{APP_VERSION_LABEL}"

    texts = [label.text() for label in window.findChildren(QLabel)]
    assert "串口调试助手" not in texts
    assert APP_VERSION_LABEL not in texts

    assert not window.windowIcon().isNull()
    assert resources.asset_path("app.ico") is not None
    assert resources.asset_path("app.png") is not None


def test_always_on_top_toggle(windows):
    from PySide6.QtCore import Qt as QtCore

    window = windows()
    window.top_cb.setChecked(True)
    assert bool(window.windowFlags() & QtCore.WindowStaysOnTopHint)
    window.top_cb.setChecked(False)
    assert not bool(window.windowFlags() & QtCore.WindowStaysOnTopHint)


def test_interval_cell_and_header_centered(windows):
    from PySide6.QtCore import Qt as QtCore

    window = windows()
    table = window.current_session().send_table
    table.set_items(_items())

    spin = table.table.cellWidget(0, table.COL_INTERVAL)
    assert spin.alignment() & QtCore.AlignHCenter

    header = table.table.horizontalHeaderItem(table.COL_INTERVAL)
    assert header.textAlignment() & QtCore.AlignHCenter
    assert table.table.cellWidget(0, table.COL_DELETE).height() == 24


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
