from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    resolve_cloud_policy_thresholds,
)

from .scaffold_run import scaffold_run_for_run_id


def _load_run_scene_context(
    db_path: Path | str,
    *,
    run_id: str,
) -> tuple[dict, dict, list[dict], dict]:
    run_repository = RunRepository(db_path)
    manifest_repository = ManifestRepository(db_path)
    try:
        run_metadata = run_repository.fetch_run(run_id)
    except sqlite3.OperationalError as exc:
        if "no such table: runs" in str(exc):
            raise ValueError(f"run not found: {run_id}") from exc
        raise
    if run_metadata is None:
        raise ValueError(f"run not found: {run_id}")

    manifest_row = manifest_repository.fetch_manifest_row(
        run_metadata["source_scene_manifest_hash"]
    )
    if manifest_row is None:
        raise ValueError(
            f"run {run_id} is missing source scene manifest metadata"
        )

    manifest_metadata = dict(manifest_row)
    manifest_path_value = manifest_metadata.get("manifest_path")
    if not manifest_path_value:
        raise ValueError(f"run {run_id} source scene manifest path is missing")
    manifest_path = Path(manifest_path_value)
    if not manifest_path.exists():
        raise ValueError(
            f"run {run_id} source scene manifest missing at {manifest_path}"
        )
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"run {run_id} source scene manifest is invalid JSON: {manifest_path}"
        ) from exc
    if not isinstance(manifest_payload, dict):
        raise ValueError(
            f"run {run_id} source scene manifest has invalid structure: {manifest_path}"
        )
    if not isinstance(manifest_payload.get("scenes"), list):
        raise ValueError(
            f"run {run_id} source scene manifest is missing scenes: {manifest_path}"
        )

    scenes = manifest_repository.list_scenes(run_metadata["source_scene_manifest_hash"])
    composite_quality = build_composite_quality_metadata(
        scenes,
        cloud_policy_thresholds=resolve_cloud_policy_thresholds(),
    )
    return run_metadata, manifest_metadata, scenes, composite_quality


def build_scene_window_precheck(
    db_path: Path | str,
    *,
    run_id: str,
) -> dict:
    run_metadata, _, _, composite_quality = _load_run_scene_context(
        db_path,
        run_id=run_id,
    )

    scene_count = composite_quality["scene_count"]
    clear_scene_count = composite_quality["clear_scene_count"]
    cloud_policy_decision = composite_quality["cloud_policy_decision"]

    if scene_count == 0:
        recommendation = "choose_different_window"
        recommendation_reason = "No scenes were discovered for this date window."
    elif cloud_policy_decision == "fail":
        recommendation = "choose_different_window"
        recommendation_reason = "Cloud policy failed for the current date window."
    elif clear_scene_count == 0:
        recommendation = "widen_date_window"
        recommendation_reason = "No clear scenes are available in the current date window."
    elif clear_scene_count < 2:
        recommendation = "widen_date_window"
        recommendation_reason = "Fewer than two clear scenes are available."
    elif cloud_policy_decision == "warn":
        recommendation = "proceed_with_caution"
        recommendation_reason = "Scene quality is usable but cloud coverage is elevated."
    else:
        recommendation = "proceed"
        recommendation_reason = "Scene quality meets the current cloud policy."

    return {
        "run_id": run_metadata["run_id"],
        "source_endpoint_id": run_metadata["source_endpoint_id"],
        "source_scene_manifest_hash": run_metadata["source_scene_manifest_hash"],
        "start_date": run_metadata["start_date"],
        "end_date": run_metadata["end_date"],
        "scene_count": scene_count,
        "clear_scene_count": clear_scene_count,
        "cloudy_scene_count": composite_quality["cloudy_scene_count"],
        "mean_cloud_cover": composite_quality["mean_cloud_cover"],
        "max_cloud_cover": composite_quality["max_cloud_cover"],
        "cloud_policy_decision": cloud_policy_decision,
        "cloud_policy_reason": composite_quality["cloud_policy_reason"],
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
    }


def execute_run(
    db_path: Path | str,
    *,
    run_id: str,
    cache_root: Path | str = Path("data/cache"),
) -> dict:
    run_metadata, _, scenes, composite_quality = _load_run_scene_context(
        db_path,
        run_id=run_id,
    )
    if composite_quality["cloud_policy_decision"] == "fail":
        raise ValueError(
            "run blocked by cloud policy: "
            f"{composite_quality['cloud_policy_reason']}"
        )
    summary = scaffold_run_for_run_id(
        db_path,
        run_id=run_id,
        cache_root=cache_root,
    )
    refreshed_run_metadata = RunRepository(db_path).fetch_run(run_id)
    if refreshed_run_metadata is None:
        raise ValueError(f"run not found: {run_id}")
    run_metadata = dict(refreshed_run_metadata)
    run_metadata["composite_quality"] = composite_quality
    if "candidate_generation_diagnostics" in summary:
        run_metadata["candidate_generation_diagnostics"] = summary["candidate_generation_diagnostics"]
    summary["run_metadata"] = run_metadata
    summary["scene_summary"] = {
        "scene_count": len(scenes),
        "scene_ids": [scene["scene_id"] for scene in scenes],
        "start_date": run_metadata["start_date"],
        "end_date": run_metadata["end_date"],
        "composite_quality": composite_quality,
    }
    summary["composite_quality"] = composite_quality
    summary["aoi_execution_geometry"] = {
        "aoi_bbox": run_metadata["aoi_bbox"],
        "derived_tile_bbox": summary["execution_geometry"]["derived_tile_bbox"],
        "tile_count": summary["tile_count"],
        "selected_tile_count": summary["selected_tile_count"],
    }
    return summary
