from lawful_anomaly_screening.orchestration.rerun_modes import (
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS,
    CACHE_STATUS_PARTIAL,
    RERUN_MODE_EXACT_CACHED,
    RERUN_MODE_EXACT_RECOMPUTE,
    RERUN_MODE_NEW_WINDOW,
    RERUN_MODE_REVIEW_ONLY,
    VALID_RERUN_MODES,
    build_rerun_plan,
)
from lawful_anomaly_screening.sources.candidate_diff import (
    build_candidate_diff_report,
    classify_candidate_pair,
)


def test_rerun_mode_values_and_cache_status_scaffold():
    assert VALID_RERUN_MODES == (
        RERUN_MODE_REVIEW_ONLY,
        RERUN_MODE_EXACT_CACHED,
        RERUN_MODE_EXACT_RECOMPUTE,
        RERUN_MODE_NEW_WINDOW,
    )

    miss_plan = build_rerun_plan(
        run_id="run-001",
        rerun_mode=RERUN_MODE_REVIEW_ONLY,
        required_asset_kinds=["polygonization_manifest"],
        cached_asset_rows=[],
    )
    partial_plan = build_rerun_plan(
        run_id="run-001",
        rerun_mode=RERUN_MODE_EXACT_CACHED,
        required_asset_kinds=["preprocessing_manifest", "polygonization_manifest"],
        cached_asset_rows=[{"asset_kind": "preprocessing_manifest"}],
    )
    hit_plan = build_rerun_plan(
        run_id="run-001",
        rerun_mode=RERUN_MODE_EXACT_CACHED,
        required_asset_kinds=["preprocessing_manifest"],
        cached_asset_rows=[{"asset_kind": "preprocessing_manifest"}],
    )

    assert miss_plan["cache_status"] == CACHE_STATUS_MISS
    assert partial_plan["cache_status"] == CACHE_STATUS_PARTIAL
    assert partial_plan["reuse_cached_assets"] is False
    assert hit_plan["cache_status"] == CACHE_STATUS_HIT
    assert hit_plan["reuse_cached_assets"] is True


def test_candidate_diff_classification_rules():
    prior_candidate = {
        "candidate_id": "prior-1",
        "parent_tile_id": "tile-001",
        "bounds": [0.0, 0.0, 100.0, 100.0],
        "centroid": [50.0, 50.0],
        "area_m2": 10000.0,
    }
    stable_candidate = {
        "candidate_id": "current-stable",
        "parent_tile_id": "tile-001",
        "bounds": [10.0, 10.0, 110.0, 110.0],
        "centroid": [60.0, 60.0],
        "area_m2": 10000.0,
    }
    moved_candidate = {
        "candidate_id": "current-moved",
        "parent_tile_id": "tile-001",
        "bounds": [120.0, 0.0, 220.0, 100.0],
        "centroid": [130.0, 50.0],
        "area_m2": 10000.0,
    }
    new_candidate = {
        "candidate_id": "current-new",
        "parent_tile_id": "tile-002",
        "bounds": [500.0, 500.0, 600.0, 600.0],
        "centroid": [550.0, 550.0],
        "area_m2": 10000.0,
    }

    stable = classify_candidate_pair(stable_candidate, prior_candidate)
    moved = classify_candidate_pair(moved_candidate, prior_candidate)
    new = classify_candidate_pair(new_candidate, prior_candidate)

    assert stable is not None
    assert stable["classification"] == "stable"
    assert stable["iou"] >= 0.50

    assert moved is not None
    assert moved["classification"] == "moved"
    assert moved["iou"] < 0.50
    assert moved["centroid_shift_m"] <= 160.0
    assert 0.5 <= moved["area_ratio"] <= 2.0

    assert new is None


def test_candidate_diff_report_is_deterministic():
    prior_candidates = [
        {
            "candidate_id": "prior-stable",
            "parent_tile_id": "tile-001",
            "bounds": [0.0, 0.0, 100.0, 100.0],
            "centroid": [50.0, 50.0],
            "area_m2": 10000.0,
        },
        {
            "candidate_id": "prior-lost",
            "parent_tile_id": "tile-002",
            "bounds": [300.0, 0.0, 360.0, 60.0],
            "centroid": [330.0, 30.0],
            "area_m2": 3600.0,
        },
    ]
    current_candidates = [
        {
            "candidate_id": "current-new",
            "parent_tile_id": "tile-003",
            "bounds": [600.0, 600.0, 660.0, 660.0],
            "centroid": [630.0, 630.0],
            "area_m2": 3600.0,
        },
        {
            "candidate_id": "current-moved",
            "parent_tile_id": "tile-001",
            "bounds": [120.0, 0.0, 220.0, 100.0],
            "centroid": [130.0, 50.0],
            "area_m2": 10000.0,
        },
        {
            "candidate_id": "current-stable",
            "parent_tile_id": "tile-001",
            "bounds": [10.0, 10.0, 110.0, 110.0],
            "centroid": [60.0, 60.0],
            "area_m2": 10000.0,
        },
    ]

    report_one = build_candidate_diff_report(
        prior_candidates=prior_candidates,
        current_candidates=current_candidates,
        prior_run_id="run-prior",
        current_run_id="run-current",
    )
    report_two = build_candidate_diff_report(
        prior_candidates=list(reversed(prior_candidates)),
        current_candidates=list(reversed(current_candidates)),
        prior_run_id="run-prior",
        current_run_id="run-current",
    )

    assert report_one == report_two
    assert report_one["summary"] == {
        "stable": 1,
        "moved": 1,
        "new": 1,
        "lost": 1,
    }
    assert [entry["classification"] for entry in report_one["diff_entries"]] == [
        "lost",
        "moved",
        "new",
        "stable",
    ]
