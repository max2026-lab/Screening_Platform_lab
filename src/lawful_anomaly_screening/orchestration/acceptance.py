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
PENDING_REVIEW_STATE = "pending_review"
WATCH_REVIEW_STATE = "watch"
REJECTED_REVIEW_STATE = "rejected"
CALIBRATION_REVIEW_COVERAGE_MINIMUM_RATE = 0.20
CALIBRATION_TOP20_REVIEW_COVERAGE_MINIMUM_RATE = 0.50


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


def review_coverage_rate(candidate_rows: list[dict], top_n: int | None = None) -> float:
    ranked_candidates = rank_candidates(candidate_rows)
    if top_n is not None:
        ranked_candidates = ranked_candidates[:top_n]
    if not ranked_candidates:
        return 0.0
    reviewed_count = sum(
        1 for candidate in ranked_candidates if candidate.get("review_state") != PENDING_REVIEW_STATE
    )
    return round(reviewed_count / len(ranked_candidates), 6)


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
    run_metadata: dict | None = None,
    review_state_counts: dict[str, int] | None = None,
    export_audit_manifest: dict | None = None,
    reproducibility_summary: dict | None = None,
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
    candidate_count = int(kpi_summary["candidate_count"])
    legal_gate = (run_metadata or {}).get("legal_gate")
    legal_gate_decision = (legal_gate or {}).get("decision")
    if legal_gate_decision is not None:
        checks.append(
            {
                "name": "legal_gate",
                "status": "pass" if legal_gate_decision == "pass" else "fail",
                "observed": legal_gate_decision,
                "target": "decision == pass",
            }
        )

    checks.append(
        {
            "name": "candidate_count",
            "status": "pass" if candidate_count > 0 else "fail",
            "observed": candidate_count,
            "target": ">= 1",
        }
    )

    composite_quality = (run_metadata or {}).get("composite_quality")
    cloud_policy_decision = (composite_quality or {}).get("cloud_policy_decision")
    if cloud_policy_decision is not None:
        checks.append(
            {
                "name": "composite_cloud_policy",
                "status": cloud_policy_decision,
                "observed": cloud_policy_decision,
                "target": "pass preferred; warn allowed; fail blocks run",
            }
        )

    export_audit_ready = export_audit_manifest is not None
    checks.append(
        {
            "name": "export_audit_ready",
            "status": "pass" if export_audit_ready else "warn",
            "observed": export_audit_ready,
            "target": "export audit manifest available",
        }
    )

    normalized_reproducibility_summary = None
    if reproducibility_summary is not None:
        normalized_reproducibility_summary = {
            "status": reproducibility_summary["status"],
            "top10_stability_rate": reproducibility_summary["top10_stability_rate"],
            "same_aoi_hash": reproducibility_summary["same_aoi_hash"],
            "same_date_window": reproducibility_summary["same_date_window"],
            "same_source_scene_manifest_hash": reproducibility_summary["same_source_scene_manifest_hash"],
            "reasons": list(reproducibility_summary["reasons"]),
        }
        checks.append(
            {
                "name": "reproducibility",
                "status": reproducibility_summary["status"],
                "observed": {
                    "top10_stability_rate": reproducibility_summary["top10_stability_rate"],
                    "same_aoi_hash": reproducibility_summary["same_aoi_hash"],
                    "same_date_window": reproducibility_summary["same_date_window"],
                    "same_source_scene_manifest_hash": reproducibility_summary["same_source_scene_manifest_hash"],
                },
                "target": "deterministic comparison stable",
            }
        )

    reasons = []
    if legal_gate_decision not in {None, "pass"}:
        reasons.append(
            f"Legal gate failed: {(legal_gate or {}).get('reason') or 'legal gate did not pass'}"
        )
    if candidate_count == 0:
        reasons.append("No candidates produced for run")
    if cloud_policy_decision == "warn":
        reasons.append(
            f"Composite cloud policy warning: {(composite_quality or {}).get('cloud_policy_reason') or 'cloud conditions require operator review'}"
        )
    if cloud_policy_decision == "fail":
        reasons.append(
            f"Composite cloud policy failed: {(composite_quality or {}).get('cloud_policy_reason') or 'cloud policy blocked run'}"
        )
    if not export_audit_ready:
        reasons.append("Export audit manifest not created yet")
    if normalized_reproducibility_summary is not None and reproducibility_summary["status"] in {"warn", "fail"}:
        reasons.extend(normalized_reproducibility_summary["reasons"])

    for check in checks:
        if check["status"] == "warn" and check["name"] == "top_20_approval_rate":
            reasons.append(
                f"Top-20 approval rate {float(check['observed']):.2f} is below aspirational threshold"
            )
        elif check["status"] == "fail" and check["name"] == "top_20_approval_rate":
            reasons.append(
                f"Top-20 approval rate {float(check['observed']):.2f} is below minimum viable target"
            )
        elif check["status"] == "fail" and check["name"] == "candidate_count_per_100_km2":
            reasons.append(
                f"Candidate density {float(check['observed']):.2f} is outside target range {check['target']}"
            )
        elif check["status"] == "fail" and check["name"] == "paid_escalations_per_100_km2":
            reasons.append(
                f"Paid escalations per 100 km2 {float(check['observed']):.2f} exceeds target {check['target']}"
            )
        elif check["status"] == "fail" and check["name"] == "time_to_first_review_package_hours":
            reasons.append(
                f"Time to first review package {float(check['observed']):.2f}h exceeds target {check['target']}"
            )
        elif check["status"] == "fail" and check["name"] == "top_10_stability_after_small_retune":
            reasons.append(
                f"Top-10 stability after small retune {float(check['observed']):.2f} is below target {check['target']}"
            )

    seen_reasons = set()
    ordered_reasons = []
    for reason in reasons:
        if reason not in seen_reasons:
            ordered_reasons.append(reason)
            seen_reasons.add(reason)

    status = acceptance_status(checks)
    if not ordered_reasons:
        ordered_reasons = ["Acceptance checks passed"]

    return {
        "run_id": kpi_summary["run_id"],
        "status": status,
        "reasons": ordered_reasons,
        "checks": checks,
        "kpis": kpi_summary,
        "legal_gate": legal_gate,
        "composite_quality": composite_quality,
        "source_scene_manifest_hash": (run_metadata or {}).get(
            "source_scene_manifest_hash",
            kpi_summary["source_scene_manifest_hash"],
        ),
        "processing_baseline_id": (run_metadata or {}).get("processing_baseline_id"),
        "score_formula_version": (run_metadata or {}).get("score_formula_version"),
        "candidate_count": candidate_count,
        "review_state_counts": dict(sorted((review_state_counts or {}).items())),
        "export_audit_ready": export_audit_ready,
        "latest_export_audit_manifest_hash": (
            export_audit_manifest.get("audit_manifest_hash") if export_audit_manifest else None
        ),
        "reproducibility_summary": normalized_reproducibility_summary,
    }


def build_calibration_pack(
    *,
    run_metadata: dict,
    candidate_rows: list[dict],
    review_state_counts: dict[str, int] | None = None,
    export_audit_manifest: dict | None = None,
    paid_escalation_count: int = 0,
    reproducibility_summary: dict | None = None,
) -> dict:
    sorted_review_state_counts = dict(sorted((review_state_counts or {}).items()))
    candidate_count = len(candidate_rows)
    reviewed_count = sum(
        count
        for state, count in sorted_review_state_counts.items()
        if state != PENDING_REVIEW_STATE
    )
    approved_count = int(sorted_review_state_counts.get(APPROVED_REVIEW_STATE, 0))
    rejected_count = int(sorted_review_state_counts.get(REJECTED_REVIEW_STATE, 0))
    watched_count = int(sorted_review_state_counts.get(WATCH_REVIEW_STATE, 0))
    coverage_rate = review_coverage_rate(candidate_rows)
    top20_coverage_rate = review_coverage_rate(candidate_rows, top_n=20)
    top20_approval_rate = approval_rate(candidate_rows, top_n=20)
    export_audit_ready = export_audit_manifest is not None
    legal_gate = run_metadata.get("legal_gate")
    legal_gate_decision = (legal_gate or {}).get("decision")
    composite_quality = run_metadata.get("composite_quality")

    acceptance_reasons = []
    acceptance_status = "pass"
    if legal_gate_decision not in {None, "pass"}:
        acceptance_status = "fail"
        acceptance_reasons.append(
            f"Legal gate failed: {(legal_gate or {}).get('reason') or 'legal gate did not pass'}"
        )
    if candidate_count == 0:
        acceptance_status = "fail"
        acceptance_reasons.append("No candidates produced for run")
    cloud_policy_decision = (composite_quality or {}).get("cloud_policy_decision")
    if cloud_policy_decision == "warn":
        if acceptance_status == "pass":
            acceptance_status = "warn"
        acceptance_reasons.append(
            f"Composite cloud policy warning: {(composite_quality or {}).get('cloud_policy_reason') or 'cloud conditions require operator review'}"
        )
    if cloud_policy_decision == "fail":
        acceptance_status = "fail"
        acceptance_reasons.append(
            f"Composite cloud policy failed: {(composite_quality or {}).get('cloud_policy_reason') or 'cloud policy blocked run'}"
        )
    if not export_audit_ready:
        if acceptance_status == "pass":
            acceptance_status = "warn"
        acceptance_reasons.append("Export audit manifest not created yet")
    normalized_reproducibility_summary = None
    if reproducibility_summary is not None:
        normalized_reproducibility_summary = {
            "status": reproducibility_summary["status"],
            "top10_stability_rate": reproducibility_summary["top10_stability_rate"],
            "same_aoi_hash": reproducibility_summary["same_aoi_hash"],
            "same_date_window": reproducibility_summary["same_date_window"],
            "same_source_scene_manifest_hash": reproducibility_summary["same_source_scene_manifest_hash"],
            "reasons": list(reproducibility_summary["reasons"]),
        }
        if reproducibility_summary["status"] == "fail":
            acceptance_status = "fail"
        elif reproducibility_summary["status"] == "warn" and acceptance_status == "pass":
            acceptance_status = "warn"
        if reproducibility_summary["status"] in {"warn", "fail"}:
            acceptance_reasons.extend(normalized_reproducibility_summary["reasons"])
    if not acceptance_reasons:
        acceptance_reasons = ["Acceptance evidence available"]

    readiness_checks = [
        {
            "name": "legal_gate",
            "status": "pass" if legal_gate_decision == "pass" else "fail",
            "observed": legal_gate_decision,
            "target": "decision == pass",
        },
        {
            "name": "candidate_count",
            "status": "pass" if candidate_count > 0 else "incomplete",
            "observed": candidate_count,
            "target": ">= 1",
        },
        {
            "name": "review_coverage_rate",
            "status": "pass" if coverage_rate >= CALIBRATION_REVIEW_COVERAGE_MINIMUM_RATE else "incomplete",
            "observed": coverage_rate,
            "target": ">= 0.20",
        },
        {
            "name": "top20_review_coverage_rate",
            "status": "pass"
            if top20_coverage_rate >= CALIBRATION_TOP20_REVIEW_COVERAGE_MINIMUM_RATE
            else "incomplete",
            "observed": top20_coverage_rate,
            "target": ">= 0.50",
        },
        {
            "name": "export_audit_ready",
            "status": "pass" if export_audit_ready else "incomplete",
            "observed": export_audit_ready,
            "target": "export audit manifest available",
        },
    ]
    if reproducibility_summary is None:
        readiness_checks.append(
            {
                "name": "reproducibility",
                "status": "incomplete",
                "observed": None,
                "target": "comparison run supplied with pass status",
            }
        )
    else:
        readiness_checks.append(
            {
                "name": "reproducibility",
                "status": "pass" if reproducibility_summary["status"] == "pass" else reproducibility_summary["status"],
                "observed": {
                    "status": reproducibility_summary["status"],
                    "top10_stability_rate": reproducibility_summary["top10_stability_rate"],
                    "same_aoi_hash": reproducibility_summary["same_aoi_hash"],
                    "same_date_window": reproducibility_summary["same_date_window"],
                    "same_source_scene_manifest_hash": reproducibility_summary["same_source_scene_manifest_hash"],
                },
                "target": "comparison run supplied with pass status",
            }
        )

    reasons = []
    if legal_gate_decision != "pass":
        reasons.append(
            f"Legal gate failed: {(legal_gate or {}).get('reason') or 'legal gate did not pass'}"
        )
    if candidate_count == 0:
        reasons.append("No candidates produced for run")
    if coverage_rate < CALIBRATION_REVIEW_COVERAGE_MINIMUM_RATE:
        reasons.append(
            f"Review coverage rate {coverage_rate:.2f} is below minimum {CALIBRATION_REVIEW_COVERAGE_MINIMUM_RATE:.2f}"
        )
    if top20_coverage_rate < CALIBRATION_TOP20_REVIEW_COVERAGE_MINIMUM_RATE:
        reasons.append(
            f"Top-20 review coverage rate {top20_coverage_rate:.2f} is below minimum {CALIBRATION_TOP20_REVIEW_COVERAGE_MINIMUM_RATE:.2f}"
        )
    if not export_audit_ready:
        reasons.append("Export audit manifest not created yet")
    if reproducibility_summary is None:
        reasons.append("Reproducibility comparison run not supplied")
    elif reproducibility_summary["status"] != "pass":
        reasons.extend(reproducibility_summary["reasons"])

    check_statuses = {check["status"] for check in readiness_checks}
    if "fail" in check_statuses:
        status = "fail"
    elif "incomplete" in check_statuses or "warn" in check_statuses:
        status = "incomplete"
    else:
        status = "ready"

    seen_reasons = set()
    ordered_reasons = []
    for reason in reasons:
        if reason not in seen_reasons:
            ordered_reasons.append(reason)
            seen_reasons.add(reason)
    if not ordered_reasons:
        ordered_reasons = ["Calibration readiness checks passed"]

    payload = {
        "run_id": run_metadata["run_id"],
        "status": status,
        "reasons": ordered_reasons,
        "processing_baseline_id": run_metadata.get("processing_baseline_id"),
        "score_formula_version": run_metadata.get("score_formula_version"),
        "source_scene_manifest_hash": run_metadata.get("source_scene_manifest_hash"),
        "legal_gate": legal_gate,
        "composite_quality": composite_quality,
        "candidate_count": candidate_count,
        "review_state_counts": sorted_review_state_counts,
        "reviewed_candidate_count": reviewed_count,
        "approved_candidate_count": approved_count,
        "rejected_candidate_count": rejected_count,
        "watched_candidate_count": watched_count,
        "review_coverage_rate": coverage_rate,
        "top20_review_coverage_rate": top20_coverage_rate,
        "top20_approval_rate": top20_approval_rate,
        "acceptance_summary": {
            "run_id": run_metadata["run_id"],
            "status": acceptance_status,
            "reasons": acceptance_reasons,
            "legal_gate": legal_gate,
            "composite_quality": composite_quality,
            "candidate_count": candidate_count,
            "review_state_counts": sorted_review_state_counts,
            "export_audit_ready": export_audit_ready,
            "latest_export_audit_manifest_hash": (
                export_audit_manifest.get("audit_manifest_hash") if export_audit_manifest else None
            ),
            "reproducibility_summary": normalized_reproducibility_summary,
        },
        "export_audit_ready": export_audit_ready,
        "latest_export_audit_manifest_hash": (
            export_audit_manifest.get("audit_manifest_hash") if export_audit_manifest else None
        ),
        "paid_escalation_count": paid_escalation_count,
        "calibration_readiness_checks": readiness_checks,
    }
    if normalized_reproducibility_summary is not None:
        payload["reproducibility_summary"] = normalized_reproducibility_summary
    return payload


def render_acceptance_summary_markdown(summary: dict) -> str:
    lines = [
        "# Acceptance Summary",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Overall status: `{summary['status']}`",
        f"- Candidate count: `{summary.get('candidate_count')}`",
        f"- Export audit ready: `{summary.get('export_audit_ready')}`",
    ]
    if summary.get("legal_gate") is not None:
        lines.append(f"- Legal gate: `{summary['legal_gate'].get('decision')}`")
    if summary.get("composite_quality") is not None:
        lines.append(
            f"- Composite cloud policy: `{summary['composite_quality'].get('cloud_policy_decision')}`"
        )
    if summary.get("reasons"):
        lines.extend(
            [
                "",
                "## Reasons",
                "",
            ]
        )
        lines.extend(f"- {reason}" for reason in summary["reasons"])
    lines.extend(
        [
        "",
        "| Check | Status | Observed | Target |",
        "| --- | --- | ---: | --- |",
        ]
    )
    for check in summary["checks"]:
        observed = json.dumps(check["observed"])
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | {observed} | {check['target']} |"
        )
    return "\n".join(lines) + "\n"


def render_calibration_pack_markdown(pack: dict) -> str:
    lines = [
        "# Calibration Evidence Pack",
        "",
        f"- Run ID: `{pack['run_id']}`",
        f"- Status: `{pack['status']}`",
        f"- Candidate count: `{pack['candidate_count']}`",
        f"- Reviewed candidate count: `{pack['reviewed_candidate_count']}`",
        f"- Review coverage rate: `{pack['review_coverage_rate']}`",
        f"- Top-20 review coverage rate: `{pack['top20_review_coverage_rate']}`",
        f"- Top-20 approval rate: `{pack['top20_approval_rate']}`",
        f"- Export audit ready: `{pack['export_audit_ready']}`",
        f"- Paid escalation count: `{pack['paid_escalation_count']}`",
    ]
    if pack.get("legal_gate") is not None:
        lines.append(f"- Legal gate: `{pack['legal_gate'].get('decision')}`")
    if pack.get("composite_quality") is not None:
        lines.append(
            f"- Composite cloud policy: `{pack['composite_quality'].get('cloud_policy_decision')}`"
        )
    lines.extend(
        [
            "",
            "## Readiness Checks",
            "",
            "| Check | Status | Observed | Target |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for check in pack["calibration_readiness_checks"]:
        observed = json.dumps(check["observed"])
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | {observed} | {check['target']} |"
        )
    lines.extend(
        [
            "",
            "## Reasons",
            "",
        ]
    )
    lines.extend(f"- {reason}" for reason in pack["reasons"])
    return "\n".join(lines) + "\n"
