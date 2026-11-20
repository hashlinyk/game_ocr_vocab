"""离线 TTS：Piper 神经语音优先（自然度高），SAPI 系统语音回退。

专用线程 + 队列（连点只保留最新），同步播报。
"""

import queue
import threading

from . import config
from .logutil import get_logger

log = get_logger("tts")


class TtsSpeaker:
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=1)  # 连点只保留最新
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        piper_voice = self._load_piper()
        sapi_voice = None
        if piper_voice is None:
            sapi_voice = self._load_sapi()
        while self._running:
            try:
                text = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                if piper_voice is not None:
                    self._speak_piper(piper_voice, text)
                elif sapi_voice is not None:
                    sapi_voice.Speak(text)  # 同步播报
                    log.debug(f"sapi spoke: {text!r}")
            except Exception as exc:
                log.debug(f"speak failed: {exc}")
        if piper_voice is None:
            import comtypes

            comtypes.CoUninitialize()

    def _load_piper(self):
        model = config.TTS_MODEL
        if not model.exists():
            log.debug("piper 模型缺失，回退 SAPI")
            return None
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(str(model))
            log.debug(f"piper ready: {model.name}")
            return voice
        except Exception as exc:
            log.debug(f"piper load failed: {exc}")
            return None

    def _load_sapi(self):
        try:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            log.debug(f"SAPI ready, voices={voice.GetVoices().Count}")
            return voice
        except Exception as exc:
            log.debug(f"SAPI create failed: {exc}")
            return None

    def _speak_piper(self, voice, text: str) -> None:
        import io
        import wave

        import winsound

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf)
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)
        log.debug(f"piper spoke: {text!r}")

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
