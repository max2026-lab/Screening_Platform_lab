from __future__ import annotations

import json
from pathlib import Path


VALID_GEOFENCE_STATUSES = ("clear", "hit", "missing", "unknown")


def normalize_geofence_status(status: str | None = None) -> str:
    if status is None:
        return "missing"
    normalized = status.strip().lower()
    if normalized in VALID_GEOFENCE_STATUSES:
        return normalized
    return "unknown"


def is_valid_geofence_status(status: str | None = None) -> bool:
    if status is None:
        return True
    return status.strip().lower() in VALID_GEOFENCE_STATUSES


def load_geofence_policy(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_geofence_policy(
    aoi_path: Path | str,
    *,
    policy: dict | None = None,
    aoi_hash: str | None = None,
) -> str:
    resolved_policy = policy or {}
    normalized_path = Path(aoi_path).as_posix().lower()
    blocked_hashes = {
        str(candidate).strip().lower()
        for candidate in resolved_policy.get("blocked_aoi_hashes", [])
        if str(candidate).strip()
    }
    if aoi_hash and aoi_hash.lower() in blocked_hashes:
        return "hit"

    blocked_suffixes = [
        str(candidate).replace("\\", "/").lower()
        for candidate in resolved_policy.get("blocked_path_suffixes", [])
        if str(candidate).strip()
    ]
    if any(normalized_path.endswith(candidate) for candidate in blocked_suffixes):
        return "hit"

    default_status = normalize_geofence_status(resolved_policy.get("default_status", "clear"))
    if default_status == "hit":
        return "hit"
    return "clear"
