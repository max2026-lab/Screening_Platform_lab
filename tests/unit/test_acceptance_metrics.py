from lawful_anomaly_screening.orchestration.acceptance import (
    REPRODUCIBILITY_TOP10_MINIMUM_RATE,
    build_acceptance_summary,
    build_kpi_summary,
    candidate_count_per_100_km2,
    paid_escalations_per_100_km2,
    reproducibility_check,
    top10_stability_rate,
)


def _candidate(
    candidate_id: str,
    score: float,
    state: str = "pending_review",
    *,
    stable_candidate_key: str | None = None,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_score": score,
        "parent_tile_score": score - 1.0,
        "review_state": state,
        "stable_candidate_key": stable_candidate_key or candidate_id,
    }


def _run(
    run_id: str,
    *,
    processing_baseline_id: str = "baseline_v1_5_default",
    source_scene_manifest_hash: str = "manifest-hash-001",
    aoi_hash: str = "aoi-hash-001",
    start_date: str = "2024-01-01",
    end_date: str = "2024-03-31",
    composite_quality: dict | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "processing_baseline_id": processing_baseline_id,
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "aoi_hash": aoi_hash,
        "start_date": start_date,
        "end_date": end_date,
        "composite_quality": composite_quality,
    }


def test_candidate_count_and_paid_escalation_rates_are_per_100_km2():
    assert candidate_count_per_100_km2(candidate_count=20, aoi_area_km2=100.0) == 20.0
    assert candidate_count_per_100_km2(candidate_count=20, aoi_area_km2=50.0) == 40.0
    assert paid_escalations_per_100_km2(escalation_count=5, aoi_area_km2=100.0) == 5.0


def test_kpi_summary_and_acceptance_thresholds():
    candidates = [
        _candidate(f"candidate-{index:03d}", 100.0 - index, "approved_for_archive_quote")
        if index <= 5
        else _candidate(f"candidate-{index:03d}", 100.0 - index)
        for index in range(1, 21)
    ]

    kpis = build_kpi_summary(
        run_id="run-001",
        source_scene_manifest_hash="manifest-hash-001",
        candidate_rows=candidates,
        aoi_area_km2=100.0,
        time_to_first_review_package_hours=1.5,
        paid_escalation_count=5,
    )
    summary = build_acceptance_summary(kpi_summary=kpis, top10_stability_rate_value=0.8)

    assert kpis["candidate_count_per_100_km2"] == 20.0
    assert kpis["top_20_approval_rate"] == 0.25
    assert kpis["paid_escalations_per_100_km2"] == 5.0
    assert summary["status"] == "pass"
    assert {check["status"] for check in summary["checks"]} == {"pass"}


def test_acceptance_summary_warns_for_minimum_viable_approval_rate():
    candidates = [
        _candidate(f"candidate-{index:03d}", 100.0 - index, "approved_for_archive_quote")
        if index <= 3
        else _candidate(f"candidate-{index:03d}", 100.0 - index)
        for index in range(1, 21)
    ]

    kpis = build_kpi_summary(
        run_id="run-001",
        source_scene_manifest_hash="manifest-hash-001",
        candidate_rows=candidates,
        aoi_area_km2=100.0,
        time_to_first_review_package_hours=1.5,
        paid_escalation_count=5,
    )
    summary = build_acceptance_summary(kpi_summary=kpis)

    approval_check = next(
        check for check in summary["checks"] if check["name"] == "top_20_approval_rate"
    )
    assert approval_check["observed"] == 0.15
    assert approval_check["status"] == "warn"
    assert summary["status"] == "warn"


def test_reproducibility_identical_deterministic_reruns_return_pass():
    baseline_run = _run("run-001")
    comparison_run = _run("run-002")
    baseline = [
        _candidate(f"baseline-{index:03d}", 100.0 - index, stable_candidate_key=f"stable-{index:03d}")
        for index in range(1, 12)
    ]
    comparison = [
        _candidate(f"comparison-{index:03d}", 100.0 - index, stable_candidate_key=f"stable-{index:03d}")
        for index in range(1, 12)
    ]

    result = reproducibility_check(
        baseline_run=baseline_run,
        comparison_run=comparison_run,
        baseline_candidates=baseline,
        comparison_candidates=comparison,
    )

    assert result["status"] == "pass"
    assert result["same_processing_baseline"] is True
    assert result["same_aoi_hash"] is True
    assert result["same_date_window"] is True
    assert result["same_source_scene_manifest_hash"] is True
    assert result["common_candidate_count"] == 11
    assert result["added_candidate_ids"] == []
    assert result["removed_candidate_ids"] == []
    assert result["top10_stability_rate"] == 1.0
    assert result["reasons"] == ["Deterministic checks stable"]
    assert result["baseline_run"]["processing_baseline_id"] == "baseline_v1_5_default"


def test_reproducibility_fails_for_aoi_mismatch_with_clear_reason():
    result = reproducibility_check(
        baseline_run=_run("run-001", aoi_hash="aoi-hash-001"),
        comparison_run=_run("run-002", aoi_hash="aoi-hash-002"),
        baseline_candidates=[_candidate("baseline-001", 99.0, stable_candidate_key="stable-001")],
        comparison_candidates=[_candidate("comparison-001", 99.0, stable_candidate_key="stable-001")],
    )

    assert result["status"] == "fail"
    assert result["same_aoi_hash"] is False
    assert "AOI hash differs between runs" in result["reasons"]


def test_reproducibility_fails_for_date_window_mismatch_with_clear_reason():
    result = reproducibility_check(
        baseline_run=_run("run-001", start_date="2024-01-01", end_date="2024-03-31"),
        comparison_run=_run("run-002", start_date="2024-02-01", end_date="2024-03-31"),
        baseline_candidates=[_candidate("baseline-001", 99.0, stable_candidate_key="stable-001")],
        comparison_candidates=[_candidate("comparison-001", 99.0, stable_candidate_key="stable-001")],
    )

    assert result["status"] == "fail"
    assert result["same_date_window"] is False
    assert any(reason.startswith("Date window differs between runs:") for reason in result["reasons"])


def test_reproducibility_warns_for_manifest_mismatch_with_clear_reason():
    result = reproducibility_check(
        baseline_run=_run("run-001", source_scene_manifest_hash="manifest-hash-001"),
        comparison_run=_run("run-002", source_scene_manifest_hash="manifest-hash-002"),
        baseline_candidates=[_candidate("baseline-001", 99.0, stable_candidate_key="stable-001")],
        comparison_candidates=[_candidate("comparison-001", 99.0, stable_candidate_key="stable-001")],
    )

    assert result["status"] == "warn"
    assert result["same_source_scene_manifest_hash"] is False
    assert "Source scene manifest differs between runs" in result["reasons"]


def test_candidate_added_removed_and_common_counts_are_correct():
    result = reproducibility_check(
        baseline_run=_run("run-001"),
        comparison_run=_run("run-002"),
        baseline_candidates=[
            _candidate("baseline-001", 99.0, stable_candidate_key="stable-001"),
            _candidate("baseline-002", 98.0, stable_candidate_key="stable-002"),
        ],
        comparison_candidates=[
            _candidate("comparison-001", 99.0, stable_candidate_key="stable-001"),
            _candidate("comparison-003", 97.0, stable_candidate_key="stable-003"),
        ],
    )

    assert result["baseline_candidate_count"] == 2
    assert result["comparison_candidate_count"] == 2
    assert result["common_candidate_count"] == 1
    assert result["added_candidate_ids"] == ["comparison-003"]
    assert result["removed_candidate_ids"] == ["baseline-002"]


def test_rank_deltas_and_score_deltas_are_deterministic():
    result = reproducibility_check(
        baseline_run=_run("run-001"),
        comparison_run=_run("run-002"),
        baseline_candidates=[
            _candidate("baseline-001", 100.0, stable_candidate_key="stable-001"),
            _candidate("baseline-002", 99.0, stable_candidate_key="stable-002"),
        ],
        comparison_candidates=[
            _candidate("comparison-002", 100.5, stable_candidate_key="stable-002"),
            _candidate("comparison-001", 99.5, stable_candidate_key="stable-001"),
        ],
    )

    assert result["rank_deltas"] == [
        {
            "stable_candidate_key": "stable-001",
            "baseline_candidate_id": "baseline-001",
            "comparison_candidate_id": "comparison-001",
            "baseline_rank": 1,
            "comparison_rank": 2,
            "rank_delta": 1,
        },
        {
            "stable_candidate_key": "stable-002",
            "baseline_candidate_id": "baseline-002",
            "comparison_candidate_id": "comparison-002",
            "baseline_rank": 2,
            "comparison_rank": 1,
            "rank_delta": -1,
        },
    ]
    assert result["score_deltas"] == [
        {
            "stable_candidate_key": "stable-001",
            "baseline_candidate_id": "baseline-001",
            "comparison_candidate_id": "comparison-001",
            "baseline_score": 100.0,
            "comparison_score": 99.5,
            "score_delta": -0.5,
        },
        {
            "stable_candidate_key": "stable-002",
            "baseline_candidate_id": "baseline-002",
            "comparison_candidate_id": "comparison-002",
            "baseline_score": 99.0,
            "comparison_score": 100.5,
            "score_delta": 1.5,
        },
    ]


def test_top10_stability_threshold_warning_works():
    baseline = [
        _candidate(f"baseline-{index:03d}", 100.0 - index, stable_candidate_key=f"stable-{index:03d}")
        for index in range(1, 12)
    ]
    comparison = [
        _candidate("comparison-001", 100.0, stable_candidate_key="stable-001"),
        _candidate("comparison-002", 99.0, stable_candidate_key="stable-002"),
        _candidate("comparison-003", 98.0, stable_candidate_key="stable-003"),
        _candidate("comparison-004", 97.0, stable_candidate_key="stable-004"),
        _candidate("comparison-005", 96.0, stable_candidate_key="stable-005"),
        _candidate("comparison-006", 95.0, stable_candidate_key="stable-006"),
        _candidate("comparison-007", 94.0, stable_candidate_key="stable-007"),
        _candidate("comparison-011", 93.0, stable_candidate_key="stable-011"),
        _candidate("comparison-012", 92.0, stable_candidate_key="stable-012"),
        _candidate("comparison-013", 91.0, stable_candidate_key="stable-013"),
    ]

    result = reproducibility_check(
        baseline_run=_run("run-001"),
        comparison_run=_run("run-002"),
        baseline_candidates=baseline,
        comparison_candidates=comparison,
    )

    assert result["top10_stability_rate"] == 0.7
    assert result["top10_stability_threshold"] == REPRODUCIBILITY_TOP10_MINIMUM_RATE
    assert result["status"] == "warn"
    assert (
        f"Top-10 stability rate 0.70 is below threshold {REPRODUCIBILITY_TOP10_MINIMUM_RATE:.2f}"
        in result["reasons"]
    )


def test_top10_stability_after_small_retune():
    baseline = [_candidate(f"candidate-{index:03d}", 100.0 - index) for index in range(1, 13)]
    retuned = [
        _candidate("candidate-001", 100.0),
        _candidate("candidate-002", 99.0),
        _candidate("candidate-003", 98.0),
        _candidate("candidate-004", 97.0),
        _candidate("candidate-005", 96.0),
        _candidate("candidate-006", 95.0),
        _candidate("candidate-007", 94.0),
        _candidate("candidate-011", 93.0),
        _candidate("candidate-012", 92.0),
        _candidate("candidate-013", 91.0),
    ]

    assert top10_stability_rate(baseline, retuned) == 0.7
