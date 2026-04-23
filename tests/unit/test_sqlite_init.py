import sqlite3

from lawful_anomaly_screening.db.sqlite import init_db


def test_sqlite_init(tmp_path):
    db = tmp_path / "test.sqlite3"
    init_db(db)
    assert db.exists()
    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "processing_baselines",
        "feature_versions",
        "runs",
        "source_scene_manifests",
        "cached_assets",
        "geofence_hits",
        "export_records",
    } <= tables
