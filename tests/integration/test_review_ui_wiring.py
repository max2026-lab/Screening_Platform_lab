from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
from lawful_anomaly_screening.db.sqlite import init_db
from lawful_anomaly_screening.ui.streamlit_app import (
    UI_MODE_EXPORT_SAFE,
    UI_MODE_REVIEWER_ONLY,
    build_candidate_detail_view,
    build_candidate_queue_view,
    build_review_app_state,
    submit_review_decision,
)

from review_seed_helpers import seed_reviewable_candidates


def test_review_ui_helpers_use_repository_ordering_and_persistence(tmp_path):
    db_path = tmp_path / "review-ui.sqlite3"
    cache_root = tmp_path / "cache"
    init_db(db_path)
    candidate_records, score_records = seed_reviewable_candidates(db_path, cache_root)
    repository = ReviewRepository(db_path)

    queue = build_candidate_queue_view(
        repository,
        run_id="run-001",
        display_mode=UI_MODE_EXPORT_SAFE,
    )
    expected_candidate_order = [
        row["candidate_id"]
        for row in sorted(score_records, key=lambda item: (-item["candidate_score"], item["candidate_id"]))
    ]

    export_safe_detail = build_candidate_detail_view(
        repository,
        candidate_id=candidate_records[0]["candidate_id"],
        run_id="run-001",
        display_mode=UI_MODE_EXPORT_SAFE,
    )
    reviewer_detail = build_candidate_detail_view(
        repository,
        candidate_id=candidate_records[0]["candidate_id"],
        run_id="run-001",
        display_mode=UI_MODE_REVIEWER_ONLY,
    )
    decision_result = submit_review_decision(
        repository,
        candidate_id=candidate_records[0]["candidate_id"],
        run_id="run-001",
        reviewer_id="reviewer-ui",
        decision="watch",
        note="thin ui note",
        display_mode=UI_MODE_EXPORT_SAFE,
    )
    app_state = build_review_app_state(
        repository,
        selected_run_id="run-001",
        selected_candidate_id=candidate_records[0]["candidate_id"],
        display_mode=UI_MODE_EXPORT_SAFE,
    )

    assert [row["candidate_id"] for row in queue] == expected_candidate_order
    assert queue[0]["run_id"] == "run-001"
    assert queue[0]["candidate_score"] is not None
    assert queue[0]["parent_tile_score"] is not None
    assert export_safe_detail is not None
    assert reviewer_detail is not None
    assert export_safe_detail["centroid"] != reviewer_detail["centroid"]
    assert decision_result["review_action"]["note"] == "thin ui note"
    assert decision_result["candidate_detail"]["review_state"] == "watch"
    assert app_state["selector"]["selected_run_id"] == "run-001"
    assert app_state["detail"]["candidate_id"] == candidate_records[0]["candidate_id"]
