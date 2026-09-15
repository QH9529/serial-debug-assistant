"""快捷发送面板：一键发送按钮 + 自定义快捷键。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.quicksend import MAX_SLOTS, QuickSlot
from .send_table import CHECKSUM_KEY_TO_LABEL, CHECKSUM_LABELS

COLUMNS = 6


class QuickSlotDialog(QDialog):
    """新增 / 编辑一条快捷发送。"""

    def __init__(self, slot: QuickSlot | None = None, parent=None):
        super().__init__(parent)
        slot = slot or QuickSlot()
        self.setWindowTitle("快捷发送条目")
        self.setMinimumWidth(360)

        form = QFormLayout(self)
        self.name_edit = QLineEdit(slot.label)
        self.name_edit.setPlaceholderText("按钮名称；留空则自动截取内容")
        self.content_edit = QLineEdit(slot.content)
        self.content_edit.setPlaceholderText("发送内容，文本模式支持 \\n \\r \\t \\xhh")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["文本", "HEX"])
        self.mode_combo.setCurrentIndex(1 if slot.is_hex else 0)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(list(CHECKSUM_LABELS.keys()))
        self.checksum_combo.setCurrentText(CHECKSUM_KEY_TO_LABEL.get(slot.checksum, "无"))
        self.hotkey_edit = QLineEdit(slot.hotkey)
        self.hotkey_edit.setPlaceholderText("例如 F1 / Ctrl+1 / Alt+S，留空表示不绑定")

        form.addRow("名称", self.name_edit)
        form.addRow("内容", self.content_edit)
        form.addRow("模式", self.mode_combo)
        form.addRow("校验", self.checksum_combo)
        form.addRow("快捷键", self.hotkey_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_slot(self) -> QuickSlot:
        return QuickSlot(
            label=self.name_edit.text().strip(),
            content=self.content_edit.text(),
            is_hex=self.mode_combo.currentIndex() == 1,
            checksum=CHECKSUM_LABELS.get(self.checksum_combo.currentText(), "none"),
            hotkey=self.hotkey_edit.text().strip(),
        )


class QuickSendPanel(QWidget):
    """把常用指令固定成一排按钮，点击即发送。"""

    send_requested = Signal(object)
    add_requested = Signal()
    slots_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[QuickSlot] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.add_btn = QPushButton("添加")
        self.add_btn.setObjectName("ghost")
        self.add_btn.setToolTip("把当前发送框内容固定为一个快捷按钮")
        self.hint = QLabel("点击按钮立即发送；右键可编辑或删除")
        self.hint.setObjectName("hint")
        bar.addWidget(self.add_btn)
        bar.addWidget(self.hint)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        layout.addLayout(self.grid)

        self.add_btn.clicked.connect(self.add_requested)
        self._rebuild()

    # ---------- 数据 ----------
    def get_slots(self) -> list:
        self._collect_edits()
        return list(self._slots)

    def set_slots(self, slots) -> None:
        self._slots = list(slots)[:MAX_SLOTS]
        self._rebuild()

    def add_slot(self, slot: QuickSlot) -> bool:
        if len(self._slots) >= MAX_SLOTS:
            return False
        self._slots.append(slot)
        self._rebuild()
        self.slots_changed.emit()
        return True

    def _collect_edits(self):
        """对话框编辑走的是临时对象，这里保持 slots 为唯一数据源。"""
        return None

    # ---------- 渲染 ----------
    def _rebuild(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._slots:
            empty = QLabel("还没有快捷指令。点击左侧「添加」把常用报文固定到这里。")
            empty.setObjectName("hint")
            self.grid.addWidget(empty, 0, 0, 1, COLUMNS)
            return

        for index, slot in enumerate(self._slots):
            button = QPushButton(slot.display_label())
            button.setObjectName("ghost")
            tip = slot.content if slot.content else "(空)"
            if slot.hotkey:
                tip += f"\n快捷键：{slot.hotkey}"
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=slot: self.send_requested.emit(s))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, s=slot, b=button: self._context_menu(s, b, pos)
            )
            self.grid.addWidget(button, index // COLUMNS, index % COLUMNS)

    def _context_menu(self, slot: QuickSlot, button: QPushButton, pos):
        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        delete_action = menu.addAction("删除")
        chosen = menu.exec(button.mapToGlobal(pos))
        if chosen is edit_action:
            dialog = QuickSlotDialog(slot, self)
            if dialog.exec():
                updated = dialog.result_slot()
                index = self._slots.index(slot)
                self._slots[index] = updated
                self._rebuild()
                self.slots_changed.emit()
        elif chosen is delete_action:
            self._slots.remove(slot)
            self._rebuild()
            self.slots_changed.emit()
