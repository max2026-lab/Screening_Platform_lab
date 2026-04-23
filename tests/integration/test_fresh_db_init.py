from pathlib import Path

from lawful_anomaly_screening.db.sqlite import init_db


def test_fresh_db_init(tmp_path):
    db = tmp_path / "fresh.sqlite3"
    init_db(db)
    assert db.is_file()
