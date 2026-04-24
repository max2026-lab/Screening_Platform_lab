from lawful_anomaly_screening.sources.manifest_builder import (
    build_manifest,
    create_source_scene_manifest_hash,
)
from lawful_anomaly_screening.sources.earth_search import discover_scenes


def test_manifest_builder_is_deterministic():
    manifest_one = build_manifest("earth_search")
    manifest_two = build_manifest("earth_search")
    assert manifest_one == manifest_two
    assert create_source_scene_manifest_hash(manifest_one) == create_source_scene_manifest_hash(manifest_two)


def test_manifest_hash_changes_when_content_changes():
    manifest_one = build_manifest("earth_search")
    manifest_two = build_manifest(
        "earth_search",
        scenes=[
            {
                "scene_id": "earth_search-scene-001",
                "acquired_at": "2024-01-01T00:00:00Z",
                "cloud_cover": 99.0,
            }
        ],
    )
    assert create_source_scene_manifest_hash(manifest_one) != create_source_scene_manifest_hash(manifest_two)


def test_discovered_scenes_are_stable_for_same_aoi_and_dates():
    scenes_one = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    scenes_two = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert scenes_one == scenes_two


def test_discovered_scenes_change_when_aoi_or_date_window_changes():
    baseline = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    different_aoi = discover_scenes(
        "earth_search",
        aoi_hash="hash-002",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    different_dates = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-02-01",
        end_date="2024-03-31",
    )
    assert baseline != different_aoi
    assert baseline != different_dates


def test_discovered_scenes_fall_within_requested_date_window():
    scenes = discover_scenes(
        "earth_search",
        aoi_hash="hash-001",
        start_date="2024-02-10",
        end_date="2024-02-20",
    )
    acquired_dates = [scene["acquired_at"][:10] for scene in scenes]
    assert all("2024-02-10" <= acquired_date <= "2024-02-20" for acquired_date in acquired_dates)
