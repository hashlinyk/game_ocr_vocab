"""端到端管线测试（不开主 GUI）。

同进程内：目标窗口显示英文对话 -> 捕获线程抓该区域 -> OCR -> 词典 -> 增量信号。
验证：初始文本出词；切换文本后新词追加；重复词不重复。

运行: python scripts/e2e_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel

from game_ocr_vocab.capture import CaptureWorker, FrameSource
from game_ocr_vocab.ocr_worker import OcrWorker
from game_ocr_vocab.store import WordStore

TEXT_1 = "The ancient rune glows faintly beside the forgotten tome."
TEXT_2 = "A mysterious merchant whispers: beckon the spirit tonight."


class TargetWindow(QLabel):
    def __init__(self):
        super().__init__(TEXT_1)
        font = QFont("Arial", 26)
        self.setFont(font)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setGeometry(300, 200, 760, 260)
        self.setStyleSheet("background: white; color: black;")


def main() -> int:
    app = QApplication(sys.argv)
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio()

    target = TargetWindow()
    target.show()

    source = FrameSource()
    store = WordStore(db_path=str(Path(__file__).resolve().parent.parent / "data" / "e2e_vocab.db"))
    seen: list[str] = []

    capture_worker = CaptureWorker(source)
    ocr_worker = OcrWorker(source, store)
    ocr_worker.wordsFound.connect(lambda entries: seen.extend(e.canonical for e in entries) or print(
        "[found]", ", ".join(f"{e.word}->{e.canonical}" for e in entries)))

    from PySide6.QtCore import QThread

    cap_thread = QThread()
    capture_worker.moveToThread(cap_thread)
    cap_thread.started.connect(capture_worker.run)
    cap_thread.start()

    ocr_thread = QThread()
    ocr_worker.moveToThread(ocr_thread)
    ocr_thread.started.connect(ocr_worker.run)
    ocr_thread.start()

    g = target.geometry()
    region = (int(g.x() * dpr), int(g.y() * dpr),
              int((g.x() + g.width()) * dpr), int((g.y() + g.height()) * dpr))
    print(f"region={region} dpr={dpr}")
    capture_worker.set_region(region)

    def phase2() -> None:
        print("== 切换文本 ==")
        target.setText(TEXT_2)

    def finish() -> None:
        ocr_worker.stop()
        capture_worker.stop()
        cap_thread.quit()
        ocr_thread.quit()
        cap_thread.wait(3000)
        ocr_thread.wait(3000)
        store.close()
        uniq = set(seen)
        expect_1 = {"rune", "ancient", "glow", "faintly", "beside", "forget", "tome"}
        expect_2 = {"merchant", "whisper", "beckon", "spirit", "tonight"}
        ok1 = expect_1 & uniq
        ok2 = expect_2 & uniq
        dup = len(seen) != len(uniq)
        print(f"识别词 {len(seen)} 个: {sorted(uniq)}")
        print(f"文本1命中 {len(ok1)}/{len(expect_1)}, 文本2命中 {len(ok2)}/{len(expect_2)}, 增量去重{'OK' if not dup else 'FAIL(有重复)'}")
        success = len(ok1) >= 5 and len(ok2) >= 4 and not dup
        print("E2E_" + ("PASS" if success else "FAIL"))
        app.quit()

    QTimer.singleShot(4000, phase2)
    QTimer.singleShot(9000, finish)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
