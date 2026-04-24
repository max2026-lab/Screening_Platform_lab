from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run
from lawful_anomaly_screening.db.sqlite import connect
from lawful_anomaly_screening.orchestration.scaffold_run import scaffold_run_for_run_id
import sqlite3


def seed_reviewable_candidates(db_path, cache_root):
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-001",
        manifest_path="data/manifests/manifest-hash-001.json",
    )
    summary = scaffold_run_for_run_id(
        db_path,
        run_id="run-001",
        cache_root=cache_root,
    )
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        candidate_records = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    candidate_id,
                    polygonization_manifest_cache_key,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    parent_tile_id,
                    current_state,
                    bounds_json,
                    centroid_json,
                    area_m2,
                    perimeter_m,
                    pixel_count,
                    boundary_touching,
                    possible_duplicate,
                    duplicate_resolution_action
                FROM candidate_polygons
                WHERE run_id = ?
                ORDER BY candidate_id ASC
                """,
                (summary["run_id"],),
            ).fetchall()
        ]
        score_records = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    candidate_id,
                    polygonization_manifest_cache_key,
                    source_scene_manifest_hash,
                    source_endpoint_id,
                    parent_tile_id,
                    parent_tile_score,
                    texture_support,
                    compactness_support,
                    polygon_object_score,
                    candidate_score,
                    score_breakdown_json,
                    contribution_sum,
                    integrity_delta,
                    integrity_within_tolerance
                FROM candidate_scores
                WHERE run_id = ?
                ORDER BY candidate_score DESC, parent_tile_score DESC, candidate_id ASC
                """,
                (summary["run_id"],),
            ).fetchall()
        ]
    return candidate_records, score_records
