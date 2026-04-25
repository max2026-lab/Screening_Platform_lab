from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect, insert_export_record
from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.exports.precision_policy import (
    build_artifact_name,
    build_bundle_name,
    export_subdirectory,
    normalize_export_tier,
    resolve_export_policy,
    sanitize_candidates_for_export,
)
from lawful_anomaly_screening.exports.reporting import render_markdown_report
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    resolve_cloud_policy_thresholds,
)
from lawful_anomaly_screening.sources.candidate_explainability import (
    build_candidate_scoring_explanation,
    rank_items_by_score,
)


class ExportRepository:
    def __init__(self, db_path: Path | str, export_root: Path | str = Path(".")) -> None:
        self.db_path = Path(db_path)
        self.export_root = Path(export_root)

    def persist_export(
        self,
        *,
        run_id: str,
        audience: str,
        candidates: list[dict],
        requested_precision: str | None = None,
    ) -> dict:
        run_metadata = RunRepository(self.db_path).fetch_run(run_id)
        if run_metadata is not None:
            run_metadata = dict(run_metadata)
            scenes = ManifestRepository(self.db_path).list_scenes(
                run_metadata["source_scene_manifest_hash"]
            )
            run_metadata["composite_quality"] = build_composite_quality_metadata(
                scenes,
                cloud_policy_thresholds=resolve_cloud_policy_thresholds(),
            )
        normalized_audience = normalize_export_tier(audience)
        policy = resolve_export_policy(normalized_audience, requested_precision)
        sanitized_candidates = sanitize_candidates_for_export(
            candidates,
            normalized_audience,
            requested_precision,
        )
        centroid = sanitized_candidates[0]["centroid"] if sanitized_candidates else None
        artifact_kind = "report" if normalized_audience == "report_pdf" else "export"
        artifact_extension = "md" if normalized_audience == "report_pdf" else "json"
        artifact_name = build_artifact_name(
            run_id=run_id,
            audience=normalized_audience,
            artifact_kind=artifact_kind,
            centroid=centroid,
            requested_precision=requested_precision,
            extension=artifact_extension,
        )
        bundle_name = build_bundle_name(
            run_id=run_id,
            audience=normalized_audience,
            artifact_kind=artifact_kind,
            centroid=centroid,
            requested_precision=requested_precision,
        )
        artifact_path = export_subdirectory(normalized_audience) / artifact_name
        export_record_id = self._create_export_record_id(
            run_id=run_id,
            audience=normalized_audience,
            precision_tier=policy.precision_tier,
            artifact_name=artifact_name,
            candidate_ids=[candidate["candidate_id"] for candidate in sanitized_candidates],
        )

        if normalized_audience == "report_pdf":
            resolved_path = self.export_root / artifact_path
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(
                render_markdown_report(
                    run_id=run_id,
                    audience=normalized_audience,
                    policy=policy,
                    artifact_name=artifact_name,
                    bundle_name=bundle_name,
                    candidates=sanitized_candidates,
                ),
                encoding="utf-8",
            )

        with connect(self.db_path) as conn:
            insert_export_record(
                conn,
                export_record_id=export_record_id,
                run_id=run_id,
                audience=normalized_audience,
                precision_tier=policy.precision_tier,
                artifact_name=artifact_name,
                bundle_name=bundle_name,
                artifact_path=str(artifact_path).replace("\\", "/"),
                exact_coordinates_included=policy.exact_coordinates_included,
                coordinate_resolution_m=policy.coordinate_resolution_m,
            )
            conn.commit()

        return {
            "export_record_id": export_record_id,
            "run_id": run_id,
            "run_metadata": run_metadata,
            "audience": normalized_audience,
            "precision_tier": policy.precision_tier,
            "artifact_name": artifact_name,
            "bundle_name": bundle_name,
            "artifact_path": str(artifact_path).replace("\\", "/"),
            "exact_coordinates_included": policy.exact_coordinates_included,
            "coordinate_resolution_m": policy.coordinate_resolution_m,
            "candidates": sanitized_candidates,
        }

    def fetch_export_records(self, run_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    export_record_id,
                    run_id,
                    audience,
                    precision_tier,
                    artifact_name,
                    bundle_name,
                    artifact_path,
                    exact_coordinates_included,
                    coordinate_resolution_m,
                    created_at
                FROM export_records
                WHERE run_id = ?
                ORDER BY audience ASC, export_record_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_export_candidates(self, run_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    cp.candidate_id,
                    cp.run_id,
                    cp.current_state,
                    cp.parent_tile_id,
                    cp.source_scene_manifest_hash,
                    cp.source_scene_ids_json,
                    cp.bounds_json,
                    cp.centroid_json,
                    cp.clipped_geometry_json,
                    cp.area_m2,
                    cp.perimeter_m,
                    cp.pixel_count,
                    cp.boundary_touching,
                    cp.possible_duplicate,
                    cp.duplicate_resolution_action,
                    pb.score_formula_version,
                    cs.parent_tile_score,
                    cs.candidate_score,
                    cs.score_breakdown_json,
                    ts.optical_anomaly,
                    ts.persistence,
                    ts.cloud_penalty,
                    ts.noise_penalty
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
                WHERE cp.run_id = ?
                ORDER BY
                    COALESCE(cs.candidate_score, -1.0) DESC,
                    COALESCE(cs.parent_tile_score, -1.0) DESC,
                    cp.candidate_id ASC
                """,
                (run_id,),
            ).fetchall()

        candidates = []
        manifest_repository = ManifestRepository(self.db_path)
        rank_map = rank_items_by_score(
            [dict(row) for row in rows],
            id_key="candidate_id",
            primary_score_key="candidate_score",
            secondary_score_key="parent_tile_score",
        )
        tile_rank_map = self._tile_rank_map(run_id)
        for row in rows:
            candidate = dict(row)
            source_scene_manifest_hash = candidate.pop("source_scene_manifest_hash")
            candidate["source_scene_ids"] = json.loads(candidate.pop("source_scene_ids_json"))
            candidate["source_scenes"] = manifest_repository.resolve_source_scenes(
                source_scene_manifest_hash,
                candidate["source_scene_ids"],
            )
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
            candidate["boundary_touching"] = bool(candidate["boundary_touching"])
            candidate["possible_duplicate"] = bool(candidate["possible_duplicate"])
            candidate["scoring_explanation"] = build_candidate_scoring_explanation(
                candidate_score=candidate.get("candidate_score"),
                parent_tile_score=candidate.get("parent_tile_score"),
                score_formula_version=candidate.get("score_formula_version"),
                rank=rank_map.get(str(candidate["candidate_id"])),
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
            candidates.append(candidate)
        return candidates

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

    @staticmethod
    def _create_export_record_id(
        *,
        run_id: str,
        audience: str,
        precision_tier: str,
        artifact_name: str,
        candidate_ids: list[str],
    ) -> str:
        payload = {
            "artifact_name": artifact_name,
            "audience": audience,
            "candidate_ids": candidate_ids,
            "precision_tier": precision_tier,
            "run_id": run_id,
        }
        digest = sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return f"export-{digest[:16]}"
