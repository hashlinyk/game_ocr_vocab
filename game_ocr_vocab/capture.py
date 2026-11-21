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
from .window_pick import is_window_valid

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
    windowStopped = Signal()            # 窗口跟随模式下目标窗口被关闭

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
        self._paused = False
        self._output_idx: int | None = None
        self._camera_dirty = False
        self._mode = "region"          # region=固定区域 / window=窗口捕获(WGC)
        self._hwnd: int | None = None
        self._wgc_control = None
        self._last_wgc_ts = 0.0

    def set_paused(self, paused: bool) -> None:
        """暂停/恢复识别：区域保持不变，暂停期间不抓帧不触发 OCR。"""
        self._paused = paused
        if not paused:
            self._prev = None
            self._force_next = True  # 恢复后首帧直接识别，避免漏掉暂停期间的内容

    def set_region(self, region: tuple[int, int, int, int] | None, output_idx: int = 0) -> None:
        self._stop_wgc()
        with self._region_lock:
            self._region = region
            output_changed = self._output_idx != output_idx
            self._output_idx = output_idx
        self._mode = "region"
        self._prev = None
        self._force_next = True  # 新区域首帧直接触发 OCR
        if output_changed:
            self._camera_dirty = True  # dxcam 相机绑定输出，切换屏幕需重建

    def set_window(self, hwnd: int) -> None:
        """窗口捕获模式（Windows Graphics Capture）：直接抓目标窗口内容，
        不受遮挡影响，窗口移动/缩放自动跟随。"""
        with self._region_lock:
            self._region = None
            self._hwnd = hwnd
        self._mode = "window"
        self._prev = None
        self._force_next = True

    def stop_window(self) -> None:
        self._stop_wgc()
        self._mode = "region"
        self._hwnd = None

    def stop(self) -> None:
        self._running = False
        self._stop_wgc()

    def _stop_wgc(self) -> None:
        ctl = self._wgc_control
        self._wgc_control = None
        if ctl is not None:
            try:
                ctl.stop()
            except Exception:
                pass

    def _start_wgc(self, hwnd: int) -> None:
        from windows_capture import WindowsCapture

        if not is_window_valid(hwnd):
            self.captureError.emit("目标窗口已关闭，识别已停止")
            self.windowStopped.emit()
            return
        capture = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)

        @capture.event
        def on_frame_arrived(frame, capture_control):  # noqa: ARG001 - control 由库要求
            self._on_wgc_frame(frame)

        @capture.event
        def on_closed():
            if self._mode == "window" and self._wgc_control is not None:
                self._wgc_control = None
                self._mode = "region"
                with self._region_lock:
                    self._region = None
                    self._hwnd = None
                self.captureError.emit("目标窗口已关闭，识别已停止")
                self.windowStopped.emit()

        self._wgc_control = capture.start_free_threaded()
        log.debug(f"WGC 窗口捕获启动 hwnd={hwnd}")

    def _on_wgc_frame(self, frame) -> None:
        """WGC 帧回调（独立线程）：节流 + 变化检测，与固定区域模式共用触发逻辑。"""
        if self._mode != "window" or self._paused:
            return
        now = time.monotonic()
        if now - self._last_wgc_ts < config.POLL_INTERVAL:
            return
        self._last_wgc_ts = now
        try:
            rgb = cv2.cvtColor(frame.frame_buffer, cv2.COLOR_BGRA2RGB)
        except Exception:
            return
        if rgb.ndim != 3 or rgb.shape[0] < 8 or rgb.shape[1] < 8:
            return
        ratio = self._diff_ratio(rgb)
        now = time.monotonic()
        cooled = now - self._last_trigger >= config.COOLDOWN
        significant = ratio >= config.CHANGE_RATIO
        if self._force_next:
            trigger, reason = True, "force"
        elif significant and cooled:
            trigger, reason = True, "change"
        elif significant:
            self._pending = True
            trigger, reason = False, "pending"
        elif self._pending and cooled:
            trigger, reason = True, "pending-flush"
        else:
            trigger, reason = False, ""
        if trigger:
            self._force_next = False
            self._pending = False
            self._last_trigger = now
            if config.DEBUG_SAVE_FRAMES:
                self._save_debug(rgb, reason, ratio)
            self.source.put(rgb)
            self.frameChanged.emit(rgb)

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

        output_idx = self._output_idx or 0
        return dxcam.create(output_color="RGB", backend="dxgi", output_idx=output_idx)

    def run(self) -> None:
        self._running = True
        camera = None
        fail_streak = 0
        rebuilt = False
        while self._running:
            with self._region_lock:
                mode = self._mode
                hwnd = self._hwnd
                region = self._region

            if mode == "window":
                if self._wgc_control is None and hwnd is not None:
                    try:
                        self._start_wgc(hwnd)
                    except Exception as exc:
                        self._wgc_control = None
                        self._mode = "region"
                        with self._region_lock:
                            self._region = None
                            self._hwnd = None
                        self.captureError.emit(f"窗口捕获启动失败: {exc}")
                        self.windowStopped.emit()
                time.sleep(0.2)  # WGC 回调独立线程供帧，此线程仅管理生命周期
                continue

            if camera is not None and self._camera_dirty:
                # 切换屏幕：dxcam 相机绑定输出设备，必须重建
                try:
                    camera.release()
                except Exception:
                    pass
                camera = None
                self._camera_dirty = False
                fail_streak = 0
                rebuilt = False
            if camera is None:
                try:
                    camera = self._create_camera()
                    fail_streak = 0
                except Exception as exc:
                    self.captureError.emit(f"无法初始化屏幕捕获: {exc}")
                    time.sleep(2.0)
                    continue
            if region is None or self._paused:
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
        # 防止无限占用磁盘：超量删最旧
        frames = sorted(config.DEBUG_DIR.glob("t*.png"))
        for old in frames[: max(0, len(frames) - config.DEBUG_KEEP)]:
            try:
                old.unlink()
            except OSError:
                pass


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
