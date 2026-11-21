"""窗口枚举与窗口矩形获取（物理像素）。

DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) 返回不含阴影的真实窗口边界，
物理像素坐标（进程为 per-monitor DPI aware）。
"""

import ctypes
from ctypes import wintypes

DWMWA_EXTENDED_FRAME_BOUNDS = 9
GA_ROOT = 2


def _is_app_window(hwnd) -> bool:
    WS_EX_TOOLWINDOW = 0x80
    ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    return bool(ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) == hwnd)


def enum_app_windows(exclude_hwnd=None) -> list[tuple[int, str]]:
    """返回 [(hwnd, 标题)]：可见、有标题、非工具窗口的顶层窗口。"""
    result: list[tuple[int, str]] = []

    def cb(hwnd, _lparam):
        if exclude_hwnd and int(hwnd) == int(exclude_hwnd):
            return True
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        if not _is_app_window(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            result.append((int(hwnd), title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result


def get_window_physical_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """窗口物理边界 (left, top, right, bottom)；窗口不存在/最小化返回 None。"""
    if not ctypes.windll.user32.IsWindow(hwnd):
        return None
    if ctypes.windll.user32.IsIconic(hwnd):  # 最小化
        return None
    rect = wintypes.RECT()
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if hr != 0 or rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_window_valid(hwnd: int) -> bool:
    return bool(ctypes.windll.user32.IsWindow(hwnd))
