import json
from pathlib import Path

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import connect, init_db, insert_source_scene_manifest
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
    build_full_aoi_anomaly_raster_manifest,
    build_polygonization_manifest,
)


def test_cache_repository_persists_polygonization_scaffold_records(tmp_path):
    db_path = tmp_path / "polygonization.sqlite3"
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

    tile_grid = generate_fixed_tile_grid(composite_manifest, composite_record["cache_key"])
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
        composite_record["cache_key"],
        tile_records,
    )
    full_aoi_record = repository.persist_full_aoi_anomaly_raster(full_aoi_manifest)

    first_selected_tile = full_aoi_manifest["selected_tiles"][0]
    min_x, min_y, max_x, max_y = first_selected_tile["bounds"]
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        full_aoi_record["cache_key"],
        anomaly_regions=[
            {
                "region_id": "polygon-a",
                "bounds": [min_x + 24.0, min_y + 24.0, min_x + 124.0, min_y + 124.0],
            },
            {
                "region_id": "polygon-b",
                "bounds": [min_x + 48.0, min_y + 48.0, min_x + 148.0, min_y + 148.0],
            },
        ],
    )
    polygonization_record = repository.persist_polygonization_manifest(polygonization_manifest)

    full_aoi_row = repository.fetch_cached_asset_row(full_aoi_record["cache_key"])
    polygonization_row = repository.fetch_cached_asset_row(polygonization_record["cache_key"])

    assert full_aoi_row is not None
    assert full_aoi_row["asset_kind"] == "full_aoi_anomaly_raster"
    assert polygonization_row is not None
    assert polygonization_row["asset_kind"] == "polygonization_manifest"

    full_aoi_payload = json.loads(Path(full_aoi_record["asset_path"]).read_text(encoding="utf-8"))
    polygonization_payload = json.loads(
        Path(polygonization_record["asset_path"]).read_text(encoding="utf-8")
    )

    assert full_aoi_payload["selected_tile_count"] == 3
    assert polygonization_payload["polygon_count"] == 1
    assert polygonization_payload["polygons"][0]["source_region_ids"] == [
        "polygon-a",
        "polygon-b",
    ]
