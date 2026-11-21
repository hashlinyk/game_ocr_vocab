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

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 12))
    app.setStyleSheet("QPushButton { padding: 5px 12px; } QListWidget { font-size: 12pt; }")

    err = check_prereqs()
    if err:
        QMessageBox.critical(None, "游戏单词助手", err)
        return 1

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

    def on_region_selected(output_idx: int, region: tuple) -> None:
        """框选完成：仅登记目标，等待点击『开始识别』。"""
        pending["kind"] = "region"
        pending["arg"] = (region, output_idx)  # 与 set_region(region, output_idx) 参数顺序一致
        win.set_region_text(region)
        win.set_run_state("idle")
        win.set_start_ready(True)

    def on_window_selected(hwnd: int, title: str) -> None:
        """选择窗口：仅登记目标，等待点击『开始识别』。"""
        pending["kind"] = "window"
        pending["arg"] = hwnd
        win.set_window_text(title)
        win.set_run_state("idle")
        win.set_start_ready(True)

    def on_start() -> None:
        if pending["kind"] is None:
            return
        ocr_worker.reset_snap()
        capture_worker.set_paused(False)
        if pending["kind"] == "region":
            capture_worker.set_region(*pending["arg"])
        else:
            capture_worker.set_window(pending["arg"])
        win.set_run_state("running")

    def on_toggle_pause(paused: bool) -> None:
        capture_worker.set_paused(paused)
        win.set_run_state("paused" if paused else "running")

    def on_window_stopped() -> None:
        pending["kind"] = None
        win.set_run_state("idle")
        win.set_start_ready(False)

    main_dict = Dictionary()
    win = MainWindow(
        store, tts, on_region_selected,
        dict_ref=main_dict,
        on_toggle_pause=on_toggle_pause,
        on_pick_window=on_window_selected,
        on_start=on_start,
    )
    capture_worker.windowStopped.connect(on_window_stopped)

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
