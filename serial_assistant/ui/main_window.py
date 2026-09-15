"""主窗口：多会话标签页、广播下发与串口间转发。"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, resources
from . import theme as theme_mod
from .session_widget import SessionWidget

APP_NAME = "串口调试助手"
APP_VERSION = __version__
APP_VERSION_LABEL = f"V{APP_VERSION}"

BROADCAST_CURRENT = "current"
BROADCAST_ALL = "all"
BROADCAST_CUSTOM = "custom"


class BroadcastTargetDialog(QDialog):
    """勾选广播目标会话。"""

    def __init__(self, sessions, selected_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择广播目标")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        hint = QLabel("勾选要同时接收数据（同一条指令）的会话：")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.list = QListWidget()
        for session in sessions:
            state = "已连接" if session.is_open else "未连接"
            item = QListWidgetItem(f"{session.label()}（{state}）")
            item.setData(Qt.UserRole, session.session_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if session.session_id in selected_ids else Qt.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_ids(self):
        result = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked:
                result.append(str(item.data(Qt.UserRole)))
        return result


class MainWindow(QMainWindow):
    def __init__(self, parent=None, settings=None, interactive=True):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME}-{APP_VERSION_LABEL}")
        self.resize(1280, 820)

        icon = resources.app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._settings = settings or QSettings("QH9529", "SerialDebugAssistant")
        self._theme_name = str(self._settings.value("theme", "dark") or "dark")
        self._theme = theme_mod.current_theme(self._theme_name)
        self._interactive = interactive
        self._sessions = []
        self._next_no = int(self._settings.value("next_session_no", 1) or 1)
        self._broadcast_mode = str(
            self._settings.value("broadcast", BROADCAST_CURRENT) or BROADCAST_CURRENT
        )
        self._broadcast_ids = [str(x) for x in (self._settings.value("broadcast_ids", []) or [])]

        self._build_ui()
        self._apply_theme()
        self._restore_sessions()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(8)

        layout.addLayout(self._build_toolbar())

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_session)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        status = self.statusBar()
        self.counts_label = QLabel("RX 0 B  TX 0 B")
        self.counts_label.setObjectName("pill")
        self.counts_label.setToolTip("当前会话的收发字节数")
        status.addPermanentWidget(self.counts_label)
        status.showMessage("就绪")

    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)

        self.add_btn = QPushButton("新建会话")
        self.add_btn.setObjectName("primary")
        self.add_btn.setToolTip("新建一个独立的串口会话（独立参数、计数与日志）")
        self.del_btn = QPushButton("关闭会话")
        self.del_btn.setObjectName("ghost")
        self.del_btn.setToolTip("关闭当前会话（会先关闭其串口）")

        bc_tag = QLabel("发送目标")
        bc_tag.setObjectName("hint")
        self.broadcast_combo = QComboBox()
        self.broadcast_combo.addItem("当前会话", BROADCAST_CURRENT)
        self.broadcast_combo.addItem("全部会话", BROADCAST_ALL)
        self.broadcast_combo.addItem("勾选会话…", BROADCAST_CUSTOM)
        self.broadcast_combo.setFixedWidth(120)
        self.broadcast_combo.setToolTip(
            "单次发送 / 快捷发送 / 循环发送的目标范围\n"
            "选「勾选会话…」可指定一个或多个会话同时下发"
        )
        index = self.broadcast_combo.findData(self._broadcast_mode)
        if index >= 0:
            self.broadcast_combo.setCurrentIndex(index)

        self.top_cb = QCheckBox("置顶")
        self.top_cb.setToolTip("窗口保持在其他窗口之上")
        self.theme_btn = QPushButton(self._theme["label"])
        self.theme_btn.setObjectName("ghost")
        self.theme_btn.setToolTip("切换深色 / 浅色主题")

        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addSpacing(10)
        row.addWidget(bc_tag)
        row.addWidget(self.broadcast_combo)
        row.addStretch(1)
        row.addWidget(self.top_cb)
        row.addWidget(self.theme_btn)

        self.add_btn.clicked.connect(lambda: self.add_session())
        self.del_btn.clicked.connect(lambda: self.close_session(self.tabs.currentIndex()))
        self.broadcast_combo.currentIndexChanged.connect(self._on_broadcast_changed)
        self.top_cb.toggled.connect(self._toggle_always_on_top)
        self.theme_btn.clicked.connect(self._toggle_theme)
        return row

    # ---------- 会话管理 ----------
    def sessions(self):
        return list(self._sessions)

    def current_session(self):
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, SessionWidget) else None

    def resolve_session(self, session_id):
        for session in self._sessions:
            if session.session_id == session_id:
                return session
        return None

    def add_session(self, session_no=None) -> SessionWidget:
        no = int(session_no) if session_no else self._next_no
        self._next_no = max(self._next_no, no + 1)
        session = SessionWidget(
            session_no=no,
            settings=self._settings,
            theme=self._theme,
            port_in_use=self._port_in_use,
            resolve_targets=self._resolve_targets,
            resolve_session=self.resolve_session,
            interactive=self._interactive,
        )
        session.title_changed.connect(self._refresh_titles)
        session.counts_changed.connect(self._on_counts)
        session.message.connect(self._on_session_message)
        self._sessions.append(session)

        index = self.tabs.addTab(session, session.tab_text())
        self.tabs.setTabToolTip(index, session.tab_tooltip())
        self.tabs.setCurrentIndex(index)
        self._refresh_forward_targets()
        self._refresh_titles()
        self._refresh_counts_label()
        return session

    def close_session(self, index: int):
        if index < 0 or index >= self.tabs.count():
            return
        session = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if isinstance(session, SessionWidget):
            session.shutdown()
            if session in self._sessions:
                self._sessions.remove(session)
            session.setParent(None)
            session.deleteLater()
        self._refresh_forward_targets()
        self._refresh_titles()
        self._save_settings()
        if not self._sessions:
            self.add_session()

    def _restore_sessions(self):
        count = int(self._settings.value("session_count", 1) or 1)
        count = max(1, min(count, 8))
        active = int(self._settings.value("active_index", 0) or 0)
        for no in range(1, count + 1):
            self.add_session(session_no=no)
        self._next_no = max(self._next_no, count + 1)
        if 0 <= active < self.tabs.count():
            self.tabs.setCurrentIndex(active)
        self._refresh_counts_label()

    def _refresh_forward_targets(self):
        for session in self._sessions:
            session.refresh_forward_targets(self._sessions)

    def _refresh_titles(self):
        for index in range(self.tabs.count()):
            session = self.tabs.widget(index)
            if isinstance(session, SessionWidget):
                self.tabs.setTabText(index, session.tab_text())
                self.tabs.setTabToolTip(index, session.tab_tooltip())
        self._refresh_forward_targets()

    def _refresh_counts_label(self):
        session = self.current_session()
        self.counts_label.setText(session.counts_text() if session else "RX 0 B  TX 0 B")

    # ---------- 广播 / 转发 ----------
    def _port_in_use(self, port, exclude):
        for session in self._sessions:
            if session is exclude:
                continue
            if session.is_open and session.port_name == port:
                return session.label()
        return None

    def _resolve_targets(self, sender):
        """按「发送目标」计算本次发送要覆盖的会话（发起方一定包含在内）。"""
        if self._broadcast_mode == BROADCAST_ALL:
            targets = list(self._sessions)
        elif self._broadcast_mode == BROADCAST_CUSTOM:
            targets = [s for s in self._sessions if s.session_id in self._broadcast_ids]
        else:
            targets = [s for s in self._sessions if s is sender]
        if sender is not None and sender not in targets:
            targets.insert(0, sender)
        return targets

    def _on_broadcast_changed(self, *_):
        mode = str(self.broadcast_combo.currentData() or BROADCAST_CURRENT)
        if mode == BROADCAST_CUSTOM:
            dialog = BroadcastTargetDialog(self._sessions, self._broadcast_ids, self)
            if not dialog.exec():
                index = self.broadcast_combo.findData(self._broadcast_mode)
                self.broadcast_combo.blockSignals(True)
                self.broadcast_combo.setCurrentIndex(max(0, index))
                self.broadcast_combo.blockSignals(False)
                return
            self._broadcast_ids = dialog.selected_ids()
        self._broadcast_mode = mode
        self._settings.setValue("broadcast", mode)
        self._settings.setValue("broadcast_ids", self._broadcast_ids)
        labels = {BROADCAST_CURRENT: "当前会话", BROADCAST_ALL: "全部会话"}
        if mode == BROADCAST_CUSTOM:
            names = [s.label() for s in self._sessions if s.session_id in self._broadcast_ids]
            text = "勾选：" + ("、".join(names) if names else "（未选择）")
        else:
            text = labels.get(mode, mode)
        self.statusBar().showMessage(f"发送目标已设为 {text}")

    # ---------- 主题 / 窗口 ----------
    def _apply_theme(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            self._theme = theme_mod.apply_theme(app, self._theme_name)
        for session in self._sessions:
            session.set_theme(self._theme)
        if hasattr(self, "theme_btn"):
            self.theme_btn.setText(self._theme["label"])

    def _toggle_theme(self):
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        self._settings.setValue("theme", self._theme_name)
        self._apply_theme()

    def _toggle_always_on_top(self, checked: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(checked))
        self.show()

    # ---------- 状态 ----------
    def _on_tab_changed(self, *_):
        self._refresh_counts_label()
        session = self.current_session()
        if session is not None:
            self.statusBar().showMessage(f"{session.label()} · {'已连接' if session.is_open else '未连接'}")

    def _on_counts(self, rx: int, tx: int):
        sender = self.sender()
        if sender is self.current_session():
            self.counts_label.setText(f"RX {rx} B  TX {tx} B")

    def _on_session_message(self, text: str):
        sender = self.sender()
        if self.current_session() is None or sender is self.current_session():
            self.statusBar().showMessage(text)

    # ---------- 设置 ----------
    def _save_settings(self):
        settings = self._settings
        settings.setValue("theme", self._theme_name)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("session_count", len(self._sessions))
        settings.setValue("active_index", self.tabs.currentIndex())
        settings.setValue("next_session_no", self._next_no)
        settings.setValue("broadcast", self._broadcast_mode)
        settings.setValue("broadcast_ids", self._broadcast_ids)
        settings.setValue("on_top", self.top_cb.isChecked())
        for session in self._sessions:
            session._save_settings()

    def closeEvent(self, event):
        try:
            for session in list(self._sessions):
                session.shutdown()
        finally:
            self._save_settings()
            event.accept()
