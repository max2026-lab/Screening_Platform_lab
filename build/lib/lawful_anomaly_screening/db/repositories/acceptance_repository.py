from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect


class AcceptanceRepository:
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
                    source_scene_manifest_hash,
                    source_endpoint_id,
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

    def fetch_candidate_rows(self, run_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    cp.candidate_id,
                    cp.run_id,
                    cp.current_state AS review_state,
                    cp.parent_tile_id,
                    cp.bounds_json,
                    cp.centroid_json,
                    cp.area_m2,
                    cp.perimeter_m,
                    cp.pixel_count,
                    cs.parent_tile_score,
                    cs.candidate_score
                FROM candidate_polygons cp
                LEFT JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                    AND cs.run_id = cp.run_id
                WHERE cp.run_id = ?
                ORDER BY
                    COALESCE(cs.candidate_score, -1.0) DESC,
                    COALESCE(cs.parent_tile_score, -1.0) DESC,
                    cp.candidate_id ASC
                """,
                (run_id,),
            ).fetchall()
        candidate_rows = []
        for row in rows:
            candidate = dict(row)
            candidate["stable_candidate_key"] = _stable_candidate_key(candidate)
            candidate_rows.append(candidate)
        return candidate_rows

    def count_paid_escalations(self, run_id: str) -> int:
        with connect(self.db_path) as conn:
            quote_count = conn.execute(
                """
                SELECT COUNT(DISTINCT candidate_id)
                FROM paid_quotes
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
            order_count = conn.execute(
                """
                SELECT COUNT(DISTINCT candidate_id)
                FROM paid_orders
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        return int(max(quote_count, order_count))


def _stable_candidate_key(candidate_row: dict) -> str:
    payload = {
        "bounds": json.loads(candidate_row["bounds_json"]),
        "centroid": json.loads(candidate_row["centroid_json"]),
        "area_m2": round(float(candidate_row["area_m2"]), 6),
        "perimeter_m": round(float(candidate_row["perimeter_m"]), 6),
        "pixel_count": int(candidate_row["pixel_count"]),
    }
    digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest
