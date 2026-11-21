"""已掌握/单词本持久化 + 会话增量去重。OCR 线程与主线程共用，内部加锁。"""

import sqlite3
import threading
import time

from . import config


class WordStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or (config.DATA_DIR / "vocab.db")
        config.DATA_DIR.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS word_status ("
            "word TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('mastered','vocab')),"
            "updated REAL)"
        )
        self._conn.commit()
        self._shown: set[str] = set()
        self._mastered: set[str] = set()
        self._vocab: set[str] = set()
        for word, status in self._conn.execute("SELECT word, status FROM word_status"):
            (self._mastered if status == "mastered" else self._vocab).add(word)

    # ---- 增量判定（OCR 线程调用） ----
    def is_new(self, canonical: str) -> bool:
        """生词本中的词允许再次识别；只排除已展示与本会话已掌握。"""
        with self._lock:
            return canonical not in self._shown and canonical not in self._mastered

    def is_vocab(self, canonical: str) -> bool:
        with self._lock:
            return canonical in self._vocab

    def reset_shown_word(self, canonical: str) -> None:
        """清除单个词的本会话已展示记录（配合识别页隐藏按钮：下次出现会再次追加）。"""
        with self._lock:
            self._shown.discard(canonical)

    def mark_shown(self, canonical: str) -> None:
        with self._lock:
            self._shown.add(canonical)

    # ---- 状态标记（主线程调用） ----
    def set_status(self, canonical: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO word_status(word, status, updated) VALUES (?,?,?) "
                "ON CONFLICT(word) DO UPDATE SET status=excluded.status, updated=excluded.updated",
                (canonical, status, time.time()),
            )
            self._conn.commit()
            self._mastered.discard(canonical)
            self._vocab.discard(canonical)
            target = self._mastered if status == "mastered" else self._vocab
            target.add(canonical)

    def remove_status(self, canonical: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM word_status WHERE word = ?", (canonical,))
            self._conn.commit()
            self._mastered.discard(canonical)
            self._vocab.discard(canonical)
            self._shown.discard(canonical)  # 允许该词再次被识别追加

    def words_of(self, status: str) -> list[tuple[str, float]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT word, updated FROM word_status WHERE status = ? ORDER BY updated DESC",
                (status,),
            )
            return cur.fetchall()

    def clear_all(self) -> None:
        """清空全部标记，并重置会话已展示集合（清掉的词再次出现会重新追加）。"""
        with self._lock:
            self._conn.execute("DELETE FROM word_status")
            self._conn.commit()
            self._mastered.clear()
            self._vocab.clear()
            self._shown.clear()

    def reset_shown(self) -> None:
        """重置会话已展示集合（配合首页清空列表：这些词再次出现会重新追加）。"""
        with self._lock:
            self._shown.clear()

    def status_of(self, canonical: str) -> str | None:
        with self._lock:
            if canonical in self._mastered:
                return "mastered"
            if canonical in self._vocab:
                return "vocab"
            return None

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return len(self._mastered), len(self._vocab)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
