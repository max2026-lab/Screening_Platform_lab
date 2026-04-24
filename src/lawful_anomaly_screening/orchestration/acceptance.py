from __future__ import annotations

from dataclasses import dataclass
import json


CANDIDATE_COUNT_MIN_PER_100_KM2 = 15.0
CANDIDATE_COUNT_MAX_PER_100_KM2 = 50.0
TOP20_APPROVAL_MINIMUM_VIABLE_RATE = 0.15
TOP20_APPROVAL_ASPIRATIONAL_RATE = 0.25
REPRODUCIBILITY_SCORE_TOLERANCE = 0.5
TOP10_STABILITY_MINIMUM_RATE = 0.70
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


def top_candidate_ids(candidate_rows: list[dict], top_n: int = 10) -> list[str]:
    return [row["candidate_id"] for row in rank_candidates(candidate_rows)[:top_n]]


def scores_within_tolerance(
    baseline_candidates: list[dict],
    comparison_candidates: list[dict],
    tolerance: float = REPRODUCIBILITY_SCORE_TOLERANCE,
    top_n: int = 10,
) -> bool:
    baseline_by_id = {row["candidate_id"]: row for row in baseline_candidates}
    comparison_by_id = {row["candidate_id"]: row for row in comparison_candidates}
    for candidate_id in top_candidate_ids(baseline_candidates, top_n):
        if candidate_id not in comparison_by_id:
            return False
        baseline_score = float(baseline_by_id[candidate_id].get("candidate_score") or 0.0)
        comparison_score = float(comparison_by_id[candidate_id].get("candidate_score") or 0.0)
        if abs(baseline_score - comparison_score) > tolerance:
            return False
    return True


def reproducibility_check(
    baseline_manifest_hash: str,
    comparison_manifest_hash: str,
    baseline_candidates: list[dict],
    comparison_candidates: list[dict],
    tolerance: float = REPRODUCIBILITY_SCORE_TOLERANCE,
    top_n: int = 10,
) -> dict:
    same_manifest = baseline_manifest_hash == comparison_manifest_hash
    baseline_top_ids = top_candidate_ids(baseline_candidates, top_n)
    comparison_top_ids = top_candidate_ids(comparison_candidates, top_n)
    same_top_rank_order = baseline_top_ids == comparison_top_ids
    scores_match = scores_within_tolerance(
        baseline_candidates,
        comparison_candidates,
        tolerance=tolerance,
        top_n=top_n,
    )
    passed = same_manifest and same_top_rank_order and scores_match
    return {
        "status": "pass" if passed else "fail",
        "same_manifest": same_manifest,
        "same_top_10_rank_order": same_top_rank_order,
        "scores_within_tolerance": scores_match,
        "score_tolerance": tolerance,
        "baseline_top_10": baseline_top_ids,
        "comparison_top_10": comparison_top_ids,
    }


def top10_stability_rate(baseline_candidates: list[dict], retuned_candidates: list[dict]) -> float:
    baseline_top = set(top_candidate_ids(baseline_candidates, 10))
    if not baseline_top:
        return 0.0
    retuned_top = set(top_candidate_ids(retuned_candidates, 10))
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
