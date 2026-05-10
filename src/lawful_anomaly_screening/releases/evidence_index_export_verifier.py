from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

EXPECTED_SCHEMA_VERSION = "v1.12.0"

SHA256_LINE_PATTERN = re.compile(r"^([0-9A-Fa-f]{64})  ([^\r\n]+)$")

ALLOWED_SHA256SUMS_ARTIFACTS = {
    "release_evidence_index.json",
    "release_evidence_index.md",
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_release_evidence_index_export(export_dir: str | Path) -> dict:
    """Verify a V1.12 release evidence index export directory.

    Validates:
    - SHA256SUMS.txt exists and is well-formed
    - SHA256SUMS.txt does not include itself
    - Each hash in SHA256SUMS.txt matches the corresponding artifact
    - Artifact set matches one of the V1.12 output formats
    - If JSON exists: schema version, required fields, self-hash rule
    - If Markdown exists: required sections and headings
    """
    reasons: list[str] = []
    export_path = Path(export_dir)

    if not export_path.is_dir():
        reasons.append(f"Export directory does not exist: {export_path}")
        return _build_result(False, reasons, export_path)

    sums_path = export_path / "SHA256SUMS.txt"
    if not sums_path.is_file():
        reasons.append("SHA256SUMS.txt is missing")
        return _build_result(False, reasons, export_path)

    sums_text = sums_path.read_text(encoding="utf-8")
    sums_lines = [line for line in sums_text.splitlines() if line.strip()]

    if not sums_lines:
        reasons.append("SHA256SUMS.txt is empty")
        return _build_result(False, reasons, export_path)

    # Check for self-reference
    for line in sums_lines:
        parsed = _parse_sums_line(line)
        if parsed is None:
            continue
        _hash, name = parsed
        if name == "SHA256SUMS.txt":
            reasons.append("SHA256SUMS.txt must not include its own hash")
            return _build_result(False, reasons, export_path)

    # Verify each hash
    entries: list[dict] = []
    for line in sums_lines:
        parsed = _parse_sums_line(line)
        if parsed is None:
            reasons.append(f"Malformed SHA256SUMS line: {line}")
            continue
        h, name = parsed
        if name not in ALLOWED_SHA256SUMS_ARTIFACTS:
            reasons.append(f"Unsupported artifact in SHA256SUMS.txt: {name}")
            continue
        artifact_path = export_path / name
        if not artifact_path.is_file():
            reasons.append(f"Artifact listed in SHA256SUMS but missing on disk: {name}")
            continue
        actual = _sha256_file(artifact_path)
        if actual.lower() != h.lower():
            reasons.append(f"Hash mismatch for {name}: expected {h}, got {actual}")
            continue
        entries.append({"name": name, "sha256": h})

    # Determine expected format from SHA256SUMS lines (not verified entries)
    parsed_names = [
        parsed[1] for line in sums_lines if (parsed := _parse_sums_line(line)) is not None
    ]
    has_json_entry = "release_evidence_index.json" in parsed_names
    has_md_entry = "release_evidence_index.md" in parsed_names

    json_path = export_path / "release_evidence_index.json"
    md_path = export_path / "release_evidence_index.md"

    json_valid = False
    md_valid = False
    json_payload: dict | None = None

    if json_path.exists():
        if not has_json_entry:
            reasons.append("release_evidence_index.json exists but is not listed in SHA256SUMS.txt")
        else:
            json_valid, json_payload, json_reasons = _verify_json(json_path)
            reasons.extend(json_reasons)
    elif has_json_entry:
        reasons.append("release_evidence_index.json is listed in SHA256SUMS.txt but missing on disk")

    if md_path.exists():
        if not has_md_entry:
            reasons.append("release_evidence_index.md exists but is not listed in SHA256SUMS.txt")
        else:
            md_valid, md_reasons = _verify_markdown(md_path)
            reasons.extend(md_reasons)
    elif has_md_entry:
        reasons.append("release_evidence_index.md is listed in SHA256SUMS.txt but missing on disk")

    # Validate format consistency
    if has_json_entry and has_md_entry:
        expected_format = "both"
    elif has_json_entry:
        expected_format = "json"
    elif has_md_entry:
        expected_format = "markdown"
    else:
        expected_format = None
        reasons.append("SHA256SUMS.txt contains no recognized artifact entries")

    # If both JSON and markdown exist, cross-check markdown hash in JSON
    if json_payload is not None and md_path.exists():
        _cross_check_md_hash(json_payload, entries, reasons)

    status = "pass" if not reasons else "fail"
    return _build_result(
        status == "pass",
        reasons,
        export_path,
        format_detected=expected_format,
        sha256sums_entries=entries,
        json_valid=json_valid,
        markdown_valid=md_valid,
    )


def _parse_sums_line(line: str) -> tuple[str, str] | None:
    match = SHA256_LINE_PATTERN.match(line)
    if not match:
        return None
    return match.group(1), match.group(2)


def _verify_json(json_path: Path) -> tuple[bool, dict | None, list[str]]:
    reasons: list[str] = []
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        reasons.append(f"release_evidence_index.json is not valid JSON: {exc}")
        return False, None, reasons

    if not isinstance(payload, dict):
        reasons.append("release_evidence_index.json root must be an object")
        return False, None, reasons

    schema = payload.get("schema", {})
    version = schema.get("version")
    if version != EXPECTED_SCHEMA_VERSION:
        reasons.append(
            f"Schema version mismatch: expected {EXPECTED_SCHEMA_VERSION}, got {version}"
        )

    if not payload.get("index_hash"):
        reasons.append("Missing index_hash in release_evidence_index.json")

    if not isinstance(payload.get("evidence_directories"), list):
        reasons.append("Missing or invalid evidence_directories in release_evidence_index.json")

    artifacts = payload.get("export_artifacts")
    if not isinstance(artifacts, list):
        reasons.append("Missing or invalid export_artifacts in release_evidence_index.json")
        return False, payload, reasons

    json_artifact = next((a for a in artifacts if a.get("name") == "release_evidence_index.json"), None)
    if json_artifact is None:
        reasons.append("export_artifacts missing release_evidence_index.json entry")
    else:
        if json_artifact.get("sha256") is not None:
            reasons.append("release_evidence_index.json self-hash must be null")
        note = json_artifact.get("note", "")
        if "self" not in note.lower() and "circular" not in note.lower():
            reasons.append("release_evidence_index.json self-hash note must mention self-reference or circularity")

    sums_artifact = next((a for a in artifacts if a.get("name") == "SHA256SUMS.txt"), None)
    if sums_artifact is None:
        reasons.append("export_artifacts missing SHA256SUMS.txt entry")

    return (not reasons), payload, reasons


def _verify_markdown(md_path: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    text = md_path.read_text(encoding="utf-8")

    if "# Release Evidence Index Export" not in text:
        reasons.append("Markdown missing '# Release Evidence Index Export' heading")

    if "- Index hash:" not in text:
        reasons.append("Markdown missing Index hash line")

    if "## Evidence Directories" not in text:
        reasons.append("Markdown missing '## Evidence Directories' section")

    if "## Exported Artifacts" not in text:
        reasons.append("Markdown missing '## Exported Artifacts' section")

    return (not reasons), reasons


def _cross_check_md_hash(payload: dict, entries: list[dict], reasons: list[str]) -> None:
    artifacts = payload.get("export_artifacts", [])
    md_artifact = next((a for a in artifacts if a.get("name") == "release_evidence_index.md"), None)
    if md_artifact is None:
        return
    md_hash = md_artifact.get("sha256")
    if md_hash is None:
        return
    sums_md_entry = next((e for e in entries if e["name"] == "release_evidence_index.md"), None)
    if sums_md_entry is None:
        reasons.append("Markdown hash in JSON export_artifacts but SHA256SUMS.txt missing markdown entry")
        return
    if sums_md_entry["sha256"].lower() != md_hash.lower():
        reasons.append(
            f"Markdown hash mismatch: JSON export_artifacts says {md_hash}, "
            f"SHA256SUMS.txt says {sums_md_entry['sha256']}"
        )


def _build_result(
    passed: bool,
    reasons: list[str],
    export_path: Path,
    *,
    format_detected: str | None = None,
    sha256sums_entries: list[dict] | None = None,
    json_valid: bool = False,
    markdown_valid: bool = False,
) -> dict:
    return {
        "status": "pass" if passed else "fail",
        "export_dir": str(export_path).replace("\\", "/"),
        "format_detected": format_detected,
        "sha256sums_valid": True if passed else not any("SHA256SUMS" in r for r in reasons),
        "json_valid": json_valid,
        "markdown_valid": markdown_valid,
        "sha256sums_entries": sha256sums_entries or [],
        "reasons": reasons,
    }
