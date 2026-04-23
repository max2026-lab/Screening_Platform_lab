import json
from pathlib import Path

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import init_db, insert_source_scene_manifest, connect
from lawful_anomaly_screening.sources.manifest_builder import build_preprocessing_manifest


def test_cache_repository_persists_preprocessing_manifest_record(tmp_path):
    db_path = tmp_path / "cache.sqlite3"
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

    record = repository.persist_preprocessing_manifest(preprocessing_manifest)
    stored_row = repository.fetch_cached_asset_row(record["cache_key"])

    assert stored_row is not None
    assert stored_row["asset_kind"] == "preprocessing_manifest"
    assert stored_row["source_scene_manifest_hash"] == "manifest-hash-001"
    assert stored_row["source_endpoint_id"] == "earth_search"
    assert Path(record["asset_path"]).is_file()
    payload = json.loads(Path(record["asset_path"]).read_text(encoding="utf-8"))
    assert payload["season_window_name"] == "leaf_on"
    assert payload["cloud_mask"]["provider"] == "stubbed-cloud-mask"
