"""下载 Piper 神经 TTS 英文语音模型（amy-medium，约 63MB，仅需联网运行一次）。

用法:
    python scripts/prepare_tts.py [--proxy https://hf-mirror.com/]

HuggingFace 直连慢时可加 --proxy，或设环境变量 HF_PROXY。
"""
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_DIR = ROOT / "data" / "tts"

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium"
FILES = ["en_US-amy-medium.onnx", "en_US-amy-medium.onnx.json"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def download(url: str, dest: Path, proxy: str) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {dest.name} 已存在")
        return
    full = proxy + url if proxy else url
    print(f"[down] {full}")
    req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:.1f}/{total / 1e6:.1f} MB", end="", flush=True)
    print()
    tmp.rename(dest)


def main() -> None:
    proxy = ""
    if "--proxy" in sys.argv:
        proxy = sys.argv[sys.argv.index("--proxy") + 1]
    elif os.environ.get("HF_PROXY"):
        proxy = os.environ["HF_PROXY"]
    if proxy and not proxy.endswith("/"):
        proxy += "/"
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        download(f"{BASE}/{name}", TTS_DIR / name, proxy)
    onnx = TTS_DIR / FILES[0]
    print(f"[ok] TTS 模型就绪: {onnx} ({onnx.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
