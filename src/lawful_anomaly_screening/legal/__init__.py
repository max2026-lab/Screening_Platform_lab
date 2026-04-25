"""Legal gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lawful_anomaly_screening.legal.attestation import (
    is_valid_attestation_status,
    normalize_attestation_status,
)
from lawful_anomaly_screening.legal.geofence import (
    evaluate_geofence_policy,
    is_valid_geofence_status,
    normalize_geofence_status,
)

LEGAL_OUTCOME_ALLOWED = "allowed"
LEGAL_OUTCOME_MANUAL_REVIEW_REQUIRED = "manual_review_required"
LEGAL_OUTCOME_BLOCKED = "blocked"
LEGAL_GATE_DECISION_PASS = "pass"
LEGAL_GATE_DECISION_FAIL = "fail"


@dataclass(frozen=True)
class LegalGateRecord:
    attestation_status: str
    geofence_status: str
    decision: str
    reason: str
    evaluated_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "attestation_status": self.attestation_status,
            "geofence_status": self.geofence_status,
            "decision": self.decision,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
        }


def build_legal_gate_record(
    *,
    attestation_status: str | None = None,
    geofence_status: str | None = None,
    aoi_path: Path | str | None = None,
    aoi_hash: str | None = None,
    geofence_policy: dict | None = None,
) -> LegalGateRecord:
    evaluated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    normalized_attestation = normalize_attestation_status(attestation_status)
    normalized_geofence = normalize_geofence_status(geofence_status)

    if not is_valid_attestation_status(attestation_status):
        return LegalGateRecord(
            attestation_status="invalid",
            geofence_status=normalized_geofence,
            decision=LEGAL_GATE_DECISION_FAIL,
            reason=f"invalid attestation status: {attestation_status}",
            evaluated_at=evaluated_at,
        )
    if normalized_attestation != "present":
        return LegalGateRecord(
            attestation_status=normalized_attestation,
            geofence_status=normalized_geofence,
            decision=LEGAL_GATE_DECISION_FAIL,
            reason=f"attestation status must be present, got {normalized_attestation}",
            evaluated_at=evaluated_at,
        )

    if not is_valid_geofence_status(geofence_status):
        return LegalGateRecord(
            attestation_status=normalized_attestation,
            geofence_status="invalid",
            decision=LEGAL_GATE_DECISION_FAIL,
            reason=f"invalid geofence status: {geofence_status}",
            evaluated_at=evaluated_at,
        )

    if normalized_geofence == "missing":
        return LegalGateRecord(
            attestation_status=normalized_attestation,
            geofence_status=normalized_geofence,
            decision=LEGAL_GATE_DECISION_FAIL,
            reason="geofence status must be provided and clear",
            evaluated_at=evaluated_at,
        )
    if normalized_geofence == "unknown":
        return LegalGateRecord(
            attestation_status=normalized_attestation,
            geofence_status=normalized_geofence,
            decision=LEGAL_GATE_DECISION_FAIL,
            reason="geofence status is unresolved",
            evaluated_at=evaluated_at,
        )
    if normalized_geofence == "hit":
        return LegalGateRecord(
            attestation_status=normalized_attestation,
            geofence_status=normalized_geofence,
            decision=LEGAL_GATE_DECISION_FAIL,
            reason="geofence status indicates blocked AOI",
            evaluated_at=evaluated_at,
        )

    if aoi_path is not None:
        policy_status = evaluate_geofence_policy(
            aoi_path,
            policy=geofence_policy,
            aoi_hash=aoi_hash,
        )
        if policy_status == "hit":
            return LegalGateRecord(
                attestation_status=normalized_attestation,
                geofence_status="hit",
                decision=LEGAL_GATE_DECISION_FAIL,
                reason=f"deterministic geofence policy blocked AOI: {Path(aoi_path).name}",
                evaluated_at=evaluated_at,
            )

    return LegalGateRecord(
        attestation_status=normalized_attestation,
        geofence_status="clear",
        decision=LEGAL_GATE_DECISION_PASS,
        reason="legal gate passed",
        evaluated_at=evaluated_at,
    )


def evaluate_legal_gate(
    attestation_status: str | None = None,
    geofence_status: str | None = None,
) -> str:
    record = build_legal_gate_record(
        attestation_status=attestation_status,
        geofence_status=geofence_status,
    )

    if record.decision == LEGAL_GATE_DECISION_PASS:
        return LEGAL_OUTCOME_ALLOWED
    if record.geofence_status == "hit":
        return LEGAL_OUTCOME_BLOCKED
    return LEGAL_OUTCOME_MANUAL_REVIEW_REQUIRED
