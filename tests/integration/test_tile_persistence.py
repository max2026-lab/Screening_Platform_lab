import sqlite3

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import (
    connect,
    init_db,
    insert_source_scene_manifest,
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

    with connect(db_path) as conn:
        insert_source_scene_manifest(
            conn,
            source_scene_manifest_hash="manifest-hash-001",
            source_endpoint_id="earth_search",
            source_name="earth-search",
            manifest_path="data/manifests/manifest-hash-001.json",
        )
        conn.commit()

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
            source_scene_manifest_hash=tile_feature_input["source_scene_manifest_hash"],
            source_endpoint_id=tile_feature_input["source_endpoint_id"],
            composite_metadata_cache_key=tile_feature_input["composite_metadata_cache_key"],
            tile_size_m=tile_feature_input["tile_size_m"],
            x_index=tile_feature_input["x_index"],
            y_index=tile_feature_input["y_index"],
            is_valid=tile_feature_input["is_valid"],
        )
        insert_tile_feature(
            conn,
            tile_feature_input_cache_key=tile_input_record["cache_key"],
            tile_id=tile_feature_input["tile_id"],
            source_scene_manifest_hash=tile_feature_input["source_scene_manifest_hash"],
            source_endpoint_id=tile_feature_input["source_endpoint_id"],
            optical_signal=tile_feature_input["score_inputs"]["optical_signal"],
            optical_baseline=tile_feature_input["score_inputs"]["optical_baseline"],
            persistence_detections=tile_feature_input["score_inputs"]["persistence_detections"],
            persistence_observations=tile_feature_input["score_inputs"]["persistence_observations"],
            cloud_fraction=tile_feature_input["score_inputs"]["cloud_fraction"],
            noise_fraction=tile_feature_input["score_inputs"]["noise_fraction"],
        )
        insert_tile_score(
            conn,
            tile_id=scored_tile["tile_id"],
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
                optical_signal,
                optical_baseline,
                persistence_detections,
                persistence_observations,
                cloud_fraction,
                noise_fraction
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
        composite_record["cache_key"],
        320,
    )
    assert tile_feature_row == (
        tile_input_record["cache_key"],
        tile_feature_input["score_inputs"]["optical_signal"],
        tile_feature_input["score_inputs"]["optical_baseline"],
        tile_feature_input["score_inputs"]["persistence_detections"],
        tile_feature_input["score_inputs"]["persistence_observations"],
        tile_feature_input["score_inputs"]["cloud_fraction"],
        tile_feature_input["score_inputs"]["noise_fraction"],
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
