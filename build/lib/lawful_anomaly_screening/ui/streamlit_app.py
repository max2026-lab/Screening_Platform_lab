from __future__ import annotations

from pathlib import Path
from typing import Protocol

from lawful_anomaly_screening.db.repositories.review_repository import (
    REVIEW_DECISION_APPROVE_FOR_ARCHIVE_QUOTE,
    REVIEW_DECISION_REJECT,
    REVIEW_DECISION_WATCH,
    ReviewRepository,
)
from lawful_anomaly_screening.exports.precision_policy import sanitize_candidate_for_export
from lawful_anomaly_screening.settings import load_settings

UI_MODE_REVIEWER_ONLY = "reviewer_only"
UI_MODE_EXPORT_SAFE = "export_safe"
VALID_UI_MODES = (UI_MODE_REVIEWER_ONLY, UI_MODE_EXPORT_SAFE)
VALID_REVIEW_DECISIONS = (
    REVIEW_DECISION_REJECT,
    REVIEW_DECISION_WATCH,
    REVIEW_DECISION_APPROVE_FOR_ARCHIVE_QUOTE,
)


class ReviewDataSource(Protocol):
    def list_runs(self) -> list[dict]: ...
    def list_review_queue(self, *, run_id: str | None = None, limit: int | None = None) -> list[dict]: ...
    def fetch_candidate(self, candidate_id: str, run_id: str | None = None) -> dict | None: ...
    def fetch_review_actions(self, candidate_id: str) -> list[dict]: ...
    def decide(
        self,
        *,
        candidate_id: str,
        run_id: str,
        reviewer_id: str,
        decision: str,
        note: str | None = None,
    ) -> dict: ...


def build_mode_indicator(display_mode: str) -> dict:
    normalized_mode = display_mode if display_mode in VALID_UI_MODES else UI_MODE_EXPORT_SAFE
    if normalized_mode == UI_MODE_REVIEWER_ONLY:
        return {
            "mode": normalized_mode,
            "label": "Reviewer-only",
            "exact_coordinates_visible": True,
            "warning": "Exact coordinates may be shown for reviewer-only analysis.",
        }
    return {
        "mode": UI_MODE_EXPORT_SAFE,
        "label": "Export-safe",
        "exact_coordinates_visible": False,
        "warning": "Exact unconfirmed coordinates are hidden in export-safe mode.",
    }


def build_project_run_selector(
    run_rows: list[dict],
    selected_run_id: str | None = None,
) -> dict:
    ordered_runs = [
        {
            "project_id": "default_project",
            "run_id": row["run_id"],
            "label": f"{row['run_id']} ({row['status']})",
            "status": row["status"],
        }
        for row in sorted(run_rows, key=lambda item: item["run_id"])
    ]
    available_run_ids = {row["run_id"] for row in ordered_runs}
    resolved_run_id = selected_run_id if selected_run_id in available_run_ids else None
    if resolved_run_id is None and ordered_runs:
        resolved_run_id = ordered_runs[0]["run_id"]
    return {
        "project_options": [
            {
                "project_id": "default_project",
                "label": "Default Project",
            }
        ],
        "selected_project_id": "default_project",
        "run_options": ordered_runs,
        "selected_run_id": resolved_run_id,
    }


def build_warning_area(candidate: dict, mode_indicator: dict) -> list[str]:
    warnings = [mode_indicator["warning"]]
    if candidate.get("possible_duplicate"):
        warnings.append("Possible duplicate candidate requires reviewer attention.")
    if candidate.get("duplicate_resolution_action"):
        warnings.append(
            f"Duplicate resolution action: {candidate['duplicate_resolution_action']}."
        )
    warnings.append("Geofence/export warning area scaffold only.")
    return warnings


def _sanitize_candidate_for_mode(candidate: dict, display_mode: str) -> dict:
    if display_mode == UI_MODE_REVIEWER_ONLY:
        return dict(candidate)
    return sanitize_candidate_for_export(candidate, "public")


def build_candidate_queue_view(
    review_repository: ReviewDataSource,
    *,
    run_id: str | None = None,
    display_mode: str = UI_MODE_EXPORT_SAFE,
    limit: int | None = None,
) -> list[dict]:
    mode_indicator = build_mode_indicator(display_mode)
    queue_rows = review_repository.list_review_queue(run_id=run_id, limit=limit)
    return [
        {
            "candidate_id": row["candidate_id"],
            "run_id": row["run_id"],
            "candidate_score": row.get("candidate_score"),
            "parent_tile_score": row.get("parent_tile_score"),
            "parent_tile_id": row["parent_tile_id"],
            "review_state": row["current_state"],
            "possible_duplicate": bool(row["possible_duplicate"]),
            "mode_label": mode_indicator["label"],
        }
        for row in queue_rows
    ]


def build_candidate_detail_view(
    review_repository: ReviewDataSource,
    *,
    candidate_id: str,
    run_id: str | None = None,
    display_mode: str = UI_MODE_EXPORT_SAFE,
) -> dict | None:
    candidate = review_repository.fetch_candidate(candidate_id, run_id=run_id)
    if candidate is None:
        return None
    visible_candidate = _sanitize_candidate_for_mode(candidate, display_mode)
    mode_indicator = build_mode_indicator(display_mode)
    review_actions = review_repository.fetch_review_actions(candidate_id)
    return {
        "candidate_id": visible_candidate["candidate_id"],
        "run_id": visible_candidate["run_id"],
        "candidate_score": visible_candidate.get("candidate_score"),
        "parent_tile_score": visible_candidate.get("parent_tile_score"),
        "review_state": visible_candidate["current_state"],
        "centroid": visible_candidate["centroid"],
        "bounds": visible_candidate["bounds"],
        "mode_indicator": mode_indicator,
        "geofence_export_warning_area": build_warning_area(visible_candidate, mode_indicator),
        "review_actions": review_actions,
        "action_controls": {
            "allowed_decisions": list(VALID_REVIEW_DECISIONS),
            "note_placeholder": "Optional review note",
        },
    }


def submit_review_decision(
    review_repository: ReviewDataSource,
    *,
    candidate_id: str,
    run_id: str,
    reviewer_id: str,
    decision: str,
    note: str | None = None,
    display_mode: str = UI_MODE_EXPORT_SAFE,
) -> dict:
    action = review_repository.decide(
        candidate_id=candidate_id,
        run_id=run_id,
        reviewer_id=reviewer_id,
        decision=decision,
        note=note,
    )
    return {
        "review_action": action,
        "candidate_detail": build_candidate_detail_view(
            review_repository,
            candidate_id=candidate_id,
            run_id=run_id,
            display_mode=display_mode,
        ),
    }


def build_review_app_state(
    review_repository: ReviewDataSource,
    *,
    selected_run_id: str | None = None,
    selected_candidate_id: str | None = None,
    display_mode: str = UI_MODE_EXPORT_SAFE,
    queue_limit: int | None = None,
) -> dict:
    selector = build_project_run_selector(
        review_repository.list_runs(),
        selected_run_id=selected_run_id,
    )
    resolved_run_id = selector["selected_run_id"]
    queue_rows = build_candidate_queue_view(
        review_repository,
        run_id=resolved_run_id,
        display_mode=display_mode,
        limit=queue_limit,
    )
    resolved_candidate_id = selected_candidate_id
    if resolved_candidate_id is None and queue_rows:
        resolved_candidate_id = queue_rows[0]["candidate_id"]
    return {
        "selector": selector,
        "mode_indicator": build_mode_indicator(display_mode),
        "queue": queue_rows,
        "detail": (
            build_candidate_detail_view(
                review_repository,
                candidate_id=resolved_candidate_id,
                run_id=resolved_run_id,
                display_mode=display_mode,
            )
            if resolved_candidate_id is not None
            else None
        ),
    }


def app(db_path: Path | str | None = None) -> dict:
    settings = load_settings()
    repository = ReviewRepository(db_path or settings.db_path)
    return build_review_app_state(repository)


def run_streamlit_app(
    *,
    db_path: Path | str | None = None,
    st_module=None,
) -> None:
    if st_module is None:
        try:
            import streamlit as st_module  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError("streamlit is not installed for this scaffold") from exc

    settings = load_settings()
    repository = ReviewRepository(db_path or settings.db_path)
    selector = build_project_run_selector(repository.list_runs())
    selected_run_id = st_module.sidebar.selectbox(
        "Run",
        [row["run_id"] for row in selector["run_options"]],
        index=0 if selector["selected_run_id"] is not None else None,
    ) if selector["run_options"] else None
    display_mode = st_module.sidebar.radio(
        "Coordinate Mode",
        [UI_MODE_REVIEWER_ONLY, UI_MODE_EXPORT_SAFE],
        format_func=lambda value: build_mode_indicator(value)["label"],
    )
    state = build_review_app_state(
        repository,
        selected_run_id=selected_run_id,
        display_mode=display_mode,
    )
    st_module.title("Lawful Anomaly Screening Review")
    st_module.caption(state["mode_indicator"]["warning"])
    st_module.subheader("Candidate Queue")
    st_module.write(state["queue"])
    st_module.subheader("Candidate Detail")
    st_module.write(state["detail"])
