from __future__ import annotations

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
                    created_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def fetch_candidate_rows(self, run_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    cp.candidate_id,
                    cp.current_state AS review_state,
                    cp.parent_tile_id,
                    cs.parent_tile_score,
                    cs.candidate_score
                FROM candidate_polygons cp
                JOIN runs r
                    ON r.source_scene_manifest_hash = cp.source_scene_manifest_hash
                    AND r.source_endpoint_id = cp.source_endpoint_id
                LEFT JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                WHERE r.run_id = ?
                ORDER BY
                    COALESCE(cs.candidate_score, -1.0) DESC,
                    COALESCE(cs.parent_tile_score, -1.0) DESC,
                    cp.candidate_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
