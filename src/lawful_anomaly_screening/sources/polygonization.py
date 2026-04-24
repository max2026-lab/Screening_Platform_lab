from __future__ import annotations

import json
import math
from hashlib import sha256


def _stable_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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


def _union_bounds(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _centroid(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)


def _contains_point(
    bounds: tuple[float, float, float, float],
    point: tuple[float, float],
) -> bool:
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def _compute_iou(
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


def tile_bounds(tile_record: dict) -> tuple[float, float, float, float]:
    tile_size_m = float(tile_record["tile_size_m"])
    min_x = float(tile_record["x_index"]) * tile_size_m
    min_y = float(tile_record["y_index"]) * tile_size_m
    max_x = min_x + tile_size_m
    max_y = min_y + tile_size_m
    return (min_x, min_y, max_x, max_y)


def build_full_aoi_anomaly_raster_manifest(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    tile_records: list[dict],
) -> dict:
    sorted_tiles = sorted(tile_records, key=lambda tile: tile["tile_id"])
    selected_tiles = [tile for tile in sorted_tiles if tile["selected_for_polygonization"]]

    all_bounds = [tile_bounds(tile) for tile in sorted_tiles]
    full_aoi_bounds = (
        min(bounds[0] for bounds in all_bounds),
        min(bounds[1] for bounds in all_bounds),
        max(bounds[2] for bounds in all_bounds),
        max(bounds[3] for bounds in all_bounds),
    )

    return {
        "manifest_version": "phase1-full-aoi-anomaly-raster-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": composite_metadata_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": composite_metadata_manifest["source_endpoint_id"],
        "preprocessing_manifest_cache_key": composite_metadata_manifest["preprocessing_manifest_cache_key"],
        "composite_metadata_cache_key": composite_metadata_cache_key,
        "composite_season_window_name": composite_metadata_manifest["composite_season_window_name"],
        "full_aoi_bounds": list(full_aoi_bounds),
        "tile_count": len(sorted_tiles),
        "selected_tile_count": len(selected_tiles),
        "selected_tile_ids": [tile["tile_id"] for tile in selected_tiles],
        "selected_tiles": [
            {
                "tile_id": tile["tile_id"],
                "tile_score": tile["tile_score"],
                "bounds": list(tile_bounds(tile)),
            }
            for tile in selected_tiles
        ],
        "raster_reference": "synthetic://full-aoi-anomaly-raster",
    }


def build_default_anomaly_regions(full_aoi_anomaly_raster_manifest: dict) -> list[dict]:
    regions = []
    for selected_tile in full_aoi_anomaly_raster_manifest["selected_tiles"]:
        min_x, min_y, max_x, max_y = selected_tile["bounds"]
        margin_x = (max_x - min_x) * 0.15
        margin_y = (max_y - min_y) * 0.15
        regions.append(
            {
                "region_id": f"region-{selected_tile['tile_id'][:12]}",
                "bounds": [
                    round(min_x + margin_x, 6),
                    round(min_y + margin_y, 6),
                    round(max_x - margin_x, 6),
                    round(max_y - margin_y, 6),
                ],
            }
        )
    return regions


def _selected_overlap_ratio(
    polygon_bounds: tuple[float, float, float, float],
    selected_tiles: list[dict],
) -> float:
    polygon_area = _bounds_area(polygon_bounds)
    if polygon_area <= 0.0:
        return 0.0

    overlap_area = sum(
        _intersection_area(polygon_bounds, tuple(selected_tile["bounds"]))
        for selected_tile in selected_tiles
    )
    return round(overlap_area / polygon_area, 6)


def is_tile_edge_eligible(
    polygon_bounds: tuple[float, float, float, float],
    selected_tiles: list[dict],
) -> bool:
    polygon_centroid = _centroid(polygon_bounds)
    centroid_in_selected_tile = any(
        _contains_point(tuple(selected_tile["bounds"]), polygon_centroid)
        for selected_tile in selected_tiles
    )
    return centroid_in_selected_tile or _selected_overlap_ratio(polygon_bounds, selected_tiles) >= 0.30


def assign_parent_tile(
    polygon_bounds: tuple[float, float, float, float],
    selected_tiles: list[dict],
) -> str | None:
    polygon_centroid = _centroid(polygon_bounds)
    centroid_tiles = [
        selected_tile
        for selected_tile in selected_tiles
        if _contains_point(tuple(selected_tile["bounds"]), polygon_centroid)
    ]
    if centroid_tiles:
        ranked_centroid_tiles = sorted(
            centroid_tiles,
            key=lambda selected_tile: (
                -_intersection_area(polygon_bounds, tuple(selected_tile["bounds"])),
                selected_tile["tile_id"],
            ),
        )
        return ranked_centroid_tiles[0]["tile_id"]

    overlap_tiles = [
        selected_tile
        for selected_tile in selected_tiles
        if _intersection_area(polygon_bounds, tuple(selected_tile["bounds"])) > 0.0
    ]
    if not overlap_tiles:
        return None

    ranked_overlap_tiles = sorted(
        overlap_tiles,
        key=lambda selected_tile: (
            -_intersection_area(polygon_bounds, tuple(selected_tile["bounds"])),
            selected_tile["tile_id"],
        ),
    )
    return ranked_overlap_tiles[0]["tile_id"]


def _polygon_id(bounds: tuple[float, float, float, float], source_region_ids: list[str]) -> str:
    payload = {
        "bounds": [round(value, 6) for value in bounds],
        "source_region_ids": sorted(source_region_ids),
    }
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _build_polygon_candidate(
    *,
    polygon_bounds: tuple[float, float, float, float],
    source_region_ids: list[str],
    selected_tiles: list[dict],
    possible_duplicate: bool = False,
) -> dict | None:
    if not is_tile_edge_eligible(polygon_bounds, selected_tiles):
        return None

    polygon_centroid = _centroid(polygon_bounds)
    centroid_in_selected_tile = any(
        _contains_point(tuple(selected_tile["bounds"]), polygon_centroid)
        for selected_tile in selected_tiles
    )
    return {
        "polygon_id": _polygon_id(polygon_bounds, source_region_ids),
        "bounds": [round(value, 6) for value in polygon_bounds],
        "centroid": [round(value, 6) for value in polygon_centroid],
        "selected_overlap_ratio": _selected_overlap_ratio(polygon_bounds, selected_tiles),
        "centroid_in_selected_tile": centroid_in_selected_tile,
        "parent_tile_id": assign_parent_tile(polygon_bounds, selected_tiles),
        "possible_duplicate": possible_duplicate,
        "source_region_ids": sorted(source_region_ids),
    }


def deduplicate_polygon_candidates(
    polygon_candidates: list[dict],
    selected_tiles: list[dict],
) -> list[dict]:
    deduplicated: list[dict] = []
    for candidate in sorted(
        polygon_candidates,
        key=lambda item: (item["source_region_ids"], item["polygon_id"]),
    ):
        current_candidate = dict(candidate)
        merged = False
        for index, existing in enumerate(deduplicated):
            iou = _compute_iou(tuple(existing["bounds"]), tuple(current_candidate["bounds"]))
            if iou >= 0.30:
                merged_bounds = _union_bounds(
                    tuple(existing["bounds"]),
                    tuple(current_candidate["bounds"]),
                )
                merged_candidate = _build_polygon_candidate(
                    polygon_bounds=merged_bounds,
                    source_region_ids=existing["source_region_ids"] + current_candidate["source_region_ids"],
                    selected_tiles=selected_tiles,
                    possible_duplicate=False,
                )
                if merged_candidate is not None:
                    deduplicated[index] = merged_candidate
                merged = True
                break
            if 0.10 <= iou < 0.30:
                existing["possible_duplicate"] = True
                current_candidate["possible_duplicate"] = True
        if not merged:
            deduplicated.append(current_candidate)

    return sorted(deduplicated, key=lambda item: item["polygon_id"])


def polygonize_full_aoi(
    full_aoi_anomaly_raster_manifest: dict,
    anomaly_regions: list[dict] | None = None,
) -> list[dict]:
    selected_tiles = list(full_aoi_anomaly_raster_manifest["selected_tiles"])
    regions = anomaly_regions or build_default_anomaly_regions(full_aoi_anomaly_raster_manifest)

    polygon_candidates = []
    for region in sorted(regions, key=lambda item: item["region_id"]):
        candidate = _build_polygon_candidate(
            polygon_bounds=tuple(region["bounds"]),
            source_region_ids=[region["region_id"]],
            selected_tiles=selected_tiles,
        )
        if candidate is not None:
            polygon_candidates.append(candidate)

    return deduplicate_polygon_candidates(polygon_candidates, selected_tiles)


def build_polygonization_manifest(
    full_aoi_anomaly_raster_manifest: dict,
    full_aoi_anomaly_raster_cache_key: str,
    *,
    anomaly_regions: list[dict] | None = None,
) -> dict:
    polygons = polygonize_full_aoi(
        full_aoi_anomaly_raster_manifest,
        anomaly_regions=anomaly_regions,
    )
    return {
        "manifest_version": "phase1-polygonization-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": full_aoi_anomaly_raster_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": full_aoi_anomaly_raster_manifest["source_endpoint_id"],
        "composite_metadata_cache_key": full_aoi_anomaly_raster_manifest["composite_metadata_cache_key"],
        "full_aoi_anomaly_raster_cache_key": full_aoi_anomaly_raster_cache_key,
        "full_aoi_bounds": list(full_aoi_anomaly_raster_manifest["full_aoi_bounds"]),
        "polygon_count": len(polygons),
        "polygons": polygons,
    }


def _perimeter(bounds: tuple[float, float, float, float]) -> float:
    width = max(0.0, bounds[2] - bounds[0])
    height = max(0.0, bounds[3] - bounds[1])
    return (2.0 * width) + (2.0 * height)


def _touches_bounds_edge(
    bounds: tuple[float, float, float, float],
    container_bounds: tuple[float, float, float, float],
) -> bool:
    return (
        bounds[0] <= container_bounds[0]
        or bounds[1] <= container_bounds[1]
        or bounds[2] >= container_bounds[2]
        or bounds[3] >= container_bounds[3]
    )


def create_candidate_id(
    polygonization_manifest_cache_key: str,
    polygon_record: dict,
) -> str:
    payload = {
        "polygonization_manifest_cache_key": polygonization_manifest_cache_key,
        "parent_tile_id": polygon_record["parent_tile_id"],
        "bounds": [round(value, 6) for value in polygon_record["bounds"]],
        "source_region_ids": sorted(polygon_record["source_region_ids"]),
    }
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def build_candidate_polygon_records(
    polygonization_manifest: dict,
    polygonization_manifest_cache_key: str,
) -> list[dict]:
    full_aoi_bounds = tuple(polygonization_manifest["full_aoi_bounds"])
    candidate_records = []
    for polygon in sorted(
        polygonization_manifest["polygons"],
        key=lambda item: (item["parent_tile_id"] or "", item["polygon_id"]),
    ):
        polygon_bounds = tuple(polygon["bounds"])
        area_m2 = _bounds_area(polygon_bounds)
        perimeter_m = _perimeter(polygon_bounds)
        candidate_record = {
            "candidate_id": "",
            "polygonization_manifest_cache_key": polygonization_manifest_cache_key,
            "source_scene_manifest_hash": polygonization_manifest["source_scene_manifest_hash"],
            "source_endpoint_id": polygonization_manifest["source_endpoint_id"],
            "parent_tile_id": polygon["parent_tile_id"],
            "bounds": [round(value, 6) for value in polygon_bounds],
            "centroid": [round(value, 6) for value in polygon["centroid"]],
            "area_m2": round(area_m2, 6),
            "perimeter_m": round(perimeter_m, 6),
            "pixel_count": max(1, int(round(area_m2 / 100.0))),
            "boundary_touching": _touches_bounds_edge(polygon_bounds, full_aoi_bounds),
            "possible_duplicate": polygon["possible_duplicate"],
            "duplicate_resolution_action": (
                "review_possible_duplicate"
                if polygon["possible_duplicate"]
                else "keep"
            ),
            "source_region_ids": list(sorted(polygon["source_region_ids"])),
        }
        candidate_record["candidate_id"] = create_candidate_id(
            polygonization_manifest_cache_key,
            candidate_record,
        )
        candidate_records.append(candidate_record)
    return candidate_records


def build_candidate_feature_records(candidate_polygon_records: list[dict]) -> list[dict]:
    feature_records = []
    for candidate in sorted(candidate_polygon_records, key=lambda item: item["candidate_id"]):
        bounds = tuple(candidate["bounds"])
        width = max(0.0, bounds[2] - bounds[0])
        height = max(0.0, bounds[3] - bounds[1])
        area_m2 = candidate["area_m2"]
        perimeter_m = candidate["perimeter_m"]
        compactness_ratio = 0.0
        if perimeter_m > 0.0:
            compactness_ratio = max(
                0.0,
                min(1.0, (4.0 * math.pi * area_m2) / (perimeter_m * perimeter_m)),
            )
        convex_hull_area_m2 = area_m2
        shorter_side = min(width, height)
        elongation = 0.0 if shorter_side <= 0.0 else max(width, height) / shorter_side
        aspect_delta = 0.0 if (width + height) <= 0.0 else abs(width - height) / (width + height)
        water_edge_overlap_ratio = max(
            0.0,
            min(1.0, ((1.0 - compactness_ratio) * 0.6) + (0.2 if candidate["boundary_touching"] else 0.0)),
        )
        cloud_seam_overlap_ratio = max(
            0.0,
            min(
                1.0,
                (0.1 if candidate["possible_duplicate"] else 0.02) + (aspect_delta * 0.5),
            ),
        )
        feature_records.append(
            {
                "candidate_id": candidate["candidate_id"],
                "polygonization_manifest_cache_key": candidate["polygonization_manifest_cache_key"],
                "source_scene_manifest_hash": candidate["source_scene_manifest_hash"],
                "source_endpoint_id": candidate["source_endpoint_id"],
                "compactness_ratio": round(compactness_ratio, 6),
                "convex_hull_area_m2": round(convex_hull_area_m2, 6),
                "elongation": round(elongation, 6),
                "local_contrast_values": [
                    round((candidate["area_m2"] / candidate["pixel_count"]) / 100.0, 6),
                    round((candidate["perimeter_m"] / candidate["pixel_count"]) / 10.0, 6),
                    round(aspect_delta, 6),
                ],
                "water_edge_overlap_ratio": round(water_edge_overlap_ratio, 6),
                "cloud_seam_overlap_ratio": round(cloud_seam_overlap_ratio, 6),
            }
        )
    return feature_records
