"""多条循环发送表格控件。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.scheduler import MessageItem

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
    """循环发送条目表：启用 / 内容 / 模式 / 间隔 / 校验 / 备注。"""

    COL_ENABLED = 0
    COL_CONTENT = 1
    COL_MODE = 2
    COL_INTERVAL = 3
    COL_CHECKSUM = 4
    COL_NOTE = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["启用", "内容", "模式", "间隔(ms)", "校验", "备注"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_CONTENT, QHeaderView.Stretch)
        self.table.setColumnWidth(self.COL_ENABLED, 48)
        self.table.setColumnWidth(self.COL_MODE, 72)
        self.table.setColumnWidth(self.COL_INTERVAL, 84)
        self.table.setColumnWidth(self.COL_CHECKSUM, 120)
        self.table.setColumnWidth(self.COL_NOTE, 120)
        layout.addWidget(self.table)

    # ---------- 行操作 ----------
    def add_row(self, item=None) -> int:
        item = item or MessageItem()
        row = self.table.rowCount()
        self.table.insertRow(row)

        flag = QTableWidgetItem()
        flag.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        flag.setCheckState(Qt.Checked if item.enabled else Qt.Unchecked)
        self.table.setItem(row, self.COL_ENABLED, flag)

        self.table.setItem(row, self.COL_CONTENT, QTableWidgetItem(item.content))

        mode_combo = QComboBox()
        mode_combo.addItems(["文本", "HEX"])
        mode_combo.setCurrentIndex(1 if item.is_hex else 0)
        self.table.setCellWidget(row, self.COL_MODE, mode_combo)

        self.table.setItem(row, self.COL_INTERVAL, QTableWidgetItem(str(item.interval_ms)))

        sum_combo = QComboBox()
        for label in CHECKSUM_LABELS:
            sum_combo.addItem(label)
            sum_combo.setItemData(
                sum_combo.count() - 1, CHECKSUM_TOOLTIPS.get(label, ""), Qt.ToolTipRole
            )
        sum_combo.setCurrentText(CHECKSUM_KEY_TO_LABEL.get(item.checksum, "无"))
        self.table.setCellWidget(row, self.COL_CHECKSUM, sum_combo)

        self.table.setItem(row, self.COL_NOTE, QTableWidgetItem(item.note))
        return row

    def get_items(self):
        items = []
        for row in range(self.table.rowCount()):
            flag = self.table.item(row, self.COL_ENABLED)
            content_item = self.table.item(row, self.COL_CONTENT)
            interval_item = self.table.item(row, self.COL_INTERVAL)
            note_item = self.table.item(row, self.COL_NOTE)
            mode_combo = self.table.cellWidget(row, self.COL_MODE)
            sum_combo = self.table.cellWidget(row, self.COL_CHECKSUM)
            try:
                interval = int((interval_item.text() if interval_item else "").strip() or "1000")
            except ValueError:
                interval = 1000
            items.append(
                MessageItem(
                    content=content_item.text() if content_item else "",
                    is_hex=bool(mode_combo and mode_combo.currentIndex() == 1),
                    interval_ms=max(interval, 1),
                    note=note_item.text() if note_item else "",
                    enabled=bool(flag and flag.checkState() == Qt.Checked),
                    checksum=CHECKSUM_LABELS.get(sum_combo.currentText(), "none") if sum_combo else "none",
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
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if len(rows) == 1:
            return rows[0]
        return None

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
