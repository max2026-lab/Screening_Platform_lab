import pytest
import json
from pathlib import Path
from lawful_anomaly_screening.sources.earth_search import discover_scenes, load_endpoint_registry
from lawful_anomaly_screening.sources.manifest_builder import build_manifest
from lawful_anomaly_screening.exceptions import SourceError
from lawful_anomaly_screening.cli import main

def test_unknown_source_endpoint_id_fails_clearly():
    with pytest.raises(SourceError, match="unknown source endpoint: unknown-id"):
        discover_scenes(source_endpoint_id="unknown-id")

def test_empty_discovered_scenes_fails_clearly():
    # Using our simulation hook: aoi_hash="empty_discovery_trigger"
    with pytest.raises(SourceError, match="no scenes discovered for endpoint"):
        build_manifest(
            source_endpoint_id="earth_search",
            aoi_hash="empty_discovery_trigger"
        )

def test_malformed_provider_scene_payload_fails_clearly():
    # Using our simulation hook: aoi_hash="malformed_discovery_trigger"
    with pytest.raises(SourceError, match="malformed scene record"):
        build_manifest(
            source_endpoint_id="earth_search",
            aoi_hash="malformed_discovery_trigger"
        )

def test_invalid_endpoint_config_fails_clearly(tmp_path):
    config_file = tmp_path / "invalid_endpoints.json"
    config_file.write_text(json.dumps({"primary": "missing-def", "fallbacks": []}))
    
    with pytest.raises(SourceError, match="definition for 'missing-def' missing"):
        load_endpoint_registry(path=config_file)

def test_cli_handles_source_error_gracefully(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "error_test.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    
    # We trigger a SourceError by providing an unknown endpoint ID
    args = [
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--aoi-path", "tests/fixtures/sample_aoi.geojson",
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31",
        "--source-endpoint-id", "unknown-cli-endpoint"
    ]
    
    exit_code = main(args)
    assert exit_code == 1
    
    stderr = capsys.readouterr().err
    assert "Source Error: unknown source endpoint: unknown-cli-endpoint" in stderr

def test_happy_path_still_works():
    manifest = build_manifest(
        start_date="2024-01-01",
        end_date="2024-01-02",
        aoi_hash="happy_path"
    )
    assert manifest["source_endpoint_id"] == "earth_search"
    assert manifest["scene_count"] > 0
    assert len(manifest["scenes"]) == manifest["scene_count"]
    for scene in manifest["scenes"]:
        assert "scene_id" in scene
        assert "acquired_at" in scene
        assert "cloud_cover" in scene
