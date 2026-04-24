from __future__ import annotations

from pathlib import Path

from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.repositories.run_repository import RunRepository

from .scaffold_run import scaffold_run_for_run_id

def execute_run(
    db_path: Path | str,
    *,
    run_id: str,
    cache_root: Path | str = Path("data/cache"),
) -> dict:
    summary = scaffold_run_for_run_id(
        db_path,
        run_id=run_id,
        cache_root=cache_root,
    )
    run_metadata = RunRepository(db_path).fetch_run(run_id)
    if run_metadata is None:
        raise ValueError(f"run not found: {run_id}")
    scenes = ManifestRepository(db_path).list_scenes(run_metadata["source_scene_manifest_hash"])
    summary["run_metadata"] = run_metadata
    summary["scene_summary"] = {
        "scene_count": len(scenes),
        "scene_ids": [scene["scene_id"] for scene in scenes],
        "start_date": run_metadata["start_date"],
        "end_date": run_metadata["end_date"],
    }
    return summary
