import json

import pytest

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.acceptance_repository import AcceptanceRepository
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.paid_repository import PaidRepository
from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
from lawful_anomaly_screening.db.sqlite import init_db
from lawful_anomaly_screening.exceptions import PaidOrderStateError, PaidQuoteEligibilityError
from lawful_anomaly_screening.paid.order_service import (
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_SUBMITTED,
    OrderService,
)
from lawful_anomaly_screening.paid.quote_service import QUOTE_STATUS_ORDERED, QUOTE_STATUS_RECEIVED, QuoteService
from lawful_anomaly_screening.paid.up42_archive import Up42ArchiveClient
from review_seed_helpers import seed_reviewable_candidates


def _legal_gate_pass() -> dict:
    return {
        "attestation_status": "present",
        "geofence_status": "clear",
        "decision": "pass",
        "reason": "legal gate passed",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _legal_gate_fail() -> dict:
    return {
        "attestation_status": "missing",
        "geofence_status": "clear",
        "decision": "fail",
        "reason": "attestation missing",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _build_services(db_path):
    repository = PaidRepository(db_path)
    review_repository = ReviewRepository(db_path)
    acceptance_repository = AcceptanceRepository(db_path)
    archive_client = Up42ArchiveClient()
    return (
        repository,
        review_repository,
        acceptance_repository,
        QuoteService(
            acceptance_repository=acceptance_repository,
            paid_repository=repository,
            review_repository=review_repository,
            archive_client=archive_client,
        ),
        OrderService(
            acceptance_repository=acceptance_repository,
            paid_repository=repository,
            review_repository=review_repository,
            archive_client=archive_client,
        ),
    )


def _create_export_audit(db_path, export_root, run_id: str) -> dict:
    export_repository = ExportRepository(db_path, export_root=export_root)
    candidates = export_repository.fetch_export_candidates(run_id)
    assert candidates
    return export_repository.persist_export(
        run_id=run_id,
        audience="report_pdf",
        requested_precision="restricted",
        candidates=candidates,
    )


def test_paid_quote_requires_approved_candidate_and_persists_metadata(tmp_path):
    db_path = tmp_path / "paid-flow.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_pass(),
    )
    repository, review_repository, _, quote_service, _ = _build_services(db_path)
    candidate_id = candidate_records[0]["candidate_id"]

    with pytest.raises(
        PaidQuoteEligibilityError,
        match="candidate review state must be approved_for_archive_quote",
    ):
        quote_service.create_quote(
            candidate_id=candidate_id,
            provider_quote_id="quote-001",
            amount=149.5,
            credits=88.0,
            currency="usd",
            eula_reference="eula-2026-04",
            project_id="project-001",
        )

    review_repository.decide(
        candidate_id=candidate_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="approved for archive-only quote",
    )

    quote = quote_service.create_quote(
        candidate_id=candidate_id,
        provider_quote_id="quote-001",
        amount=149.5,
        credits=88.0,
        currency="usd",
        eula_reference="eula-2026-04",
        project_id="project-001",
    )
    persisted_quote = repository.fetch_quote(provider_quote_id="quote-001")

    assert persisted_quote is not None
    assert quote["candidate_id"] == candidate_id
    assert quote["run_id"] == "run-001"
    assert quote["project_id"] == "project-001"
    assert quote["provider"] == "up42"
    assert quote["quote_id"] == "quote-001"
    assert quote["provider_quote_id"] == "quote-001"
    assert quote["amount"] == 149.5
    assert quote["credits"] == 88.0
    assert quote["currency"] == "USD"
    assert quote["eula_reference"] == "eula-2026-04"
    assert quote["paid_status"] == QUOTE_STATUS_RECEIVED
    assert quote["archive_mode"] == "archive_first"
    assert quote["tasking_requested"] is False
    assert quote["autonomous_purchase_enabled"] is False
    assert quote["current_review_state"] == "approved_for_archive_quote"
    assert quote["legal_gate"]["decision"] == "pass"
    assert quote["paid_escalation_ready"] is True
    assert quote["reasons"] == ["Paid archive escalation checks passed"]
    assert quote["created_at"]
    assert quote["updated_at"]


def test_paid_quote_fails_clearly_for_pending_and_rejected_candidates(tmp_path):
    db_path = tmp_path / "paid-quote-states.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_pass(),
    )
    _, review_repository, _, quote_service, _ = _build_services(db_path)
    candidate_id = candidate_records[0]["candidate_id"]

    with pytest.raises(
        PaidQuoteEligibilityError,
        match="candidate review state must be approved_for_archive_quote",
    ):
        quote_service.create_quote(
            candidate_id=candidate_id,
            provider_quote_id="quote-pending-001",
            amount=149.5,
            credits=88.0,
            currency="usd",
            eula_reference="eula-2026-04",
        )

    review_repository.decide(
        candidate_id=candidate_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="reject",
        note="rejected for archive flow",
    )
    with pytest.raises(
        PaidQuoteEligibilityError,
        match="candidate review state must be approved_for_archive_quote",
    ):
        quote_service.create_quote(
            candidate_id=candidate_id,
            provider_quote_id="quote-rejected-001",
            amount=149.5,
            credits=88.0,
            currency="usd",
            eula_reference="eula-2026-04",
        )


def test_paid_quote_fails_for_legal_denied_run(tmp_path):
    db_path = tmp_path / "paid-quote-legal.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_fail(),
    )
    _, review_repository, _, quote_service, _ = _build_services(db_path)
    candidate_id = candidate_records[0]["candidate_id"]
    review_repository.decide(
        candidate_id=candidate_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="approved but legal gate denied",
    )

    with pytest.raises(
        PaidQuoteEligibilityError,
        match="legal gate must pass before paid quote creation",
    ):
        quote_service.create_quote(
            candidate_id=candidate_id,
            provider_quote_id="quote-legal-denied-001",
            amount=149.5,
            credits=88.0,
            currency="usd",
            eula_reference="eula-2026-04",
        )


def test_paid_order_requires_export_audit_and_tracks_status_transitions(tmp_path):
    db_path = tmp_path / "paid-order-flow.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_pass(),
    )
    repository, review_repository, _, quote_service, order_service = _build_services(db_path)
    candidate_id = candidate_records[0]["candidate_id"]

    review_repository.decide(
        candidate_id=candidate_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="approved for archive-only quote",
    )
    quote_service.create_quote(
        candidate_id=candidate_id,
        provider_quote_id="quote-002",
        amount=210.0,
        credits=100.0,
        currency="usd",
        eula_reference="eula-2026-04",
        project_id="project-001",
    )

    with pytest.raises(PaidOrderStateError):
        order_service.create_order(
            candidate_id=candidate_id,
            provider_quote_id="quote-002",
            provider_order_id="order-blank-requester-001",
            requested_by="   ",
        )

    with pytest.raises(
        PaidOrderStateError,
        match="export audit manifest must exist before paid order creation",
    ):
        order_service.create_order(
            candidate_id=candidate_id,
            provider_quote_id="quote-002",
            provider_order_id="order-no-export-001",
            requested_by="reviewer-001",
        )

    export_payload = _create_export_audit(db_path, tmp_path, "run-001")
    order = order_service.create_order(
        candidate_id=candidate_id,
        provider_quote_id="quote-002",
        provider_order_id="order-001",
        requested_by="reviewer-001",
    )
    confirmed_order = order_service.update_order_status(
        provider_order_id="order-001",
        paid_status=ORDER_STATUS_CONFIRMED,
    )
    delivered_order = order_service.update_order_status(
        provider_order_id="order-001",
        paid_status=ORDER_STATUS_DELIVERED,
    )
    updated_quote = repository.fetch_quote(provider_quote_id="quote-002")

    assert order["candidate_id"] == candidate_id
    assert order["run_id"] == "run-001"
    assert order["provider_quote_id"] == "quote-002"
    assert order["provider_order_id"] == "order-001"
    assert order["requested_by"] == "reviewer-001"
    assert order["human_triggered_by"] == "reviewer-001"
    assert order["paid_status"] == ORDER_STATUS_SUBMITTED
    assert order["latest_export_audit_manifest_hash"] == export_payload["audit_manifest"]["audit_manifest_hash"]
    assert order["legal_gate"]["decision"] == "pass"
    assert order["reasons"] == ["Paid archive order checks passed"]
    assert updated_quote is not None
    assert updated_quote["paid_status"] == QUOTE_STATUS_ORDERED
    assert confirmed_order["paid_status"] == ORDER_STATUS_CONFIRMED
    assert confirmed_order["latest_export_audit_manifest_hash"] == export_payload["audit_manifest"]["audit_manifest_hash"]
    assert delivered_order["paid_status"] == ORDER_STATUS_DELIVERED


def test_paid_cli_flow_persists_quote_and_order_metadata(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "paid-cli.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_pass(),
    )
    candidate_id = candidate_records[0]["candidate_id"]
    review_repository = ReviewRepository(db_path)
    review_repository.decide(
        candidate_id=candidate_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="approved for archive-only quote",
    )

    assert main(
        [
            "paid-quote-create",
            "--candidate-id",
            candidate_id,
            "--provider-quote-id",
            "quote-cli-001",
            "--amount",
            "175.0",
            "--credits",
            "95.0",
            "--currency",
            "usd",
            "--eula-reference",
            "eula-cli-001",
            "--project-id",
            "project-cli-001",
        ]
    ) == 0
    quote_payload = json.loads(capsys.readouterr().out)
    assert quote_payload["paid_escalation_ready"] is True
    assert quote_payload["legal_gate"]["decision"] == "pass"
    assert quote_payload["reasons"] == ["Paid archive escalation checks passed"]

    assert main(
        [
            "paid-order-create",
            "--candidate-id",
            candidate_id,
            "--provider-quote-id",
            "quote-cli-001",
            "--provider-order-id",
            "order-cli-001",
            "--requested-by",
            "reviewer-001",
        ]
    ) == 1
    order_failure_stderr = capsys.readouterr().err
    assert "export audit manifest must exist before paid order creation" in order_failure_stderr
    assert "Traceback" not in order_failure_stderr

    _create_export_audit(db_path, tmp_path, "run-001")

    assert main(
        [
            "paid-order-create",
            "--candidate-id",
            candidate_id,
            "--provider-quote-id",
            "quote-cli-001",
            "--provider-order-id",
            "order-cli-001",
            "--requested-by",
            "reviewer-001",
        ]
    ) == 0
    order_payload = json.loads(capsys.readouterr().out)

    assert main(
        [
            "paid-order-status",
            "--provider-order-id",
            "order-cli-001",
            "--paid-status",
            "order_confirmed",
        ]
    ) == 0
    status_payload = json.loads(capsys.readouterr().out)

    assert quote_payload["provider_quote_id"] == "quote-cli-001"
    assert order_payload["provider_order_id"] == "order-cli-001"
    assert order_payload["paid_status"] == ORDER_STATUS_SUBMITTED
    assert order_payload["latest_export_audit_manifest_hash"]
    assert status_payload["paid_status"] == ORDER_STATUS_CONFIRMED


def test_paid_order_status_fails_clearly_for_missing_order(tmp_path):
    db_path = tmp_path / "paid-order-missing.sqlite3"
    init_db(db_path)
    _, _, _, _, order_service = _build_services(db_path)

    with pytest.raises(PaidOrderStateError, match="paid order not found: missing-order-001"):
        order_service.update_order_status(
            provider_order_id="missing-order-001",
            paid_status=ORDER_STATUS_CONFIRMED,
        )
