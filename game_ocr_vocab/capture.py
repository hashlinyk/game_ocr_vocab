"""dxcam 捕获线程 + 画面变化检测。

grab(region) 无新帧时返回 None（直接 skip）；
有新帧时做 缩小->灰度->像素差 检测，变化显著且过冷却期才投递帧。
"""

import queue
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from . import config
from .logutil import get_logger

log = get_logger("capture")


class FrameSource(QObject):
    """捕获线程持有；OCR 线程从这里阻塞取帧。"""

    def __init__(self):
        super().__init__()
        self._q: queue.Queue = queue.Queue(maxsize=1)

    def put(self, frame: np.ndarray) -> None:
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            log.debug("QUEUE-DROP: OCR 跟不上，丢弃旧帧（处理中的画面已过期）")
            try:
                self._q.get_nowait()
                self._q.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def get(self, timeout: float | None = None) -> np.ndarray | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None


class CaptureWorker(QObject):
    frameChanged = Signal(np.ndarray)   # 判定为变化的帧(RGB ndarray)
    captureError = Signal(str)

    def __init__(self, frame_source: FrameSource):
        super().__init__()
        self.source = frame_source
        self._region: tuple[int, int, int, int] | None = None
        self._region_lock = threading.Lock()
        self._running = False
        self._prev: np.ndarray | None = None
        self._last_trigger = 0.0
        self._force_next = False
        self._pending = False
        self._frame_no = 0

    def set_region(self, region: tuple[int, int, int, int] | None) -> None:
        with self._region_lock:
            self._region = region
        self._prev = None
        self._force_next = True  # 新区域首帧直接触发 OCR

    def stop(self) -> None:
        self._running = False

    # ---- 变化检测 ----
    def _diff_ratio(self, frame: np.ndarray) -> float:
        """纵向分条带各算变化占比，取最大值——避免全屏框选时小字幕的变化被整屏稀释。"""
        h, w = frame.shape[:2]
        scale = config.DOWNSCALE_W / w
        small = cv2.resize(frame, (config.DOWNSCALE_W, max(int(h * scale), 1)))
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        if self._prev is None or self._prev.shape != gray.shape:
            self._prev = gray
            return 1.0
        diff = cv2.absdiff(gray, self._prev)
        gh = diff.shape[0]
        max_ratio = 0.0
        for i in range(config.DIFF_BANDS):
            y0, y1 = gh * i // config.DIFF_BANDS, gh * (i + 1) // config.DIFF_BANDS
            band = diff[y0:y1]
            if band.size == 0:
                continue
            ratio = float(np.count_nonzero(band > config.DIFF_THRESH)) / band.size
            max_ratio = max(max_ratio, ratio)
        self._prev = gray
        return max_ratio

    def _create_camera(self):
        import dxcam

        return dxcam.create(output_color="RGB", backend="dxgi")

    def run(self) -> None:
        self._running = True
        camera = None
        fail_streak = 0
        rebuilt = False
        while self._running:
            if camera is None:
                try:
                    camera = self._create_camera()
                    fail_streak = 0
                except Exception as exc:
                    self.captureError.emit(f"无法初始化屏幕捕获: {exc}")
                    time.sleep(2.0)
                    continue
            with self._region_lock:
                region = self._region
            if region is None:
                time.sleep(0.2)
                continue
            try:
                frame = camera.grab(region=region)
                fail_streak = 0
            except Exception as exc:
                fail_streak += 1
                if fail_streak >= 5:
                    try:
                        camera.release()
                    except Exception:
                        pass
                    if rebuilt:
                        self.captureError.emit(f"屏幕捕获持续失败: {exc}")
                        time.sleep(2.0)
                        continue
                    camera = None
                    rebuilt = True
                continue
            if frame is None:
                time.sleep(config.POLL_INTERVAL)
                continue

            ratio = self._diff_ratio(frame)
            now = time.monotonic()
            cooled = now - self._last_trigger >= config.COOLDOWN
            significant = ratio >= config.CHANGE_RATIO
            if self._force_next:
                trigger, reason = True, "force"
            elif significant and cooled:
                trigger, reason = True, "change"
            elif significant:
                self._pending = True  # 冷却期内发生变化：冷却一结束立即触发
                trigger, reason = False, "pending"
            elif self._pending and cooled:
                trigger, reason = True, "pending-flush"
            else:
                trigger, reason = False, ""
            if trigger:
                self._force_next = False
                self._pending = False
                gap = now - self._last_trigger
                self._last_trigger = now
                log.debug(f"TRIGGER reason={reason} ratio={ratio:.4f} gap={gap:.2f}s")
                if config.DEBUG_SAVE_FRAMES:
                    self._save_debug(frame, reason, ratio)
                self.source.put(frame)
                self.frameChanged.emit(frame)
            time.sleep(config.POLL_INTERVAL)
        if camera is not None:
            try:
                camera.release()
            except Exception:
                pass

    def _save_debug(self, frame: np.ndarray, reason: str, ratio: float) -> None:
        import cv2 as _cv2

        config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        self._frame_no += 1
        path = config.DEBUG_DIR / f"t{self._frame_no:04d}_{reason}_r{ratio:.2f}_{time.strftime('%H%M%S')}.png"
        _cv2.imwrite(str(path), _cv2.cvtColor(frame, _cv2.COLOR_RGB2BGR))


def _selftest() -> None:
    """python -m game_ocr_vocab.capture --region l,t,r,b [秒数]"""
    import argparse
    import sys

    sys.path.insert(0, str(config.ROOT))
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="100,100,900,500")
    ap.add_argument("--seconds", type=float, default=10.0)
    args = ap.parse_args()
    region = tuple(int(v) for v in args.region.split(","))

    from PySide6.QtCore import Qt

    src = FrameSource()
    worker = CaptureWorker(src)
    worker.frameChanged.connect(lambda f: print(f"[change] trigger, frame {f.shape}"), Qt.DirectConnection)
    worker.captureError.connect(lambda m: print(f"[error] {m}"), Qt.DirectConnection)

    thread = threading.Thread(target=worker.run, daemon=True)
    worker.set_region(region)
    thread.start()
    print(f"监听区域 {region}，请在该区域内滚动/变化画面… (Ctrl+C 退出)")
    n = 0
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        frame = src.get(timeout=0.5)
        if frame is not None:
            n += 1
            print(f"  队列取出第 {n} 帧")
    worker.stop()
    thread.join(timeout=2)
    print(f"结束: 共触发 {n} 帧")


if __name__ == "__main__":
    _selftest()
