from __future__ import annotations

from pathlib import Path
import sqlite3


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
