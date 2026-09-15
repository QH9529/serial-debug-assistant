"""主窗口：串口参数、接收日志、单次发送与多条循环发送。"""
from __future__ import annotations

import html
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.checksum import append_checksum
from ..core.codec import bytes_to_hex, encode_payload
from ..core.profile import ProfileError, load_profile, save_profile
from ..core.scheduler import MODE_PER_ITEM, MODE_SEQUENTIAL
from ..serial_worker import SerialWorkerController, list_available_ports
from . import theme as theme_mod
from .send_table import CHECKSUM_LABELS, SendTableWidget

BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]

PARITY_MAP = {"无校验": "N", "偶校验": "E", "奇校验": "O"}
FLOW_MAP = {"无流控": None, "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff"}

LOG_DIR = "logs"
KIND_LABELS = {"rx": "RX", "tx": "TX", "sys": "SYS"}


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口调试助手")
        self.resize(1180, 760)

        self._settings = QSettings("QH9529", "SerialDebugAssistant")
        self._theme_name = str(self._settings.value("theme", "dark") or "dark")
        self._theme = theme_mod.current_theme(self._theme_name)

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
        self._append_line("sys", "就绪。选择串口并打开后即可收发；循环发送支持顺序轮询与单条周期两种调度。")

    # ---------- 主题 ----------
    def _apply_theme(self):
        app = QApplication.instance()
        if app is not None:
            self._theme = theme_mod.apply_theme(app, self._theme_name)
        if hasattr(self, "theme_btn"):
            self.theme_btn.setText(self._theme["label"])

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 10)
        layout.setSpacing(12)

        layout.addWidget(self._build_connection_bar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_log_panel())

        right = QSplitter(Qt.Vertical)
        right.addWidget(self._build_send_panel())
        right.addWidget(self._build_loop_panel())
        right.setStretchFactor(0, 0)
        right.setStretchFactor(1, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 540])
        layout.addWidget(splitter, 1)

        self.statusBar().showMessage("就绪")

    @staticmethod
    def _panel(title: str):
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("panelTitle")
            layout.addWidget(label)
        return frame, layout

    def _build_connection_bar(self):
        panel, layout = self._panel("串口连接")
        row = QHBoxLayout()
        row.setSpacing(8)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(132)
        self.port_combo.setToolTip("可用串口，插拔设备后点「刷新」")
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("ghost")

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMinimumWidth(96)

        self.databits_combo = QComboBox()
        self.databits_combo.addItems(["8 位", "7 位"])
        self.databits_combo.setToolTip("数据位")
        self.databits_combo.setFixedWidth(64)
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1 位", "2 位"])
        self.stopbits_combo.setToolTip("停止位")
        self.stopbits_combo.setFixedWidth(64)
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(list(PARITY_MAP.keys()))
        self.parity_combo.setToolTip("校验位")
        self.parity_combo.setFixedWidth(88)
        self.flow_combo = QComboBox()
        self.flow_combo.addItems(list(FLOW_MAP.keys()))
        self.flow_combo.setToolTip("流控")
        self.flow_combo.setFixedWidth(100)
        self.reconnect_cb = QCheckBox("断线自动重连")

        self.open_btn = QPushButton("打开串口")
        self.open_btn.setObjectName("primary")

        self.dot = QLabel()
        self.dot.setObjectName("dotOff")
        self.conn_label = QLabel("未连接")
        self.conn_label.setObjectName("pill")

        self.theme_btn = QPushButton(self._theme["label"])
        self.theme_btn.setObjectName("ghost")
        self.theme_btn.setToolTip("切换深色 / 浅色主题")
        self.theme_btn.clicked.connect(self._toggle_theme)

        port_tag = QLabel("端口")
        port_tag.setObjectName("hint")
        baud_tag = QLabel("波特率")
        baud_tag.setObjectName("hint")
        row.addWidget(port_tag)
        row.addWidget(self.port_combo)
        row.addWidget(self.refresh_btn)
        row.addWidget(baud_tag)
        row.addWidget(self.baud_combo)
        row.addWidget(self.databits_combo)
        row.addWidget(self.stopbits_combo)
        row.addWidget(self.parity_combo)
        row.addWidget(self.flow_combo)
        row.addWidget(self.reconnect_cb)
        row.addStretch(1)
        row.addWidget(self.dot)
        row.addWidget(self.conn_label)
        row.addWidget(self.open_btn)
        row.addWidget(self.theme_btn)
        layout.addLayout(row)
        return panel

    def _build_log_panel(self):
        panel, layout = self._panel("接收日志")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.hex_display_cb = QCheckBox("HEX 显示")
        self.timestamp_cb = QCheckBox("时间戳")
        self.timestamp_cb.setChecked(True)
        self.pause_cb = QCheckBox("暂停滚动")
        self.log_cb = QCheckBox("自动保存日志")
        self.rx_label = QLabel("RX 0 B")
        self.rx_label.setObjectName("pill")
        self.tx_label = QLabel("TX 0 B")
        self.tx_label.setObjectName("pill")
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self._clear_receive)

        for widget in (self.hex_display_cb, self.timestamp_cb, self.pause_cb, self.log_cb):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.rx_label)
        row.addWidget(self.tx_label)
        row.addWidget(clear_btn)
        layout.addLayout(row)

        self.rx_text = QPlainTextEdit()
        self.rx_text.setObjectName("log")
        self.rx_text.setReadOnly(True)
        self.rx_text.document().setMaximumBlockCount(20000)
        layout.addWidget(self.rx_text, 1)
        return panel

    def _build_send_panel(self):
        panel, layout = self._panel("单次发送")
        self.tx_text = QPlainTextEdit()
        self.tx_text.setMaximumHeight(64)
        self.tx_text.setPlaceholderText("输入待发送内容：文本模式支持 \\n \\r \\t \\xhh 转义，Ctrl+Enter 直接发送")
        layout.addWidget(self.tx_text)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["文本", "HEX"])
        self.append_newline_cb = QCheckBox("追加 \\r\\n")
        self.escape_cb = QCheckBox("使用转义符")
        self.escape_cb.setChecked(True)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(list(CHECKSUM_LABELS.keys()))
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("ghost")

        mode_tag = QLabel("模式")
        mode_tag.setObjectName("hint")
        sum_tag = QLabel("校验")
        sum_tag.setObjectName("hint")
        row.addWidget(mode_tag)
        row.addWidget(self.mode_combo)
        row.addWidget(self.append_newline_cb)
        row.addWidget(self.escape_cb)
        row.addWidget(sum_tag)
        row.addWidget(self.checksum_combo)
        row.addStretch(1)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.tx_text)
        shortcut.activated.connect(self._send_once)
        shortcut2 = QShortcut(QKeySequence("Ctrl+Enter"), self.tx_text)
        shortcut2.activated.connect(self._send_once)
        return panel

    def _build_loop_panel(self):
        panel, layout = self._panel("多条循环发送")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.seq_radio = QRadioButton("顺序轮询")
        self.seq_radio.setChecked(True)
        self.seq_radio.setToolTip("按列表顺序逐条发送，每条发完等待它自己的间隔，到尾后回绕")
        self.per_radio = QRadioButton("单条周期")
        self.per_radio.setToolTip("每条启用项按自己的周期独立触发")

        self.add_btn = QPushButton("添加")
        self.del_btn = QPushButton("删除")
        self.up_btn = QPushButton("上移")
        self.down_btn = QPushButton("下移")
        self.clear_btn = QPushButton("清空")
        for button in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            button.setObjectName("ghost")

        self.save_btn = QPushButton("保存方案")
        self.load_btn = QPushButton("加载方案")
        self.save_btn.setObjectName("ghost")
        self.load_btn.setObjectName("ghost")

        self.loop_btn = QPushButton("开始循环")
        self.loop_btn.setObjectName("primary")

        row.addWidget(self.seq_radio)
        row.addWidget(self.per_radio)
        row.addSpacing(10)
        for button in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self.save_btn)
        row.addWidget(self.load_btn)
        row.addWidget(self.loop_btn)
        layout.addLayout(row)

        self.send_table = SendTableWidget()
        table = self.send_table.table
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.send_table, 1)
        return panel

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

    def _toggle_theme(self):
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        self._apply_theme()
        self._settings.setValue("theme", self._theme_name)

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
            "bytesize": int(self.databits_combo.currentText().split()[0]),
            "stopbits": float(self.stopbits_combo.currentText().split()[0]),
            "parity": PARITY_MAP[self.parity_combo.currentText()],
            "flow": FLOW_MAP[self.flow_combo.currentText()],
            "auto_reconnect": self.reconnect_cb.isChecked(),
        }
        self._controller.open_requested.emit(config)

    def _set_conn_state(self, connected: bool, text: str):
        self._port_open = connected
        self.dot.setObjectName("dotOn" if connected else "dotOff")
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)
        self.conn_label.setText(text)
        self.open_btn.setText("关闭串口" if connected else "打开串口")

    def _on_port_opened(self, port_name: str):
        baud = self.baud_combo.currentText().strip()
        self._set_conn_state(True, f"{port_name} @ {baud}")
        self._save_settings()

    def _on_port_closed(self):
        self._set_conn_state(False, "未连接")
        self._set_loop_ui(False)

    def _on_port_lost(self, message: str):
        self._set_conn_state(False, "已断开")
        self._set_loop_ui(False)
        self._append_line("sys", f"{message}。可勾选「断线自动重连」。")
        self.statusBar().showMessage(message)

    def _on_status(self, message: str):
        self.statusBar().showMessage(message)
        if "打开" in message and "已打开" in message:
            self._append_line("sys", message)
        elif "重连成功" in message:
            self._append_line("sys", message)
        elif "已关闭" in message:
            self._append_line("sys", message)

    def _on_error(self, message: str):
        self.statusBar().showMessage(message)
        self._append_line("sys", message)
        if "打开串口失败" in message:
            QMessageBox.warning(self, "串口错误", message)

    # ---------- 接收 ----------
    def _clear_receive(self):
        self.rx_text.clear()

    def _append_line(self, kind: str, text: str):
        colors = {
            "rx": self._theme["rx"],
            "tx": self._theme["tx"],
            "sys": self._theme["sys"],
        }
        color = colors.get(kind, self._theme["sys"])
        label = KIND_LABELS.get(kind, "SYS")
        stamp = ""
        if self.timestamp_cb.isChecked():
            stamp = f'<span style="color:{self._theme["sys"]}">[{time.strftime("%H:%M:%S")}] </span>'
        body = html.escape(text)
        self.rx_text.appendHtml(
            f'{stamp}<span style="color:{color};font-weight:600">{label}</span> '
            f'<span style="color:{color}">{body}</span>'
        )

    def _on_data_received(self, payload):
        data = bytes(payload)
        self._rx_count += len(data)
        self.rx_label.setText(f"RX {self._rx_count} B")
        if self.hex_display_cb.isChecked():
            text = bytes_to_hex(data)
        else:
            text = data.decode("utf-8", errors="replace")
        scrollbar = self.rx_text.verticalScrollBar()
        previous = scrollbar.value()
        self._append_line("rx", text)
        if self.pause_cb.isChecked():
            scrollbar.setValue(previous)
        if self.log_cb.isChecked():
            self._write_log("RX", bytes_to_hex(data))

    def _on_bytes_sent(self, count: int):
        self._tx_count += int(count)
        self.tx_label.setText(f"TX {self._tx_count} B")

    def _write_log(self, tag: str, text: str):
        day = time.strftime("%Y-%m-%d")
        try:
            if self._log_path is None or self._log_day != day:
                Path(LOG_DIR).mkdir(exist_ok=True)
                self._log_path = Path(LOG_DIR) / f"serial_{day}.log"
                self._log_day = day
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{time.strftime('%H:%M:%S')}] {tag} {text}\n")
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
        self._append_line("tx", bytes_to_hex(payload))

    # ---------- 循环发送 ----------
    def _toggle_loop(self):
        if self._loop_active:
            self._controller.loop_stop_requested.emit()
            self._set_loop_ui(False)
            self.statusBar().showMessage("循环发送已停止")
            self._append_line("sys", "循环发送已停止")
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
        self._append_line("sys", f"循环发送已启动：{len(payloads)} 条，{mode_label}")

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
        self._apply_theme()

    def _save_settings(self):
        self._settings.setValue("port", self.port_combo.currentText())
        self._settings.setValue("baudrate", self.baud_combo.currentText())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("theme", self._theme_name)

    def closeEvent(self, event):
        try:
            self._controller.loop_stop_requested.emit()
            self._controller.close_requested.emit()
            self._controller.shutdown()
        finally:
            self._save_settings()
            event.accept()
