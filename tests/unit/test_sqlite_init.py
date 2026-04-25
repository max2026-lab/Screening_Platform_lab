import sqlite3

from lawful_anomaly_screening.db.repositories.run_repository import RunRepository
from lawful_anomaly_screening.db.sqlite import (
    LEGAL_GATE_MIGRATION_TIMESTAMP,
    bootstrap_minimal_run,
    init_db,
)


def test_sqlite_init(tmp_path):
    db = tmp_path / "test.sqlite3"
    init_db(db)
    assert db.exists()
    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "processing_baselines",
        "feature_versions",
        "runs",
        "source_scene_manifests",
        "discovered_scenes",
        "cached_assets",
        "geofence_hits",
        "export_records",
        "tiles",
        "tile_features",
        "tile_scores",
        "candidate_polygons",
        "candidate_features",
        "candidate_scores",
        "review_actions",
        "paid_quotes",
        "paid_orders",
    } <= tables


def test_bootstrap_minimal_run_path(tmp_path):
    db = tmp_path / "bootstrap.sqlite3"
    init_db(db)

    result = bootstrap_minimal_run(
        db,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-001",
        manifest_path="data/manifests/manifest-hash-001.json",
    )

    assert result["run_id"] == "run-001"

    with sqlite3.connect(db) as conn:
        baseline_count = conn.execute(
            "SELECT COUNT(*) FROM processing_baselines WHERE processing_baseline_id = ?",
            ("baseline_v1_5_default",),
        ).fetchone()[0]
        manifest_count = conn.execute(
            "SELECT COUNT(*) FROM source_scene_manifests WHERE source_scene_manifest_hash = ?",
            ("manifest-hash-001",),
        ).fetchone()[0]
        manifest_row = conn.execute(
            """
            SELECT source_endpoint_id, source_name, manifest_path
            FROM source_scene_manifests
            WHERE source_scene_manifest_hash = ?
            """,
            ("manifest-hash-001",),
        ).fetchone()
        run_row = conn.execute(
            """
            SELECT status, source_endpoint_id, execution_mode, rerun_mode, cache_status, aoi_geometry_json
            FROM runs
            WHERE run_id = ?
            """,
            ("run-001",),
        ).fetchone()

    assert baseline_count == 1
    assert manifest_count == 1
    assert manifest_row == ("earth_search", "earth_search", "data/manifests/manifest-hash-001.json")
    assert run_row == ("new", "earth_search", "synchronous", "review_only", "miss", None)
    assert result["legal_gate"]["evaluated_at"]


def test_init_db_upgrades_existing_runs_table_with_legal_columns(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE processing_baselines (
                processing_baseline_id TEXT PRIMARY KEY,
                score_formula_version TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                persistence_backend TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE source_scene_manifests (
                source_scene_manifest_hash TEXT PRIMARY KEY,
                source_endpoint_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE runs (
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO processing_baselines (
                processing_baseline_id,
                score_formula_version,
                execution_mode,
                persistence_backend
            ) VALUES ('baseline-001', 'v1', 'synchronous', 'sqlite');
            INSERT INTO source_scene_manifests (
                source_scene_manifest_hash,
                source_endpoint_id,
                source_name,
                manifest_path
            ) VALUES ('manifest-001', 'earth_search', 'earth_search', 'data/manifests/manifest-001.json');
            INSERT INTO runs (
                run_id,
                status,
                processing_baseline_id,
                source_scene_manifest_hash,
                source_endpoint_id,
                execution_mode,
                rerun_mode,
                cache_status,
                aoi_hash,
                start_date,
                end_date
            ) VALUES (
                'run-legacy-001',
                'new',
                'baseline-001',
                'manifest-001',
                'earth_search',
                'synchronous',
                'review_only',
                'miss',
                'hash-001',
                '2024-01-01',
                '2024-03-31'
            );
            """
        )
        conn.commit()

    init_db(db)

    run = RunRepository(db).fetch_run("run-legacy-001")

    assert run is not None
    assert run["legal_gate"]["attestation_status"] == "missing"
    assert run["legal_gate"]["geofence_status"] == "missing"
    assert run["legal_gate"]["decision"] == "fail"
    assert run["legal_gate"]["reason"] == ""
    assert run["legal_gate"]["evaluated_at"] == LEGAL_GATE_MIGRATION_TIMESTAMP


def test_runs_schema_supports_persisted_legal_gate_evidence(tmp_path):
    db = tmp_path / "runs.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(runs)")
        }

    assert {
        "legal_attestation_status",
        "legal_geofence_status",
        "legal_gate_decision",
        "legal_gate_reason",
        "legal_gate_evaluated_at",
    } <= run_columns


def test_discovered_scene_schema_supports_manifest_linkage(tmp_path):
    db = tmp_path / "discovered-scenes.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(discovered_scenes)")
        }

    assert {
        "source_scene_manifest_hash",
        "scene_id",
        "source_endpoint_id",
        "acquired_at",
        "cloud_cover",
    } <= columns


def test_cached_assets_schema_supports_preprocessing_records(tmp_path):
    db = tmp_path / "cached-assets.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(cached_assets)")
        }

    assert {
        "cache_key",
        "asset_kind",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "asset_path",
        "content_hash",
    } <= columns


def test_export_record_schema_supports_precision_logging(tmp_path):
    db = tmp_path / "exports.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        export_record_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(export_records)")
        }

    assert {
        "export_record_id",
        "run_id",
        "audience",
        "precision_tier",
        "artifact_name",
        "bundle_name",
        "artifact_path",
        "exact_coordinates_included",
        "coordinate_resolution_m",
    } <= export_record_columns


def test_tiles_schema_supports_retained_scoring_records(tmp_path):
    db = tmp_path / "tiles.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        tile_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(tiles)")
        }
        tile_feature_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(tile_features)")
        }
        tile_score_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(tile_scores)")
        }

    assert {
        "tile_id",
        "run_id",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "composite_metadata_cache_key",
        "tile_size_m",
        "x_index",
        "y_index",
        "is_valid",
    } <= tile_columns
    assert {
        "tile_feature_input_cache_key",
        "run_id",
        "tile_id",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "target_bands_json",
        "baseline_median_bands_json",
        "baseline_std_bands_json",
        "valid_season_optical_values_json",
        "masked_or_invalid_pixel_count",
        "total_pixel_count",
        "water_edge_overlap_ratio",
        "cloud_seam_overlap_ratio",
        "compactness_ratio_value",
        "elongation",
    } <= tile_feature_columns
    assert {
        "tile_id",
        "run_id",
        "tile_feature_input_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "optical_anomaly",
        "persistence",
        "cloud_penalty",
        "noise_penalty",
        "tile_score",
        "selected_for_polygonization",
    } <= tile_score_columns


def test_candidate_schema_supports_polygon_and_feature_records(tmp_path):
    db = tmp_path / "candidates.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        candidate_polygon_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(candidate_polygons)")
        }
        candidate_feature_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(candidate_features)")
        }

    assert {
        "candidate_id",
        "run_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "parent_tile_id",
        "current_state",
        "bounds_json",
        "centroid_json",
        "clipped_geometry_json",
        "area_m2",
        "perimeter_m",
        "pixel_count",
        "boundary_touching",
        "possible_duplicate",
        "duplicate_resolution_action",
    } <= candidate_polygon_columns
    assert {
        "candidate_id",
        "run_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "compactness_ratio",
        "convex_hull_area_m2",
        "elongation",
        "local_contrast_inputs_json",
        "water_edge_overlap_ratio",
        "cloud_seam_overlap_ratio",
    } <= candidate_feature_columns


def test_candidate_score_schema_supports_retained_score_records(tmp_path):
    db = tmp_path / "candidate-scores.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        candidate_score_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(candidate_scores)")
        }

    assert {
        "candidate_id",
        "run_id",
        "polygonization_manifest_cache_key",
        "source_scene_manifest_hash",
        "source_endpoint_id",
        "parent_tile_id",
        "parent_tile_score",
        "texture_support",
        "compactness_support",
        "polygon_object_score",
        "candidate_score",
        "score_breakdown_json",
        "contribution_sum",
        "integrity_delta",
        "integrity_within_tolerance",
    } <= candidate_score_columns


def test_review_action_schema_supports_audit_records(tmp_path):
    db = tmp_path / "review-actions.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        review_action_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(review_actions)")
        }

    assert {
        "review_action_id",
        "candidate_id",
        "run_id",
        "reviewer_id",
        "decision",
        "prior_state",
        "new_state",
        "note",
        "acted_at",
    } <= review_action_columns


def test_paid_quote_schema_supports_archive_quote_metadata(tmp_path):
    db = tmp_path / "paid-quotes.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        quote_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(paid_quotes)")
        }

    assert {
        "provider_quote_id",
        "candidate_id",
        "run_id",
        "project_id",
        "provider",
        "amount",
        "credits",
        "currency",
        "eula_reference",
        "paid_status",
        "archive_mode",
        "tasking_requested",
        "autonomous_purchase_enabled",
        "created_at",
        "updated_at",
    } <= quote_columns


def test_paid_order_schema_supports_archive_order_metadata(tmp_path):
    db = tmp_path / "paid-orders.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        order_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(paid_orders)")
        }

    assert {
        "provider_order_id",
        "provider_quote_id",
        "candidate_id",
        "run_id",
        "project_id",
        "provider",
        "amount",
        "credits",
        "currency",
        "eula_reference",
        "paid_status",
        "archive_mode",
        "tasking_requested",
        "autonomous_purchase_enabled",
        "human_triggered_by",
        "created_at",
        "updated_at",
    } <= order_columns
