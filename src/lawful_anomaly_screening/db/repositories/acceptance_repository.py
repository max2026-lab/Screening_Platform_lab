from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
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
