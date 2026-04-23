from lawful_anomaly_screening.sources.manifest_builder import (
    RETAINED_TILE_SCORE_FIELDS,
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    build_tile_feature_input,
    create_cache_key,
    flag_top_valid_tiles,
    generate_fixed_tile_grid,
    score_retained_tile,
)


def _composite_manifest() -> tuple[dict, str]:
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    preprocessing_cache_key = create_cache_key("preprocessing_manifest", preprocessing_manifest)
    composite_manifest = build_composite_metadata_manifest(
        preprocessing_manifest,
        preprocessing_cache_key,
        composite_season_window_name="leaf_on",
    )
    composite_cache_key = create_cache_key("composite_metadata", composite_manifest)
    return composite_manifest, composite_cache_key


def test_tile_ids_are_deterministic():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_one = build_tile_feature_input(
        composite_manifest,
        composite_cache_key,
        x_index=2,
        y_index=3,
    )
    tile_two = build_tile_feature_input(
        composite_manifest,
        composite_cache_key,
        x_index=2,
        y_index=3,
    )
    assert tile_one["tile_id"] == tile_two["tile_id"]


def test_retained_tile_score_integrity():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_feature_input = build_tile_feature_input(
        composite_manifest,
        composite_cache_key,
        x_index=1,
        y_index=4,
    )
    tile_feature_input["tile_feature_input_cache_key"] = create_cache_key(
        "tile_feature_input",
        tile_feature_input,
    )
    scored_tile = score_retained_tile(tile_feature_input)

    assert tuple(RETAINED_TILE_SCORE_FIELDS) == (
        "optical_anomaly",
        "persistence",
        "cloud_penalty",
        "noise_penalty",
    )
    assert scored_tile["retained_score"] == round(
        scored_tile["optical_anomaly"]
        + scored_tile["persistence"]
        - scored_tile["cloud_penalty"]
        - scored_tile["noise_penalty"],
        6,
    )
    assert "radar_support" not in scored_tile
    assert "topographic_support" not in scored_tile
    assert "edge_contrast_support" not in scored_tile
    assert "context_fit_adjustment" not in scored_tile


def test_top_valid_tile_selection_flags_only_top_15_percent():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_cache_key)

    scored_tiles = []
    for tile in tile_grid:
        tile["tile_feature_input_cache_key"] = create_cache_key("tile_feature_input", tile)
        scored_tiles.append(score_retained_tile(tile))

    flagged_tiles = flag_top_valid_tiles(scored_tiles)
    selected_tiles = [tile for tile in flagged_tiles if tile["top_valid_selection_flag"]]
    valid_tiles = [tile for tile in flagged_tiles if tile["is_valid"]]

    assert all(tile["is_valid"] for tile in selected_tiles)
    assert len(selected_tiles) == 3
    ranked_valid = sorted(valid_tiles, key=lambda tile: (-tile["retained_score"], tile["tile_id"]))
    assert sorted(tile["tile_id"] for tile in selected_tiles) == sorted(
        tile["tile_id"] for tile in ranked_valid[:3]
    )
