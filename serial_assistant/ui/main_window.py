"""主窗口。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..core.checksum import append_checksum
from ..core.codec import bytes_to_hex, encode_payload
from ..core.profile import ProfileError, load_profile, save_profile
from ..core.scheduler import MODE_PER_ITEM, MODE_SEQUENTIAL
from ..serial_worker import SerialWorkerController, list_available_ports
from .send_table import CHECKSUM_LABELS, SendTableWidget

BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]

PARITY_MAP = {"无": "N", "偶校验": "E", "奇校验": "O"}
FLOW_MAP = {"无": None, "硬件 RTS/CTS": "rtscts", "软件 XON/XOFF": "xonxoff"}

LOG_DIR = "logs"


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口调试助手")
        self.resize(960, 780)

        self._settings = QSettings("QH9529", "SerialDebugAssistant")
        self._port_open = False
        self._loop_active = False
        self._rx_count = 0
        self._tx_count = 0
        self._log_path = None
        self._log_day = ""

        self._controller = SerialWorkerController()
        self._worker = self._controller.worker

        self._build_ui()
        self._connect_signals()
        self._restore_settings()
        self.refresh_ports()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(self._build_port_group())
        layout.addWidget(self._build_receive_group(), 1)
        layout.addWidget(self._build_send_group())
        layout.addWidget(self._build_loop_group(), 2)

        self.statusBar().showMessage("就绪")

    def _build_port_group(self):
        group = QGroupBox("串口参数")
        grid = QGridLayout(group)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self.refresh_btn = QPushButton("刷新")
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("115200")
        self.databits_combo = QComboBox()
        self.databits_combo.addItems(["8", "7"])
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1", "2"])
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(list(PARITY_MAP.keys()))
        self.flow_combo = QComboBox()
        self.flow_combo.addItems(list(FLOW_MAP.keys()))
        self.reconnect_cb = QCheckBox("断线自动重连")
        self.open_btn = QPushButton("打开串口")

        grid.addWidget(QLabel("端口"), 0, 0)
        grid.addWidget(self.port_combo, 0, 1)
        grid.addWidget(self.refresh_btn, 0, 2)
        grid.addWidget(QLabel("波特率"), 0, 3)
        grid.addWidget(self.baud_combo, 0, 4)
        grid.addWidget(QLabel("数据位"), 0, 5)
        grid.addWidget(self.databits_combo, 0, 6)
        grid.addWidget(QLabel("停止位"), 0, 7)
        grid.addWidget(self.stopbits_combo, 0, 8)
        grid.addWidget(QLabel("校验"), 1, 0)
        grid.addWidget(self.parity_combo, 1, 1)
        grid.addWidget(QLabel("流控"), 1, 3)
        grid.addWidget(self.flow_combo, 1, 4)
        grid.addWidget(self.reconnect_cb, 1, 5, 1, 2)
        grid.addWidget(self.open_btn, 1, 7, 1, 2)
        return group

    def _build_receive_group(self):
        group = QGroupBox("接收区")
        layout = QVBoxLayout(group)
        bar = QHBoxLayout()
        self.hex_display_cb = QCheckBox("HEX 显示")
        self.timestamp_cb = QCheckBox("时间戳")
        self.timestamp_cb.setChecked(True)
        self.pause_cb = QCheckBox("暂停滚动")
        self.log_cb = QCheckBox("自动保存日志")
        self.rx_label = QLabel("RX 0 B")
        self.tx_label = QLabel("TX 0 B")
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_receive)
        for widget in (self.hex_display_cb, self.timestamp_cb, self.pause_cb, self.log_cb):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(self.rx_label)
        bar.addWidget(self.tx_label)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)
        self.rx_text = QPlainTextEdit()
        self.rx_text.setReadOnly(True)
        self.rx_text.document().setMaximumBlockCount(20000)
        layout.addWidget(self.rx_text)
        return group

    def _build_send_group(self):
        group = QGroupBox("单次发送")
        layout = QVBoxLayout(group)
        self.tx_text = QPlainTextEdit()
        self.tx_text.setMaximumHeight(72)
        self.tx_text.setPlaceholderText("输入要发送的内容，文本模式支持 \\n \\r \\t \\xhh 转义")
        layout.addWidget(self.tx_text)
        bar = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["文本", "HEX"])
        self.append_newline_cb = QCheckBox("追加 \\r\\n")
        self.escape_cb = QCheckBox("使用转义符")
        self.escape_cb.setChecked(True)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(list(CHECKSUM_LABELS.keys()))
        self.send_btn = QPushButton("发送")
        bar.addWidget(QLabel("模式"))
        bar.addWidget(self.mode_combo)
        bar.addWidget(self.append_newline_cb)
        bar.addWidget(self.escape_cb)
        bar.addWidget(QLabel("校验"))
        bar.addWidget(self.checksum_combo)
        bar.addStretch(1)
        bar.addWidget(self.send_btn)
        layout.addLayout(bar)
        return group

    def _build_loop_group(self):
        group = QGroupBox("多条循环发送")
        layout = QVBoxLayout(group)
        bar = QHBoxLayout()
        self.seq_radio = QRadioButton("顺序轮询")
        self.seq_radio.setChecked(True)
        self.per_radio = QRadioButton("单条周期")
        self.add_btn = QPushButton("添加")
        self.del_btn = QPushButton("删除")
        self.up_btn = QPushButton("上移")
        self.down_btn = QPushButton("下移")
        self.clear_btn = QPushButton("清空")
        self.save_btn = QPushButton("保存方案")
        self.load_btn = QPushButton("加载方案")
        self.loop_btn = QPushButton("开始循环")
        bar.addWidget(self.seq_radio)
        bar.addWidget(self.per_radio)
        bar.addSpacing(12)
        for widget in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.load_btn)
        bar.addWidget(self.loop_btn)
        layout.addLayout(bar)
        self.send_table = SendTableWidget()
        layout.addWidget(self.send_table)
        return group

    # ---------- 信号 ----------
    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.open_btn.clicked.connect(self._toggle_port)
        self.send_btn.clicked.connect(self._send_once)
        self.add_btn.clicked.connect(lambda: self.send_table.add_row())
        self.del_btn.clicked.connect(self.send_table.remove_selected)
        self.up_btn.clicked.connect(lambda: self.send_table.move_current(-1))
        self.down_btn.clicked.connect(lambda: self.send_table.move_current(1))
        self.clear_btn.clicked.connect(self.send_table.clear_rows)
        self.save_btn.clicked.connect(self._save_scheme)
        self.load_btn.clicked.connect(self._load_scheme)
        self.loop_btn.clicked.connect(self._toggle_loop)

        self._worker.data_received.connect(self._on_data_received)
        self._worker.bytes_sent.connect(self._on_bytes_sent)
        self._worker.status_changed.connect(self._on_status)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.port_opened.connect(self._on_port_opened)
        self._worker.port_closed.connect(self._on_port_closed)
        self._worker.port_lost.connect(self._on_port_lost)
        self._worker.loop_sent.connect(self._on_loop_sent)

    # ---------- 串口 ----------
    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        try:
            ports = list_available_ports()
        except Exception:
            ports = []
        self.port_combo.addItems(ports)
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def _toggle_port(self):
        if self._port_open:
            self._controller.loop_stop_requested.emit()
            self._set_loop_ui(False)
            self._controller.close_requested.emit()
            return
        port = self.port_combo.currentText().strip()
        if not port:
            self._warn("请先选择串口")
            return
        try:
            baudrate = int(self.baud_combo.currentText().strip() or "115200")
        except ValueError:
            self._warn("波特率必须是整数")
            return
        config = {
            "port": port,
            "baudrate": baudrate,
            "bytesize": int(self.databits_combo.currentText()),
            "stopbits": float(self.stopbits_combo.currentText()),
            "parity": PARITY_MAP[self.parity_combo.currentText()],
            "flow": FLOW_MAP[self.flow_combo.currentText()],
            "auto_reconnect": self.reconnect_cb.isChecked(),
        }
        self._controller.open_requested.emit(config)

    def _on_port_opened(self, port_name: str):
        self._port_open = True
        self.open_btn.setText("关闭串口")
        self._save_settings()

    def _on_port_closed(self):
        self._port_open = False
        self.open_btn.setText("打开串口")
        self._set_loop_ui(False)

    def _on_port_lost(self, message: str):
        self._port_open = False
        self.open_btn.setText("打开串口")
        self._set_loop_ui(False)
        self.statusBar().showMessage(f"{message}（可勾选「断线自动重连」）")

    def _on_status(self, message: str):
        self.statusBar().showMessage(message)

    def _on_error(self, message: str):
        self.statusBar().showMessage(message)
        if "打开串口失败" in message:
            QMessageBox.warning(self, "串口错误", message)

    # ---------- 接收 ----------
    def _clear_receive(self):
        self.rx_text.clear()

    def _on_data_received(self, payload):
        data = bytes(payload)
        self._rx_count += len(data)
        self.rx_label.setText(f"RX {self._rx_count} B")
        stamp = time.strftime("%H:%M:%S")
        if self.hex_display_cb.isChecked():
            text = bytes_to_hex(data)
        else:
            text = data.decode("utf-8", errors="replace")
        line = f"[{stamp}] {text}" if self.timestamp_cb.isChecked() else text
        scrollbar = self.rx_text.verticalScrollBar()
        previous = scrollbar.value()
        self.rx_text.appendPlainText(line)
        if self.pause_cb.isChecked():
            scrollbar.setValue(previous)
        if self.log_cb.isChecked():
            self._write_log(stamp, data)

    def _on_bytes_sent(self, count: int):
        self._tx_count += int(count)
        self.tx_label.setText(f"TX {self._tx_count} B")

    def _write_log(self, stamp: str, data: bytes):
        day = time.strftime("%Y-%m-%d")
        try:
            if self._log_path is None or self._log_day != day:
                Path(LOG_DIR).mkdir(exist_ok=True)
                self._log_path = Path(LOG_DIR) / f"serial_{day}.log"
                self._log_day = day
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] RX {bytes_to_hex(data)}\n")
        except OSError as exc:
            self.statusBar().showMessage(f"日志写入失败：{exc}")

    # ---------- 发送 ----------
    def _send_once(self):
        if not self._port_open:
            self._warn("请先打开串口")
            return
        text = self.tx_text.toPlainText()
        if not text:
            return
        is_hex = self.mode_combo.currentText() == "HEX"
        try:
            payload = encode_payload(text, is_hex, self.escape_cb.isChecked())
        except ValueError as exc:
            self._warn(f"编码错误：{exc}")
            return
        if self.append_newline_cb.isChecked():
            payload += b"\r\n"
        payload = append_checksum(payload, CHECKSUM_LABELS[self.checksum_combo.currentText()])
        if not payload:
            return
        self._controller.send_requested.emit(payload)

    # ---------- 循环发送 ----------
    def _toggle_loop(self):
        if self._loop_active:
            self._controller.loop_stop_requested.emit()
            self._set_loop_ui(False)
            self.statusBar().showMessage("循环发送已停止")
            return
        if not self._port_open:
            self._warn("请先打开串口再启动循环发送")
            return
        items = self.send_table.get_items()
        payloads = []
        for row, item in enumerate(items):
            if not item.enabled or not item.content.strip():
                continue
            try:
                raw = encode_payload(item.content, item.is_hex, True)
            except ValueError as exc:
                self._warn(f"第 {row + 1} 条编码错误：{exc}")
                return
            payloads.append(
                {
                    "index": row,
                    "payload": append_checksum(raw, item.checksum),
                    "interval_ms": item.interval_ms,
                }
            )
        if not payloads:
            self._warn("没有启用的发送条目")
            return
        mode = MODE_SEQUENTIAL if self.seq_radio.isChecked() else MODE_PER_ITEM
        self._controller.loop_requested.emit({"mode": mode, "payloads": payloads})
        self._set_loop_ui(True)
        mode_label = "顺序轮询" if mode == MODE_SEQUENTIAL else "单条周期"
        self.statusBar().showMessage(f"循环发送已启动：{len(payloads)} 条，{mode_label}")

    def _set_loop_ui(self, active: bool):
        self._loop_active = active
        self.loop_btn.setText("停止循环" if active else "开始循环")

    def _on_loop_sent(self, row: int):
        self.statusBar().showMessage(f"循环发送中：第 {row + 1} 条")

    # ---------- 方案 ----------
    def _save_scheme(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存发送方案", "send_scheme.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        mode = MODE_SEQUENTIAL if self.seq_radio.isChecked() else MODE_PER_ITEM
        try:
            save_profile(path, mode, self.send_table.get_items())
            self.statusBar().showMessage(f"方案已保存：{path}")
        except (OSError, ProfileError) as exc:
            self._warn(f"保存失败：{exc}")

    def _load_scheme(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载发送方案", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            mode, items = load_profile(path)
        except (OSError, ProfileError) as exc:
            self._warn(f"加载失败：{exc}")
            return
        self.send_table.set_items(items)
        if mode == MODE_PER_ITEM:
            self.per_radio.setChecked(True)
        else:
            self.seq_radio.setChecked(True)
        self.statusBar().showMessage(f"方案已加载：{path}")

    # ---------- 其它 ----------
    def _warn(self, message: str):
        QMessageBox.warning(self, "提示", message)

    def _restore_settings(self):
        settings = self._settings
        port = settings.value("port", "")
        if port:
            index = self.port_combo.findText(str(port))
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        baud = settings.value("baudrate", "115200")
        if baud:
            self.baud_combo.setCurrentText(str(baud))
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _save_settings(self):
        self._settings.setValue("port", self.port_combo.currentText())
        self._settings.setValue("baudrate", self.baud_combo.currentText())
        self._settings.setValue("geometry", self.saveGeometry())

    def closeEvent(self, event):
        try:
            self._controller.loop_stop_requested.emit()
            self._controller.close_requested.emit()
            self._controller.shutdown()
        finally:
            self._save_settings()
            event.accept()
