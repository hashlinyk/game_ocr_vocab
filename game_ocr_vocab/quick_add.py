"""全局热键唤起的快速查词弹窗：极简卡片、自动获焦、实时过滤识别页单词、回车加入生词本。"""

import ctypes

from PySide6.QtCore import QEvent, Qt
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
        self.edit.installEventFilter(self)  # 焦点在输入框时可靠拦截 ↑↓/Enter/Esc
        lay.addWidget(self.edit)
        self.listw = QListWidget()
        self.listw.setMaximumHeight(LIST_MAX_H)
        self.listw.itemDoubleClicked.connect(lambda _i: self._commit_current())
        lay.addWidget(self.listw)
        outer.addWidget(card)
        self.setFixedWidth(CARD_W + 36)
        self._prev_hwnd: int | None = None

    # ---- 按键处理 ----
    def _handle_key(self, key) -> bool:
        if key == Qt.Key_Down:
            row = self.listw.currentRow()
            if row < self.listw.count() - 1:
                self.listw.setCurrentRow(row + 1)
            return True
        if key == Qt.Key_Up:
            row = self.listw.currentRow()
            if row > 0:
                self.listw.setCurrentRow(row - 1)
            return True
        if key == Qt.Key_Escape:
            self._dismiss()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_current()
            return True
        return False

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.edit and ev.type() == QEvent.KeyPress and self._handle_key(ev.key()):
            return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, event) -> None:
        if self._handle_key(event.key()):
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self.hide()  # 用户点击了别处：不打回焦点

    def _dismiss(self) -> None:
        """关闭弹窗并尝试把焦点还给弹出前的窗口（如游戏）。"""
        prev = self._prev_hwnd
        self.hide()
        if prev:
            try:
                ctypes.windll.user32.SetForegroundWindow(prev)
                ctypes.windll.user32.SetActiveWindow(prev)
            except Exception:
                pass

    # ---- 展示与数据 ----
    def popup(self) -> None:
        try:
            self._prev_hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            self._prev_hwnd = None
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

    def _add_entry(self, text: str, canonical: str | None) -> None:
        item = QListWidgetItem(text)
        if canonical is None:  # 分组标题行：不可选
            item.setData(Qt.UserRole, None)
            item.setFlags(Qt.NoItemFlags)
        else:
            item.setData(Qt.UserRole, canonical)
        self.listw.addItem(item)

    def _refill(self, kw: str) -> None:
        from .main_window import WordRow

        self.listw.clear()
        kw = kw.strip().lower()
        seen: set[str] = set()

        # 1) 识别区匹配（排在最前，可带生词标记）
        stream_hit = 0
        for i in range(self._win.list.count()):
            row = self._win.list.itemWidget(self._win.list.item(i))
            if not isinstance(row, WordRow):
                continue
            word = row.word_label.text()
            trans = row.trans_label.text()
            if kw and kw.lower() not in word.lower() and kw not in trans.lower():
                continue
            tag = " · 生" if row.in_vocab else ""
            seen.add(row.canonical)
            stream_hit += 1
            self._add_entry(f"{word}{tag}    {trans[:60]}", row.canonical)

        # 2) 全词典前缀检索（排在识别区结果之后）
        dict_hits: list[tuple[str, str]] = []
        if kw and self._win.dict is not None:
            for word, trans in self._win.dict.search_prefix(kw):
                if word in seen:
                    continue
                seen.add(word)
                dict_hits.append((word, trans))
        if dict_hits:
            if stream_hit:
                self._add_entry("── 词典 ──", None)  # 分组分隔
            for word, trans in dict_hits:
                self._add_entry(f"{word}    {trans[:60]}", word)

        # 默认选中第一条可选词条
        for i in range(self.listw.count()):
            if self.listw.item(i).data(Qt.UserRole):
                self.listw.setCurrentRow(i)
                break
        if self.isVisible():
            self.adjustSize()

    def _commit_current(self) -> None:
        item = self.listw.currentItem()
        if item is None:
            return
        canonical = item.data(Qt.UserRole)
        if not canonical:
            return
        self._win.add_to_vocab(canonical)
        self._dismiss()
