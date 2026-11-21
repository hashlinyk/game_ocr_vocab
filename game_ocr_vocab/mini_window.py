"""Mini 模式：半透明卡片悬浮窗，极简深色风格，仅显示单词/翻译与状态图标。

交互：滚轮滚动列表；左键点行=掌握；右键点行=加入生词本；顶部「完整模式」返回。
"""

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MINI_W = 340
MINI_H = 520
STATE_COLORS = {"idle": "#777777", "running": "#3ddc84", "paused": "#ffb300"}

CARD_BG_IDLE = "rgba(18, 18, 24, 0.35)"   # 默认更透明
CARD_BG_HOVER = "rgba(18, 18, 24, 0.82)"  # 鼠标移入恢复

CARD_QSS = """
#miniCard {
    background: rgba(18, 18, 24, 0.35);
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.10);
}
QLabel { color: #e8e8ea; background: transparent; }
#stateDot { font-size: 14px; }
QPushButton {
    border: none; background: rgba(255,255,255,0.10); color: #e8e8ea;
    border-radius: 8px; padding: 4px 12px; font-size: 12px;
}
QPushButton:hover { background: rgba(255,255,255,0.20); }
QListWidget { border: none; background: transparent; outline: none; }
QListWidget::item { border: none; }
QListWidget::item:selected { background: transparent; }
#miniRow { background: transparent; border-radius: 8px; }
#miniRow:hover { background: rgba(255, 255, 255, 0.09); }
QScrollBar:vertical { width: 6px; background: rgba(0, 0, 0, 0.25); border-radius: 3px; margin: 2px 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.65); border-radius: 3px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.85); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class MiniRow(QWidget):
    """紧凑单词行：单词 + 单行翻译。左键掌握，右键生词本。"""

    def __init__(self, canonical, word, translation, in_vocab, on_master, on_vocab):
        super().__init__()
        self.canonical = canonical
        self._on_master = on_master
        self._on_vocab = on_vocab
        self._leaving = False
        self._anim = None
        self.setObjectName("miniRow")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 让 QSS 背景作用于整行而非仅文字
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(4)
        wl = QLabel(word)
        wl.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff;")
        top.addWidget(wl)
        if in_vocab:
            tag = QLabel("生")
            tag.setStyleSheet(
                "font-size: 10px; color: #ffb300; border: 1px solid #ffb300;"
                "border-radius: 6px; padding: 0px 4px;"
            )
            top.addWidget(tag)
        top.addStretch()
        lay.addLayout(top)
        tl = QLabel(translation.replace("\n", " ▸ "))
        tl.setStyleSheet("font-size: 12px; color: rgba(232,232,234,0.55);")
        lay.addWidget(tl)
        self.setToolTip(f"{word}\n左键：已掌握　右键：加入生词本")

    def mousePressEvent(self, event) -> None:
        if self._leaving:
            return
        if event.button() == Qt.LeftButton:
            self._animate_out(-1, lambda: self._on_master(self.canonical))
        elif event.button() == Qt.RightButton:
            self._animate_out(1, lambda: self._on_vocab(self.canonical))

    def _animate_out(self, direction: int, done) -> None:
        """左键向左滑出、右键向右滑出（淡出），动画结束后再执行操作触发列表刷新。"""
        self._leaving = True
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(220)
        anim.setStartValue(self.pos())
        anim.setEndValue(self.pos() + QPoint(direction * (self.width() + 60), 0))
        anim.setEasingCurve(QEasingCurve.InCubic)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(220)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        anim.finished.connect(done)
        self._anim = anim
        self._fade = fade
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        fade.start(QPropertyAnimation.DeleteWhenStopped)


class MiniWindow(QWidget):
    def __init__(self, main_win):
        super().__init__(None)
        self._win = main_win
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(CARD_QSS)
        self.setFixedSize(MINI_W, MINI_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        card = QWidget()
        card.setObjectName("miniCard")
        outer.addWidget(card)
        self._card = card
        self._card_bg = None
        self._apply_card_bg(CARD_BG_IDLE)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        header = QHBoxLayout()
        self.state_dot = QLabel("●")
        self.state_dot.setObjectName("stateDot")
        self.state_dot.setStyleSheet(f"color: {STATE_COLORS['idle']};")
        self.state_dot.setToolTip("识别状态")
        title = QLabel("词汇")
        title.setStyleSheet("font-size: 12px; color: rgba(232,232,234,0.45);")
        full_btn = QPushButton("完整模式")
        full_btn.clicked.connect(self._to_full)
        header.addWidget(self.state_dot)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(full_btn)
        lay.addLayout(header)

        self.listw = QListWidget()
        self.listw.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.listw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.listw, 1)
        self._drag_offset = None

        # 鼠标悬停背景切换：轮询光标位置（enter/leave 在子控件间切换会误报）
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(180)
        self._hover_timer.timeout.connect(self._check_hover)
        self._hover_timer.start()

    def _apply_card_bg(self, color: str) -> None:
        if self._card_bg == color:
            return
        self._card_bg = color
        self._card.setStyleSheet(
            f"#miniCard {{ background: {color}; border-radius: 16px;"
            " border: 1px solid rgba(255, 255, 255, 0.10); }}"
        )

    def _check_hover(self) -> None:
        if not self.isVisible():
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        self._apply_card_bg(CARD_BG_HOVER if inside else CARD_BG_IDLE)

    # ---- 拖动窗口（按住空白处拖动） ----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None

    # ---- 状态与内容 ----
    def set_state(self, state: str) -> None:
        color = STATE_COLORS.get(state, STATE_COLORS["idle"])
        self.state_dot.setStyleSheet(f"color: {color};")

    def refresh(self) -> None:
        from .main_window import WordRow

        sb = self.listw.verticalScrollBar()
        was_at_bottom = sb.maximum() <= 0 or sb.value() >= sb.maximum() - 4
        self.listw.clear()
        for i in range(self._win.list.count()):
            row = self._win.list.itemWidget(self._win.list.item(i))
            if not isinstance(row, WordRow):
                continue
            mini = MiniRow(
                row.canonical,
                row.word_label.text(),
                row.trans_label.text(),
                row.in_vocab,
                on_master=lambda c: self._win._mark(c, "mastered")(c),
                on_vocab=lambda c: self._win.add_to_vocab(c),
            )
            item = QListWidgetItem()
            item.setSizeHint(mini.sizeHint())
            self.listw.addItem(item)
            self.listw.setItemWidget(item, mini)
        if was_at_bottom and self.listw.count():
            QTimer.singleShot(0, self._smooth_scroll_bottom)

    def _smooth_scroll_bottom(self) -> None:
        """平滑缓慢滚动到底部（新词追加时跟随）。"""
        sb = self.listw.verticalScrollBar()
        if sb.maximum() <= 0:
            return
        anim = QPropertyAnimation(sb, b"value", self)
        anim.setDuration(500)
        anim.setStartValue(sb.value())
        anim.setEndValue(sb.maximum())
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_anim = anim  # 防回收
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def show_at(self) -> None:
        screen = QGuiApplication.primaryScreen().geometry()
        self.move(screen.right() - MINI_W - 40, screen.top() + (screen.height() - MINI_H) // 2)
        self.show()
        self.raise_()

    def _to_full(self) -> None:
        self.hide()
        self._win.show()
        self._win.raise_()
