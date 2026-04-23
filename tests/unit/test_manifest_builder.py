from lawful_anomaly_screening.sources.manifest_builder import (
    build_manifest,
    create_source_scene_manifest_hash,
)


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
