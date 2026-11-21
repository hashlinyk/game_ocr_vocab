"""全局热键管理：Win32 RegisterHotKey + Qt nativeEventFilter，支持运行时重绑定与持久化。"""

import ctypes
import json
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

MOD_NAMES = {MOD_CONTROL: "Ctrl", MOD_ALT: "Alt", MOD_SHIFT: "Shift"}


class _MultiHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callbacks: dict):
        super().__init__()
        self._cbs = callbacks

    def nativeEventFilter(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY:
            cb = self._cbs.get(int(msg.wParam))
            if cb is not None:
                cb()
        return False, 0


class HotkeyManager:
    """以 slug 管理热键：define 注册、rebind 动态换绑（失败自动回滚）、持久化到 json。"""

    def __init__(self, app, settings_path: Path):
        self._app = app
        self._path = Path(settings_path)
        self._cbs: dict[int, callable] = {}
        self._defs: dict[str, tuple] = {}      # slug -> (hid, display, default_mods, default_vk, cb)
        self._binding: dict[str, tuple] = {}   # slug -> (mods, vk) 当前生效
        self._next_id = 0x9A40
        self._filter = _MultiHotkeyFilter(self._cbs)
        app.installNativeEventFilter(self._filter)
        self._saved: dict[str, list] = {}
        try:
            if self._path.exists():
                self._saved = json.loads(self._path.read_text(encoding="utf-8")).get("hotkeys", {})
        except Exception:
            self._saved = {}

    def _register(self, hid: int, mods: int, vk: int, cb) -> bool:
        ok = ctypes.windll.user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
        if ok:
            self._cbs[hid] = cb
        return bool(ok)

    def _unregister(self, hid: int) -> None:
        try:
            ctypes.windll.user32.UnregisterHotKey(None, hid)
        except Exception:
            pass
        self._cbs.pop(hid, None)

    def define(self, slug: str, display: str, default_mods: int, default_vk: int, cb) -> bool:
        hid = self._next_id
        self._next_id += 1
        self._defs[slug] = (hid, display, default_mods, default_vk, cb)
        mods, vk = self._saved.get(slug, [default_mods, default_vk])
        if self._register(hid, mods, vk, cb):
            self._binding[slug] = (mods, vk)
            return True
        if self._register(hid, default_mods, default_vk, cb):
            self._binding[slug] = (default_mods, default_vk)
            return False  # 用自定义失败、回退默认
        self._binding[slug] = (mods, vk)
        return False

    def rebind(self, slug: str, mods: int, vk: int, register: bool = True) -> bool:
        """换绑并持久化。register=False 时只保存配置不注册（设置窗口 suspend 期间用）。"""
        if slug not in self._defs:
            return False
        hid, _display, _dm, _dv, cb = self._defs[slug]
        if not register:
            self._binding[slug] = (mods, vk)
            self._saved[slug] = [mods, vk]
            self._save()
            return True
        old = self._binding.get(slug)
        self._unregister(hid)
        if self._register(hid, mods, vk, cb):
            self._binding[slug] = (mods, vk)
            self._saved[slug] = [mods, vk]
            self._save()
            return True
        if old is not None:
            if self._register(hid, old[0], old[1], cb):
                self._binding[slug] = old
        return False

    def suspend(self) -> None:
        """临时注销全部热键（设置窗口录制按键期间，避免组合被全局热键抢占）。"""
        for slug, d in self._defs.items():
            self._unregister(d[0])

    def resume(self) -> list[str]:
        """按当前配置重新注册全部热键；返回注册失败的「功能名（组合）」列表。"""
        failed = []
        for slug, (hid, display, dm, dv, cb) in self._defs.items():
            self._unregister(hid)
            mods, vk = self._saved.get(slug, [dm, dv])
            if self._register(hid, mods, vk, cb):
                self._binding[slug] = (mods, vk)
                continue
            if self._register(hid, dm, dv, cb):
                self._binding[slug] = (dm, dv)
                self._saved[slug] = [dm, dv]
                self._save()
                failed.append(f"{display}（{format_hotkey(mods, vk)} 被占用，已回退默认）")
            else:
                failed.append(f"{display}（{format_hotkey(mods, vk)} 与默认均不可用）")
        return failed

    def bindings(self) -> dict[str, tuple[str, int, int]]:
        """slug -> (功能名, mods, vk)。"""
        return {
            slug: (d[1], *self._binding.get(slug, (d[2], d[3])))
            for slug, d in self._defs.items()
        }

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"hotkeys": self._saved}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def shutdown(self) -> None:
        for slug in self._defs:
            self._unregister(self._defs[slug][0])


def format_hotkey(mods: int, vk: int) -> str:
    parts = [name for bit, name in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift")) if mods & bit]
    if 0x30 <= vk <= 0x5A:
        parts.append(chr(vk))
    elif 0x70 <= vk <= 0x87:
        parts.append(f"F{vk - 0x6F}")
    else:
        parts.append(f"VK{vk}")
    return "+".join(parts)
