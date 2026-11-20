"""下载 ECDICT 词典数据并构建 data/dict.db（仅需联网运行一次）。

用法:
    python scripts/prepare_dict.py [--proxy https://ghfast.top/]

GitHub 直连慢时可加 --proxy 镜像前缀，或设环境变量 GH_PROXY。
"""
import csv
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DICT_DB = DATA / "dict.db"

CSV_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
LEMMA_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/lemma.en.txt"

KEEP_COLS = ("word", "phonetic", "definition", "translation", "pos", "frq", "exchange")


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


def build_db(csv_path: Path, lemma_path: Path) -> None:
    if DICT_DB.exists():
        DICT_DB.unlink()
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DICT_DB)
    conn.execute(
        "CREATE TABLE dict (word TEXT PRIMARY KEY, phonetic TEXT, translation TEXT,"
        " definition TEXT, pos TEXT, frq INTEGER, exchange TEXT)"
    )
    conn.execute("CREATE TABLE lemma_map (inflected TEXT PRIMARY KEY, lemma TEXT)")

    n_words = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for rec in reader:
            frq = rec.get("frq") or "0"
            rows.append(
                (
                    rec["word"],
                    rec.get("phonetic", ""),
                    rec.get("translation", ""),
                    rec.get("definition", ""),
                    rec.get("pos", ""),
                    int(frq) if frq.isdigit() else 0,
                    rec.get("exchange", ""),
                )
            )
            if len(rows) >= 20000:
                conn.executemany("INSERT OR IGNORE INTO dict VALUES (?,?,?,?,?,?,?)", rows)
                n_words += len(rows)
                rows = []
        if rows:
            conn.executemany("INSERT OR IGNORE INTO dict VALUES (?,?,?,?,?,?,?)", rows)
            n_words += len(rows)
    conn.commit()

    n_lemma = 0
    with open(lemma_path, encoding="utf-8") as f:
        pairs = []
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if " -> " not in line:
                continue
            left, right = line.split(" -> ", 1)
            lemma = left.split("/")[0].strip().lower()
            if not lemma:
                continue
            for inf in right.split(","):
                inf = inf.strip().lower()
                if inf:
                    pairs.append((inf, lemma))
        conn.executemany("INSERT OR IGNORE INTO lemma_map VALUES (?,?)", pairs)
        n_lemma = len(pairs)
    conn.commit()
    conn.close()
    print(f"[ok] dict.db: {n_words} 词条, {n_lemma} 条词形映射, {DICT_DB.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    proxy = ""
    if "--proxy" in sys.argv:
        proxy = sys.argv[sys.argv.index("--proxy") + 1]
    elif os.environ.get("GH_PROXY"):
        proxy = os.environ["GH_PROXY"]
    if proxy and not proxy.endswith("/"):
        proxy += "/"
    DATA.mkdir(exist_ok=True)
    csv_path = DATA / "ecdict.csv"
    lemma_path = DATA / "lemma.en.txt"
    download(CSV_URL, csv_path, proxy)
    download(LEMMA_URL, lemma_path, proxy)
    build_db(csv_path, lemma_path)


if __name__ == "__main__":
    main()
