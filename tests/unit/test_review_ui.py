from lawful_anomaly_screening.ui.streamlit_app import (
    UI_MODE_EXPORT_SAFE,
    UI_MODE_REVIEWER_ONLY,
    build_candidate_detail_view,
    build_mode_indicator,
    build_project_run_selector,
    submit_review_decision,
)


class FakeReviewRepository:
    def __init__(self) -> None:
        self.decide_calls: list[dict] = []

    def list_runs(self) -> list[dict]:
        return [
            {"run_id": "run-002", "status": "review", "processing_baseline_id": "baseline"},
            {"run_id": "run-001", "status": "new", "processing_baseline_id": "baseline"},
        ]

    def list_review_queue(self, *, run_id: str | None = None, limit: int | None = None) -> list[dict]:
        return []

    def fetch_candidate(self, candidate_id: str, run_id: str | None = None) -> dict | None:
        return {
            "candidate_id": candidate_id,
            "run_id": run_id or "run-001",
            "candidate_score": 91.5,
            "parent_tile_score": 82.0,
            "current_state": "pending_review",
            "centroid": [1234.0, 2789.0],
            "bounds": [1201.0, 2705.0, 1281.0, 2879.0],
            "possible_duplicate": True,
            "duplicate_resolution_action": "review_pair",
        }

    def fetch_review_actions(self, candidate_id: str) -> list[dict]:
        return [{"candidate_id": candidate_id, "decision": "watch"}]

    def decide(
        self,
        *,
        candidate_id: str,
        run_id: str,
        reviewer_id: str,
        decision: str,
        note: str | None = None,
    ) -> dict:
        call = {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "note": note,
        }
        self.decide_calls.append(call)
        return {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "note": note,
        }


def test_mode_indicator_tracks_reviewer_only_vs_export_safe():
    reviewer = build_mode_indicator(UI_MODE_REVIEWER_ONLY)
    export_safe = build_mode_indicator(UI_MODE_EXPORT_SAFE)

    assert reviewer["exact_coordinates_visible"] is True
    assert reviewer["label"] == "Reviewer-only"
    assert export_safe["exact_coordinates_visible"] is False
    assert export_safe["label"] == "Export-safe"


def test_project_run_selector_defaults_to_first_sorted_run():
    repository = FakeReviewRepository()
    selector = build_project_run_selector(repository.list_runs())

    assert selector["selected_project_id"] == "default_project"
    assert [row["run_id"] for row in selector["run_options"]] == ["run-001", "run-002"]
    assert selector["selected_run_id"] == "run-001"


def test_candidate_detail_hides_exact_coordinates_in_export_safe_mode():
    repository = FakeReviewRepository()

    export_safe_detail = build_candidate_detail_view(
        repository,
        candidate_id="candidate-001",
        run_id="run-001",
        display_mode=UI_MODE_EXPORT_SAFE,
    )
    reviewer_detail = build_candidate_detail_view(
        repository,
        candidate_id="candidate-001",
        run_id="run-001",
        display_mode=UI_MODE_REVIEWER_ONLY,
    )

    assert export_safe_detail is not None
    assert reviewer_detail is not None
    assert export_safe_detail["candidate_id"] == "candidate-001"
    assert export_safe_detail["run_id"] == "run-001"
    assert export_safe_detail["candidate_score"] == 91.5
    assert export_safe_detail["parent_tile_score"] == 82.0
    assert export_safe_detail["centroid"] == [1000.0, 3000.0]
    assert reviewer_detail["centroid"] == [1234.0, 2789.0]
    assert export_safe_detail["action_controls"]["allowed_decisions"] == [
        "reject",
        "watch",
        "approve_for_archive_quote",
    ]
    assert len(export_safe_detail["geofence_export_warning_area"]) >= 2


def test_submit_review_decision_wires_to_repository():
    repository = FakeReviewRepository()

    result = submit_review_decision(
        repository,
        candidate_id="candidate-001",
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="ready for archive",
        display_mode=UI_MODE_REVIEWER_ONLY,
    )

    assert repository.decide_calls == [
        {
            "candidate_id": "candidate-001",
            "run_id": "run-001",
            "reviewer_id": "reviewer-001",
            "decision": "approve_for_archive_quote",
            "note": "ready for archive",
        }
    ]
    assert result["review_action"]["decision"] == "approve_for_archive_quote"
    assert result["candidate_detail"]["run_id"] == "run-001"
