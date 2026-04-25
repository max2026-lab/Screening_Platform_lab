import io
import json
from contextlib import redirect_stdout

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db
from lawful_anomaly_screening.orchestration.scaffold_run import scaffold_run_for_run_id


def _legal_gate_pass() -> dict:
    return {
        "attestation_status": "present",
        "geofence_status": "clear",
        "decision": "pass",
        "reason": "legal gate passed",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _bootstrap_scaffolded_run(db_path, cache_root, run_id: str) -> dict:
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id=run_id,
        manifest_path="data/manifests/manifest-hash-001.json",
        aoi_hash="aoi-hash-001",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=_legal_gate_pass(),
    )
    return scaffold_run_for_run_id(
        db_path,
        run_id=run_id,
        cache_root=cache_root,
    )


def test_calibration_pack_cli_is_ready_after_review_export_and_comparison(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "calibration-pack.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    run_1_summary = _bootstrap_scaffolded_run(db_path, cache_root, "run-001")
    _bootstrap_scaffolded_run(db_path, cache_root, "run-002")
    approved_candidate_ids = run_1_summary["candidate_ids"][:10]
    watched_candidate_ids = run_1_summary["candidate_ids"][10:15]

    review_repository = ReviewRepository(db_path)
    for candidate_id in approved_candidate_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id="run-001",
            reviewer_id="reviewer-001",
            decision="approve_for_archive_quote",
            note="approved for calibration readiness",
        )
    for candidate_id in watched_candidate_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id="run-001",
            reviewer_id="reviewer-001",
            decision="watch",
            note="watchlisted for calibration readiness",
        )

    export_repository = ExportRepository(db_path, export_root=tmp_path)
    export_payload = export_repository.persist_export(
        run_id="run-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=export_repository.fetch_export_candidates("run-001"),
    )

    output = io.StringIO()
    with redirect_stdout(output):
        assert (
            main(
                [
                    "calibration-pack",
                    "--run-id",
                    "run-001",
                    "--comparison-run-id",
                    "run-002",
                ]
            )
            == 0
        )
    pack = json.loads(output.getvalue())

    assert pack["status"] == "ready"
    assert pack["run_id"] == "run-001"
    assert pack["processing_baseline_id"] == "baseline_v1_5_default"
    assert pack["score_formula_version"] == "v1.5.1-phase0"
    assert pack["legal_gate"]["decision"] == "pass"
    assert pack["candidate_count"] == len(run_1_summary["candidate_ids"])
    assert pack["reviewed_candidate_count"] == len(approved_candidate_ids) + len(
        watched_candidate_ids
    )
    assert pack["approved_candidate_count"] == len(approved_candidate_ids)
    assert pack["watched_candidate_count"] == len(watched_candidate_ids)
    assert pack["review_coverage_rate"] == 1.0
    assert pack["top20_review_coverage_rate"] == 1.0
    assert pack["export_audit_ready"] is True
    assert (
        pack["latest_export_audit_manifest_hash"]
        == (export_payload["audit_manifest"]["audit_manifest_hash"])
    )
    assert pack["reproducibility_summary"]["status"] == "pass"
    assert pack["reasons"] == ["Calibration readiness checks passed"]
    assert pack["calibration_policy_id"] == "calibration_policy_v1_0_default"
    assert pack["calibration_policy"]["review_coverage_minimum_rate"] == 0.20
    assert pack["calibration_policy"]["requires_export_audit_manifest"] is True
    assert pack["threshold_policy_source"] is not None


def test_calibration_pack_markdown_is_operator_readable(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-pack-markdown.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _bootstrap_scaffolded_run(db_path, cache_root, "run-001")

    output = io.StringIO()
    with redirect_stdout(output):
        assert (
            main(
                [
                    "calibration-pack",
                    "--run-id",
                    "run-001",
                    "--output",
                    "markdown",
                ]
            )
            == 0
        )
    markdown = output.getvalue()

    assert "# Calibration Evidence Pack" in markdown
    assert "Status: `incomplete`" in markdown
    assert "## Readiness Checks" in markdown
    assert "## Reasons" in markdown
    assert "Reproducibility comparison run not supplied" in markdown
