VALID_GEOFENCE_STATUSES = ("clear", "hit", "missing", "unknown")


def normalize_geofence_status(status: str | None = None) -> str:
    if status is None:
        return "missing"
    normalized = status.strip().lower()
    if normalized in VALID_GEOFENCE_STATUSES:
        return normalized
    return "unknown"
