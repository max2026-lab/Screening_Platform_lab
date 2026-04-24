import json
from pathlib import Path
from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.settings import Settings

def test_create_and_execute_run_aoi(tmp_path, monkeypatch):
    # Setup paths
    db_path = tmp_path / "test.db"
    
    # Mock settings for BOTH settings and cli modules
    mock_settings = Settings(db_path=db_path)
    monkeypatch.setattr("lawful_anomaly_screening.settings.load_settings", lambda: mock_settings)
    monkeypatch.setattr("lawful_anomaly_screening.cli.load_settings", lambda: mock_settings)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.run_pipeline.load_settings", lambda: mock_settings, raising=False)
    monkeypatch.setattr("lawful_anomaly_screening.orchestration.scaffold_run.load_settings", lambda: mock_settings, raising=False)
    
    aoi_path = tmp_path / "test_aoi.geojson"
    aoi_data = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
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
    
    # 2. execute-run
    args = ["execute-run", "--run-id", "test-run-001"]
    assert main(args) == 0
    
    # 3. verify review-queue
    args = ["review-queue", "--run-id", "test-run-001"]
    # Capture stdout
    import io
    from contextlib import redirect_stdout
    f = io.StringIO()
    with redirect_stdout(f):
        main(args)
    
    queue = json.loads(f.getvalue())
    assert len(queue) > 0
    assert queue[0]["run_id"] == "test-run-001"
