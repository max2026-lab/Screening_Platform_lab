import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db


def _generate_report_bundle(tmp_path, db_path):
    """Bootstrap a zero-candidate run and create a report_pdf restricted export."""
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-verify-001",
        manifest_path="data/manifests/manifest-hash-001.json",
        run_status="completed",
        aoi_hash="aoi-hash-001",
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
        run_id="run-verify-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=[],
    )
    return export_record


def test_export_bundle_verify_passes(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(bundle_manifest_path),
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert payload["bundle_sha256_valid"] is True
    assert payload["bundle_members_valid"] is True
    assert payload["sidecar_files_valid"] is True
    assert payload["sha256sums_valid"] is True
    assert payload["forbidden_geometry_keys_absent"] is True
    assert payload["checked_file_count"] == 4
    assert payload["reasons"] == []


def test_export_bundle_verify_markdown_output(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify_md.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(bundle_manifest_path),
        "--export-root", str(tmp_path),
        "--output", "markdown",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    assert "Status: `pass`" in stdout_text
    assert "Bundle path:" in stdout_text


def test_export_bundle_verify_tampered_bundle_fails(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify_tamper.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    # Tamper the ZIP by appending bytes
    bundle_path = tmp_path / Path(export_record["bundle_path"])
    bundle_path.write_bytes(bundle_path.read_bytes() + b"TAMPER")

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(bundle_manifest_path),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert any("bundle_sha256 mismatch" in r for r in payload["reasons"])


def test_export_bundle_verify_forbidden_geometry_key_fails(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify_geom.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    # Inject forbidden key into sidecar copy
    sidecar = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    sidecar["centroid"] = [1.0, 2.0]
    tampered_manifest = tmp_path / "tampered.manifest.json"
    tampered_manifest.write_text(json.dumps(sidecar, sort_keys=True), encoding="utf-8")

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(tampered_manifest),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert any("forbidden geometry keys" in r for r in payload["reasons"])


def test_export_bundle_verify_missing_file_fails(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify_missing.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    # Delete the markdown report
    artifact_path = tmp_path / Path(export_record["artifact_path"])
    artifact_path.unlink()

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(bundle_manifest_path),
        "--export-root", str(tmp_path),
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert any("not found" in r for r in payload["reasons"])


def test_export_bundle_verify_no_db_access(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "verify_nodb.sqlite3"
    export_record = _generate_report_bundle(tmp_path, db_path)
    bundle_manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])

    # Point DB to a nonexistent path; verifier should still pass
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "nonexistent.sqlite3"))

    result = main([
        "export-bundle-verify",
        "--bundle-manifest-path", str(bundle_manifest_path),
        "--export-root", str(tmp_path),
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"


def test_export_bundle_verify_missing_arg(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([
            "export-bundle-verify",
        ])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "required" in captured.err.lower() or "error" in captured.err.lower()
