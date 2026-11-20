"""Windows SAPI 离线 TTS：专用线程 + 队列，连点只读最新一个词。"""

import queue
import threading

from .logutil import get_logger

log = get_logger("tts")


class TtsSpeaker:
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=1)  # 连点只保留最新
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        voice = None
        try:
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            log.debug(f"SAPI ready, voices={voice.GetVoices().Count}, volume={voice.Volume}")
        except Exception as exc:
            log.debug(f"SAPI create failed: {exc}")
            voice = None
        while self._running:
            try:
                text = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            if voice is not None:
                try:
                    # 同步播报：STA 线程无消息泵，SVSFlagsAsync 不会真正出声
                    voice.Speak(text)
                    log.debug(f"spoke: {text!r}")
                except Exception as exc:
                    log.debug(f"speak failed: {exc}")
        comtypes.CoUninitialize()

    def speak(self, text: str) -> None:
        try:
            self._q.put_nowait(text)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(text)
            except (queue.Empty, queue.Full):
                pass

    def stop(self) -> None:
        self._running = False
