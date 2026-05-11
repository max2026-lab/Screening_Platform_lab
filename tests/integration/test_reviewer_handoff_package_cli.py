import hashlib
import json
from pathlib import Path

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db
from lawful_anomaly_screening.settings import REPO_ROOT


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legal_gate_pass() -> dict:
    return {
        "attestation_status": "present",
        "geofence_status": "clear",
        "decision": "pass",
        "reason": "legal gate passed",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _legal_gate_fail() -> dict:
    return {
        "attestation_status": "missing",
        "geofence_status": "clear",
        "decision": "fail",
        "reason": "attestation missing",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


# --- API tests ---


def test_happy_path_with_candidates(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_candidates.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "handoff-candidates-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "handoff-candidates-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-candidates-001",
        "--output-dir", str(out),
        "--format", "both",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] in ("pass", "warn")
    assert (out / "reviewer_handoff_package.json").exists()
    assert (out / "reviewer_handoff_package.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2

    json_report = json.loads((out / "reviewer_handoff_package.json").read_text(encoding="utf-8"))
    assert json_report["schema"]["version"] == "v1.19.0"
    assert json_report["run_id"] == "handoff-candidates-001"
    assert json_report["handoff"]["run_summary"]["run_id"] == "handoff-candidates-001"
    assert json_report["handoff"]["readiness"]["status"] in ("pass", "warn")
    assert json_report["handoff"]["review_queue_summary"]["candidate_count"] > 0
    assert len(json_report["handoff"]["queued_candidates"]) > 0


def test_missing_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_missing.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-missing-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("not found" in f for f in payload["failures"])
    assert (out / "reviewer_handoff_package.json").exists()


def test_readiness_fail_propagation(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_legal.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-003",
        source_endpoint_id="earth_search",
        run_id="handoff-legal-fail-001",
        manifest_path="data/manifests/manifest-hash-003.json",
        run_status="completed",
        aoi_hash="aoi-hash-legal",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_fail(),
    )

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-legal-fail-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    json_report = json.loads((out / "reviewer_handoff_package.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "fail"
    assert any("legal gate" in f.lower() for f in json_report["failures"])
    assert json_report["handoff"]["readiness"]["status"] == "fail"


def test_artifact_root_missing(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_art.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-004",
        source_endpoint_id="earth_search",
        run_id="handoff-art-001",
        manifest_path="data/manifests/manifest-hash-004.json",
        run_status="new",
        aoi_hash="aoi-hash-art",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-art-001",
        "--artifact-root", str(tmp_path / "nonexistent"),
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("does not exist" in f.lower() for f in payload["failures"])


def test_artifact_safety_warning(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_safe.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-005",
        source_endpoint_id="earth_search",
        run_id="handoff-safe-001",
        manifest_path="data/manifests/manifest-hash-005.json",
        run_status="new",
        aoi_hash="aoi-hash-safe",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    artifact_root = tmp_path / "artifacts"
    public_dir = artifact_root / "exports" / "public"
    public_dir.mkdir(parents=True)
    unsafe_file = public_dir / "exact_coordinates.json"
    unsafe_file.write_text("{}", encoding="utf-8")

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-safe-001",
        "--artifact-root", str(artifact_root),
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("exact" in w.lower() and "public" in w.lower() for w in payload["warnings"])


def test_limit_behavior(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_limit.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "handoff-limit-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "handoff-limit-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-limit-001",
        "--output-dir", str(out),
        "--format", "json",
        "--limit", "2",
    ])
    assert result == 0
    json_report = json.loads((out / "reviewer_handoff_package.json").read_text(encoding="utf-8"))
    queued = json_report["handoff"]["queued_candidates"]
    assert len(queued) == 2


def test_format_json_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_json.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-006",
        source_endpoint_id="earth_search",
        run_id="handoff-json-001",
        manifest_path="data/manifests/manifest-hash-006.json",
        run_status="new",
        aoi_hash="aoi-hash-json",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-json-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    assert (out / "reviewer_handoff_package.json").exists()
    assert not (out / "reviewer_handoff_package.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_markdown_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_md.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-007",
        source_endpoint_id="earth_search",
        run_id="handoff-md-001",
        manifest_path="data/manifests/manifest-hash-007.json",
        run_status="new",
        aoi_hash="aoi-hash-md",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-md-001",
        "--output-dir", str(out),
        "--format", "markdown",
    ])
    assert result == 0
    assert not (out / "reviewer_handoff_package.json").exists()
    assert (out / "reviewer_handoff_package.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_no_db_mutation(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "handoff_mutation.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-008",
        source_endpoint_id="earth_search",
        run_id="handoff-mutation-001",
        manifest_path="data/manifests/manifest-hash-008.json",
        run_status="new",
        aoi_hash="aoi-hash-mutation",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    before_hash = _file_hash(db_path)

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-mutation-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0

    after_hash = _file_hash(db_path)
    assert before_hash == after_hash


def test_no_v18_artifacts_created_explicit_output_dir(monkeypatch, capsys, tmp_path):
    import shutil
    if Path(".review-package-readiness").exists():
        shutil.rmtree(".review-package-readiness")

    db_path = tmp_path / "handoff_no_v18.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-009",
        source_endpoint_id="earth_search",
        run_id="handoff-no-v18-001",
        manifest_path="data/manifests/manifest-hash-009.json",
        run_status="new",
        aoi_hash="aoi-hash-no-v18",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "handoff-out"
    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-no-v18-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    assert (out / "reviewer_handoff_package.json").exists()
    assert not (out / "review_package_readiness_check.json").exists()
    assert not Path(".review-package-readiness").exists()


def test_no_v18_artifacts_created_default_output_dir(monkeypatch, capsys, tmp_path):
    import shutil
    if Path(".review-package-readiness").exists():
        shutil.rmtree(".review-package-readiness")
    if Path(".reviewer-handoff").exists():
        shutil.rmtree(".reviewer-handoff")

    db_path = tmp_path / "handoff_no_v18_default.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-010",
        source_endpoint_id="earth_search",
        run_id="handoff-no-v18-default-001",
        manifest_path="data/manifests/manifest-hash-010.json",
        run_status="new",
        aoi_hash="aoi-hash-no-v18-default",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    result = main([
        "reviewer-handoff-package",
        "--run-id", "handoff-no-v18-default-001",
        "--format", "json",
    ])
    assert result == 0
    try:
        assert (Path(".reviewer-handoff") / "reviewer_handoff_package.json").exists()
        assert not Path(".review-package-readiness").exists()
    finally:
        if Path(".reviewer-handoff").exists():
            shutil.rmtree(".reviewer-handoff")
        if Path(".review-package-readiness").exists():
            shutil.rmtree(".review-package-readiness")
