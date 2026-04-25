from lawful_anomaly_screening.db.repositories.acceptance_repository import AcceptanceRepository
from lawful_anomaly_screening.db.sqlite import connect, init_db, insert_review_action, upsert_paid_quote

from review_seed_helpers import seed_reviewable_candidates


def test_acceptance_repository_reads_candidates_reviews_and_paid_escalations(tmp_path):
    db_path = tmp_path / "acceptance.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, score_records = seed_reviewable_candidates(db_path, cache_root)
    approved_candidate_id = score_records[0]["candidate_id"]

    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE candidate_polygons
            SET current_state = 'approved_for_archive_quote'
            WHERE candidate_id = ?
            """,
            (approved_candidate_id,),
        )
        insert_review_action(
            conn,
            candidate_id=approved_candidate_id,
            run_id="run-001",
            reviewer_id="reviewer-001",
            decision="approve_for_archive_quote",
            prior_state="pending_review",
            new_state="approved_for_archive_quote",
            note="accepted",
        )
        upsert_paid_quote(
            conn,
            candidate_id=approved_candidate_id,
            run_id="run-001",
            project_id="project-001",
            provider="up42",
            provider_quote_id="quote-001",
            amount=100.0,
            credits=25.0,
            currency="USD",
            eula_reference="eula-001",
            paid_status="quote_received",
            archive_mode="archive_first",
            tasking_requested=False,
            autonomous_purchase_enabled=False,
        )
        conn.commit()

    repository = AcceptanceRepository(db_path)
    run = repository.fetch_run("run-001")
    candidates = repository.fetch_candidate_rows("run-001")

    assert run is not None
    assert run["source_scene_manifest_hash"] == "manifest-hash-001"
    assert run["score_formula_version"] == "v1.5.1-phase0"
    assert run["legal_gate"]["decision"] == "fail"
    assert candidates[0]["candidate_id"] == approved_candidate_id
    assert candidates[0]["review_state"] == "approved_for_archive_quote"
    assert repository.fetch_review_state_counts("run-001")["approved_for_archive_quote"] == 1
    assert repository.fetch_latest_export_audit_manifest("run-001") is None
    assert repository.count_paid_escalations("run-001") == 1
    assert len(candidates) == len(candidate_records)
