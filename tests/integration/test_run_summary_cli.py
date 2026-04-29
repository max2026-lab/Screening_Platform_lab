import json
import os
from pathlib import Path

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db


def test_run_summary_returns_expected_json_for_run_with_candidates(tmp_path):
    db_path = tmp_path / "summary_candidates.sqlite3"
    init_db(db_path)
    run_id = "run-summary-001"
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id=run_id,
        manifest_path="data/manifests/manifest-hash-001.json",
    )

    repository = RunRepository(db_path)
    run = repository.fetch_run(run_id)
    assert run is not None
    assert run["run_id"] == run_id


def test_run_summary_zero_candidate_completed_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "summary_zero.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-002",
        source_endpoint_id="earth_search",
        run_id="run-summary-zero-001",
        manifest_path="data/manifests/manifest-hash-002.json",
        run_status="completed",
        aoi_hash="aoi-hash-zero",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate={
            "attestation_status": "present",
            "geofence_status": "clear",
            "decision": "pass",
            "reason": "",
            "evaluated_at": "2024-01-01T00:00:00Z",
        },
    )

    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    result = main([
        "run-summary",
        "--run-id", "run-summary-zero-001",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    summary = json.loads(stdout_text)
    assert summary["run_id"] == "run-summary-zero-001"
    assert summary["status"] == "completed"
    assert summary["candidate_count"] == 0
    assert summary["top_candidate_id"] is None


def test_run_summary_includes_latest_export_info(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "summary_export.sqlite3"
    init_db(db_path)
    run_id = "run-summary-export-001"
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-003",
        source_endpoint_id="earth_search",
        run_id=run_id,
        manifest_path="data/manifests/manifest-hash-003.json",
    )

    repository = ExportRepository(db_path, export_root=tmp_path)
    export_record = repository.persist_export(
        run_id=run_id,
        audience="report_pdf",
        requested_precision="restricted",
        candidates=[],
    )

    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    result = main([
        "run-summary",
        "--run-id", run_id,
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    summary = json.loads(stdout_text)
    assert summary["run_id"] == run_id
    assert summary["latest_export_record_id"] == export_record["export_record_id"]
    assert summary["latest_export_artifact_path"] is not None


def test_run_summary_fails_for_missing_run_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "summary_missing.sqlite3"
    init_db(db_path)
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    result = main([
        "run-summary",
        "--run-id", "nonexistent-run",
    ])
    assert result != 0

    captured = capsys.readouterr()
    assert "run not found: nonexistent-run" in captured.err
