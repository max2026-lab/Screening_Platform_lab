from __future__ import annotations

import math


def _bounds_area(bounds: tuple[float, float, float, float]) -> float:
    min_x, min_y, max_x, max_y = bounds
    return max(0.0, max_x - min_x) * max(0.0, max_y - min_y)


def _intersection_area(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    min_x = max(left[0], right[0])
    min_y = max(left[1], right[1])
    max_x = min(left[2], right[2])
    max_y = min(left[3], right[3])
    return _bounds_area((min_x, min_y, max_x, max_y))


def _iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0.0:
        return 0.0
    union = _bounds_area(left) + _bounds_area(right) - intersection
    if union <= 0.0:
        return 0.0
    return round(intersection / union, 6)


def _centroid_shift_m(current_centroid: tuple[float, float], prior_centroid: tuple[float, float]) -> float:
    return round(
        math.dist((current_centroid[0], current_centroid[1]), (prior_centroid[0], prior_centroid[1])),
        6,
    )


def _area_ratio(current_area_m2: float, prior_area_m2: float) -> float:
    if prior_area_m2 <= 0.0:
        return 0.0
    return round(current_area_m2 / prior_area_m2, 6)


def classify_candidate_pair(current_candidate: dict, prior_candidate: dict) -> dict | None:
    if current_candidate["parent_tile_id"] != prior_candidate["parent_tile_id"]:
        return None

    current_bounds = tuple(current_candidate["bounds"])
    prior_bounds = tuple(prior_candidate["bounds"])
    iou = _iou(current_bounds, prior_bounds)
    centroid_shift_m = _centroid_shift_m(
        tuple(current_candidate["centroid"]),
        tuple(prior_candidate["centroid"]),
    )
    area_ratio = _area_ratio(current_candidate["area_m2"], prior_candidate["area_m2"])

    if iou >= 0.50:
        return {
            "classification": "stable",
            "iou": iou,
            "centroid_shift_m": centroid_shift_m,
            "area_ratio": area_ratio,
        }
    if iou < 0.50 and centroid_shift_m <= 160.0 and 0.5 <= area_ratio <= 2.0:
        return {
            "classification": "moved",
            "iou": iou,
            "centroid_shift_m": centroid_shift_m,
            "area_ratio": area_ratio,
        }
    return None


def build_candidate_diff_report(
    *,
    prior_candidates: list[dict],
    current_candidates: list[dict],
    prior_run_id: str,
    current_run_id: str,
) -> dict:
    matched_prior_candidate_ids: set[str] = set()
    diff_entries: list[dict] = []

    sorted_current_candidates = sorted(
        current_candidates,
        key=lambda item: (item["parent_tile_id"], item["candidate_id"]),
    )
    sorted_prior_candidates = sorted(
        prior_candidates,
        key=lambda item: (item["parent_tile_id"], item["candidate_id"]),
    )

    for current_candidate in sorted_current_candidates:
        qualifying_matches = []
        for prior_candidate in sorted_prior_candidates:
            classification = classify_candidate_pair(current_candidate, prior_candidate)
            if classification is None:
                continue
            qualifying_matches.append(
                {
                    "prior_candidate": prior_candidate,
                    "classification": classification["classification"],
                    "iou": classification["iou"],
                    "centroid_shift_m": classification["centroid_shift_m"],
                    "area_ratio": classification["area_ratio"],
                }
            )

        qualifying_matches.sort(
            key=lambda item: (
                0 if item["classification"] == "stable" else 1,
                -item["iou"],
                item["centroid_shift_m"],
                item["prior_candidate"]["candidate_id"],
            )
        )

        if qualifying_matches:
            best_match = qualifying_matches[0]
            matched_prior_candidate_ids.add(best_match["prior_candidate"]["candidate_id"])
            diff_entries.append(
                {
                    "classification": best_match["classification"],
                    "current_candidate_id": current_candidate["candidate_id"],
                    "prior_candidate_id": best_match["prior_candidate"]["candidate_id"],
                    "parent_tile_id": current_candidate["parent_tile_id"],
                    "iou": best_match["iou"],
                    "centroid_shift_m": best_match["centroid_shift_m"],
                    "area_ratio": best_match["area_ratio"],
                }
            )
        else:
            diff_entries.append(
                {
                    "classification": "new",
                    "current_candidate_id": current_candidate["candidate_id"],
                    "prior_candidate_id": None,
                    "parent_tile_id": current_candidate["parent_tile_id"],
                    "iou": 0.0,
                    "centroid_shift_m": None,
                    "area_ratio": None,
                }
            )

    for prior_candidate in sorted_prior_candidates:
        if prior_candidate["candidate_id"] in matched_prior_candidate_ids:
            continue
        diff_entries.append(
            {
                "classification": "lost",
                "current_candidate_id": None,
                "prior_candidate_id": prior_candidate["candidate_id"],
                "parent_tile_id": prior_candidate["parent_tile_id"],
                "iou": 0.0,
                "centroid_shift_m": None,
                "area_ratio": None,
            }
        )

    sorted_diff_entries = sorted(
        diff_entries,
        key=lambda item: (
            item["classification"],
            item["parent_tile_id"],
            item["current_candidate_id"] or "",
            item["prior_candidate_id"] or "",
        ),
    )

    return {
        "report_version": "phase1-rerun-diff-v1",
        "execution_mode": "synchronous",
        "prior_run_id": prior_run_id,
        "current_run_id": current_run_id,
        "summary": {
            "stable": sum(1 for item in sorted_diff_entries if item["classification"] == "stable"),
            "moved": sum(1 for item in sorted_diff_entries if item["classification"] == "moved"),
            "new": sum(1 for item in sorted_diff_entries if item["classification"] == "new"),
            "lost": sum(1 for item in sorted_diff_entries if item["classification"] == "lost"),
        },
        "diff_entries": sorted_diff_entries,
    }
