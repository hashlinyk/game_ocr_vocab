"""全局热键唤起的快速查词弹窗：极简卡片、自动获焦、实时过滤识别页单词、回车加入生词本。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

CARD_W = 480
LIST_MAX_H = 340


class QuickAddDialog(QDialog):
    """输入过滤识别页单词 → 上下键选择 → 回车加入生词本并关闭。"""

    def __init__(self, main_win):
        super().__init__(None)
        self._win = main_win
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)  # 阴影空间
        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: #ffffff; border-radius: 12px; }"
            "QLineEdit { border: none; border-bottom: 1px solid #eeeeee; padding: 10px 8px;"
            "  font-size: 16px; background: transparent; }"
            "QListWidget { border: none; background: transparent; font-size: 14px; outline: none; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; }"
            "QListWidget::item:selected { background: #eaf2fe; color: #1a1a1a; }"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(26)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入单词或翻译…   ↑↓ 选择   Enter 加入生词本   Esc 关闭")
        self.edit.textChanged.connect(self._refill)
        lay.addWidget(self.edit)
        self.listw = QListWidget()
        self.listw.setMaximumHeight(LIST_MAX_H)
        self.listw.itemDoubleClicked.connect(lambda _i: self._commit_current())
        lay.addWidget(self.listw)
        outer.addWidget(card)
        self.setFixedWidth(CARD_W + 36)
        self._entries: list[str] = []  # canonical 列表（与行对应）

    # ---- 按键：上下切换、回车提交 ----
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Down:
            row = self.listw.currentRow()
            if row < self.listw.count() - 1:
                self.listw.setCurrentRow(row + 1)
            return
        if key == Qt.Key_Up:
            row = self.listw.currentRow()
            if row > 0:
                self.listw.setCurrentRow(row - 1)
            return
        if key in (Qt.Key_Escape,):
            self.hide()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_current()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self.hide()

    # ---- 展示与数据 ----
    def popup(self) -> None:
        self.edit.clear()
        self._refill("")
        self.show()
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().geometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def _refill(self, kw: str) -> None:
        from .main_window import WordRow

        self.listw.clear()
        self._entries = []
        kw = kw.strip().lower()
        for i in range(self._win.list.count()):
            row = self._win.list.itemWidget(self._win.list.item(i))
            if not isinstance(row, WordRow):
                continue
            word = row.word_label.text()
            trans = row.trans_label.text()
            if kw and kw not in word.lower() and kw not in trans.lower():
                continue
            tag = " [生]" if row.in_vocab else ""
            self._entries.append(row.canonical)
            self.listw.addItem(QListWidgetItem(f"{word}{tag}    {trans[:60]}"))
        if self.listw.count():
            self.listw.setCurrentRow(0)
        if self.isVisible():
            self.adjustSize()

    def _commit_current(self) -> None:
        row = self.listw.currentRow()
        if row < 0 or row >= len(self._entries):
            return
        canonical = self._entries[row]
        self.hide()
        self._win.add_to_vocab(canonical)
