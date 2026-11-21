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
        self.menu.addItem("关于")
        self.menu.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        layout.addWidget(self.menu)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_hotkey_page())
        self.stack.addWidget(self._build_about_page())
        layout.addWidget(self.stack, 1)

    def _build_about_page(self) -> QWidget:
        from . import __author__, __version__

        page = QWidget()
        vbox = QVBoxLayout(page)
        title = QLabel("游戏单词助手")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        ver = QLabel(f"版本 {__version__}")
        ver.setStyleSheet("color: #666;")
        author = QLabel(f"作者：{__author__}")
        author.setStyleSheet("color: #666;")
        desc = QLabel(
            "游戏画面离线英文单词识别与翻译\n"
            "OCR：RapidOCR ｜ 词典：ECDICT ｜ 发音：Piper 神经语音\n"
            "识别方式：窗口捕获（WGC）/ 框选区域"
        )
        desc.setStyleSheet("color: #888;")
        vbox.addWidget(title)
        vbox.addWidget(ver)
        vbox.addWidget(author)
        vbox.addSpacing(8)
        vbox.addWidget(desc)
        vbox.addStretch()
        return page

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
        bottom = QHBoxLayout()
        reset_btn = QPushButton("重置")
        reset_btn.setToolTip("恢复全部默认快捷键")
        reset_btn.clicked.connect(self._reset)
        apply_btn = QPushButton("应用")
        apply_btn.clicked.connect(self._apply)
        bottom.addWidget(reset_btn)
        bottom.addStretch()
        bottom.addWidget(apply_btn)
        vbox.addLayout(bottom)
        return page

    def _reset(self) -> None:
        ret = QMessageBox.question(self, "确认重置", "将所有快捷键恢复为默认组合？")
        if ret != QMessageBox.Yes:
            return
        self.manager.reset_defaults()
        for slug, (edit, state) in self._editors.items():
            _display, mods, vk = self.manager.bindings()[slug]
            edit.setKeySequence(_qt_seq_from(mods, vk))
            state.setText(f"当前: {format_hotkey(mods, vk)}")

    def _apply(self) -> None:
        for slug, (edit, state) in self._editors.items():
            parsed = _seq_to_qt(edit.keySequence())
            if parsed is None:
                continue  # 未修改或无效（无修饰键）的跳过
            mods, vk = parsed
            # 设置窗口打开期间热键处于 suspend 状态，这里只保存配置；
            # 关闭窗口时由 manager.resume() 统一注册并报告被占用的组合
            self.manager.rebind(slug, mods, vk, register=False)
            state.setText(f"当前: {format_hotkey(mods, vk)}")
