"""OCR 线程：RapidOCR -> 拆词 -> 词典查询 -> 增量过滤 -> wordsFound 信号。"""

import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from . import config
from .capture import FrameSource
from .dictionary import Dictionary, WordEntry
from .logutil import get_logger
from .store import WordStore
from .tokenizer import extract_words

log = get_logger("ocr")


class OcrWorker(QObject):
    wordsFound = Signal(list)   # list[WordEntry]（跨线程 queued 到主线程）
    ocrError = Signal(str)

    def __init__(self, source: FrameSource, store: WordStore):
        super().__init__()
        self.source = source
        self.store = store
        self.dict: Dictionary | None = None
        self._engine = None
        self._running = False
        self._snap_gray: object | None = None   # 上次真实 OCR 帧的灰度小图
        self._snap_boxes: object | None = None  # 其文本框（小图坐标，N×4×2）

    def reset_snap(self) -> None:
        self._snap_gray = None
        self._snap_boxes = None

    def _text_unchanged(self, frame) -> bool:
        """与上次真实 OCR 帧对比：旧文本框内没变、框外也没新增内容 -> 跳过整轮 OCR。"""
        if self._snap_gray is None or self._snap_boxes is None:
            return False
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (config.TEXT_SNAP_W, max(int(h * config.TEXT_SNAP_W / w), 1)))
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        if gray.shape != self._snap_gray.shape:
            return False  # 尺寸变了（如窗口移动/缩放），必须重 OCR
        sx = config.TEXT_SNAP_W / w
        sy = small.shape[0] / h
        gh, gw = gray.shape
        mask = np.zeros((gh, gw), dtype=np.uint8)
        for box in self._snap_boxes:
            xs = [int(p[0] * sx) for p in box]
            ys = [int(p[1] * sy) for p in box]
            x0, x1 = max(min(xs) - 2, 0), min(max(xs) + 2, gw)
            y0, y1 = max(min(ys) - 2, 0), min(max(ys) + 2, gh)
            if x1 <= x0 or y1 <= y0:
                return False
            mask[y0:y1, x0:x1] = 1
            diff = cv2.absdiff(self._snap_gray[y0:y1, x0:x1], gray[y0:y1, x0:x1])
            ratio = float(np.count_nonzero(diff > config.TEXT_DIFF_THRESH)) / diff.size
            if ratio > config.TEXT_DIFF_RATIO:
                return False
        # 框外区域：检测新增文本（新文字必然出现在旧框之外）。
        # 文字笔画稀疏，先膨胀聚块再统计占比；宁滥勿漏（框外有变就 OCR）。
        outside = mask == 0
        diff_out = cv2.absdiff(self._snap_gray, gray)
        bin_out = ((diff_out > config.TEXT_DIFF_THRESH) & outside).astype(np.uint8)
        bin_out = cv2.dilate(bin_out, np.ones((5, 3), np.uint8))
        ratio_out = int(bin_out.sum()) / max(int(outside.sum()), 1)
        if ratio_out > config.OUTSIDE_DIFF_RATIO:
            return False
        return True

    def _ensure_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import ModelType, OCRVersion

            if config.OCR_MODEL_TYPE == "mobile":
                params = {
                    "Det.ocr_version": OCRVersion.PPOCRV5,
                    "Det.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.MOBILE,
                }
            elif config.DET_MAX_SIDE:
                params = {"Det.limit_type": "max", "Det.limit_side_len": config.DET_MAX_SIDE}
            else:
                params = {}
            self._engine = RapidOCR(params=params)
            log.debug(f"OCR engine loaded (model_type={config.OCR_MODEL_TYPE}, det_max_side={config.DET_MAX_SIDE})")
        return self._engine

    def process_frame(self, frame) -> list[WordEntry]:
        if self._text_unchanged(frame):
            log.debug("SKIP: 文本区域无变化，跳过整轮 OCR")
            return []
        if self.dict is None:
            self.dict = Dictionary()
        engine = self._ensure_engine()
        t0 = time.perf_counter()
        result = engine(frame)
        t_ocr = time.perf_counter() - t0
        if result is None or not getattr(result, "txts", None):
            log.debug(f"OCR {t_ocr:.2f}s lines=0 words=0 new=0 (无文本)")
            return []
        n_lines = len(result.txts)
        words = extract_words(result.boxes, result.txts)
        entries: list[WordEntry] = []
        seen: set[str] = set()
        skipped_known = 0
        for w in words:
            entry = self.dict.lookup(w)
            if entry is None or entry.canonical in seen:
                continue
            seen.add(entry.canonical)
            if not self.store.is_new(entry.canonical):
                skipped_known += 1
                continue
            self.store.mark_shown(entry.canonical)
            entries.append(entry)
        self._save_snap(frame, result.boxes)
        log.debug(
            f"OCR {t_ocr:.2f}s lines={n_lines} words={len(words)} "
            f"uniq={len(seen)} new={len(entries)} known_skip={skipped_known}"
        )
        return entries

    def _save_snap(self, frame, boxes) -> None:
        h, w = frame.shape[:2]
        scale = config.TEXT_SNAP_W / w
        small = cv2.resize(frame, (config.TEXT_SNAP_W, max(int(h * scale), 1)))
        self._snap_gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        self._snap_boxes = boxes

    def run(self) -> None:
        self._running = True
        try:
            t0 = time.perf_counter()
            self.dict = Dictionary()
            self._ensure_engine()
            log.debug(f"engine ready in {time.perf_counter() - t0:.2f}s")
        except Exception as exc:
            self.ocrError.emit(f"OCR 引擎初始化失败: {exc}")
            return
        while self._running:
            frame = self.source.get(timeout=0.5)
            if frame is None:
                continue
            try:
                entries = self.process_frame(frame)
            except Exception as exc:
                self.ocrError.emit(f"OCR 处理失败: {exc}")
                continue
            if entries:
                self.wordsFound.emit(entries)

    def stop(self) -> None:
        self._running = False


def _selftest() -> None:
    """python -m game_ocr_vocab.ocr_worker <图片路径>：对静态图片跑完整管线。"""
    import sys

    import cv2

    sys.path.insert(0, str(config.ROOT))
    path = sys.argv[1] if len(sys.argv) > 1 else str(config.DEBUG_DIR / "test_card.png")
    frame = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    store = WordStore(db_path=config.DATA_DIR / "test_vocab.db")
    worker = OcrWorker(None, store)
    worker.dict = Dictionary()
    entries = worker.process_frame(frame)
    for e in entries:
        print(f"{e.word:12s} -> {e.canonical:12s} {e.translation}")
    print(f"共 {len(entries)} 词")
    worker.dict.close()
    store.close()


if __name__ == "__main__":
    _selftest()
