r"""多显示器全屏遮罩框选：每块屏幕一个遮罩，返回 dxcam output_idx 与物理像素区域。

Qt screen -> dxcam output 匹配规则：
1. screen.name() 形如 \\.\DISPLAYN 时，output_idx = N-1（Windows DISPLAY 编号与
   DXGI output 枚举顺序一致）。
2. friendly name（如显示器型号）时，用 Windows 枚举的物理分辨率
   (= Qt 逻辑分辨率 x 该屏 DPR) 匹配对应显示器，再取其 DISPLAY 编号。
"""

import ctypes
import re
from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QRubberBand, QWidget

MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def enum_monitors() -> list[tuple[str, tuple[int, int, int, int]]]:
    """返回 [(szDevice 如 '\\\\.\\DISPLAY1', 物理虚拟桌面坐标矩形)]。"""
    result: list[tuple[str, tuple[int, int, int, int]]] = []

    def cb(hmon, hdc, lprect, _lparam):
        r = lprect.contents
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            result.append((info.szDevice, (r.left, r.top, r.right, r.bottom)))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return result


def screen_to_output_idx(screen) -> int | None:
    """Qt screen -> dxcam output_idx；匹配失败返回 None（调用方回退主输出）。"""
    name = screen.name() or ""
    m = re.search(r"DISPLAY(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1)) - 1
    # friendly name（如显示器型号）：按物理分辨率匹配显示器
    g = screen.geometry()
    phys_w = round(g.width() * screen.devicePixelRatio())
    phys_h = round(g.height() * screen.devicePixelRatio())
    for device, rect in enum_monitors():
        if rect[2] - rect[0] == phys_w and rect[3] - rect[1] == phys_h:
            m = re.search(r"DISPLAY(\d+)", device, re.IGNORECASE)
            if m:
                return int(m.group(1)) - 1
    return None


class ScreenMask(QWidget):
    """单块屏幕的全屏遮罩。selectionDone(screen, 全局逻辑坐标选区)。"""

    selectionDone = Signal(object, QRect)
    cancelled = Signal()

    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self._origin: QPoint | None = None
        self._band = QRubberBand(QRubberBand.Rectangle, self)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._band.setGeometry(QRect(self._origin, self._origin))
            self._band.show()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._band.setGeometry(QRect(self._origin, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is None:
            return
        rect = self._band.geometry()
        self._band.hide()
        self._origin = None
        if rect.width() < 100 or rect.height() < 50:
            self.cancelled.emit()
            return
        screen_g = self.screen().geometry()
        tl = rect.topLeft()
        br = rect.bottomRight()
        global_rect = QRect(
            screen_g.topLeft() + tl, screen_g.topLeft() + br
        )  # 虚拟桌面全局逻辑坐标
        self.selectionDone.emit(self.screen(), global_rect)


class RegionPicker(QObject):
    """管理全部屏幕遮罩；regionSelected(output_idx, 物理区域四元组)。"""

    regionSelected = Signal(int, tuple)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._masks: list[ScreenMask] = []
        self._done = False
        for screen in QApplication.screens():
            mask = ScreenMask(screen)
            mask.selectionDone.connect(self._on_done)
            mask.cancelled.connect(self._on_cancel)
            self._masks.append(mask)

    def show(self) -> None:
        for mask in self._masks:
            mask.show()

    def close_all(self) -> None:
        for mask in self._masks:
            mask.close()
        self.deleteLater()

    def _on_done(self, screen, global_rect: QRect) -> None:
        if self._done:
            return
        self._done = True
        g = screen.geometry()
        dpr = screen.devicePixelRatio()
        rel = QRect(global_rect.topLeft() - g.topLeft(), global_rect.bottomRight() - g.topLeft())
        region = (
            int(rel.left() * dpr),
            int(rel.top() * dpr),
            int(rel.right() * dpr),
            int(rel.bottom() * dpr),
        )
        output_idx = screen_to_output_idx(screen)
        self.close_all()
        self.regionSelected.emit(
            output_idx if output_idx is not None else 0, region
        )

    def _on_cancel(self) -> None:
        if self._done:
            return
        self.close_all()
        self.cancelled.emit()
