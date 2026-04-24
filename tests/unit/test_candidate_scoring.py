from lawful_anomaly_screening.sources.candidate_scoring import (
    AUTOMATED_CANDIDATE_SCORE_FIELDS,
    build_candidate_score_breakdown,
    build_candidate_score_records,
    compute_candidate_score,
    compute_compactness_support,
    compute_polygon_object_score,
    compute_texture_support,
    rank_candidate_scores,
)
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    create_cache_key,
    flag_top_valid_tiles,
    generate_fixed_tile_grid,
    score_retained_tile,
)
from lawful_anomaly_screening.sources.polygonization import (
    build_candidate_feature_records,
    build_candidate_polygon_records,
    build_full_aoi_anomaly_raster_manifest,
    build_polygonization_manifest,
)


def _candidate_pipeline() -> tuple[list[dict], list[dict], list[dict]]:
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
    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        "polygonization-cache-key-001",
    )
    feature_records = build_candidate_feature_records(candidate_records)
    return candidate_records, feature_records, flagged_tiles


def test_retained_candidate_formula_helpers_and_ranges():
    texture_support = compute_texture_support(
        {
            "ring_mean_delta": 0.5,
            "local_variance_proxy": 0.75,
            "neighbor_contrast_proxy": 0.25,
        }
    )
    compactness_support = compute_compactness_support(0.6, 2.0)
    polygon_object_score = compute_polygon_object_score(texture_support, compactness_support)
    candidate_score = compute_candidate_score(82.0, polygon_object_score)

    assert tuple(AUTOMATED_CANDIDATE_SCORE_FIELDS) == (
        "texture_support",
        "compactness_support",
        "polygon_object_score",
        "candidate_score",
    )
    assert texture_support == 7.75
    assert compactness_support == 6.6
    assert polygon_object_score == 14.35
    assert candidate_score == 96.35

    assert 0.0 <= texture_support <= 15.0
    assert 0.0 <= compactness_support <= 10.0
    assert 0.0 <= polygon_object_score <= 25.0
    assert 0.0 <= candidate_score <= 100.0


def test_candidate_score_clamps_and_breakdown_integrity():
    texture_support = compute_texture_support(
        {
            "ring_mean_delta": 5.0,
            "local_variance_proxy": 5.0,
            "neighbor_contrast_proxy": 5.0,
        }
    )
    compactness_support = compute_compactness_support(5.0, 0.5)
    polygon_object_score = compute_polygon_object_score(texture_support, compactness_support)
    candidate_score = compute_candidate_score(95.0, polygon_object_score)
    breakdown = build_candidate_score_breakdown(
        95.0,
        texture_support,
        compactness_support,
        polygon_object_score,
        candidate_score,
    )

    assert texture_support == 15.0
    assert compactness_support == 10.0
    assert polygon_object_score == 25.0
    assert candidate_score == 100.0
    assert breakdown["contribution_sum"] == 120.0
    assert breakdown["integrity_delta"] == 20.0
    assert "edge_contrast_support" not in breakdown
    assert "context_fit_adjustment" not in breakdown
    assert "radar_support" not in breakdown
    assert "topographic_support" not in breakdown


def test_candidate_score_records_only_use_parent_tile_and_retained_polygon_object_score():
    candidate_records, feature_records, tile_score_records = _candidate_pipeline()
    score_records = build_candidate_score_records(
        candidate_records,
        feature_records,
        tile_score_records,
    )

    assert len(score_records) == 2
    first_record = score_records[0]
    assert {
        "candidate_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "parent_tile_id",
        "parent_tile_score",
        "texture_support",
        "compactness_support",
        "polygon_object_score",
        "candidate_score",
        "score_breakdown",
        "contribution_sum",
        "integrity_delta",
        "integrity_within_tolerance",
    } <= set(first_record)
    assert first_record["candidate_score"] == round(
        first_record["parent_tile_score"] + first_record["polygon_object_score"],
        6,
    )
    assert first_record["contribution_sum"] == first_record["score_breakdown"]["contribution_sum"]
    assert first_record["integrity_delta"] == first_record["score_breakdown"]["integrity_delta"]
    assert first_record["integrity_within_tolerance"] is True
    assert "edge_contrast_support" not in first_record
    assert "context_fit_adjustment" not in first_record
    assert "radar_support" not in first_record
    assert "topographic_support" not in first_record


def test_candidate_ranking_is_deterministic():
    ranked_records = rank_candidate_scores(
        [
            {
                "candidate_id": "candidate-b",
                "parent_tile_score": 50.0,
                "candidate_score": 75.0,
            },
            {
                "candidate_id": "candidate-a",
                "parent_tile_score": 55.0,
                "candidate_score": 75.0,
            },
            {
                "candidate_id": "candidate-c",
                "parent_tile_score": 60.0,
                "candidate_score": 88.0,
            },
        ]
    )

    assert [record["candidate_id"] for record in ranked_records] == [
        "candidate-c",
        "candidate-a",
        "candidate-b",
    ]
    assert [record["rank"] for record in ranked_records] == [1, 2, 3]
