"""串口 IO 工作线程：串口读写与循环发送均在独立线程内完成。"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from serial import Serial, SerialException
from serial.tools import list_ports

from .core.ports import sort_ports
from .core.scheduler import LoopScheduler, MessageItem


def list_available_ports():
    """当前可用串口设备名列表，按数字自然升序（COM2 排在 COM10 前）。"""
    return sort_ports(p.device for p in list_ports.comports())


class SerialWorker(QObject):
    """在工作线程中运行的串口读写对象。"""

    RECONNECT_NOTICE_SECONDS = 10.0

    data_received = Signal(object)
    bytes_sent = Signal(int)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    port_opened = Signal(str)
    port_closed = Signal()
    port_lost = Signal(str)
    loop_sent = Signal(int, object)

    READ_INTERVAL_MS = 20
    LOOP_TICK_MS = 5
    RECONNECT_MS = 2000

    def __init__(self):
        super().__init__()
        self._serial = None
        self._config = None
        self._auto_reconnect = False
        self._scheduler = None
        self._payloads = {}
        self._row_map = []
        self._last_reconnect_notice = 0.0
        self._read_timer = QTimer(self)
        self._read_timer.setInterval(self.READ_INTERVAL_MS)
        self._read_timer.timeout.connect(self._poll_read)
        self._loop_timer = QTimer(self)
        self._loop_timer.setInterval(self.LOOP_TICK_MS)
        self._loop_timer.timeout.connect(self._poll_loop)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(self.RECONNECT_MS)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

    # ---------- 端口 ----------
    @Slot(object)
    def open_port(self, config: dict):
        self._config = dict(config)
        self._auto_reconnect = bool(config.get("auto_reconnect", False))
        if self._open():
            self._read_timer.start()
            self.port_opened.emit(str(config.get("port", "")))
            self.status_changed.emit(
                f"已打开 {config.get('port', '')} @ {config.get('baudrate', '')}"
            )

    def _open(self, silent: bool = False) -> bool:
        """打开串口；silent=True 时不弹错误（用于自动重连轮询）。"""
        self._close_serial()
        cfg = self._config or {}
        flow = cfg.get("flow")
        try:
            self._serial = Serial(
                port=cfg.get("port"),
                baudrate=int(cfg.get("baudrate", 115200)),
                bytesize=int(cfg.get("bytesize", 8)),
                stopbits=float(cfg.get("stopbits", 1)),
                parity=str(cfg.get("parity", "N")),
                xonxoff=(flow == "xonxoff"),
                rtscts=(flow == "rtscts"),
                timeout=0.02,
            )
            if cfg.get("rts") is not None:
                self._serial.rts = bool(cfg["rts"])
            if cfg.get("dtr") is not None:
                self._serial.dtr = bool(cfg["dtr"])
            return True
        except (SerialException, OSError, ValueError) as exc:
            self._serial = None
            if not silent:
                self.error_occurred.emit(f"打开串口失败：{exc}")
            return False

    def _close_serial(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @Slot()
    def close_port(self):
        self._stop_loop()
        self._reconnect_timer.stop()
        self._read_timer.stop()
        self._close_serial()
        self.port_closed.emit()
        self.status_changed.emit("串口已关闭")

    def _on_lost(self, message: str):
        self._read_timer.stop()
        self._stop_loop()
        self._close_serial()
        self.port_lost.emit(message)
        if self._auto_reconnect and self._config:
            self.status_changed.emit("串口断开，正在自动重连…")
            self._reconnect_timer.start()

    def _try_reconnect(self):
        if self.is_open:
            self._reconnect_timer.stop()
            return
        if self._open(silent=True):
            self._reconnect_timer.stop()
            self._read_timer.start()
            self.port_opened.emit(str((self._config or {}).get("port", "")))
            self.status_changed.emit("自动重连成功")
            self._last_reconnect_notice = 0.0
            return
        now = time.monotonic()
        if now - self._last_reconnect_notice >= self.RECONNECT_NOTICE_SECONDS:
            self._last_reconnect_notice = now
            self.status_changed.emit("自动重连中：暂未找到可用串口")

    # ---------- 收发 ----------
    @Slot(object)
    def set_control_lines(self, state: dict):
        """运行时切换 RTS / DTR 电平（复位 MCU 等场景）。"""
        if not self.is_open:
            self.error_occurred.emit("串口未打开，无法控制 RTS/DTR")
            return
        try:
            if "rts" in state:
                self._serial.rts = bool(state["rts"])
            if "dtr" in state:
                self._serial.dtr = bool(state["dtr"])
        except (SerialException, OSError, ValueError) as exc:
            self.error_occurred.emit(f"控制线设置失败：{exc}")
            return
        desc = "　".join(
            f"{key.upper()}={'ON' if bool(value) else 'OFF'}"
            for key, value in state.items()
        )
        self.status_changed.emit(f"控制线已切换：{desc}")

    @Slot(object)
    def send_bytes(self, payload):
        data = bytes(payload)
        if not self.is_open:
            self.error_occurred.emit("串口未打开，无法发送")
            return
        try:
            self._serial.write(data)
            self.bytes_sent.emit(len(data))
        except (SerialException, OSError) as exc:
            self.error_occurred.emit(f"发送失败：{exc}")
            self._on_lost("串口连接丢失")

    def _poll_read(self):
        if not self.is_open:
            return
        try:
            waiting = self._serial.in_waiting
            if waiting:
                data = self._serial.read(waiting)
                if data:
                    self.data_received.emit(bytes(data))
        except (SerialException, OSError) as exc:
            self.error_occurred.emit(f"读取失败：{exc}")
            self._on_lost("串口连接丢失")

    # ---------- 循环发送 ----------
    @Slot(object)
    def start_loop(self, config: dict):
        mode = config.get("mode")
        payloads = config.get("payloads", [])
        items = [
            MessageItem(interval_ms=int(p.get("interval_ms", 1000)), enabled=True)
            for p in payloads
        ]
        self._payloads = {i: bytes(p.get("payload", b"")) for i, p in enumerate(payloads)}
        self._row_map = [int(p.get("index", i)) for i, p in enumerate(payloads)]
        self._scheduler = LoopScheduler(items, mode)
        self._loop_timer.start()

    @Slot()
    def stop_loop(self):
        self._stop_loop()

    def _stop_loop(self):
        self._loop_timer.stop()
        self._scheduler = None

    def _poll_loop(self):
        if self._scheduler is None or not self.is_open:
            return
        for k in self._scheduler.poll():
            payload = self._payloads.get(k)
            if payload:
                self.send_bytes(payload)
                if 0 <= k < len(self._row_map):
                    self.loop_sent.emit(self._row_map[k], payload)


class SerialWorkerController(QObject):
    """UI 线程侧控制器：持有工作线程并转发请求。"""

    open_requested = Signal(object)
    close_requested = Signal()
    send_requested = Signal(object)
    control_requested = Signal(object)
    loop_requested = Signal(object)
    loop_stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = QThread(self)
        self.worker = SerialWorker()
        self.worker.moveToThread(self._thread)
        self.open_requested.connect(self.worker.open_port)
        self.close_requested.connect(self.worker.close_port)
        self.send_requested.connect(self.worker.send_bytes)
        self.control_requested.connect(self.worker.set_control_lines)
        self.loop_requested.connect(self.worker.start_loop)
        self.loop_stop_requested.connect(self.worker.stop_loop)
        self._thread.finished.connect(self.worker.deleteLater)
        self._thread.start()

    def shutdown(self):
        self.loop_stop_requested.emit()
        self.close_requested.emit()
        self._thread.quit()
        self._thread.wait(3000)
