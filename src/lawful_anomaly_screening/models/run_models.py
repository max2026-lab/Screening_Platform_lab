from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    processing_baseline_id: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
