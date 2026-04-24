from __future__ import annotations

import json
from pathlib import Path

from lawful_anomaly_screening.cli import main


def test_operator_scaffold_run_populates_review_export_paid_and_acceptance_flows(
    monkeypatch,
    tmp_path,
    capsys,
):
    db_path = tmp_path / "operator.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    assert main(["init-db"]) == 0
    capsys.readouterr()

    assert main(
        [
            "create-run",
            "--attestation",
            "present",
            "--geofence",
            "clear",
            "--run-id",
            "run-001",
        ]
    ) == 0
    create_run_1_payload = json.loads(capsys.readouterr().out)

    assert main(
        [
            "create-run",
            "--attestation",
            "present",
            "--geofence",
            "clear",
            "--run-id",
            "run-002",
        ]
    ) == 0
    create_run_2_payload = json.loads(capsys.readouterr().out)

    assert create_run_1_payload["source_scene_manifest_hash"] == create_run_2_payload["source_scene_manifest_hash"]

    assert main(["scaffold-run", "--run-id", "run-001"]) == 0
    scaffold_run_1_payload = json.loads(capsys.readouterr().out)
    assert scaffold_run_1_payload["candidate_count"] > 0
    assert scaffold_run_1_payload["tile_count"] > 0
    assert scaffold_run_1_payload["selected_tile_count"] > 0

    assert main(["scaffold-run", "--run-id", "run-002"]) == 0
    scaffold_run_2_payload = json.loads(capsys.readouterr().out)
    assert scaffold_run_2_payload["candidate_count"] > 0
    assert set(scaffold_run_1_payload["candidate_ids"]).isdisjoint(scaffold_run_2_payload["candidate_ids"])

    assert main(["review-queue", "--run-id", "run-001", "--limit", "10"]) == 0
    review_queue_run_1_payload = json.loads(capsys.readouterr().out)
    assert review_queue_run_1_payload

    assert main(["review-queue", "--run-id", "run-002", "--limit", "10"]) == 0
    review_queue_run_2_payload = json.loads(capsys.readouterr().out)
    assert review_queue_run_2_payload

    approved_candidate_id = review_queue_run_1_payload[0]["candidate_id"]
    run_2_top_candidate_id = review_queue_run_2_payload[0]["candidate_id"]
    assert main(
        [
            "review-decide",
            "--candidate-id",
            approved_candidate_id,
            "--run-id",
            "run-001",
            "--reviewer-id",
            "reviewer-001",
            "--decision",
            "approve_for_archive_quote",
            "--note",
            "operator smoke",
        ]
    ) == 0
    review_decision_payload = json.loads(capsys.readouterr().out)
    assert review_decision_payload["candidate"]["current_state"] == "approved_for_archive_quote"

    assert main(["review-show", "--candidate-id", run_2_top_candidate_id]) == 0
    run_2_candidate_payload = json.loads(capsys.readouterr().out)
    assert run_2_candidate_payload["candidate"]["current_state"] == "pending_review"

    assert main(
        [
            "export-create",
            "--run-id",
            "run-001",
            "--audience",
            "report_pdf",
            "--requested-precision",
            "restricted",
        ]
    ) == 0
    export_payload = json.loads(capsys.readouterr().out)
    export_path = Path(export_payload["artifact_path"])
    assert export_payload["precision_tier"] == "restricted"
    assert export_payload["exact_coordinates_included"] is False
    assert export_payload["candidates"]
    assert export_path.exists()
    assert {candidate["candidate_id"] for candidate in export_payload["candidates"]} == set(
        scaffold_run_1_payload["candidate_ids"]
    )

    assert main(
        [
            "paid-quote-create",
            "--candidate-id",
            approved_candidate_id,
            "--provider-quote-id",
            "quote-smoke-001",
            "--amount",
            "149.5",
            "--credits",
            "88.0",
            "--currency",
            "usd",
            "--eula-reference",
            "eula-smoke-001",
            "--project-id",
            "project-smoke-001",
        ]
    ) == 0
    paid_quote_payload = json.loads(capsys.readouterr().out)
    assert paid_quote_payload["candidate_id"] == approved_candidate_id

    assert main(
        [
            "paid-order-create",
            "--candidate-id",
            approved_candidate_id,
            "--provider-quote-id",
            "quote-smoke-001",
            "--provider-order-id",
            "order-smoke-001",
            "--requested-by",
            "reviewer-001",
        ]
    ) == 0
    paid_order_payload = json.loads(capsys.readouterr().out)
    assert paid_order_payload["candidate_id"] == approved_candidate_id

    assert main(
        [
            "kpi-summary",
            "--run-id",
            "run-001",
            "--aoi-area-km2",
            "100",
            "--time-to-first-review-package-hours",
            "1.5",
        ]
    ) == 0
    run_1_kpi_summary_payload = json.loads(capsys.readouterr().out)
    assert run_1_kpi_summary_payload["candidate_count"] > 0
    assert run_1_kpi_summary_payload["paid_escalation_count"] == 1

    assert main(
        [
            "kpi-summary",
            "--run-id",
            "run-002",
            "--aoi-area-km2",
            "100",
            "--time-to-first-review-package-hours",
            "1.5",
        ]
    ) == 0
    run_2_kpi_summary_payload = json.loads(capsys.readouterr().out)
    assert run_2_kpi_summary_payload["candidate_count"] > 0
    assert run_2_kpi_summary_payload["paid_escalation_count"] == 0

    assert main(
        [
            "reproducibility-check",
            "--run-id",
            "run-001",
            "--comparison-run-id",
            "run-002",
        ]
    ) == 0
    reproducibility_payload = json.loads(capsys.readouterr().out)
    assert reproducibility_payload["status"] == "pass"
