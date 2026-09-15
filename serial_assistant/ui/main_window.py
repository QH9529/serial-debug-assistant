"""主窗口：串口参数、接收日志、快捷发送、单次发送与多条循环发送。"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
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
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.checksum import append_checksum
from ..core.codec import bytes_to_hex, encode_payload, format_display, line_ending
from ..core.profile import ProfileError, load_profile, save_profile
from ..core.quicksend import (
    QuickSlot,
    dump_history,
    dump_slots,
    history_from_raw,
    load_slots,
    push_history,
)
from ..core.scheduler import MODE_PER_ITEM, MODE_SEQUENTIAL
from ..serial_worker import SerialWorkerController, list_available_ports
from . import theme as theme_mod
from .quick_panel import QuickSendPanel, QuickSlotDialog
from .send_table import CHECKSUM_LABELS, SendTableWidget

BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]

PARITY_MAP = {"无校验": "N", "偶校验": "E", "奇校验": "O"}
FLOW_MAP = {"无流控": None, "RTS/CTS": "rtscts", "XON/XOFF": "xonxoff"}

DISPLAY_LABELS = [("文本", "text"), ("HEX", "hex"), ("对照", "both")]
ENCODING_LABELS = [
    ("UTF-8", "utf-8"),
    ("GBK", "gbk"),
    ("UTF-16", "utf-16"),
    ("ASCII", "ascii"),
    ("Latin-1", "latin-1"),
]
LINE_ENDING_LABELS = [
    ("无", "none"),
    ("CR", "cr"),
    ("LF", "lf"),
    ("CRLF", "crlf"),
]
LINE_ENDING_TOOLTIPS = {
    "none": "不追加换行",
    "cr": "追加 CR（\\r）",
    "lf": "追加 LF（\\n）",
    "crlf": "追加 CRLF（\\r\\n）",
}

_HOTKEY_RE = re.compile(
    r"^(?:(?:ctrl|alt|shift|meta)\+)*(?:f(?:[1-9]|1\d|2[0-4])|[a-z0-9]"
    r"|space|tab|enter|return|insert|delete|home|end|pageup|pagedown"
    r"|up|down|left|right)$",
    re.IGNORECASE,
)


def hotkey_sequence(text: str):
    """把用户填的快捷键文本转成 QKeySequence；非法或空返回 None。"""
    text = (text or "").strip()
    if not text or not _HOTKEY_RE.match(text):
        return None
    sequence = QKeySequence(text)
    return None if sequence.isEmpty() else sequence

LOG_DIR = "logs"
KIND_LABELS = {"rx": "RX", "tx": "TX", "sys": "SYS"}
FILE_CHUNK = 1024
FILE_INTERVAL_MS = 10


class MainWindow(QMainWindow):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("串口调试助手")
        self.resize(1240, 800)

        self._settings = settings or QSettings("QH9529", "SerialDebugAssistant")
        self._theme_name = str(self._settings.value("theme", "dark") or "dark")
        self._theme = theme_mod.current_theme(self._theme_name)

        self._port_open = False
        self._loop_active = False
        self._rx_count = 0
        self._tx_count = 0
        self._log_path = None
        self._log_day = ""
        self._rx_pending = bytearray()
        self._history = history_from_raw(self._settings.value("history"))
        self._quick_shortcuts = []
        self._file_state = None

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
        right.addWidget(self._build_quick_panel())
        right.addWidget(self._build_send_panel())
        right.addWidget(self._build_loop_panel())
        right.setStretchFactor(0, 0)
        right.setStretchFactor(1, 0)
        right.setStretchFactor(2, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 560])
        layout.addWidget(splitter, 1)

        status = self.statusBar()
        status.addPermanentWidget(self.rx_label)
        status.addPermanentWidget(self.tx_label)
        status.showMessage("就绪")

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

        self.databits_combo = QComboBox()
        self.databits_combo.addItems(["8 位", "7 位"])
        self.databits_combo.setToolTip("数据位")
        self.databits_combo.setFixedWidth(78)
        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1 位", "2 位"])
        self.stopbits_combo.setToolTip("停止位")
        self.stopbits_combo.setFixedWidth(78)
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(list(PARITY_MAP.keys()))
        self.parity_combo.setToolTip("校验位")
        self.parity_combo.setFixedWidth(88)
        self.flow_combo = QComboBox()
        self.flow_combo.addItems(list(FLOW_MAP.keys()))
        self.flow_combo.setToolTip("流控")
        self.flow_combo.setFixedWidth(138)

        self.reconnect_cb = QCheckBox("自动重连")
        self.reconnect_cb.setToolTip("串口断开后自动尝试重连")
        self.rts_cb = QCheckBox("RTS")
        self.rts_cb.setChecked(True)
        self.rts_cb.setToolTip("手动控制 RTS 电平，可用于复位 MCU / 切换模块模式")
        self.dtr_cb = QCheckBox("DTR")
        self.dtr_cb.setChecked(True)
        self.dtr_cb.setToolTip("手动控制 DTR 电平")

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
        row.addWidget(self.rts_cb)
        row.addWidget(self.dtr_cb)
        row.addStretch(1)
        row.addWidget(self.dot)
        row.addWidget(self.conn_label)
        row.addWidget(self.open_btn)
        self.top_cb = QCheckBox("置顶")
        self.top_cb.setToolTip("窗口保持在其他窗口之上")
        row.addWidget(self.top_cb)
        row.addWidget(self.theme_btn)
        layout.addLayout(row)
        return panel

    def _build_log_panel(self):
        panel, layout = self._panel("接收日志")

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        display_tag = QLabel("显示")
        display_tag.setObjectName("hint")
        self.display_combo = QComboBox()
        for label, value in DISPLAY_LABELS:
            self.display_combo.addItem(label, value)
        self.display_combo.setFixedWidth(80)
        self.display_combo.setToolTip("文本 / HEX / 对照（十六进制与文本同屏）")

        self.timestamp_cb = QCheckBox("时间戳")
        self.timestamp_cb.setChecked(True)
        self.pause_cb = QCheckBox("暂停滚动")
        self.log_cb = QCheckBox("保存日志")
        self.log_cb.setToolTip("接收数据自动写入 logs/ 目录")

        for widget in (display_tag, self.display_combo, self.timestamp_cb, self.pause_cb, self.log_cb):
            row1.addWidget(widget)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        encoding_tag = QLabel("编码")
        encoding_tag.setObjectName("hint")
        self.encoding_combo = QComboBox()
        for label, value in ENCODING_LABELS:
            self.encoding_combo.addItem(label, value)
        self.encoding_combo.setToolTip("接收数据的文本解码方式")

        self.auto_wrap_cb = QCheckBox("自动换行")
        self.auto_wrap_cb.setToolTip("接收空闲一段时间后自动断行，便于阅读没有换行符的日志")
        self.wrap_spin = QSpinBox()
        self.wrap_spin.setRange(20, 5000)
        self.wrap_spin.setSingleStep(20)
        self.wrap_spin.setValue(200)
        self.wrap_spin.setToolTip("空闲多少毫秒后自动断行")

        self.rx_label = QLabel("RX 0 B")
        self.rx_label.setObjectName("pill")
        self.tx_label = QLabel("TX 0 B")
        self.tx_label.setObjectName("pill")
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self._clear_receive)

        row2.addWidget(encoding_tag)
        row2.addWidget(self.encoding_combo)
        row2.addSpacing(6)
        row2.addWidget(self.auto_wrap_cb)
        row2.addWidget(self.wrap_spin)
        row2.addStretch(1)
        self.save_log_btn = QPushButton("保存数据")
        self.save_log_btn.setObjectName("ghost")
        self.save_log_btn.setToolTip("把接收区当前内容另存为文本文件")
        row2.addWidget(self.save_log_btn)
        row2.addWidget(clear_btn)
        layout.addLayout(row2)

        self.rx_text = QPlainTextEdit()
        self.rx_text.setObjectName("log")
        self.rx_text.setReadOnly(True)
        self.rx_text.document().setMaximumBlockCount(20000)
        layout.addWidget(self.rx_text, 1)

        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.timeout.connect(self._flush_pending)
        return panel

    def _build_quick_panel(self):
        panel, layout = self._panel("快捷发送")
        self.quick_panel = QuickSendPanel()
        layout.addWidget(self.quick_panel)
        return panel

    def _build_send_panel(self):
        panel, layout = self._panel("单次发送")
        self.tx_text = QPlainTextEdit()
        self.tx_text.setMaximumHeight(56)
        self.tx_text.setPlaceholderText("输入待发送内容：文本模式支持 \\n \\r \\t \\xhh 转义，Ctrl+Enter 直接发送")
        layout.addWidget(self.tx_text)

        row = QHBoxLayout()
        row.setSpacing(8)
        history_tag = QLabel("历史")
        history_tag.setObjectName("hint")
        self.history_combo = QComboBox()
        self.history_combo.setFixedWidth(118)
        self.history_combo.setToolTip("最近发送记录，选中即可重新填入")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["文本", "HEX"])
        self.mode_combo.setFixedWidth(74)
        self.line_ending_combo = QComboBox()
        for label, value in LINE_ENDING_LABELS:
            self.line_ending_combo.addItem(label, value)
            self.line_ending_combo.setItemData(
                self.line_ending_combo.count() - 1,
                LINE_ENDING_TOOLTIPS.get(value, ""),
                Qt.ToolTipRole,
            )
        self.line_ending_combo.setToolTip("发送时在末尾追加的换行符")
        self.escape_cb = QCheckBox("转义")
        self.escape_cb.setChecked(True)
        self.escape_cb.setToolTip("解析 \\n \\r \\t \\0 \\xhh")
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(list(CHECKSUM_LABELS.keys()))
        self.checksum_combo.setToolTip("发送前追加校验")
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("ghost")
        self.send_file_btn = QPushButton("文件")
        self.send_file_btn.setObjectName("ghost")
        self.send_file_btn.setToolTip("发送文件：按 %d 字节 / %d ms 分块下发（进度见状态栏）" % (FILE_CHUNK, FILE_INTERVAL_MS))

        row.addWidget(history_tag)
        row.addWidget(self.history_combo)
        row.addWidget(self.mode_combo)
        row.addWidget(self.line_ending_combo)
        row.addWidget(self.escape_cb)
        row.addWidget(self.checksum_combo)
        row.addStretch(1)
        self.clear_send_btn = QPushButton("清空")
        self.clear_send_btn.setObjectName("ghost")
        self.clear_send_btn.setToolTip("清空发送框")
        row.addWidget(self.clear_send_btn)
        row.addWidget(self.send_btn)
        row.addWidget(self.send_file_btn)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.auto_send_cb = QCheckBox("定时发送")
        self.auto_send_cb.setToolTip("按右侧周期反复发送发送框内容")
        self.auto_send_spin = QSpinBox()
        self.auto_send_spin.setRange(10, 600000)
        self.auto_send_spin.setSingleStep(50)
        self.auto_send_spin.setValue(1000)
        self.auto_send_spin.setToolTip("定时发送周期，单位毫秒")
        self.send_stats_label = QLabel("0 字节")
        self.send_stats_label.setObjectName("pill")
        self.send_stats_label.setToolTip("本期发送将实际发出的字节数（含换行与校验）")
        row2.addWidget(self.auto_send_cb)
        row2.addWidget(self.auto_send_spin)
        row2.addStretch(1)
        row2.addWidget(self.send_stats_label)
        layout.addLayout(row2)

        for key in ("Ctrl+Return", "Ctrl+Enter"):
            shortcut = QShortcut(QKeySequence(key), self.tx_text)
            shortcut.activated.connect(self._send_once)

        self._file_timer = QTimer(self)
        self._file_timer.setInterval(FILE_INTERVAL_MS)
        self._file_timer.timeout.connect(self._send_file_tick)
        self._auto_send_timer = QTimer(self)
        self._auto_send_timer.setSingleShot(False)
        self._auto_send_timer.timeout.connect(self._auto_send_tick)
        return panel

    def _build_loop_panel(self):
        panel, layout = self._panel("多条循环发送")

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.mode_combo_loop = QComboBox()
        self.mode_combo_loop.addItem("顺序轮询", MODE_SEQUENTIAL)
        self.mode_combo_loop.addItem("单条周期", MODE_PER_ITEM)
        self.mode_combo_loop.setFixedWidth(104)
        self.mode_combo_loop.setToolTip(
            "调度模式\n"
            "顺序轮询：按列表顺序逐条发送，每条发完等待它自己的间隔，到尾后回绕\n"
            "单条周期：每条启用项按自己的周期独立触发"
        )

        self.add_btn = QPushButton("添加")
        self.del_btn = QPushButton("删除")
        self.up_btn = QPushButton("上移")
        self.down_btn = QPushButton("下移")
        self.clear_btn = QPushButton("清空")
        for button in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            button.setObjectName("ghost")

        self.save_btn = QPushButton("保存")
        self.save_btn.setToolTip("把当前条目与调度模式保存为 JSON 方案")
        self.load_btn = QPushButton("加载")
        self.load_btn.setToolTip("从 JSON 方案文件恢复条目与调度模式")
        self.save_btn.setObjectName("ghost")
        self.load_btn.setObjectName("ghost")

        self.loop_btn = QPushButton("开始循环")
        self.loop_btn.setObjectName("primary")

        row1.addWidget(self.mode_combo_loop)
        row1.addSpacing(6)
        self.uniform_cb = QCheckBox("统一周期")
        self.uniform_cb.setToolTip("勾选后所有条目都用右侧这一个周期发送（SSCOM 式多字符串循环）")
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setSingleStep(50)
        self.period_spin.setValue(1000)
        self.period_spin.setToolTip("统一周期，单位毫秒")
        self.checksum_hint = QLabel("校验共用")
        self.checksum_hint.setObjectName("hint")
        self.checksum_hint.setToolTip("循环发送与单次发送、快捷发送共用同一个校验设置（在「单次发送」面板选择）")
        row1.addWidget(self.uniform_cb)
        row1.addWidget(self.period_spin)
        row1.addSpacing(6)
        for button in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            row1.addWidget(button)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.send_once_btn = QPushButton("发送一次")
        self.send_once_btn.setObjectName("ghost")
        self.send_once_btn.setToolTip("把勾选的条目按列表顺序各发一遍，不启动循环")
        row2.addWidget(self.send_once_btn)
        row2.addWidget(self.checksum_hint)
        row2.addStretch(1)
        row2.addWidget(self.save_btn)
        row2.addWidget(self.load_btn)
        row2.addWidget(self.loop_btn)
        layout.addLayout(row2)

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
        self.send_file_btn.clicked.connect(self._toggle_send_file)
        self.clear_send_btn.clicked.connect(self._clear_send)
        self.save_log_btn.clicked.connect(self._save_receive_log)
        self.top_cb.toggled.connect(self._toggle_always_on_top)
        self.auto_send_cb.toggled.connect(self._on_auto_send_toggled)
        self.auto_send_spin.valueChanged.connect(self._on_auto_send_period_changed)
        self.tx_text.textChanged.connect(self._update_send_stats)
        self.mode_combo.currentIndexChanged.connect(self._update_send_stats)
        self.line_ending_combo.currentIndexChanged.connect(self._update_send_stats)
        self.checksum_combo.currentIndexChanged.connect(self._update_send_stats)
        self.checksum_combo.currentIndexChanged.connect(self._update_checksum_hint)
        self.escape_cb.toggled.connect(self._update_send_stats)
        self.history_combo.activated.connect(self._on_history_selected)
        self.rts_cb.toggled.connect(self._on_control_toggled)
        self.dtr_cb.toggled.connect(self._on_control_toggled)
        self.display_combo.currentIndexChanged.connect(self._on_display_changed)

        self.add_btn.clicked.connect(lambda: self.send_table.add_row())
        self.del_btn.clicked.connect(self.send_table.remove_selected)
        self.up_btn.clicked.connect(lambda: self.send_table.move_current(-1))
        self.down_btn.clicked.connect(lambda: self.send_table.move_current(1))
        self.clear_btn.clicked.connect(self.send_table.clear_rows)
        self.save_btn.clicked.connect(self._save_scheme)
        self.load_btn.clicked.connect(self._load_scheme)
        self.loop_btn.clicked.connect(self._toggle_loop)
        self.send_once_btn.clicked.connect(self._send_checked_once)

        self.quick_panel.send_requested.connect(self._on_quick_send)
        self.quick_panel.add_requested.connect(self._on_quick_add)
        self.quick_panel.slots_changed.connect(self._on_quick_slots_changed)

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

    # ---------- 快捷发送 ----------
    def _on_quick_add(self):
        prefill = QuickSlot(
            content=self.tx_text.toPlainText().strip(),
            is_hex=self.mode_combo.currentText() == "HEX",
            checksum=CHECKSUM_LABELS.get(self.checksum_combo.currentText(), "none"),
        )
        dialog = QuickSlotDialog(prefill, self)
        if not dialog.exec():
            return
        slot = dialog.result_slot()
        if not slot.content.strip():
            self._warn("快捷发送内容不能为空")
            return
        if not self.quick_panel.add_slot(slot):
            self._warn("快捷发送条目已达上限")
            return
        self.statusBar().showMessage(f"已添加快捷发送：{slot.display_label()}")

    def _on_quick_send(self, slot):
        try:
            payload = self._build_payload(
                slot.content,
                slot.is_hex,
                True,
                CHECKSUM_LABELS.get(self.checksum_combo.currentText(), "none"),
                str(self.line_ending_combo.currentData()),
            )
        except ValueError as exc:
            self._warn(f"快捷发送编码错误：{exc}")
            return
        self._transmit(payload)

    def _on_quick_slots_changed(self):
        self._refresh_quick_shortcuts()
        self._save_settings()

    def _refresh_quick_shortcuts(self):
        for shortcut in self._quick_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._quick_shortcuts = []
        for slot in self.quick_panel.get_slots():
            sequence = hotkey_sequence(slot.hotkey)
            if sequence is None:
                continue
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(lambda s=slot: self._on_quick_send(s))
            self._quick_shortcuts.append(shortcut)

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
            "rts": self.rts_cb.isChecked(),
            "dtr": self.dtr_cb.isChecked(),
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
        self._flush_pending()
        if self.auto_send_cb.isChecked():
            self.auto_send_cb.setChecked(False)
        self._set_conn_state(False, "未连接")
        self._set_loop_ui(False)

    def _on_port_lost(self, message: str):
        self._flush_pending()
        if self.auto_send_cb.isChecked():
            self.auto_send_cb.setChecked(False)
        self._set_conn_state(False, "已断开")
        self._set_loop_ui(False)
        self._append_line("sys", f"{message}。可勾选「断线自动重连」。")
        self.statusBar().showMessage(message)

    def _on_status(self, message: str):
        self.statusBar().showMessage(message)
        if "已打开" in message or "重连成功" in message or "已关闭" in message or "控制线" in message:
            self._append_line("sys", message)

    def _on_error(self, message: str):
        self.statusBar().showMessage(message)
        self._append_line("sys", message)
        if "打开串口失败" in message:
            QMessageBox.warning(self, "串口错误", message)

    def _on_control_toggled(self, *_):
        if not self._port_open:
            return
        self._controller.control_requested.emit(
            {"rts": self.rts_cb.isChecked(), "dtr": self.dtr_cb.isChecked()}
        )

    # ---------- 接收 ----------
    def _clear_receive(self):
        self._rx_pending.clear()
        self.rx_text.clear()

    def _on_display_changed(self, *_):
        self._flush_pending()

    def _append_line(self, kind: str, text: str):
        color = self._theme.get(kind if kind in ("rx", "tx") else "sys", self._theme["sys"])
        label = KIND_LABELS.get(kind, "SYS")
        stamp = ""
        if self.timestamp_cb.isChecked():
            stamp = f'<span style="color:{self._theme["sys"]}">[{self._timestamp()}] </span>'
        body = html.escape(text)
        self.rx_text.appendHtml(
            f'{stamp}<span style="color:{color};font-weight:600">{label}</span> '
            f'<span style="color:{color}">{body}</span>'
        )

    def _render_line(self, kind: str, data: bytes):
        mode = self.display_combo.currentData() or "text"
        encoding = self.encoding_combo.currentData() or "utf-8"
        scrollbar = self.rx_text.verticalScrollBar()
        previous = scrollbar.value()
        self._append_line(kind, format_display(data, mode, encoding))
        if self.pause_cb.isChecked():
            scrollbar.setValue(previous)

    def _on_data_received(self, payload):
        data = bytes(payload)
        self._rx_count += len(data)
        self.rx_label.setText(f"RX {self._rx_count} B")
        if self.log_cb.isChecked():
            self._write_log("RX", bytes_to_hex(data))
        if self.auto_wrap_cb.isChecked():
            self._rx_pending += data
            self._wrap_timer.start(self.wrap_spin.value())
            return
        self._render_line("rx", data)

    def _flush_pending(self):
        if not self._rx_pending:
            return
        data = bytes(self._rx_pending)
        self._rx_pending.clear()
        self._render_line("rx", data)

    def _on_bytes_sent(self, count: int):
        self._tx_count += int(count)
        self.tx_label.setText(f"TX {self._tx_count} B")

    @staticmethod
    def _timestamp() -> str:
        """毫秒精度时间戳（HH:MM:SS.mmm）。"""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _write_log(self, tag: str, text: str):
        day = time.strftime("%Y-%m-%d")
        try:
            if self._log_path is None or self._log_day != day:
                Path(LOG_DIR).mkdir(exist_ok=True)
                self._log_path = Path(LOG_DIR) / f"serial_{day}.log"
                self._log_day = day
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{self._timestamp()}] {tag} {text}\n")
        except OSError as exc:
            self.statusBar().showMessage(f"日志写入失败：{exc}")

    # ---------- 发送 ----------
    def _build_payload(self, text, is_hex, use_escapes, checksum, ending) -> bytes:
        payload = encode_payload(text, is_hex, use_escapes)
        payload += line_ending(ending)
        return append_checksum(payload, checksum)

    def _transmit(self, payload: bytes, echo: bool = True) -> bool:
        if not self._port_open:
            self._warn("请先打开串口")
            return False
        if not payload:
            return False
        self._controller.send_requested.emit(payload)
        if echo:
            self._append_line("tx", bytes_to_hex(payload))
        return True

    def _send_once(self, *_args, remember: bool = True):
        text = self.tx_text.toPlainText()
        if not text.strip():
            return
        is_hex = self.mode_combo.currentText() == "HEX"
        try:
            payload = self._build_payload(
                text,
                is_hex,
                self.escape_cb.isChecked(),
                CHECKSUM_LABELS[self.checksum_combo.currentText()],
                str(self.line_ending_combo.currentData()),
            )
        except ValueError as exc:
            self._warn(f"编码错误：{exc}")
            return
        if self._transmit(payload) and remember:
            self._push_history(text, is_hex)

    def _push_history(self, text: str, is_hex: bool):
        self._history = push_history(self._history, text, is_hex)
        self._refresh_history_combo()

    def _refresh_history_combo(self):
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        self.history_combo.addItem("（最近发送）", None)
        for entry in self._history:
            text = entry["text"].replace("\n", " ").replace("\r", " ")
            label = f"[HEX] {text}" if entry["is_hex"] else text
            self.history_combo.addItem(label[:40], entry)
        self.history_combo.setCurrentIndex(0)
        self.history_combo.blockSignals(False)

    def _on_history_selected(self, index: int):
        data = self.history_combo.itemData(index)
        if not data:
            return
        self.tx_text.setPlainText(data["text"])
        self.mode_combo.setCurrentText("HEX" if data["is_hex"] else "文本")
        self.history_combo.setCurrentIndex(0)

    def _toggle_send_file(self):
        if self._file_state is not None:
            self._file_stop("已取消发送文件")
            return
        if not self._port_open:
            self._warn("请先打开串口")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择要发送的文件", "", "所有文件 (*.*)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            self._warn(f"读取文件失败：{exc}")
            return
        if not data:
            self._warn("文件内容为空")
            return
        self._file_state = {"data": data, "offset": 0, "name": Path(path).name}
        self.send_file_btn.setText("取消发送")
        self._append_line("sys", f"开始发送文件：{Path(path).name}（{len(data)} 字节，分块 {FILE_CHUNK} 字节）")
        self._file_timer.start()

    def _send_file_tick(self):
        state = self._file_state
        if state is None:
            self._file_timer.stop()
            return
        if not self._port_open:
            self._file_stop("串口已关闭，文件发送中止")
            return
        chunk = state["data"][state["offset"]: state["offset"] + FILE_CHUNK]
        if not chunk:
            self._file_stop(f"文件发送完成：{state['name']}（{len(state['data'])} 字节）")
            return
        self._controller.send_requested.emit(bytes(chunk))
        state["offset"] += len(chunk)
        self.statusBar().showMessage(f"发送文件 {state['offset']}/{len(state['data'])} 字节")

    def _file_stop(self, message: str):
        self._file_timer.stop()
        self._file_state = None
        self.send_file_btn.setText("文件")
        self.statusBar().showMessage(message)
        self._append_line("sys", message)

    # ---------- 循环发送 ----------
    def _collect_loop_payloads(self):
        """收集勾选且非空的条目；校验与单次发送共用同一设置，统一周期时用全局周期。"""
        uniform = self.uniform_cb.isChecked()
        period = self.period_spin.value()
        checksum = CHECKSUM_LABELS.get(self.checksum_combo.currentText(), "none")
        items = self.send_table.get_items()
        payloads = []
        for row, item in enumerate(items):
            if not item.enabled or not item.content.strip():
                continue
            try:
                raw = encode_payload(item.content, item.is_hex, True)
            except ValueError as exc:
                raise ValueError(f"第 {row + 1} 条编码错误：{exc}") from exc
            payloads.append(
                {
                    "index": row,
                    "payload": append_checksum(raw, checksum),
                    "interval_ms": period if uniform else item.interval_ms,
                }
            )
        return payloads

    def _send_checked_once(self):
        if not self._port_open:
            self._warn("请先打开串口")
            return
        try:
            payloads = self._collect_loop_payloads()
        except ValueError as exc:
            self._warn(str(exc))
            return
        if not payloads:
            self._warn("没有启用的发送条目")
            return
        for entry in payloads:
            self._controller.send_requested.emit(entry["payload"])
            self._append_line("tx", bytes_to_hex(entry["payload"]))
        self.statusBar().showMessage(f"已按顺序发送 {len(payloads)} 条勾选指令")

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
        try:
            payloads = self._collect_loop_payloads()
        except ValueError as exc:
            self._warn(str(exc))
            return
        if not payloads:
            self._warn("没有启用的发送条目")
            return
        mode = self.mode_combo_loop.currentData() or MODE_SEQUENTIAL
        if self.uniform_cb.isChecked() and mode == MODE_SEQUENTIAL:
            self._controller.loop_requested.emit({"mode": MODE_SEQUENTIAL, "payloads": payloads})
            label = f"统一周期 {self.period_spin.value()} ms"
        else:
            self._controller.loop_requested.emit({"mode": mode, "payloads": payloads})
            label = "顺序轮询" if mode == MODE_SEQUENTIAL else "单条周期"
        self._set_loop_ui(True)
        self.statusBar().showMessage(f"循环发送已启动：{len(payloads)} 条，{label}")
        self._append_line("sys", f"循环发送已启动：{len(payloads)} 条，{label}")

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
        mode = str(self.mode_combo_loop.currentData() or MODE_SEQUENTIAL)
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
        index = self.mode_combo_loop.findData(mode)
        if index >= 0:
            self.mode_combo_loop.setCurrentIndex(index)
        self.statusBar().showMessage(f"方案已加载：{path}")

    # ---------- 定时发送与发送辅助 ----------
    def _clear_send(self):
        self.tx_text.clear()
        self.history_combo.setCurrentIndex(0)

    def _update_send_stats(self, *_):
        try:
            payload = self._build_payload(
                self.tx_text.toPlainText(),
                self.mode_combo.currentText() == "HEX",
                self.escape_cb.isChecked(),
                CHECKSUM_LABELS[self.checksum_combo.currentText()],
                str(self.line_ending_combo.currentData()),
            )
        except ValueError:
            self.send_stats_label.setText("编码错误")
            return
        self.send_stats_label.setText(f"{len(payload)} 字节")

    def _update_checksum_hint(self, *_):
        self.checksum_hint.setText(f"校验 {self.checksum_combo.currentText()}")

    def _on_auto_send_period_changed(self, value: int):
        if self._auto_send_timer.isActive():
            self._auto_send_timer.start(int(value))

    def _on_auto_send_toggled(self, checked: bool):
        if checked:
            if not self._port_open:
                self.auto_send_cb.setChecked(False)
                self.statusBar().showMessage("定时发送需要先打开串口")
                return
            self._auto_send_timer.start(self.auto_send_spin.value())
            self.statusBar().showMessage(f"定时发送已开启：每 {self.auto_send_spin.value()} ms")
            self._append_line("sys", f"定时发送已开启：每 {self.auto_send_spin.value()} ms")
            return
        self._auto_send_timer.stop()
        self.statusBar().showMessage("定时发送已停止")
        self._append_line("sys", "定时发送已停止")

    def _auto_send_tick(self):
        if not self._port_open:
            self.auto_send_cb.setChecked(False)
            return
        self._send_once(remember=False)

    def _save_receive_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存接收数据", "serial_log.txt", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.rx_text.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self._warn(f"保存失败：{exc}")
            return
        self.statusBar().showMessage(f"接收数据已保存：{path}")

    def _toggle_always_on_top(self, checked: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
        self.show()

    # ---------- 其它 ----------
    def _warn(self, message: str):
        QMessageBox.warning(self, "提示", message)

    def _combo_set(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

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

        self._combo_set(self.display_combo, str(settings.value("display", "text")))
        self._combo_set(self.encoding_combo, str(settings.value("encoding", "utf-8")))
        self._combo_set(self.line_ending_combo, str(settings.value("line_ending", "none")))
        self.auto_wrap_cb.setChecked(settings.value("auto_wrap", "false") in (True, "true"))
        self.wrap_spin.setValue(int(settings.value("wrap_ms", 200) or 200))
        self.rts_cb.setChecked(settings.value("rts", "true") in (True, "true"))
        self.dtr_cb.setChecked(settings.value("dtr", "true") in (True, "true"))
        self.uniform_cb.setChecked(settings.value("uniform", "false") in (True, "true"))
        self.period_spin.setValue(int(settings.value("period_ms", 1000) or 1000))
        self.auto_send_spin.setValue(int(settings.value("auto_send_ms", 1000) or 1000))
        on_top = settings.value("on_top", "false") in (True, "true")
        self.top_cb.setChecked(on_top)
        if on_top:
            self._toggle_always_on_top(True)

        self.quick_panel.set_slots(load_slots(settings.value("quick_slots")))
        self._refresh_quick_shortcuts()
        self._refresh_history_combo()
        self._update_checksum_hint()
        self._update_send_stats()
        self._apply_theme()

    def _save_settings(self):
        settings = self._settings
        settings.setValue("port", self.port_combo.currentText())
        settings.setValue("baudrate", self.baud_combo.currentText())
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("theme", self._theme_name)
        settings.setValue("display", str(self.display_combo.currentData() or "text"))
        settings.setValue("encoding", str(self.encoding_combo.currentData() or "utf-8"))
        settings.setValue("line_ending", str(self.line_ending_combo.currentData() or "none"))
        settings.setValue("auto_wrap", self.auto_wrap_cb.isChecked())
        settings.setValue("wrap_ms", self.wrap_spin.value())
        settings.setValue("rts", self.rts_cb.isChecked())
        settings.setValue("dtr", self.dtr_cb.isChecked())
        settings.setValue("uniform", self.uniform_cb.isChecked())
        settings.setValue("period_ms", self.period_spin.value())
        settings.setValue("auto_send_ms", self.auto_send_spin.value())
        settings.setValue("on_top", self.top_cb.isChecked())
        settings.setValue("quick_slots", dump_slots(self.quick_panel.get_slots()))
        settings.setValue("history", dump_history(self._history))

    def closeEvent(self, event):
        try:
            self._file_timer.stop()
            self._auto_send_timer.stop()
            self._flush_pending()
            self._controller.loop_stop_requested.emit()
            self._controller.close_requested.emit()
            self._controller.shutdown()
        finally:
            self._save_settings()
            event.accept()
