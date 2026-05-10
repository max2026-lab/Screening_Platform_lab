from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = "v1.17.0"

_FormatLiteral = Literal["json", "markdown", "both"]

_SHA256_LINE_PATTERN = re.compile(r"^([0-9A-Fa-f]{64})  ([^\r\n]+)$")
_MAX_SAME_DIR_VERIFY_BYTES = 25 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _check_readable(path: Path) -> bool:
    try:
        return os.access(path, os.R_OK)
    except OSError:
        return False


def _scan_directory(root: Path) -> dict:
    expected_folders = ["cache", "manifests", "artifacts", "exports", "logs", "data"]
    folder_presence: dict[str, bool] = {}
    for folder in expected_folders:
        folder_path = root / folder
        folder_presence[folder] = folder_path.is_dir()

    json_count = 0
    md_count = 0
    sha_count = 0
    zip_count = 0
    sqlite_count = 0
    temp_count = 0
    sha_files: list[str] = []
    malformed_checksum_lines: list[str] = []
    nonlocal_checksum_refs: list[str] = []
    hash_mismatches: list[str] = []
    missing_checksum_targets: list[str] = []
    safety_warnings: list[str] = []

    export_folders: list[Path] = []

    for item in root.rglob("*"):
        try:
            rel = item.relative_to(root)
        except ValueError:
            continue
        name_lower = item.name.lower()
        if item.is_file():
            if name_lower.endswith(".json"):
                json_count += 1
            elif name_lower.endswith(".md"):
                md_count += 1
            elif name_lower.endswith(".zip"):
                zip_count += 1
            elif name_lower.endswith(".sqlite3") or name_lower.endswith(".db"):
                sqlite_count += 1
            elif name_lower == "sha256sums.txt":
                sha_count += 1
                sha_files.append(str(rel).replace("\\", "/"))
                _process_sha256sums(
                    item, root, rel,
                    malformed_checksum_lines,
                    nonlocal_checksum_refs,
                    hash_mismatches,
                    missing_checksum_targets,
                )

            if (
                name_lower.endswith(".tmp")
                or name_lower.endswith(".partial")
                or name_lower.endswith(".incomplete")
                or "incomplete" in name_lower
            ):
                temp_count += 1

            # Safety signal detection
            parent_parts = [p.lower() for p in rel.parent.parts]
            is_public = any(p in ("public", "obfuscated") for p in parent_parts)
            if is_public:
                if any(k in name_lower for k in ("exact", "precise", "reviewer_only")):
                    safety_warnings.append(
                        f"Potentially unsafe artifact '{rel}' found in public/obfuscated export folder"
                    )
        elif item.is_dir():
            if name_lower in ("public", "obfuscated"):
                export_folders.append(item)
            if name_lower in ("reviewer", "reviewer_only"):
                export_folders.append(item)

    # Warn if exports folder exists but no public/obfuscated/reviewer subfolders found
    if (root / "exports").is_dir() and not any(
        p.name.lower() in ("public", "obfuscated", "reviewer", "reviewer_only")
        for p in export_folders
    ):
        safety_warnings.append(
            "exports folder exists but no public/obfuscated/reviewer subfolders detected"
        )

    return {
        "folder_presence": folder_presence,
        "file_counts": {
            "json": json_count,
            "markdown": md_count,
            "sha256sums_txt": sha_count,
            "zip": zip_count,
            "sqlite": sqlite_count,
            "temp_incomplete": temp_count,
        },
        "sha256sums_files": sorted(sha_files),
        "malformed_checksum_lines": malformed_checksum_lines,
        "nonlocal_checksum_refs": nonlocal_checksum_refs,
        "hash_mismatches": hash_mismatches,
        "missing_checksum_targets": missing_checksum_targets,
        "safety_warnings": safety_warnings,
    }


def _process_sha256sums(
    sha_path: Path,
    root: Path,
    rel: Path,
    malformed_lines: list[str],
    nonlocal_refs: list[str],
    hash_mismatches: list[str],
    missing_targets: list[str],
) -> None:
    try:
        text = sha_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        match = _SHA256_LINE_PATTERN.match(line_stripped)
        if not match:
            malformed_lines.append(f"{rel}: {line_stripped}")
            continue
        expected_hash = match.group(1)
        target_name = match.group(2)
        # Same-directory check: filename must have no path separators or parent refs
        target_path = Path(target_name)
        if (
            len(target_path.parts) != 1
            or target_path.is_absolute()
            or ".." in target_path.parts
        ):
            nonlocal_refs.append(
                f"{rel}: nonlocal checksum reference not followed: {target_name}"
            )
            continue
        target_file = sha_path.parent / target_name
        try:
            target_file.relative_to(root)
        except ValueError:
            nonlocal_refs.append(
                f"{rel}: nonlocal checksum reference not followed: {target_name}"
            )
            continue
        if not target_file.is_file():
            missing_targets.append(f"{rel} references missing target: {target_name}")
            continue
        size = target_file.stat().st_size
        if size > _MAX_SAME_DIR_VERIFY_BYTES:
            # too large, skip verification
            continue
        actual_hash = _sha256_file(target_file)
        if actual_hash.lower() != expected_hash.lower():
            hash_mismatches.append(
                f"{rel}: hash mismatch for {target_name}: expected {expected_hash}, got {actual_hash}"
            )


def run_operator_artifact_inventory(
    root: str | Path,
    output_dir: str | Path | None = None,
    fmt: _FormatLiteral = "both",
) -> dict:
    """Run an offline operator artifact inventory and write deterministic report artifacts.

    Produces under <output_dir>/:
    - operator_artifact_inventory.json
    - operator_artifact_inventory.md
    - SHA256SUMS.txt
    """
    root_path = Path(root).resolve()

    # Root checks (must happen before any mkdir to avoid creating the root)
    root_exists = root_path.exists()
    root_is_dir = root_path.is_dir()
    root_readable = root_exists and root_is_dir and _check_readable(root_path)

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = root_path / ".operator-artifact-inventory"
    out_path.mkdir(parents=True, exist_ok=True)

    root_failures: list[str] = []
    root_warnings: list[str] = []

    if not root_exists:
        root_failures.append(f"Root path does not exist: {root_path}")
    elif not root_is_dir:
        root_failures.append(f"Root path is not a directory: {root_path}")
    elif not root_readable:
        root_failures.append(f"Root path is not readable: {root_path}")

    scan = _scan_directory(root_path) if root_exists and root_is_dir and root_readable else {}

    malformed_checksum_lines = scan.get("malformed_checksum_lines", [])
    nonlocal_checksum_refs = scan.get("nonlocal_checksum_refs", [])
    hash_mismatches = scan.get("hash_mismatches", [])
    missing_checksum_targets = scan.get("missing_checksum_targets", [])
    safety_warnings = scan.get("safety_warnings", [])

    warnings = root_warnings + malformed_checksum_lines + nonlocal_checksum_refs + safety_warnings
    failures = root_failures + hash_mismatches + missing_checksum_targets

    overall_status = "pass"
    if failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "warn"

    write_json = fmt in ("json", "both")
    write_md = fmt in ("markdown", "both")

    json_path = out_path / "operator_artifact_inventory.json"
    md_path = out_path / "operator_artifact_inventory.md"
    sums_path = out_path / "SHA256SUMS.txt"

    # Build artifact manifest without hashes to avoid circular dependency
    artifact_manifest: list[dict] = []
    if write_json:
        artifact_manifest.append({
            "name": "operator_artifact_inventory.json",
            "sha256": None,
            "note": "self-hash omitted to avoid circular dependency",
        })
    if write_md:
        artifact_manifest.append({
            "name": "operator_artifact_inventory.md",
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
            "name": "operator_artifact_inventory",
        },
        "root": str(root_path).replace("\\", "/"),
        "status": overall_status,
        "checks": {
            "root_exists": root_exists,
            "root_is_directory": root_is_dir,
            "root_readable": root_readable,
            "folder_presence": scan.get("folder_presence", {}),
            "file_counts": scan.get("file_counts", {}),
            "sha256sums_files": scan.get("sha256sums_files", []),
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
                if entry["name"] == "operator_artifact_inventory.md":
                    entry["sha256"] = md_hash
                    entry["note"] = "hash finalized after markdown write"
            json_path.write_text(_stable_json(report_payload), encoding="utf-8")
            json_hash_final = _sha256_file(json_path)
        else:
            json_hash_final = json_hash_first
    elif write_md:
        md_path.write_text(_render_report_markdown(report_payload), encoding="utf-8")
        md_hash = _sha256_file(md_path)

    # SHA256SUMS.txt for generated JSON/Markdown only, never self
    sums_lines: list[str] = []
    if write_json and json_hash_final is not None:
        sums_lines.append(f"{json_hash_final}  operator_artifact_inventory.json")
    if write_md and md_hash is not None:
        sums_lines.append(f"{md_hash}  operator_artifact_inventory.md")
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
        "# Operator Artifact Inventory",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Root: `{payload['root']}`",
        f"- Overall status: `{payload['status']}`",
        "",
        "## Checks",
        "",
        f"- Root exists: `{payload['checks']['root_exists']}`",
        f"- Root is directory: `{payload['checks']['root_is_directory']}`",
        f"- Root readable: `{payload['checks']['root_readable']}`",
        "",
        "### Folder Presence",
        "",
    ]
    for folder, present in sorted((payload["checks"].get("folder_presence") or {}).items()):
        lines.append(f"- `{folder}`: {present}")
    lines.append("")

    lines.append("### File Counts")
    lines.append("")
    for label, count in sorted((payload["checks"].get("file_counts") or {}).items()):
        lines.append(f"- {label}: {count}")
    lines.append("")

    sha_files = payload["checks"].get("sha256sums_files", [])
    if sha_files:
        lines.append("### SHA256SUMS.txt Files")
        lines.append("")
        for path in sha_files:
            lines.append(f"- `{path}`")
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
        "- This inventory was generated offline.",
        "- No network or GitHub API calls were made.",
        "- No DB access was required.",
        "- No source files were modified.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
