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
