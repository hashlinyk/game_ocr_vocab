"""入口：装配捕获/OCR/UI 三线程 + 前置检查。运行: python -m game_ocr_vocab"""

import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox


def check_prereqs() -> str | None:
    from . import config

    if not config.DICT_DB.exists():
        return "词典缺失，请先运行: python scripts/prepare_dict.py"
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("rapidocr")
    if spec is None:
        return "rapidocr 未安装"
    models = Path(spec.origin).parent / "models"
    if not any(models.glob("*.onnx")):
        return "OCR 模型缺失，请先运行: python scripts/prepare_ocr_models.py"
    return None


def main() -> int:
    from PySide6.QtGui import QFont

    from .main_window import THEME_QSS

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(THEME_QSS)

    err = check_prereqs()
    if err:
        QMessageBox.critical(None, "游戏单词助手", err)
        return 1

    from . import config
    from .capture import CaptureWorker, FrameSource
    from .dictionary import Dictionary
    from .ocr_worker import OcrWorker
    from .store import WordStore
    from .tts import TtsSpeaker
    from .main_window import MainWindow

    source = FrameSource()
    store = WordStore()
    tts = TtsSpeaker()

    capture_worker = CaptureWorker(source)
    capture_thread = _start_thread(capture_worker)

    ocr_worker = OcrWorker(source, store)
    ocr_thread = _start_thread(ocr_worker)

    pending: dict = {"kind": None, "arg": None}
    run_state: dict = {"value": "idle"}  # idle / running / paused

    def start_capture() -> None:
        if pending["kind"] is None:
            return
        ocr_worker.reset_snap()
        capture_worker.set_paused(False)
        if pending["kind"] == "region":
            capture_worker.set_region(*pending["arg"])
        else:
            capture_worker.set_window(pending["arg"])
        run_state["value"] = "running"
        win.set_run_state("running")

    def on_region_selected(output_idx: int, region: tuple) -> None:
        """框选完成：识别中直接切到新区域；未开始则等待点击『开始识别』。"""
        pending["kind"] = "region"
        pending["arg"] = (region, output_idx)  # 与 set_region(region, output_idx) 参数顺序一致
        win.set_region_text(region)
        if run_state["value"] in ("running", "paused"):
            start_capture()
        else:
            win.set_run_state("idle")
            win.set_start_ready(True)

    def on_window_selected(hwnd: int, title: str) -> None:
        """选择窗口：识别中直接切到新窗口；未开始则等待点击『开始识别』。"""
        pending["kind"] = "window"
        pending["arg"] = hwnd
        win.set_window_text(title)
        if run_state["value"] in ("running", "paused"):
            start_capture()
        else:
            win.set_run_state("idle")
            win.set_start_ready(True)

    def on_start() -> None:
        start_capture()

    def on_toggle_pause(paused: bool) -> None:
        capture_worker.set_paused(paused)
        run_state["value"] = "paused" if paused else "running"
        win.set_run_state("paused" if paused else "running")

    def on_window_stopped() -> None:
        pending["kind"] = None
        run_state["value"] = "idle"
        win.set_run_state("idle")
        win.set_start_ready(False)

    def open_settings() -> None:
        from .settings_dialog import SettingsDialog

        manager.suspend()  # 录制期间注销全局热键，避免组合被抢占
        SettingsDialog(manager, win).exec()
        failed = manager.resume()  # 关闭后按新配置重新注册
        if failed:
            win.show_error("快捷键注册失败：" + "；".join(failed))

    main_dict = Dictionary()
    win = MainWindow(
        store, tts, on_region_selected,
        dict_ref=main_dict,
        on_toggle_pause=on_toggle_pause,
        on_pick_window=on_window_selected,
        on_start=on_start,
        on_settings=open_settings,
    )
    capture_worker.windowStopped.connect(on_window_stopped)

    # 全局热键（无论焦点在哪，可在设置中自定义）：
    #   Ctrl+Alt+Shift+F 快速查词 / C 全部掌握 / X 全部掌握（不含生词）
    from .hotkey import HotkeyManager, MOD_ALT, MOD_CONTROL, MOD_SHIFT
    from .quick_add import QuickAddDialog

    quick_add = QuickAddDialog(win)
    manager = HotkeyManager(app, config.DATA_DIR / "settings.json")
    MODS = MOD_ALT | MOD_CONTROL | MOD_SHIFT
    HOTKEY_DEFS = (
        ("quick_add", "快速查词", MODS, ord("F"), quick_add.popup),
        ("master_all", "全部掌握", MODS, ord("C"), lambda: win._mark_all_mastered(include_vocab=True)),
        ("master_nv", "全部掌握（不含生词）", MODS, ord("X"), lambda: win._mark_all_mastered(include_vocab=False)),
    )
    for slug, display, mods, vk, cb in HOTKEY_DEFS:
        if not manager.define(slug, display, mods, vk, cb):
            win.show_error(f"全局热键（{display}）注册失败，可能已被其他程序占用，可在设置中修改")

    ocr_worker.wordsFound.connect(win.add_entries)
    ocr_worker.ocrError.connect(win.show_error)
    capture_worker.captureError.connect(win.show_error)
    win.show()

    # 自测钩子：GV_SELFTEST_TTS=1 时启动数秒后自动合成一次，用于复现打包环境 TTS 崩溃
    if os.environ.get("GV_SELFTEST_TTS"):
        from PySide6.QtCore import QTimer

        def _selftest_speak():
            tts.speak("selftest")
            win.statusBar().showMessage("selftest speak triggered", 5000)

        QTimer.singleShot(6000, _selftest_speak)

    ret = app.exec()

    ocr_worker.stop()
    capture_worker.stop()
    capture_thread.quit()
    capture_thread.wait(3000)
    ocr_thread.quit()
    ocr_thread.wait(3000)
    tts.stop()
    store.close()
    main_dict.close()
    manager.shutdown()
    return ret


def _start_thread(worker) -> "object":
    from PySide6.QtCore import QThread

    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    return thread


if __name__ == "__main__":
    sys.exit(main())
