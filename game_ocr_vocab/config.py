"""全部可调参数集中于此。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if getattr(sys, "frozen", False):
    # PyInstaller 打包：只读资源(dict.db/OCR模型)在 _MEIPASS；用户数据写在 exe 同级
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLED_DATA = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "data"
else:
    APP_DIR = ROOT
    BUNDLED_DATA = ROOT / "data"

DATA_DIR = APP_DIR / "data"        # 用户数据：vocab.db / app.log / debug 帧
DEBUG_DIR = DATA_DIR / "debug"
DICT_DB = BUNDLED_DATA / "dict.db"
TTS_MODEL = BUNDLED_DATA / "tts" / "en_US-amy-medium.onnx"  # 缺失时回退 SAPI

# ---- OCR 模型 ----
# small = PP-OCRv6 small（推荐，实测比 v5 mobile 更快更准）
# mobile = PP-OCRv5 mobile，实测更慢，仅备用
OCR_MODEL_TYPE = "small"
DET_MAX_SIDE = 960  # det 输入长边上限；0=默认(min736)。960 比 1920 全分辨率快约 44%

# ---- 变化检测 ----
DOWNSCALE_W = 320      # 检测前缩放到的宽度
DIFF_THRESH = 25       # 灰度差超过此值算有效变化像素
CHANGE_RATIO = 0.004   # 单条带变化像素占比超过此值判定画面变化（全屏框选时小字幕易被稀释，故按条带算+低阈值）
DIFF_BANDS = 4         # 纵向切条带数，任一条带超阈值即触发
POLL_INTERVAL = 0.06   # 捕获轮询间隔(秒)，约 16Hz
COOLDOWN = 0.15        # 触发最小间隔(秒)；重复文本由预筛跳过，冷却只防抖

# ---- 文本区域预筛（跳过文本未变的重复 OCR） ----
TEXT_SNAP_W = 320       # 预筛快照缩放宽度
TEXT_DIFF_THRESH = 12   # 灰度差超过此值算变化像素
TEXT_DIFF_RATIO = 0.04  # 旧文本框内变化占比超过此值 => 需要重 OCR
OUTSIDE_DIFF_RATIO = 0.005  # 旧文本框之外变化占比(膨胀后)超过此值 => 有新增内容，重 OCR（宁滥勿漏）

# ---- UI ----
POLL_MS = 200
DEBUG_SAVE_FRAMES = True   # 把每次触发 OCR 的帧存到 data/debug/（t0001_change_r0.83.png）
DEBUG_LOG = True           # 写 data/app.log：触发原因/差异度/OCR 耗时

# ---- 拆词 ----
WORD_MAX_LEN = 24
SINGLE_OK = {"a", "i"}
