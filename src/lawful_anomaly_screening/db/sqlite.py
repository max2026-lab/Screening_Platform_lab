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
    source_name: str = "earth_search",
    manifest_path: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO source_scene_manifests (
            source_scene_manifest_hash,
            source_name,
            manifest_path
        ) VALUES (?, ?, ?)
        """,
        (source_scene_manifest_hash, source_name, manifest_path),
    )


def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    processing_baseline_id: str,
    source_scene_manifest_hash: str,
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
            execution_mode,
            rerun_mode,
            cache_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            status,
            processing_baseline_id,
            source_scene_manifest_hash,
            execution_mode,
            rerun_mode,
            cache_status,
        ),
    )


def bootstrap_minimal_run(
    db_path: Path | str,
    *,
    processing_baseline_id: str,
    score_formula_version: str,
    source_scene_manifest_hash: str,
    run_id: str,
    source_name: str = "earth_search",
    manifest_path: str | None = None,
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
            source_name=source_name,
            manifest_path=manifest_path,
        )
        insert_run(
            conn,
            run_id=run_id,
            processing_baseline_id=processing_baseline_id,
            source_scene_manifest_hash=source_scene_manifest_hash,
            status=run_status,
        )
        conn.commit()
    return {
        "processing_baseline_id": processing_baseline_id,
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "run_id": run_id,
    }
