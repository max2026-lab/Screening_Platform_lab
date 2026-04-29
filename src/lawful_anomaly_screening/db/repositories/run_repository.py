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
                    aoi_geometry_json,
                    aoi_bbox,
                    aoi_hash,
                    start_date,
                    end_date,
                    legal_attestation_status,
                    legal_geofence_status,
                    legal_gate_decision,
                    legal_gate_reason,
                    legal_gate_evaluated_at,
                    created_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        
        data = dict(row)
        if data.get("aoi_geometry_json"):
            data["aoi_geometry"] = json.loads(data.pop("aoi_geometry_json"))
        if data.get("aoi_bbox"):
            data["aoi_bbox"] = json.loads(data["aoi_bbox"])
        data["legal_gate"] = {
            "attestation_status": data.pop("legal_attestation_status"),
            "geofence_status": data.pop("legal_geofence_status"),
            "decision": data.pop("legal_gate_decision"),
            "reason": data.pop("legal_gate_reason"),
            "evaluated_at": data.pop("legal_gate_evaluated_at"),
        }
        return data

    def count_tiles(self, run_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM tiles WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_selected_tiles(self, run_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM tiles t
                JOIN tile_scores ts ON ts.tile_id = t.tile_id
                WHERE t.run_id = ? AND ts.selected_for_polygonization = 1
                """,
                (run_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_candidates(self, run_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM candidate_polygons WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def fetch_top_candidate_id(self, run_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT cp.candidate_id
                FROM candidate_polygons cp
                JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                    AND cs.run_id = cp.run_id
                WHERE cp.run_id = ?
                ORDER BY cs.candidate_score DESC, cs.parent_tile_score DESC, cp.candidate_id ASC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return str(row[0]) if row else None

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
