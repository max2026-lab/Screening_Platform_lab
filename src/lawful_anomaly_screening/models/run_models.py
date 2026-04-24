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


@dataclass(frozen=True)
class CompositeMetadataRecord:
    source_scene_manifest_hash: str
    source_endpoint_id: str
    preprocessing_manifest_cache_key: str
    preprocessing_season_window_name: str
    composite_season_window_name: str


@dataclass(frozen=True)
class TileRecord:
    tile_id: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    composite_metadata_cache_key: str
    tile_size_m: int
    x_index: int
    y_index: int
    is_valid: bool


@dataclass(frozen=True)
class TileFeatureRecord:
    tile_feature_input_cache_key: str
    tile_id: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    target_bands_json: str
    baseline_median_bands_json: str
    baseline_std_bands_json: str
    valid_season_optical_values_json: str
    masked_or_invalid_pixel_count: int
    total_pixel_count: int
    water_edge_overlap_ratio: float
    cloud_seam_overlap_ratio: float
    compactness_ratio_value: float
    elongation: float


@dataclass(frozen=True)
class TileScoreRecord:
    tile_id: str
    tile_feature_input_cache_key: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    optical_anomaly: float
    persistence: float
    cloud_penalty: float
    noise_penalty: float
    tile_score: float
    selected_for_polygonization: bool
