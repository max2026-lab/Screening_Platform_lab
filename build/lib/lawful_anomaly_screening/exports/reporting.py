from __future__ import annotations

import json

from lawful_anomaly_screening.exports.precision_policy import ExportPolicy


def render_markdown_report(
    *,
    run_id: str,
    audience: str,
    policy: ExportPolicy,
    artifact_name: str,
    bundle_name: str,
    candidates: list[dict],
) -> str:
    lines = [
        "# Lawful Anomaly Screening Report",
        "",
        f"- Run ID: `{run_id}`",
        f"- Audience: `{audience}`",
        f"- Precision tier: `{policy.precision_tier}`",
        f"- Exact coordinates included: `{str(policy.exact_coordinates_included).lower()}`",
        f"- Artifact name: `{artifact_name}`",
        f"- Bundle name: `{bundle_name}`",
        f"- Candidate count: `{len(candidates)}`",
        "",
        "## Candidate Summary",
    ]

    if not candidates:
        lines.extend(["", "No candidate records were included in this scaffold export."])
        return "\n".join(lines) + "\n"

    lines.extend(["", "| Candidate | Centroid | Area (m2) | Possible Duplicate |", "| --- | --- | ---: | --- |"])
    for candidate in candidates:
        centroid = json.dumps(candidate.get("centroid"))
        area_m2 = candidate.get("area_m2", 0.0)
        possible_duplicate = str(bool(candidate.get("possible_duplicate", False))).lower()
        lines.append(
            f"| `{candidate['candidate_id']}` | `{centroid}` | {area_m2:.2f} | `{possible_duplicate}` |"
        )

    return "\n".join(lines) + "\n"
