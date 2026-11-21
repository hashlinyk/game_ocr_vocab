"""设置窗口：左侧菜单 + 右侧内容（当前仅「快捷键」页，支持录制与重绑定）。"""

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, format_hotkey


def _qt_seq_from(mods: int, vk: int) -> QKeySequence:
    qmods = Qt.NoModifier
    if mods & MOD_CONTROL:
        qmods |= Qt.ControlModifier
    if mods & MOD_ALT:
        qmods |= Qt.AltModifier
    if mods & MOD_SHIFT:
        qmods |= Qt.ShiftModifier
    if 0x30 <= vk <= 0x5A:
        key = Qt.Key(vk)  # 字母/数字 VK 与 Qt.Key 数值一致
    elif 0x70 <= vk <= 0x87:
        key = Qt.Key(Qt.Key_F1 + (vk - 0x70))
    else:
        return QKeySequence()
    return QKeySequence(QKeyCombination(qmods, key))


def _seq_to_qt(seq: QKeySequence):
    """QKeySequence -> (win32 mods, vk)；无法转换返回 None。"""
    if seq.count() == 0:
        return None
    comb = seq[0]
    s = comb.keyboardModifiers()
    mods = 0
    if s & Qt.ControlModifier:
        mods |= MOD_CONTROL
    if s & Qt.AltModifier:
        mods |= MOD_ALT
    if s & Qt.ShiftModifier:
        mods |= MOD_SHIFT
    if not mods:
        return None  # 必须带修饰键
    key = comb.key()
    vk = key.value if hasattr(key, "value") else int(key)
    if 0x30 <= vk <= 0x5A:
        return mods, vk
    if Qt.Key_F1.value <= vk <= Qt.Key_F24.value:
        return mods, 0x70 + (vk - Qt.Key_F1.value)
    return None


class SettingsDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("设置")
        self.resize(640, 420)

        layout = QHBoxLayout(self)
        self.menu = QListWidget()
        self.menu.setFixedWidth(150)
        self.menu.addItem("快捷键")
        self.menu.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        layout.addWidget(self.menu)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_hotkey_page())
        layout.addWidget(self.stack, 1)

    def _build_hotkey_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        hint = QLabel("点击输入框后按下新组合键（需包含 Ctrl/Alt/Shift），点「应用」立即生效")
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        vbox.addWidget(hint)

        self._editors: dict[str, tuple[QKeySequenceEdit, QLabel]] = {}
        for slug, (display, mods, vk) in self.manager.bindings().items():
            row = QHBoxLayout()
            row.addWidget(QLabel(display), 1)
            edit = QKeySequenceEdit()
            edit.setKeySequence(_qt_seq_from(mods, vk))
            edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(220)
            row.addWidget(edit)
            state = QLabel(f"当前: {format_hotkey(mods, vk)}")
            state.setStyleSheet("color: #2e8b57;")
            state.setFixedWidth(180)
            row.addWidget(state)
            vbox.addLayout(row)
            self._editors[slug] = (edit, state)

        vbox.addStretch()
        apply_btn = QPushButton("应用")
        apply_btn.clicked.connect(self._apply)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(apply_btn)
        vbox.addLayout(bottom)
        return page

    def _apply(self) -> None:
        failed = []
        for slug, (edit, state) in self._editors.items():
            parsed = _seq_to_qt(edit.keySequence())
            if parsed is None:
                continue  # 未修改或无效（无修饰键）的跳过
            mods, vk = parsed
            display = self.manager.bindings()[slug][0]
            if self.manager.rebind(slug, mods, vk):
                state.setText(f"当前: {format_hotkey(mods, vk)}")
            else:
                failed.append(display)
        if failed:
            QMessageBox.warning(
                self, "快捷键注册失败",
                "以下快捷键被其他程序占用，已恢复原组合：\n" + "\n".join(failed),
            )
