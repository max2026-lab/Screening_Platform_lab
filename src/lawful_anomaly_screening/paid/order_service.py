from __future__ import annotations

from lawful_anomaly_screening.db.repositories.acceptance_repository import AcceptanceRepository
from lawful_anomaly_screening.db.repositories.paid_repository import PaidRepository
from lawful_anomaly_screening.db.repositories.review_repository import (
    CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE,
    ReviewRepository,
)
from lawful_anomaly_screening.exceptions import PaidOrderStateError
from lawful_anomaly_screening.paid.quote_service import QUOTE_STATUS_ORDERED, QUOTE_STATUS_RECEIVED
from lawful_anomaly_screening.paid.up42_archive import Up42ArchiveClient


ORDER_STATUS_SUBMITTED = "order_submitted"
ORDER_STATUS_CONFIRMED = "order_confirmed"
ORDER_STATUS_DELIVERED = "order_delivered"
ORDER_STATUS_CANCELLED = "order_cancelled"

ALLOWED_ORDER_STATUS_TRANSITIONS = {
    ORDER_STATUS_SUBMITTED: {ORDER_STATUS_CONFIRMED, ORDER_STATUS_CANCELLED},
    ORDER_STATUS_CONFIRMED: {ORDER_STATUS_DELIVERED, ORDER_STATUS_CANCELLED},
    ORDER_STATUS_DELIVERED: set(),
    ORDER_STATUS_CANCELLED: set(),
}


class OrderService:
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

    def create_order(
        self,
        *,
        candidate_id: str,
        provider_quote_id: str,
        provider_order_id: str,
        requested_by: str,
    ) -> dict:
        normalized_requested_by = requested_by.strip()
        if not normalized_requested_by:
            raise PaidOrderStateError("paid order creation requires explicit human-triggered action")

        candidate = self.review_repository.fetch_candidate(candidate_id)
        if candidate is None:
            raise PaidOrderStateError(f"candidate not found: {candidate_id}")

        run = self.acceptance_repository.fetch_run(str(candidate["run_id"]))
        quote_record = self.paid_repository.fetch_quote(provider_quote_id=provider_quote_id)
        if quote_record is None:
            raise PaidOrderStateError(f"paid quote not found: {provider_quote_id}")
        if quote_record["candidate_id"] != candidate_id:
            raise PaidOrderStateError("paid quote does not belong to the selected candidate")
        if quote_record["paid_status"] != QUOTE_STATUS_RECEIVED:
            raise PaidOrderStateError(
                f"paid order requires quote_received status, got {quote_record['paid_status']}"
            )

        export_audit_manifest = self.acceptance_repository.fetch_latest_export_audit_manifest(
            str(candidate["run_id"])
        )
        reasons = self._order_gate_failures(
            candidate=candidate,
            run=run,
            export_audit_manifest=export_audit_manifest,
        )
        if reasons:
            raise PaidOrderStateError("; ".join(reasons))

        order_record = self.archive_client.build_order_record(
            quote_record=quote_record,
            provider_order_id=provider_order_id,
            paid_status=ORDER_STATUS_SUBMITTED,
            requested_by=normalized_requested_by,
        )
        saved_order = self.paid_repository.save_order(order_record)
        self.paid_repository.update_quote_status(
            provider_quote_id=provider_quote_id,
            paid_status=QUOTE_STATUS_ORDERED,
        )
        return self._build_order_output(
            saved_order,
            candidate=candidate,
            run=run,
            export_audit_manifest=export_audit_manifest,
        )

    def fetch_order(
        self,
        *,
        candidate_id: str | None = None,
        provider_order_id: str | None = None,
    ) -> dict | None:
        order_record = self.paid_repository.fetch_order(
            candidate_id=candidate_id,
            provider_order_id=provider_order_id,
        )
        if order_record is None:
            return None
        candidate = self.review_repository.fetch_candidate(str(order_record["candidate_id"]))
        run_id = candidate["run_id"] if candidate is not None else order_record.get("run_id")
        run = self.acceptance_repository.fetch_run(str(run_id)) if run_id is not None else None
        export_audit_manifest = (
            self.acceptance_repository.fetch_latest_export_audit_manifest(str(run_id))
            if run_id is not None
            else None
        )
        return self._build_order_output(
            order_record,
            candidate=candidate,
            run=run,
            export_audit_manifest=export_audit_manifest,
        )

    def update_order_status(self, *, provider_order_id: str, paid_status: str) -> dict:
        order_record = self.paid_repository.fetch_order(provider_order_id=provider_order_id)
        if order_record is None:
            raise PaidOrderStateError(f"paid order not found: {provider_order_id}")

        prior_status = order_record["paid_status"]
        if paid_status not in ALLOWED_ORDER_STATUS_TRANSITIONS.get(prior_status, set()):
            raise PaidOrderStateError(
                f"invalid paid order transition: {prior_status} -> {paid_status}"
            )

        updated_order = self.paid_repository.update_order_status(
            provider_order_id=provider_order_id,
            paid_status=paid_status,
        )
        if updated_order is None:
            raise PaidOrderStateError("paid order status was not persisted")
        return self.fetch_order(provider_order_id=provider_order_id)

    @staticmethod
    def _order_gate_failures(
        *,
        candidate: dict,
        run: dict | None,
        export_audit_manifest: dict | None,
    ) -> list[str]:
        reasons = []
        if candidate.get("current_state") != CANDIDATE_STATE_APPROVED_FOR_ARCHIVE_QUOTE:
            reasons.append("candidate review state must remain approved_for_archive_quote")
        if run is None:
            reasons.append("parent run not found for candidate")
        elif (run.get("legal_gate") or {}).get("decision") != "pass":
            reasons.append("legal gate must pass before paid order creation")
        if export_audit_manifest is None:
            reasons.append("export audit manifest must exist before paid order creation")
        return reasons

    def _build_order_output(
        self,
        order_record: dict,
        *,
        candidate: dict | None,
        run: dict | None,
        export_audit_manifest: dict | None,
    ) -> dict:
        gate_reasons = (
            self._order_gate_failures(
                candidate=candidate or {},
                run=run,
                export_audit_manifest=export_audit_manifest,
            )
            if candidate is not None
            else ["candidate not found for paid order record"]
        )
        return {
            **order_record,
            "requested_by": order_record.get("human_triggered_by"),
            "legal_gate": (run or {}).get("legal_gate"),
            "latest_export_audit_manifest_hash": (
                export_audit_manifest.get("audit_manifest_hash") if export_audit_manifest else None
            ),
            "reasons": gate_reasons or ["Paid archive order checks passed"],
        }
