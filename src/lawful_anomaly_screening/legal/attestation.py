VALID_ATTESTATION_STATUSES = ("present", "missing", "unknown")


def normalize_attestation_status(status: str | None = None) -> str:
    if status is None:
        return "missing"
    normalized = status.strip().lower()
    if normalized in VALID_ATTESTATION_STATUSES:
        return normalized
    return "unknown"
