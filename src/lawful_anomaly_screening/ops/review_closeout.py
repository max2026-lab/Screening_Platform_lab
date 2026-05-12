from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Literal

from ..db.repositories.run_repository import RunRepository
from ..db.sqlite import connect
from ..domain.candidate_flags import compute_landscape_scale_fields
from ..settings import load_settings

SCHEMA_VERSION = "v1.20.0"

_FormatLiteral = Literal["json", "markdown", "both"]

_UNRESOLVED_STATES = {"pending_review", "watch"}
_APPROVED_STATES = {"approved_for_archive_quote"}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _fetch_candidate_state_counts(db_path: Path, run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT current_state, COUNT(*) FROM candidate_polygons WHERE run_id = ? GROUP BY current_state",
            (run_id,),
        ).fetchall()
    for state, cnt in rows:
        counts[str(state)] = int(cnt)
    return counts


def _fetch_unresolved_candidates(db_path: Path, run_id: str, limit: int = 50) -> list[dict]:
    rows: list[dict] = []
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            """
            SELECT candidate_id, current_state, possible_duplicate, area_m2
            FROM candidate_polygons
            WHERE run_id = ? AND current_state IN ('pending_review', 'watch')
            ORDER BY candidate_id ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
    for row in result:
        record = {
            "candidate_id": row["candidate_id"],
            "current_state": row["current_state"],
            "possible_duplicate": bool(row["possible_duplicate"]),
        }
        record.update(compute_landscape_scale_fields(float(row["area_m2"])))
        rows.append(record)
    return rows


def _fetch_approved_candidates(db_path: Path, run_id: str) -> list[dict]:
    rows: list[dict] = []
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            """
            SELECT cp.candidate_id, cp.possible_duplicate, cp.area_m2, cs.candidate_score
            FROM candidate_polygons cp
            LEFT JOIN candidate_scores cs
                ON cs.candidate_id = cp.candidate_id
                AND cs.run_id = cp.run_id
            WHERE cp.run_id = ? AND cp.current_state = 'approved_for_archive_quote'
            ORDER BY cp.candidate_id ASC
            """,
            (run_id,),
        ).fetchall()
    for row in result:
        record = {
            "candidate_id": row["candidate_id"],
            "possible_duplicate": bool(row["possible_duplicate"]),
            "candidate_score": row["candidate_score"],
        }
        record.update(compute_landscape_scale_fields(float(row["area_m2"])))
        rows.append(record)
    return rows


def _fetch_export_record_count(db_path: Path, run_id: str) -> int:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM export_records WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _fetch_review_action_count(db_path: Path, run_id: str) -> int:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM review_actions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def run_review_closeout_package(
    run_id: str,
    output_dir: str | Path | None = None,
    fmt: _FormatLiteral = "both",
    require_all_resolved: bool = False,
) -> dict:
    """Run an offline review closeout package and write deterministic report artifacts.

    Produces under <output_dir>/:
    - review_closeout_package.json
    - review_closeout_package.md
    - SHA256SUMS.txt
    """
    settings = load_settings()
    db_path = settings.db_path

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = Path(".review-closeout").resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    failures: list[str] = []
    run: dict | None = None

    try:
        run_repo = RunRepository(db_path)
        run = run_repo.fetch_run(run_id)
    except Exception as exc:
        failures.append(f"DB read failed: {exc}")

    if run is None:
        failures.append(f"Run not found: {run_id}")
    else:
        legal_gate = run.get("legal_gate", {})
        legal_decision = legal_gate.get("decision")
        if legal_decision is None:
            warnings.append("Legal gate decision is missing")
        elif legal_decision != "pass":
            failures.append(f"Legal gate decision is '{legal_decision}'; expected 'pass'")

    candidate_counts: dict[str, int] = {}
    unresolved_candidates: list[dict] = []
    approved_candidates: list[dict] = []
    export_record_count = 0
    review_action_count = 0

    if run is not None:
        try:
            candidate_counts = _fetch_candidate_state_counts(db_path, run_id)
            unresolved_candidates = _fetch_unresolved_candidates(db_path, run_id)
            approved_candidates = _fetch_approved_candidates(db_path, run_id)
            export_record_count = _fetch_export_record_count(db_path, run_id)
            review_action_count = _fetch_review_action_count(db_path, run_id)
        except Exception as exc:
            failures.append(f"DB read failed: {exc}")

    total_candidates = sum(candidate_counts.values())
    unresolved_count = sum(candidate_counts.get(s, 0) for s in _UNRESOLVED_STATES)
    approved_count = sum(candidate_counts.get(s, 0) for s in _APPROVED_STATES)
    rejected_count = candidate_counts.get("rejected", 0)
    watch_count = candidate_counts.get("watch", 0)
    pending_count = candidate_counts.get("pending_review", 0)
    other_count = total_candidates - unresolved_count - approved_count - rejected_count

    # Decision completeness
    if unresolved_count > 0:
        if require_all_resolved:
            failures.append(
                f"Unresolved candidates exist ({unresolved_count}); "
                "--require-all-resolved is set"
            )
        else:
            warnings.append(f"Unresolved candidates exist: {unresolved_count}")

    # Export readiness signals
    if total_candidates > 0 and approved_count == 0:
        warnings.append("Run has candidates but none are approved for export")

    for cand in approved_candidates:
        if cand["possible_duplicate"]:
            warnings.append(
                f"Approved candidate {cand['candidate_id']} has possible_duplicate flag"
            )

    if export_record_count > 0:
        warnings.append(f"Previous export records exist for run: {export_record_count}")

    overall_status = "pass"
    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "warn"

    write_json = fmt in ("json", "both")
    write_md = fmt in ("markdown", "both")

    json_path = out_path / "review_closeout_package.json"
    md_path = out_path / "review_closeout_package.md"
    sums_path = out_path / "SHA256SUMS.txt"

    artifact_manifest: list[dict] = []
    if write_json:
        artifact_manifest.append({
            "name": "review_closeout_package.json",
            "sha256": None,
            "note": "self-hash omitted to avoid circular dependency",
        })
    if write_md:
        artifact_manifest.append({
            "name": "review_closeout_package.md",
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
            "name": "review_closeout_package",
        },
        "run_id": run_id,
        "status": overall_status,
        "closeout": {
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
            "review_summary": {
                "total_candidates": total_candidates,
                "pending_review": pending_count,
                "watch": watch_count,
                "rejected": rejected_count,
                "approved_for_archive_quote": approved_count,
                "other": other_count,
                "review_action_count": review_action_count,
            },
            "unresolved_candidates": unresolved_candidates,
            "approved_candidates": [
                {
                    "candidate_id": c["candidate_id"],
                    "possible_duplicate": c["possible_duplicate"],
                    "candidate_score": c["candidate_score"],
                    "is_landscape_scale": c["is_landscape_scale"],
                    "landscape_scale_threshold_m2": c["landscape_scale_threshold_m2"],
                    "landscape_scale_area_ha": c["landscape_scale_area_ha"],
                }
                for c in approved_candidates
            ],
            "export_readiness": {
                "export_record_count": export_record_count,
                "approved_count": approved_count,
            },
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
                if entry["name"] == "review_closeout_package.md":
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
        sums_lines.append(f"{json_hash_final}  review_closeout_package.json")
    if write_md and md_hash is not None:
        sums_lines.append(f"{md_hash}  review_closeout_package.md")
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
        "# Review Closeout Package",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Run ID: `{payload['run_id']}`",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Run Summary",
        "",
    ]

    run_summary = payload.get("closeout", {}).get("run_summary", {})
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

    review = payload.get("closeout", {}).get("review_summary", {})
    lines.append("## Review Summary")
    lines.append(f"- Total candidates: {review.get('total_candidates', 0)}")
    lines.append(f"- Pending review: {review.get('pending_review', 0)}")
    lines.append(f"- Watch: {review.get('watch', 0)}")
    lines.append(f"- Rejected: {review.get('rejected', 0)}")
    lines.append(f"- Approved for archive/quote: {review.get('approved_for_archive_quote', 0)}")
    lines.append(f"- Other: {review.get('other', 0)}")
    lines.append(f"- Review actions: {review.get('review_action_count', 0)}")
    lines.append("")

    unresolved = payload.get("closeout", {}).get("unresolved_candidates", [])
    if unresolved:
        lines.append("## Unresolved Candidates")
        lines.append("")
        for c in unresolved:
            lines.append(f"- `{c['candidate_id']}` (state: `{c['current_state']}`)")
        lines.append("")

    approved = payload.get("closeout", {}).get("approved_candidates", [])
    if approved:
        lines.append("## Approved Candidates")
        lines.append("")
        for c in approved:
            lines.append(f"- `{c['candidate_id']}`")
            if c.get("possible_duplicate"):
                lines.append("  - possible_duplicate: true")
        lines.append("")

    export_ready = payload.get("closeout", {}).get("export_readiness", {})
    lines.append("## Export Readiness")
    lines.append(f"- Approved count: {export_ready.get('approved_count', 0)}")
    lines.append(f"- Existing export records: {export_ready.get('export_record_count', 0)}")
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
        "- This closeout package was generated offline.",
        "- No network or GitHub API calls were made.",
        "- No DB mutations were performed.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
