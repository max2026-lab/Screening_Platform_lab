from lawful_anomaly_screening.orchestration.scaffold_run import build_tile_scene_attribution
from lawful_anomaly_screening.sources.manifest_builder import (
    RETAINED_TILE_SCORE_FIELDS,
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    build_tile_feature_input,
    compute_cloud_penalty,
    compute_noise_penalty,
    compute_optical_anomaly,
    compute_persistence,
    compute_tile_score,
    create_cache_key,
    flag_top_valid_tiles,
    generate_fixed_tile_grid,
    score_retained_tile,
)
from lawful_anomaly_screening.aoi.validation import derive_execution_geometry_summary


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
    assert scored_tile["tile_score"] == round(
        scored_tile["optical_anomaly"]
        + scored_tile["persistence"]
        + scored_tile["cloud_penalty"]
        + scored_tile["noise_penalty"],
        6,
    )
    assert "tile_score" in scored_tile
    assert "selected_for_polygonization" in scored_tile
    assert scored_tile["cloud_penalty"] <= 0
    assert scored_tile["noise_penalty"] <= 0
    assert "radar_support" not in scored_tile
    assert "topographic_support" not in scored_tile
    assert "edge_contrast_support" not in scored_tile
    assert "context_fit_adjustment" not in scored_tile
    assert "retained_score" not in scored_tile
    assert "top_valid_selection_flag" not in scored_tile


def test_retained_formula_helpers():
    assert compute_optical_anomaly(
        {"B4": 1.0, "B8": 1.2, "B11": 1.4, "B12": 1.5},
        {"B4": 0.6, "B8": 0.8, "B11": 1.0, "B12": 1.1},
        {"B4": 0.1, "B8": 0.2, "B11": 0.1, "B12": 0.1},
    ) == 35.0
    assert compute_persistence([1.0, 2.0, 2.5, 1.5]) == 12.5
    assert compute_cloud_penalty(24, 80) == -9.0
    assert compute_noise_penalty(0.4, 0.2, 0.8, 3.0) == -8.0
    assert compute_tile_score(30.0, 12.5, -9.0, -8.0) == 25.5


def test_component_ranges_and_signed_penalties():
    optical_anomaly = compute_optical_anomaly(
        {"B4": 2.0},
        {"B4": 0.0},
        {"B4": 0.01},
    )
    persistence = compute_persistence([0.0, 2.0, 3.0, 4.0])
    cloud_penalty = compute_cloud_penalty(120, 80)
    noise_penalty = compute_noise_penalty(1.5, 0.9, 0.1, 7.0)

    assert 0.0 <= optical_anomaly <= 40.0
    assert 0.0 <= persistence <= 25.0
    assert -30.0 <= cloud_penalty <= 0.0
    assert -30.0 <= noise_penalty <= 0.0
    assert cloud_penalty <= 0.0
    assert noise_penalty <= 0.0


def test_tile_feature_inputs_match_retained_helper_signatures():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_feature_input = build_tile_feature_input(
        composite_manifest,
        composite_cache_key,
        x_index=2,
        y_index=1,
    )

    assert set(tile_feature_input["score_inputs"]) == {
        "target_bands",
        "baseline_median_bands",
        "baseline_std_bands",
        "valid_season_optical_values",
        "masked_or_invalid_pixel_count",
        "total_pixel_count",
        "water_edge_overlap_ratio",
        "cloud_seam_overlap_ratio",
        "compactness_ratio_value",
        "elongation",
    }
    assert set(tile_feature_input["score_inputs"]["target_bands"]) == {"B4", "B8", "B11", "B12"}
    assert set(tile_feature_input["score_inputs"]["baseline_median_bands"]) == {"B4", "B8", "B11", "B12"}
    assert set(tile_feature_input["score_inputs"]["baseline_std_bands"]) == {"B4", "B8", "B11", "B12"}


def test_noise_penalty_linear_artifact_trigger_behavior():
    assert compute_noise_penalty(0.0, 0.0, 0.09, 6.1) == -5.0
    assert compute_noise_penalty(0.0, 0.0, 0.10, 6.1) == 0.0
    assert compute_noise_penalty(0.0, 0.0, 0.09, 6.0) == 0.0


def test_noise_penalty_formula_matches_pinned_rule():
    assert compute_noise_penalty(0.4, 0.2, 0.09, 6.1) == -13.0
    assert compute_noise_penalty(3.0, 2.0, 0.09, 7.0) == -30.0


def test_tile_score_uses_signed_penalty_formula():
    optical_anomaly = 28.0
    persistence = 12.5
    cloud_penalty = compute_cloud_penalty(18, 60)
    noise_penalty = compute_noise_penalty(0.3, 0.25, 0.7, 2.0)

    assert cloud_penalty <= 0.0
    assert noise_penalty <= 0.0
    assert compute_tile_score(
        optical_anomaly,
        persistence,
        cloud_penalty,
        noise_penalty,
    ) == round(optical_anomaly + persistence + cloud_penalty + noise_penalty, 6)


def test_top_valid_tile_selection_flags_only_top_15_percent():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_cache_key)

    scored_tiles = []
    for tile in tile_grid:
        tile["tile_feature_input_cache_key"] = create_cache_key("tile_feature_input", tile)
        scored_tiles.append(score_retained_tile(tile))

    flagged_tiles = flag_top_valid_tiles(scored_tiles)
    selected_tiles = [tile for tile in flagged_tiles if tile["selected_for_polygonization"]]
    valid_tiles = [tile for tile in flagged_tiles if tile["is_valid"]]

    assert all(tile["is_valid"] for tile in selected_tiles)
    assert len(selected_tiles) == 3
    ranked_valid = sorted(valid_tiles, key=lambda tile: (-tile["tile_score"], tile["tile_id"]))
    assert sorted(tile["tile_id"] for tile in selected_tiles) == sorted(
        tile["tile_id"] for tile in ranked_valid[:3]
    )


def test_same_aoi_geometry_yields_same_tile_layout():
    composite_manifest, composite_cache_key = _composite_manifest()
    geometry = derive_execution_geometry_summary(
        {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 3], [0, 3], [0, 0]]]},
        [0.0, 0.0, 4.0, 3.0],
    )
    grid_one = generate_fixed_tile_grid(
        composite_manifest,
        composite_cache_key,
        width=geometry["grid_width"],
        height=geometry["grid_height"],
        grid_bounds=geometry["derived_tile_bbox"],
    )
    grid_two = generate_fixed_tile_grid(
        composite_manifest,
        composite_cache_key,
        width=geometry["grid_width"],
        height=geometry["grid_height"],
        grid_bounds=geometry["derived_tile_bbox"],
    )
    assert [tile["tile_id"] for tile in grid_one] == [tile["tile_id"] for tile in grid_two]


def test_different_aoi_geometry_yields_different_tile_layout():
    composite_manifest, composite_cache_key = _composite_manifest()
    left_weighted_geometry = derive_execution_geometry_summary(
        {"type": "Polygon", "coordinates": [[[0, 0], [6, 0], [6, 6], [3, 2], [0, 6], [0, 0]]]},
        [0.0, 0.0, 6.0, 6.0],
    )
    right_weighted_geometry = derive_execution_geometry_summary(
        {"type": "Polygon", "coordinates": [[[0, 0], [6, 0], [6, 6], [6, 6], [3, 4], [0, 6], [0, 0]]]},
        [0.0, 0.0, 6.0, 6.0],
    )
    left_weighted_grid = generate_fixed_tile_grid(
        composite_manifest,
        composite_cache_key,
        width=left_weighted_geometry["grid_width"],
        height=left_weighted_geometry["grid_height"],
        grid_bounds=left_weighted_geometry["derived_tile_bbox"],
    )
    right_weighted_grid = generate_fixed_tile_grid(
        composite_manifest,
        composite_cache_key,
        width=right_weighted_geometry["grid_width"],
        height=right_weighted_geometry["grid_height"],
        grid_bounds=right_weighted_geometry["derived_tile_bbox"],
    )
    assert [tile["tile_id"] for tile in left_weighted_grid] != [tile["tile_id"] for tile in right_weighted_grid]


def test_tile_scene_attribution_is_deterministic_and_granular():
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_cache_key)
    tile_ids = [tile["tile_id"] for tile in tile_grid[:5]]
    discovered_scene_ids = ["scene-001", "scene-002", "scene-003"]

    attribution_one = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-001",
        tile_ids=tile_ids,
        discovered_scene_ids=discovered_scene_ids,
    )
    attribution_two = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-001",
        tile_ids=tile_ids,
        discovered_scene_ids=discovered_scene_ids,
    )

    assert attribution_one == attribution_two
    assert all(attribution_one[tile_id] for tile_id in tile_ids)
    assert all(set(attribution_one[tile_id]) < set(discovered_scene_ids) for tile_id in tile_ids)
    assert len({tuple(attribution_one[tile_id]) for tile_id in tile_ids}) > 1


def test_tile_scene_attribution_changes_when_manifest_changes():
    tile_ids = ["tile-a", "tile-b", "tile-c"]
    discovered_scene_ids = ["scene-001", "scene-002", "scene-003"]

    baseline = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-001",
        tile_ids=tile_ids,
        discovered_scene_ids=discovered_scene_ids,
    )
    changed = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-002",
        tile_ids=tile_ids,
        discovered_scene_ids=discovered_scene_ids,
    )

    assert baseline != changed


def test_tile_scene_attribution_seed_keys_stabilize_same_input_runs():
    discovered_scene_ids = ["scene-001", "scene-002", "scene-003"]
    run_one_tile_ids = ["run-001-tile-a", "run-001-tile-b", "run-001-tile-c"]
    run_two_tile_ids = ["run-002-tile-a", "run-002-tile-b", "run-002-tile-c"]
    stable_seed_keys = {
        run_one_tile_ids[0]: "0:0",
        run_one_tile_ids[1]: "1:0",
        run_one_tile_ids[2]: "2:0",
        run_two_tile_ids[0]: "0:0",
        run_two_tile_ids[1]: "1:0",
        run_two_tile_ids[2]: "2:0",
    }

    run_one = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-001",
        tile_ids=run_one_tile_ids,
        discovered_scene_ids=discovered_scene_ids,
        attribution_seed_keys=stable_seed_keys,
    )
    run_two = build_tile_scene_attribution(
        source_scene_manifest_hash="manifest-hash-001",
        tile_ids=run_two_tile_ids,
        discovered_scene_ids=discovered_scene_ids,
        attribution_seed_keys=stable_seed_keys,
    )

    assert [run_one[tile_id] for tile_id in run_one_tile_ids] == [
        run_two[tile_id] for tile_id in run_two_tile_ids
    ]
