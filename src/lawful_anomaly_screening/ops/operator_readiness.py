from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Literal

from ..settings import load_settings

SCHEMA_VERSION = "v1.16.0"

_FormatLiteral = Literal["json", "markdown", "both"]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _git_context() -> dict:
    cwd = Path.cwd()
    git_dir = cwd / ".git"
    git_exists = git_dir.is_dir()
    branch = None
    head = None
    if git_exists:
        head_file = git_dir / "HEAD"
        if head_file.is_file():
            head_text = head_file.read_text(encoding="utf-8").strip()
            if head_text.startswith("ref: "):
                branch = head_text[5:].replace("refs/heads/", "")
            else:
                head = head_text
    return {
        "status": "pass",
        "cwd": str(cwd).replace("\\", "/"),
        "git_exists": git_exists,
        "branch": branch,
        "head": head,
    }


def _check_writable(path: Path) -> dict:
    result = {"exists": path.exists(), "writable": False}
    if not path.exists():
        return result
    temp_dir = path / ".readiness-check"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / "probe.txt"
        temp_file.write_text("probe", encoding="utf-8")
        temp_file.unlink()
        temp_dir.rmdir()
        result["writable"] = True
    except OSError:
        result["writable"] = False
    return result


def _check_path(path: Path, label: str) -> dict:
    parent = path.parent if path.suffix else path
    fs = _check_writable(parent)
    return {
        "label": label,
        "path": str(path).replace("\\", "/"),
        "exists": fs["exists"],
        "writable": fs["writable"],
    }


def run_operator_readiness_check(
    output_dir: str | Path | None = None,
    fmt: _FormatLiteral = "both",
) -> dict:
    """Run an offline operator readiness check and write deterministic report artifacts.

    Produces under <output_dir>/:
    - operator_readiness_check.json
    - operator_readiness_check.md
    - SHA256SUMS.txt
    """
    out_path = Path(output_dir) if output_dir else Path(".operator-readiness")
    out_path.mkdir(parents=True, exist_ok=True)

    settings = load_settings()

    # Runtime checks
    runtime_status = "pass"
    runtime_failures: list[str] = []
    try:
        import lawful_anomaly_screening  # noqa: F401
        package_import = "pass"
    except Exception as exc:
        package_import = f"fail: {exc}"
        runtime_status = "fail"
        runtime_failures.append(f"Package import failed: {exc}")

    runtime_check = {
        "status": runtime_status,
        "python_version": sys.version,
        "platform": platform.platform(),
        "package_import": package_import,
    }

    # Git context
    git_check = _git_context()

    # Config / environment
    env_vars = {
        "APP_ENV": os.getenv("APP_ENV"),
        "LAWFUL_ANOMALY_DB_PATH": os.getenv("LAWFUL_ANOMALY_DB_PATH"),
        "ARTIFACT_ROOT": os.getenv("ARTIFACT_ROOT"),
        "CACHE_ROOT": os.getenv("CACHE_ROOT"),
        "MANIFEST_ROOT": os.getenv("MANIFEST_ROOT"),
        "EXPORT_ROOT": os.getenv("EXPORT_ROOT"),
        "REVIEWER_EXACT_COORDINATES_ENABLED": os.getenv("REVIEWER_EXACT_COORDINATES_ENABLED"),
        "EXPORT_UNCONFIRMED_COORDINATE_MODE": os.getenv("EXPORT_UNCONFIRMED_COORDINATE_MODE"),
        "EXPORT_UNCONFIRMED_GRID_KM": os.getenv("EXPORT_UNCONFIRMED_GRID_KM"),
        "UP42_ENABLED": os.getenv("UP42_ENABLED"),
    }

    config_status = "pass"
    config_warnings: list[str] = []
    config_failures: list[str] = []
    for key in ("APP_ENV", "LAWFUL_ANOMALY_DB_PATH"):
        if env_vars[key] is None:
            config_status = "warn"
            config_warnings.append(f"{key} is not set")

    config_check = {
        "status": config_status,
        "vars": {k: v for k, v in env_vars.items()},
    }

    # Filesystem readiness
    paths_to_check: list[tuple[Path, str]] = [
        (settings.db_path, "db_path"),
        (settings.baseline_path, "baseline_path"),
        (settings.logging_config_path, "logging_config_path"),
        (settings.export_precision_path, "export_precision_path"),
        (settings.endpoints_path, "endpoints_path"),
        (settings.geofence_policy_path, "geofence_policy_path"),
        (settings.preprocessing_config_path, "preprocessing_config_path"),
    ]
    for env_key in ("ARTIFACT_ROOT", "CACHE_ROOT", "MANIFEST_ROOT", "EXPORT_ROOT"):
        if val := env_vars[env_key]:
            paths_to_check.append((Path(val), env_key))

    fs_results: list[dict] = []
    fs_status = "pass"
    for p, label in paths_to_check:
        entry = _check_path(p, label)
        fs_results.append(entry)
        if not entry["exists"]:
            fs_status = "fail"
            config_failures.append(f"{label} path does not exist: {entry['path']}")
        elif not entry["writable"]:
            fs_status = "fail"
            config_failures.append(f"{label} path is not writable: {entry['path']}")

    filesystem_check = {
        "status": fs_status,
        "paths": fs_results,
    }

    # Safety config
    safety_status = "pass"
    safety_failures: list[str] = []
    safety_warnings: list[str] = []

    coord_mode = env_vars.get("EXPORT_UNCONFIRMED_COORDINATE_MODE") or ""
    if coord_mode.lower() == "exact":
        safety_status = "fail"
        safety_failures.append("EXPORT_UNCONFIRMED_COORDINATE_MODE is 'exact'; expected obfuscated")

    grid_km_str = env_vars.get("EXPORT_UNCONFIRMED_GRID_KM") or ""
    if grid_km_str:
        try:
            grid_km = float(grid_km_str)
            if grid_km != 1.0:
                safety_status = "warn"
                safety_warnings.append(f"EXPORT_UNCONFIRMED_GRID_KM is {grid_km}; expected 1 unless explicitly pinned")
        except ValueError:
            safety_status = "warn"
            safety_warnings.append(f"EXPORT_UNCONFIRMED_GRID_KM is not a valid number: {grid_km_str}")

    up42_val = env_vars.get("UP42_ENABLED") or ""
    if up42_val.lower() in ("1", "true", "yes", "on"):
        safety_status = "warn"
        safety_warnings.append("UP42_ENABLED is explicitly enabled")

    safety_check = {
        "status": safety_status,
        "export_unconfirmed_coordinate_mode": coord_mode or "not_set",
        "export_unconfirmed_grid_km": grid_km_str or "1 (default)",
        "up42_enabled": up42_val or "not_set",
    }

    # Database / Redis
    db_check = {
        "status": "not_checked",
        "reason": "no existing safe readiness probe",
    }

    # Overall status
    overall_status = "pass"
    all_warnings = config_warnings + safety_warnings
    all_failures = runtime_failures + config_failures + safety_failures
    all_reasons = all_warnings + all_failures

    for check_status in (runtime_check["status"], filesystem_check["status"], safety_check["status"]):
        if check_status == "fail":
            overall_status = "fail"
        elif check_status == "warn" and overall_status == "pass":
            overall_status = "warn"

    write_json = fmt in ("json", "both")
    write_md = fmt in ("markdown", "both")

    json_path = out_path / "operator_readiness_check.json"
    md_path = out_path / "operator_readiness_check.md"
    sums_path = out_path / "SHA256SUMS.txt"

    # Build artifact manifest (no hashes yet to avoid circular dependency)
    artifact_manifest: list[dict] = []
    if write_json:
        artifact_manifest.append({
            "name": "operator_readiness_check.json",
            "sha256": None,
            "note": "self-hash omitted to avoid circular dependency",
        })
    if write_md:
        artifact_manifest.append({
            "name": "operator_readiness_check.md",
            "sha256": None,
            "note": "hash populated after markdown is finalized",
        })
    artifact_manifest.append({
        "name": "SHA256SUMS.txt",
        "sha256": None,
        "note": "canonical hash list for all report artifacts",
    })

    # Build report payload
    report_payload = {
        "schema": {
            "version": SCHEMA_VERSION,
            "name": "operator_readiness_check",
        },
        "status": overall_status,
        "checks": {
            "runtime": runtime_check,
            "git_context": git_check,
            "config_env": config_check,
            "filesystem": filesystem_check,
            "safety": safety_check,
            "database": db_check,
        },
        "warnings": all_warnings,
        "failures": all_failures,
        "reasons": all_reasons,
        "artifact_manifest": artifact_manifest,
    }

    json_hash_first: str | None = None
    json_hash_final: str | None = None
    md_hash: str | None = None

    # Step 1: write JSON first pass (no artifact hashes)
    if write_json:
        json_path.write_text(_stable_json(report_payload), encoding="utf-8")
        json_hash_first = _sha256_file(json_path)

        if write_md:
            # both mode: write markdown, then rewrite JSON with md hash
            md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")
            md_hash = _sha256_file(md_path)

            for entry in report_payload["artifact_manifest"]:
                if entry["name"] == "operator_readiness_check.md":
                    entry["sha256"] = md_hash
                    entry["note"] = "hash finalized after markdown write"
            json_path.write_text(_stable_json(report_payload), encoding="utf-8")
            json_hash_final = _sha256_file(json_path)
        else:
            json_hash_final = json_hash_first
    elif write_md:
        # markdown-only mode: no JSON artifact
        md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")
        md_hash = _sha256_file(md_path)

    # Step 2: write SHA256SUMS.txt (only for JSON/Markdown artifacts, never self)
    sums_lines: list[str] = []
    if write_json and json_hash_final is not None:
        sums_lines.append(f"{json_hash_final}  operator_readiness_check.json")
    if write_md and md_hash is not None:
        sums_lines.append(f"{md_hash}  operator_readiness_check.md")
    sums_text = "\n".join(sorted(sums_lines)) + "\n"
    sums_path.write_text(sums_text, encoding="utf-8")

    # Step 3: compute final artifact hashes for return payload
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
        "warnings": all_warnings,
        "failures": all_failures,
        "reasons": all_reasons,
    }


def _render_report_markdown(payload: dict) -> str:
    lines = [
        "# Operator Readiness Check",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Checks",
        "",
    ]

    checks = payload.get("checks", {})

    # Runtime
    runtime = checks.get("runtime", {})
    lines.append("### Runtime")
    lines.append(f"- Status: `{runtime.get('status', 'unknown')}`")
    lines.append(f"- Python version: `{runtime.get('python_version', '')}`")
    lines.append(f"- Platform: `{runtime.get('platform', '')}`")
    lines.append(f"- Package import: `{runtime.get('package_import', 'unknown')}`")
    lines.append("")

    # Git context
    git = checks.get("git_context", {})
    lines.append("### Git Context")
    lines.append(f"- Status: `{git.get('status', 'unknown')}`")
    lines.append(f"- CWD: `{git.get('cwd', '')}`")
    lines.append(f"- Git exists: `{git.get('git_exists', False)}`")
    if git.get("branch"):
        lines.append(f"- Branch: `{git['branch']}`")
    if git.get("head"):
        lines.append(f"- HEAD: `{git['head']}`")
    lines.append("")

    # Config env
    config = checks.get("config_env", {})
    lines.append("### Config / Environment")
    lines.append(f"- Status: `{config.get('status', 'unknown')}`")
    for key, val in sorted((config.get("vars") or {}).items()):
        display = val if val is not None else "(not set)"
        lines.append(f"- {key}: `{display}`")
    lines.append("")

    # Filesystem
    fs = checks.get("filesystem", {})
    lines.append("### Filesystem")
    lines.append(f"- Status: `{fs.get('status', 'unknown')}`")
    for entry in fs.get("paths", []):
        lines.append(
            f"- `{entry.get('label', '')}`: exists=`{entry.get('exists', False)}` writable=`{entry.get('writable', False)}` path=`{entry.get('path', '')}`"
        )
    lines.append("")

    # Safety
    safety = checks.get("safety", {})
    lines.append("### Safety")
    lines.append(f"- Status: `{safety.get('status', 'unknown')}`")
    lines.append(f"- Export unconfirmed coordinate mode: `{safety.get('export_unconfirmed_coordinate_mode', '')}`")
    lines.append(f"- Export unconfirmed grid km: `{safety.get('export_unconfirmed_grid_km', '')}`")
    lines.append(f"- UP42 enabled: `{safety.get('up42_enabled', '')}`")
    lines.append("")

    # Database
    db = checks.get("database", {})
    lines.append("### Database / Redis")
    lines.append(f"- Status: `{db.get('status', 'unknown')}`")
    if db.get("reason"):
        lines.append(f"- Reason: {db['reason']}")
    lines.append("")

    warnings = payload.get("warnings", [])
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    failures = payload.get("failures", [])
    if failures:
        lines.append("## Failures")
        lines.append("")
        for failure in failures:
            lines.append(f"- {failure}")
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
        "- No DB mutations were performed.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
