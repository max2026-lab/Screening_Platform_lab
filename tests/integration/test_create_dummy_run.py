import json
import sqlite3
from pathlib import Path

from lawful_anomaly_screening.cli import main


def test_create_dummy_run(monkeypatch, tmp_path):
    db_path = tmp_path / "run.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    assert main(
        [
            "create-run",
            "--attestation",
            "present",
            "--geofence",
            "clear",
            "--run-id",
            "run-integration-001",
            "--source-endpoint-id",
            "earth_search",
            "--aoi-path", "tests/fixtures/sample_aoi.geojson",
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    ) == 0

    with sqlite3.connect(db_path) as conn:
        run_row = conn.execute(
            """
            SELECT source_scene_manifest_hash, source_endpoint_id
            FROM runs
            WHERE run_id = ?
            """,
            ("run-integration-001",),
        ).fetchone()
        manifest_row = conn.execute(
            """
            SELECT source_endpoint_id, source_name, manifest_path
            FROM source_scene_manifests
            WHERE source_scene_manifest_hash = ?
            """,
            (run_row[0],),
        ).fetchone()

    assert run_row[1] == "earth_search"
    assert manifest_row[0] == "earth_search"
    assert manifest_row[1] == "earth-search"
    assert Path(manifest_row[2]).is_file()
    payload = json.loads(Path(manifest_row[2]).read_text(encoding="utf-8"))
    assert payload["source_endpoint_id"] == "earth_search"
