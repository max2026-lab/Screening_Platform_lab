from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    processing_baseline_id: str
    source_scene_manifest_hash: str
    source_endpoint_id: str


@dataclass(frozen=True)
class PreprocessingManifestRecord:
    source_scene_manifest_hash: str
    source_endpoint_id: str
    season_window_name: str
    cloud_mask_provider: str


@dataclass(frozen=True)
class CachedAssetRecord:
    cache_key: str
    asset_kind: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    asset_path: str
