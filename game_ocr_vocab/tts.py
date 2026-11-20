"""Windows SAPI 离线 TTS：专用线程 + 队列，连点只读最新一个词。"""

import queue
import threading


class TtsSpeaker:
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=4)
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
        except Exception:
            voice = None
        while self._running:
            try:
                text = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            if voice is not None:
                try:
                    voice.Speak(text, 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak
                except Exception:
                    pass
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
