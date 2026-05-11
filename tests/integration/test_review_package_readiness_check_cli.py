import hashlib
import json
from pathlib import Path

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
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
    db_path = tmp_path / "readiness_candidates.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "readiness-candidates-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "readiness-candidates-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-candidates-001",
        "--output-dir", str(out),
        "--format", "both",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] in ("pass", "warn")
    assert (out / "review_package_readiness_check.json").exists()
    assert (out / "review_package_readiness_check.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2

    json_report = json.loads((out / "review_package_readiness_check.json").read_text(encoding="utf-8"))
    assert json_report["schema"]["version"] == "v1.18.0"
    assert json_report["run_id"] == "readiness-candidates-001"
    assert json_report["checks"]["run_exists"] is True
    assert json_report["checks"]["candidate_count"] > 0


def test_missing_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_missing.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-missing-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("not found" in f for f in payload["failures"])
    assert (out / "review_package_readiness_check.json").exists()


def test_legal_blocked_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_legal.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-003",
        source_endpoint_id="earth_search",
        run_id="readiness-legal-fail-001",
        manifest_path="data/manifests/manifest-hash-003.json",
        run_status="completed",
        aoi_hash="aoi-hash-legal",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_fail(),
    )

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-legal-fail-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("legal gate" in f.lower() for f in payload["failures"])


def test_candidates_exist_but_queue_empty(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_queue.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "readiness-queue-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "readiness-queue-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    # Reject all candidates to empty the review queue
    review_repo = ReviewRepository(db_path)
    queue = review_repo.list_review_queue(run_id="readiness-queue-001")
    for item in queue:
        review_repo.decide(
            candidate_id=item["candidate_id"],
            run_id="readiness-queue-001",
            reviewer_id="test-reviewer",
            decision="reject",
        )

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-queue-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("review queue is empty" in w.lower() for w in payload["warnings"])


def test_artifact_root_missing(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_art.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-004",
        source_endpoint_id="earth_search",
        run_id="readiness-art-001",
        manifest_path="data/manifests/manifest-hash-004.json",
        run_status="completed",
        aoi_hash="aoi-hash-art",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-art-001",
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
    db_path = tmp_path / "readiness_safe.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-005",
        source_endpoint_id="earth_search",
        run_id="readiness-safe-001",
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

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-safe-001",
        "--artifact-root", str(artifact_root),
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "warn"
    assert any("exact" in w.lower() and "public" in w.lower() for w in payload["warnings"])


def test_format_json_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_json.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-006",
        source_endpoint_id="earth_search",
        run_id="readiness-json-001",
        manifest_path="data/manifests/manifest-hash-006.json",
        run_status="new",
        aoi_hash="aoi-hash-json",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-json-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    assert (out / "review_package_readiness_check.json").exists()
    assert not (out / "review_package_readiness_check.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_markdown_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_md.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-007",
        source_endpoint_id="earth_search",
        run_id="readiness-md-001",
        manifest_path="data/manifests/manifest-hash-007.json",
        run_status="new",
        aoi_hash="aoi-hash-md",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-md-001",
        "--output-dir", str(out),
        "--format", "markdown",
    ])
    assert result == 0
    assert not (out / "review_package_readiness_check.json").exists()
    assert (out / "review_package_readiness_check.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_no_db_mutation(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_mutation.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-008",
        source_endpoint_id="earth_search",
        run_id="readiness-mutation-001",
        manifest_path="data/manifests/manifest-hash-008.json",
        run_status="new",
        aoi_hash="aoi-hash-mutation",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    before_hash = _file_hash(db_path)

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-mutation-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0

    after_hash = _file_hash(db_path)
    assert before_hash == after_hash


def test_geojson_count_separate_from_json(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "readiness_geojson.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-009",
        source_endpoint_id="earth_search",
        run_id="readiness-geojson-001",
        manifest_path="data/manifests/manifest-hash-009.json",
        run_status="new",
        aoi_hash="aoi-hash-geojson",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "data.geojson").write_text('{"type": "FeatureCollection"}', encoding="utf-8")
    (artifact_root / "manifest.json").write_text('{"ok": true}', encoding="utf-8")

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-geojson-001",
        "--artifact-root", str(artifact_root),
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    json_report = json.loads((out / "review_package_readiness_check.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "pass"
    artifact_check = json_report["checks"]["artifact_check"]
    assert artifact_check["file_counts"]["geojson"] == 1
    assert artifact_check["file_counts"]["json"] == 1


def test_db_read_failure(monkeypatch, capsys, tmp_path):
    # Use a non-existent DB path to force a read failure
    db_path = tmp_path / "nonexistent" / "readiness.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    out = tmp_path / "readiness-out"
    result = main([
        "review-package-readiness-check",
        "--run-id", "readiness-dbfail-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("db read failed" in f.lower() for f in payload["failures"])
    assert (out / "review_package_readiness_check.json").exists()
    # Ensure DB file was not created
    assert not db_path.exists()
