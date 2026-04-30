import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lawful_anomaly_screening.exceptions import SourceError
from lawful_anomaly_screening.sources.earth_search import (
    discover_scenes,
    load_endpoint_registry,
)
from lawful_anomaly_screening.sources.manifest_builder import (
    build_manifest,
    create_source_scene_manifest_hash,
)
from lawful_anomaly_screening.sources.stac_client import (
    _normalize_stac_item,
    query_stac_search,
)


SAMPLE_STAC_ITEM = {
    "type": "Feature",
    "id": "S2A_20240101",
    "collection": "sentinel-2-l2a",
    "properties": {
        "datetime": "2024-01-01T10:30:00Z",
        "eo:cloud_cover": 12.5,
    },
}

SAMPLE_STAC_ITEM_NO_CLOUD = {
    "type": "Feature",
    "id": "S2B_20240102",
    "collection": "sentinel-2-l2a",
    "properties": {
        "datetime": "2024-01-02T11:00:00Z",
    },
}

SAMPLE_STAC_FEATURECOLLECTION = {
    "type": "FeatureCollection",
    "features": [SAMPLE_STAC_ITEM, SAMPLE_STAC_ITEM_NO_CLOUD],
}


def test_normalize_stac_item_extracts_required_fields():
    normalized = _normalize_stac_item(SAMPLE_STAC_ITEM)
    assert normalized["scene_id"] == "S2A_20240101"
    assert normalized["acquired_at"] == "2024-01-01T10:30:00Z"
    assert normalized["cloud_cover"] == 12.5
    assert normalized["collection"] == "sentinel-2-l2a"
    assert normalized["provider_item_id"] == "S2A_20240101"


def test_normalize_stac_item_handles_missing_cloud_cover():
    normalized = _normalize_stac_item(SAMPLE_STAC_ITEM_NO_CLOUD)
    assert normalized["scene_id"] == "S2B_20240102"
    assert normalized["cloud_cover"] is None


def test_normalize_stac_item_uses_alternate_cloud_cover_key():
    item = {
        "id": "TEST_001",
        "properties": {
            "datetime": "2024-03-01T00:00:00Z",
            "cloud_cover": 25.0,
        },
    }
    normalized = _normalize_stac_item(item)
    assert normalized["cloud_cover"] == 25.0


def test_manifest_hash_is_stable_after_shuffling():
    manifest_one = build_manifest(
        "earth_search",
        scenes=[
            {"scene_id": "S2A_20240101", "acquired_at": "2024-01-01T10:30:00Z", "cloud_cover": 12.5},
            {"scene_id": "S2B_20240102", "acquired_at": "2024-01-02T11:00:00Z", "cloud_cover": 5.0},
        ],
    )
    manifest_two = build_manifest(
        "earth_search",
        scenes=[
            {"scene_id": "S2B_20240102", "acquired_at": "2024-01-02T11:00:00Z", "cloud_cover": 5.0},
            {"scene_id": "S2A_20240101", "acquired_at": "2024-01-01T10:30:00Z", "cloud_cover": 12.5},
        ],
    )
    assert create_source_scene_manifest_hash(manifest_one) == create_source_scene_manifest_hash(manifest_two)


def test_query_stac_search_with_mocked_http():
    """Mock urllib to avoid network calls."""
    mock_response = type("MockResponse", (), {
        "read": lambda *args: json.dumps(SAMPLE_STAC_FEATURECOLLECTION).encode("utf-8"),
        "__enter__": lambda self: self,
        "__exit__": lambda *args: None,
    })()

    with patch("lawful_anomaly_screening.sources.stac_client.request.urlopen", return_value=mock_response):
        scenes = query_stac_search(
            base_url="https://example.com/v1",
            collections=["sentinel-2-l2a"],
            bbox=[-120.0, 35.0, -119.9, 35.1],
            start_date="2024-01-01",
            end_date="2024-03-31",
        )

    assert len(scenes) == 2
    assert scenes[0]["scene_id"] == "S2A_20240101"
    assert scenes[1]["scene_id"] == "S2B_20240102"
    assert scenes[0]["acquired_at"] == "2024-01-01T10:30:00Z"
    assert scenes[1]["cloud_cover"] is None


def test_query_stac_search_empty_features_fails_clearly():
    mock_response = type("MockResponse", (), {
        "read": lambda *args: json.dumps({"type": "FeatureCollection", "features": []}).encode("utf-8"),
        "__enter__": lambda self: self,
        "__exit__": lambda *args: None,
    })()

    with patch("lawful_anomaly_screening.sources.stac_client.request.urlopen", return_value=mock_response):
        with pytest.raises(SourceError, match="no usable scenes"):
            query_stac_search(base_url="https://example.com/v1")


def test_query_stac_search_http_error_fails_clearly():
    from urllib.error import HTTPError

    def raise_http_error(*args, **kwargs):
        raise HTTPError("https://example.com/v1/search", 500, "Internal Server Error", {}, None)

    with patch("lawful_anomaly_screening.sources.stac_client.request.urlopen", side_effect=raise_http_error):
        with pytest.raises(SourceError, match="STAC search HTTP error 500"):
            query_stac_search(base_url="https://example.com/v1")


def test_discover_scenes_uses_real_stac_when_explicitly_active(tmp_path):
    config_path = tmp_path / "active_stac_endpoints.json"
    config_path.write_text(json.dumps({
        "primary": "earth_search",
        "fallbacks": [],
        "earth_search": {
            "provider": "earth-search",
            "role": "primary",
            "synchronous_only": True,
            "active": True,
            "base_url": "https://example.com/v1",
            "search_path": "search",
            "collections": ["sentinel-2-l2a"],
            "timeout_seconds": 30,
            "max_items": 10,
            "metadata_only": True,
        },
    }))

    registry = load_endpoint_registry(path=config_path)
    mock_response = type("MockResponse", (), {
        "read": lambda *args: json.dumps(SAMPLE_STAC_FEATURECOLLECTION).encode("utf-8"),
        "__enter__": lambda self: self,
        "__exit__": lambda *args: None,
    })()

    with patch("lawful_anomaly_screening.sources.stac_client.request.urlopen", return_value=mock_response):
        scenes = discover_scenes(
            "earth_search",
            registry=registry,
            aoi_hash="test-aoi-001",
            start_date="2024-01-01",
            end_date="2024-03-31",
        )

    assert len(scenes) == 2
    assert scenes[0]["scene_id"] == "S2A_20240101"


def test_discover_scenes_defaults_to_simulation_when_not_active():
    scenes = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert len(scenes) == 3
    for scene in scenes:
        assert "scene_id" in scene
        assert "acquired_at" in scene
        assert "cloud_cover" in scene


def test_discover_scenes_no_usable_scenes_fails_clearly():
    mock_response = type("MockResponse", (), {
        "read": lambda *args: json.dumps({"type": "FeatureCollection", "features": []}).encode("utf-8"),
        "__enter__": lambda self: self,
        "__exit__": lambda *args: None,
    })()

    with patch("lawful_anomaly_screening.sources.stac_client.request.urlopen", return_value=mock_response):
        with pytest.raises(SourceError, match="no usable scenes"):
            query_stac_search(base_url="https://example.com/v1")
