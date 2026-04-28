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
    run_metadata: dict | None = None,
) -> str:
    if not candidates:
        lines = [
            "# Lawful Anomaly Screening Report",
            "",
            f"- Run ID: `{run_id}`",
            f"- Audience: `{audience}`",
            f"- Precision tier: `{policy.precision_tier}`",
            f"- Exact coordinates included: `{str(policy.exact_coordinates_included).lower()}`",
            f"- Candidate count: `0`",
        ]
        if run_metadata:
            aoi_hash = run_metadata.get("aoi_hash")
            aoi_bbox = run_metadata.get("aoi_bbox")
            if aoi_hash:
                lines.append(f"- AOI hash: `{aoi_hash}`")
            elif aoi_bbox:
                lines.append(f"- AOI bbox: `{json.dumps(aoi_bbox)}`")
            start_date = run_metadata.get("start_date")
            end_date = run_metadata.get("end_date")
            if start_date:
                lines.append(f"- Start date: `{start_date}`")
            if end_date:
                lines.append(f"- End date: `{end_date}`")
            legal_gate = run_metadata.get("legal_gate")
            if legal_gate:
                lines.append(f"- Legal gate decision: `{legal_gate.get('decision', '')}`")
        lines.extend([
            "",
            "## No Exportable Candidates Found",
            "",
            "This AOI/date window was screened and produced zero exportable candidates.",
            "",
        ])
        return "\n".join(lines) + "\n"

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

    lines.extend(["", "| Candidate | Centroid | Area (m2) | Possible Duplicate |", "| --- | --- | ---: | --- |"])
    for candidate in candidates:
        centroid = json.dumps(candidate.get("centroid"))
        area_m2 = candidate.get("area_m2", 0.0)
        possible_duplicate = str(bool(candidate.get("possible_duplicate", False))).lower()
        lines.append(
            f"| `{candidate['candidate_id']}` | `{centroid}` | {area_m2:.2f} | `{possible_duplicate}` |"
        )

    return "\n".join(lines) + "\n"
