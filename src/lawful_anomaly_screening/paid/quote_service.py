from __future__ import annotations

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
        paid_repository: PaidRepository,
        review_repository: ReviewRepository,
        archive_client: Up42ArchiveClient,
    ) -> None:
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
        if candidate["current_state"] != CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE:
            raise PaidQuoteEligibilityError(
                "candidate must be approved_for_archive_quote before quote creation"
            )

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
        return self.paid_repository.save_quote(quote_record)

    def fetch_quote(
        self,
        *,
        candidate_id: str | None = None,
        provider_quote_id: str | None = None,
    ) -> dict | None:
        return self.paid_repository.fetch_quote(
            candidate_id=candidate_id,
            provider_quote_id=provider_quote_id,
        )

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
        return updated_quote
