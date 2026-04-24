from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect


class RunRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def fetch_run(self, run_id: str) -> dict | None:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    run_id,
                    status,
                    processing_baseline_id,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    execution_mode,
                    rerun_mode,
                    cache_status,
                    aoi_path,
                    aoi_geometry_type,
                    aoi_bbox,
                    aoi_hash,
                    start_date,
                    end_date,
                    created_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        
        data = dict(row)
        if data.get("aoi_bbox"):
            data["aoi_bbox"] = json.loads(data["aoi_bbox"])
        return data

    def update_run_state(self, *, run_id: str, status: str, cache_status: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, cache_status = ?
                WHERE run_id = ?
                """,
                (status, cache_status, run_id),
            )
            conn.commit()
