from __future__ import annotations


AUTOMATED_CANDIDATE_SCORE_FIELDS = (
    "texture_support",
    "compactness_support",
    "polygon_object_score",
    "candidate_score",
)
SCORE_TOLERANCE = 1e-6


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def compute_texture_support(local_contrast_values: list[float]) -> float:
    if not local_contrast_values:
        return 0.0
    mean_local_contrast = sum(local_contrast_values) / len(local_contrast_values)
    return round(_clamp(20.0 * mean_local_contrast, 0.0, 40.0), 6)


def compute_compactness_support(
    area_m2: float,
    convex_hull_area_m2: float,
) -> float:
    compactness_ratio = 0.0
    if convex_hull_area_m2 > 0.0:
        compactness_ratio = _clamp(area_m2 / convex_hull_area_m2, 0.0, 1.0)
    return round(_clamp(30.0 * compactness_ratio, 0.0, 30.0), 6)


def compute_polygon_object_score(
    texture_support: float,
    compactness_support: float,
) -> float:
    raw = texture_support + compactness_support
    return round(_clamp((raw / 70.0) * 100.0, 0.0, 100.0), 6)


def compute_candidate_score(
    parent_tile_score: float,
    polygon_object_score: float,
) -> float:
    return round(_clamp((0.7 * parent_tile_score) + (0.3 * polygon_object_score), 0.0, 100.0), 6)


def check_candidate_score_integrity(
    contribution_sum: float,
    candidate_score: float,
    tolerance: float = SCORE_TOLERANCE,
) -> dict[str, float | bool]:
    integrity_delta = round(abs(contribution_sum - candidate_score), 6)
    return {
        "contribution_sum": round(contribution_sum, 6),
        "integrity_delta": integrity_delta,
        "integrity_tolerance": tolerance,
        "integrity_within_tolerance": integrity_delta <= tolerance,
    }


def build_candidate_score_breakdown(
    parent_tile_score: float,
    texture_support: float,
    compactness_support: float,
    polygon_object_score: float,
    candidate_score: float,
) -> dict:
    weighted_parent_tile_score = round(0.7 * parent_tile_score, 6)
    weighted_polygon_object_score = round(0.3 * polygon_object_score, 6)
    integrity_check = check_candidate_score_integrity(
        weighted_parent_tile_score + weighted_polygon_object_score,
        candidate_score,
    )
    return {
        "parent_tile_score": round(parent_tile_score, 6),
        "texture_support": texture_support,
        "compactness_support": compactness_support,
        "polygon_object_score": polygon_object_score,
        "weighted_parent_tile_score": weighted_parent_tile_score,
        "weighted_polygon_object_score": weighted_polygon_object_score,
        "contribution_sum": integrity_check["contribution_sum"],
        "candidate_score": candidate_score,
        "integrity_delta": integrity_check["integrity_delta"],
        "integrity_tolerance": integrity_check["integrity_tolerance"],
        "integrity_within_tolerance": integrity_check["integrity_within_tolerance"],
    }


def build_candidate_score_records(
    candidate_polygon_records: list[dict],
    candidate_feature_records: list[dict],
    tile_score_records: list[dict],
) -> list[dict]:
    feature_by_candidate_id = {
        feature_record["candidate_id"]: feature_record
        for feature_record in candidate_feature_records
    }
    tile_score_by_tile_id = {
        tile_score_record["tile_id"]: tile_score_record["tile_score"]
        for tile_score_record in tile_score_records
    }

    score_records = []
    for candidate_record in sorted(candidate_polygon_records, key=lambda item: item["candidate_id"]):
        feature_record = feature_by_candidate_id[candidate_record["candidate_id"]]
        parent_tile_score = round(tile_score_by_tile_id[candidate_record["parent_tile_id"]], 6)
        texture_support = compute_texture_support(feature_record["local_contrast_values"])
        compactness_support = compute_compactness_support(
            candidate_record["area_m2"],
            feature_record["convex_hull_area_m2"],
        )
        polygon_object_score = compute_polygon_object_score(
            texture_support,
            compactness_support,
        )
        candidate_score = compute_candidate_score(parent_tile_score, polygon_object_score)
        score_breakdown = build_candidate_score_breakdown(
            parent_tile_score,
            texture_support,
            compactness_support,
            polygon_object_score,
            candidate_score,
        )
        contribution_sum = score_breakdown["contribution_sum"]
        integrity_delta = score_breakdown["integrity_delta"]
        integrity_within_tolerance = bool(score_breakdown["integrity_within_tolerance"])
        score_records.append(
            {
                "candidate_id": candidate_record["candidate_id"],
                "run_id": candidate_record.get("run_id"),
                "polygonization_manifest_cache_key": candidate_record["polygonization_manifest_cache_key"],
                "source_scene_manifest_hash": candidate_record["source_scene_manifest_hash"],
                "source_endpoint_id": candidate_record["source_endpoint_id"],
                "parent_tile_id": candidate_record["parent_tile_id"],
                "parent_tile_score": parent_tile_score,
                "texture_support": texture_support,
                "compactness_support": compactness_support,
                "polygon_object_score": polygon_object_score,
                "candidate_score": candidate_score,
                "score_breakdown": score_breakdown,
                "contribution_sum": contribution_sum,
                "integrity_delta": integrity_delta,
                "integrity_within_tolerance": integrity_within_tolerance,
            }
        )
    return score_records


def rank_candidate_scores(candidate_score_records: list[dict]) -> list[dict]:
    ranked_records = []
    for rank_position, score_record in enumerate(
        sorted(
            candidate_score_records,
            key=lambda item: (-item["candidate_score"], -item["parent_tile_score"], item["candidate_id"]),
        ),
        start=1,
    ):
        ranked_record = dict(score_record)
        ranked_record["rank"] = rank_position
        ranked_records.append(ranked_record)
    return ranked_records
