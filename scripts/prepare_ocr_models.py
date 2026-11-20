"""预下载 RapidOCR 模型（约 30MB，仅需联网运行一次），此后完全离线。

用法:
    python scripts/prepare_ocr_models.py
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    try:
        from rapidocr import download_models

        download_models()
        print("[ok] OCR 模型已就绪")
    except ImportError:
        print("旧版 rapidocr 无 download_models 接口，改为直接初始化触发下载")
        from rapidocr import RapidOCR

        RapidOCR()
        print("[ok] OCR 模型已就绪")


if __name__ == "__main__":
    main()
