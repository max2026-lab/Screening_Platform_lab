from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Literal

from ..db.repositories.run_repository import RunRepository
from ..db.repositories.review_repository import ReviewRepository
from ..db.sqlite import connect
from ..settings import load_settings

SCHEMA_VERSION = "v1.18.0"

_FormatLiteral = Literal["json", "markdown", "both"]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _check_readable(path: Path) -> bool:
    try:
        return os.access(path, os.R_OK)
    except OSError:
        return False


def _scan_artifact_root(root: Path) -> dict:
    json_count = 0
    md_count = 0
    image_count = 0
    geojson_count = 0
    zip_count = 0
    temp_count = 0
    safety_warnings: list[str] = []
    reviewer_folders: list[str] = []
    public_folders: list[str] = []

    for item in root.rglob("*"):
        try:
            rel = item.relative_to(root)
        except ValueError:
            continue
        name_lower = item.name.lower()
        if item.is_file():
            if name_lower.endswith(".geojson"):
                geojson_count += 1
            elif name_lower.endswith(".json"):
                json_count += 1
            elif name_lower.endswith(".md"):
                md_count += 1
            elif name_lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif")):
                image_count += 1
            elif name_lower.endswith(".zip"):
                zip_count += 1

            if (
                name_lower.endswith(".tmp")
                or name_lower.endswith(".partial")
                or name_lower.endswith(".incomplete")
                or "incomplete" in name_lower
            ):
                temp_count += 1

            parent_parts = [p.lower() for p in rel.parent.parts]
            is_public = any(p in ("public", "obfuscated") for p in parent_parts)
            is_reviewer = any(p in ("reviewer", "reviewer_only") for p in parent_parts)
            if is_public:
                if any(k in name_lower for k in ("exact", "precise", "reviewer_only")):
                    safety_warnings.append(
                        f"Potentially unsafe artifact '{rel}' found in public/obfuscated folder"
                    )
            if is_reviewer and is_public:
                safety_warnings.append(
                    f"Mixed export sensitivity in folder '{rel.parent}': reviewer and public artifacts"
                )
        elif item.is_dir():
            if name_lower in ("reviewer", "reviewer_only"):
                reviewer_folders.append(str(rel).replace("\\", "/"))
            if name_lower in ("public", "obfuscated"):
                public_folders.append(str(rel).replace("\\", "/"))

    return {
        "root_exists": True,
        "root_is_directory": True,
        "root_readable": _check_readable(root),
        "file_counts": {
            "json": json_count,
            "markdown": md_count,
            "image": image_count,
            "geojson": geojson_count,
            "zip": zip_count,
            "temp_incomplete": temp_count,
        },
        "reviewer_folders": sorted(reviewer_folders),
        "public_folders": sorted(public_folders),
        "safety_warnings": safety_warnings,
    }


def _fetch_geofence_hits(db_path: Path, run_id: str) -> list[dict]:
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT geofence_hit_id, hit_type FROM geofence_hits WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fetch_candidate_score_gaps(db_path: Path, run_id: str) -> list[str]:
    warnings: list[str] = []
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT cp.candidate_id, cs.candidate_score, cs.score_breakdown_json
            FROM candidate_polygons cp
            LEFT JOIN candidate_scores cs
                ON cs.candidate_id = cp.candidate_id
                AND cs.run_id = cp.run_id
            WHERE cp.run_id = ?
            """,
            (run_id,),
        ).fetchall()
    for row in rows:
        cid = row["candidate_id"]
        if row["candidate_score"] is None:
            warnings.append(f"Candidate {cid} is missing score")
        if not row["score_breakdown_json"]:
            warnings.append(f"Candidate {cid} is missing score breakdown")
    return warnings


def _fetch_duplicate_flags(db_path: Path, run_id: str) -> list[str]:
    warnings: list[str] = []
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT candidate_id
            FROM candidate_polygons
            WHERE run_id = ? AND possible_duplicate = 1
            """,
            (run_id,),
        ).fetchall()
    for row in rows:
        warnings.append(f"Candidate {row['candidate_id']} has possible_duplicate flag")
    return warnings


def _build_review_package_readiness_result(
    run_id: str,
    artifact_root: str | Path | None = None,
) -> dict:
    """Pure read-only review package readiness check. No file writes."""
    settings = load_settings()
    db_path = settings.db_path

    warnings: list[str] = []
    failures: list[str] = []

    run_exists = False
    run_status = None
    candidate_count = 0
    review_queue_count = 0
    top_candidate_id = None
    legal_decision = None
    run: dict | None = None
    legal_gate: dict | None = None
    artifact_check: dict | None = None

    try:
        run_repo = RunRepository(db_path)
        review_repo = ReviewRepository(db_path)

        run = run_repo.fetch_run(run_id)

        # Run metadata
        run_exists = run is not None
        run_status = run.get("status") if run else None
        candidate_count = run_repo.count_candidates(run_id) if run_exists else 0
        review_queue = review_repo.list_review_queue(run_id=run_id) if run_exists else []
        review_queue_count = len(review_queue)
        top_candidate_id = run_repo.fetch_top_candidate_id(run_id) if run_exists else None

        # Legal/safety
        legal_gate = run.get("legal_gate") if run else None
        legal_decision = legal_gate.get("decision") if legal_gate else None

        if not run_exists:
            failures.append(f"Run not found: {run_id}")
        else:
            if legal_decision is None:
                warnings.append("Legal gate decision is missing")
            elif legal_decision != "pass":
                failures.append(f"Legal gate decision is '{legal_decision}'; expected 'pass'")
            else:
                if legal_gate.get("geofence_status") in ("missing", "unknown"):
                    warnings.append("Legal gate geofence status is missing or unknown")

            # Candidate/review queue readiness
            if run_status in ("completed", "review_ready"):
                if candidate_count == 0:
                    with connect(db_path) as conn:
                        row = conn.execute(
                            "SELECT COUNT(*) FROM export_records WHERE run_id = ?",
                            (run_id,),
                        ).fetchone()
                        export_count = int(row[0]) if row else 0
                    if export_count == 0:
                        failures.append(
                            "Run is completed/review_ready but has no candidates and no export records"
                        )

            if candidate_count > 0 and review_queue_count == 0:
                warnings.append("Candidates exist but review queue is empty")

            # Candidate readiness
            warnings.extend(_fetch_candidate_score_gaps(db_path, run_id))
            warnings.extend(_fetch_duplicate_flags(db_path, run_id))

            # Geofence hits
            geofence_hits = _fetch_geofence_hits(db_path, run_id)
            if geofence_hits:
                for hit in geofence_hits:
                    warnings.append(
                        f"Geofence hit detected: {hit['hit_type']} ({hit['geofence_hit_id']})"
                    )
    except Exception as exc:
        failures.append(f"DB read failed: {exc}")

    # Artifact root checks
    if artifact_root is not None:
        root_path = Path(artifact_root).resolve()
        if not root_path.exists():
            failures.append(f"Artifact root does not exist: {root_path}")
            artifact_check = {"root_exists": False, "root_is_directory": False, "root_readable": False}
        elif not root_path.is_dir():
            failures.append(f"Artifact root is not a directory: {root_path}")
            artifact_check = {"root_exists": True, "root_is_directory": False, "root_readable": False}
        else:
            artifact_check = _scan_artifact_root(root_path)
            if not artifact_check["root_readable"]:
                failures.append(f"Artifact root is not readable: {root_path}")
            if artifact_check["file_counts"]["temp_incomplete"] > 0:
                warnings.append(
                    f"Artifact root contains {artifact_check['file_counts']['temp_incomplete']} incomplete/temp files"
                )
            warnings.extend(artifact_check.get("safety_warnings", []))

    overall_status = "pass"
    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "warn"

    return {
        "status": overall_status,
        "warnings": warnings,
        "failures": failures,
        "checks": {
            "run_exists": run_exists,
            "run_status": run_status,
            "aoi_hash": run.get("aoi_hash") if run else None,
            "aoi_path": run.get("aoi_path") if run else None,
            "start_date": run.get("start_date") if run else None,
            "end_date": run.get("end_date") if run else None,
            "legal_gate_decision": legal_decision,
            "source_endpoint_id": run.get("source_endpoint_id") if run else None,
            "source_scene_manifest_hash": run.get("source_scene_manifest_hash") if run else None,
            "candidate_count": candidate_count,
            "review_queue_count": review_queue_count,
            "top_candidate_id": top_candidate_id,
            "artifact_root": str(Path(artifact_root).resolve()).replace("\\", "/") if artifact_root else None,
            "artifact_check": artifact_check,
        },
    }


def run_review_package_readiness_check(
    run_id: str,
    artifact_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    fmt: _FormatLiteral = "both",
) -> dict:
    """Run an offline review package readiness check and write deterministic report artifacts.

    Produces under <output_dir>/:
    - review_package_readiness_check.json
    - review_package_readiness_check.md
    - SHA256SUMS.txt
    """
    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = Path(".review-package-readiness").resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    result = _build_review_package_readiness_result(run_id, artifact_root)
    overall_status = result["status"]
    warnings = result["warnings"]
    failures = result["failures"]
    checks = result["checks"]

    write_json = fmt in ("json", "both")
    write_md = fmt in ("markdown", "both")

    json_path = out_path / "review_package_readiness_check.json"
    md_path = out_path / "review_package_readiness_check.md"
    sums_path = out_path / "SHA256SUMS.txt"

    artifact_manifest: list[dict] = []
    if write_json:
        artifact_manifest.append({
            "name": "review_package_readiness_check.json",
            "sha256": None,
            "note": "self-hash omitted to avoid circular dependency",
        })
    if write_md:
        artifact_manifest.append({
            "name": "review_package_readiness_check.md",
            "sha256": None,
            "note": "hash populated after markdown is finalized",
        })
    artifact_manifest.append({
        "name": "SHA256SUMS.txt",
        "sha256": None,
        "note": "canonical hash list for all report artifacts",
    })

    report_payload = {
        "schema": {
            "version": SCHEMA_VERSION,
            "name": "review_package_readiness_check",
        },
        "run_id": run_id,
        "status": overall_status,
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
        "reasons": warnings + failures,
        "artifact_manifest": artifact_manifest,
    }

    json_hash_first: str | None = None
    json_hash_final: str | None = None
    md_hash: str | None = None

    if write_json:
        json_path.write_text(_stable_json(report_payload), encoding="utf-8")
        json_hash_first = _sha256_file(json_path)

        if write_md:
            md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")
            md_hash = _sha256_file(md_path)

            for entry in report_payload["artifact_manifest"]:
                if entry["name"] == "review_package_readiness_check.md":
                    entry["sha256"] = md_hash
                    entry["note"] = "hash finalized after markdown write"
            json_path.write_text(_stable_json(report_payload), encoding="utf-8")
            json_hash_final = _sha256_file(json_path)
        else:
            json_hash_final = json_hash_first
    elif write_md:
        md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")
        md_hash = _sha256_file(md_path)

    sums_lines: list[str] = []
    if write_json and json_hash_final is not None:
        sums_lines.append(f"{json_hash_final}  review_package_readiness_check.json")
    if write_md and md_hash is not None:
        sums_lines.append(f"{md_hash}  review_package_readiness_check.md")
    sums_text = "\n".join(sorted(sums_lines)) + "\n"
    sums_path.write_text(sums_text, encoding="utf-8")

    result_artifacts: list[dict] = []
    if write_json and json_hash_final is not None:
        result_artifacts.append({"name": json_path.name, "sha256": json_hash_final})
    if write_md and md_hash is not None:
        result_artifacts.append({"name": md_path.name, "sha256": md_hash})
    result_artifacts.append({"name": sums_path.name, "sha256": _sha256_file(sums_path)})

    return {
        "schema": report_payload["schema"],
        "status": overall_status,
        "output_dir": str(out_path).replace("\\", "/"),
        "artifacts": result_artifacts,
        "warnings": warnings,
        "failures": failures,
        "reasons": warnings + failures,
    }


def _render_report_markdown(payload: dict) -> str:
    lines = [
        "# Review Package Readiness Check",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Run ID: `{payload['run_id']}`",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Checks",
        "",
    ]

    checks = payload.get("checks", {})
    lines.append(f"- Run exists: `{checks.get('run_exists', False)}`")
    lines.append(f"- Run status: `{checks.get('run_status', 'unknown')}`")
    lines.append(f"- Legal gate decision: `{checks.get('legal_gate_decision', 'unknown')}`")
    lines.append(f"- Candidate count: {checks.get('candidate_count', 0)}")
    lines.append(f"- Review queue count: {checks.get('review_queue_count', 0)}")
    if checks.get("top_candidate_id"):
        lines.append(f"- Top candidate ID: `{checks['top_candidate_id']}`")
    if checks.get("aoi_hash"):
        lines.append(f"- AOI hash: `{checks['aoi_hash']}`")
    if checks.get("start_date"):
        lines.append(f"- Start date: `{checks['start_date']}`")
    if checks.get("end_date"):
        lines.append(f"- End date: `{checks['end_date']}`")
    if checks.get("source_endpoint_id"):
        lines.append(f"- Source endpoint ID: `{checks['source_endpoint_id']}`")
    if checks.get("source_scene_manifest_hash"):
        lines.append(f"- Source scene manifest hash: `{checks['source_scene_manifest_hash']}`")
    lines.append("")

    artifact = checks.get("artifact_check")
    if artifact is not None:
        lines.append("### Artifact Root")
        lines.append(f"- Root exists: `{artifact.get('root_exists', False)}`")
        lines.append(f"- Root is directory: `{artifact.get('root_is_directory', False)}`")
        lines.append(f"- Root readable: `{artifact.get('root_readable', False)}`")
        file_counts = artifact.get("file_counts", {})
        if file_counts:
            for label, count in sorted(file_counts.items()):
                lines.append(f"- {label}: {count}")
        if artifact.get("reviewer_folders"):
            lines.append("- Reviewer folders:")
            for f in artifact["reviewer_folders"]:
                lines.append(f"  - `{f}`")
        if artifact.get("public_folders"):
            lines.append("- Public/obfuscated folders:")
            for f in artifact["public_folders"]:
                lines.append(f"  - `{f}`")
        lines.append("")

    warnings = payload.get("warnings", [])
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    failures = payload.get("failures", [])
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- This report was generated offline.",
        "- No network or GitHub API calls were made.",
        "- No DB mutations were performed.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
