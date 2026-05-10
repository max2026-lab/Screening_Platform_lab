from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .evidence_verifier import verify_release_evidence

REQUIRED_FILES = (
    "full_release_evidence_manifest.json",
    "full_release_evidence_manifest.md",
    "SHA256SUMS.txt",
)


def _is_evidence_dir(path: Path) -> bool:
    return path.is_dir() and all((path / name).exists() for name in REQUIRED_FILES)


def discover_evidence_dirs(root: Path) -> list[Path]:
    """Recursively discover evidence directories under root."""
    dirs: list[Path] = []
    for candidate in root.rglob("*"):
        if _is_evidence_dir(candidate):
            dirs.append(candidate)
    # Deterministic sort by normalized path string
    return sorted(dirs, key=lambda p: str(p.resolve()).replace("\\", "/").lower())


def load_evidence_list(list_path: Path) -> list[Path]:
    """Load evidence directory paths from a text file."""
    text = list_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    paths: list[Path] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        paths.append(Path(stripped))
    return paths


def _compute_index_hash(results: list[dict]) -> str:
    """Compute deterministic index hash from results."""
    payload: dict = {
        "results": [],
    }
    for result in results:
        entry: dict = {
            "evidence_dir": str(result.get("evidence_dir", "")).replace("\\", "/").lower(),
            "status": result.get("status", "fail"),
            "checked_file_count": result.get("checked_file_count", 0),
            "files": [],
        }
        for file_entry in result.get("files", []):
            entry["files"].append({
                "name": file_entry.get("name", ""),
                "sha256": file_entry.get("sha256"),
            })
        payload["results"].append(entry)
    hash_input = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


def verify_release_evidence_index(
    evidence_root: Path | None = None,
    evidence_list: list[Path] | None = None,
    evidence_list_path: str | None = None,
    fail_fast: bool = False,
) -> dict:
    """Verify multiple release evidence directories."""
    result: dict = {
        "status": "fail",
        "evidence_root": None,
        "evidence_list": None,
        "evidence_dir_count": 0,
        "passed_count": 0,
        "failed_count": 0,
        "checked_file_count": 0,
        "fail_fast": fail_fast,
        "index_hash": None,
        "results": [],
        "reasons": [],
    }

    dirs: list[Path] = []
    if evidence_list is not None:
        dirs = evidence_list
        result["evidence_list"] = evidence_list_path
    elif evidence_root is not None:
        dirs = discover_evidence_dirs(evidence_root)
        result["evidence_root"] = str(evidence_root).replace("\\", "/")

    result["evidence_dir_count"] = len(dirs)

    if not dirs:
        result["reasons"].append("No evidence directories found")
        return result

    # Check for duplicates in evidence-list mode
    seen: set[str] = set()
    for d in dirs:
        normalized = str(d.resolve()).replace("\\", "/").lower()
        if normalized in seen:
            result["reasons"].append(
                f"Duplicate evidence directory: {d}"
            )
            return result
        seen.add(normalized)

    checked_file_count = 0
    for d in dirs:
        single_result = verify_release_evidence(d)
        result["results"].append(single_result)
        checked_file_count += single_result.get("checked_file_count", 0)
        if single_result["status"] == "pass":
            result["passed_count"] += 1
        else:
            result["failed_count"] += 1
            if fail_fast:
                break

    result["checked_file_count"] = checked_file_count
    result["index_hash"] = _compute_index_hash(result["results"])

    if result["failed_count"] == 0:
        result["status"] = "pass"
        result["reasons"] = []
    else:
        result["reasons"].append(
            f"{result['failed_count']} release evidence verification failed"
        )

    return result


def render_release_evidence_index_markdown(result: dict) -> str:
    lines = [
        "# Release Evidence Index Verification",
        "",
        f"- Status: `{result.get('status', 'fail')}`",
    ]
    if result.get("evidence_root"):
        lines.append(f"- Evidence root: `{result['evidence_root']}`")
    if result.get("evidence_list"):
        lines.append(f"- Evidence list: `{result['evidence_list']}`")
    lines.extend([
        f"- Evidence dir count: `{result.get('evidence_dir_count', 0)}`",
        f"- Passed count: `{result.get('passed_count', 0)}`",
        f"- Failed count: `{result.get('failed_count', 0)}`",
        f"- Checked file count: `{result.get('checked_file_count', 0)}`",
        f"- Index hash: `{result.get('index_hash', '')}`",
        f"- Fail fast: `{result.get('fail_fast', False)}`",
        "",
        "## Results",
        "",
    ])
    for single in result.get("results", []):
        lines.append(
            f"- `{single.get('evidence_dir', '')}`: status=`{single.get('status', 'fail')}` "
            f"checked={single.get('checked_file_count', 0)}"
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
