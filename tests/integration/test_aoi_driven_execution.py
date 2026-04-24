import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.settings import Settings

def setup_mocks(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    mock_settings = Settings(db_path=db_path)
    monkeypatch.setattr("lawful_anomaly_screening.settings.load_settings", lambda: mock_settings)
    monkeypatch.setattr("lawful_anomaly_screening.cli.load_settings", lambda: mock_settings)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.run_pipeline.load_settings", lambda: mock_settings, raising=False)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.scaffold_run.load_settings", lambda: mock_settings, raising=False)
    return db_path

def test_create_and_execute_run_aoi(tmp_path, monkeypatch):
    db_path = setup_mocks(tmp_path, monkeypatch)
    
    aoi_path = tmp_path / "test_aoi.geojson"
    aoi_data = {
        "type": "Polygon",
        "coordinates": [[[3000, 1000], [4000, 1000], [4000, 2000], [3000, 2000], [3000, 1000]]]
    }
    aoi_path.write_text(json.dumps(aoi_data))

    # 1. create-run
    args = [
        "create-run",
        "--run-id", "test-run-001",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ]
    assert main(args) == 0
    
    # 2. execute-run (capture stdout)
    args = ["execute-run", "--run-id", "test-run-001"]
    f = io.StringIO()
    with redirect_stdout(f):
        assert main(args) == 0
    
    summary = json.loads(f.getvalue())
    assert "run_metadata" in summary
    assert summary["run_metadata"]["run_id"] == "test-run-001"
    assert summary["run_metadata"]["start_date"] == "2024-01-01"
    assert summary["run_metadata"]["status"] == "review_ready"
    assert summary["run_metadata"]["cache_status"] == "warm"
    assert summary["run_metadata"]["aoi_geometry"] == aoi_data
    assert summary["scene_summary"]["scene_count"] == 3
    assert len(summary["scene_summary"]["scene_ids"]) == 3
    assert summary["scene_summary"]["start_date"] == "2024-01-01"
    assert summary["scene_summary"]["end_date"] == "2024-03-31"
    assert summary["aoi_execution_geometry"]["aoi_bbox"] == [3000.0, 1000.0, 4000.0, 2000.0]
    assert summary["aoi_execution_geometry"]["tile_count"] == summary["tile_count"]
    assert summary["aoi_execution_geometry"]["selected_tile_count"] == summary["selected_tile_count"]
    assert len(summary["aoi_execution_geometry"]["derived_tile_bbox"]) == 4
    
    # 3. verify review-queue
    args = ["review-queue", "--run-id", "test-run-001"]
    f = io.StringIO()
    with redirect_stdout(f):
        main(args)
    
    queue = json.loads(f.getvalue())
    assert len(queue) > 0
    assert queue[0]["run_id"] == "test-run-001"

    persisted_scenes = ManifestRepository(db_path).list_scenes(
        summary["run_metadata"]["source_scene_manifest_hash"]
    )
    assert [scene["scene_id"] for scene in persisted_scenes] == summary["scene_summary"]["scene_ids"]


def test_same_bbox_different_geometry_changes_execute_run_layout(tmp_path, monkeypatch):
    setup_mocks(tmp_path, monkeypatch)

    left_aoi_path = tmp_path / "left_weighted_aoi.geojson"
    left_aoi_path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[3000, 1000], [4000, 1000], [4000, 2000], [3500, 1200], [3000, 2000], [3000, 1000]]],
    }))
    right_aoi_path = tmp_path / "right_weighted_aoi.geojson"
    right_aoi_path.write_text(json.dumps({
        "type": "Polygon",
        "coordinates": [[[3000, 1000], [4000, 1000], [4000, 2000], [3500, 1600], [3000, 2000], [3000, 1000]]],
    }))

    assert main([
        "create-run",
        "--run-id", "run-left",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(left_aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0
    assert main([
        "create-run",
        "--run-id", "run-right",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(right_aoi_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
    ]) == 0

    left_output = io.StringIO()
    with redirect_stdout(left_output):
        assert main(["execute-run", "--run-id", "run-left"]) == 0
    right_output = io.StringIO()
    with redirect_stdout(right_output):
        assert main(["execute-run", "--run-id", "run-right"]) == 0

    left_summary = json.loads(left_output.getvalue())
    right_summary = json.loads(right_output.getvalue())
    left_review_output = io.StringIO()
    with redirect_stdout(left_review_output):
        assert main(["review-show", "--candidate-id", left_summary["top_candidate_id"]]) == 0
    right_review_output = io.StringIO()
    with redirect_stdout(right_review_output):
        assert main(["review-show", "--candidate-id", right_summary["top_candidate_id"]]) == 0
    left_export_output = io.StringIO()
    with redirect_stdout(left_export_output):
        assert main([
            "export-create",
            "--run-id", "run-left",
            "--audience", "report_pdf",
            "--requested-precision", "restricted",
        ]) == 0
    right_export_output = io.StringIO()
    with redirect_stdout(right_export_output):
        assert main([
            "export-create",
            "--run-id", "run-right",
            "--audience", "report_pdf",
            "--requested-precision", "restricted",
        ]) == 0

    left_review = json.loads(left_review_output.getvalue())
    right_review = json.loads(right_review_output.getvalue())
    left_export = json.loads(left_export_output.getvalue())
    right_export = json.loads(right_export_output.getvalue())
    assert left_summary["run_metadata"]["aoi_bbox"] == right_summary["run_metadata"]["aoi_bbox"]
    assert left_summary["run_metadata"]["aoi_geometry"] != right_summary["run_metadata"]["aoi_geometry"]
    assert (
        left_summary["aoi_execution_geometry"]["derived_tile_bbox"]
        != right_summary["aoi_execution_geometry"]["derived_tile_bbox"]
        or left_summary["candidate_ids"] != right_summary["candidate_ids"]
    )
    assert left_review["candidate"]["bounds"] != right_review["candidate"]["bounds"]
    assert left_export["candidates"] != right_export["candidates"]

def test_create_run_missing_aoi(tmp_path, monkeypatch):
    setup_mocks(tmp_path, monkeypatch)
    args = [
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ]
    # argparse will exit or error because it's required
    import pytest
    with pytest.raises(SystemExit):
        main(args)

def test_create_run_invalid_date_format(tmp_path, monkeypatch):
    setup_mocks(tmp_path, monkeypatch)
    aoi_path = tmp_path / "test.geojson"
    aoi_path.write_text(json.dumps({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}))
    
    args = [
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "01-01-2024",
        "--end-date", "2024-03-31"
    ]
    f = io.StringIO()
    with redirect_stdout(f): # errors go to stderr but main returns 1
        import sys
        old_stderr = sys.stderr
        sys.stderr = f
        try:
            assert main(args) == 1
        finally:
            sys.stderr = old_stderr
            
    assert "dates must be in YYYY-MM-DD format" in f.getvalue()

def test_create_run_end_before_start(tmp_path, monkeypatch):
    setup_mocks(tmp_path, monkeypatch)
    aoi_path = tmp_path / "test.geojson"
    aoi_path.write_text(json.dumps({"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}))
    
    args = [
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", str(aoi_path),
        "--start-date", "2024-03-31",
        "--end-date", "2024-01-01"
    ]
    f = io.StringIO()
    with redirect_stdout(f):
        import sys
        old_stderr = sys.stderr
        sys.stderr = f
        try:
            assert main(args) == 1
        finally:
            sys.stderr = old_stderr
            
    assert "end-date cannot be before start-date" in f.getvalue()

def test_acceptance_check_regression(tmp_path, monkeypatch):
    setup_mocks(tmp_path, monkeypatch)
    
    aoi_path = tmp_path / "test_aoi.geojson"
    aoi_data = {
        "type": "Polygon",
        "coordinates": [[[3000, 1000], [4000, 1000], [4000, 2000], [3000, 2000], [3000, 1000]]]
    }
    aoi_path.write_text(json.dumps(aoi_data))

    # Create and execute run 1
    main([
        "create-run", "--run-id", "run-1", "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01", "--end-date", "2024-03-31",
        "--attestation", "present", "--geofence", "clear"
    ])
    main(["execute-run", "--run-id", "run-1"])
    
    # Create and execute run 2
    main([
        "create-run", "--run-id", "run-2", "--aoi-path", str(aoi_path),
        "--start-date", "2024-01-01", "--end-date", "2024-03-31",
        "--attestation", "present", "--geofence", "clear"
    ])
    main(["execute-run", "--run-id", "run-2"])
    
    # Run acceptance-check with --retuned-run-id
    # Use area that might allow PASS if deterministic local paths result in same candidates
    args = [
        "acceptance-check",
        "--run-id", "run-1",
        "--aoi-area-km2", "20",
        "--retuned-run-id", "run-2"
    ]
    f = io.StringIO()
    with redirect_stdout(f):
        # We don't strictly care if it passes or warns, just that it doesn't AttributeError
        main(args)
    
    summary = json.loads(f.getvalue())
    assert "status" in summary
    # Verify the check we cared about is present
    stability_check = next((c for c in summary["checks"] if c["name"] == "top_10_stability_after_small_retune"), None)
    assert stability_check is not None
    assert "observed" in stability_check
