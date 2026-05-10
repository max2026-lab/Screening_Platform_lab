from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from .evidence_index_verifier import verify_release_evidence_index

SCHEMA_VERSION = "v1.12.0"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def export_release_evidence_index(
    evidence_root: Path | None = None,
    evidence_list: list[Path] | None = None,
    evidence_list_path: str | None = None,
    output_dir: Path | None = None,
    fmt: Literal["json", "markdown", "both"] = "both",
) -> dict:
    """Verify and export a release evidence index.

    Steps:
    1. Verify all evidence directories using V1.11 logic.
    2. If any verification fails, fail without producing artifacts.
    3. If all pass, write deterministic export artifacts.

    Self-reference rule:
    - release_evidence_index.json is written first and cannot include its own
      final hash without creating a circular dependency. Its own sha256 is set
      to None in the JSON export_artifacts section.
    - release_evidence_index.md is written second and may reference the JSON
      hash from the first write.
    - SHA256SUMS.txt is written last and is the canonical source for the final
      hashes of all export artifacts.
    """
    # Step 1: verify
    verify_result = verify_release_evidence_index(
        evidence_root=evidence_root,
        evidence_list=evidence_list,
        evidence_list_path=evidence_list_path,
        fail_fast=False,
    )

    if verify_result["status"] != "pass":
        return {
            "status": "fail",
            "verify_result": verify_result,
            "output_dir": None,
            "artifacts": [],
            "reasons": verify_result.get("reasons", ["Verification failed"]),
        }

    # Step 2: determine output directory
    if output_dir is None:
        if evidence_root is not None:
            output_dir = evidence_root / "release-evidence-index-export"
        else:
            first_dir = evidence_list[0] if evidence_list else Path.cwd()
            output_dir = first_dir.parent / "release-evidence-index-export"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build deterministic index payload (no wall-clock timestamps)
    index_payload: dict = {
        "schema": {
            "version": SCHEMA_VERSION,
            "name": "release_evidence_index",
        },
        "index_hash": verify_result.get("index_hash"),
        "evidence_root": verify_result.get("evidence_root"),
        "evidence_list": verify_result.get("evidence_list"),
        "evidence_dir_count": verify_result.get("evidence_dir_count", 0),
        "passed_count": verify_result.get("passed_count", 0),
        "failed_count": verify_result.get("failed_count", 0),
        "checked_file_count": verify_result.get("checked_file_count", 0),
        "evidence_directories": [],
        "export_artifacts": [
            {
                "name": "release_evidence_index.json",
                "sha256": None,
                "note": "self-hash omitted to avoid circular dependency",
            },
            {
                "name": "release_evidence_index.md",
                "sha256": None,
                "note": "hash populated after markdown is finalized",
            },
            {
                "name": "SHA256SUMS.txt",
                "sha256": None,
                "note": "canonical hash list for all export artifacts",
            },
        ],
    }

    for single in verify_result.get("results", []):
        dir_entry = {
            "evidence_dir": single.get("evidence_dir"),
            "status": single.get("status"),
            "checked_file_count": single.get("checked_file_count", 0),
            "files": [],
        }
        for file_entry in single.get("files", []):
            dir_entry["files"].append({
                "name": file_entry.get("name"),
                "sha256": file_entry.get("sha256"),
                "sha256_valid": file_entry.get("sha256_valid"),
            })
        index_payload["evidence_directories"].append(dir_entry)

    # Step 3: write JSON (first pass, no artifact hashes)
    json_path = output_dir / "release_evidence_index.json"
    json_path.write_text(_stable_json(index_payload), encoding="utf-8")
    json_hash_first = _sha256_file(json_path)

    # Step 4: write markdown (references first JSON hash to avoid circularity)
    md_path = output_dir / "release_evidence_index.md"
    md_text = _render_index_markdown(index_payload, json_hash=json_hash_first)
    md_path.write_text(md_text, encoding="utf-8")
    md_hash = _sha256_file(md_path)

    # Step 5: rewrite JSON with finalized markdown hash
    for artifact_entry in index_payload["export_artifacts"]:
        if artifact_entry["name"] == "release_evidence_index.md":
            artifact_entry["sha256"] = md_hash
            artifact_entry["note"] = "hash finalized after markdown write"
    json_path.write_text(_stable_json(index_payload), encoding="utf-8")
    json_hash_final = _sha256_file(json_path)

    # Step 6: write SHA256SUMS.txt (canonical source for all final hashes)
    # Note: SHA256SUMS.txt does not include its own hash to avoid self-reference.
    sums_lines = [
        f"{json_hash_final}  release_evidence_index.json",
        f"{md_hash}  release_evidence_index.md",
    ]
    sums_text = "\n".join(sums_lines) + "\n"
    sums_path = output_dir / "SHA256SUMS.txt"
    sums_path.write_text(sums_text, encoding="utf-8")

    # Step 7: compute final artifact hashes for return payload
    artifact_hashes = [
        {"name": json_path.name, "sha256": json_hash_final},
        {"name": md_path.name, "sha256": md_hash},
        {"name": sums_path.name, "sha256": _sha256_file(sums_path)},
    ]

    return {
        "status": "pass",
        "verify_result": verify_result,
        "output_dir": str(output_dir).replace("\\", "/"),
        "artifacts": artifact_hashes,
        "reasons": [],
    }


def _render_index_markdown(payload: dict, *, json_hash: str | None = None) -> str:
    lines = [
        "# Release Evidence Index Export",
        "",
        f"- Schema version: `{payload['schema']['version']}`",
        f"- Index hash: `{payload.get('index_hash', '')}`",
    ]
    if payload.get("evidence_root"):
        lines.append(f"- Evidence root: `{payload['evidence_root']}`")
    if payload.get("evidence_list"):
        lines.append(f"- Evidence list: `{payload['evidence_list']}`")
    lines.extend([
        f"- Evidence dir count: `{payload.get('evidence_dir_count', 0)}`",
        f"- Passed count: `{payload.get('passed_count', 0)}`",
        f"- Failed count: `{payload.get('failed_count', 0)}`",
        f"- Checked file count: `{payload.get('checked_file_count', 0)}`",
        "",
        "## Evidence Directories",
        "",
    ])
    for directory in payload.get("evidence_directories", []):
        lines.append(
            f"- `{directory.get('evidence_dir', '')}`: status=`{directory.get('status', 'fail')}` "
            f"checked={directory.get('checked_file_count', 0)}"
        )
        for file_entry in directory.get("files", []):
            valid = file_entry.get("sha256_valid", False)
            lines.append(
                f"  - `{file_entry.get('name', '')}`: sha256_valid=`{valid}`"
            )
    lines.extend([
        "",
        "## Exported Artifacts",
        "",
    ])
    for artifact in payload.get("export_artifacts", []):
        name = artifact.get("name", "")
        h = artifact.get("sha256")
        note = artifact.get("note", "")
        if h is not None:
            lines.append(f"- `{name}`: sha256=`{h}`")
        elif json_hash and name == "release_evidence_index.json":
            # Include first-pass JSON hash to satisfy "includes hashes" requirement
            # without creating a circular dependency.
            lines.append(f"- `{name}`: sha256=`{json_hash}`")
        else:
            lines.append(f"- `{name}`: sha256=`(see SHA256SUMS.txt)`")
        if note:
            lines.append(f"  - Note: {note}")
    lines.extend([
        "",
        "## Notes",
        "",
        "- This index was exported offline.",
        "- No network or GitHub API calls were made.",
        "- All evidence directories were verified before export.",
        "- Canonical artifact hashes are available in `SHA256SUMS.txt`.",
    ])
    return "\n".join(lines) + "\n"
