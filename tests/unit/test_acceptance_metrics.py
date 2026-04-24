from lawful_anomaly_screening.orchestration.acceptance import (
    build_acceptance_summary,
    build_kpi_summary,
    candidate_count_per_100_km2,
    paid_escalations_per_100_km2,
    reproducibility_check,
    top10_stability_rate,
)


def _candidate(candidate_id: str, score: float, state: str = "pending_review") -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_score": score,
        "parent_tile_score": score - 1.0,
        "review_state": state,
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


def test_reproducibility_requires_same_manifest_rank_order_and_score_tolerance():
    baseline = [_candidate(f"candidate-{index:03d}", 100.0 - index) for index in range(1, 12)]
    comparison = [
        _candidate(candidate["candidate_id"], candidate["candidate_score"] + 0.4)
        for candidate in baseline
    ]

    passing = reproducibility_check(
        baseline_manifest_hash="manifest-hash-001",
        comparison_manifest_hash="manifest-hash-001",
        baseline_candidates=baseline,
        comparison_candidates=comparison,
    )
    failing = reproducibility_check(
        baseline_manifest_hash="manifest-hash-001",
        comparison_manifest_hash="different-manifest",
        baseline_candidates=baseline,
        comparison_candidates=comparison,
    )

    assert passing["status"] == "pass"
    assert passing["same_top_10_rank_order"] is True
    assert passing["scores_within_tolerance"] is True
    assert failing["status"] == "fail"
    assert failing["same_manifest"] is False


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
