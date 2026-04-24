from lawful_anomaly_screening.paid.order_service import ORDER_STATUS_SUBMITTED
from lawful_anomaly_screening.paid.quote_service import QUOTE_STATUS_RECEIVED
from lawful_anomaly_screening.paid.up42_archive import ARCHIVE_MODE_ARCHIVE_FIRST, Up42ArchiveClient


def test_up42_archive_client_scaffold_is_archive_only():
    client = Up42ArchiveClient()
    candidate = {
        "candidate_id": "candidate-001",
        "run_id": "run-001",
    }

    quote_record = client.build_quote_record(
        candidate=candidate,
        provider_quote_id="quote-001",
        amount=120.0,
        credits=45.0,
        currency="usd",
        eula_reference="eula-001",
        project_id="project-001",
        paid_status=QUOTE_STATUS_RECEIVED,
    )
    order_record = client.build_order_record(
        quote_record=quote_record,
        provider_order_id="order-001",
        paid_status=ORDER_STATUS_SUBMITTED,
        requested_by="reviewer-001",
    )

    assert quote_record["archive_mode"] == ARCHIVE_MODE_ARCHIVE_FIRST
    assert quote_record["tasking_requested"] is False
    assert quote_record["autonomous_purchase_enabled"] is False
    assert quote_record["currency"] == "USD"
    assert order_record["archive_mode"] == ARCHIVE_MODE_ARCHIVE_FIRST
    assert order_record["tasking_requested"] is False
    assert order_record["autonomous_purchase_enabled"] is False
    assert order_record["human_triggered_by"] == "reviewer-001"
