from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from .evidence_index_export_smoke import run_release_evidence_index_export_smoke

SCHEMA_VERSION = "v1.15.0"

_FormatLiteral = Literal["json", "markdown", "both"]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def run_release_evidence_index_export_smoke_report(
    evidence_root: str | Path,
    output_root: str | Path,
    formats: list[_FormatLiteral] | None = None,
) -> dict:
    """Run V1.14 smoke and write durable evidence report artifacts.

    Produces under <output_root>/release-evidence-index-export-smoke-report/:
    - release_evidence_index_export_smoke_report.json
    - release_evidence_index_export_smoke_report.md
    - SHA256SUMS.txt

    The command is offline, requires no DB, no network, and does not
    mutate source evidence directories.
    """
    evidence_path = Path(evidence_root).resolve()
    out_root = Path(output_root).resolve()

    # Safety: output_root must not be evidence_root or inside it
    try:
        out_root.relative_to(evidence_path)
        return {
            "schema": {
                "version": SCHEMA_VERSION,
                "name": "release_evidence_index_export_smoke_report",
            },
            "evidence_root": str(evidence_path).replace("\\", "/"),
            "output_root": str(out_root).replace("\\", "/"),
            "formats_run": formats if formats else ["json", "markdown", "both"],
            "smoke_result": None,
            "report_dir": None,
            "report_artifacts": [],
            "status": "fail",
            "reasons": ["output_root must not be the same as or inside evidence_root"],
        }
    except ValueError:
        pass

    selected_formats: list[_FormatLiteral] = formats if formats else ["json", "markdown", "both"]

    # Run V1.14 smoke (reuse existing implementation)
    smoke_result = run_release_evidence_index_export_smoke(
        evidence_root=evidence_path,
        output_root=out_root,
        formats=selected_formats,
    )

    # Build report payload
    report_payload = {
        "schema": {
            "version": SCHEMA_VERSION,
            "name": "release_evidence_index_export_smoke_report",
        },
        "evidence_root": str(evidence_path).replace("\\", "/"),
        "output_root": str(out_root).replace("\\", "/"),
        "formats_run": selected_formats,
        "smoke_result": smoke_result,
        "status": smoke_result.get("status", "fail"),
        "reasons": smoke_result.get("reasons", []),
    }

    # Write report artifacts
    report_dir = out_root / "release-evidence-index-export-smoke-report"
    report_dir.mkdir(parents=True, exist_ok=True)

    json_path = report_dir / "release_evidence_index_export_smoke_report.json"
    md_path = report_dir / "release_evidence_index_export_smoke_report.md"

    json_path.write_text(_stable_json(report_payload), encoding="utf-8")
    md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")

    # Write SHA256SUMS.txt (only for report artifacts, never self)
    sums_lines: list[str] = []
    json_hash = _sha256_file(json_path)
    md_hash = _sha256_file(md_path)
    sums_lines.append(f"{json_hash}  release_evidence_index_export_smoke_report.json")
    sums_lines.append(f"{md_hash}  release_evidence_index_export_smoke_report.md")
    sums_text = "\n".join(sorted(sums_lines)) + "\n"
    sums_path = report_dir / "SHA256SUMS.txt"
    sums_path.write_text(sums_text, encoding="utf-8")

    sums_hash = _sha256_file(sums_path)

    return {
        "schema": report_payload["schema"],
        "evidence_root": report_payload["evidence_root"],
        "output_root": report_payload["output_root"],
        "formats_run": selected_formats,
        "smoke_result": smoke_result,
        "report_dir": str(report_dir).replace("\\", "/"),
        "report_artifacts": [
            {"name": json_path.name, "sha256": json_hash},
            {"name": md_path.name, "sha256": md_hash},
            {"name": sums_path.name, "sha256": sums_hash},
        ],
        "status": report_payload["status"],
        "reasons": report_payload["reasons"],
    }


def _render_report_markdown(payload: dict) -> str:
    lines = [
        "# Release Evidence Index Export Smoke Report",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Evidence root: `{payload['evidence_root']}`",
        f"- Output root: `{payload['output_root']}`",
        f"- Formats run: {', '.join(payload['formats_run'])}",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Smoke Result",
        "",
    ]

    smoke = payload.get("smoke_result")
    if smoke:
        lines.append(f"- Smoke status: `{smoke.get('status', 'unknown')}`")
        lines.append(f"- Smoke evidence root: `{smoke.get('evidence_root', '')}`")
        lines.append(f"- Smoke output root: `{smoke.get('output_root', '')}`")
        lines.append("")
        for fmt_result in smoke.get("results", []):
            fmt = fmt_result.get("format", "unknown")
            lines.append(f"### Format: {fmt}")
            lines.append(f"- Export status: `{fmt_result.get('export_status', 'unknown')}`")
            lines.append(f"- Verify status: `{fmt_result.get('verify_status', 'unknown')}`")
            lines.append(f"- Overall: `{fmt_result.get('status', 'unknown')}`")
            artifacts = fmt_result.get("export_artifacts", [])
            if artifacts:
                lines.append("- Artifacts:")
                for artifact in artifacts:
                    lines.append(f"  - `{artifact['name']}`: `{artifact['sha256']}`")
            reasons = fmt_result.get("verify_reasons", [])
            if reasons:
                lines.append("- Reasons:")
                for reason in reasons:
                    lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("- No smoke result available.")
        lines.append("")

    reasons = payload.get("reasons", [])
    if reasons:
        lines.append("## Reasons")
        lines.append("")
        for reason in reasons:
            lines.append(f"- {reason}")
        lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- This report was generated offline.",
        "- No network or GitHub API calls were made.",
        "- No DB access was required.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
