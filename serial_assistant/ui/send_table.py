"""多条循环发送表格控件。

每行都是真实输入控件（勾选框 / 输入框 / 数字框），行尾带删除按钮。
模式与校验为全局设置（与单次发送共用），不在此表内。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.scheduler import MessageItem

MAX_INTERVAL_MS = 86400000

# 校验标签（发送区的全局校验下拉使用）
CHECKSUM_LABELS = {
    "无": "none",
    "CRC16": "crc16",
    "SUM8": "sum8",
    "LRC": "lrc",
}
CHECKSUM_TOOLTIPS = {
    "无": "不追加校验",
    "CRC16": "CRC16-Modbus，低字节在前",
    "SUM8": "8 位累加和",
    "LRC": "各字节之和取反加一",
}
CHECKSUM_KEY_TO_LABEL = {v: k for k, v in CHECKSUM_LABELS.items()}


class SendTableWidget(QWidget):
    """循环发送条目表：启用 / 内容 / 间隔 / 备注 / 删除。"""

    COL_ENABLED = 0
    COL_CONTENT = 1
    COL_INTERVAL = 2
    COL_NOTE = 3
    COL_DELETE = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["启用", "内容（模式与校验见发送区）", "间隔(ms)", "备注", ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_CONTENT, QHeaderView.Stretch)
        self.table.setColumnWidth(self.COL_ENABLED, 46)
        self.table.setColumnWidth(self.COL_INTERVAL, 104)
        self.table.setColumnWidth(self.COL_NOTE, 130)
        self.table.setColumnWidth(self.COL_DELETE, 60)
        layout.addWidget(self.table)

    # ---------- 行构建 ----------
    def add_row(self, item=None) -> int:
        item = item or MessageItem()
        row = self.table.rowCount()
        self.table.insertRow(row)

        enabled = QCheckBox()
        enabled.setChecked(bool(item.enabled))
        enabled.setToolTip("是否参与循环发送")
        wrap = QWidget()
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setAlignment(Qt.AlignCenter)
        wrap_layout.addWidget(enabled)
        self.table.setCellWidget(row, self.COL_ENABLED, wrap)

        content = QLineEdit(item.content)
        content.setPlaceholderText("发送内容，文本模式支持 \\n \\r \\t \\xhh 转义")
        self.table.setCellWidget(row, self.COL_CONTENT, content)

        interval = QSpinBox()
        interval.setRange(1, MAX_INTERVAL_MS)
        interval.setSingleStep(50)
        interval.setValue(max(1, int(item.interval_ms)))
        interval.setToolTip("这条指令发送后等待的间隔；勾选「统一周期」时以全局周期为准")
        self.table.setCellWidget(row, self.COL_INTERVAL, interval)

        note = QLineEdit(item.note)
        note.setPlaceholderText("备注")
        self.table.setCellWidget(row, self.COL_NOTE, note)

        delete = QPushButton("删除")
        delete.setObjectName("rowDelete")
        delete.setToolTip("删除这一条")
        delete.clicked.connect(self._on_row_delete)
        self.table.setCellWidget(row, self.COL_DELETE, delete)
        return row

    def _on_row_delete(self):
        button = self.sender()
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self.COL_DELETE) is button:
                self.table.removeRow(row)
                return

    # ---------- 读写 ----------
    def get_items(self):
        items = []
        for row in range(self.table.rowCount()):
            enabled_wrap = self.table.cellWidget(row, self.COL_ENABLED)
            enabled_box = enabled_wrap.findChild(QCheckBox) if enabled_wrap else None
            content = self.table.cellWidget(row, self.COL_CONTENT)
            interval = self.table.cellWidget(row, self.COL_INTERVAL)
            note = self.table.cellWidget(row, self.COL_NOTE)
            items.append(
                MessageItem(
                    content=content.text() if content else "",
                    is_hex=False,
                    interval_ms=max(1, interval.value()) if interval else 1000,
                    note=note.text() if note else "",
                    enabled=bool(enabled_box and enabled_box.isChecked()),
                    checksum="none",
                )
            )
        return items

    def set_items(self, items):
        self.table.setRowCount(0)
        for item in items:
            self.add_row(item)

    def clear_rows(self):
        self.table.setRowCount(0)

    def remove_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def selected_row(self):
        row = self.table.currentRow()
        if row >= 0:
            return row
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return rows[0] if len(rows) == 1 else None

    def move_current(self, delta: int):
        row = self.selected_row()
        if row is None:
            return
        target = row + delta
        if target < 0 or target >= self.table.rowCount():
            return
        items = self.get_items()
        items[row], items[target] = items[target], items[row]
        self.set_items(items)
        self.table.selectRow(target)
