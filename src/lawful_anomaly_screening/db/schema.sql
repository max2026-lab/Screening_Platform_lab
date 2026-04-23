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

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    processing_baseline_id TEXT NOT NULL REFERENCES processing_baselines(processing_baseline_id),
    source_scene_manifest_hash TEXT NOT NULL REFERENCES source_scene_manifests(source_scene_manifest_hash),
    source_endpoint_id TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    rerun_mode TEXT NOT NULL,
    cache_status TEXT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
