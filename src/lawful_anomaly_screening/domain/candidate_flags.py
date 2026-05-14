from __future__ import annotations

LANDSCAPE_SCALE_THRESHOLD_M2: float = 250000.0

_LANDSCAPE_GUIDANCE = (
    "This candidate exceeds the 25 ha (250,000 m2) landscape-scale threshold. "
    "Do not fast-track to paid imagery solely from the automated score. "
    "Use a separate landscape / context review before paid escalation."
)

_STANDARD_GUIDANCE = (
    "Standard object-scale candidate. Follow normal review workflow."
)

_STANDARD_CLOSEOUT_GUIDANCE = (
    "Standard candidate closeout. No separate landscape/context review is required."
)

_LANDSCAPE_UNRESOLVED_GUIDANCE = (
    "Separate landscape/context review is still required before any paid escalation."
)

_LANDSCAPE_WATCH_GUIDANCE = (
    "Candidate is deferred for separate landscape/context follow-up."
)

_LANDSCAPE_REJECTED_GUIDANCE = (
    "No paid escalation is expected from this closeout."
)

_LANDSCAPE_APPROVED_GUIDANCE = (
    "Approval should be treated as requiring separate landscape/context review "
    "before paid imagery escalation."
)

_PAID_LANDSCAPE_WARNING_MESSAGE = (
    "Candidate is landscape-scale / above the 25 ha threshold. "
    "Context review is recommended before paid imagery escalation. "
    "This is warning-only and does not block quote/order."
)

_PAID_STANDARD_MESSAGE = "No landscape-scale paid warning."


def compute_landscape_scale_fields(area_m2: float) -> dict[str, object]:
    """Return landscape-scale flag and reviewer rubric fields for a candidate area.

    These are presentation-only metadata; they do not affect scoring,
    ranking, or suppression.
    """
    is_landscape_scale = area_m2 > LANDSCAPE_SCALE_THRESHOLD_M2
    if is_landscape_scale:
        rubric = {
            "reviewer_review_track": "landscape_scale_separate_review",
            "reviewer_rubric_label": "Landscape-scale candidate",
            "reviewer_rubric_guidance": _LANDSCAPE_GUIDANCE,
        }
    else:
        rubric = {
            "reviewer_review_track": "standard_candidate_review",
            "reviewer_rubric_label": "Standard candidate",
            "reviewer_rubric_guidance": _STANDARD_GUIDANCE,
        }
    return {
        "is_landscape_scale": is_landscape_scale,
        "landscape_scale_threshold_m2": LANDSCAPE_SCALE_THRESHOLD_M2,
        "landscape_scale_area_ha": round(area_m2 / 10000.0, 6),
        **rubric,
    }


def compute_landscape_scale_closeout_fields(
    is_landscape_scale: bool,
    current_state: str,
) -> dict[str, str]:
    """Return deterministic closeout messaging for landscape-scale handling."""
    if not is_landscape_scale:
        return {
            "landscape_scale_closeout_path": "standard_candidate_closeout",
            "landscape_scale_closeout_label": "Standard candidate closeout",
            "landscape_scale_closeout_guidance": _STANDARD_CLOSEOUT_GUIDANCE,
        }

    if current_state == "pending_review":
        return {
            "landscape_scale_closeout_path": "landscape_scale_unresolved",
            "landscape_scale_closeout_label": "Landscape-scale unresolved",
            "landscape_scale_closeout_guidance": _LANDSCAPE_UNRESOLVED_GUIDANCE,
        }
    if current_state == "watch":
        return {
            "landscape_scale_closeout_path": "landscape_scale_watch",
            "landscape_scale_closeout_label": "Landscape-scale watch",
            "landscape_scale_closeout_guidance": _LANDSCAPE_WATCH_GUIDANCE,
        }
    if current_state == "rejected":
        return {
            "landscape_scale_closeout_path": "landscape_scale_rejected",
            "landscape_scale_closeout_label": "Landscape-scale rejected",
            "landscape_scale_closeout_guidance": _LANDSCAPE_REJECTED_GUIDANCE,
        }
    if current_state == "approved_for_archive_quote":
        return {
            "landscape_scale_closeout_path": "landscape_scale_paid_escalation_requires_context_review",
            "landscape_scale_closeout_label": "Landscape-scale paid escalation requires context review",
            "landscape_scale_closeout_guidance": _LANDSCAPE_APPROVED_GUIDANCE,
        }

    return {
        "landscape_scale_closeout_path": "standard_candidate_closeout",
        "landscape_scale_closeout_label": "Standard candidate closeout",
        "landscape_scale_closeout_guidance": _STANDARD_CLOSEOUT_GUIDANCE,
    }


def compute_paid_landscape_scale_warning_fields(
    is_landscape_scale: bool,
) -> dict[str, object]:
    """Return warning-only paid escalation metadata for landscape-scale candidates."""
    if is_landscape_scale:
        return {
            "paid_landscape_scale_warning": True,
            "paid_landscape_scale_warning_code": "landscape_scale_context_review_recommended",
            "paid_landscape_scale_warning_message": _PAID_LANDSCAPE_WARNING_MESSAGE,
            "paid_landscape_scale_context_review_recommended": True,
        }
    return {
        "paid_landscape_scale_warning": False,
        "paid_landscape_scale_warning_code": "none",
        "paid_landscape_scale_warning_message": _PAID_STANDARD_MESSAGE,
        "paid_landscape_scale_context_review_recommended": False,
    }
