from __future__ import annotations


UP42_PROVIDER = "up42"
ARCHIVE_MODE_ARCHIVE_FIRST = "archive_first"


class Up42ArchiveClient:
    def __init__(self, provider: str = UP42_PROVIDER) -> None:
        self.provider = provider

    def build_quote_record(
        self,
        *,
        candidate: dict,
        provider_quote_id: str,
        amount: float,
        credits: float,
        currency: str,
        eula_reference: str,
        project_id: str | None,
        paid_status: str,
    ) -> dict:
        return {
            "candidate_id": candidate["candidate_id"],
            "run_id": candidate.get("run_id"),
            "project_id": project_id,
            "provider": self.provider,
            "provider_quote_id": provider_quote_id,
            "amount": amount,
            "credits": credits,
            "currency": currency.upper(),
            "eula_reference": eula_reference,
            "paid_status": paid_status,
            "archive_mode": ARCHIVE_MODE_ARCHIVE_FIRST,
            "tasking_requested": False,
            "autonomous_purchase_enabled": False,
        }

    def build_order_record(
        self,
        *,
        quote_record: dict,
        provider_order_id: str,
        paid_status: str,
        requested_by: str,
    ) -> dict:
        return {
            "provider_order_id": provider_order_id,
            "provider_quote_id": quote_record["provider_quote_id"],
            "candidate_id": quote_record["candidate_id"],
            "run_id": quote_record.get("run_id"),
            "project_id": quote_record.get("project_id"),
            "provider": self.provider,
            "amount": quote_record["amount"],
            "credits": quote_record["credits"],
            "currency": quote_record["currency"],
            "eula_reference": quote_record["eula_reference"],
            "paid_status": paid_status,
            "archive_mode": ARCHIVE_MODE_ARCHIVE_FIRST,
            "tasking_requested": False,
            "autonomous_purchase_enabled": False,
            "human_triggered_by": requested_by,
        }
