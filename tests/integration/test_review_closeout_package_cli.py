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


def test_happy_path_all_resolved(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_happy.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "closeout-happy-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "closeout-happy-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    # Approve all candidates via review decisions
    from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
    review_repo = ReviewRepository(db_path)
    queue = review_repo.list_review_queue(run_id="closeout-happy-001")
    for item in queue:
        review_repo.decide(
            candidate_id=item["candidate_id"],
            run_id="closeout-happy-001",
            reviewer_id="test-reviewer",
            decision="approve_for_archive_quote",
        )

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-happy-001",
        "--output-dir", str(out),
        "--format", "both",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] in ("pass", "warn")
    assert (out / "review_closeout_package.json").exists()
    assert (out / "review_closeout_package.md").exists()
    assert (out / "SHA256SUMS.txt").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 2

    json_report = json.loads((out / "review_closeout_package.json").read_text(encoding="utf-8"))
    assert json_report["schema"]["version"] == "v1.20.0"
    assert json_report["run_id"] == "closeout-happy-001"
    assert json_report["closeout"]["run_summary"]["run_id"] == "closeout-happy-001"
    assert json_report["closeout"]["review_summary"]["approved_for_archive_quote"] > 0
    assert json_report["closeout"]["unresolved_candidates"] == []
    approved = json_report["closeout"]["approved_candidates"]
    assert len(approved) > 0
    assert "is_landscape_scale" in approved[0]
    assert approved[0]["landscape_scale_threshold_m2"] == 250000.0
    assert approved[0]["landscape_scale_area_ha"] > 25.0
    assert approved[0]["is_landscape_scale"] is True
    assert approved[0]["reviewer_review_track"] == "landscape_scale_separate_review"
    assert approved[0]["reviewer_rubric_label"] == "Landscape-scale candidate"
    assert "25 ha" in approved[0]["reviewer_rubric_guidance"]
    assert (
        approved[0]["landscape_scale_closeout_path"]
        == "landscape_scale_paid_escalation_requires_context_review"
    )
    assert (
        approved[0]["landscape_scale_closeout_label"]
        == "Landscape-scale paid escalation requires context review"
    )
    assert "context review" in approved[0]["landscape_scale_closeout_guidance"]
    assert "paid imagery" in approved[0]["landscape_scale_closeout_guidance"]
    landscape_summary = json_report["closeout"]["landscape_scale_closeout_summary"]
    assert landscape_summary["landscape_scale_candidate_count"] > 0
    assert landscape_summary["landscape_scale_approved_for_archive_quote_count"] > 0
    assert landscape_summary["landscape_scale_closeout_requires_context_review_count"] > 0
    assert landscape_summary["landscape_scale_closeout_ready"] is True


def test_missing_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_missing.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-missing-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("not found" in f for f in payload["failures"])
    assert (out / "review_closeout_package.json").exists()


def test_legal_blocked_run(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_legal.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-003",
        source_endpoint_id="earth_search",
        run_id="closeout-legal-fail-001",
        manifest_path="data/manifests/manifest-hash-003.json",
        run_status="completed",
        aoi_hash="aoi-hash-legal",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_fail(),
    )

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-legal-fail-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("legal gate" in f.lower() for f in payload["failures"])


def test_unresolved_candidates_warn(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_unresolved.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "closeout-unresolved-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "closeout-unresolved-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-unresolved-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    json_report = json.loads((out / "review_closeout_package.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "warn"
    assert any("unresolved" in w.lower() for w in json_report["warnings"])
    assert len(json_report["closeout"]["unresolved_candidates"]) > 0
    unresolved = json_report["closeout"]["unresolved_candidates"]
    landscape_unresolved = [c for c in unresolved if c["is_landscape_scale"] is True]
    assert landscape_unresolved
    assert (
        landscape_unresolved[0]["landscape_scale_closeout_path"]
        == "landscape_scale_unresolved"
    )
    assert (
        landscape_unresolved[0]["landscape_scale_closeout_label"]
        == "Landscape-scale unresolved"
    )
    assert "context review" in landscape_unresolved[0]["landscape_scale_closeout_guidance"]
    assert "paid escalation" in landscape_unresolved[0]["landscape_scale_closeout_guidance"]
    landscape_summary = json_report["closeout"]["landscape_scale_closeout_summary"]
    assert landscape_summary["landscape_scale_unresolved_count"] > 0
    assert landscape_summary["landscape_scale_closeout_ready"] is False


def test_unresolved_candidates_fail_with_require_all_resolved(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_required.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main([
        "create-run",
        "--run-id", "closeout-required-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "closeout-required-001"]) == 0
    execute_payload = json.loads(capsys.readouterr().out)
    assert execute_payload["candidate_count"] > 0

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-required-001",
        "--output-dir", str(out),
        "--format", "json",
        "--require-all-resolved",
    ])
    assert result != 0
    json_report = json.loads((out / "review_closeout_package.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "fail"
    assert any("unresolved" in f.lower() for f in json_report["failures"])
    landscape_summary = json_report["closeout"]["landscape_scale_closeout_summary"]
    assert landscape_summary["landscape_scale_unresolved_count"] > 0
    assert landscape_summary["landscape_scale_closeout_ready"] is False


def test_existing_export_records_warn(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_export.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-004",
        source_endpoint_id="earth_search",
        run_id="closeout-export-001",
        manifest_path="data/manifests/manifest-hash-004.json",
        run_status="completed",
        aoi_hash="aoi-hash-export",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )
    # Insert a dummy export record
    from lawful_anomaly_screening.db.sqlite import connect
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO export_records (export_record_id, run_id, audience, precision_tier, artifact_name, bundle_name, artifact_path, exact_coordinates_included)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("exp-001", "closeout-export-001", "public", "obfuscated", "artifact.json", "bundle.zip", "exports/public/artifact.json", 0),
        )
        conn.commit()

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-export-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    json_report = json.loads((out / "review_closeout_package.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "warn"
    assert any("export records exist" in w.lower() for w in json_report["warnings"])


def test_possible_duplicate_warn(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_dup.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-005",
        source_endpoint_id="earth_search",
        run_id="closeout-dup-001",
        manifest_path="data/manifests/manifest-hash-005.json",
        run_status="completed",
        aoi_hash="aoi-hash-dup",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )
    # Insert an approved candidate with possible_duplicate=1
    from lawful_anomaly_screening.db.sqlite import connect
    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO candidate_polygons (candidate_id, run_id, polygonization_manifest_cache_key, source_scene_manifest_hash, source_endpoint_id, parent_tile_id, source_scene_ids_json, current_state, bounds_json, centroid_json, area_m2, perimeter_m, pixel_count, boundary_touching, possible_duplicate, duplicate_resolution_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cand-dup-001", "closeout-dup-001", "key-001", "manifest-hash-005", "earth_search", "tile-001", '["s1"]', "approved_for_archive_quote", "{}", "{}", 100.0, 40.0, 100, 0, 1, "none"),
        )
        conn.execute(
            """
            INSERT INTO candidate_scores (candidate_id, run_id, polygonization_manifest_cache_key, source_scene_manifest_hash, source_endpoint_id, parent_tile_id, parent_tile_score, texture_support, compactness_support, polygon_object_score, candidate_score, score_breakdown_json, contribution_sum, integrity_delta, integrity_within_tolerance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("cand-dup-001", "closeout-dup-001", "key-001", "manifest-hash-005", "earth_search", "tile-001", 0.5, 0.1, 0.1, 0.5, 0.5, "{}", 1.0, 0.0, 1),
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-dup-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    json_report = json.loads((out / "review_closeout_package.json").read_text(encoding="utf-8"))
    assert json_report["status"] == "warn"
    assert any("possible_duplicate" in w.lower() for w in json_report["warnings"])


def test_format_json_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_json.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-006",
        source_endpoint_id="earth_search",
        run_id="closeout-json-001",
        manifest_path="data/manifests/manifest-hash-006.json",
        run_status="completed",
        aoi_hash="aoi-hash-json",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-json-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    assert (out / "review_closeout_package.json").exists()
    assert not (out / "review_closeout_package.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_format_markdown_only(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_md.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-007",
        source_endpoint_id="earth_search",
        run_id="closeout-md-001",
        manifest_path="data/manifests/manifest-hash-007.json",
        run_status="completed",
        aoi_hash="aoi-hash-md",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-md-001",
        "--output-dir", str(out),
        "--format", "markdown",
    ])
    assert result == 0
    assert not (out / "review_closeout_package.json").exists()
    assert (out / "review_closeout_package.md").exists()
    sums_lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(sums_lines) == 1


def test_no_sensitive_geometry(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_nosens.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-008",
        source_endpoint_id="earth_search",
        run_id="closeout-nosens-001",
        manifest_path="data/manifests/manifest-hash-008.json",
        run_status="completed",
        aoi_hash="aoi-hash-nosens",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-nosens-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0
    json_text = (out / "review_closeout_package.json").read_text(encoding="utf-8")
    assert "centroid" not in json_text.lower()
    assert "bounds" not in json_text.lower()
    assert "geometry" not in json_text.lower()
    assert "coordinates" not in json_text.lower()
    assert "bbox" not in json_text.lower()
    assert "exact_coordinate" not in json_text.lower()


def test_no_db_mutation(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "closeout_mutation.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-009",
        source_endpoint_id="earth_search",
        run_id="closeout-mutation-001",
        manifest_path="data/manifests/manifest-hash-009.json",
        run_status="completed",
        aoi_hash="aoi-hash-mutation",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )

    before_hash = _file_hash(db_path)

    out = tmp_path / "closeout-out"
    result = main([
        "review-closeout-package",
        "--run-id", "closeout-mutation-001",
        "--output-dir", str(out),
        "--format", "json",
    ])
    assert result == 0

    after_hash = _file_hash(db_path)
    assert before_hash == after_hash
