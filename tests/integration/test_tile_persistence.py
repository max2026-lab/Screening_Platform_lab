import json
import sqlite3

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import (
    bootstrap_minimal_run,
    connect,
    init_db,
    insert_tile,
    insert_tile_feature,
    insert_tile_score,
)
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    build_tile_feature_input,
    create_cache_key,
    score_retained_tile,
)


def test_tile_record_persistence_with_cached_tile_input(tmp_path):
    db_path = tmp_path / "tiles.sqlite3"
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

    tile_feature_input = build_tile_feature_input(
        composite_manifest,
        composite_record["cache_key"],
        x_index=1,
        y_index=2,
    )
    tile_input_record = repository.persist_tile_feature_input(tile_feature_input)
    tile_feature_input["tile_feature_input_cache_key"] = tile_input_record["cache_key"]
    scored_tile = score_retained_tile(tile_feature_input)
    scored_tile["selected_for_polygonization"] = True

    with connect(db_path) as conn:
        insert_tile(
            conn,
            tile_id=tile_feature_input["tile_id"],
            run_id="run-001",
            source_scene_manifest_hash=tile_feature_input["source_scene_manifest_hash"],
            source_endpoint_id=tile_feature_input["source_endpoint_id"],
            source_scene_ids=["scene-001", "scene-002", "scene-003"],
            composite_metadata_cache_key=tile_feature_input["composite_metadata_cache_key"],
            tile_size_m=tile_feature_input["tile_size_m"],
            x_index=tile_feature_input["x_index"],
            y_index=tile_feature_input["y_index"],
            is_valid=tile_feature_input["is_valid"],
        )
        insert_tile_feature(
            conn,
            tile_feature_input_cache_key=tile_input_record["cache_key"],
            run_id="run-001",
            tile_id=tile_feature_input["tile_id"],
            source_scene_manifest_hash=tile_feature_input["source_scene_manifest_hash"],
            source_endpoint_id=tile_feature_input["source_endpoint_id"],
            target_bands=tile_feature_input["score_inputs"]["target_bands"],
            baseline_median_bands=tile_feature_input["score_inputs"]["baseline_median_bands"],
            baseline_std_bands=tile_feature_input["score_inputs"]["baseline_std_bands"],
            valid_season_optical_values=tile_feature_input["score_inputs"]["valid_season_optical_values"],
            masked_or_invalid_pixel_count=tile_feature_input["score_inputs"]["masked_or_invalid_pixel_count"],
            total_pixel_count=tile_feature_input["score_inputs"]["total_pixel_count"],
            water_edge_overlap_ratio=tile_feature_input["score_inputs"]["water_edge_overlap_ratio"],
            cloud_seam_overlap_ratio=tile_feature_input["score_inputs"]["cloud_seam_overlap_ratio"],
            compactness_ratio_value=tile_feature_input["score_inputs"]["compactness_ratio_value"],
            elongation=tile_feature_input["score_inputs"]["elongation"],
        )
        insert_tile_score(
            conn,
            tile_id=scored_tile["tile_id"],
            run_id="run-001",
            tile_feature_input_cache_key=scored_tile["tile_feature_input_cache_key"],
            source_scene_manifest_hash=scored_tile["source_scene_manifest_hash"],
            source_endpoint_id=scored_tile["source_endpoint_id"],
            optical_anomaly=scored_tile["optical_anomaly"],
            persistence=scored_tile["persistence"],
            cloud_penalty=scored_tile["cloud_penalty"],
            noise_penalty=scored_tile["noise_penalty"],
            tile_score=scored_tile["tile_score"],
            selected_for_polygonization=scored_tile["selected_for_polygonization"],
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        tile_row = conn.execute(
            """
            SELECT
                tile_id,
                source_scene_manifest_hash,
                source_endpoint_id,
                source_scene_ids_json,
                composite_metadata_cache_key,
                tile_size_m
            FROM tiles
            WHERE tile_id = ?
            """,
            (scored_tile["tile_id"],),
        ).fetchone()
        tile_feature_row = conn.execute(
            """
            SELECT
                tile_feature_input_cache_key,
                target_bands_json,
                baseline_median_bands_json,
                baseline_std_bands_json,
                valid_season_optical_values_json,
                masked_or_invalid_pixel_count,
                total_pixel_count,
                water_edge_overlap_ratio,
                cloud_seam_overlap_ratio,
                compactness_ratio_value,
                elongation
            FROM tile_features
            WHERE tile_id = ?
            """,
            (scored_tile["tile_id"],),
        ).fetchone()
        tile_score_row = conn.execute(
            """
            SELECT
                tile_id,
                tile_feature_input_cache_key,
                optical_anomaly,
                persistence,
                cloud_penalty,
                noise_penalty,
                tile_score,
                selected_for_polygonization
            FROM tile_scores
            WHERE tile_id = ?
            """,
            (scored_tile["tile_id"],),
        ).fetchone()

    assert tile_row == (
        scored_tile["tile_id"],
        "manifest-hash-001",
        "earth_search",
        json.dumps(["scene-001", "scene-002", "scene-003"]),
        composite_record["cache_key"],
        320,
    )
    assert tile_feature_row == (
        tile_input_record["cache_key"],
        json.dumps(tile_feature_input["score_inputs"]["target_bands"], sort_keys=True),
        json.dumps(tile_feature_input["score_inputs"]["baseline_median_bands"], sort_keys=True),
        json.dumps(tile_feature_input["score_inputs"]["baseline_std_bands"], sort_keys=True),
        json.dumps(tile_feature_input["score_inputs"]["valid_season_optical_values"]),
        tile_feature_input["score_inputs"]["masked_or_invalid_pixel_count"],
        tile_feature_input["score_inputs"]["total_pixel_count"],
        tile_feature_input["score_inputs"]["water_edge_overlap_ratio"],
        tile_feature_input["score_inputs"]["cloud_seam_overlap_ratio"],
        tile_feature_input["score_inputs"]["compactness_ratio_value"],
        tile_feature_input["score_inputs"]["elongation"],
    )
    assert tile_score_row == (
        scored_tile["tile_id"],
        tile_input_record["cache_key"],
        scored_tile["optical_anomaly"],
        scored_tile["persistence"],
        scored_tile["cloud_penalty"],
        scored_tile["noise_penalty"],
        scored_tile["tile_score"],
        1,
    )
