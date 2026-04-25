from __future__ import annotations

from lawful_anomaly_screening.db.repositories.acceptance_repository import AcceptanceRepository
from lawful_anomaly_screening.db.repositories.paid_repository import PaidRepository
from lawful_anomaly_screening.db.repositories.review_repository import (
    CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE,
    ReviewRepository,
)
from lawful_anomaly_screening.exceptions import PaidQuoteEligibilityError, PaidQuoteStateError
from lawful_anomaly_screening.paid.up42_archive import Up42ArchiveClient


QUOTE_STATUS_RECEIVED = "quote_received"
QUOTE_STATUS_ORDERED = "quote_ordered"
QUOTE_STATUS_EXPIRED = "quote_expired"

ALLOWED_QUOTE_STATUS_TRANSITIONS = {
    QUOTE_STATUS_RECEIVED: {QUOTE_STATUS_ORDERED, QUOTE_STATUS_EXPIRED},
    QUOTE_STATUS_ORDERED: set(),
    QUOTE_STATUS_EXPIRED: set(),
}


class QuoteService:
    def __init__(
        self,
        *,
        acceptance_repository: AcceptanceRepository,
        paid_repository: PaidRepository,
        review_repository: ReviewRepository,
        archive_client: Up42ArchiveClient,
    ) -> None:
        self.acceptance_repository = acceptance_repository
        self.paid_repository = paid_repository
        self.review_repository = review_repository
        self.archive_client = archive_client

    def create_quote(
        self,
        *,
        candidate_id: str,
        provider_quote_id: str,
        amount: float,
        credits: float,
        currency: str,
        eula_reference: str,
        project_id: str | None = None,
    ) -> dict:
        candidate = self.review_repository.fetch_candidate(candidate_id)
        if candidate is None:
            raise PaidQuoteEligibilityError(f"candidate not found: {candidate_id}")

        run = self.acceptance_repository.fetch_run(str(candidate["run_id"]))
        reasons = self._quote_gate_failures(candidate=candidate, run=run)
        if reasons:
            raise PaidQuoteEligibilityError("; ".join(reasons))

        quote_record = self.archive_client.build_quote_record(
            candidate=candidate,
            provider_quote_id=provider_quote_id,
            amount=amount,
            credits=credits,
            currency=currency,
            eula_reference=eula_reference,
            project_id=project_id,
            paid_status=QUOTE_STATUS_RECEIVED,
        )
        saved_quote = self.paid_repository.save_quote(quote_record)
        return self._build_quote_output(saved_quote, candidate=candidate, run=run)

    def fetch_quote(
        self,
        *,
        candidate_id: str | None = None,
        provider_quote_id: str | None = None,
    ) -> dict | None:
        quote_record = self.paid_repository.fetch_quote(
            candidate_id=candidate_id,
            provider_quote_id=provider_quote_id,
        )
        if quote_record is None:
            return None
        candidate = self.review_repository.fetch_candidate(str(quote_record["candidate_id"]))
        run_id = candidate["run_id"] if candidate is not None else quote_record.get("run_id")
        run = self.acceptance_repository.fetch_run(str(run_id)) if run_id is not None else None
        return self._build_quote_output(quote_record, candidate=candidate, run=run)

    def update_quote_status(self, *, provider_quote_id: str, paid_status: str) -> dict:
        quote_record = self.paid_repository.fetch_quote(provider_quote_id=provider_quote_id)
        if quote_record is None:
            raise PaidQuoteStateError(f"paid quote not found: {provider_quote_id}")

        prior_status = quote_record["paid_status"]
        if paid_status not in ALLOWED_QUOTE_STATUS_TRANSITIONS.get(prior_status, set()):
            raise PaidQuoteStateError(
                f"invalid paid quote transition: {prior_status} -> {paid_status}"
            )

        updated_quote = self.paid_repository.update_quote_status(
            provider_quote_id=provider_quote_id,
            paid_status=paid_status,
        )
        if updated_quote is None:
            raise PaidQuoteStateError("paid quote status was not persisted")
        return self.fetch_quote(provider_quote_id=provider_quote_id)

    @staticmethod
    def _quote_gate_failures(*, candidate: dict, run: dict | None) -> list[str]:
        reasons = []
        if candidate.get("current_state") != CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE:
            reasons.append("candidate review state must be approved_for_archive_quote")
        if run is None:
            reasons.append("parent run not found for candidate")
        elif (run.get("legal_gate") or {}).get("decision") != "pass":
            reasons.append("legal gate must pass before paid quote creation")
        return reasons

    def _build_quote_output(
        self,
        quote_record: dict,
        *,
        candidate: dict | None,
        run: dict | None,
    ) -> dict:
        gate_reasons = (
            self._quote_gate_failures(candidate=candidate or {}, run=run)
            if candidate is not None
            else ["candidate not found for paid quote record"]
        )
        return {
            **quote_record,
            "quote_id": quote_record["provider_quote_id"],
            "current_review_state": candidate.get("current_state") if candidate is not None else None,
            "legal_gate": (run or {}).get("legal_gate"),
            "paid_escalation_ready": len(gate_reasons) == 0,
            "reasons": gate_reasons or ["Paid archive escalation checks passed"],
        }
