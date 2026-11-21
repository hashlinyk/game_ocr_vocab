"""通用小部件：无边框窗口的右下角拖拽调整手柄。

无边框窗口没有 WS_THICKFRAME 样式，原生 QSizeGrip 在 Windows 上无效，
这里用自绘斜纹手柄 + 鼠标拖动手动改变窗口大小。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ResizeHandle(QWidget):
    SIZE = 22

    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.SizeFDiagCursor)
        self._press_pos = None
        self._start_size = None
        self.reposition()

    def reposition(self) -> None:
        w = self._win
        self.move(w.width() - self.SIZE - 3, w.height() - self.SIZE - 3)
        self.raise_()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
        w, h = self.width(), self.height()
        for off in (0, 6, 12):
            p.drawLine(w - 4 - off, h - 4, w - 4, h - 4 - off)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._start_size = self._win.size()

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._press_pos
        new_w = max(self._win.minimumWidth(), self._start_size.width() + delta.x())
        new_h = max(self._win.minimumHeight(), self._start_size.height() + delta.y())
        self._win.resize(new_w, new_h)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
