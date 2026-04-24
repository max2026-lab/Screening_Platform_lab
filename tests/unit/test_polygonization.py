from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    build_tile_feature_input,
    create_cache_key,
    flag_top_valid_tiles,
    generate_fixed_tile_grid,
    score_retained_tile,
)
from lawful_anomaly_screening.sources.polygonization import (
    assign_parent_tile,
    build_full_aoi_anomaly_raster_manifest,
    build_polygonization_manifest,
    deduplicate_polygon_candidates,
    is_tile_edge_eligible,
    polygonize_full_aoi,
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


def _selected_tile_records() -> tuple[dict, str, list[dict]]:
    composite_manifest, composite_cache_key = _composite_manifest()
    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_cache_key)

    scored_tiles = []
    for tile in tile_grid:
        tile["tile_feature_input_cache_key"] = create_cache_key("tile_feature_input", tile)
        scored_tiles.append(score_retained_tile(tile))

    flagged_tiles = flag_top_valid_tiles(scored_tiles)
    scored_by_id = {tile["tile_id"]: tile for tile in flagged_tiles}
    tile_records = []
    for tile in tile_grid:
        tile_record = dict(tile)
        tile_record.update(
            tile_score=scored_by_id[tile["tile_id"]]["tile_score"],
            selected_for_polygonization=scored_by_id[tile["tile_id"]]["selected_for_polygonization"],
        )
        tile_records.append(tile_record)

    return composite_manifest, composite_cache_key, tile_records


def test_full_aoi_anomaly_raster_manifest_is_deterministic():
    composite_manifest, composite_cache_key, tile_records = _selected_tile_records()
    manifest_one = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_cache_key,
        tile_records,
    )
    manifest_two = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_cache_key,
        tile_records,
    )

    assert manifest_one == manifest_two
    assert manifest_one["manifest_version"] == "phase1-full-aoi-anomaly-raster-v1"
    assert manifest_one["selected_tile_count"] == 3
    assert len(manifest_one["selected_tile_ids"]) == 3


def test_tile_edge_eligibility_rules_and_parent_tile_assignment():
    selected_tiles = [
        {"tile_id": "tile-a", "bounds": [0.0, 0.0, 320.0, 320.0], "tile_score": 80.0},
        {"tile_id": "tile-b", "bounds": [320.0, 0.0, 640.0, 320.0], "tile_score": 75.0},
    ]

    centroid_inside_bounds = (40.0, 40.0, 180.0, 180.0)
    overlap_only_bounds = (100.0, -80.0, 220.0, 40.0)
    ineligible_bounds = (100.0, -100.0, 220.0, 20.0)

    assert is_tile_edge_eligible(centroid_inside_bounds, selected_tiles) is True
    assert assign_parent_tile(centroid_inside_bounds, selected_tiles) == "tile-a"

    assert is_tile_edge_eligible(overlap_only_bounds, selected_tiles) is True
    assert assign_parent_tile(overlap_only_bounds, selected_tiles) == "tile-a"

    assert is_tile_edge_eligible(ineligible_bounds, selected_tiles) is False
    assert assign_parent_tile(ineligible_bounds, selected_tiles) == "tile-a"


def test_iou_dedup_rules_merge_mark_possible_duplicate_and_keep():
    selected_tiles = [
        {"tile_id": "tile-a", "bounds": [0.0, 0.0, 400.0, 400.0], "tile_score": 80.0},
    ]
    polygon_candidates = [
        {
            "polygon_id": "merge-a",
            "bounds": [20.0, 20.0, 120.0, 120.0],
            "source_region_ids": ["merge-a"],
            "possible_duplicate": False,
        },
        {
            "polygon_id": "merge-b",
            "bounds": [40.0, 40.0, 140.0, 140.0],
            "source_region_ids": ["merge-b"],
            "possible_duplicate": False,
        },
        {
            "polygon_id": "duplicate-a",
            "bounds": [200.0, 20.0, 300.0, 120.0],
            "source_region_ids": ["duplicate-a"],
            "possible_duplicate": False,
        },
        {
            "polygon_id": "duplicate-b",
            "bounds": [260.0, 20.0, 360.0, 120.0],
            "source_region_ids": ["duplicate-b"],
            "possible_duplicate": False,
        },
        {
            "polygon_id": "keep-a",
            "bounds": [20.0, 180.0, 120.0, 280.0],
            "source_region_ids": ["keep-a"],
            "possible_duplicate": False,
        },
        {
            "polygon_id": "keep-b",
            "bounds": [110.0, 180.0, 210.0, 280.0],
            "source_region_ids": ["keep-b"],
            "possible_duplicate": False,
        },
    ]

    deduplicated = deduplicate_polygon_candidates(polygon_candidates, selected_tiles)

    assert len(deduplicated) == 5
    merged_candidate = next(
        polygon for polygon in deduplicated if polygon["source_region_ids"] == ["merge-a", "merge-b"]
    )
    assert merged_candidate["possible_duplicate"] is False

    possible_duplicates = [
        polygon for polygon in deduplicated if polygon["source_region_ids"] in (["duplicate-a"], ["duplicate-b"])
    ]
    assert len(possible_duplicates) == 2
    assert all(polygon["possible_duplicate"] is True for polygon in possible_duplicates)

    kept_candidates = [
        polygon for polygon in deduplicated if polygon["source_region_ids"] in (["keep-a"], ["keep-b"])
    ]
    assert len(kept_candidates) == 2
    assert all(polygon["possible_duplicate"] is False for polygon in kept_candidates)


def test_polygonization_manifest_uses_full_aoi_scaffold_rules():
    composite_manifest, composite_cache_key, tile_records = _selected_tile_records()
    full_aoi_manifest = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_cache_key,
        tile_records,
    )
    selected_tiles = full_aoi_manifest["selected_tiles"]
    first_selected_tile = selected_tiles[0]
    min_x, min_y, max_x, max_y = first_selected_tile["bounds"]

    anomaly_regions = [
        {
            "region_id": "selected-core",
            "bounds": [min_x + 20.0, min_y + 20.0, min_x + 120.0, min_y + 120.0],
        },
        {
            "region_id": "selected-overlap",
            "bounds": [min_x + 40.0, min_y + 40.0, min_x + 140.0, min_y + 140.0],
        },
        {
            "region_id": "outside-aoi",
            "bounds": [max_x + 50.0, max_y + 50.0, max_x + 120.0, max_y + 120.0],
        },
    ]

    polygons = polygonize_full_aoi(full_aoi_manifest, anomaly_regions=anomaly_regions)
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        "full-aoi-cache-key-001",
        anomaly_regions=anomaly_regions,
    )

    assert len(polygons) == 1
    assert polygonization_manifest["polygon_count"] == 1
    assert polygonization_manifest["polygons"][0]["source_region_ids"] == [
        "selected-core",
        "selected-overlap",
    ]

