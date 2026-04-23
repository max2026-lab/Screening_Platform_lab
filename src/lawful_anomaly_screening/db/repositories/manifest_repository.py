from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect, insert_source_scene_manifest
from lawful_anomaly_screening.sources.manifest_builder import (
    create_source_scene_manifest_hash,
    manifest_payload_reference,
)


class ManifestRepository:
    def __init__(self, db_path: Path | str, manifest_root: Path | str = Path("data/manifests")) -> None:
        self.db_path = Path(db_path)
        self.manifest_root = Path(manifest_root)

    def persist_manifest(self, manifest: dict) -> dict:
        manifest_hash = create_source_scene_manifest_hash(manifest)
        manifest_path = manifest_payload_reference(manifest_hash, self.manifest_root)
        manifest_file = Path(manifest_path)
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        with connect(self.db_path) as conn:
            insert_source_scene_manifest(
                conn,
                source_scene_manifest_hash=manifest_hash,
                source_endpoint_id=manifest["source_endpoint_id"],
                source_name=manifest["source_name"],
                manifest_path=manifest_path,
            )
            conn.commit()

        return {
            "source_scene_manifest_hash": manifest_hash,
            "source_endpoint_id": manifest["source_endpoint_id"],
            "source_name": manifest["source_name"],
            "manifest_path": manifest_path,
        }

    def fetch_manifest_row(self, source_scene_manifest_hash: str) -> sqlite3.Row | None:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """
                SELECT
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    source_name,
                    manifest_path
                FROM source_scene_manifests
                WHERE source_scene_manifest_hash = ?
                """,
                (source_scene_manifest_hash,),
            ).fetchone()
