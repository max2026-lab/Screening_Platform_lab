from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect, insert_cached_asset
from lawful_anomaly_screening.sources.manifest_builder import cache_asset_reference, create_cache_key


class CacheRepository:
    def __init__(self, db_path: Path | str, cache_root: Path | str = Path("data/cache")) -> None:
        self.db_path = Path(db_path)
        self.cache_root = Path(cache_root)

    def persist_preprocessing_manifest(self, preprocessing_manifest: dict) -> dict:
        asset_kind = "preprocessing_manifest"
        content_hash = create_cache_key(asset_kind, preprocessing_manifest)
        asset_path = cache_asset_reference(content_hash, asset_kind, self.cache_root)
        asset_file = Path(asset_path)
        asset_file.parent.mkdir(parents=True, exist_ok=True)
        asset_file.write_text(
            json.dumps(preprocessing_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with connect(self.db_path) as conn:
            insert_cached_asset(
                conn,
                cache_key=content_hash,
                asset_kind=asset_kind,
                source_scene_manifest_hash=preprocessing_manifest["source_scene_manifest_hash"],
                source_endpoint_id=preprocessing_manifest["source_endpoint_id"],
                asset_path=asset_path,
                content_hash=content_hash,
            )
            conn.commit()

        return {
            "cache_key": content_hash,
            "asset_kind": asset_kind,
            "source_scene_manifest_hash": preprocessing_manifest["source_scene_manifest_hash"],
            "source_endpoint_id": preprocessing_manifest["source_endpoint_id"],
            "asset_path": asset_path,
            "content_hash": content_hash,
        }

    def fetch_cached_asset_row(self, cache_key: str) -> sqlite3.Row | None:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT
                    cache_key,
                    asset_kind,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    asset_path,
                    content_hash
                FROM cached_assets
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
