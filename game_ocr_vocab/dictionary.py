"""ECDICT SQLite 查询 + 词形还原。

每个线程应创建自己的 Dictionary 实例（sqlite3 连接不可跨线程共用）。
"""

import sqlite3
from typing import NamedTuple

from . import config


class WordEntry(NamedTuple):
    word: str        # OCR 原词(小写)
    canonical: str   # 原形（lemma 还原后）
    phonetic: str
    translation: str  # 第一行释义
    translation_full: str


def parse_exchange_lemma(exchange: str) -> str | None:
    """exchange 格式如 'p:rooted/d:rooted/i:rooting/0:root'，取 0: 后的原形。"""
    if not exchange:
        return None
    for seg in exchange.split("/"):
        if seg.startswith("0:"):
            lemma = seg[2:].strip().lower()
            return lemma or None
    return None


class Dictionary:
    def __init__(self, db_path=config.DICT_DB):
        if not db_path.exists():
            raise FileNotFoundError(f"词典不存在: {db_path}，请先运行 scripts/prepare_dict.py")
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.execute("PRAGMA cache_size=-32000")

    def close(self):
        self.conn.close()

    def _raw(self, word: str):
        cur = self.conn.execute(
            "SELECT word, phonetic, translation, definition, exchange FROM dict WHERE word = ?",
            (word,),
        )
        return cur.fetchone()

    def to_canonical(self, word: str) -> str:
        row = self.conn.execute(
            "SELECT lemma FROM lemma_map WHERE inflected = ?", (word,)
        ).fetchone()
        if row:
            return row[0]
        raw = self._raw(word)
        if raw and raw[4]:
            lemma = parse_exchange_lemma(raw[4])
            if lemma:
                return lemma
        return word

    def lookup(self, word: str) -> WordEntry | None:
        canonical = self.to_canonical(word)
        for candidate in (canonical, word):
            raw = self._raw(candidate)
            if raw and (raw[2].strip() or raw[3].strip()):
                _, phonetic, translation, definition, _ = raw
                # ECDICT 部分条目的换行是字面 "\n" 文本，先归一为真实换行
                trans_clean = translation.replace("\\n", "\n")
                def_clean = definition.replace("\\n", " ")
                lines = [ln.strip() for ln in trans_clean.split("\n") if ln.strip()]
                first = lines[0] if lines else (def_clean[:80] or "")
                return WordEntry(
                    word=word,
                    canonical=canonical,
                    phonetic=phonetic or "",
                    translation=first,
                    translation_full="\n".join(lines) or def_clean,
                )
        return None


if __name__ == "__main__":
    d = Dictionary()
    for w in ("perceive", "perceived", "looted", "xyzzy", "a"):
        e = d.lookup(w)
        print(f"{w:12s} -> canonical={e.canonical if e else '-':12s} {e.translation if e else '(丢弃)'}")
    d.close()
