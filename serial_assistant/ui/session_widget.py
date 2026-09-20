"""单个串口会话组件：连接参数、接收日志、快捷发送、单次发送、多条循环发送。

每个会话是独立的：独立线程、独立参数、独立计数与日志、独立的快捷指令与发送历史。
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
from .send_table import CHECKSUM_LABELS, CHECKSUM_TOOLTIPS, SendTableWidget

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
LINE_ENDING_LABELS = [("无", "none"), ("CR", "cr"), ("LF", "lf"), ("CRLF", "crlf")]
LINE_ENDING_TOOLTIPS = {
    "none": "不追加换行",
    "cr": "追加 CR（\\r）",
    "lf": "追加 LF（\\n）",
    "crlf": "追加 CRLF（\\r\\n）",
}

LOG_DIR = "logs"
MAX_LOG_BLOCKS = 20000
LOG_FLUSH_MS = 250
COUNT_REFRESH_MS = 120
STATS_DEBOUNCE_MS = 150
KIND_LABELS = {"rx": "RX", "tx": "TX", "sys": "SYS"}
FILE_CHUNK = 1024
FILE_INTERVAL_MS = 10

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


class SessionWidget(QWidget):
    """一个串口会话的完整界面与状态。"""

    title_changed = Signal()
    counts_changed = Signal(int, int)
    message = Signal(str)
    received = Signal(bytes)  # 供转发使用

    def __init__(
        self,
        session_no: int = 1,
        settings=None,
        theme: dict | None = None,
        port_in_use=None,
        resolve_targets=None,
        resolve_session=None,
        interactive: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.session_no = session_no
        self.session_id = f"s{session_no}"
        self._settings = settings
        self._theme = theme or theme_mod.current_theme("dark")
        self._port_in_use = port_in_use or (lambda port, exclude: None)
        self._resolve_targets = resolve_targets or (lambda sender: [sender])
        self._resolve_session = resolve_session or (lambda sid: None)
        self._interactive = interactive

        self._port_open = False
        self._loop_active = False
        self._rx_count = 0
        self._tx_count = 0
        self._log_path = None
        self._log_day = ""
        self._log_handle = None
        self._log_buffer = []
        self._ports_cache = None
        self._rx_pending = bytearray()
        self._history = []
        self._quick_shortcuts = []
        self._file_state = None
        self.log_dir = ""
        self.forward_target_id = ""
        self._alias = ""

        self._controller = SerialWorkerController()
        self._worker = self._controller.worker

        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self.refresh_ports()

    # ---------- 对外接口 ----------
    @property
    def is_open(self) -> bool:
        return self._port_open

    @property
    def port_name(self) -> str:
        return self.port_combo.currentText().strip()

    @property
    def rx_count(self) -> int:
        return self._rx_count

    @property
    def tx_count(self) -> int:
        return self._tx_count

    def counts_text(self) -> str:
        return f"RX {self._rx_count} B  TX {self._tx_count} B"

    @property
    def alias(self) -> str:
        """会话自定义名称（可为空）。"""
        return self._alias

    def set_alias(self, text: str):
        text = (text or "").strip()
        if text == self._alias:
            return
        self._alias = text
        self._save_settings()
        self.title_changed.emit()

    def label(self) -> str:
        port = self.port_name or "新会话"
        if self._alias:
            return f"#{self.session_no} {self._alias}（{port}）"
        return f"#{self.session_no} {port}"

    def tab_text(self) -> str:
        dot = "●" if self._port_open else "○"
        port = self.port_name or "未选口"
        if self._alias:
            name = self._alias if len(self._alias) <= 12 else self._alias[:11] + "…"
            return f"{dot} {name}（{port}）"
        return f"{dot} {port}"

    def tab_tooltip(self) -> str:
        state = "已连接" if self._port_open else "未连接"
        port = self.port_name or "未选择端口"
        prefix = f"{self._alias} · " if self._alias else ""
        return f"{prefix}{port} · {self.baud_combo.currentText()} · {state}"

    def set_theme(self, theme: dict):
        self._theme = theme

    def deliver(self, payload, echo: bool = True, origin: str | None = None) -> bool:
        """把数据写入本会话的串口（广播 / 转发 / 自身发送都走这里）。"""
        data = bytes(payload)
        if not data:
            return False
        if not self._port_open:
            return False
        if self._file_state is not None and origin is None:
            self.status("文件发送中，已跳过一条发送")
            return False
        self._controller.send_requested.emit(data)
        if echo:
            prefix = f"[转发自 {origin}] " if origin else ""
            self._append_line("tx", f"{prefix}{bytes_to_hex(data)}")
        return True

    def status(self, text: str):
        self.message.emit(f"{self.label()}：{text}")

    def shutdown(self):
        try:
            self._file_timer.stop()
            self._auto_send_timer.stop()
            self._log_flush_timer.stop()
            self._flush_pending()
            self._flush_log()
            self._controller.loop_stop_requested.emit()
            self._controller.close_requested.emit()
            self._controller.shutdown()
        finally:
            self._close_log_handle()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

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
        self._splitter = splitter
        layout.addWidget(splitter, 1)

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
        self.reconnect_cb.setChecked(True)
        self.reconnect_cb.setToolTip("串口断开后自动尝试重连（默认开启）")
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

        self.param_hint = QLabel("")
        self.param_hint.setObjectName("hint")
        self.param_hint.setToolTip("串口参数在打开端口时生效；改动后需要重新打开端口")

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
        row.addWidget(self.param_hint)
        row.addStretch(1)
        row.addWidget(self.dot)
        row.addWidget(self.conn_label)
        row.addWidget(self.open_btn)
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
        self.log_cb.setToolTip("接收数据自动写入日志文件（目录可选）")
        self.echo_cb = QCheckBox("发送回显")
        self.echo_cb.setChecked(True)
        self.echo_cb.setToolTip("把发出的数据也显示在接收日志里（单次 / 快捷 / 循环 / 广播都生效）")

        for widget in (display_tag, self.display_combo, self.timestamp_cb, self.pause_cb, self.log_cb, self.echo_cb):
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

        forward_tag = QLabel("转发到")
        forward_tag.setObjectName("hint")
        self.forward_combo = QComboBox()
        self.forward_combo.setToolTip("把本会话收到的数据自动转发到另一个会话的串口（做链路验证 / 中继）")
        self.forward_combo.setMinimumWidth(126)

        self.save_log_btn = QPushButton("保存数据")
        self.save_log_btn.setObjectName("ghost")
        self.save_log_btn.setToolTip("把接收区当前内容另存为文本文件")
        self.log_dir_btn = QPushButton("日志目录")
        self.log_dir_btn.setObjectName("ghost")
        self.log_dir_btn.setToolTip("选择自动日志的保存目录；日志为 txt 格式，按天命名")
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self._clear_receive)

        row2.addWidget(encoding_tag)
        row2.addWidget(self.encoding_combo)
        row2.addWidget(self.auto_wrap_cb)
        row2.addWidget(self.wrap_spin)
        row2.addSpacing(6)
        row2.addWidget(forward_tag)
        row2.addWidget(self.forward_combo)
        row2.addStretch(1)
        row2.addWidget(self.save_log_btn)
        row2.addWidget(self.log_dir_btn)
        row2.addWidget(clear_btn)
        layout.addLayout(row2)

        self.rx_text = QPlainTextEdit()
        self.rx_text.setObjectName("log")
        self.rx_text.setReadOnly(True)
        self.rx_text.document().setMaximumBlockCount(MAX_LOG_BLOCKS)
        layout.addWidget(self.rx_text, 1)

        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.timeout.connect(self._flush_pending)

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setInterval(LOG_FLUSH_MS)
        self._log_flush_timer.timeout.connect(self._flush_log)
        self._log_flush_timer.start()

        self._counts_timer = QTimer(self)
        self._counts_timer.setSingleShot(True)
        self._counts_timer.setInterval(COUNT_REFRESH_MS)
        self._counts_timer.timeout.connect(self._refresh_counts)

        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(STATS_DEBOUNCE_MS)
        self._stats_timer.timeout.connect(self._refresh_send_stats)
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
        self.history_combo.setFixedWidth(96)
        self.history_combo.setToolTip("本会话最近发送记录，选中即可重新填入")
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
        self.line_ending_combo.setFixedWidth(86)
        self.escape_cb = QCheckBox("转义")
        self.escape_cb.setChecked(True)
        self.escape_cb.setToolTip("解析 \\n \\r \\t \\0 \\xhh")
        self.checksum_combo = QComboBox()
        for label in CHECKSUM_LABELS:
            self.checksum_combo.addItem(label)
            self.checksum_combo.setItemData(
                self.checksum_combo.count() - 1, CHECKSUM_TOOLTIPS.get(label, ""), Qt.ToolTipRole
            )
        self.checksum_combo.setToolTip("发送前追加校验（单次 / 快捷 / 循环共用）")
        self.send_btn = QPushButton("发 送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setMinimumWidth(92)
        self.send_btn.setToolTip("发送输入框内容（Ctrl+Enter）；按「发送目标」决定是否广播")
        self.clear_send_btn = QPushButton("清空")
        self.clear_send_btn.setObjectName("ghost")
        self.clear_send_btn.setToolTip("清空发送框")
        self.send_file_btn = QPushButton("文件")
        self.send_file_btn.setObjectName("ghost")
        self.send_file_btn.setToolTip(
            "发送文件：按 %d 字节 / %d ms 分块下发（进度见状态栏）" % (FILE_CHUNK, FILE_INTERVAL_MS)
        )

        row.addWidget(history_tag)
        row.addWidget(self.history_combo)
        row.addWidget(self.mode_combo)
        row.addWidget(self.line_ending_combo)
        row.addWidget(self.escape_cb)
        row.addWidget(self.checksum_combo)
        row.addStretch(1)
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
        self.send_stats_label.setToolTip("本次发送将实际发出的字节数（含换行与校验）")
        row2.addWidget(self.auto_send_cb)
        row2.addWidget(self.auto_send_spin)
        row2.addWidget(self.clear_send_btn)
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
        self.mode_combo_loop.setFixedWidth(96)
        self.mode_combo_loop.setToolTip(
            "调度模式\n"
            "顺序轮询：按列表顺序逐条发送，每条发完等待它自己的间隔，到尾后回绕\n"
            "单条周期：每条启用项按自己的周期独立触发"
        )
        self.uniform_cb = QCheckBox("统一周期")
        self.uniform_cb.setToolTip("勾选后所有条目都用右侧这一个周期发送（SSCOM 式多字符串循环）")
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setSingleStep(50)
        self.period_spin.setValue(1000)
        self.period_spin.setToolTip("统一周期，单位毫秒")
        self.checksum_hint = QLabel("模式·校验共用")
        self.checksum_hint.setObjectName("hint")
        self.checksum_hint.setToolTip(
            "循环发送共用发送区的设置：模式与校验在「单次发送」面板选择"
        )

        self.add_btn = QPushButton("添加")
        self.up_btn = QPushButton("上移")
        self.down_btn = QPushButton("下移")
        self.clear_btn = QPushButton("清空")
        for button in (self.add_btn, self.up_btn, self.down_btn, self.clear_btn):
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
        row1.addWidget(self.uniform_cb)
        row1.addWidget(self.period_spin)
        row1.addSpacing(6)
        for button in (self.add_btn, self.up_btn, self.down_btn, self.clear_btn):
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
        self.log_dir_btn.clicked.connect(self._choose_log_dir)
        self.history_combo.activated.connect(self._on_history_selected)
        self.rts_cb.toggled.connect(self._on_control_toggled)
        self.dtr_cb.toggled.connect(self._on_control_toggled)
        self.display_combo.currentIndexChanged.connect(self._on_display_changed)
        self.forward_combo.currentIndexChanged.connect(self._on_forward_changed)

        self.add_btn.clicked.connect(lambda: self.send_table.add_row())
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

        self.auto_send_cb.toggled.connect(self._on_auto_send_toggled)
        self.auto_send_spin.valueChanged.connect(self._on_auto_send_period_changed)
        self.tx_text.textChanged.connect(self._update_send_stats)
        self.mode_combo.currentIndexChanged.connect(self._update_send_stats)
        self.line_ending_combo.currentIndexChanged.connect(self._update_send_stats)
        self.checksum_combo.currentIndexChanged.connect(self._update_send_stats)
        self.escape_cb.toggled.connect(self._update_send_stats)
        self.checksum_combo.currentIndexChanged.connect(self._update_checksum_hint)
        self.mode_combo.currentIndexChanged.connect(self._update_checksum_hint)

        for widget in (self.port_combo, self.baud_combo, self.databits_combo, self.stopbits_combo,
                       self.parity_combo, self.flow_combo):
            widget.currentIndexChanged.connect(self._on_param_changed)
        self.baud_combo.currentTextChanged.connect(self._on_param_changed)
        self.reconnect_cb.toggled.connect(self._on_param_changed)

        self._worker.data_received.connect(self._on_data_received)
        self._worker.bytes_sent.connect(self._on_bytes_sent)
        self._worker.status_changed.connect(self._on_worker_status)
        self._worker.error_occurred.connect(self._on_worker_error)
        self._worker.port_opened.connect(self._on_port_opened)
        self._worker.port_closed.connect(self._on_port_closed)
        self._worker.port_lost.connect(self._on_port_lost)
        self._worker.loop_sent.connect(self._on_loop_sent)

    # ---------- 广播 / 转发 ----------
    def _broadcast_others(self, payload):
        """把数据发给「发送目标」里的其它会话（本会话的发送由调用方负责）。"""
        for target in self._resolve_targets(self):
            if target is self:
                continue
            target.deliver(payload, origin=self.port_name or "本会话")

    def _dispatch(self, payload) -> bool:
        """发送并（按发送目标）广播；返回是否至少成功发出一份。"""
        delivered = self.deliver(payload)
        self._broadcast_others(payload)
        return delivered

    def _has_open_port(self) -> bool:
        return self._port_open

    def _on_forward_changed(self, *_):
        self.forward_target_id = str(self.forward_combo.currentData() or "")

    def refresh_forward_targets(self, sessions):
        """由主窗口在会话增删/改名时调用，刷新「转发到」列表。"""
        current = self.forward_target_id
        self.forward_combo.blockSignals(True)
        self.forward_combo.clear()
        self.forward_combo.addItem("不转发", "")
        for session in sessions:
            if session is self:
                continue
            self.forward_combo.addItem(session.label(), session.session_id)
        index = self.forward_combo.findData(current)
        self.forward_combo.setCurrentIndex(index if index >= 0 else 0)
        self.forward_combo.blockSignals(False)
        self.forward_target_id = str(self.forward_combo.currentData() or "")

    # ---------- 快捷发送 ----------
    def _on_quick_add(self):
        prefill = QuickSlot(
            content=self.tx_text.toPlainText().strip(),
            is_hex=self.mode_combo.currentText() == "HEX",
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
        self.status(f"已添加快捷发送：{slot.display_label()}")

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
        if not self._dispatch(payload):
            self._warn("没有已打开的会话，无法发送")

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
        try:
            ports = list_available_ports()
        except Exception:
            ports = []
        if ports != self._ports_cache:
            self._ports_cache = list(ports)
            self.port_combo.blockSignals(True)
            self.port_combo.clear()
            self.port_combo.addItems(ports)
            self.port_combo.blockSignals(False)
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self.title_changed.emit()

    def _on_param_changed(self, *_):
        if self._port_open:
            self.param_hint.setText("参数已改，需重开端口生效")

    def _toggle_port(self):
        if self._port_open:
            self._controller.loop_stop_requested.emit()
            self._set_loop_ui(False)
            self._controller.close_requested.emit()
            return
        port = self.port_name
        if not port:
            self._warn("请先选择串口")
            return
        holder = self._port_in_use(port, self)
        if holder:
            self._warn(f"{port} 已被 {holder} 占用，同一个串口不能被两个会话同时打开")
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
        if connected:
            self.param_hint.setText("")
        self.title_changed.emit()

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
        self._append_line("sys", f"{message}。可勾选「自动重连」。")
        self.status(message)

    def _on_worker_status(self, message: str):
        self.status(message)
        if "已打开" in message or "重连成功" in message or "已关闭" in message or "控制线" in message:
            self._append_line("sys", message)

    def _on_worker_error(self, message: str):
        self.status(message)
        self._append_line("sys", message)
        if "打开串口失败" in message:
            if self._interactive:
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
        else:
            # appendHtml 后布局未立即更新，maximum() 可能是旧值，延迟到下一轮事件循环再滚到底
            QTimer.singleShot(0, scrollbar.setValue, scrollbar.maximum())

    def _on_data_received(self, payload):
        data = bytes(payload)
        self._rx_count += len(data)
        self._mark_counts_dirty()
        self._write_log("RX", bytes_to_hex(data))
        self.received.emit(data)

        target_id = self.forward_target_id
        if target_id:
            target = self._resolve_session(target_id)
            if target is not None:
                target.deliver(data, origin=self.label())

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
        self._mark_counts_dirty()

    def _mark_counts_dirty(self):
        if not self._counts_timer.isActive():
            self._counts_timer.start()

    def _refresh_counts(self):
        self.counts_changed.emit(self._rx_count, self._tx_count)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _write_log(self, tag: str, text: str):
        if not self.log_cb.isChecked():
            return
        self._log_buffer.append(f"[{self._timestamp()}] {tag} {text}")
        if len(self._log_buffer) >= 500:
            self._flush_log()

    def _flush_log(self):
        if not self._log_buffer:
            return
        payload = "\n".join(self._log_buffer) + "\n"
        self._log_buffer.clear()
        day = time.strftime("%Y-%m-%d")
        try:
            if self._log_handle is None or self._log_day != day:
                self._close_log_handle()
                base = Path(self.log_dir) if self.log_dir else Path(LOG_DIR)
                base.mkdir(parents=True, exist_ok=True)
                self._log_path = base / f"serial_{day}.txt"
                self._log_day = day
                self._log_handle = open(self._log_path, "a", encoding="utf-8")
            self._log_handle.write(payload)
            self._log_handle.flush()
        except OSError as exc:
            self.status(f"日志写入失败：{exc}")
            self._close_log_handle()

    def _close_log_handle(self):
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
        self._log_handle = None

    def _choose_log_dir(self):
        current = self.log_dir or str(Path(LOG_DIR).resolve())
        folder = QFileDialog.getExistingDirectory(self, "选择日志保存目录", current)
        if not folder:
            return
        self.log_dir = folder
        self._flush_log()
        self._close_log_handle()
        self._log_path = None
        self._log_dir_btn_tooltip()
        self.status(f"日志目录已设为：{folder}")
        self._append_line("sys", f"日志目录已设为：{folder}")

    def _log_dir_btn_tooltip(self):
        shown = self.log_dir or str(Path(LOG_DIR).resolve())
        self.log_dir_btn.setToolTip(f"当前日志目录：{shown}\n点击可更换；日志为 txt，按天命名")

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
        self.status(f"接收数据已保存：{path}")

    # ---------- 发送 ----------
    def _build_payload(self, text, is_hex, use_escapes, checksum, ending) -> bytes:
        payload = encode_payload(text, is_hex, use_escapes)
        payload += line_ending(ending)
        return append_checksum(payload, checksum)

    def _transmit(self, payload: bytes, echo: bool = True) -> bool:
        if not payload:
            return False
        if self._dispatch(payload):
            return True
        self._warn("没有已打开的会话，无法发送")
        return False

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
        self.history_combo.addItem("最近发送", None)
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

    def _clear_send(self):
        self.tx_text.clear()
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
        self.status(f"发送文件 {state['offset']}/{len(state['data'])} 字节")

    def _file_stop(self, message: str):
        self._file_timer.stop()
        self._file_state = None
        self.send_file_btn.setText("文件")
        self.status(message)
        self._append_line("sys", message)

    # ---------- 定时发送与发送辅助 ----------
    def _update_send_stats(self, *_):
        self._stats_timer.start()

    def _compute_send_size(self):
        try:
            payload = self._build_payload(
                self.tx_text.toPlainText(),
                self.mode_combo.currentText() == "HEX",
                self.escape_cb.isChecked(),
                CHECKSUM_LABELS[self.checksum_combo.currentText()],
                str(self.line_ending_combo.currentData()),
            )
        except ValueError:
            return None
        return len(payload)

    def _refresh_send_stats(self):
        size = self._compute_send_size()
        self.send_stats_label.setText("编码错误" if size is None else f"{size} 字节")

    def _update_checksum_hint(self, *_):
        self.checksum_hint.setText("模式·校验共用")

    def _on_auto_send_period_changed(self, value: int):
        if self._auto_send_timer.isActive():
            self._auto_send_timer.start(int(value))

    def _on_auto_send_toggled(self, checked: bool):
        if checked:
            if not self._port_open:
                self.auto_send_cb.setChecked(False)
                self.status("定时发送需要先打开串口")
                return
            self._auto_send_timer.start(self.auto_send_spin.value())
            self.status(f"定时发送已开启：每 {self.auto_send_spin.value()} ms")
            self._append_line("sys", f"定时发送已开启：每 {self.auto_send_spin.value()} ms")
            return
        self._auto_send_timer.stop()
        self.status("定时发送已停止")
        self._append_line("sys", "定时发送已停止")

    def _auto_send_tick(self):
        if not self._port_open:
            self.auto_send_cb.setChecked(False)
            return
        self._send_once(remember=False)

    # ---------- 循环发送 ----------
    def _collect_loop_payloads(self):
        uniform = self.uniform_cb.isChecked()
        period = self.period_spin.value()
        checksum = CHECKSUM_LABELS.get(self.checksum_combo.currentText(), "none")
        items = self.send_table.get_items()
        payloads = []
        for row, item in enumerate(items):
            if not item.enabled or not item.content.strip():
                continue
            try:
                raw = encode_payload(item.content, self.mode_combo.currentText() == "HEX", True)
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
            self._dispatch(entry["payload"])
        self.status(f"已按顺序发送 {len(payloads)} 条勾选指令")

    def _toggle_loop(self):
        if self._loop_active:
            self._controller.loop_stop_requested.emit()
            self._set_loop_ui(False)
            self.status("循环发送已停止")
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
        self._controller.loop_requested.emit({"mode": mode, "payloads": payloads})
        self._set_loop_ui(True)
        label = "顺序轮询" if mode == MODE_SEQUENTIAL else "单条周期"
        if self.uniform_cb.isChecked():
            label = f"统一周期 {self.period_spin.value()} ms"
        self.status(f"循环发送已启动：{len(payloads)} 条，{label}")
        self._append_line("sys", f"循环发送已启动：{len(payloads)} 条，{label}")

    def _set_loop_ui(self, active: bool):
        self._loop_active = active
        self.loop_btn.setText("停止循环" if active else "开始循环")
        if not active:
            self.loop_btn.setObjectName("primary")
        self.loop_btn.style().unpolish(self.loop_btn)
        self.loop_btn.style().polish(self.loop_btn)

    def _on_loop_sent(self, row: int, payload=None):
        self.status(f"循环发送中：第 {row + 1} 条")
        if payload:
            data = bytes(payload)
            if self.echo_cb.isChecked():
                self._append_line("tx", bytes_to_hex(data))
            self._broadcast_others(data)

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
            self.status(f"方案已保存：{path}")
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
        self.status(f"方案已加载：{path}")

    # ---------- 设置 ----------
    def _group(self, key: str) -> str:
        return f"sessions/{self.session_id}/{key}"

    def _load_settings(self):
        settings = self._settings
        if settings is None:
            self._refresh_history_combo()
            self._refresh_send_stats()
            self._log_dir_btn_tooltip()
            return

        def value(key, default=None):
            return settings.value(self._group(key), default)

        baud = value("baudrate", "115200")
        if baud:
            self.baud_combo.setCurrentText(str(baud))
        data_bits = str(value("bytesize", "8 位"))
        index = self.databits_combo.findText(data_bits)
        if index >= 0:
            self.databits_combo.setCurrentIndex(index)
        stop_bits = str(value("stopbits", "1 位"))
        index = self.stopbits_combo.findText(stop_bits)
        if index >= 0:
            self.stopbits_combo.setCurrentIndex(index)
        parity = str(value("parity", "无校验"))
        index = self.parity_combo.findText(parity)
        if index >= 0:
            self.parity_combo.setCurrentIndex(index)
        flow = str(value("flow", "无流控"))
        index = self.flow_combo.findText(flow)
        if index >= 0:
            self.flow_combo.setCurrentIndex(index)
        self.reconnect_cb.setChecked(value("reconnect", "true") in (True, "true"))
        self.rts_cb.setChecked(value("rts", "true") in (True, "true"))
        self.dtr_cb.setChecked(value("dtr", "true") in (True, "true"))

        self._combo_set(self.display_combo, str(value("display", "text")))
        self._combo_set(self.encoding_combo, str(value("encoding", "utf-8")))
        self._combo_set(self.line_ending_combo, str(value("line_ending", "none")))
        self.auto_wrap_cb.setChecked(value("auto_wrap", "false") in (True, "true"))
        self.wrap_spin.setValue(int(value("wrap_ms", 200) or 200))

        self.uniform_cb.setChecked(value("uniform", "false") in (True, "true"))
        self.period_spin.setValue(int(value("period_ms", 1000) or 1000))
        self.auto_send_spin.setValue(int(value("auto_send_ms", 1000) or 1000))
        self.log_dir = str(value("log_dir", "") or "")
        self._alias = str(value("name", "") or "")

        self._history = history_from_raw(value("history"))
        self.quick_panel.set_slots(load_slots(value("quick_slots")))
        self._refresh_quick_shortcuts()
        self._refresh_history_combo()
        self._update_checksum_hint()
        self._refresh_send_stats()
        self._log_dir_btn_tooltip()

    @staticmethod
    def _combo_set(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save_settings(self):
        settings = self._settings
        if settings is None:
            return
        settings.setValue(self._group("port"), self.port_name)
        settings.setValue(self._group("baudrate"), self.baud_combo.currentText())
        settings.setValue(self._group("bytesize"), self.databits_combo.currentText())
        settings.setValue(self._group("stopbits"), self.stopbits_combo.currentText())
        settings.setValue(self._group("parity"), self.parity_combo.currentText())
        settings.setValue(self._group("flow"), self.flow_combo.currentText())
        settings.setValue(self._group("reconnect"), self.reconnect_cb.isChecked())
        settings.setValue(self._group("rts"), self.rts_cb.isChecked())
        settings.setValue(self._group("dtr"), self.dtr_cb.isChecked())
        settings.setValue(self._group("display"), str(self.display_combo.currentData() or "text"))
        settings.setValue(self._group("encoding"), str(self.encoding_combo.currentData() or "utf-8"))
        settings.setValue(self._group("line_ending"), str(self.line_ending_combo.currentData() or "none"))
        settings.setValue(self._group("auto_wrap"), self.auto_wrap_cb.isChecked())
        settings.setValue(self._group("wrap_ms"), self.wrap_spin.value())
        settings.setValue(self._group("uniform"), self.uniform_cb.isChecked())
        settings.setValue(self._group("period_ms"), self.period_spin.value())
        settings.setValue(self._group("auto_send_ms"), self.auto_send_spin.value())
        settings.setValue(self._group("log_dir"), self.log_dir)
        settings.setValue(self._group("name"), self._alias)
        settings.setValue(self._group("quick_slots"), dump_slots(self.quick_panel.get_slots()))
        settings.setValue(self._group("history"), dump_history(self._history))

    def closeEvent(self, event):
        """部件被关闭时确保串口线程退出（防线程泄漏）。"""
        self.shutdown()
        event.accept()

    # ---------- 其它 ----------
    def _warn(self, message: str):
        self.status(message)
        if self._interactive:
            QMessageBox.warning(self, "提示", message)
