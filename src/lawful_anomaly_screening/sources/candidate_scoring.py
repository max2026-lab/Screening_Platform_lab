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


def compute_texture_support(local_contrast_inputs: dict[str, float]) -> float:
    ring_mean_delta = _clamp(local_contrast_inputs.get("ring_mean_delta", 0.0), 0.0, 1.0)
    local_variance_proxy = _clamp(local_contrast_inputs.get("local_variance_proxy", 0.0), 0.0, 1.0)
    neighbor_contrast_proxy = _clamp(local_contrast_inputs.get("neighbor_contrast_proxy", 0.0), 0.0, 1.0)
    raw_support = (
        (8.0 * ring_mean_delta)
        + (4.0 * local_variance_proxy)
        + (3.0 * neighbor_contrast_proxy)
    )
    return round(_clamp(raw_support, 0.0, 15.0), 6)


def compute_compactness_support(
    compactness_ratio: float,
    elongation: float,
) -> float:
    normalized_compactness = _clamp(compactness_ratio, 0.0, 1.0)
    normalized_elongation_support = 1.0 - _clamp((max(elongation, 1.0) - 1.0) / 4.0, 0.0, 1.0)
    raw_support = (6.0 * normalized_compactness) + (4.0 * normalized_elongation_support)
    return round(_clamp(raw_support, 0.0, 10.0), 6)


def compute_polygon_object_score(
    texture_support: float,
    compactness_support: float,
) -> float:
    return round(_clamp(texture_support + compactness_support, 0.0, 25.0), 6)


def compute_candidate_score(
    parent_tile_score: float,
    polygon_object_score: float,
) -> float:
    return round(_clamp(parent_tile_score + polygon_object_score, 0.0, 100.0), 6)


def build_candidate_score_breakdown(
    parent_tile_score: float,
    texture_support: float,
    compactness_support: float,
    polygon_object_score: float,
    candidate_score: float,
) -> dict:
    contribution_sum = round(parent_tile_score + polygon_object_score, 6)
    integrity_delta = round(abs(contribution_sum - candidate_score), 6)
    return {
        "parent_tile_score": round(parent_tile_score, 6),
        "texture_support": texture_support,
        "compactness_support": compactness_support,
        "polygon_object_score": polygon_object_score,
        "contribution_sum": contribution_sum,
        "candidate_score": candidate_score,
        "integrity_delta": integrity_delta,
        "integrity_tolerance": SCORE_TOLERANCE,
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
        texture_support = compute_texture_support(feature_record["local_contrast_inputs"])
        compactness_support = compute_compactness_support(
            feature_record["compactness_ratio"],
            feature_record["elongation"],
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
        score_records.append(
            {
                "candidate_id": candidate_record["candidate_id"],
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
                "integrity_within_tolerance": integrity_delta <= SCORE_TOLERANCE,
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
