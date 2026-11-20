"""全屏半透明遮罩 + 拖拽框选捕获区域（主屏）。返回物理像素坐标。"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QRubberBand, QWidget


class RegionPicker(QWidget):
    regionSelected = Signal(tuple)   # (left, top, right, bottom) 物理像素
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        screen = QApplication.primaryScreen()
        self._geometry = screen.geometry()
        self._dpr = screen.devicePixelRatio()
        self.setGeometry(self._geometry)
        self._origin: QPoint | None = None
        self._band = QRubberBand(QRubberBand.Rectangle, self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._band.setGeometry(QRect(self._origin, self._origin))
            self._band.show()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._band.setGeometry(QRect(self._origin, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event):
        if self._origin is None:
            return
        rect = self._band.geometry()
        self._band.hide()
        self._origin = None
        self.close()
        if rect.width() < 100 or rect.height() < 50:
            self.cancelled.emit()
            return
        tl = rect.topLeft()
        br = rect.bottomRight()
        g = self._geometry.topLeft()
        region = (
            int((g.x() + tl.x()) * self._dpr),
            int((g.y() + tl.y()) * self._dpr),
            int((g.x() + br.x()) * self._dpr),
            int((g.y() + br.y()) * self._dpr),
        )
        self.regionSelected.emit(region)
