"""Legal gate."""

from lawful_anomaly_screening.legal.attestation import normalize_attestation_status
from lawful_anomaly_screening.legal.geofence import normalize_geofence_status

LEGAL_OUTCOME_ALLOWED = "allowed"
LEGAL_OUTCOME_MANUAL_REVIEW_REQUIRED = "manual_review_required"
LEGAL_OUTCOME_BLOCKED = "blocked"


def evaluate_legal_gate(
    attestation_status: str | None = None,
    geofence_status: str | None = None,
) -> str:
    attestation = normalize_attestation_status(attestation_status)
    geofence = normalize_geofence_status(geofence_status)

    if geofence == "hit":
        return LEGAL_OUTCOME_BLOCKED
    if attestation == "present" and geofence == "clear":
        return LEGAL_OUTCOME_ALLOWED
    if attestation in {"missing", "unknown"} or geofence in {"missing", "unknown"}:
        return LEGAL_OUTCOME_MANUAL_REVIEW_REQUIRED
    return LEGAL_OUTCOME_BLOCKED
