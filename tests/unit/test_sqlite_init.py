import sqlite3

from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db


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


def test_bootstrap_minimal_run_path(tmp_path):
    db = tmp_path / "bootstrap.sqlite3"
    init_db(db)

    result = bootstrap_minimal_run(
        db,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-001",
        manifest_path="data/manifests/manifest-hash-001.json",
    )

    assert result["run_id"] == "run-001"

    with sqlite3.connect(db) as conn:
        baseline_count = conn.execute(
            "SELECT COUNT(*) FROM processing_baselines WHERE processing_baseline_id = ?",
            ("baseline_v1_5_default",),
        ).fetchone()[0]
        manifest_count = conn.execute(
            "SELECT COUNT(*) FROM source_scene_manifests WHERE source_scene_manifest_hash = ?",
            ("manifest-hash-001",),
        ).fetchone()[0]
        manifest_row = conn.execute(
            """
            SELECT source_endpoint_id, source_name, manifest_path
            FROM source_scene_manifests
            WHERE source_scene_manifest_hash = ?
            """,
            ("manifest-hash-001",),
        ).fetchone()
        run_row = conn.execute(
            """
            SELECT status, source_endpoint_id, execution_mode, rerun_mode, cache_status
            FROM runs
            WHERE run_id = ?
            """,
            ("run-001",),
        ).fetchone()

    assert baseline_count == 1
    assert manifest_count == 1
    assert manifest_row == ("earth_search", "earth_search", "data/manifests/manifest-hash-001.json")
    assert run_row == ("new", "earth_search", "synchronous", "full", "cold")
