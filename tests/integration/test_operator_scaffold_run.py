from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.settings import REPO_ROOT


def test_operator_scaffold_run_populates_review_export_paid_and_acceptance_flows(
    monkeypatch,
    tmp_path,
    capsys,
):
    db_path = tmp_path / "operator.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"
    common_args = [
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]

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
            *common_args,
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
            *common_args,
        ]
    ) == 0
    create_run_2_payload = json.loads(capsys.readouterr().out)
    expected_source_scene_ids = None

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
    expected_source_scene_ids = run_2_candidate_payload["candidate"]["source_scene_ids"]
    assert run_2_candidate_payload["candidate"]["current_state"] == "pending_review"
    assert len(run_2_candidate_payload["candidate"]["bounds"]) == 4
    assert len(run_2_candidate_payload["candidate"]["centroid"]) == 2
    assert run_2_candidate_payload["candidate"]["clipped_geometry"]["type"] == "MultiPolygon"
    assert expected_source_scene_ids
    assert isinstance(run_2_candidate_payload["candidate"]["boundary_touching"], int)

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
    assert len(export_payload["candidates"][0]["bounds"]) == 4
    assert len(export_payload["candidates"][0]["centroid"]) == 2
    assert export_payload["candidates"][0]["clipped_geometry"]["type"] == "MultiPolygon"
    assert export_payload["candidates"][0]["source_scene_ids"] == expected_source_scene_ids
    assert isinstance(export_payload["candidates"][0]["boundary_touching"], bool)
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


def test_operator_cli_commands_work_from_outside_repo_root(tmp_path):
    db_path = tmp_path / "operator-outside-cwd.sqlite3"
    outside_cwd = tmp_path / "outside-cwd"
    outside_cwd.mkdir()

    env = os.environ.copy()
    env["LAWFUL_ANOMALY_DB_PATH"] = str(db_path)

    def run_cli(*args: str) -> str:
        completed = subprocess.run(
            [sys.executable, "-m", "lawful_anomaly_screening.cli", *args],
            cwd=outside_cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout

    assert run_cli("init-db").strip() == "ok"

    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi.geojson"
    create_run_payload = json.loads(
        run_cli(
            "create-run",
            "--attestation",
            "present",
            "--geofence",
            "clear",
            "--run-id",
            "run-001",
            "--aoi-path", str(aoi_path),
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31",
        )
    )
    scaffold_run_payload = json.loads(run_cli("scaffold-run", "--run-id", "run-001"))
    execute_run_payload = json.loads(run_cli("execute-run", "--run-id", "run-001"))
    review_show_payload = json.loads(
        run_cli("review-show", "--candidate-id", execute_run_payload["top_candidate_id"])
    )
    export_payload = json.loads(
        run_cli(
            "export-create",
            "--run-id",
            "run-001",
            "--audience",
            "report_pdf",
            "--requested-precision",
            "restricted",
        )
    )

    assert create_run_payload["run_id"] == "run-001"
    assert scaffold_run_payload["candidate_count"] > 0
    assert execute_run_payload["run_metadata"]["status"] == "review_ready"
    assert execute_run_payload["run_metadata"]["cache_status"] == "warm"
    assert execute_run_payload["scene_summary"]["scene_count"] > 0
    assert execute_run_payload["scene_summary"]["start_date"] == "2024-01-01"
    assert execute_run_payload["scene_summary"]["end_date"] == "2024-03-31"
    assert review_show_payload["candidate"]["source_scene_ids"] == execute_run_payload["scene_summary"]["scene_ids"]
    assert execute_run_payload["aoi_execution_geometry"]["tile_count"] == execute_run_payload["tile_count"]
    assert execute_run_payload["aoi_execution_geometry"]["selected_tile_count"] == execute_run_payload["selected_tile_count"]
    assert len(execute_run_payload["aoi_execution_geometry"]["derived_tile_bbox"]) == 4
    assert len(review_show_payload["candidate"]["bounds"]) == 4
    assert len(review_show_payload["candidate"]["centroid"]) == 2
    assert review_show_payload["candidate"]["clipped_geometry"]["type"] == "MultiPolygon"
    assert isinstance(review_show_payload["candidate"]["boundary_touching"], int)
    assert export_payload["run_id"] == "run-001"
    assert export_payload["precision_tier"] == "restricted"
    assert len(export_payload["candidates"][0]["bounds"]) == 4
    assert len(export_payload["candidates"][0]["centroid"]) == 2
    assert export_payload["candidates"][0]["clipped_geometry"]["type"] == "MultiPolygon"
    assert export_payload["candidates"][0]["source_scene_ids"] == execute_run_payload["scene_summary"]["scene_ids"]
    assert isinstance(export_payload["candidates"][0]["boundary_touching"], bool)
    assert (outside_cwd / export_payload["artifact_path"]).is_file()
    assert not (outside_cwd / "config").exists()
    assert (REPO_ROOT / "config" / "sources" / "endpoints.json").is_file()
