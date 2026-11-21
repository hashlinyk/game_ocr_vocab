"""主窗口：三标签页（识别词流 / 已掌握 / 生词本）+ 区域控制 + 状态提示。"""

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dictionary import Dictionary, WordEntry

WORD_TRANS_SPACING = 10  # 单词行与释义行间距
VOCAB_PAGE = 10          # 词库懒加载每批行数

RUN_STATES = {
    "idle": ("未开始识别", "#999999"),
    "running": ("持续识别中", "#2e8b57"),
    "paused": ("已暂停", "#e67e22"),
}


def _flat_btn(style: QStyle, icon: QStyle.StandardPixmap, tooltip: str, close=False) -> QPushButton:
    b = QPushButton()
    b.setIcon(style.standardIcon(icon))
    b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(38, 30)
    hover = "background: #e81123; color: white;" if close else "background: rgba(0,0,0,14);"
    b.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; border-radius: 4px; }}"
        f"QPushButton:hover {{ {hover} }}"
    )
    return b


class TitleBar(QWidget):
    """自绘标题栏：置顶图钉按钮在系统按钮（最小化/最大化/关闭）左侧，支持拖拽移动窗口。"""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self._win = win
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(36)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 2, 0)
        lay.setSpacing(2)
        title = QLabel("游戏单词助手")
        title.setStyleSheet("font-size: 13px; color: #555;")
        lay.addWidget(title)
        lay.addStretch()

        self.pin_btn = QPushButton()
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFixedSize(38, 30)
        self.pin_btn.setToolTip("窗口置顶")
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setIcon(self._pin_icon(False))
        self.pin_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(0,0,0,14); }"
            "QPushButton:checked { background: rgba(26,115,232,40); }"
        )
        self.pin_btn.toggled.connect(self._toggle_pin)
        lay.addWidget(self.pin_btn)

        style = win.style()
        min_btn = _flat_btn(style, QStyle.StandardPixmap.SP_TitleBarMinButton, "最小化")
        min_btn.clicked.connect(win.showMinimized)
        lay.addWidget(min_btn)
        self.max_btn = _flat_btn(style, QStyle.StandardPixmap.SP_TitleBarMaxButton, "最大化")
        self.max_btn.clicked.connect(self._toggle_max)
        lay.addWidget(self.max_btn)
        close_btn = _flat_btn(style, QStyle.StandardPixmap.SP_TitleBarCloseButton, "关闭", close=True)
        close_btn.clicked.connect(win.close)
        lay.addWidget(close_btn)

    def _pin_icon(self, active: bool) -> QPixmap:
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor("#1a73e8") if active else QColor("#9a9a9a")
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRect(10, 3, 12, 12))       # 钉头
        p.setPen(QPen(c, 2.5))
        p.drawLine(16, 15, 16, 24)                # 针杆
        p.drawLine(11, 27, 21, 27)                # 针脚
        p.end()
        return QPixmap(pm)

    def _toggle_pin(self, checked: bool) -> None:
        self.pin_btn.setIcon(self._pin_icon(checked))
        self._win.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self._win.show()

    def _toggle_max(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self._win.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event) -> None:
        self._toggle_max()


class _RowBase(QWidget):
    """识别行/词库行公共基类：按释义标签实际宽度精确计算行高。"""

    def preferred_height(self) -> int:
        m = self.layout().contentsMargins()
        h = m.top() + m.bottom() + self.word_label.sizeHint().height() + WORD_TRANS_SPACING
        tl = self.trans_label
        if tl.width() > 0:
            h += tl.heightForWidth(tl.width())
        return max(h, 48)


class WordRow(_RowBase):
    """识别词流行。"""

    def __init__(self, entry: WordEntry, in_vocab: bool, on_mastered, on_vocab, on_hide, on_speak):
        super().__init__()
        self.canonical = entry.canonical
        self.in_vocab = in_vocab
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        left = QVBoxLayout()
        left.setSpacing(WORD_TRANS_SPACING)
        top = QHBoxLayout()
        self.word_label = QLabel(entry.word)
        self.word_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        top.addWidget(self.word_label)
        if in_vocab:
            tag = QLabel("生")
            tag.setFixedWidth(20)
            tag.setAlignment(Qt.AlignCenter)
            tag.setToolTip("该词在生词本中")
            tag.setStyleSheet(
                "background: #e67e22; color: white; border-radius: 4px;"
                "font-size: 11px; font-weight: bold;"
            )
            top.addWidget(tag)
        pho = QLabel(entry.phonetic)
        pho.setStyleSheet("color: #888888; font-size: 13px;")
        top.addWidget(pho)
        top.addStretch()
        left.addLayout(top)
        # 发音：喇叭小按钮紧贴音标（插在 stretch 之前，避免被推到最右）
        speak_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume), "")
        speak_btn.setFixedSize(26, 26)
        speak_btn.setToolTip(f"发音 {entry.word}")
        speak_btn.setCursor(Qt.PointingHandCursor)
        speak_btn.clicked.connect(lambda _=False: on_speak(entry.canonical))
        top.insertWidget(top.count() - 1, speak_btn)
        self.trans_label = QLabel(entry.translation)
        self.trans_label.setWordWrap(True)
        self.trans_label.setToolTip(entry.translation_full)
        self.trans_label.setStyleSheet("color: #1a1a1a; font-size: 14px;")
        left.addWidget(self.trans_label)
        layout.addLayout(left, 1)

        # 右侧按钮固定贴顶：与单词首行对齐，不随释义行数垂直居中
        btn_box = QWidget()
        btn_lay = QHBoxLayout(btn_box)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)
        # 第二按钮：生词显示「隐藏」（仅本次隐藏），普通词显示「生词本」；宽度统一
        if in_vocab:
            second = ("隐藏", on_hide, "仅从本次列表隐藏，下次出现会再次显示")
        else:
            second = ("生词本", on_vocab, "加入生词本")
        second_btn = QPushButton(second[0])
        second_btn.setFixedWidth(64)
        second_btn.setToolTip(second[2])
        second_btn.setCursor(Qt.PointingHandCursor)
        second_btn.clicked.connect(lambda _=False, c=entry.canonical, f=second[1]: f(c))
        btn_lay.addWidget(second_btn)
        layout.addWidget(btn_box, 0, Qt.AlignTop)


class VocabRow(_RowBase):
    """词库行：排版与识别行一致（单词+音标+喇叭 / 释义多行 / 右侧互移、移除）。"""

    def __init__(self, entry: WordEntry, move_label, on_move, on_remove, on_speak):
        super().__init__()
        self.canonical = entry.canonical
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        left = QVBoxLayout()
        left.setSpacing(WORD_TRANS_SPACING)
        top = QHBoxLayout()
        self.word_label = QLabel(entry.word)
        self.word_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        pho = QLabel(entry.phonetic)
        pho.setStyleSheet("color: #888888; font-size: 13px;")
        top.addWidget(self.word_label)
        top.addWidget(pho)
        speak_btn = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume), "")
        speak_btn.setFixedSize(26, 26)
        speak_btn.setToolTip(f"发音 {entry.word}")
        speak_btn.setCursor(Qt.PointingHandCursor)
        speak_btn.clicked.connect(lambda _=False: on_speak(entry.word))
        top.addWidget(speak_btn)
        top.addStretch()
        left.addLayout(top)
        self.trans_label = QLabel(entry.translation)
        self.trans_label.setWordWrap(True)
        self.trans_label.setToolTip(entry.translation_full)
        self.trans_label.setStyleSheet("color: #555555; font-size: 14px;")
        left.addWidget(self.trans_label)
        layout.addLayout(left, 1)

        btn_box = QWidget()
        btn_lay = QHBoxLayout(btn_box)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)
        mv = QPushButton(f"→{move_label}")
        mv.clicked.connect(lambda _=False: on_move(entry.word))
        rm = QPushButton("移除")
        rm.clicked.connect(lambda _=False: on_remove(entry.word))
        for b in (mv, rm):
            b.setCursor(Qt.PointingHandCursor)
            btn_lay.addWidget(b)
        layout.addWidget(btn_box, 0, Qt.AlignTop)


class WindowPickerDialog(QDialog):
    """选择要识别的目标窗口。"""

    windowPicked = Signal(int, str)   # (hwnd, title)

    def __init__(self, exclude_hwnd=None):
        super().__init__()
        from .window_pick import enum_app_windows

        self.setWindowTitle("选择目标窗口")
        self.resize(520, 520)
        vbox = QVBoxLayout(self)
        hint = QLabel("双击列表中的窗口开始识别；目标窗口移动/缩放会自动跟随")
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        vbox.addWidget(hint)
        self.listw = QListWidget()
        self.listw.setWordWrap(True)
        self.listw.itemDoubleClicked.connect(self._on_double)
        vbox.addWidget(self.listw, 1)
        bottom = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(lambda: self._fill())
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(refresh_btn)
        bottom.addStretch()
        bottom.addWidget(cancel_btn)
        vbox.addLayout(bottom)
        self._entries = []
        self._fill(exclude_hwnd)

    def _fill(self, exclude_hwnd=None) -> None:
        from .window_pick import enum_app_windows

        self.listw.clear()
        self._entries = enum_app_windows(exclude_hwnd)
        for hwnd, title in self._entries:
            self.listw.addItem(f"{title}")

    def _on_double(self, item) -> None:
        idx = self.listw.row(item)
        if 0 <= idx < len(self._entries):
            hwnd, title = self._entries[idx]
            self.windowPicked.emit(hwnd, title)
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self, store, tts, on_region_selected, dict_ref: Dictionary, on_toggle_pause=None, on_pick_window=None):
        super().__init__()
        self.store = store
        self.tts = tts
        self.dict = dict_ref
        self._on_region_selected = on_region_selected
        self._on_toggle_pause = on_toggle_pause
        self._on_pick_window = on_pick_window
        self._new_words = 0
        self._vocab_dirty = {"mastered", "vocab"}  # 词库数据变化标记，切入 tab 时才刷新
        self._vocab_pages = {}                     # status -> 全量词表（懒加载分批渲染）
        self.setWindowTitle("游戏单词助手")
        self.setWindowFlag(Qt.FramelessWindowHint)
        screen_w = self.screen().availableGeometry().width()
        self.resize(int(screen_w * 0.7), 640)

        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        self.titlebar = TitleBar(self)
        vbox.addWidget(self.titlebar)

        inner = QVBoxLayout()
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(8)
        top = QHBoxLayout()
        win_btn = QPushButton("选择窗口")
        win_btn.setToolTip("选定目标窗口，窗口移动/缩放自动跟随（优先推荐）")
        win_btn.clicked.connect(self._pick_window)
        pick_btn = QPushButton("框选识别区域")
        pick_btn.setToolTip("全屏遮罩拖拽框出固定区域")
        pick_btn.clicked.connect(self._pick_region)
        self.state_label = QLabel("未开始识别")
        self.state_label.setStyleSheet("color: #999999; font-weight: bold;")
        self.pause_btn = QPushButton("暂停识别")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.region_label = QLabel("未选择区域")
        self.region_label.setStyleSheet("color: gray;")
        self.count_label = QLabel("")
        self._update_counts()
        top.addWidget(win_btn)
        top.addWidget(pick_btn)
        top.addWidget(self.state_label)
        top.addWidget(self.pause_btn)
        top.addWidget(self.region_label, 1)
        top.addWidget(self.count_label)
        inner.addLayout(top)
        vbox.addLayout(inner)
        QSizeGrip(self)  # 无边框窗口右下角拖拽调整大小

        # debug 帧清理：主线程定时执行（捕获线程只写帧，避免并发删除竞争）
        cleanup_timer = QTimer(self)
        cleanup_timer.timeout.connect(self._cleanup_debug_frames)
        cleanup_timer.start(60_000)
        QTimer.singleShot(5_000, self._cleanup_debug_frames)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_stream_tab(), "识别")
        self.tabs.addTab(self._build_vocab_tab("mastered"), "已掌握")
        self.tabs.addTab(self._build_vocab_tab("vocab"), "生词本")
        self.tabs.currentChanged.connect(lambda _i: self._on_tab_changed())
        inner.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("点击「框选区域」选择要监视的屏幕区域（Esc 取消）")

    def set_run_state(self, state: str) -> None:
        text, color = RUN_STATES.get(state, RUN_STATES["idle"])
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.pause_btn.setText("继续识别" if state == "paused" else "暂停识别")
        self.pause_btn.setEnabled(state != "idle")

    def _cleanup_debug_frames(self) -> None:
        from . import config

        if not config.DEBUG_SAVE_FRAMES:
            return
        frames = sorted(config.DEBUG_DIR.glob("t*.png"))
        for old in frames[: max(0, len(frames) - config.DEBUG_KEEP)]:
            try:
                old.unlink()
            except OSError:
                pass

    def _pick_window(self) -> None:
        dlg = WindowPickerDialog(exclude_hwnd=int(self.winId()))
        dlg.windowPicked.connect(self._on_window_picked)
        dlg.exec()

    def _on_window_picked(self, hwnd: int, title: str) -> None:
        self._on_pick_window(hwnd, title)

    def set_window_text(self, title: str) -> None:
        self.region_label.setText(f"窗口: {title}")

    def set_pinned(self, checked: bool) -> None:
        self.titlebar.pin_btn.setChecked(checked)

    def _toggle_pause(self) -> None:
        if self._on_toggle_pause is None:
            return
        paused = self.pause_btn.text() == "暂停识别"
        self._on_toggle_pause(paused)

    # ---- 识别 tab ----
    def _build_stream_tab(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        tools = QHBoxLayout()
        tools.addStretch()
        clear_btn = QPushButton("清空列表")
        clear_btn.clicked.connect(self._clear_list)
        master_btn = QPushButton("全部掌握")
        master_btn.clicked.connect(lambda: self._mark_all_mastered(include_vocab=True))
        master_nv_btn = QPushButton("全部掌握（不含生词）")
        master_nv_btn.setToolTip("只把不在生词本中的词加入已掌握，生词保留在列表")
        master_nv_btn.clicked.connect(lambda: self._mark_all_mastered(include_vocab=False))
        for b in (clear_btn, master_btn, master_nv_btn):
            b.setCursor(Qt.PointingHandCursor)
            tools.addWidget(b)
        vbox.addLayout(tools)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setWordWrap(True)
        vbox.addWidget(self.list, 1)
        return page

    # ---- 词库 tab ----
    def _build_vocab_tab(self, status: str) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        tools = QHBoxLayout()
        tools.addStretch()
        clear_btn = QPushButton("清空本页")
        clear_btn.clicked.connect(lambda: self._clear_vocab_page(status))
        tools.addWidget(clear_btn)
        vbox.addLayout(tools)

        lw = QListWidget()
        lw.setSelectionMode(QListWidget.NoSelection)
        lw.setWordWrap(True)
        lw.verticalScrollBar().valueChanged.connect(
            lambda _v, lw=lw, status=status: self._maybe_load_more(lw, status)
        )
        vbox.addWidget(lw, 1)
        if status == "mastered":
            self.list_m = lw
        else:
            self.list_v = lw
        return page

    def _on_tab_changed(self) -> None:
        idx = self.tabs.currentIndex()
        if idx == 0:
            self._new_words = 0
            self.tabs.setTabText(0, "识别")
            QTimer.singleShot(0, lambda: self._fit_heights(self.list))
        elif idx == 1:
            if "mastered" in self._vocab_dirty:
                self._refresh_vocab("mastered")
        elif idx == 2:
            if "vocab" in self._vocab_dirty:
                self._refresh_vocab("vocab")

    def _fit_heights(self, lw: QListWidget, start: int = 0) -> None:
        """按释义标签实际宽度精确计算行高：同行数=同高度，多行=更高。

        wordWrap QLabel 的 sizeHint 高度随内容长度抖动，不能用；布局完成后
        label 已有真实宽度，heightForWidth(width) 对相同行数给出相同高度。
        """
        if lw.count() == 0 or lw.viewport().width() <= 0:
            return
        for i in range(max(start, 0), lw.count()):
            row = lw.itemWidget(lw.item(i))
            if row is None or getattr(row, "trans_label", None) is None:
                continue
            lw.item(i).setSizeHint(QSize(10, row.preferred_height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        idx = self.tabs.currentIndex()
        lw = self.list if idx == 0 else (self.list_m if idx == 1 else self.list_v)
        QTimer.singleShot(0, lambda: self._fit_heights(lw))

    # ---- 识别流 ----
    def add_entries(self, entries: list) -> None:
        for entry in entries:
            in_vocab = self.store.is_vocab(entry.canonical)
            row = WordRow(
                entry,
                in_vocab,
                on_mastered=self._mark(entry.canonical, "mastered"),
                on_vocab=self._mark(entry.canonical, "vocab"),
                on_hide=self._hide_stream_word,
                on_speak=self.tts.speak,
            )
            item = QListWidgetItem()
            item.setSizeHint(QSize(10, row.preferred_height()))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self.list.scrollToBottom()
        QTimer.singleShot(0, lambda: self._fit_heights(self.list))
        if self.tabs.currentIndex() != 0:
            self._new_words += len(entries)
            self.tabs.setTabText(0, f"识别 ({self._new_words})")

    def _mark(self, canonical: str, status: str):
        def handler(canonical: str) -> None:
            self.store.set_status(canonical, status)
            self.remove_word(canonical)
            self._update_counts()
        return handler

    def _hide_stream_word(self, canonical: str) -> None:
        """识别页隐藏：仅从列表移除并清除本会话记录，不改任何状态（只生效一次）。"""
        self.store.reset_shown_word(canonical)
        self.remove_word(canonical)

    def remove_word(self, canonical: str) -> None:
        for i in range(self.list.count()):
            row = self.list.itemWidget(self.list.item(i))
            if isinstance(row, WordRow) and row.canonical == canonical:
                self.list.takeItem(i)
                break

    def _clear_list(self) -> None:
        self.list.clear()
        self.store.reset_shown()

    def _mark_all_mastered(self, include_vocab: bool = True) -> None:
        n = 0
        removed_rows = []
        for i in range(self.list.count()):
            row = self.list.itemWidget(self.list.item(i))
            if not isinstance(row, WordRow):
                continue
            if not include_vocab and row.in_vocab:
                continue  # 生词保留在列表
            self.store.set_status(row.canonical, "mastered")
            removed_rows.append(i)
            n += 1
        for i in reversed(removed_rows):
            self.list.takeItem(i)
        self._update_counts()
        msg = f"已将 {n} 个词加入已掌握"
        if not include_vocab:
            msg += "（生词已保留）"
        self.statusBar().showMessage(msg, 5000)

    # ---- 词库 ----
    def _refresh_vocab(self, status: str) -> None:
        """懒加载渲染：只渲染第一批，滚动接近底部时续载。词库按字母序。"""
        lw = self.list_m if status == "mastered" else self.list_v
        self._vocab_pages[status] = sorted(self.store.words_of(status), key=lambda wt: wt[0])
        lw.setUpdatesEnabled(False)
        lw.clear()
        lw.setUpdatesEnabled(True)
        self._vocab_dirty.discard(status)
        self._vocab_fill_batch(lw, status, 0, VOCAB_PAGE)

    def _vocab_fill_batch(self, lw: QListWidget, status: str, start: int, count: int) -> None:
        words = self._vocab_pages.get(status, [])
        end = min(start + count, len(words))
        if start >= end:
            return
        other = "生词本" if status == "mastered" else "已掌握"
        lw.setUpdatesEnabled(False)
        for word, _ts in words[start:end]:
            entry = self.dict.lookup(word) or WordEntry(word, word, "", "（词典中未收录）", "")
            row = VocabRow(
                entry,
                other,
                on_move=self._move_word,
                on_remove=self._remove_word,
                on_speak=self.tts.speak,
            )
            item = QListWidgetItem()
            item.setSizeHint(QSize(10, row.preferred_height()))
            lw.addItem(item)
            lw.setItemWidget(item, row)
        lw.setUpdatesEnabled(True)
        QTimer.singleShot(0, lambda: self._fit_heights(lw, start))

    def _maybe_load_more(self, lw: QListWidget, status: str) -> None:
        sb = lw.verticalScrollBar()
        if sb.maximum() <= 0 or sb.value() < sb.maximum() - 60:
            return
        total = len(self._vocab_pages.get(status, []))
        if lw.count() >= total:
            return
        self._vocab_fill_batch(lw, status, lw.count(), VOCAB_PAGE)

    def _vocab_row_take(self, lw: QListWidget, word: str) -> None:
        for i in range(lw.count()):
            row = lw.itemWidget(lw.item(i))
            if isinstance(row, VocabRow) and row.canonical == word:
                lw.takeItem(i)
                return

    def _move_word(self, word: str) -> None:
        status = self.store.status_of(word)
        target = "vocab" if status == "mastered" else "mastered"
        self.store.set_status(word, target)
        lw = self.list_m if status == "mastered" else self.list_v
        self._vocab_row_take(lw, word)          # 仅移除当前行，另一 tab 标脏延迟刷新
        pages = self._vocab_pages.get(status)
        if pages is not None:
            self._vocab_pages[status] = [(w, t) for w, t in pages if w != word]
        self._vocab_dirty = {"mastered", "vocab"}
        self._update_counts()

    def _remove_word(self, word: str) -> None:
        self.store.remove_status(word)
        self._vocab_row_take(self.list_m, word)
        self._vocab_row_take(self.list_v, word)
        for status in ("mastered", "vocab"):
            pages = self._vocab_pages.get(status)
            if pages is not None:
                self._vocab_pages[status] = [(w, t) for w, t in pages if w != word]
        self._vocab_dirty = {"mastered", "vocab"}
        self._update_counts()

    def _clear_vocab_page(self, status: str) -> None:
        label = "已掌握" if status == "mastered" else "生词本"
        ret = QMessageBox.question(
            self, "确认清空",
            f"将清空「{label}」中的全部单词（不可恢复），这些单词再次出现在画面中会重新被识别追加。确定吗？",
        )
        if ret != QMessageBox.Yes:
            return
        for word, _ts in self.store.words_of(status):
            self.store.remove_status(word)
        self._refresh_vocab(status)
        self._update_counts()

    # ---- 通用 ----
    def _pick_region(self) -> None:
        from .region_picker import RegionPicker

        self._picker = RegionPicker()
        self._picker.regionSelected.connect(self._on_region_picked)
        self._picker.cancelled.connect(self._on_region_cancelled)
        self.hide()  # 主窗口临时隐藏，避免遮挡待框选区域
        self._picker.show()

    def _on_region_picked(self, output_idx: int, region: tuple) -> None:
        self.show()
        self.raise_()
        self._on_region_selected(output_idx, region)

    def _on_region_cancelled(self) -> None:
        self.show()
        self.raise_()

    def _update_counts(self) -> None:
        m, v = self.store.counts()
        self.count_label.setText(f"已掌握 {m} | 生词本 {v}")

    def set_region_text(self, region: tuple) -> None:
        l, t, r, b = region
        self.region_label.setText(f"区域 ({l},{t})-({r},{b})  {r - l}x{b - t}")
        self.statusBar().showMessage(f"已开始监视区域 {region}", 5000)

    def show_error(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 10000)
