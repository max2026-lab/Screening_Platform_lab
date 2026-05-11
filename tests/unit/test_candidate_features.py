from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    create_cache_key,
    flag_top_valid_tiles,
    generate_fixed_tile_grid,
    score_retained_tile,
)
from lawful_anomaly_screening.sources.polygonization import (
    _passes_candidate_sanity_filter,
    build_candidate_feature_records,
    build_candidate_polygon_records,
    build_full_aoi_anomaly_raster_manifest,
    build_polygonization_manifest,
    create_candidate_id,
)


def _polygonization_manifest() -> tuple[dict, str]:
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

    full_aoi_manifest = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_cache_key,
        tile_records,
    )
    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        "full-aoi-cache-key-001",
        anomaly_regions=[
            {
                "region_id": "candidate-a",
                "bounds": [min_x + 24.0, min_y + 24.0, min_x + 124.0, min_y + 144.0],
            },
            {
                "region_id": "candidate-b",
                "bounds": [min_x + 180.0, min_y + 32.0, min_x + 260.0, min_y + 132.0],
            },
        ],
    )
    return polygonization_manifest, "polygonization-cache-key-001"


def test_candidate_ids_are_deterministic():
    polygonization_manifest, polygonization_manifest_cache_key = _polygonization_manifest()
    candidate_records_one = build_candidate_polygon_records(
        polygonization_manifest,
        polygonization_manifest_cache_key,
    )
    candidate_records_two = build_candidate_polygon_records(
        polygonization_manifest,
        polygonization_manifest_cache_key,
    )

    assert candidate_records_one == candidate_records_two
    first_candidate = candidate_records_one[0]
    assert create_candidate_id(polygonization_manifest_cache_key, first_candidate) == first_candidate["candidate_id"]


def test_candidate_polygon_and_feature_records_include_required_fields():
    polygonization_manifest, polygonization_manifest_cache_key = _polygonization_manifest()
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        polygonization_manifest_cache_key,
    )
    feature_records = build_candidate_feature_records(candidate_records)

    assert len(candidate_records) == 2
    assert len(feature_records) == 2

    first_candidate = candidate_records[0]
    assert {
        "candidate_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "parent_tile_id",
        "source_scene_ids",
        "bounds",
        "centroid",
        "clipped_geometry",
        "area_m2",
        "perimeter_m",
        "pixel_count",
        "boundary_touching",
        "possible_duplicate",
        "duplicate_resolution_action",
        "source_region_ids",
    } <= set(first_candidate)
    assert first_candidate["clipped_geometry"]["type"] == "MultiPolygon"
    assert first_candidate["source_scene_ids"] == []

    first_feature = feature_records[0]
    assert {
        "candidate_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "compactness_ratio",
        "convex_hull_area_m2",
        "elongation",
        "local_contrast_values",
        "water_edge_overlap_ratio",
        "cloud_seam_overlap_ratio",
    } <= set(first_feature)
    assert isinstance(first_feature["local_contrast_values"], list)
    assert len(first_feature["local_contrast_values"]) == 3


def _make_polygonization_manifest_with_regions(regions: list[dict]) -> tuple[dict, str, dict]:
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-002",
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

    full_aoi_manifest = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_cache_key,
        tile_records,
    )
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        "full-aoi-cache-key-002",
        anomaly_regions=regions,
    )
    return polygonization_manifest, "polygonization-cache-key-002", full_aoi_manifest


def test_zero_area_degenerate_candidate_is_filtered():
    _, _, full_aoi_manifest = _make_polygonization_manifest_with_regions([])
    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    # Degenerate bounds: max_x == min_x and max_y == min_y
    polygonization_manifest, cache_key, _ = _make_polygonization_manifest_with_regions([
        {
            "region_id": "degenerate-point",
            "bounds": [min_x + 10.0, min_y + 10.0, min_x + 10.0, min_y + 10.0],
        },
    ])
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        cache_key,
    )
    assert len(candidate_records) == 0


def test_one_pixel_near_zero_candidate_is_filtered():
    _, _, full_aoi_manifest = _make_polygonization_manifest_with_regions([])
    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    # Tiny area: ~50 m2 -> pixel_count rounds to 1
    polygonization_manifest, cache_key, _ = _make_polygonization_manifest_with_regions([
        {
            "region_id": "tiny-one-pixel",
            "bounds": [min_x + 10.0, min_y + 10.0, min_x + 10.0 + 5.0, min_y + 10.0 + 10.0],
        },
    ])
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        cache_key,
    )
    assert len(candidate_records) == 0


def test_zero_height_bounds_candidate_is_filtered():
    _, _, full_aoi_manifest = _make_polygonization_manifest_with_regions([])
    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    # Zero-height bounds: max_y == min_y
    polygonization_manifest, cache_key, _ = _make_polygonization_manifest_with_regions([
        {
            "region_id": "flat-line",
            "bounds": [min_x + 10.0, min_y + 10.0, min_x + 110.0, min_y + 10.0],
        },
    ])
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        cache_key,
    )
    assert len(candidate_records) == 0


def test_valid_candidates_preserved_and_degenerate_suppressed():
    _, _, full_aoi_manifest = _make_polygonization_manifest_with_regions([])
    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    polygonization_manifest, cache_key, _ = _make_polygonization_manifest_with_regions([
        {
            "region_id": "valid-a",
            "bounds": [min_x + 24.0, min_y + 24.0, min_x + 124.0, min_y + 144.0],
        },
        {
            "region_id": "degenerate-point",
            "bounds": [min_x + 10.0, min_y + 10.0, min_x + 10.0, min_y + 10.0],
        },
        {
            "region_id": "tiny-one-pixel",
            "bounds": [min_x + 10.0, min_y + 10.0, min_x + 10.0 + 5.0, min_y + 10.0 + 10.0],
        },
    ])
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        cache_key,
    )
    feature_records = build_candidate_feature_records(candidate_records)

    assert len(candidate_records) == 1
    assert len(feature_records) == 1
    assert candidate_records[0]["source_region_ids"] == ["valid-a"]
    assert feature_records[0]["candidate_id"] == candidate_records[0]["candidate_id"]


def test_candidate_sanity_filter_rejects_degenerate_records():
    assert _passes_candidate_sanity_filter({
        "pixel_count": 1,
        "area_m2": 0.0,
        "perimeter_m": 0.0,
        "bounds": [0.0, 0.0, 0.0, 0.0],
        "clipped_geometry": None,
    }) is False
    assert _passes_candidate_sanity_filter({
        "pixel_count": 2,
        "area_m2": 50.0,
        "perimeter_m": 30.0,
        "bounds": [0.0, 0.0, 5.0, 10.0],
        "clipped_geometry": None,
    }) is False
    assert _passes_candidate_sanity_filter({
        "pixel_count": 10,
        "area_m2": 1000.0,
        "perimeter_m": 130.0,
        "bounds": [0.0, 0.0, 31.623, 31.623],
        "clipped_geometry": None,
    }) is True
