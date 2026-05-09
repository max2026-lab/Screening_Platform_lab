from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


REQUIRED_FILES = (
    "full_release_evidence_manifest.json",
    "full_release_evidence_manifest.md",
    "SHA256SUMS.txt",
)

CHECKSUM_TARGET_FILES = (
    "full_release_evidence_manifest.json",
    "full_release_evidence_manifest.md",
)

RECOGNIZABLE_KEYWORDS = (
    "phase",
    "release",
    "evidence",
    "manifest",
    "checks",
    "results",
    "artifacts",
)

MARKDOWN_MARKER_PATTERN = re.compile(
    r"(phase 28|release evidence|full release evidence)",
    re.IGNORECASE,
)
SHA256_LINE_PATTERN = re.compile(r"^([0-9A-Fa-f]{64})  ([^\r\n]+)$")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_utf8_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _build_result(evidence_dir: Path) -> dict:
    return {
        "status": "fail",
        "evidence_dir": str(evidence_dir).replace("\\", "/"),
        "required_files_present": False,
        "json_manifest_valid": False,
        "markdown_manifest_valid": False,
        "sha256sums_valid": False,
        "checked_file_count": 0,
        "files": [
            {
                "name": name,
                "sha256": None,
                "sha256_valid": False,
            }
            for name in CHECKSUM_TARGET_FILES
        ],
        "reasons": [],
    }


def _file_entry(result: dict, name: str) -> dict:
    for entry in result["files"]:
        if entry["name"] == name:
            return entry
    raise KeyError(name)


def _validate_json_manifest(path: Path, result: dict) -> None:
    try:
        manifest_text = _read_utf8_text(path)
    except UnicodeDecodeError as exc:
        result["reasons"].append(f"Invalid UTF-8 JSON manifest: {exc}")
        return
    except OSError as exc:
        result["reasons"].append(f"Failed to read JSON manifest: {exc}")
        return

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        result["reasons"].append(f"Invalid JSON manifest: {exc}")
        return

    if not isinstance(manifest, dict):
        result["reasons"].append("JSON manifest must contain a JSON object")
        return

    if not any(
        any(keyword in key.lower() for keyword in RECOGNIZABLE_KEYWORDS)
        for key in manifest.keys()
        if isinstance(key, str)
    ):
        result["reasons"].append(
            "JSON manifest does not contain recognizable release evidence structure"
        )
        return

    result["json_manifest_valid"] = True


def _validate_markdown_manifest(path: Path, result: dict) -> None:
    try:
        markdown_text = _read_utf8_text(path)
    except UnicodeDecodeError as exc:
        result["reasons"].append(f"Invalid UTF-8 markdown manifest: {exc}")
        return
    except OSError as exc:
        result["reasons"].append(f"Failed to read markdown manifest: {exc}")
        return

    if not markdown_text.strip():
        result["reasons"].append("Markdown manifest is empty")
        return

    if not MARKDOWN_MARKER_PATTERN.search(markdown_text):
        result["reasons"].append(
            "Markdown manifest does not contain recognizable release evidence text"
        )
        return

    result["markdown_manifest_valid"] = True


def _parse_sha256sums(path: Path, result: dict) -> tuple[dict[str, str] | None, bool]:
    try:
        sums_text = _read_utf8_text(path)
    except UnicodeDecodeError as exc:
        result["reasons"].append(f"Invalid UTF-8 SHA256SUMS.txt: {exc}")
        return None, False
    except OSError as exc:
        result["reasons"].append(f"Failed to read SHA256SUMS.txt: {exc}")
        return None, False

    if not sums_text.strip():
        result["reasons"].append("SHA256SUMS.txt is empty")
        return None, False

    entries: dict[str, str] = {}
    checksum_contract_valid = True
    for raw_line in sums_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = SHA256_LINE_PATTERN.match(raw_line)
        if match is None:
            result["reasons"].append(f"Malformed SHA256SUMS line: {raw_line}")
            checksum_contract_valid = False
            continue
        hash_value = match.group(1)
        filename = match.group(2)
        if filename in entries:
            result["reasons"].append(f"Duplicate SHA256SUMS entry for {filename}")
            checksum_contract_valid = False
            continue
        entries[filename] = hash_value.lower()

    unexpected_files = sorted(set(entries) - set(CHECKSUM_TARGET_FILES))
    for unexpected in unexpected_files:
        result["reasons"].append(f"Unexpected checksum entry: {unexpected}")
        checksum_contract_valid = False

    missing_files = sorted(set(CHECKSUM_TARGET_FILES) - set(entries))
    for missing in missing_files:
        result["reasons"].append(f"Missing checksum entry: {missing}")
        checksum_contract_valid = False

    return entries, checksum_contract_valid


def _validate_sha256_entries(
    evidence_dir: Path,
    entries: dict[str, str] | None,
    checksum_contract_valid: bool,
    result: dict,
) -> None:
    if entries is None:
        return

    checked_count = 0
    all_valid = True
    for name in CHECKSUM_TARGET_FILES:
        file_path = evidence_dir / name
        entry = _file_entry(result, name)
        if not file_path.exists() or name not in entries:
            all_valid = False
            continue
        actual_hash = _sha256_file(file_path)
        expected_hash = entries[name]
        entry["sha256"] = actual_hash
        entry["sha256_valid"] = actual_hash == expected_hash
        checked_count += 1
        if actual_hash != expected_hash:
            result["reasons"].append(
                f"SHA256 mismatch for {name}: expected {expected_hash}, got {actual_hash}"
            )
            all_valid = False

    result["checked_file_count"] = checked_count
    if checked_count == len(CHECKSUM_TARGET_FILES) and all_valid and checksum_contract_valid:
        result["sha256sums_valid"] = True


def verify_release_evidence(evidence_dir: str | Path) -> dict:
    resolved_dir = Path(evidence_dir).resolve()
    result = _build_result(resolved_dir)

    if not resolved_dir.exists():
        result["reasons"].append(f"Evidence directory does not exist: {resolved_dir}")
        return result

    if not resolved_dir.is_dir():
        result["reasons"].append(f"Evidence path is not a directory: {resolved_dir}")
        return result

    missing_required_files = [
        name for name in REQUIRED_FILES if not (resolved_dir / name).exists()
    ]
    if missing_required_files:
        for name in missing_required_files:
            result["reasons"].append(f"Missing required file: {name}")
        return result

    result["required_files_present"] = True

    _validate_json_manifest(resolved_dir / "full_release_evidence_manifest.json", result)
    _validate_markdown_manifest(resolved_dir / "full_release_evidence_manifest.md", result)
    entries, checksum_contract_valid = _parse_sha256sums(
        resolved_dir / "SHA256SUMS.txt",
        result,
    )
    _validate_sha256_entries(resolved_dir, entries, checksum_contract_valid, result)

    if (
        result["required_files_present"]
        and result["json_manifest_valid"]
        and result["markdown_manifest_valid"]
        and result["sha256sums_valid"]
    ):
        result["status"] = "pass"
        result["reasons"] = []

    return result


def render_release_evidence_verify_markdown(result: dict) -> str:
    lines = [
        "# Release Evidence Verification",
        "",
        f"- Status: `{result.get('status', 'fail')}`",
        f"- Evidence dir: `{result.get('evidence_dir', '')}`",
        f"- Required files present: `{result.get('required_files_present', False)}`",
        f"- JSON manifest valid: `{result.get('json_manifest_valid', False)}`",
        f"- Markdown manifest valid: `{result.get('markdown_manifest_valid', False)}`",
        f"- SHA256SUMS valid: `{result.get('sha256sums_valid', False)}`",
        f"- Checked file count: `{result.get('checked_file_count', 0)}`",
        "",
        "## Files",
        "",
    ]
    for entry in result.get("files", []):
        lines.append(
            f"- `{entry.get('name', '')}`: sha256_valid=`{entry.get('sha256_valid', False)}` sha256=`{entry.get('sha256')}`"
        )
    lines.extend([
        "",
        "## Reasons",
        "",
    ])
    if result.get("reasons"):
        for reason in result["reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- All checks passed")
    return "\n".join(lines) + "\n"
