import pytest

from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    create_cache_key,
    is_valid_composite_season,
    resolve_cloud_policy_thresholds,
)


def test_composite_metadata_is_deterministic():
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    composite_one = build_composite_metadata_manifest(
        preprocessing_manifest,
        "preprocess-cache-key-001",
        composite_season_window_name="leaf_on",
    )
    composite_two = build_composite_metadata_manifest(
        preprocessing_manifest,
        "preprocess-cache-key-001",
        composite_season_window_name="leaf_on",
    )
    assert composite_one == composite_two
    assert create_cache_key("composite_metadata", composite_one) == create_cache_key(
        "composite_metadata",
        composite_two,
    )
    assert composite_one["composite_quality"] == composite_two["composite_quality"]


def test_composite_quality_metadata_is_deterministic_from_scene_cloud_cover_values():
    scenes = [
        {"scene_id": "scene-b", "cloud_cover": 10.0},
        {"scene_id": "scene-a", "cloud_cover": 20.0},
        {"scene_id": "scene-c", "cloud_cover": 30.0},
    ]
    thresholds = resolve_cloud_policy_thresholds()
    quality_one = build_composite_quality_metadata(
        scenes,
        cloud_policy_thresholds=thresholds,
    )
    quality_two = build_composite_quality_metadata(
        list(reversed(scenes)),
        cloud_policy_thresholds=thresholds,
    )
    assert quality_one == quality_two
    assert quality_one["scene_count"] == 3
    assert quality_one["contributing_scene_ids"] == ["scene-a", "scene-b", "scene-c"]
    assert quality_one["mean_cloud_cover"] == 20.0
    assert quality_one["max_cloud_cover"] == 30.0
    assert quality_one["clear_scene_count"] == 2
    assert quality_one["cloudy_scene_count"] == 1


def test_cloud_policy_decision_pass_warn_fail():
    thresholds = resolve_cloud_policy_thresholds()
    pass_quality = build_composite_quality_metadata(
        [
            {"scene_id": "scene-1", "cloud_cover": 10.0},
            {"scene_id": "scene-2", "cloud_cover": 30.0},
        ],
        cloud_policy_thresholds=thresholds,
    )
    warn_quality = build_composite_quality_metadata(
        [
            {"scene_id": "scene-1", "cloud_cover": 40.0},
            {"scene_id": "scene-2", "cloud_cover": 40.0},
        ],
        cloud_policy_thresholds=thresholds,
    )
    fail_quality = build_composite_quality_metadata(
        [
            {"scene_id": "scene-1", "cloud_cover": 70.0},
            {"scene_id": "scene-2", "cloud_cover": 70.0},
        ],
        cloud_policy_thresholds=thresholds,
    )
    assert pass_quality["cloud_policy_decision"] == "pass"
    assert warn_quality["cloud_policy_decision"] == "warn"
    assert fail_quality["cloud_policy_decision"] == "fail"


def test_composite_metadata_valid_season_rule():
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="dry",
    )
    assert is_valid_composite_season(preprocessing_manifest, "dry") is True
    assert is_valid_composite_season(preprocessing_manifest, "wet") is False


def test_composite_metadata_rejects_invalid_season():
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_off",
    )
    with pytest.raises(ValueError):
        build_composite_metadata_manifest(
            preprocessing_manifest,
            "preprocess-cache-key-001",
            composite_season_window_name="leaf_on",
        )


def test_composite_metadata_embeds_composite_quality_metadata():
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    composite_manifest = build_composite_metadata_manifest(
        preprocessing_manifest,
        "preprocess-cache-key-001",
        composite_season_window_name="leaf_on",
        scenes=[
            {"scene_id": "scene-2", "cloud_cover": 10.0},
            {"scene_id": "scene-1", "cloud_cover": 30.0},
        ],
    )
    quality = composite_manifest["composite_quality"]
    assert quality["scene_count"] == 2
    assert quality["contributing_scene_ids"] == ["scene-1", "scene-2"]
    assert quality["mean_cloud_cover"] == 20.0
