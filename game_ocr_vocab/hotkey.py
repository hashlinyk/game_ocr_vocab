"""全局热键（Win32 RegisterHotKey + Qt nativeEventFilter），窗口失焦也可触发。"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback):
        super().__init__()
        self._id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
            self._callback()
        return False, 0


def install_hotkey(app, hotkey_id: int, modifiers: int, vk: int, callback) -> bool:
    """注册全局热键；返回是否注册成功（被其他程序占用时失败）。"""
    ok = ctypes.windll.user32.RegisterHotKey(
        None, hotkey_id, modifiers | MOD_NOREPEAT, vk
    )
    if ok:
        flt = _HotkeyFilter(hotkey_id, callback)
        app.installNativeEventFilter(flt)
        app._hotkey_filter = flt  # 防回收
    return bool(ok)


def uninstall_hotkey(hotkey_id: int) -> None:
    ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
