import json
from pathlib import Path

from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.sqlite import init_db, insert_source_scene_manifest, connect
from lawful_anomaly_screening.orchestration.rerun_modes import (
    CACHE_STATUS_HIT,
    CACHE_STATUS_PARTIAL,
    RERUN_MODE_EXACT_CACHED,
    build_rerun_plan,
)
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


def test_cache_repository_links_cached_assets_for_reruns(tmp_path):
    db_path = tmp_path / "cache-rerun.sqlite3"
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
    repository.persist_composite_metadata(
        {
            "manifest_version": "phase1-composite-metadata-v1",
            "execution_mode": "synchronous",
            "source_scene_manifest_hash": "manifest-hash-001",
            "source_endpoint_id": "earth_search",
            "preprocessing_manifest_cache_key": preprocessing_record["cache_key"],
            "preprocessing_season_window_name": "leaf_on",
            "composite_season_window_name": "leaf_on",
            "season_window": {"start_month_day": "04-01", "end_month_day": "09-30"},
            "cloud_mask": {"provider": "stubbed-cloud-mask"},
        }
    )

    rerun_rows = repository.fetch_cached_assets_for_rerun(
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        asset_kinds=["preprocessing_manifest", "composite_metadata", "polygonization_manifest"],
    )
    rerun_plan = build_rerun_plan(
        run_id="run-001",
        rerun_mode=RERUN_MODE_EXACT_CACHED,
        required_asset_kinds=["preprocessing_manifest", "composite_metadata", "polygonization_manifest"],
        cached_asset_rows=[dict(row) for row in rerun_rows],
    )

    assert [row["asset_kind"] for row in rerun_rows] == [
        "composite_metadata",
        "preprocessing_manifest",
    ]
    assert rerun_plan["cache_status"] == CACHE_STATUS_PARTIAL
    assert rerun_plan["reuse_cached_assets"] is False

    hit_plan = build_rerun_plan(
        run_id="run-001",
        rerun_mode=RERUN_MODE_EXACT_CACHED,
        required_asset_kinds=["preprocessing_manifest", "composite_metadata"],
        cached_asset_rows=[dict(row) for row in rerun_rows],
    )
    assert hit_plan["cache_status"] == CACHE_STATUS_HIT
