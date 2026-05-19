from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import sqlite3

from lawful_anomaly_screening.aoi.validation import derive_execution_geometry_summary
from lawful_anomaly_screening.db.repositories.cache_repository import CacheRepository
from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.sqlite import (
    connect,
    init_db,
    insert_candidate_feature,
    insert_candidate_polygon,
    insert_candidate_score,
    insert_tile,
    insert_tile_feature,
    insert_tile_score,
    update_run_state,
)
from lawful_anomaly_screening.sources.candidate_scoring import (
    build_candidate_score_records,
    rank_candidate_scores,
)
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_metadata_manifest,
    build_preprocessing_manifest,
    flag_top_valid_tiles_for_aoi,
    generate_fixed_tile_grid,
    score_retained_tile,
)
from lawful_anomaly_screening.sources.polygonization import (
    build_candidate_feature_records,
    build_candidate_polygon_records,
    build_full_aoi_anomaly_raster_manifest,
    build_polygonization_manifest,
)


def _stable_scene_digest(*parts: str) -> str:
    return sha256("::".join(parts).encode("utf-8")).hexdigest()


def _zero_candidate_reason(diagnostics: dict[str, object]) -> str:
    final_candidate_count = int(diagnostics["final_candidate_count"])
    if final_candidate_count > 0:
        return "candidates_generated"

    raw_polygon_count = int(diagnostics["raw_polygon_count"])
    dropped_below_min_area_count = int(diagnostics["dropped_below_min_area_count"])
    dropped_below_pixel_floor_count = int(diagnostics["dropped_below_pixel_floor_count"])
    dropped_tile_edge_eligibility_count = int(
        diagnostics["dropped_tile_edge_eligibility_count"]
    )

    if raw_polygon_count == 0:
        return "no_raw_polygons"
    if raw_polygon_count == dropped_below_min_area_count:
        return "all_polygons_dropped_below_min_area"
    if raw_polygon_count == dropped_below_pixel_floor_count:
        return "all_polygons_dropped_below_pixel_floor"
    if raw_polygon_count == dropped_tile_edge_eligibility_count:
        return "all_polygons_dropped_by_tile_edge_eligibility"
    return "candidates_removed_by_multiple_filters"


def build_tile_scene_attribution(
    *,
    source_scene_manifest_hash: str,
    tile_ids: list[str],
    discovered_scene_ids: list[str],
    attribution_seed_keys: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    ordered_scene_ids = sorted(set(discovered_scene_ids))
    if not ordered_scene_ids:
        return {tile_id: [] for tile_id in tile_ids}

    max_subset_size = 1 if len(ordered_scene_ids) == 1 else len(ordered_scene_ids) - 1
    attribution: dict[str, list[str]] = {}
    for tile_id in sorted(tile_ids):
        tile_seed_key = attribution_seed_keys.get(tile_id, tile_id) if attribution_seed_keys else tile_id
        size_digest = _stable_scene_digest(source_scene_manifest_hash, tile_seed_key, "scene-count")
        subset_size = 1 + (int(size_digest[:8], 16) % max_subset_size)
        start_digest = _stable_scene_digest(source_scene_manifest_hash, tile_seed_key, "scene-start")
        start_index = int(start_digest[:8], 16) % len(ordered_scene_ids)
        rotated_scene_ids = ordered_scene_ids[start_index:] + ordered_scene_ids[:start_index]
        attribution[tile_id] = sorted(rotated_scene_ids[:subset_size])
    return attribution


def fetch_run_seed_context(db_path: Path | str, run_id: str) -> dict:
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                r.run_id,
                r.processing_baseline_id,
                r.source_scene_manifest_hash,
                r.source_endpoint_id,
                r.status,
                r.cache_status,
                r.aoi_geometry_type,
                r.aoi_geometry_json,
                r.aoi_bbox,
                r.aoi_hash,
                s.source_name,
                s.manifest_path
            FROM runs r
            JOIN source_scene_manifests s
                ON s.source_scene_manifest_hash = r.source_scene_manifest_hash
            WHERE r.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"run not found: {run_id}")
    data = dict(row)
    if data.get("aoi_geometry_json"):
        data["aoi_geometry"] = json.loads(data.pop("aoi_geometry_json"))
    if data.get("aoi_bbox"):
        data["aoi_bbox"] = json.loads(data["aoi_bbox"])
    return data


def scaffold_run_for_run_id(
    db_path: Path | str,
    *,
    run_id: str,
    cache_root: Path | str = Path("data/cache"),
) -> dict:
    init_db(db_path)
    run_context = fetch_run_seed_context(db_path, run_id)
    cache_repository = CacheRepository(db_path, cache_root=cache_root)

    preprocessing_manifest = build_preprocessing_manifest(
        source_scene_manifest_hash=run_context["source_scene_manifest_hash"],
        source_endpoint_id=run_context["source_endpoint_id"],
        season_window_name="leaf_on",
    )
    preprocessing_record = cache_repository.persist_preprocessing_manifest(preprocessing_manifest)
    discovered_scenes = ManifestRepository(db_path).list_scenes(
        run_context["source_scene_manifest_hash"]
    )
    composite_manifest = build_composite_metadata_manifest(
        preprocessing_manifest,
        preprocessing_record["cache_key"],
        composite_season_window_name="leaf_on",
        scenes=discovered_scenes,
    )
    composite_record = cache_repository.persist_composite_metadata(composite_manifest)
    execution_geometry = derive_execution_geometry_summary(
        run_context.get("aoi_geometry"),
        run_context.get("aoi_bbox"),
    )
    source_scene_ids = [scene["scene_id"] for scene in discovered_scenes]

    tile_grid = generate_fixed_tile_grid(
        composite_manifest,
        composite_record["cache_key"],
        run_id=run_id,
        width=execution_geometry["grid_width"],
        height=execution_geometry["grid_height"],
        grid_bounds=execution_geometry["derived_tile_bbox"],
    )
    scored_tiles = []
    for tile in tile_grid:
        tile_feature_record = cache_repository.persist_tile_feature_input(tile)
        tile["tile_feature_input_cache_key"] = tile_feature_record["cache_key"]
        scored_tiles.append(score_retained_tile(tile))

    flagged_tiles = flag_top_valid_tiles_for_aoi(
        scored_tiles,
        run_context.get("aoi_geometry"),
    )
    scored_by_id = {tile["tile_id"]: tile for tile in flagged_tiles}
    tile_attribution_seed_keys = {
        tile["tile_id"]: f"{tile['x_index']}:{tile['y_index']}"
        for tile in tile_grid
    }
    tile_source_scene_ids_by_tile_id = build_tile_scene_attribution(
        source_scene_manifest_hash=run_context["source_scene_manifest_hash"],
        tile_ids=[tile["tile_id"] for tile in tile_grid],
        discovered_scene_ids=source_scene_ids,
        attribution_seed_keys=tile_attribution_seed_keys,
    )

    with connect(db_path) as conn:
        for tile in tile_grid:
            score_inputs = tile["score_inputs"]
            scored_tile = scored_by_id[tile["tile_id"]]
            insert_tile(
                conn,
                tile_id=tile["tile_id"],
                run_id=run_id,
                source_scene_manifest_hash=tile["source_scene_manifest_hash"],
                source_endpoint_id=tile["source_endpoint_id"],
                source_scene_ids=tile_source_scene_ids_by_tile_id[tile["tile_id"]],
                composite_metadata_cache_key=tile["composite_metadata_cache_key"],
                tile_size_m=tile["tile_size_m"],
                x_index=tile["x_index"],
                y_index=tile["y_index"],
                is_valid=tile["is_valid"],
            )
            insert_tile_feature(
                conn,
                tile_feature_input_cache_key=tile["tile_feature_input_cache_key"],
                run_id=run_id,
                tile_id=tile["tile_id"],
                source_scene_manifest_hash=tile["source_scene_manifest_hash"],
                source_endpoint_id=tile["source_endpoint_id"],
                target_bands=score_inputs["target_bands"],
                baseline_median_bands=score_inputs["baseline_median_bands"],
                baseline_std_bands=score_inputs["baseline_std_bands"],
                valid_season_optical_values=score_inputs["valid_season_optical_values"],
                masked_or_invalid_pixel_count=score_inputs["masked_or_invalid_pixel_count"],
                total_pixel_count=score_inputs["total_pixel_count"],
                water_edge_overlap_ratio=score_inputs["water_edge_overlap_ratio"],
                cloud_seam_overlap_ratio=score_inputs["cloud_seam_overlap_ratio"],
                compactness_ratio_value=score_inputs["compactness_ratio_value"],
                elongation=score_inputs["elongation"],
            )
            insert_tile_score(
                conn,
                tile_id=tile["tile_id"],
                run_id=run_id,
                tile_feature_input_cache_key=tile["tile_feature_input_cache_key"],
                source_scene_manifest_hash=tile["source_scene_manifest_hash"],
                source_endpoint_id=tile["source_endpoint_id"],
                optical_anomaly=scored_tile["optical_anomaly"],
                persistence=scored_tile["persistence"],
                cloud_penalty=scored_tile["cloud_penalty"],
                noise_penalty=scored_tile["noise_penalty"],
                tile_score=scored_tile["tile_score"],
                selected_for_polygonization=scored_tile["selected_for_polygonization"],
            )
        conn.commit()

    tile_records = []
    for tile in tile_grid:
        tile_record = dict(tile)
        tile_record.update(
            tile_score=scored_by_id[tile["tile_id"]]["tile_score"],
            selected_for_polygonization=scored_by_id[tile["tile_id"]]["selected_for_polygonization"],
            source_scene_ids=tile_source_scene_ids_by_tile_id[tile["tile_id"]],
        )
        tile_records.append(tile_record)

    full_aoi_manifest = build_full_aoi_anomaly_raster_manifest(
        composite_manifest,
        composite_record["cache_key"],
        tile_records,
        aoi_geometry=run_context.get("aoi_geometry"),
        aoi_bbox=run_context.get("aoi_bbox"),
    )
    full_aoi_record = cache_repository.persist_full_aoi_anomaly_raster(full_aoi_manifest)
    polygonization_manifest = build_polygonization_manifest(
        full_aoi_manifest,
        full_aoi_record["cache_key"],
    )
    polygonization_record = cache_repository.persist_polygonization_manifest(polygonization_manifest)

    candidate_records, candidate_filter_diagnostics = build_candidate_polygon_records(
        polygonization_manifest,
        polygonization_record["cache_key"],
        run_id=run_id,
        tile_source_scene_ids_by_tile_id=tile_source_scene_ids_by_tile_id,
        return_diagnostics=True,
    )
    feature_records = build_candidate_feature_records(candidate_records)
    score_records = rank_candidate_scores(
        build_candidate_score_records(candidate_records, feature_records, flagged_tiles)
    )

    with connect(db_path) as conn:
        for candidate_record in candidate_records:
            insert_candidate_polygon(
                conn,
                candidate_id=candidate_record["candidate_id"],
                run_id=run_id,
                polygonization_manifest_cache_key=candidate_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=candidate_record["source_scene_manifest_hash"],
                source_endpoint_id=candidate_record["source_endpoint_id"],
                parent_tile_id=candidate_record["parent_tile_id"],
                source_scene_ids=candidate_record["source_scene_ids"],
                bounds=candidate_record["bounds"],
                centroid=candidate_record["centroid"],
                clipped_geometry=candidate_record["clipped_geometry"],
                area_m2=candidate_record["area_m2"],
                perimeter_m=candidate_record["perimeter_m"],
                pixel_count=candidate_record["pixel_count"],
                boundary_touching=candidate_record["boundary_touching"],
                possible_duplicate=candidate_record["possible_duplicate"],
                duplicate_resolution_action=candidate_record["duplicate_resolution_action"],
            )
        for feature_record in feature_records:
            insert_candidate_feature(
                conn,
                candidate_id=feature_record["candidate_id"],
                run_id=run_id,
                polygonization_manifest_cache_key=feature_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=feature_record["source_scene_manifest_hash"],
                source_endpoint_id=feature_record["source_endpoint_id"],
                compactness_ratio=feature_record["compactness_ratio"],
                convex_hull_area_m2=feature_record["convex_hull_area_m2"],
                elongation=feature_record["elongation"],
                local_contrast_values=feature_record["local_contrast_values"],
                water_edge_overlap_ratio=feature_record["water_edge_overlap_ratio"],
                cloud_seam_overlap_ratio=feature_record["cloud_seam_overlap_ratio"],
            )
        for score_record in score_records:
            insert_candidate_score(
                conn,
                candidate_id=score_record["candidate_id"],
                run_id=run_id,
                polygonization_manifest_cache_key=score_record["polygonization_manifest_cache_key"],
                source_scene_manifest_hash=score_record["source_scene_manifest_hash"],
                source_endpoint_id=score_record["source_endpoint_id"],
                parent_tile_id=score_record["parent_tile_id"],
                parent_tile_score=score_record["parent_tile_score"],
                texture_support=score_record["texture_support"],
                compactness_support=score_record["compactness_support"],
                polygon_object_score=score_record["polygon_object_score"],
                candidate_score=score_record["candidate_score"],
                score_breakdown=score_record["score_breakdown"],
                contribution_sum=score_record["contribution_sum"],
                integrity_delta=score_record["integrity_delta"],
                integrity_within_tolerance=score_record["integrity_within_tolerance"],
            )
        update_run_state(conn, run_id=run_id, status="review_ready", cache_status="warm")
        conn.commit()

    selected_tiles = [tile for tile in flagged_tiles if tile["selected_for_polygonization"]]
    polygonization_diagnostics = polygonization_manifest.get(
        "polygonization_diagnostics",
        {},
    )
    candidate_generation_diagnostics = {
        "diagnostic_version": "v1",
        "tile_count": len(tile_grid),
        "valid_tile_count": sum(1 for tile in tile_grid if tile["is_valid"]),
        "selected_tile_count": len(selected_tiles),
        "raw_polygon_count": int(polygonization_diagnostics.get("raw_polygon_count", 0)),
        "dropped_below_min_area_count": int(
            candidate_filter_diagnostics.get("dropped_below_min_area_count", 0)
        ),
        "dropped_below_pixel_floor_count": int(
            candidate_filter_diagnostics.get("dropped_below_pixel_floor_count", 0)
        ),
        "dropped_tile_edge_eligibility_count": int(
            polygonization_diagnostics.get("dropped_tile_edge_eligibility_count", 0)
        ),
        "duplicate_merged_count": int(
            polygonization_diagnostics.get("duplicate_merged_count", 0)
        ),
        "possible_duplicate_count": int(
            polygonization_diagnostics.get("possible_duplicate_count", 0)
        ),
        "final_candidate_count": len(candidate_records),
        "raw_polygonization_diagnostics": polygonization_diagnostics.get(
            "raw_polygonization_diagnostics",
            {},
        ),
        "pixel_floor_diagnostics": candidate_filter_diagnostics.get(
            "pixel_floor_diagnostics",
            {},
        ),
    }
    candidate_generation_diagnostics["zero_candidate_reason"] = _zero_candidate_reason(
        candidate_generation_diagnostics
    )
    return {
        "run_id": run_id,
        "source_scene_manifest_hash": run_context["source_scene_manifest_hash"],
        "source_endpoint_id": run_context["source_endpoint_id"],
        "execution_geometry": execution_geometry,
        "composite_quality": composite_manifest["composite_quality"],
        "preprocessing_manifest_cache_key": preprocessing_record["cache_key"],
        "composite_metadata_cache_key": composite_record["cache_key"],
        "full_aoi_anomaly_raster_cache_key": full_aoi_record["cache_key"],
        "polygonization_manifest_cache_key": polygonization_record["cache_key"],
        "tile_count": len(tile_grid),
        "selected_tile_count": len(selected_tiles),
        "candidate_count": len(candidate_records),
        "candidate_generation_diagnostics": candidate_generation_diagnostics,
        "candidate_ids": [record["candidate_id"] for record in score_records],
        "top_candidate_id": score_records[0]["candidate_id"] if score_records else None,
    }
