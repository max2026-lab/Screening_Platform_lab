from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.settings import REPO_ROOT, PACKAGE_ROOT


def _installed_cli_command() -> str:
    return "lawful-anomaly.exe" if os.name == "nt" else "lawful-anomaly"


def test_operator_scaffold_run_populates_review_export_paid_and_acceptance_flows(
    monkeypatch,
    tmp_path,
    capsys,
):
    db_path = tmp_path / "operator.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"
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
    assert create_run_1_payload["legal_gate"]["decision"] == "pass"
    assert create_run_2_payload["legal_gate"]["decision"] == "pass"

    assert main(["scaffold-run", "--run-id", "run-001"]) == 0
    scaffold_run_1_payload = json.loads(capsys.readouterr().out)
    assert scaffold_run_1_payload["candidate_count"] > 0
    assert scaffold_run_1_payload["tile_count"] > 0
    assert scaffold_run_1_payload["selected_tile_count"] > 0
    assert "candidate_generation_diagnostics" in scaffold_run_1_payload
    assert (
        scaffold_run_1_payload["candidate_generation_diagnostics"]["final_candidate_count"]
        == scaffold_run_1_payload["candidate_count"]
    )
    assert (
        scaffold_run_1_payload["candidate_generation_diagnostics"]["zero_candidate_reason"]
        == "candidates_generated"
    )

    assert main(["scaffold-run", "--run-id", "run-002"]) == 0
    scaffold_run_2_payload = json.loads(capsys.readouterr().out)
    assert scaffold_run_2_payload["candidate_count"] > 0
    assert set(scaffold_run_1_payload["candidate_ids"]).isdisjoint(scaffold_run_2_payload["candidate_ids"])

    assert main(["review-queue", "--run-id", "run-001", "--limit", "10"]) == 0
    review_queue_run_1_payload = json.loads(capsys.readouterr().out)
    assert review_queue_run_1_payload
    assert "is_landscape_scale" in review_queue_run_1_payload[0]
    assert review_queue_run_1_payload[0]["landscape_scale_threshold_m2"] == 250000.0
    assert review_queue_run_1_payload[0]["landscape_scale_area_ha"] > 25.0
    assert review_queue_run_1_payload[0]["is_landscape_scale"] is True
    assert review_queue_run_1_payload[0]["reviewer_review_track"] == "landscape_scale_separate_review"
    assert review_queue_run_1_payload[0]["reviewer_rubric_label"] == "Landscape-scale candidate"
    assert "25 ha" in review_queue_run_1_payload[0]["reviewer_rubric_guidance"]

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
    assert review_decision_payload["candidate"]["source_scene_ids"]
    assert review_decision_payload["candidate"]["source_scenes"]
    assert [
        scene["scene_id"] for scene in review_decision_payload["candidate"]["source_scenes"]
    ] == review_decision_payload["candidate"]["source_scene_ids"]

    assert main(["review-show", "--candidate-id", approved_candidate_id]) == 0
    run_1_candidate_payload = json.loads(capsys.readouterr().out)
    assert "is_landscape_scale" in run_1_candidate_payload["candidate"]
    assert run_1_candidate_payload["candidate"]["landscape_scale_threshold_m2"] == 250000.0
    assert run_1_candidate_payload["candidate"]["landscape_scale_area_ha"] > 25.0
    assert run_1_candidate_payload["candidate"]["is_landscape_scale"] is True
    assert run_1_candidate_payload["candidate"]["reviewer_review_track"] == "landscape_scale_separate_review"
    assert run_1_candidate_payload["candidate"]["reviewer_rubric_label"] == "Landscape-scale candidate"
    assert "25 ha" in run_1_candidate_payload["candidate"]["reviewer_rubric_guidance"]

    assert main(["review-show", "--candidate-id", run_2_top_candidate_id]) == 0
    run_2_candidate_payload = json.loads(capsys.readouterr().out)
    expected_source_scene_ids = run_2_candidate_payload["candidate"]["source_scene_ids"]
    assert run_2_candidate_payload["candidate"]["current_state"] == "pending_review"
    assert len(run_2_candidate_payload["candidate"]["bounds"]) == 4
    assert len(run_2_candidate_payload["candidate"]["centroid"]) == 2
    assert run_2_candidate_payload["candidate"]["clipped_geometry"]["type"] == "MultiPolygon"
    assert expected_source_scene_ids
    assert isinstance(run_2_candidate_payload["candidate"]["boundary_touching"], int)
    assert run_1_candidate_payload["candidate"]["scoring_explanation"]["rank"] == 1
    assert run_2_candidate_payload["candidate"]["scoring_explanation"]["rank"] == 1
    assert run_1_candidate_payload["candidate"]["scoring_explanation"]["score_formula_version"] == "v1.5.1-phase0"
    assert run_2_candidate_payload["candidate"]["scoring_explanation"]["score_formula_version"] == "v1.5.1-phase0"
    assert run_2_candidate_payload["candidate"]["source_scenes"]
    assert [
        scene["scene_id"] for scene in run_2_candidate_payload["candidate"]["source_scenes"]
    ] == run_2_candidate_payload["candidate"]["source_scene_ids"]
    ex1 = dict(run_1_candidate_payload["candidate"]["scoring_explanation"])
    ex2 = dict(run_2_candidate_payload["candidate"]["scoring_explanation"])
    ex1.pop("parent_tile_rank", None)
    ex2.pop("parent_tile_rank", None)
    assert ex1 == ex2

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
    assert export_payload["run_metadata"]["legal_gate"]["decision"] == "pass"
    assert export_payload["exact_coordinates_included"] is False
    assert export_payload["audit_manifest"]["run_id"] == "run-001"
    assert export_payload["audit_manifest"]["precision_tier"] == "restricted"
    assert export_payload["audit_manifest"]["processing_baseline_id"] == "baseline_v1_5_default"
    assert export_payload["audit_manifest"]["score_formula_version"] == "v1.5.1-phase0"
    assert export_payload["audit_manifest"]["source_scene_manifest_hash"] == create_run_1_payload["source_scene_manifest_hash"]
    assert export_payload["audit_manifest"]["legal_gate"]["decision"] == "pass"
    assert export_payload["audit_manifest"]["composite_quality"] == export_payload["run_metadata"]["composite_quality"]
    assert export_payload["audit_manifest"]["candidate_count"] == len(export_payload["candidates"])
    assert export_payload["audit_manifest"]["candidate_ids"] == sorted(
        candidate["candidate_id"] for candidate in export_payload["candidates"]
    )
    assert export_payload["audit_manifest"]["top_candidate_id"] == review_queue_run_1_payload[0]["candidate_id"]
    assert export_payload["audit_manifest"]["candidate_score_formula_versions"] == ["v1.5.1-phase0"]
    assert export_payload["audit_manifest"]["audit_manifest_hash"]
    assert export_payload["candidates"]
    assert "is_landscape_scale" in export_payload["candidates"][0]
    assert export_payload["candidates"][0]["landscape_scale_threshold_m2"] == 250000.0
    assert export_payload["candidates"][0]["landscape_scale_area_ha"] > 25.0
    assert export_payload["candidates"][0]["is_landscape_scale"] is True
    assert export_payload["candidates"][0]["reviewer_review_track"] == "landscape_scale_separate_review"
    assert export_payload["candidates"][0]["reviewer_rubric_label"] == "Landscape-scale candidate"
    assert "25 ha" in export_payload["candidates"][0]["reviewer_rubric_guidance"]
    assert len(export_payload["candidates"][0]["bounds"]) == 4
    assert len(export_payload["candidates"][0]["centroid"]) == 2
    assert export_payload["candidates"][0]["clipped_geometry"]["type"] == "MultiPolygon"
    assert export_payload["candidates"][0]["source_scene_ids"]
    assert export_payload["candidates"][0]["source_scenes"]
    assert export_payload["candidates"][0]["scoring_explanation"]["score_formula_version"] == "v1.5.1-phase0"
    assert [
        scene["scene_id"] for scene in export_payload["candidates"][0]["source_scenes"]
    ] == export_payload["candidates"][0]["source_scene_ids"]
    assert len({tuple(candidate["source_scene_ids"]) for candidate in export_payload["candidates"]}) > 1
    assert isinstance(export_payload["candidates"][0]["boundary_touching"], bool)
    assert export_path.exists()
    assert {candidate["candidate_id"] for candidate in export_payload["candidates"]} == set(
        scaffold_run_1_payload["candidate_ids"]
    )

    assert main(
        [
            "export-create",
            "--run-id",
            "run-002",
            "--audience",
            "report_pdf",
            "--requested-precision",
            "restricted",
        ]
    ) == 0
    export_run_2_payload = json.loads(capsys.readouterr().out)

    def _strip_parent_tile_rank(candidate: dict) -> str:
        exp = dict(candidate["scoring_explanation"])
        exp.pop("parent_tile_rank", None)
        return json.dumps(exp, sort_keys=True)

    assert sorted(
        (
            _strip_parent_tile_rank(candidate),
            tuple(candidate["source_scene_ids"]),
            tuple(
                (
                    scene["scene_id"],
                    scene["acquired_at"],
                    scene["cloud_cover"],
                )
                for scene in candidate["source_scenes"]
            ),
        )
        for candidate in export_payload["candidates"]
    ) == sorted(
        (
            _strip_parent_tile_rank(candidate),
            tuple(candidate["source_scene_ids"]),
            tuple(
                (
                    scene["scene_id"],
                    scene["acquired_at"],
                    scene["cloud_cover"],
                )
                for scene in candidate["source_scenes"]
            ),
        )
        for candidate in export_run_2_payload["candidates"]
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
    assert paid_quote_payload["paid_landscape_scale_warning"] is True
    assert (
        paid_quote_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )
    assert paid_quote_payload["paid_landscape_scale_context_review_recommended"] is True
    assert "warning-only" in paid_quote_payload["paid_landscape_scale_warning_message"]

    assert main(
        [
            "paid-quote-show",
            "--provider-quote-id",
            "quote-smoke-001",
        ]
    ) == 0
    paid_quote_show_payload = json.loads(capsys.readouterr().out)
    assert paid_quote_show_payload["paid_landscape_scale_warning"] is True
    assert (
        paid_quote_show_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )

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
    assert paid_order_payload["paid_landscape_scale_warning"] is True
    assert (
        paid_order_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )
    assert paid_order_payload["paid_landscape_scale_context_review_recommended"] is True

    assert main(
        [
            "paid-order-show",
            "--provider-order-id",
            "order-smoke-001",
        ]
    ) == 0
    paid_order_show_payload = json.loads(capsys.readouterr().out)
    assert paid_order_show_payload["paid_landscape_scale_warning"] is True
    assert (
        paid_order_show_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )

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
            "acceptance-check",
            "--run-id",
            "run-001",
            "--aoi-area-km2",
            "100",
        ]
    ) == 1
    acceptance_without_comparison = json.loads(capsys.readouterr().out)
    assert acceptance_without_comparison["run_id"] == "run-001"
    assert acceptance_without_comparison["status"] == "fail"
    assert acceptance_without_comparison["legal_gate"]["decision"] == "pass"
    assert acceptance_without_comparison["composite_quality"] == export_payload["run_metadata"]["composite_quality"]
    assert acceptance_without_comparison["processing_baseline_id"] == "baseline_v1_5_default"
    assert acceptance_without_comparison["score_formula_version"] == "v1.5.1-phase0"
    assert acceptance_without_comparison["candidate_count"] == run_1_kpi_summary_payload["candidate_count"]
    assert acceptance_without_comparison["review_state_counts"]["approved_for_archive_quote"] == 1
    assert acceptance_without_comparison["export_audit_ready"] is True
    assert acceptance_without_comparison["latest_export_audit_manifest_hash"] == (
        export_payload["audit_manifest"]["audit_manifest_hash"]
    )
    assert acceptance_without_comparison["reproducibility_summary"] is None
    assert acceptance_without_comparison["source_scene_manifest_hash"] == (
        create_run_1_payload["source_scene_manifest_hash"]
    )

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
    assert reproducibility_payload["baseline_run_id"] == "run-001"
    assert reproducibility_payload["comparison_run_id"] == "run-002"
    assert reproducibility_payload["same_processing_baseline"] is True
    assert reproducibility_payload["same_aoi_hash"] is True
    assert reproducibility_payload["same_date_window"] is True
    assert reproducibility_payload["same_source_scene_manifest_hash"] is True
    assert reproducibility_payload["baseline_candidate_count"] == scaffold_run_1_payload["candidate_count"]
    assert reproducibility_payload["comparison_candidate_count"] == scaffold_run_2_payload["candidate_count"]
    assert reproducibility_payload["added_candidate_ids"] == []
    assert reproducibility_payload["removed_candidate_ids"] == []
    assert reproducibility_payload["top10_stability_rate"] == 1.0
    assert reproducibility_payload["baseline_run"]["source_scene_manifest_hash"] == create_run_1_payload["source_scene_manifest_hash"]
    assert reproducibility_payload["comparison_run"]["source_scene_manifest_hash"] == create_run_2_payload["source_scene_manifest_hash"]
    assert reproducibility_payload["baseline_run"]["composite_quality"] is not None
    assert reproducibility_payload["comparison_run"]["composite_quality"] is not None

    assert main(
        [
            "acceptance-check",
            "--run-id",
            "run-001",
            "--aoi-area-km2",
            "100",
            "--comparison-run-id",
            "run-002",
        ]
    ) == 1
    acceptance_with_comparison = json.loads(capsys.readouterr().out)
    assert acceptance_with_comparison["status"] == "fail"
    assert acceptance_with_comparison["export_audit_ready"] is True
    assert acceptance_with_comparison["latest_export_audit_manifest_hash"] == (
        export_payload["audit_manifest"]["audit_manifest_hash"]
    )
    assert acceptance_with_comparison["reproducibility_summary"] == {
        "status": "pass",
        "top10_stability_rate": 1.0,
        "same_aoi_hash": True,
        "same_date_window": True,
        "same_source_scene_manifest_hash": True,
        "reasons": ["Deterministic checks stable"],
    }
    reproducibility_check_entry = next(
        check for check in acceptance_with_comparison["checks"] if check["name"] == "reproducibility"
    )
    assert reproducibility_check_entry["status"] == "pass"


def test_operator_cli_commands_work_from_outside_repo_root(tmp_path):
    db_path = tmp_path / "operator-outside-cwd.sqlite3"
    outside_cwd = tmp_path / "outside-cwd"
    outside_cwd.mkdir()

    env = os.environ.copy()
    env["LAWFUL_ANOMALY_DB_PATH"] = str(db_path)
    env.pop("PYTHONPATH", None)

    def run_cli(*args: str) -> str:
        completed = subprocess.run(
            [_installed_cli_command(), *args],
            cwd=outside_cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout

    assert run_cli("init-db").strip() == "ok"

    aoi_path = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_large.geojson"
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
    assert create_run_payload["legal_gate"]["decision"] == "pass"
    assert scaffold_run_payload["candidate_count"] > 0
    assert execute_run_payload["run_metadata"]["status"] == "review_ready"
    assert execute_run_payload["run_metadata"]["cache_status"] == "warm"
    assert execute_run_payload["run_metadata"]["legal_gate"]["decision"] == "pass"
    assert "candidate_generation_diagnostics" in execute_run_payload
    assert (
        execute_run_payload["candidate_generation_diagnostics"]["final_candidate_count"]
        == execute_run_payload["candidate_count"]
    )
    assert (
        execute_run_payload["candidate_generation_diagnostics"]["zero_candidate_reason"]
        == "candidates_generated"
    )
    assert (
        execute_run_payload["run_metadata"]["candidate_generation_diagnostics"]
        == execute_run_payload["candidate_generation_diagnostics"]
    )
    assert execute_run_payload["run_metadata"]["composite_quality"]["cloud_policy_decision"] in {"pass", "warn"}
    assert execute_run_payload["scene_summary"]["scene_count"] > 0
    assert execute_run_payload["scene_summary"]["composite_quality"] == execute_run_payload["run_metadata"]["composite_quality"]
    assert execute_run_payload["scene_summary"]["start_date"] == "2024-01-01"
    assert execute_run_payload["scene_summary"]["end_date"] == "2024-03-31"
    assert review_show_payload["candidate"]["source_scene_ids"]
    assert review_show_payload["candidate"]["source_scenes"]
    assert review_show_payload["candidate"]["scoring_explanation"]["candidate_score"] == (
        review_show_payload["candidate"]["candidate_score"]
    )
    assert [
        scene["scene_id"] for scene in review_show_payload["candidate"]["source_scenes"]
    ] == review_show_payload["candidate"]["source_scene_ids"]
    assert set(review_show_payload["candidate"]["source_scene_ids"]) < set(execute_run_payload["scene_summary"]["scene_ids"])
    assert execute_run_payload["aoi_execution_geometry"]["tile_count"] == execute_run_payload["tile_count"]
    assert execute_run_payload["aoi_execution_geometry"]["selected_tile_count"] == execute_run_payload["selected_tile_count"]
    assert len(execute_run_payload["aoi_execution_geometry"]["derived_tile_bbox"]) == 4
    assert len(review_show_payload["candidate"]["bounds"]) == 4
    assert len(review_show_payload["candidate"]["centroid"]) == 2
    assert review_show_payload["candidate"]["clipped_geometry"]["type"] == "MultiPolygon"
    assert isinstance(review_show_payload["candidate"]["boundary_touching"], int)
    assert export_payload["run_id"] == "run-001"
    assert export_payload["run_metadata"]["legal_gate"]["decision"] == "pass"
    assert export_payload["run_metadata"]["composite_quality"] == execute_run_payload["run_metadata"]["composite_quality"]
    assert export_payload["precision_tier"] == "restricted"
    assert export_payload["audit_manifest"]["legal_gate"]["decision"] == "pass"
    assert export_payload["audit_manifest"]["composite_quality"] == export_payload["run_metadata"]["composite_quality"]
    assert export_payload["audit_manifest"]["candidate_ids"] == sorted(
        candidate["candidate_id"] for candidate in export_payload["candidates"]
    )
    assert export_payload["audit_manifest"]["top_candidate_id"] == execute_run_payload["top_candidate_id"]
    assert len(export_payload["candidates"][0]["bounds"]) == 4
    assert len(export_payload["candidates"][0]["centroid"]) == 2
    assert export_payload["candidates"][0]["clipped_geometry"]["type"] == "MultiPolygon"
    top_export_candidate = next(
        candidate
        for candidate in export_payload["candidates"]
        if candidate["candidate_id"] == execute_run_payload["top_candidate_id"]
    )
    assert top_export_candidate["source_scene_ids"] == review_show_payload["candidate"]["source_scene_ids"]
    assert top_export_candidate["source_scenes"] == review_show_payload["candidate"]["source_scenes"]
    assert top_export_candidate["scoring_explanation"] == review_show_payload["candidate"]["scoring_explanation"]
    assert [
        scene["scene_id"] for scene in top_export_candidate["source_scenes"]
    ] == top_export_candidate["source_scene_ids"]
    assert set(top_export_candidate["source_scene_ids"]) < set(execute_run_payload["scene_summary"]["scene_ids"])
    assert all(
        [scene["scene_id"] for scene in candidate["source_scenes"]] == candidate["source_scene_ids"]
        for candidate in export_payload["candidates"]
    )
    top_points = [
        point
        for polygon in top_export_candidate["clipped_geometry"]["coordinates"]
        for ring in polygon
        for point in ring
    ]
    top_xs = [point[0] for point in top_points]
    top_ys = [point[1] for point in top_points]
    assert any(value != 0.0 for value in top_export_candidate["bounds"])
    assert top_export_candidate["bounds"] == [min(top_xs), min(top_ys), max(top_xs), max(top_ys)]
    assert top_export_candidate["bounds"][0] <= top_export_candidate["centroid"][0] <= top_export_candidate["bounds"][2]
    assert top_export_candidate["bounds"][1] <= top_export_candidate["centroid"][1] <= top_export_candidate["bounds"][3]
    assert len({tuple(candidate["source_scene_ids"]) for candidate in export_payload["candidates"]}) > 1
    assert isinstance(export_payload["candidates"][0]["boundary_touching"], bool)
    assert (outside_cwd / export_payload["artifact_path"]).is_file()
    assert not (outside_cwd / "config").exists()
    assert not (outside_cwd / "sitecustomize.py").exists()
    assert (PACKAGE_ROOT / "config" / "sources" / "endpoints.json").is_file()


def test_large_aoi_produces_more_tiles_than_small_aoi(monkeypatch, capsys, tmp_path):
    """Regression test: larger AOIs must produce materially more tiles than tiny AOIs."""
    db_path = tmp_path / "scaling.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    small_aoi = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_small.geojson"
    large_aoi = REPO_ROOT / "tests" / "fixtures" / "sample_aoi_field_trial_8.geojson"

    assert main(["init-db"]) == 0
    capsys.readouterr()

    # Small AOI
    assert main([
        "create-run",
        "--run-id", "small-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(small_aoi),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "small-001"]) == 0
    small_payload = json.loads(capsys.readouterr().out)

    # Large AOI
    assert main([
        "create-run",
        "--run-id", "large-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(large_aoi),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    capsys.readouterr()

    assert main(["execute-run", "--run-id", "large-001"]) == 0
    large_payload = json.loads(capsys.readouterr().out)

    print(f"small AOI tile_count={small_payload['tile_count']} selected_tile_count={small_payload['selected_tile_count']}")
    print(f"large AOI tile_count={large_payload['tile_count']} selected_tile_count={large_payload['selected_tile_count']}")

    assert large_payload["tile_count"] >= 30
    assert large_payload["tile_count"] > small_payload["tile_count"]
    assert large_payload["selected_tile_count"] > small_payload["selected_tile_count"]


def test_installed_operator_cli_proves_provider_fallback_via_endpoint_override(tmp_path):
    db_path = tmp_path / "operator-fallback.sqlite3"
    outside_cwd = tmp_path / "outside-cwd"
    outside_cwd.mkdir()
    endpoint_config_path = tmp_path / "fallback-endpoints.json"
    endpoint_config_path.write_text(
        json.dumps(
            {
                "primary": "sim_empty",
                "fallbacks": ["cdse"],
                "sim_empty": {
                    "provider": "simulator-empty",
                    "role": "primary",
                    "synchronous_only": True,
                },
                "cdse": {
                    "provider": "cdse",
                    "role": "fallback",
                    "synchronous_only": True,
                },
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["LAWFUL_ANOMALY_DB_PATH"] = str(db_path)
    env["LAWFUL_ANOMALY_ENDPOINTS_PATH"] = str(endpoint_config_path)
    env.pop("PYTHONPATH", None)

    def run_cli(*args: str) -> str:
        completed = subprocess.run(
            [_installed_cli_command(), *args],
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
            "--aoi-path",
            str(aoi_path),
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-03-31",
        )
    )
    execute_run_payload = json.loads(run_cli("execute-run", "--run-id", "run-001"))

    assert create_run_payload["run_id"] == "run-001"
    assert create_run_payload["source_endpoint_id"] == "cdse"
    assert create_run_payload["legal_gate"]["decision"] == "pass"
    assert create_run_payload["fallback_diagnostics"]["fallback_used"] is True
    assert create_run_payload["fallback_diagnostics"]["attempted_endpoint_ids"] == [
        "sim_empty",
        "cdse",
    ]
    assert create_run_payload["fallback_diagnostics"]["selected_endpoint_id"] == "cdse"
    assert execute_run_payload["source_endpoint_id"] == "cdse"
    assert execute_run_payload["run_metadata"]["source_endpoint_id"] == "cdse"
    assert execute_run_payload["run_metadata"]["legal_gate"]["decision"] == "pass"
    assert execute_run_payload["scene_summary"]["scene_ids"]
    assert all(scene_id.startswith("cdse-scene-") for scene_id in execute_run_payload["scene_summary"]["scene_ids"])
    assert not (outside_cwd / "config").exists()
    assert not (outside_cwd / "sitecustomize.py").exists()
