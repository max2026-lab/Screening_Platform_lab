import io
import json
import sys
from contextlib import redirect_stdout

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.settings import REPO_ROOT, Settings


def test_legal_check_defaults_to_manual_review():
    assert main(["legal-check"]) == 1


def _set_test_settings(monkeypatch, tmp_path):
    db_path = tmp_path / "legal-gate.sqlite3"
    settings = Settings(db_path=db_path)
    monkeypatch.setattr("lawful_anomaly_screening.settings.load_settings", lambda: settings)
    monkeypatch.setattr("lawful_anomaly_screening.cli.load_settings", lambda: settings)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.run_pipeline.load_settings", lambda: settings, raising=False)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.scaffold_run.load_settings", lambda: settings, raising=False)
    return db_path


def _capture_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    original_stderr = sys.stderr
    try:
        sys.stderr = stderr
        with redirect_stdout(stdout):
            result = main(args)
    finally:
        sys.stderr = original_stderr
    return result, stdout.getvalue(), stderr.getvalue()


def test_create_run_fails_clearly_when_attestation_is_missing(monkeypatch, tmp_path):
    db_path = _set_test_settings(monkeypatch, tmp_path)
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    result, _, stderr = _capture_main(
        [
            "create-run",
            "--run-id", "run-attestation-missing",
            "--geofence", "clear",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )

    assert result == 1
    assert "attestation status must be present" in stderr

    run = RunRepository(db_path).fetch_run("run-attestation-missing")
    assert run is not None
    assert run["status"] == "legal_gate_failed"
    assert run["legal_gate"]["attestation_status"] == "missing"
    assert run["legal_gate"]["decision"] == "fail"
    assert run["legal_gate"]["evaluated_at"]


def test_create_run_fails_clearly_when_attestation_is_invalid(monkeypatch, tmp_path):
    _set_test_settings(monkeypatch, tmp_path)
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    result, _, stderr = _capture_main(
        [
            "create-run",
            "--run-id", "run-attestation-invalid",
            "--attestation", "signed",
            "--geofence", "clear",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )

    assert result == 1
    assert "invalid attestation status: signed" in stderr


def test_create_run_fails_when_geofence_is_missing(monkeypatch, tmp_path):
    db_path = _set_test_settings(monkeypatch, tmp_path)
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    result, _, stderr = _capture_main(
        [
            "create-run",
            "--run-id", "run-geofence-missing",
            "--attestation", "present",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )

    assert result == 1
    assert "geofence status must be provided and clear" in stderr

    run = RunRepository(db_path).fetch_run("run-geofence-missing")
    assert run is not None
    assert run["legal_gate"]["geofence_status"] == "missing"
    assert run["legal_gate"]["decision"] == "fail"


def test_create_run_fails_when_geofence_policy_blocks_aoi(monkeypatch, tmp_path):
    db_path = _set_test_settings(monkeypatch, tmp_path)
    blocked_aoi = REPO_ROOT / "tests" / "fixtures" / "blocked_aoi.geojson"

    result, _, stderr = _capture_main(
        [
            "create-run",
            "--run-id", "run-geofence-blocked",
            "--attestation", "present",
            "--geofence", "clear",
            "--aoi-path", str(blocked_aoi),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )

    assert result == 1
    assert "deterministic geofence policy blocked AOI" in stderr

    run = RunRepository(db_path).fetch_run("run-geofence-blocked")
    assert run is not None
    assert run["legal_gate"]["geofence_status"] == "hit"
    assert run["legal_gate"]["decision"] == "fail"


def test_create_run_passes_for_valid_attestation_and_allowed_geofence(monkeypatch, tmp_path):
    _set_test_settings(monkeypatch, tmp_path)
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    result, stdout, stderr = _capture_main(
        [
            "create-run",
            "--run-id", "run-gate-pass",
            "--attestation", "present",
            "--geofence", "clear",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )

    assert result == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["legal_gate"]["decision"] == "pass"
    assert payload["legal_gate"]["attestation_status"] == "present"
    assert payload["legal_gate"]["geofence_status"] == "clear"


def test_execute_run_refuses_failed_persisted_gate(monkeypatch, tmp_path):
    _set_test_settings(monkeypatch, tmp_path)
    blocked_aoi = REPO_ROOT / "tests" / "fixtures" / "blocked_aoi.geojson"

    create_result, _, _ = _capture_main(
        [
            "create-run",
            "--run-id", "run-blocked-execute",
            "--attestation", "present",
            "--geofence", "clear",
            "--aoi-path", str(blocked_aoi),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )
    assert create_result == 1

    execute_result, _, execute_stderr = _capture_main(["execute-run", "--run-id", "run-blocked-execute"])
    assert execute_result == 1
    assert "blocked by legal gate" in execute_stderr


def test_execute_run_output_surfaces_persisted_legal_gate(monkeypatch, tmp_path):
    _set_test_settings(monkeypatch, tmp_path)
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    create_result, create_stdout, _ = _capture_main(
        [
            "create-run",
            "--run-id", "run-output-pass",
            "--attestation", "present",
            "--geofence", "clear",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        ]
    )
    execute_result, execute_stdout, _ = _capture_main(["execute-run", "--run-id", "run-output-pass"])

    assert create_result == 0
    assert execute_result == 0
    create_payload = json.loads(create_stdout)
    execute_payload = json.loads(execute_stdout)
    assert create_payload["legal_gate"]["decision"] == "pass"
    assert execute_payload["run_metadata"]["legal_gate"]["decision"] == "pass"
    assert execute_payload["run_metadata"]["legal_gate"]["reason"] == "legal gate passed"
