import json

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
from lawful_anomaly_screening.db.sqlite import connect, init_db
from review_seed_helpers import seed_reviewable_candidates


def _legal_gate_pass() -> dict:
    return {
        "attestation_status": "present",
        "geofence_status": "clear",
        "decision": "pass",
        "reason": "legal gate passed",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def test_paid_quote_cli_emits_landscape_scale_warning_metadata(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "paid-quote-cli.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    candidate_records, _ = seed_reviewable_candidates(
        db_path,
        cache_root,
        legal_gate=_legal_gate_pass(),
    )
    candidate_id = candidate_records[0]["candidate_id"]
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE candidate_polygons SET area_m2 = ? WHERE candidate_id = ? AND run_id = ?",
            (300000.0, candidate_id, "run-001"),
        )
        conn.commit()
    review_repository = ReviewRepository(db_path)
    candidate = review_repository.fetch_candidate(candidate_id, "run-001")
    assert candidate is not None
    assert candidate["is_landscape_scale"] is True

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
            "quote-landscape-001",
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
    create_payload = json.loads(capsys.readouterr().out)

    assert main(
        [
            "paid-quote-show",
            "--provider-quote-id",
            "quote-landscape-001",
        ]
    ) == 0
    show_payload = json.loads(capsys.readouterr().out)

    assert create_payload["paid_escalation_ready"] is True
    assert create_payload["paid_landscape_scale_warning"] is True
    assert (
        create_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )
    assert create_payload["paid_landscape_scale_context_review_recommended"] is True
    assert "25 ha" in create_payload["paid_landscape_scale_warning_message"] or (
        "landscape-scale" in create_payload["paid_landscape_scale_warning_message"]
    )
    assert "warning-only" in create_payload["paid_landscape_scale_warning_message"] or (
        "does not block" in create_payload["paid_landscape_scale_warning_message"]
    )

    assert show_payload["paid_landscape_scale_warning"] is True
    assert (
        show_payload["paid_landscape_scale_warning_code"]
        == "landscape_scale_context_review_recommended"
    )
    assert show_payload["paid_landscape_scale_context_review_recommended"] is True
    assert show_payload["paid_landscape_scale_warning_message"] == (
        create_payload["paid_landscape_scale_warning_message"]
    )
