import sqlite3

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import connect, init_db, insert_source_scene_manifest, insert_tile
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
    scored_tile["top_valid_selection_flag"] = True

    with connect(db_path) as conn:
        insert_tile(conn, **scored_tile)
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                tile_id,
                source_scene_manifest_hash,
                source_endpoint_id,
                composite_metadata_cache_key,
                tile_feature_input_cache_key,
                tile_size_m,
                optical_anomaly,
                persistence,
                cloud_penalty,
                noise_penalty,
                retained_score,
                top_valid_selection_flag
            FROM tiles
            WHERE tile_id = ?
            """,
            (scored_tile["tile_id"],),
        ).fetchone()

    assert row[0] == scored_tile["tile_id"]
    assert row[1] == "manifest-hash-001"
    assert row[2] == "earth_search"
    assert row[3] == composite_record["cache_key"]
    assert row[4] == tile_input_record["cache_key"]
    assert row[5] == 320
    assert row[10] == scored_tile["retained_score"]
    assert row[11] == 1
