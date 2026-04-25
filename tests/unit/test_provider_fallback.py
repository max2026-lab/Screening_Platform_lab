import pytest
import json
from lawful_anomaly_screening.sources.earth_search import EndpointRegistry, SourceEndpoint
from lawful_anomaly_screening.sources.manifest_builder import build_manifest
from lawful_anomaly_screening.exceptions import SourceError

def test_primary_success_path_unchanged():
    manifest = build_manifest(
        start_date="2024-01-01",
        end_date="2024-01-02",
        aoi_hash="happy_path"
    )
    assert manifest["source_endpoint_id"] == "earth_search"
    assert manifest["scene_count"] > 0
    assert "fallback_diagnostics" not in manifest

def test_explicit_unknown_endpoint_fails_fast():
    with pytest.raises(SourceError, match="unknown source endpoint: unknown-id"):
        build_manifest(
            source_endpoint_id="unknown-id",
            start_date="2024-01-01",
            end_date="2024-01-02",
        )

def test_primary_empty_result_falls_back():
    manifest = build_manifest(
        start_date="2024-01-01",
        end_date="2024-01-02",
        aoi_hash="empty_discovery_trigger"
    )
    assert manifest["source_endpoint_id"] != "earth_search"
    assert manifest["fallback_diagnostics"]["fallback_used"] is True
    assert manifest["fallback_diagnostics"]["selected_endpoint_id"] == manifest["source_endpoint_id"]
    assert "earth_search" in manifest["fallback_diagnostics"]["attempted_endpoint_ids"]

def test_primary_malformed_result_falls_back():
    manifest = build_manifest(
        start_date="2024-01-01",
        end_date="2024-01-02",
        aoi_hash="malformed_discovery_trigger"
    )
    assert manifest["source_endpoint_id"] != "earth_search"
    assert manifest["fallback_diagnostics"]["fallback_used"] is True
    assert manifest["fallback_diagnostics"]["selected_endpoint_id"] == manifest["source_endpoint_id"]
    assert "earth_search" in manifest["fallback_diagnostics"]["attempted_endpoint_ids"]

def test_all_endpoints_failing(monkeypatch):
    # If the user specifies an endpoint with no fallback, it should fail directly
    with pytest.raises(SourceError, match="no scenes discovered"):
        build_manifest(
            source_endpoint_id="cdse",
            start_date="2024-01-01",
            end_date="2024-01-02",
            aoi_hash="all_fail_discovery_trigger"
        )

def test_all_endpoints_failing_with_fallback(monkeypatch):
    with pytest.raises(SourceError, match="all configured endpoints failed"):
        build_manifest(
            start_date="2024-01-01",
            end_date="2024-01-02",
            aoi_hash="all_fail_discovery_trigger"
        )
