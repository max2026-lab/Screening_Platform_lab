from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect, insert_review_action
from lawful_anomaly_screening.exceptions import ReviewDecisionError, ReviewStateError


REVIEW_DECISION_REJECT = "reject"
REVIEW_DECISION_WATCH = "watch"
REVIEW_DECISION_APPROVE_FOR_ARCHIVE_QUOTE = "approve_for_archive_quote"
VALID_REVIEW_DECISIONS = (
    REVIEW_DECISION_REJECT,
    REVIEW_DECISION_WATCH,
    REVIEW_DECISION_APPROVE_FOR_ARCHIVE_QUOTE,
)

CANDIDATE_STATE_PENDING_REVIEW = "pending_review"
CANDIDATE_STATE_WATCH = "watch"
CANDIDATE_STATE_REJECTED = "rejected"
CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE = "approved_for_archive_quote"
REVIEW_QUEUE_STATES = (
    CANDIDATE_STATE_PENDING_REVIEW,
    CANDIDATE_STATE_WATCH,
)

DECISION_TO_STATE = {
    REVIEW_DECISION_REJECT: CANDIDATE_STATE_REJECTED,
    REVIEW_DECISION_WATCH: CANDIDATE_STATE_WATCH,
    REVIEW_DECISION_APPROVE_FOR_ARCHIVE_QUOTE: CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE,
}

ALLOWED_STATE_TRANSITIONS = {
    CANDIDATE_STATE_PENDING_REVIEW: set(VALID_REVIEW_DECISIONS),
    CANDIDATE_STATE_WATCH: set(VALID_REVIEW_DECISIONS),
    CANDIDATE_STATE_REJECTED: set(),
    CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE: set(),
}


class ReviewRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def list_runs(self) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    status,
                    processing_baseline_id,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    created_at
                FROM runs
                ORDER BY run_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_review_queue(
        self,
        *,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        limit_clause = ""
        run_filter_clause = ""
        params_list: list[object] = list(REVIEW_QUEUE_STATES)
        if run_id is not None:
            run_filter_clause = "AND cp.run_id = ?"
            params_list.append(run_id)
        if limit is not None:
            limit_clause = "LIMIT ?"
            params_list.append(limit)

        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT
                    cp.candidate_id,
                    cp.parent_tile_id,
                    cp.current_state,
                    cp.possible_duplicate,
                    cp.duplicate_resolution_action,
                    cp.run_id,
                    r.status AS run_status,
                    cs.parent_tile_score,
                    cs.candidate_score
                FROM candidate_polygons cp
                JOIN runs r
                    ON r.run_id = cp.run_id
                LEFT JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                    AND cs.run_id = cp.run_id
                WHERE cp.current_state IN (?, ?)
                    {run_filter_clause}
                ORDER BY
                    CASE cp.current_state
                        WHEN 'pending_review' THEN 0
                        WHEN 'watch' THEN 1
                        ELSE 2
                    END,
                    COALESCE(cs.candidate_score, -1.0) DESC,
                    cp.candidate_id ASC
                {limit_clause}
                """,
                tuple(params_list),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_candidate(self, candidate_id: str, run_id: str | None = None) -> dict | None:
        run_filter_clause = ""
        params: tuple[object, ...]
        if run_id is not None:
            run_filter_clause = "AND cp.run_id = ?"
            params = (candidate_id, run_id)
        else:
            params = (candidate_id,)
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT
                    cp.candidate_id,
                    cp.parent_tile_id,
                    cp.source_scene_ids_json,
                    cp.current_state,
                    cp.run_id,
                    r.status AS run_status,
                    cp.bounds_json,
                    cp.centroid_json,
                    cp.clipped_geometry_json,
                    cp.area_m2,
                    cp.perimeter_m,
                    cp.pixel_count,
                    cp.boundary_touching,
                    cp.possible_duplicate,
                    cp.duplicate_resolution_action,
                    cs.parent_tile_score,
                    cs.candidate_score,
                    cs.score_breakdown_json
                FROM candidate_polygons cp
                JOIN runs r
                    ON r.run_id = cp.run_id
                LEFT JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                    AND cs.run_id = cp.run_id
                WHERE cp.candidate_id = ?
                    {run_filter_clause}
                ORDER BY cp.run_id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None:
            return None
        candidate = dict(row)
        candidate["source_scene_ids"] = json.loads(candidate.pop("source_scene_ids_json"))
        candidate["bounds"] = json.loads(candidate.pop("bounds_json"))
        candidate["centroid"] = json.loads(candidate.pop("centroid_json"))
        clipped_geometry_json = candidate.pop("clipped_geometry_json")
        candidate["clipped_geometry"] = (
            json.loads(clipped_geometry_json) if clipped_geometry_json is not None else None
        )
        score_breakdown_json = candidate.pop("score_breakdown_json")
        candidate["score_breakdown"] = (
            json.loads(score_breakdown_json) if score_breakdown_json is not None else None
        )
        return candidate

    def fetch_review_actions(self, candidate_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    review_action_id,
                    candidate_id,
                    run_id,
                    reviewer_id,
                    decision,
                    prior_state,
                    new_state,
                    note,
                    acted_at
                FROM review_actions
                WHERE candidate_id = ?
                ORDER BY review_action_id ASC
                """,
                (candidate_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def decide(
        self,
        *,
        candidate_id: str,
        run_id: str,
        reviewer_id: str,
        decision: str,
        note: str | None = None,
    ) -> dict:
        if decision not in VALID_REVIEW_DECISIONS:
            raise ReviewDecisionError(f"unsupported review decision: {decision}")

        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            candidate_row = conn.execute(
                """
                SELECT candidate_id, current_state
                FROM candidate_polygons
                WHERE candidate_id = ?
                  AND run_id = ?
                """,
                (candidate_id, run_id),
            ).fetchone()
            if candidate_row is None:
                raise ReviewStateError(f"candidate not found: {candidate_id}")

            prior_state = str(candidate_row["current_state"])
            if decision not in ALLOWED_STATE_TRANSITIONS.get(prior_state, set()):
                raise ReviewStateError(
                    f"invalid review transition: {prior_state} -> {decision}"
                )

            new_state = DECISION_TO_STATE[decision]
            conn.execute(
                """
                UPDATE candidate_polygons
                SET current_state = ?
                WHERE candidate_id = ?
                  AND run_id = ?
                """,
                (new_state, candidate_id, run_id),
            )
            insert_review_action(
                conn,
                candidate_id=candidate_id,
                run_id=run_id,
                reviewer_id=reviewer_id,
                decision=decision,
                prior_state=prior_state,
                new_state=new_state,
                note=note,
            )
            action_row = conn.execute(
                """
                SELECT
                    review_action_id,
                    candidate_id,
                    run_id,
                    reviewer_id,
                    decision,
                    prior_state,
                    new_state,
                    note,
                    acted_at
                FROM review_actions
                WHERE review_action_id = last_insert_rowid()
                """
            ).fetchone()
            conn.commit()

        if action_row is None:
            raise ReviewStateError("review action was not persisted")
        return dict(action_row)
