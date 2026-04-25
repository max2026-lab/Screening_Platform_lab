from __future__ import annotations

from lawful_anomaly_screening.sources.manifest_builder import (
    build_composite_quality_metadata,
    resolve_cloud_policy_thresholds,
)


def _rounded(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    return round(float(value), 6)


def rank_items_by_score(
    rows: list[dict],
    *,
    id_key: str,
    primary_score_key: str,
    secondary_score_key: str | None = None,
) -> dict[str, int]:
    ranked = sorted(
        rows,
        key=lambda row: (
            -float(row.get(primary_score_key) or 0.0),
            -float(row.get(secondary_score_key) or 0.0) if secondary_score_key else 0.0,
            str(row[id_key]),
        ),
    )
    return {
        str(row[id_key]): index
        for index, row in enumerate(ranked, start=1)
    }


def build_scoring_reason(
    *,
    rank: int | None,
    candidate_score: float | None,
    parent_tile_score: float | None,
    polygon_object_score: float | None,
    optical_anomaly: float | None,
    persistence: float | None,
    cloud_penalty: float | None,
    noise_penalty: float | None,
    source_scene_count: int,
    boundary_touching: bool,
    area_m2: float | None,
) -> str:
    fragments: list[str] = []
    if rank is not None:
        fragments.append(f"rank {rank}")
    if candidate_score is not None:
        fragments.append(f"candidate score {candidate_score:.6f}")
    if parent_tile_score is not None:
        fragments.append(f"parent tile score {parent_tile_score:.6f}")
    if polygon_object_score is not None:
        fragments.append(f"polygon object score {polygon_object_score:.6f}")

    tile_signal_fragments = []
    if optical_anomaly is not None:
        tile_signal_fragments.append(f"optical {optical_anomaly:.6f}")
    if persistence is not None:
        tile_signal_fragments.append(f"persistence {persistence:.6f}")
    if cloud_penalty is not None:
        tile_signal_fragments.append(f"cloud penalty {cloud_penalty:.6f}")
    if noise_penalty is not None:
        tile_signal_fragments.append(f"noise penalty {noise_penalty:.6f}")
    if tile_signal_fragments:
        fragments.append("tile signals " + ", ".join(tile_signal_fragments))

    fragments.append(f"{source_scene_count} source scenes")
    fragments.append(f"boundary touching {'yes' if boundary_touching else 'no'}")
    if area_m2 is not None:
        fragments.append(f"area {area_m2:.6f} m2")
    return "; ".join(fragments)


def build_candidate_scoring_explanation(
    *,
    candidate_score: float | None,
    parent_tile_score: float | None,
    score_formula_version: str | None,
    rank: int | None,
    parent_tile_rank: int | None,
    texture_support: float | None,
    compactness_support: float | None,
    polygon_object_score: float | None,
    weighted_parent_tile_score: float | None,
    weighted_polygon_object_score: float | None,
    optical_anomaly: float | None,
    persistence: float | None,
    cloud_penalty: float | None,
    noise_penalty: float | None,
    source_scene_ids: list[str],
    source_scenes: list[dict] | None,
    boundary_touching: bool,
    area_m2: float | None,
) -> dict:
    composite_quality = None
    if source_scenes:
        composite_quality = build_composite_quality_metadata(
            source_scenes,
            cloud_policy_thresholds=resolve_cloud_policy_thresholds(),
        )

    ordered_source_scene_ids = sorted(str(scene_id) for scene_id in source_scene_ids)
    explanation = {
        "candidate_score": _rounded(candidate_score),
        "parent_tile_score": _rounded(parent_tile_score),
        "score_formula_version": score_formula_version,
        "rank": rank,
        "parent_tile_rank": parent_tile_rank,
        "component_scores": {
            "texture_support": _rounded(texture_support),
            "compactness_support": _rounded(compactness_support),
            "polygon_object_score": _rounded(polygon_object_score),
            "optical_anomaly": _rounded(optical_anomaly),
            "persistence": _rounded(persistence),
            "weighted_parent_tile_score": _rounded(weighted_parent_tile_score),
            "weighted_polygon_object_score": _rounded(weighted_polygon_object_score),
        },
        "penalties": {
            "cloud_penalty": _rounded(cloud_penalty),
            "noise_penalty": _rounded(noise_penalty),
        },
        "source_scene_count": len(ordered_source_scene_ids),
        "source_scene_ids": ordered_source_scene_ids,
        "composite_quality": composite_quality,
        "boundary_touching": bool(boundary_touching),
        "area_m2": _rounded(area_m2),
    }
    explanation["reason"] = build_scoring_reason(
        rank=rank,
        candidate_score=(
            float(explanation["candidate_score"])
            if explanation["candidate_score"] is not None
            else None
        ),
        parent_tile_score=(
            float(explanation["parent_tile_score"])
            if explanation["parent_tile_score"] is not None
            else None
        ),
        polygon_object_score=(
            float(explanation["component_scores"]["polygon_object_score"])
            if explanation["component_scores"]["polygon_object_score"] is not None
            else None
        ),
        optical_anomaly=(
            float(explanation["component_scores"]["optical_anomaly"])
            if explanation["component_scores"]["optical_anomaly"] is not None
            else None
        ),
        persistence=(
            float(explanation["component_scores"]["persistence"])
            if explanation["component_scores"]["persistence"] is not None
            else None
        ),
        cloud_penalty=(
            float(explanation["penalties"]["cloud_penalty"])
            if explanation["penalties"]["cloud_penalty"] is not None
            else None
        ),
        noise_penalty=(
            float(explanation["penalties"]["noise_penalty"])
            if explanation["penalties"]["noise_penalty"] is not None
            else None
        ),
        source_scene_count=explanation["source_scene_count"],
        boundary_touching=bool(explanation["boundary_touching"]),
        area_m2=float(explanation["area_m2"]) if explanation["area_m2"] is not None else None,
    )
    return explanation
