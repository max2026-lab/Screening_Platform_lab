import json
from pathlib import Path

import pytest

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db


def _generate_report_bundle(tmp_path, db_path, run_id):
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash=f"manifest-hash-{run_id}",
        source_endpoint_id="earth_search",
        run_id=run_id,
        manifest_path=f"data/manifests/manifest-hash-{run_id}.json",
        run_status="completed",
        aoi_hash=f"aoi-hash-{run_id}",
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
    repository = ExportRepository(db_path, export_root=tmp_path)
    export_record = repository.persist_export(
        run_id=run_id,
        audience="report_pdf",
        requested_precision="restricted",
        candidates=[],
    )
    return export_record


def test_export_bundle_verify_batch_folder_all_pass(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-batch-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-batch-002")

    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert payload["manifest_count"] == 2
    assert payload["passed_count"] == 2
    assert payload["failed_count"] == 0
    for r in payload["results"]:
        assert r["status"] == "pass"


def test_export_bundle_verify_batch_default_folder_all_pass(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_default.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-default-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-default-002")

    result = main([
        "export-bundle-verify-batch",
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert payload["manifest_count"] == 2
    assert payload["passed_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["reports_dir"] is not None
    assert "exports/reports" in payload["reports_dir"]
    for r in payload["results"]:
        assert r["status"] == "pass"


def test_export_bundle_verify_batch_manifest_list_all_pass(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_list.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-list-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-list-002")

    manifest_list_path = tmp_path / "manifest-list.txt"
    lines = [
        "",
        "# comment line",
        export1["bundle_manifest_path"],
        "",
        export2["bundle_manifest_path"],
    ]
    manifest_list_path.write_text("\n".join(lines), encoding="utf-8")

    result = main([
        "export-bundle-verify-batch",
        "--manifest-list", str(manifest_list_path),
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert payload["manifest_count"] == 2
    assert isinstance(payload["manifest_list"], str)
    assert payload["manifest_list"].endswith("manifest-list.txt")
    assert not isinstance(payload["manifest_list"], list)


def test_export_bundle_verify_batch_one_tampered_fails(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_tamper.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-tamper-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-tamper-002")

    bundle_path = tmp_path / Path(export1["bundle_path"])
    bundle_path.write_bytes(bundle_path.read_bytes() + b"TAMPER")

    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 1
    assert any("bundle_sha256 mismatch" in r for r in payload["results"][0]["reasons"])


def test_export_bundle_verify_batch_fail_fast(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_ff.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-ff-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-ff-002")

    bundle_path = tmp_path / Path(export1["bundle_path"])
    bundle_path.write_bytes(bundle_path.read_bytes() + b"TAMPER")

    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
        "--fail-fast",
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert len(payload["results"]) == 1
    assert payload["failed_count"] == 1


def test_export_bundle_verify_batch_markdown_output(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_md.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-md-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-md-002")

    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
        "--output", "markdown",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    assert "# Export Bundle Batch Verification" in stdout_text
    assert "Status: `pass`" in stdout_text
    assert "Manifest count:" in stdout_text
    assert "Passed count:" in stdout_text


def test_export_bundle_verify_batch_no_manifests_found(monkeypatch, capsys, tmp_path):
    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert any("No sidecar manifests found" in r for r in payload["reasons"])


def test_export_bundle_verify_batch_argument_conflict(monkeypatch, capsys, tmp_path):
    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--manifest-list", str(tmp_path / "manifest-list.txt"),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    captured = capsys.readouterr()
    assert "Cannot use both" in captured.err or "Cannot use both" in captured.out


def test_export_bundle_verify_batch_no_db_access(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "batch_nodb.sqlite3"
    export1 = _generate_report_bundle(tmp_path, db_path, "run-nodb-001")
    export2 = _generate_report_bundle(tmp_path, db_path, "run-nodb-002")

    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "nonexistent.sqlite3"))

    result = main([
        "export-bundle-verify-batch",
        "--reports-dir", str(tmp_path / "exports" / "reports"),
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert payload["manifest_count"] == 2
