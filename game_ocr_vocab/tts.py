"""离线 TTS：Piper 神经语音优先（自然度高），SAPI 系统语音回退。

专用线程 + 队列（连点只保留最新），同步播报。
"""

import os
import queue
import shutil
import threading
from pathlib import Path

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
            import piper.phonemize_espeak as pe
            import piper.voice as pv

            # espeak 层不支持非 ASCII 路径（中文目录会卡死/崩溃）：
            # 计算 ASCII 数据目录，并替换 piper 内部全部三处 ESPEAK_DATA_DIR 绑定
            old_dir = Path(pe.ESPEAK_DATA_DIR)
            espeak_dir = self._ascii_espeak_dir(old_dir)
            model_ascii = self._to_ascii_path(model)
            if espeak_dir is None:
                log.debug("espeak 数据目录无法 ASCII 化，回退 SAPI")
                return None

            def patch_defaults(func, old: Path, new: Path) -> None:
                if func is not None and func.__defaults__:
                    func.__defaults__ = tuple(new if d == old else d for d in func.__defaults__)

            for mod in (pe, pv):
                mod.ESPEAK_DATA_DIR = espeak_dir
            patch_defaults(pe.EspeakPhonemizer.__init__, old_dir, espeak_dir)
            patch_defaults(pv.PiperVoice.load, old_dir, espeak_dir)
            patch_defaults(pv.PiperVoice.__init__, old_dir, espeak_dir)
            pv.PiperVoice.espeak_data_dir = espeak_dir

            voice = PiperVoice.load(str(model_ascii if model_ascii else model))
            log.debug(f"piper ready: {model.name} (espeak_dir_ascii={espeak_dir})")
            return voice
        except Exception as exc:
            log.debug(f"piper load failed: {exc}")
            return None

    @staticmethod
    def _to_ascii_path(p: Path) -> Path | None:
        """路径已是 ASCII 则原样返回；否则尝试 8.3 短路径；都不行返回 None。"""
        try:
            str(p).encode("ascii")
            return p
        except UnicodeEncodeError:
            pass
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024):
                short = Path(buf.value)
                str(short).encode("ascii")
                return short
        except Exception:
            pass
        return None

    @staticmethod
    def _ascii_espeak_dir(data_dir: Path) -> Path | None:
        """获取 espeak-ng-data 的 ASCII 可用路径：短路径优先，失败则复制到英文系统目录。"""
        ascii_dir = TtsSpeaker._to_ascii_path(data_dir)
        if ascii_dir is not None:
            return ascii_dir
        # 8.3 短路径不可用（卷禁用/名字太短无短名）：复制到 %PROGRAMDATA%（全英文）
        dest = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "GameOcrVocab" / "espeak-ng-data"
        try:
            if not dest.exists() or not any(dest.iterdir()):
                shutil.copytree(data_dir, dest, dirs_exist_ok=True)
            str(dest).encode("ascii")
            log.debug(f"espeak-ng-data copied to {dest}")
            return dest
        except Exception as exc:
            log.debug(f"copy espeak-ng-data failed: {exc}")
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
