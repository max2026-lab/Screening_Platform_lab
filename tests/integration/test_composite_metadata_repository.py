import json
from pathlib import Path

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import connect, init_db, insert_source_scene_manifest
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
)


def test_composite_metadata_persistence_links_to_preprocessing_manifest(tmp_path):
    db_path = tmp_path / "composite.sqlite3"
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

    composite_metadata = build_composite_metadata_manifest(
        preprocessing_manifest,
        preprocessing_record["cache_key"],
        composite_season_window_name="leaf_on",
    )
    composite_record = repository.persist_composite_metadata(composite_metadata)
    stored_row = repository.fetch_cached_asset_row(composite_record["cache_key"])

    assert stored_row is not None
    assert stored_row["asset_kind"] == "composite_metadata"
    assert stored_row["source_scene_manifest_hash"] == "manifest-hash-001"
    assert stored_row["source_endpoint_id"] == "earth_search"
    payload = json.loads(Path(composite_record["asset_path"]).read_text(encoding="utf-8"))
    assert payload["preprocessing_manifest_cache_key"] == preprocessing_record["cache_key"]
    assert payload["composite_season_window_name"] == "leaf_on"
