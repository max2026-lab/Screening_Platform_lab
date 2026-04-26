from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.sources.candidate_explainability import (
    build_candidate_scoring_explanation,
    rank_items_by_score,
)
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    resolve_cloud_policy_thresholds,
)


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
                    processing_baseline_id,
                    (
                        SELECT pb.score_formula_version
                        FROM processing_baselines pb
                        WHERE pb.processing_baseline_id = runs.processing_baseline_id
                    ) AS score_formula_version,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    cache_status,
                    aoi_path,
                    aoi_geometry_type,
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
        if data.get("aoi_bbox"):
            data["aoi_bbox"] = json.loads(data["aoi_bbox"])
        data["legal_gate"] = {
            "attestation_status": data.pop("legal_attestation_status"),
            "geofence_status": data.pop("legal_geofence_status"),
            "decision": data.pop("legal_gate_decision"),
            "reason": data.pop("legal_gate_reason"),
            "evaluated_at": data.pop("legal_gate_evaluated_at"),
        }
        scenes = ManifestRepository(self.db_path).list_scenes(data["source_scene_manifest_hash"])
        data["composite_quality"] = (
            build_composite_quality_metadata(
                scenes,
                cloud_policy_thresholds=resolve_cloud_policy_thresholds(),
            )
            if scenes
            else None
        )
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

    def fetch_label_candidates(
        self,
        run_id: str,
        *,
        include_pending: bool = False,
    ) -> list[dict]:
        pending_filter = ""
        params: tuple[object, ...] = (run_id,)
        if not include_pending:
            pending_filter = "AND cp.current_state != 'pending_review'"

        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT
                    cp.candidate_id,
                    cp.run_id,
                    cp.current_state AS review_state,
                    cp.parent_tile_id,
                    cp.source_scene_manifest_hash,
                    cp.source_scene_ids_json,
                    cp.area_m2,
                    cp.boundary_touching,
                    pb.score_formula_version,
                    cs.parent_tile_score,
                    cs.candidate_score,
                    cs.score_breakdown_json,
                    ts.optical_anomaly,
                    ts.persistence,
                    ts.cloud_penalty,
                    ts.noise_penalty,
                    latest_action.reviewer_id,
                    latest_action.note AS review_note,
                    latest_action.acted_at AS reviewed_at
                FROM candidate_polygons cp
                JOIN runs r
                    ON r.run_id = cp.run_id
                LEFT JOIN processing_baselines pb
                    ON pb.processing_baseline_id = r.processing_baseline_id
                LEFT JOIN candidate_scores cs
                    ON cs.candidate_id = cp.candidate_id
                    AND cs.run_id = cp.run_id
                LEFT JOIN tile_scores ts
                    ON ts.tile_id = cp.parent_tile_id
                    AND ts.run_id = cp.run_id
                LEFT JOIN (
                    SELECT
                        ra.candidate_id,
                        ra.run_id,
                        ra.reviewer_id,
                        ra.note,
                        ra.acted_at
                    FROM review_actions ra
                    JOIN (
                        SELECT
                            candidate_id,
                            run_id,
                            MAX(review_action_id) AS latest_review_action_id
                        FROM review_actions
                        GROUP BY candidate_id, run_id
                    ) latest
                        ON latest.latest_review_action_id = ra.review_action_id
                ) latest_action
                    ON latest_action.candidate_id = cp.candidate_id
                    AND latest_action.run_id = cp.run_id
                WHERE cp.run_id = ?
                    {pending_filter}
                ORDER BY
                    COALESCE(cs.candidate_score, -1.0) DESC,
                    COALESCE(cs.parent_tile_score, -1.0) DESC,
                    cp.candidate_id ASC
                """,
                params,
            ).fetchall()

        manifest_repository = ManifestRepository(self.db_path)
        rank_map = rank_items_by_score(
            [dict(row) for row in rows],
            id_key="candidate_id",
            primary_score_key="candidate_score",
            secondary_score_key="parent_tile_score",
        )
        tile_rank_map = self._tile_rank_map(run_id)

        labels = []
        for row in rows:
            candidate = dict(row)
            source_scene_manifest_hash = candidate.pop("source_scene_manifest_hash")
            candidate["source_scene_ids"] = json.loads(candidate.pop("source_scene_ids_json"))
            candidate["source_scenes"] = manifest_repository.resolve_source_scenes(
                source_scene_manifest_hash,
                candidate["source_scene_ids"],
            )
            score_breakdown_json = candidate.pop("score_breakdown_json")
            candidate["score_breakdown"] = (
                json.loads(score_breakdown_json) if score_breakdown_json is not None else None
            )
            candidate["boundary_touching"] = bool(candidate["boundary_touching"])
            candidate["rank"] = rank_map.get(str(candidate["candidate_id"]))
            candidate["scoring_explanation"] = build_candidate_scoring_explanation(
                candidate_score=candidate.get("candidate_score"),
                parent_tile_score=candidate.get("parent_tile_score"),
                score_formula_version=candidate.get("score_formula_version"),
                rank=candidate["rank"],
                parent_tile_rank=tile_rank_map.get(str(candidate["parent_tile_id"])),
                texture_support=(candidate.get("score_breakdown") or {}).get("texture_support"),
                compactness_support=(candidate.get("score_breakdown") or {}).get("compactness_support"),
                polygon_object_score=(candidate.get("score_breakdown") or {}).get("polygon_object_score"),
                weighted_parent_tile_score=(candidate.get("score_breakdown") or {}).get(
                    "weighted_parent_tile_score"
                ),
                weighted_polygon_object_score=(candidate.get("score_breakdown") or {}).get(
                    "weighted_polygon_object_score"
                ),
                optical_anomaly=candidate.get("optical_anomaly"),
                persistence=candidate.get("persistence"),
                cloud_penalty=candidate.get("cloud_penalty"),
                noise_penalty=candidate.get("noise_penalty"),
                source_scene_ids=list(candidate.get("source_scene_ids") or []),
                source_scenes=list(candidate.get("source_scenes") or []),
                boundary_touching=bool(candidate.get("boundary_touching")),
                area_m2=candidate.get("area_m2"),
            )
            labels.append(candidate)
        return labels

    def fetch_review_state_counts(self, run_id: str) -> dict[str, int]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT current_state, COUNT(*)
                FROM candidate_polygons
                WHERE run_id = ?
                GROUP BY current_state
                ORDER BY current_state ASC
                """,
                (run_id,),
            ).fetchall()
        return {str(state): int(count) for state, count in rows}

    def fetch_latest_export_audit_manifest(self, run_id: str) -> dict | None:
        return ExportRepository(self.db_path).fetch_latest_audit_manifest(run_id)

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

    def _tile_rank_map(self, run_id: str) -> dict[str, int]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    tile_id,
                    tile_score
                FROM tile_scores
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchall()
        return rank_items_by_score(
            [dict(row) for row in rows],
            id_key="tile_id",
            primary_score_key="tile_score",
        )


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
