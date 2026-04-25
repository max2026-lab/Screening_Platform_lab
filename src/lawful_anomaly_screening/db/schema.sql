PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processing_baselines (
    processing_baseline_id TEXT PRIMARY KEY,
    score_formula_version TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    persistence_backend TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feature_versions (
    feature_name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_scene_manifests (
    source_scene_manifest_hash TEXT PRIMARY KEY,
    source_endpoint_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discovered_scenes (
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    scene_id TEXT NOT NULL,
    source_endpoint_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    cloud_cover REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_scene_manifest_hash, scene_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    processing_baseline_id TEXT NOT NULL REFERENCES processing_baselines(processing_baseline_id),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    rerun_mode TEXT NOT NULL,
    cache_status TEXT NOT NULL,
    aoi_path TEXT,
    aoi_geometry_type TEXT,
    aoi_geometry_json TEXT,
    aoi_bbox TEXT,
    aoi_hash TEXT,
    start_date TEXT,
    end_date TEXT,
    legal_attestation_status TEXT NOT NULL DEFAULT 'missing',
    legal_geofence_status TEXT NOT NULL DEFAULT 'missing',
    legal_gate_decision TEXT NOT NULL DEFAULT 'fail',
    legal_gate_reason TEXT NOT NULL DEFAULT '',
    legal_gate_evaluated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cached_assets (
    cache_key TEXT PRIMARY KEY,
    asset_kind TEXT NOT NULL,
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geofence_hits (
    geofence_hit_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    hit_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS export_records (
    export_record_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    audience TEXT NOT NULL,
    precision_tier TEXT NOT NULL,
    artifact_name TEXT NOT NULL,
    bundle_name TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    exact_coordinates_included INTEGER NOT NULL DEFAULT 0,
    coordinate_resolution_m INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tiles (
    tile_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    source_scene_ids_json TEXT NOT NULL,
    composite_metadata_cache_key TEXT NOT NULL REFERENCES cached_assets(cache_key),
    tile_size_m INTEGER NOT NULL,
    x_index INTEGER NOT NULL,
    y_index INTEGER NOT NULL,
    is_valid INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tile_features (
    tile_feature_input_cache_key TEXT PRIMARY KEY REFERENCES cached_assets(cache_key),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tile_id TEXT NOT NULL REFERENCES tiles(tile_id),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    target_bands_json TEXT NOT NULL,
    baseline_median_bands_json TEXT NOT NULL,
    baseline_std_bands_json TEXT NOT NULL,
    valid_season_optical_values_json TEXT NOT NULL,
    masked_or_invalid_pixel_count INTEGER NOT NULL,
    total_pixel_count INTEGER NOT NULL,
    water_edge_overlap_ratio REAL NOT NULL,
    cloud_seam_overlap_ratio REAL NOT NULL,
    compactness_ratio_value REAL NOT NULL,
    elongation REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tile_scores (
    tile_id TEXT PRIMARY KEY REFERENCES tiles(tile_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    tile_feature_input_cache_key TEXT NOT NULL REFERENCES tile_features(tile_feature_input_cache_key),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    optical_anomaly REAL NOT NULL,
    persistence REAL NOT NULL,
    cloud_penalty REAL NOT NULL,
    noise_penalty REAL NOT NULL,
    tile_score REAL NOT NULL,
    selected_for_polygonization INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidate_polygons (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    polygonization_manifest_cache_key TEXT NOT NULL REFERENCES cached_assets(cache_key),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    parent_tile_id TEXT NOT NULL REFERENCES tiles(tile_id),
    source_scene_ids_json TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'pending_review',
    bounds_json TEXT NOT NULL,
    centroid_json TEXT NOT NULL,
    clipped_geometry_json TEXT,
    area_m2 REAL NOT NULL,
    perimeter_m REAL NOT NULL,
    pixel_count INTEGER NOT NULL,
    boundary_touching INTEGER NOT NULL DEFAULT 0,
    possible_duplicate INTEGER NOT NULL DEFAULT 0,
    duplicate_resolution_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidate_features (
    candidate_id TEXT PRIMARY KEY REFERENCES candidate_polygons(candidate_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    polygonization_manifest_cache_key TEXT NOT NULL REFERENCES cached_assets(cache_key),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    compactness_ratio REAL NOT NULL,
    convex_hull_area_m2 REAL NOT NULL,
    elongation REAL NOT NULL,
    local_contrast_inputs_json TEXT NOT NULL,
    water_edge_overlap_ratio REAL NOT NULL,
    cloud_seam_overlap_ratio REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidate_scores (
    candidate_id TEXT PRIMARY KEY REFERENCES candidate_polygons(candidate_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    polygonization_manifest_cache_key TEXT NOT NULL REFERENCES cached_assets(cache_key),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    parent_tile_id TEXT NOT NULL REFERENCES tiles(tile_id),
    parent_tile_score REAL NOT NULL,
    texture_support REAL NOT NULL,
    compactness_support REAL NOT NULL,
    polygon_object_score REAL NOT NULL,
    candidate_score REAL NOT NULL,
    score_breakdown_json TEXT NOT NULL,
    contribution_sum REAL NOT NULL,
    integrity_delta REAL NOT NULL,
    integrity_within_tolerance INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_actions (
    review_action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES candidate_polygons(candidate_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    reviewer_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    note TEXT,
    acted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paid_quotes (
    provider_quote_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidate_polygons(candidate_id),
    run_id TEXT REFERENCES runs(run_id),
    project_id TEXT,
    provider TEXT NOT NULL,
    amount REAL NOT NULL,
    credits REAL NOT NULL,
    currency TEXT NOT NULL,
    eula_reference TEXT NOT NULL,
    paid_status TEXT NOT NULL,
    archive_mode TEXT NOT NULL DEFAULT 'archive_first',
    tasking_requested INTEGER NOT NULL DEFAULT 0,
    autonomous_purchase_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paid_quotes_candidate_id
    ON paid_quotes(candidate_id);

CREATE INDEX IF NOT EXISTS idx_discovered_scenes_manifest
    ON discovered_scenes(source_scene_manifest_hash);

CREATE TABLE IF NOT EXISTS paid_orders (
    provider_order_id TEXT PRIMARY KEY,
    provider_quote_id TEXT NOT NULL REFERENCES paid_quotes(provider_quote_id),
    candidate_id TEXT NOT NULL REFERENCES candidate_polygons(candidate_id),
    run_id TEXT REFERENCES runs(run_id),
    project_id TEXT,
    provider TEXT NOT NULL,
    amount REAL NOT NULL,
    credits REAL NOT NULL,
    currency TEXT NOT NULL,
    eula_reference TEXT NOT NULL,
    paid_status TEXT NOT NULL,
    archive_mode TEXT NOT NULL DEFAULT 'archive_first',
    tasking_requested INTEGER NOT NULL DEFAULT 0,
    autonomous_purchase_enabled INTEGER NOT NULL DEFAULT 0,
    human_triggered_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paid_orders_candidate_id
    ON paid_orders(candidate_id);
