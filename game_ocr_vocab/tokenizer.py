"""OCR 文本行 -> 候选英文单词（纯函数，无 Qt/词典依赖）。"""

import re
from typing import NamedTuple, Sequence

from . import config

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]{1,%d}$" % config.WORD_MAX_LEN)
STRIP_CHARS = "\"'‘’“”.?!:;,()[]{}<>*—–_"


class Line(NamedTuple):
    text: str
    y: float
    x: float


def clean_token(token: str) -> str | None:
    token = token.strip(STRIP_CHARS).replace("’", "'")
    if not WORD_RE.match(token):
        low = token.lower()
        if len(token) == 1 and low in config.SINGLE_OK:
            return low
        return None
    return token.lower()


def tokenize_line(text: str) -> list[str]:
    out = []
    for raw in text.split():
        w = clean_token(raw)
        if w:
            out.append(w)
    return out


def order_lines(boxes, txts: Sequence[str]) -> list[Line]:
    """按阅读顺序排列 OCR 文本行：y 分桶（容差=框高中位数），桶内按 x。"""
    lines = []
    heights = []
    for box, text in zip(boxes, txts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        lines.append(Line(text=text, y=sum(ys) / 4, x=min(xs)))
        heights.append(max(ys) - min(ys))
    if not lines:
        return []
    h = sorted(heights)[len(heights) // 2] if heights else 20
    tol = max(h * 0.6, 8)
    lines.sort(key=lambda ln: ln.y)
    buckets: list[list[Line]] = []
    for ln in lines:
        if buckets and ln.y - buckets[-1][-1].y <= tol:
            buckets[-1].append(ln)
        else:
            buckets.append([ln])
    ordered = []
    for bucket in buckets:
        bucket.sort(key=lambda ln: ln.x)
        ordered.extend(bucket)
    return ordered


def extract_words(boxes, txts: Sequence[str]) -> list[str]:
    words: list[str] = []
    for line in order_lines(boxes, txts):
        words.extend(tokenize_line(line.text))
    return words
