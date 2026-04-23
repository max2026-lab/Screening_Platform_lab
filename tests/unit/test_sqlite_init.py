from pathlib import Path

from lawful_anomaly_screening.db.sqlite import init_db


def test_sqlite_init(tmp_path):
    db = tmp_path / "test.sqlite3"
    init_db(db)
    assert db.exists()
