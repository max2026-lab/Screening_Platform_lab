from __future__ import annotations

from dataclasses import dataclass
import json


CANDIDATE_COUNT_MIN_PER_100_KM2 = 15.0
CANDIDATE_COUNT_MAX_PER_100_KM2 = 50.0
TOP20_APPROVAL_MINIMUM_VIABLE_RATE = 0.15
TOP20_APPROVAL_ASPIRATIONAL_RATE = 0.25
REPRODUCIBILITY_SCORE_TOLERANCE = 0.5
TOP10_STABILITY_MINIMUM_RATE = 0.70
REPRODUCIBILITY_TOP10_MINIMUM_RATE = 0.80
WARM_CACHE_REVIEW_PACKAGE_MAX_HOURS = 2.0
PAID_ESCALATION_MAX_PER_100_KM2 = 5.0

APPROVED_REVIEW_STATE = "approved_for_archive_quote"


@dataclass(frozen=True)
class AcceptanceCheck:
    name: str
    status: str
    observed: float | int | bool | str
    target: str


def status_for_range(value: float, minimum: float, maximum: float) -> str:
    if minimum <= value <= maximum:
        return "pass"
    return "fail"


def status_for_minimum(value: float, minimum: float, warn_minimum: float | None = None) -> str:
    if value >= minimum:
        return "pass"
    if warn_minimum is not None and value >= warn_minimum:
        return "warn"
    return "fail"


def status_for_maximum(value: float, maximum: float) -> str:
    if value <= maximum:
        return "pass"
    return "fail"


def candidate_count_per_100_km2(candidate_count: int, aoi_area_km2: float) -> float:
    if aoi_area_km2 <= 0:
        return 0.0
    return round(candidate_count / (aoi_area_km2 / 100.0), 6)


def approval_rate(candidate_rows: list[dict], top_n: int = 20) -> float:
    if top_n <= 0:
        return 0.0
    top_candidates = rank_candidates(candidate_rows)[:top_n]
    if not top_candidates:
        return 0.0
    approved_count = sum(
        1 for candidate in top_candidates if candidate.get("review_state") == APPROVED_REVIEW_STATE
    )
    return round(approved_count / len(top_candidates), 6)


def paid_escalations_per_100_km2(escalation_count: int, aoi_area_km2: float) -> float:
    if aoi_area_km2 <= 0:
        return 0.0
    return round(escalation_count / (aoi_area_km2 / 100.0), 6)


def rank_candidates(candidate_rows: list[dict]) -> list[dict]:
    return sorted(
        candidate_rows,
        key=lambda row: (
            -float(row.get("candidate_score") or 0.0),
            -float(row.get("parent_tile_score") or 0.0),
            str(row["candidate_id"]),
        ),
    )


def candidate_identity(row: dict) -> str:
    return str(row.get("stable_candidate_key") or row["candidate_id"])


def top_candidate_ids(candidate_rows: list[dict], top_n: int = 10) -> list[str]:
    return [row["candidate_id"] for row in rank_candidates(candidate_rows)[:top_n]]


def top_candidate_match_keys(candidate_rows: list[dict], top_n: int = 10) -> list[str]:
    return [candidate_identity(row) for row in rank_candidates(candidate_rows)[:top_n]]


def scores_within_tolerance(
    baseline_candidates: list[dict],
    comparison_candidates: list[dict],
    tolerance: float = REPRODUCIBILITY_SCORE_TOLERANCE,
    top_n: int = 10,
) -> bool:
    baseline_by_id = {candidate_identity(row): row for row in baseline_candidates}
    comparison_by_id = {candidate_identity(row): row for row in comparison_candidates}
    for candidate_key in top_candidate_match_keys(baseline_candidates, top_n):
        if candidate_key not in comparison_by_id:
            return False
        baseline_score = float(baseline_by_id[candidate_key].get("candidate_score") or 0.0)
        comparison_score = float(comparison_by_id[candidate_key].get("candidate_score") or 0.0)
        if abs(baseline_score - comparison_score) > tolerance:
            return False
    return True


def _normalize_reproducibility_run(run: dict) -> dict:
    return {
        "processing_baseline_id": run.get("processing_baseline_id"),
        "source_scene_manifest_hash": run.get("source_scene_manifest_hash"),
        "aoi_hash": run.get("aoi_hash"),
        "start_date": run.get("start_date"),
        "end_date": run.get("end_date"),
        "composite_quality": run.get("composite_quality"),
    }


def _ranked_candidates_by_key(candidate_rows: list[dict]) -> tuple[list[dict], dict[str, dict], dict[str, int]]:
    ranked_candidates = rank_candidates(candidate_rows)
    candidates_by_key = {candidate_identity(row): row for row in ranked_candidates}
    ranks_by_key = {
        candidate_identity(row): index
        for index, row in enumerate(ranked_candidates, start=1)
    }
    return ranked_candidates, candidates_by_key, ranks_by_key


def reproducibility_check(
    *,
    baseline_run: dict,
    comparison_run: dict,
    baseline_candidates: list[dict],
    comparison_candidates: list[dict],
    top10_threshold: float = REPRODUCIBILITY_TOP10_MINIMUM_RATE,
) -> dict:
    same_processing_baseline = (
        baseline_run.get("processing_baseline_id") == comparison_run.get("processing_baseline_id")
    )
    same_aoi_hash = baseline_run.get("aoi_hash") == comparison_run.get("aoi_hash")
    same_date_window = (
        baseline_run.get("start_date") == comparison_run.get("start_date")
        and baseline_run.get("end_date") == comparison_run.get("end_date")
    )
    same_source_scene_manifest_hash = (
        baseline_run.get("source_scene_manifest_hash")
        == comparison_run.get("source_scene_manifest_hash")
    )

    baseline_ranked, baseline_by_key, baseline_ranks = _ranked_candidates_by_key(baseline_candidates)
    comparison_ranked, comparison_by_key, comparison_ranks = _ranked_candidates_by_key(comparison_candidates)
    common_keys = [
        candidate_identity(row)
        for row in baseline_ranked
        if candidate_identity(row) in comparison_by_key
    ]
    added_keys = sorted(set(comparison_by_key) - set(baseline_by_key))
    removed_keys = sorted(set(baseline_by_key) - set(comparison_by_key))
    stability_rate = top10_stability_rate(baseline_candidates, comparison_candidates)

    rank_deltas = [
        {
            "stable_candidate_key": stable_candidate_key,
            "baseline_candidate_id": baseline_by_key[stable_candidate_key]["candidate_id"],
            "comparison_candidate_id": comparison_by_key[stable_candidate_key]["candidate_id"],
            "baseline_rank": baseline_ranks[stable_candidate_key],
            "comparison_rank": comparison_ranks[stable_candidate_key],
            "rank_delta": comparison_ranks[stable_candidate_key] - baseline_ranks[stable_candidate_key],
        }
        for stable_candidate_key in common_keys
    ]
    score_deltas = [
        {
            "stable_candidate_key": stable_candidate_key,
            "baseline_candidate_id": baseline_by_key[stable_candidate_key]["candidate_id"],
            "comparison_candidate_id": comparison_by_key[stable_candidate_key]["candidate_id"],
            "baseline_score": round(
                float(baseline_by_key[stable_candidate_key].get("candidate_score") or 0.0),
                6,
            ),
            "comparison_score": round(
                float(comparison_by_key[stable_candidate_key].get("candidate_score") or 0.0),
                6,
            ),
            "score_delta": round(
                float(comparison_by_key[stable_candidate_key].get("candidate_score") or 0.0)
                - float(baseline_by_key[stable_candidate_key].get("candidate_score") or 0.0),
                6,
            ),
        }
        for stable_candidate_key in common_keys
    ]

    fail_reasons = []
    warn_reasons = []
    if not same_aoi_hash:
        fail_reasons.append("AOI hash differs between runs")
    if not same_date_window:
        warn_dates = (
            f"{baseline_run.get('start_date')} to {baseline_run.get('end_date')} vs "
            f"{comparison_run.get('start_date')} to {comparison_run.get('end_date')}"
        )
        fail_reasons.append(f"Date window differs between runs: {warn_dates}")
    if not same_processing_baseline:
        warn_reasons.append("Processing baseline differs between runs")
    if not same_source_scene_manifest_hash:
        warn_reasons.append("Source scene manifest differs between runs")
    if stability_rate < top10_threshold:
        warn_reasons.append(
            f"Top-10 stability rate {stability_rate:.2f} is below threshold {top10_threshold:.2f}"
        )

    if fail_reasons:
        status = "fail"
        reasons = fail_reasons + warn_reasons
    elif warn_reasons:
        status = "warn"
        reasons = warn_reasons
    else:
        status = "pass"
        reasons = ["Deterministic checks stable"]

    return {
        "baseline_run_id": baseline_run["run_id"],
        "comparison_run_id": comparison_run["run_id"],
        "same_processing_baseline": same_processing_baseline,
        "same_aoi_hash": same_aoi_hash,
        "same_date_window": same_date_window,
        "same_source_scene_manifest_hash": same_source_scene_manifest_hash,
        "baseline_candidate_count": len(baseline_ranked),
        "comparison_candidate_count": len(comparison_ranked),
        "common_candidate_count": len(common_keys),
        "added_candidate_ids": [
            comparison_by_key[stable_candidate_key]["candidate_id"]
            for stable_candidate_key in added_keys
        ],
        "removed_candidate_ids": [
            baseline_by_key[stable_candidate_key]["candidate_id"]
            for stable_candidate_key in removed_keys
        ],
        "top10_stability_rate": stability_rate,
        "top10_stability_threshold": top10_threshold,
        "rank_deltas": rank_deltas,
        "score_deltas": score_deltas,
        "status": status,
        "reasons": reasons,
        "baseline_run": _normalize_reproducibility_run(baseline_run),
        "comparison_run": _normalize_reproducibility_run(comparison_run),
    }


def top10_stability_rate(baseline_candidates: list[dict], retuned_candidates: list[dict]) -> float:
    baseline_top = set(top_candidate_match_keys(baseline_candidates, 10))
    if not baseline_top:
        return 0.0
    retuned_top = set(top_candidate_match_keys(retuned_candidates, 10))
    return round(len(baseline_top & retuned_top) / len(baseline_top), 6)


def acceptance_status(checks: list[dict]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def build_kpi_summary(
    *,
    run_id: str,
    source_scene_manifest_hash: str,
    candidate_rows: list[dict],
    aoi_area_km2: float,
    time_to_first_review_package_hours: float | None = None,
    paid_escalation_count: int = 0,
) -> dict:
    ranked_candidates = rank_candidates(candidate_rows)
    candidate_count_rate = candidate_count_per_100_km2(len(ranked_candidates), aoi_area_km2)
    top20_rate = approval_rate(ranked_candidates, top_n=20)
    paid_rate = paid_escalations_per_100_km2(paid_escalation_count, aoi_area_km2)
    return {
        "run_id": run_id,
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "aoi_area_km2": aoi_area_km2,
        "candidate_count": len(ranked_candidates),
        "candidate_count_per_100_km2": candidate_count_rate,
        "top_20_approval_rate": top20_rate,
        "top_10_candidate_ids": top_candidate_ids(ranked_candidates, top_n=10),
        "time_to_first_review_package_hours": time_to_first_review_package_hours,
        "paid_escalation_count": paid_escalation_count,
        "paid_escalations_per_100_km2": paid_rate,
    }


def build_acceptance_summary(
    *,
    kpi_summary: dict,
    top10_stability_rate_value: float | None = None,
) -> dict:
    checks = [
        {
            "name": "candidate_count_per_100_km2",
            "status": status_for_range(
                float(kpi_summary["candidate_count_per_100_km2"]),
                CANDIDATE_COUNT_MIN_PER_100_KM2,
                CANDIDATE_COUNT_MAX_PER_100_KM2,
            ),
            "observed": kpi_summary["candidate_count_per_100_km2"],
            "target": "15 to 50",
        },
        {
            "name": "top_20_approval_rate",
            "status": status_for_minimum(
                float(kpi_summary["top_20_approval_rate"]),
                TOP20_APPROVAL_ASPIRATIONAL_RATE,
                warn_minimum=TOP20_APPROVAL_MINIMUM_VIABLE_RATE,
            ),
            "observed": kpi_summary["top_20_approval_rate"],
            "target": ">= 0.25 aspirational, >= 0.15 minimum viable",
        },
        {
            "name": "paid_escalations_per_100_km2",
            "status": status_for_maximum(
                float(kpi_summary["paid_escalations_per_100_km2"]),
                PAID_ESCALATION_MAX_PER_100_KM2,
            ),
            "observed": kpi_summary["paid_escalations_per_100_km2"],
            "target": "<= 5",
        },
    ]
    if kpi_summary["time_to_first_review_package_hours"] is not None:
        checks.append(
            {
                "name": "time_to_first_review_package_hours",
                "status": status_for_maximum(
                    float(kpi_summary["time_to_first_review_package_hours"]),
                    WARM_CACHE_REVIEW_PACKAGE_MAX_HOURS,
                ),
                "observed": kpi_summary["time_to_first_review_package_hours"],
                "target": "<= 2",
            }
        )
    if top10_stability_rate_value is not None:
        checks.append(
            {
                "name": "top_10_stability_after_small_retune",
                "status": status_for_minimum(
                    top10_stability_rate_value,
                    TOP10_STABILITY_MINIMUM_RATE,
                ),
                "observed": top10_stability_rate_value,
                "target": ">= 0.70",
            }
        )
    return {
        "run_id": kpi_summary["run_id"],
        "status": acceptance_status(checks),
        "checks": checks,
        "kpis": kpi_summary,
    }


def render_acceptance_summary_markdown(summary: dict) -> str:
    lines = [
        "# Acceptance Summary",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Overall status: `{summary['status']}`",
        "",
        "| Check | Status | Observed | Target |",
        "| --- | --- | ---: | --- |",
    ]
    for check in summary["checks"]:
        observed = json.dumps(check["observed"])
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | {observed} | {check['target']} |"
        )
    return "\n".join(lines) + "\n"
