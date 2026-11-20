"""轻量文件日志：data/app.log（循环覆盖，最大 2MB x 3）。"""

import logging
from logging.handlers import RotatingFileHandler

from . import config

_fmt = logging.Formatter("%(asctime)s.%(msecs)03d [%(threadName)s] %(message)s", "%H:%M:%S")


def get_logger(name: str = "app") -> logging.Logger:
    logger = logging.getLogger(f"gov.{name}")
    if not logger.handlers and config.DEBUG_LOG:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            config.DATA_DIR / "app.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(_fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
