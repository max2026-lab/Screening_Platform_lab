from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def insert_processing_baseline(
    conn: sqlite3.Connection,
    processing_baseline_id: str,
    score_formula_version: str,
    execution_mode: str = "synchronous",
    persistence_backend: str = "sqlite",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO processing_baselines (
            processing_baseline_id,
            score_formula_version,
            execution_mode,
            persistence_backend
        ) VALUES (?, ?, ?, ?)
        """,
        (processing_baseline_id, score_formula_version, execution_mode, persistence_backend),
    )


def insert_source_scene_manifest(
    conn: sqlite3.Connection,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    source_name: str = "earth_search",
    manifest_path: str = "",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO source_scene_manifests (
            source_scene_manifest_hash,
            source_endpoint_id,
            source_name,
            manifest_path
        ) VALUES (?, ?, ?, ?)
        """,
        (source_scene_manifest_hash, source_endpoint_id, source_name, manifest_path),
    )


def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    processing_baseline_id: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    status: str = "new",
    execution_mode: str = "synchronous",
    rerun_mode: str = "full",
    cache_status: str = "cold",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO runs (
            run_id,
            status,
            processing_baseline_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            execution_mode,
            rerun_mode,
            cache_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            status,
            processing_baseline_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            execution_mode,
            rerun_mode,
            cache_status,
        ),
    )


def insert_cached_asset(
    conn: sqlite3.Connection,
    cache_key: str,
    asset_kind: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    asset_path: str,
    content_hash: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO cached_assets (
            cache_key,
            asset_kind,
            source_scene_manifest_hash,
            source_endpoint_id,
            asset_path,
            content_hash
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            asset_kind,
            source_scene_manifest_hash,
            source_endpoint_id,
            asset_path,
            content_hash,
        ),
    )


def insert_tile(
    conn: sqlite3.Connection,
    *,
    tile_id: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    composite_metadata_cache_key: str,
    tile_feature_input_cache_key: str,
    tile_size_m: int,
    x_index: int,
    y_index: int,
    is_valid: bool,
    optical_anomaly: float,
    persistence: float,
    cloud_penalty: float,
    noise_penalty: float,
    retained_score: float,
    top_valid_selection_flag: bool,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tiles (
            tile_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            composite_metadata_cache_key,
            tile_feature_input_cache_key,
            tile_size_m,
            x_index,
            y_index,
            is_valid,
            optical_anomaly,
            persistence,
            cloud_penalty,
            noise_penalty,
            retained_score,
            top_valid_selection_flag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tile_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            composite_metadata_cache_key,
            tile_feature_input_cache_key,
            tile_size_m,
            x_index,
            y_index,
            int(is_valid),
            optical_anomaly,
            persistence,
            cloud_penalty,
            noise_penalty,
            retained_score,
            int(top_valid_selection_flag),
        ),
    )


def bootstrap_minimal_run(
    db_path: Path | str,
    *,
    processing_baseline_id: str,
    score_formula_version: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    run_id: str,
    source_name: str = "earth_search",
    manifest_path: str = "",
    run_status: str = "new",
) -> dict[str, Any]:
    with connect(db_path) as conn:
        insert_processing_baseline(
            conn,
            processing_baseline_id=processing_baseline_id,
            score_formula_version=score_formula_version,
        )
        insert_source_scene_manifest(
            conn,
            source_scene_manifest_hash=source_scene_manifest_hash,
            source_endpoint_id=source_endpoint_id,
            source_name=source_name,
            manifest_path=manifest_path,
        )
        insert_run(
            conn,
            run_id=run_id,
            processing_baseline_id=processing_baseline_id,
            source_scene_manifest_hash=source_scene_manifest_hash,
            source_endpoint_id=source_endpoint_id,
            status=run_status,
        )
        conn.commit()
    return {
        "processing_baseline_id": processing_baseline_id,
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "source_endpoint_id": source_endpoint_id,
        "run_id": run_id,
    }
