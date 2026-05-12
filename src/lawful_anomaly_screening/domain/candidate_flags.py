from __future__ import annotations

LANDSCAPE_SCALE_THRESHOLD_M2: float = 250000.0


def compute_landscape_scale_fields(area_m2: float) -> dict[str, object]:
    """Return landscape-scale flag fields for a candidate area.

    These are presentation-only metadata; they do not affect scoring,
    ranking, or suppression.
    """
    is_landscape_scale = area_m2 > LANDSCAPE_SCALE_THRESHOLD_M2
    return {
        "is_landscape_scale": is_landscape_scale,
        "landscape_scale_threshold_m2": LANDSCAPE_SCALE_THRESHOLD_M2,
        "landscape_scale_area_ha": round(area_m2 / 10000.0, 6),
    }
