from lawful_anomaly_screening.sources.manifest_builder import (
    build_preprocessing_manifest,
    create_cache_key,
    load_preprocessing_config,
)


def test_preprocessing_config_loads_season_windows_and_cloud_mask():
    config = load_preprocessing_config()
    assert set(config["season_windows"]) == {"leaf_on", "leaf_off", "dry", "wet"}
    assert config["cloud_mask"]["provider"] == "stubbed-cloud-mask"


def test_cache_key_is_deterministic_for_same_preprocessing_manifest():
    manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    assert create_cache_key("preprocessing_manifest", manifest) == create_cache_key(
        "preprocessing_manifest",
        manifest,
    )


def test_cache_key_changes_when_season_window_changes():
    leaf_on = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    leaf_off = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_off",
    )
    assert create_cache_key("preprocessing_manifest", leaf_on) != create_cache_key(
        "preprocessing_manifest",
        leaf_off,
    )
