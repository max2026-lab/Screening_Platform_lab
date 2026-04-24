from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
    processing_baseline_id: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    rerun_mode: str
    cache_status: str


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


@dataclass(frozen=True)
class CandidatePolygonRecord:
    candidate_id: str
    polygonization_manifest_cache_key: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    parent_tile_id: str
    bounds_json: str
    centroid_json: str
    area_m2: float
    perimeter_m: float
    pixel_count: int
    boundary_touching: bool
    possible_duplicate: bool
    duplicate_resolution_action: str


@dataclass(frozen=True)
class CandidateFeatureRecord:
    candidate_id: str
    polygonization_manifest_cache_key: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    compactness_ratio: float
    convex_hull_area_m2: float
    elongation: float
    local_contrast_inputs_json: str
    water_edge_overlap_ratio: float
    cloud_seam_overlap_ratio: float


@dataclass(frozen=True)
class CandidateScoreRecord:
    candidate_id: str
    polygonization_manifest_cache_key: str
    source_scene_manifest_hash: str
    source_endpoint_id: str
    parent_tile_id: str
    parent_tile_score: float
    texture_support: float
    compactness_support: float
    polygon_object_score: float
    candidate_score: float
    score_breakdown_json: str
    contribution_sum: float
    integrity_delta: float
    integrity_within_tolerance: bool
