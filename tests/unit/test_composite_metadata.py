import pytest

from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    create_cache_key,
    is_valid_composite_season,
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
