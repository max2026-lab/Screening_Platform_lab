from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from ..db.repositories.run_repository import RunRepository
from ..db.sqlite import connect
from ..ops.review_package_readiness import _build_review_package_readiness_result
from ..settings import load_settings

SCHEMA_VERSION = "v1.19.0"

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
    artifact_paths: list[str] = []
    safety_warnings: list[str] = []
    temp_count = 0

    for item in root.rglob("*"):
        try:
            rel = item.relative_to(root)
        except ValueError:
            continue
        name_lower = item.name.lower()
        if item.is_file():
            artifact_paths.append(str(rel).replace("\\", "/"))
            if (
                name_lower.endswith(".tmp")
                or name_lower.endswith(".partial")
                or name_lower.endswith(".incomplete")
                or "incomplete" in name_lower
            ):
                temp_count += 1

            parent_parts = [p.lower() for p in rel.parent.parts]
            is_public = any(p in ("public", "obfuscated") for p in parent_parts)
            if is_public:
                if any(k in name_lower for k in ("exact", "precise", "reviewer_only")):
                    safety_warnings.append(
                        f"Potentially unsafe artifact '{rel}' found in public/obfuscated folder"
                    )
        elif item.is_dir():
            if name_lower in ("public", "obfuscated"):
                if not any(str(rel / "reviewer").replace("\\", "/") == ap for ap in artifact_paths):
                    pass

    return {
        "root_exists": True,
        "root_is_directory": True,
        "root_readable": _check_readable(root),
        "artifact_count": len(artifact_paths),
        "temp_incomplete_count": temp_count,
        "artifact_paths": sorted(artifact_paths)[:50],
        "safety_warnings": safety_warnings,
    }


def _fetch_candidate_states(db_path: Path, run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {
        "pending_review": 0,
        "watch": 0,
        "rejected": 0,
        "approved_for_archive_quote": 0,
        "other": 0,
    }
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT current_state, COUNT(*) FROM candidate_polygons WHERE run_id = ? GROUP BY current_state",
            (run_id,),
        ).fetchall()
    for state, cnt in rows:
        key = str(state) if str(state) in counts else "other"
        counts[key] = int(cnt)
    return counts


def _fetch_queued_candidates(
    db_path: Path,
    run_id: str,
    limit: int = 25,
) -> list[dict]:
    rows: list[dict] = []
    with connect(db_path) as conn:
        import sqlite3
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            """
            SELECT
                cp.candidate_id,
                cp.current_state,
                cp.possible_duplicate,
                cs.candidate_score,
                cs.parent_tile_score
            FROM candidate_polygons cp
            LEFT JOIN candidate_scores cs
                ON cs.candidate_id = cp.candidate_id
                AND cs.run_id = cp.run_id
            WHERE cp.run_id = ?
              AND cp.current_state IN ('pending_review', 'watch')
            ORDER BY
                CASE cp.current_state
                    WHEN 'pending_review' THEN 0
                    WHEN 'watch' THEN 1
                    ELSE 2
                END,
                COALESCE(cs.candidate_score, -1.0) DESC,
                cp.candidate_id ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
    for row in result:
        rows.append({
            "candidate_id": row["candidate_id"],
            "current_state": row["current_state"],
            "possible_duplicate": bool(row["possible_duplicate"]),
            "candidate_score": row["candidate_score"],
            "parent_tile_score": row["parent_tile_score"],
        })
    return rows


def run_reviewer_handoff_package(
    run_id: str,
    artifact_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    fmt: _FormatLiteral = "both",
    limit: int = 25,
) -> dict:
    """Run an offline reviewer handoff package and write deterministic report artifacts.

    Produces under <output_dir>/:
    - reviewer_handoff_package.json
    - reviewer_handoff_package.md
    - SHA256SUMS.txt
    """
    settings = load_settings()
    db_path = settings.db_path

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = Path(".reviewer-handoff").resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    failures: list[str] = []
    run: dict | None = None
    readiness_result: dict | None = None
    artifact_check: dict | None = None
    queued_candidates: list[dict] = []
    candidate_states: dict[str, int] = {}

    try:
        # Step 1: reuse V1.18 readiness logic internally (read-only)
        readiness_result = _build_review_package_readiness_result(
            run_id=run_id,
            artifact_root=artifact_root,
        )
        if readiness_result["status"] == "fail":
            failures.extend(readiness_result.get("failures", []))
        warnings.extend(readiness_result.get("warnings", []))

        # Step 2: fetch run metadata
        run = RunRepository(db_path).fetch_run(run_id)
        if run is None:
            failures.append(f"Run not found: {run_id}")
        else:
            # Step 3: review queue and candidate state counts
            candidate_states = _fetch_candidate_states(db_path, run_id)
            queued_candidates = _fetch_queued_candidates(db_path, run_id, limit=limit)
    except Exception as exc:
        failures.append(f"DB read failed: {exc}")

    # Artifact root scan
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
            if artifact_check["temp_incomplete_count"] > 0:
                warnings.append(
                    f"Artifact root contains {artifact_check['temp_incomplete_count']} incomplete/temp files"
                )
            warnings.extend(artifact_check.get("safety_warnings", []))

    overall_status = "pass"
    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "warn"

    write_json = fmt in ("json", "both")
    write_md = fmt in ("markdown", "both")

    json_path = out_path / "reviewer_handoff_package.json"
    md_path = out_path / "reviewer_handoff_package.md"
    sums_path = out_path / "SHA256SUMS.txt"

    artifact_manifest: list[dict] = []
    if write_json:
        artifact_manifest.append({
            "name": "reviewer_handoff_package.json",
            "sha256": None,
            "note": "self-hash omitted to avoid circular dependency",
        })
    if write_md:
        artifact_manifest.append({
            "name": "reviewer_handoff_package.md",
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
            "name": "reviewer_handoff_package",
        },
        "run_id": run_id,
        "status": overall_status,
        "handoff": {
            "run_summary": {
                "run_id": run_id,
                "run_status": run.get("status") if run else None,
                "aoi_hash": run.get("aoi_hash") if run else None,
                "aoi_path": run.get("aoi_path") if run else None,
                "start_date": run.get("start_date") if run else None,
                "end_date": run.get("end_date") if run else None,
                "legal_gate_decision": (
                    run.get("legal_gate", {}).get("decision") if run else None
                ),
                "source_endpoint_id": run.get("source_endpoint_id") if run else None,
                "source_scene_manifest_hash": run.get("source_scene_manifest_hash") if run else None,
            },
            "readiness": {
                "status": readiness_result["status"] if readiness_result else "unknown",
                "warnings": readiness_result.get("warnings", []) if readiness_result else [],
                "failures": readiness_result.get("failures", []) if readiness_result else [],
            },
            "review_queue_summary": {
                "candidate_count": sum(candidate_states.values()) if candidate_states else 0,
                "review_queue_count": (
                    candidate_states.get("pending_review", 0) + candidate_states.get("watch", 0)
                ),
                "pending_review": candidate_states.get("pending_review", 0),
                "watch": candidate_states.get("watch", 0),
                "rejected": candidate_states.get("rejected", 0),
                "approved_for_archive_quote": candidate_states.get("approved_for_archive_quote", 0),
                "top_candidate_id": (
                    queued_candidates[0]["candidate_id"] if queued_candidates else None
                ),
                "queued_candidate_ids": [c["candidate_id"] for c in queued_candidates],
            },
            "queued_candidates": queued_candidates,
            "artifact_check": artifact_check,
        },
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
                if entry["name"] == "reviewer_handoff_package.md":
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
        sums_lines.append(f"{json_hash_final}  reviewer_handoff_package.json")
    if write_md and md_hash is not None:
        sums_lines.append(f"{md_hash}  reviewer_handoff_package.md")
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
        "# Reviewer Handoff Package",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Run ID: `{payload['run_id']}`",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Run Summary",
        "",
    ]

    run_summary = payload.get("handoff", {}).get("run_summary", {})
    lines.append(f"- Run ID: `{run_summary.get('run_id', '')}`")
    lines.append(f"- Status: `{run_summary.get('run_status', 'unknown')}`")
    if run_summary.get("aoi_hash"):
        lines.append(f"- AOI hash: `{run_summary['aoi_hash']}`")
    if run_summary.get("start_date"):
        lines.append(f"- Start date: `{run_summary['start_date']}`")
    if run_summary.get("end_date"):
        lines.append(f"- End date: `{run_summary['end_date']}`")
    if run_summary.get("legal_gate_decision"):
        lines.append(f"- Legal gate decision: `{run_summary['legal_gate_decision']}`")
    if run_summary.get("source_endpoint_id"):
        lines.append(f"- Source endpoint ID: `{run_summary['source_endpoint_id']}`")
    if run_summary.get("source_scene_manifest_hash"):
        lines.append(f"- Source scene manifest hash: `{run_summary['source_scene_manifest_hash']}`")
    lines.append("")

    readiness = payload.get("handoff", {}).get("readiness", {})
    lines.append("## Readiness")
    lines.append(f"- Status: `{readiness.get('status', 'unknown')}`")
    lines.append("")

    queue = payload.get("handoff", {}).get("review_queue_summary", {})
    lines.append("## Review Queue Summary")
    lines.append(f"- Candidate count: {queue.get('candidate_count', 0)}")
    lines.append(f"- Review queue count: {queue.get('review_queue_count', 0)}")
    lines.append(f"- Pending review: {queue.get('pending_review', 0)}")
    lines.append(f"- Watch: {queue.get('watch', 0)}")
    lines.append(f"- Rejected: {queue.get('rejected', 0)}")
    lines.append(f"- Approved for archive/quote: {queue.get('approved_for_archive_quote', 0)}")
    if queue.get("top_candidate_id"):
        lines.append(f"- Top candidate ID: `{queue['top_candidate_id']}`")
    queued_ids = queue.get("queued_candidate_ids", [])
    if queued_ids:
        lines.append("- Queued candidate IDs:")
        for cid in queued_ids:
            lines.append(f"  - `{cid}`")
    lines.append("")

    candidates = payload.get("handoff", {}).get("queued_candidates", [])
    if candidates:
        lines.append("## Queued Candidates")
        lines.append("")
        for c in candidates:
            lines.append(f"- `{c['candidate_id']}`")
            lines.append(f"  - state: `{c.get('current_state', 'unknown')}`")
            lines.append(f"  - score: {c.get('candidate_score')}")
            lines.append(f"  - possible_duplicate: {c.get('possible_duplicate', False)}")
        lines.append("")

    artifact = payload.get("handoff", {}).get("artifact_check")
    if artifact is not None:
        lines.append("## Artifact Root")
        lines.append(f"- Root exists: `{artifact.get('root_exists', False)}`")
        lines.append(f"- Root is directory: `{artifact.get('root_is_directory', False)}`")
        lines.append(f"- Root readable: `{artifact.get('root_readable', False)}`")
        lines.append(f"- Artifact count: {artifact.get('artifact_count', 0)}")
        lines.append(f"- Temp/incomplete count: {artifact.get('temp_incomplete_count', 0)}")
        artifact_paths = artifact.get("artifact_paths", [])
        if artifact_paths:
            lines.append("- Artifact paths:")
            for p in artifact_paths:
                lines.append(f"  - `{p}`")
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
        "- This handoff package was generated offline.",
        "- No network or GitHub API calls were made.",
        "- No DB mutations were performed.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
