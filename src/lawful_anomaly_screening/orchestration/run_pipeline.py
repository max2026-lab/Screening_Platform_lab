from __future__ import annotations

from pathlib import Path

from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    resolve_cloud_policy_thresholds,
)

from .scaffold_run import scaffold_run_for_run_id

def execute_run(
    db_path: Path | str,
    *,
    run_id: str,
    cache_root: Path | str = Path("data/cache"),
) -> dict:
    run_metadata = RunRepository(db_path).fetch_run(run_id)
    if run_metadata is None:
        raise ValueError(f"run not found: {run_id}")
    scenes = ManifestRepository(db_path).list_scenes(run_metadata["source_scene_manifest_hash"])
    composite_quality = build_composite_quality_metadata(
        scenes,
        cloud_policy_thresholds=resolve_cloud_policy_thresholds(),
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
