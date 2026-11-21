"""窗口位置/大小持久化：data/ui_state.json（与热键配置分文件，互不覆盖）。"""

import json

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

from . import config

PATH = config.DATA_DIR / "ui_state.json"


def _load() -> dict:
    try:
        if PATH.exists():
            return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def save_geometry(key: str, widget) -> None:
    g = widget.geometry()
    data = _load()
    data[key] = [g.x(), g.y(), g.width(), g.height()]
    _save(data)


def restore_geometry(key: str, widget) -> bool:
    """恢复保存的几何；无记录或已不在任何屏幕范围内时返回 False 保持现状。"""
    data = _load()
    geo = data.get(key)
    if not geo or len(geo) != 4:
        return False
    rect = QRect(*geo)
    visible = any(
        screen.availableGeometry().intersects(rect)
        for screen in QGuiApplication.screens()
    )
    if not visible:
        return False
    widget.setGeometry(rect)
    return True
