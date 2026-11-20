"""主窗口：三标签页（识别词流 / 已掌握 / 生词本）+ 区域控制 + 状态提示。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dictionary import Dictionary, WordEntry


class WordRow(QWidget):
    """识别词流行。"""

    def __init__(self, entry: WordEntry, on_mastered, on_vocab, on_speak):
        super().__init__()
        self.canonical = entry.canonical
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        left = QVBoxLayout()
        top = QHBoxLayout()
        word_label = QLabel(entry.word)
        word_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        pho = QLabel(entry.phonetic)
        pho.setStyleSheet("color: #888888; font-size: 13px;")
        top.addWidget(word_label)
        top.addWidget(pho)
        top.addStretch()
        left.addLayout(top)
        trans = QLabel(entry.translation)
        trans.setWordWrap(True)
        trans.setToolTip(entry.translation_full)
        trans.setStyleSheet("color: #1a1a1a; font-size: 14px;")
        left.addWidget(trans)
        layout.addLayout(left, 1)

        # 按钮固定贴顶：与单词首行对齐，不随释义行数垂直居中
        btn_box = QWidget()
        btn_lay = QHBoxLayout(btn_box)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)
        for text, cb in (("掌握", on_mastered), ("生词本", on_vocab), ("发音", on_speak)):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=entry.canonical, f=cb: f(c))
            btn_lay.addWidget(btn)
        layout.addWidget(btn_box, 0, Qt.AlignTop)


class VocabRow(QWidget):
    """词库行：单词 / 释义 / 互移 / 移除。"""

    def __init__(self, word, translation, move_label, on_move, on_remove):
        super().__init__()
        self.canonical = word
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        wl = QLabel(word)
        wl.setStyleSheet("font-weight: bold; font-size: 18px;")
        tl = QLabel(translation)
        tl.setStyleSheet("color: #555555; font-size: 14px;")
        tl.setWordWrap(True)
        tl.setToolTip(translation)
        layout.addWidget(wl)
        layout.addWidget(tl, 1)
        btn_box = QWidget()
        btn_lay = QHBoxLayout(btn_box)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(6)
        mv = QPushButton(f"→{move_label}")
        mv.clicked.connect(lambda _=False: on_move(word))
        rm = QPushButton("移除")
        rm.clicked.connect(lambda _=False: on_remove(word))
        for b in (mv, rm):
            b.setCursor(Qt.PointingHandCursor)
            btn_lay.addWidget(b)
        layout.addWidget(btn_box, 0, Qt.AlignTop)


class MainWindow(QMainWindow):
    def __init__(self, store, tts, on_region_selected, dict_ref: Dictionary):
        super().__init__()
        self.store = store
        self.tts = tts
        self.dict = dict_ref
        self._on_region_selected = on_region_selected
        self._new_words = 0
        self.setWindowTitle("游戏单词助手")
        screen_w = self.screen().availableGeometry().width()
        self.resize(int(screen_w * 0.7), 640)

        central = QWidget()
        vbox = QVBoxLayout(central)
        top = QHBoxLayout()
        pick_btn = QPushButton("框选区域")
        pick_btn.clicked.connect(self._pick_region)
        self.region_label = QLabel("未选择区域")
        self.region_label.setStyleSheet("color: gray;")
        self.count_label = QLabel("")
        self._update_counts()
        self.top_btn = QPushButton("置顶")
        self.top_btn.setCheckable(True)
        self.top_btn.setToolTip("勾选后窗口始终显示在其他窗口之上")
        self.top_btn.toggled.connect(self._toggle_on_top)
        top.addWidget(pick_btn)
        top.addWidget(self.region_label, 1)
        top.addWidget(self.count_label)
        top.addWidget(self.top_btn)
        vbox.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_stream_tab(), "识别")
        self.tabs.addTab(self._build_vocab_tab("mastered"), "已掌握")
        self.tabs.addTab(self._build_vocab_tab("vocab"), "生词本")
        self.tabs.currentChanged.connect(lambda _i: self._on_tab_changed())
        vbox.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("点击「框选区域」选择要监视的屏幕区域（Esc 取消）")

    # ---- 识别 tab ----
    def _build_stream_tab(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        tools = QHBoxLayout()
        tools.addStretch()
        clear_btn = QPushButton("清空列表")
        clear_btn.clicked.connect(self._clear_list)
        master_btn = QPushButton("全部掌握")
        master_btn.clicked.connect(self._mark_all_mastered)
        for b in (clear_btn, master_btn):
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
        elif idx == 1:
            self._refresh_vocab("mastered")
        elif idx == 2:
            self._refresh_vocab("vocab")

    # ---- 识别流 ----
    def add_entries(self, entries: list) -> None:
        for entry in entries:
            row = WordRow(
                entry,
                on_mastered=self._mark(entry.canonical, "mastered"),
                on_vocab=self._mark(entry.canonical, "vocab"),
                on_speak=self.tts.speak,
            )
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self.list.scrollToBottom()
        if self.tabs.currentIndex() != 0:
            self._new_words += len(entries)
            self.tabs.setTabText(0, f"识别 ({self._new_words})")

    def _mark(self, canonical: str, status: str):
        def handler(canonical: str) -> None:
            self.store.set_status(canonical, status)
            self.remove_word(canonical)
            self._update_counts()
        return handler

    def remove_word(self, canonical: str) -> None:
        for i in range(self.list.count()):
            row = self.list.itemWidget(self.list.item(i))
            if isinstance(row, WordRow) and row.canonical == canonical:
                self.list.takeItem(i)
                break

    def _clear_list(self) -> None:
        self.list.clear()
        self.store.reset_shown()

    def _mark_all_mastered(self) -> None:
        n = 0
        for i in range(self.list.count()):
            row = self.list.itemWidget(self.list.item(i))
            if isinstance(row, WordRow):
                self.store.set_status(row.canonical, "mastered")
                n += 1
        self.list.clear()
        self._update_counts()
        self.statusBar().showMessage(f"已将 {n} 个词加入已掌握", 5000)

    # ---- 词库 ----
    def _refresh_vocab(self, status: str) -> None:
        lw = self.list_m if status == "mastered" else self.list_v
        lw.clear()
        other = "生词本" if status == "mastered" else "已掌握"
        for word, _ts in self.store.words_of(status):
            entry = self.dict.lookup(word)
            row = VocabRow(
                word,
                entry.translation if entry else "",
                other,
                on_move=self._move_word,
                on_remove=self._remove_word,
            )
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            lw.addItem(item)
            lw.setItemWidget(item, row)

    def _move_word(self, word: str) -> None:
        status = self.store.status_of(word)
        target = "vocab" if status == "mastered" else "mastered"
        self.store.set_status(word, target)
        self._refresh_vocab("mastered")
        self._refresh_vocab("vocab")
        self._update_counts()

    def _remove_word(self, word: str) -> None:
        self.store.remove_status(word)
        self._refresh_vocab("mastered")
        self._refresh_vocab("vocab")
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
    def _toggle_on_top(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def _pick_region(self) -> None:
        from .region_picker import RegionPicker

        self._picker = RegionPicker()
        self._picker.setAttribute(Qt.WA_DeleteOnClose)
        self._picker.regionSelected.connect(self._on_region_selected)
        self._picker.showFullScreen()
        self._picker.raise_()
        self._picker.activateWindow()

    def _update_counts(self) -> None:
        m, v = self.store.counts()
        self.count_label.setText(f"已掌握 {m} | 生词本 {v}")

    def set_region_text(self, region: tuple) -> None:
        l, t, r, b = region
        self.region_label.setText(f"区域 ({l},{t})-({r},{b})  {r - l}x{b - t}")
        self.statusBar().showMessage(f"已开始监视区域 {region}", 5000)

    def show_error(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 10000)
