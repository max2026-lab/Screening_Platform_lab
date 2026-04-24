import json

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import (
    bootstrap_minimal_run,
    connect,
    init_db,
    insert_candidate_feature,
    insert_candidate_polygon,
    insert_candidate_score,
    insert_tile,
)
from lawful_anomaly_screening.sources.candidate_scoring import (
    build_candidate_score_records,
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


def test_candidate_score_persistence_and_ranking(tmp_path):
    db_path = tmp_path / "candidate-score.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-001",
        manifest_path="data/manifests/manifest-hash-001.json",
    )

    repository = CacheRepository(db_path, cache_root=cache_root)
    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        season_window_name="leaf_on",
    )
    preprocessing_record = repository.persist_preprocessing_manifest(preprocessing_manifest)
    composite_manifest = build_composite_metadata_manifest(
        preprocessing_manifest,
        preprocessing_record["cache_key"],
        composite_season_window_name="leaf_on",
    )
    composite_record = repository.persist_composite_metadata(composite_manifest)

    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_record["cache_key"])
    scored_tiles = []
    for tile in tile_grid:
        tile["tile_feature_input_cache_key"] = create_cache_key("tile_feature_input", tile)
        scored_tiles.append(score_retained_tile(tile))
    flagged_tiles = flag_top_valid_tiles(scored_tiles)
    scored_by_id = {tile["tile_id"]: tile for tile in flagged_tiles}
    source_scene_ids = ["scene-001", "scene-002", "scene-003"]

    with connect(db_path) as conn:
        for tile in tile_grid:
            insert_tile(
                conn,
                tile_id=tile["tile_id"],
                run_id="run-001",
                source_scene_manifest_hash=tile["source_scene_manifest_hash"],
                source_endpoint_id=tile["source_endpoint_id"],
                source_scene_ids=source_scene_ids,
                composite_metadata_cache_key=tile["composite_metadata_cache_key"],
                tile_size_m=tile["tile_size_m"],
                x_index=tile["x_index"],
                y_index=tile["y_index"],
                is_valid=tile["is_valid"],
            )
        conn.commit()

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
        composite_record["cache_key"],
        tile_records,
    )
    full_aoi_record = repository.persist_full_aoi_anomaly_raster(full_aoi_manifest)

    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, _, _ = first_selected_tile["bounds"]
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        full_aoi_record["cache_key"],
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
    polygonization_record = repository.persist_polygonization_manifest(polygonization_manifest)

    candidate_records = build_candidate_polygon_records(
        polygonization_manifest,
        polygonization_record["cache_key"],
        source_scene_ids=source_scene_ids,
    )
    feature_records = build_candidate_feature_records(candidate_records)

    with connect(db_path) as conn:
        for candidate_record in candidate_records:
            insert_candidate_polygon(
                conn,
                candidate_id=candidate_record["candidate_id"],
                run_id="run-001",
                polygonization_manifest_cache_key=candidate_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=candidate_record["source_scene_manifest_hash"],
                source_endpoint_id=candidate_record["source_endpoint_id"],
                parent_tile_id=candidate_record["parent_tile_id"],
                source_scene_ids=candidate_record["source_scene_ids"],
                bounds=candidate_record["bounds"],
                centroid=candidate_record["centroid"],
                area_m2=candidate_record["area_m2"],
                perimeter_m=candidate_record["perimeter_m"],
                pixel_count=candidate_record["pixel_count"],
                boundary_touching=candidate_record["boundary_touching"],
                possible_duplicate=candidate_record["possible_duplicate"],
                duplicate_resolution_action=candidate_record["duplicate_resolution_action"],
            )
        for feature_record in feature_records:
            insert_candidate_feature(
                conn,
                candidate_id=feature_record["candidate_id"],
                run_id="run-001",
                polygonization_manifest_cache_key=feature_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=feature_record["source_scene_manifest_hash"],
                source_endpoint_id=feature_record["source_endpoint_id"],
                compactness_ratio=feature_record["compactness_ratio"],
                convex_hull_area_m2=feature_record["convex_hull_area_m2"],
                elongation=feature_record["elongation"],
                local_contrast_values=feature_record["local_contrast_values"],
                water_edge_overlap_ratio=feature_record["water_edge_overlap_ratio"],
                cloud_seam_overlap_ratio=feature_record["cloud_seam_overlap_ratio"],
            )

        candidate_score_records = build_candidate_score_records(
            candidate_records,
            feature_records,
            flagged_tiles,
        )
        ranked_candidate_scores = rank_candidate_scores(candidate_score_records)
        for score_record in ranked_candidate_scores:
            insert_candidate_score(
                conn,
                candidate_id=score_record["candidate_id"],
                run_id="run-001",
                polygonization_manifest_cache_key=score_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=score_record["source_scene_manifest_hash"],
                source_endpoint_id=score_record["source_endpoint_id"],
                parent_tile_id=score_record["parent_tile_id"],
                parent_tile_score=score_record["parent_tile_score"],
                texture_support=score_record["texture_support"],
                compactness_support=score_record["compactness_support"],
                polygon_object_score=score_record["polygon_object_score"],
                candidate_score=score_record["candidate_score"],
                score_breakdown=score_record["score_breakdown"],
                contribution_sum=score_record["contribution_sum"],
                integrity_delta=score_record["integrity_delta"],
                integrity_within_tolerance=score_record["integrity_within_tolerance"],
            )
        conn.commit()

    with connect(db_path) as conn:
        score_rows = conn.execute(
            """
            SELECT
                candidate_id,
                parent_tile_id,
                parent_tile_score,
                texture_support,
                compactness_support,
                polygon_object_score,
                candidate_score,
                score_breakdown_json,
                contribution_sum,
                integrity_delta,
                integrity_within_tolerance
            FROM candidate_scores
            ORDER BY candidate_score DESC, parent_tile_score DESC, candidate_id ASC
            """
        ).fetchall()

    assert len(score_rows) == 2
    first_record = ranked_candidate_scores[0]
    assert score_rows[0] == (
        first_record["candidate_id"],
        first_record["parent_tile_id"],
        first_record["parent_tile_score"],
        first_record["texture_support"],
        first_record["compactness_support"],
        first_record["polygon_object_score"],
        first_record["candidate_score"],
        json.dumps(first_record["score_breakdown"], sort_keys=True),
        first_record["contribution_sum"],
        first_record["integrity_delta"],
        int(first_record["integrity_within_tolerance"]),
    )
    assert [row[0] for row in score_rows] == [record["candidate_id"] for record in ranked_candidate_scores]
