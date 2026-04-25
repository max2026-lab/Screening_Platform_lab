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

    def _persist_cached_json(
        self,
        *,
        asset_kind: str,
        payload: dict,
    ) -> dict:
        content_hash = create_cache_key(asset_kind, payload)
        asset_path = cache_asset_reference(content_hash, asset_kind, self.cache_root)
        asset_file = Path(asset_path)
        asset_file.parent.mkdir(parents=True, exist_ok=True)
        asset_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with connect(self.db_path) as conn:
            insert_cached_asset(
                conn,
                cache_key=content_hash,
                asset_kind=asset_kind,
                source_scene_manifest_hash=payload["source_scene_manifest_hash"],
                source_endpoint_id=payload["source_endpoint_id"],
                asset_path=asset_path,
                content_hash=content_hash,
            )
            conn.commit()

        return {
            "cache_key": content_hash,
            "asset_kind": asset_kind,
            "source_scene_manifest_hash": payload["source_scene_manifest_hash"],
            "source_endpoint_id": payload["source_endpoint_id"],
            "asset_path": asset_path,
            "content_hash": content_hash,
        }

    def persist_preprocessing_manifest(self, preprocessing_manifest: dict) -> dict:
        return self._persist_cached_json(
            asset_kind="preprocessing_manifest",
            payload=preprocessing_manifest,
        )

    def persist_composite_metadata(self, composite_metadata_manifest: dict) -> dict:
        return self._persist_cached_json(
            asset_kind="composite_metadata",
            payload=composite_metadata_manifest,
        )

    def persist_tile_feature_input(self, tile_feature_input: dict) -> dict:
        return self._persist_cached_json(
            asset_kind="tile_feature_input",
            payload=tile_feature_input,
        )

    def persist_full_aoi_anomaly_raster(self, full_aoi_anomaly_raster_manifest: dict) -> dict:
        return self._persist_cached_json(
            asset_kind="full_aoi_anomaly_raster",
            payload=full_aoi_anomaly_raster_manifest,
        )

    def persist_polygonization_manifest(self, polygonization_manifest: dict) -> dict:
        return self._persist_cached_json(
            asset_kind="polygonization_manifest",
            payload=polygonization_manifest,
        )

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

    def fetch_cached_assets_for_rerun(
        self,
        *,
        source_scene_manifest_hash: str,
        source_endpoint_id: str,
        asset_kinds: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if asset_kinds:
                placeholders = ", ".join("?" for _ in asset_kinds)
                return conn.execute(
                    f"""
                    SELECT
                        cache_key,
                        asset_kind,
                        source_scene_manifest_hash,
                        source_endpoint_id,
                        asset_path,
                        content_hash
                    FROM cached_assets
                    WHERE source_scene_manifest_hash = ?
                      AND source_endpoint_id = ?
                      AND asset_kind IN ({placeholders})
                    ORDER BY asset_kind, cache_key
                    """,
                    (source_scene_manifest_hash, source_endpoint_id, *asset_kinds),
                ).fetchall()
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
                WHERE source_scene_manifest_hash = ?
                  AND source_endpoint_id = ?
                ORDER BY asset_kind, cache_key
                """,
                (source_scene_manifest_hash, source_endpoint_id),
            ).fetchall()
