from __future__ import annotations

from pathlib import Path
import json
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
    source_endpoint_id: str,
    source_name: str = "earth_search",
    manifest_path: str = "",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO source_scene_manifests (
            source_scene_manifest_hash,
            source_endpoint_id,
            source_name,
            manifest_path
        ) VALUES (?, ?, ?, ?)
        """,
        (source_scene_manifest_hash, source_endpoint_id, source_name, manifest_path),
    )


def insert_discovered_scene(
    conn: sqlite3.Connection,
    *,
    source_scene_manifest_hash: str,
    scene_id: str,
    source_endpoint_id: str,
    acquired_at: str,
    cloud_cover: float,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO discovered_scenes (
            source_scene_manifest_hash,
            scene_id,
            source_endpoint_id,
            acquired_at,
            cloud_cover
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            source_scene_manifest_hash,
            scene_id,
            source_endpoint_id,
            acquired_at,
            cloud_cover,
        ),
    )


def insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    processing_baseline_id: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    status: str = "new",
    execution_mode: str = "synchronous",
    rerun_mode: str = "review_only",
    cache_status: str = "miss",
    aoi_path: str | None = None,
    aoi_geometry_type: str | None = None,
    aoi_bbox: list[float] | None = None,
    aoi_hash: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO runs (
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
            end_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
            json.dumps(aoi_bbox) if aoi_bbox else None,
            aoi_hash,
            start_date,
            end_date,
        ),
    )


def update_run_state(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    cache_status: str,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET status = ?, cache_status = ?
        WHERE run_id = ?
        """,
        (status, cache_status, run_id),
    )


def insert_cached_asset(
    conn: sqlite3.Connection,
    cache_key: str,
    asset_kind: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    asset_path: str,
    content_hash: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO cached_assets (
            cache_key,
            asset_kind,
            source_scene_manifest_hash,
            source_endpoint_id,
            asset_path,
            content_hash
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            cache_key,
            asset_kind,
            source_scene_manifest_hash,
            source_endpoint_id,
            asset_path,
            content_hash,
        ),
    )


def insert_export_record(
    conn: sqlite3.Connection,
    *,
    export_record_id: str,
    run_id: str,
    audience: str,
    precision_tier: str,
    artifact_name: str,
    bundle_name: str,
    artifact_path: str,
    exact_coordinates_included: bool,
    coordinate_resolution_m: int | None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO export_records (
            export_record_id,
            run_id,
            audience,
            precision_tier,
            artifact_name,
            bundle_name,
            artifact_path,
            exact_coordinates_included,
            coordinate_resolution_m
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            export_record_id,
            run_id,
            audience,
            precision_tier,
            artifact_name,
            bundle_name,
            artifact_path,
            int(exact_coordinates_included),
            coordinate_resolution_m,
        ),
    )


def insert_tile(
    conn: sqlite3.Connection,
    *,
    tile_id: str,
    run_id: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    composite_metadata_cache_key: str,
    tile_size_m: int,
    x_index: int,
    y_index: int,
    is_valid: bool,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tiles (
            tile_id,
            run_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            composite_metadata_cache_key,
            tile_size_m,
            x_index,
            y_index,
            is_valid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tile_id,
            run_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            composite_metadata_cache_key,
            tile_size_m,
            x_index,
            y_index,
            int(is_valid),
        ),
    )


def insert_tile_feature(
    conn: sqlite3.Connection,
    *,
    tile_feature_input_cache_key: str,
    run_id: str,
    tile_id: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    target_bands: dict[str, float],
    baseline_median_bands: dict[str, float],
    baseline_std_bands: dict[str, float],
    valid_season_optical_values: list[float],
    masked_or_invalid_pixel_count: int,
    total_pixel_count: int,
    water_edge_overlap_ratio: float,
    cloud_seam_overlap_ratio: float,
    compactness_ratio_value: float,
    elongation: float,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tile_features (
            tile_feature_input_cache_key,
            run_id,
            tile_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            target_bands_json,
            baseline_median_bands_json,
            baseline_std_bands_json,
            valid_season_optical_values_json,
            masked_or_invalid_pixel_count,
            total_pixel_count,
            water_edge_overlap_ratio,
            cloud_seam_overlap_ratio,
            compactness_ratio_value,
            elongation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tile_feature_input_cache_key,
            run_id,
            tile_id,
            source_scene_manifest_hash,
            source_endpoint_id,
            json.dumps(target_bands, sort_keys=True),
            json.dumps(baseline_median_bands, sort_keys=True),
            json.dumps(baseline_std_bands, sort_keys=True),
            json.dumps(valid_season_optical_values),
            masked_or_invalid_pixel_count,
            total_pixel_count,
            water_edge_overlap_ratio,
            cloud_seam_overlap_ratio,
            compactness_ratio_value,
            elongation,
        ),
    )


def insert_tile_score(
    conn: sqlite3.Connection,
    *,
    tile_id: str,
    run_id: str,
    tile_feature_input_cache_key: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    optical_anomaly: float,
    persistence: float,
    cloud_penalty: float,
    noise_penalty: float,
    tile_score: float,
    selected_for_polygonization: bool,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO tile_scores (
            tile_id,
            run_id,
            tile_feature_input_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            optical_anomaly,
            persistence,
            cloud_penalty,
            noise_penalty,
            tile_score,
            selected_for_polygonization
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tile_id,
            run_id,
            tile_feature_input_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            optical_anomaly,
            persistence,
            cloud_penalty,
            noise_penalty,
            tile_score,
            int(selected_for_polygonization),
        ),
    )


def insert_candidate_polygon(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str,
    polygonization_manifest_cache_key: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    parent_tile_id: str,
    current_state: str = "pending_review",
    bounds: list[float],
    centroid: list[float],
    area_m2: float,
    perimeter_m: float,
    pixel_count: int,
    boundary_touching: bool,
    possible_duplicate: bool,
    duplicate_resolution_action: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO candidate_polygons (
            candidate_id,
            run_id,
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            run_id,
            polygonization_manifest_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            parent_tile_id,
            current_state,
            json.dumps(bounds),
            json.dumps(centroid),
            area_m2,
            perimeter_m,
            pixel_count,
            int(boundary_touching),
            int(possible_duplicate),
            duplicate_resolution_action,
        ),
    )


def insert_candidate_feature(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str,
    polygonization_manifest_cache_key: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    compactness_ratio: float,
    convex_hull_area_m2: float,
    elongation: float,
    local_contrast_values: list[float],
    water_edge_overlap_ratio: float,
    cloud_seam_overlap_ratio: float,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO candidate_features (
            candidate_id,
            run_id,
            polygonization_manifest_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            compactness_ratio,
            convex_hull_area_m2,
            elongation,
            local_contrast_inputs_json,
            water_edge_overlap_ratio,
            cloud_seam_overlap_ratio
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            run_id,
            polygonization_manifest_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            compactness_ratio,
            convex_hull_area_m2,
            elongation,
            json.dumps(local_contrast_values),
            water_edge_overlap_ratio,
            cloud_seam_overlap_ratio,
        ),
    )


def insert_candidate_score(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str,
    polygonization_manifest_cache_key: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    parent_tile_id: str,
    parent_tile_score: float,
    texture_support: float,
    compactness_support: float,
    polygon_object_score: float,
    candidate_score: float,
    score_breakdown: dict[str, float],
    contribution_sum: float,
    integrity_delta: float,
    integrity_within_tolerance: bool,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO candidate_scores (
            candidate_id,
            run_id,
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            run_id,
            polygonization_manifest_cache_key,
            source_scene_manifest_hash,
            source_endpoint_id,
            parent_tile_id,
            parent_tile_score,
            texture_support,
            compactness_support,
            polygon_object_score,
            candidate_score,
            json.dumps(score_breakdown, sort_keys=True),
            contribution_sum,
            integrity_delta,
            int(integrity_within_tolerance),
        ),
    )


def insert_review_action(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str,
    reviewer_id: str,
    decision: str,
    prior_state: str,
    new_state: str,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO review_actions (
            candidate_id,
            run_id,
            reviewer_id,
            decision,
            prior_state,
            new_state,
            note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            run_id,
            reviewer_id,
            decision,
            prior_state,
            new_state,
            note,
        ),
    )


def upsert_paid_quote(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str | None,
    project_id: str | None,
    provider: str,
    provider_quote_id: str,
    amount: float,
    credits: float,
    currency: str,
    eula_reference: str,
    paid_status: str,
    archive_mode: str,
    tasking_requested: bool,
    autonomous_purchase_enabled: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO paid_quotes (
            provider_quote_id,
            candidate_id,
            run_id,
            project_id,
            provider,
            amount,
            credits,
            currency,
            eula_reference,
            paid_status,
            archive_mode,
            tasking_requested,
            autonomous_purchase_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider_quote_id) DO UPDATE SET
            candidate_id = excluded.candidate_id,
            run_id = excluded.run_id,
            project_id = excluded.project_id,
            provider = excluded.provider,
            amount = excluded.amount,
            credits = excluded.credits,
            currency = excluded.currency,
            eula_reference = excluded.eula_reference,
            paid_status = excluded.paid_status,
            archive_mode = excluded.archive_mode,
            tasking_requested = excluded.tasking_requested,
            autonomous_purchase_enabled = excluded.autonomous_purchase_enabled,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            provider_quote_id,
            candidate_id,
            run_id,
            project_id,
            provider,
            amount,
            credits,
            currency,
            eula_reference,
            paid_status,
            archive_mode,
            int(tasking_requested),
            int(autonomous_purchase_enabled),
        ),
    )


def upsert_paid_order(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    run_id: str | None,
    project_id: str | None,
    provider: str,
    provider_quote_id: str,
    provider_order_id: str,
    amount: float,
    credits: float,
    currency: str,
    eula_reference: str,
    paid_status: str,
    archive_mode: str,
    tasking_requested: bool,
    autonomous_purchase_enabled: bool,
    human_triggered_by: str,
) -> None:
    conn.execute(
        """
        INSERT INTO paid_orders (
            provider_order_id,
            provider_quote_id,
            candidate_id,
            run_id,
            project_id,
            provider,
            amount,
            credits,
            currency,
            eula_reference,
            paid_status,
            archive_mode,
            tasking_requested,
            autonomous_purchase_enabled,
            human_triggered_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider_order_id) DO UPDATE SET
            provider_quote_id = excluded.provider_quote_id,
            candidate_id = excluded.candidate_id,
            run_id = excluded.run_id,
            project_id = excluded.project_id,
            provider = excluded.provider,
            amount = excluded.amount,
            credits = excluded.credits,
            currency = excluded.currency,
            eula_reference = excluded.eula_reference,
            paid_status = excluded.paid_status,
            archive_mode = excluded.archive_mode,
            tasking_requested = excluded.tasking_requested,
            autonomous_purchase_enabled = excluded.autonomous_purchase_enabled,
            human_triggered_by = excluded.human_triggered_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            provider_order_id,
            provider_quote_id,
            candidate_id,
            run_id,
            project_id,
            provider,
            amount,
            credits,
            currency,
            eula_reference,
            paid_status,
            archive_mode,
            int(tasking_requested),
            int(autonomous_purchase_enabled),
            human_triggered_by,
        ),
    )


def bootstrap_minimal_run(
    db_path: Path | str,
    *,
    processing_baseline_id: str,
    score_formula_version: str,
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    run_id: str,
    source_name: str = "earth_search",
    manifest_path: str = "",
    run_status: str = "new",
    aoi_path: str | None = None,
    aoi_geometry_type: str | None = None,
    aoi_bbox: list[float] | None = None,
    aoi_hash: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
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
            source_endpoint_id=source_endpoint_id,
            source_name=source_name,
            manifest_path=manifest_path,
        )
        insert_run(
            conn,
            run_id=run_id,
            processing_baseline_id=processing_baseline_id,
            source_scene_manifest_hash=source_scene_manifest_hash,
            source_endpoint_id=source_endpoint_id,
            status=run_status,
            aoi_path=aoi_path,
            aoi_geometry_type=aoi_geometry_type,
            aoi_bbox=aoi_bbox,
            aoi_hash=aoi_hash,
            start_date=start_date,
            end_date=end_date,
        )
        conn.commit()
    return {
        "processing_baseline_id": processing_baseline_id,
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "source_endpoint_id": source_endpoint_id,
        "run_id": run_id,
    }
