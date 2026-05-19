from __future__ import annotations

import json
import math
from hashlib import sha256


def _stable_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


MIN_REVIEW_CANDIDATE_PIXEL_COUNT = 3
MIN_REVIEW_CANDIDATE_AREA_M2 = 1e-6
MIN_REVIEW_CANDIDATE_PERIMETER_M = 1e-6


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
    if tile_record.get("bounds") is not None:
        bounds = tile_record["bounds"]
        return tuple(float(value) for value in bounds)

    tile_size_m = float(tile_record["tile_size_m"])
    min_x = float(tile_record["x_index"]) * tile_size_m
    min_y = float(tile_record["y_index"]) * tile_size_m
    max_x = min_x + tile_size_m
    max_y = min_y + tile_size_m
    return (min_x, min_y, max_x, max_y)


def _rect_corners(bounds: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    min_x, min_y, max_x, max_y = bounds
    return [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]


def _rect_edges(bounds: tuple[float, float, float, float]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    corners = _rect_corners(bounds)
    return [
        (corners[0], corners[1]),
        (corners[1], corners[2]),
        (corners[2], corners[3]),
        (corners[3], corners[0]),
    ]


def _iter_polygon_rings(aoi_geometry: dict | None) -> list[list[tuple[float, float]]]:
    if not aoi_geometry:
        return []

    geometry_type = aoi_geometry.get("type")
    coordinates = aoi_geometry.get("coordinates", [])
    if geometry_type == "Polygon":
        return [
            [tuple(float(value) for value in point) for point in ring]
            for ring in coordinates
        ]
    if geometry_type == "MultiPolygon":
        return [
            [tuple(float(value) for value in point) for point in ring]
            for polygon in coordinates
            for ring in polygon
        ]
    return []


def _cross_product(
    left: tuple[float, float],
    middle: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return ((middle[0] - left[0]) * (right[1] - left[1])) - ((middle[1] - left[1]) * (right[0] - left[0]))


def _point_on_segment(
    point: tuple[float, float],
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
    *,
    tolerance: float = 1e-9,
) -> bool:
    if abs(_cross_product(segment_start, segment_end, point)) > tolerance:
        return False
    return (
        min(segment_start[0], segment_end[0]) - tolerance <= point[0] <= max(segment_start[0], segment_end[0]) + tolerance
        and min(segment_start[1], segment_end[1]) - tolerance <= point[1] <= max(segment_start[1], segment_end[1]) + tolerance
    )


def _point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    inside = False
    for index in range(len(ring)):
        segment_start = ring[index]
        segment_end = ring[(index + 1) % len(ring)]
        if _point_on_segment(point, segment_start, segment_end):
            return True
        if (segment_start[1] > point[1]) != (segment_end[1] > point[1]):
            x_intercept = segment_start[0] + (
                (point[1] - segment_start[1]) * (segment_end[0] - segment_start[0]) / (segment_end[1] - segment_start[1])
            )
            if x_intercept >= point[0]:
                inside = not inside
    return inside


def _point_in_geometry(point: tuple[float, float], aoi_geometry: dict | None) -> bool:
    rings = _iter_polygon_rings(aoi_geometry)
    return any(_point_in_ring(point, ring) for ring in rings)


def _point_on_geometry_boundary(point: tuple[float, float], aoi_geometry: dict | None) -> bool:
    for ring in _iter_polygon_rings(aoi_geometry):
        for index in range(len(ring)):
            if _point_on_segment(point, ring[index], ring[(index + 1) % len(ring)]):
                return True
    return False


def _segment_intersection_points(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
    *,
    tolerance: float = 1e-9,
) -> list[tuple[float, float]]:
    intersections: list[tuple[float, float]] = []
    denominator = (
        (first_start[0] - first_end[0]) * (second_start[1] - second_end[1])
        - (first_start[1] - first_end[1]) * (second_start[0] - second_end[0])
    )
    if abs(denominator) <= tolerance:
        for point in (first_start, first_end, second_start, second_end):
            if _point_on_segment(point, first_start, first_end) and _point_on_segment(point, second_start, second_end):
                intersections.append(point)
        return intersections

    determinant_first = (first_start[0] * first_end[1]) - (first_start[1] * first_end[0])
    determinant_second = (second_start[0] * second_end[1]) - (second_start[1] * second_end[0])
    point = (
        ((determinant_first * (second_start[0] - second_end[0])) - ((first_start[0] - first_end[0]) * determinant_second)) / denominator,
        ((determinant_first * (second_start[1] - second_end[1])) - ((first_start[1] - first_end[1]) * determinant_second)) / denominator,
    )
    if _point_on_segment(point, first_start, first_end) and _point_on_segment(point, second_start, second_end):
        intersections.append(point)
    return intersections


def _clipped_bounds_from_geometry(
    bounds: tuple[float, float, float, float],
    aoi_geometry: dict | None,
) -> tuple[tuple[float, float, float, float] | None, bool]:
    if not aoi_geometry:
        return bounds, False

    clipped_points: list[tuple[float, float]] = []
    boundary_touching = False

    rect_corners = _rect_corners(bounds)
    for corner in rect_corners:
        if _point_in_geometry(corner, aoi_geometry):
            clipped_points.append(corner)
            boundary_touching = boundary_touching or _point_on_geometry_boundary(corner, aoi_geometry)

    for ring in _iter_polygon_rings(aoi_geometry):
        for point in ring:
            if _contains_point(bounds, point):
                clipped_points.append(point)
                boundary_touching = True

        for index in range(len(ring)):
            polygon_start = ring[index]
            polygon_end = ring[(index + 1) % len(ring)]
            for rect_start, rect_end in _rect_edges(bounds):
                intersections = _segment_intersection_points(polygon_start, polygon_end, rect_start, rect_end)
                if intersections:
                    clipped_points.extend(intersections)
                    boundary_touching = True

    if not clipped_points:
        return None, False

    clipped_bounds = (
        max(bounds[0], min(point[0] for point in clipped_points)),
        max(bounds[1], min(point[1] for point in clipped_points)),
        min(bounds[2], max(point[0] for point in clipped_points)),
        min(bounds[3], max(point[1] for point in clipped_points)),
    )
    if clipped_bounds[2] <= clipped_bounds[0] or clipped_bounds[3] <= clipped_bounds[1]:
        return None, False
    if clipped_bounds != bounds:
        boundary_touching = True
    return clipped_bounds, boundary_touching


def tile_intersects_aoi(
    bounds: tuple[float, float, float, float] | list[float],
    aoi_geometry: dict | None,
) -> bool:
    clipped_bounds, _ = _clipped_bounds_from_geometry(
        tuple(float(value) for value in bounds),
        aoi_geometry,
    )
    return clipped_bounds is not None


def _subdivision_count(bounds: tuple[float, float, float, float]) -> int:
    width = max(0.0, bounds[2] - bounds[0])
    height = max(0.0, bounds[3] - bounds[1])
    return max(8, min(24, int(math.ceil(max(width, height) / 25.0))))


def _cell_inside_geometry(
    bounds: tuple[float, float, float, float],
    aoi_geometry: dict,
) -> bool:
    corners = _rect_corners(bounds)
    center = _centroid(bounds)
    points = corners + [center]
    return all(_point_in_geometry(point, aoi_geometry) for point in points)


def _row_spans(occupied_cells: list[list[bool]]) -> list[list[tuple[int, int]]]:
    spans_by_row: list[list[tuple[int, int]]] = []
    for row in occupied_cells:
        row_spans: list[tuple[int, int]] = []
        start_column: int | None = None
        for column, occupied in enumerate(row):
            if occupied and start_column is None:
                start_column = column
            if not occupied and start_column is not None:
                row_spans.append((start_column, column))
                start_column = None
        if start_column is not None:
            row_spans.append((start_column, len(row)))
        spans_by_row.append(row_spans)
    return spans_by_row


def _merge_rectangles(
    occupied_cells: list[list[bool]],
    bounds: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    if not occupied_cells:
        return []

    row_count = len(occupied_cells)
    column_count = len(occupied_cells[0])
    cell_width = (bounds[2] - bounds[0]) / column_count
    cell_height = (bounds[3] - bounds[1]) / row_count
    spans_by_row = _row_spans(occupied_cells)

    rectangles: list[tuple[float, float, float, float]] = []
    active_spans: dict[tuple[int, int], int] = {}
    for row_index, row_spans in enumerate(spans_by_row):
        next_active_spans: dict[tuple[int, int], int] = {}
        for span in row_spans:
            next_active_spans[span] = active_spans.get(span, row_index)
        for span, start_row in active_spans.items():
            if span in next_active_spans:
                continue
            rectangles.append(
                (
                    round(bounds[0] + (span[0] * cell_width), 6),
                    round(bounds[1] + (start_row * cell_height), 6),
                    round(bounds[0] + (span[1] * cell_width), 6),
                    round(bounds[1] + (row_index * cell_height), 6),
                )
            )
        active_spans = next_active_spans

    for span, start_row in active_spans.items():
        rectangles.append(
            (
                round(bounds[0] + (span[0] * cell_width), 6),
                round(bounds[1] + (start_row * cell_height), 6),
                round(bounds[0] + (span[1] * cell_width), 6),
                round(bounds[1] + (row_count * cell_height), 6),
            )
        )
    return rectangles


def _rectangles_to_geometry(rectangles: list[tuple[float, float, float, float]]) -> dict | None:
    if not rectangles:
        return None
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [[
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]]
            for min_x, min_y, max_x, max_y in rectangles
        ],
    }


def _geometry_rectangles(geometry: dict | None) -> list[tuple[float, float, float, float]]:
    if not geometry:
        return []
    if geometry.get("type") == "MultiPolygon":
        rectangles = []
        for polygon in geometry.get("coordinates", []):
            ring = polygon[0]
            xs = [float(point[0]) for point in ring]
            ys = [float(point[1]) for point in ring]
            rectangles.append((min(xs), min(ys), max(xs), max(ys)))
        return rectangles
    return []


def _geometry_bounds(geometry: dict) -> tuple[float, float, float, float]:
    rectangles = _geometry_rectangles(geometry)
    return (
        min(rectangle[0] for rectangle in rectangles),
        min(rectangle[1] for rectangle in rectangles),
        max(rectangle[2] for rectangle in rectangles),
        max(rectangle[3] for rectangle in rectangles),
    )


def _geometry_area(geometry: dict) -> float:
    return sum(_bounds_area(rectangle) for rectangle in _geometry_rectangles(geometry))


def _geometry_centroid(geometry: dict) -> tuple[float, float]:
    rectangles = _geometry_rectangles(geometry)
    total_area = _geometry_area(geometry)
    if total_area <= 0.0:
        return _centroid(_geometry_bounds(geometry))

    centroid_x = 0.0
    centroid_y = 0.0
    for rectangle in rectangles:
        area = _bounds_area(rectangle)
        rectangle_centroid = _centroid(rectangle)
        centroid_x += rectangle_centroid[0] * area
        centroid_y += rectangle_centroid[1] * area
    return (centroid_x / total_area, centroid_y / total_area)


def _geometry_perimeter(geometry: dict) -> float:
    rectangles = _geometry_rectangles(geometry)
    if not rectangles:
        return 0.0
    unique_x = sorted({rectangle[0] for rectangle in rectangles} | {rectangle[2] for rectangle in rectangles})
    unique_y = sorted({rectangle[1] for rectangle in rectangles} | {rectangle[3] for rectangle in rectangles})
    if len(unique_x) < 2 or len(unique_y) < 2:
        return 0.0

    occupied_cells = {
        (x_index, y_index)
        for x_index in range(len(unique_x) - 1)
        for y_index in range(len(unique_y) - 1)
        if any(
            rectangle[0] <= unique_x[x_index]
            and rectangle[2] >= unique_x[x_index + 1]
            and rectangle[1] <= unique_y[y_index]
            and rectangle[3] >= unique_y[y_index + 1]
            for rectangle in rectangles
        )
    }

    perimeter = 0.0
    for x_index, y_index in occupied_cells:
        cell_width = unique_x[x_index + 1] - unique_x[x_index]
        cell_height = unique_y[y_index + 1] - unique_y[y_index]
        if (x_index - 1, y_index) not in occupied_cells:
            perimeter += cell_height
        if (x_index + 1, y_index) not in occupied_cells:
            perimeter += cell_height
        if (x_index, y_index - 1) not in occupied_cells:
            perimeter += cell_width
        if (x_index, y_index + 1) not in occupied_cells:
            perimeter += cell_width
    return perimeter


def _build_clipped_geometry(
    bounds: tuple[float, float, float, float],
    aoi_geometry: dict | None,
) -> tuple[dict | None, bool]:
    if not aoi_geometry:
        return _rectangles_to_geometry([bounds]), False

    subdivision_count = _subdivision_count(bounds)
    cell_width = (bounds[2] - bounds[0]) / subdivision_count
    cell_height = (bounds[3] - bounds[1]) / subdivision_count
    occupied_cells: list[list[bool]] = []
    boundary_touching = False

    for row_index in range(subdivision_count):
        row: list[bool] = []
        for column_index in range(subdivision_count):
            cell_bounds = (
                bounds[0] + (column_index * cell_width),
                bounds[1] + (row_index * cell_height),
                bounds[0] + ((column_index + 1) * cell_width),
                bounds[1] + ((row_index + 1) * cell_height),
            )
            inside = _cell_inside_geometry(cell_bounds, aoi_geometry)
            row.append(inside)
            if inside and any(_point_on_geometry_boundary(corner, aoi_geometry) for corner in _rect_corners(cell_bounds)):
                boundary_touching = True
            if not inside and _point_in_geometry(_centroid(cell_bounds), aoi_geometry):
                boundary_touching = True
        occupied_cells.append(row)

    if not any(any(row) for row in occupied_cells):
        return None, False

    if not all(all(row) for row in occupied_cells):
        boundary_touching = True

    merged_rectangles = _merge_rectangles(occupied_cells, bounds)
    return _rectangles_to_geometry(merged_rectangles), boundary_touching


def build_full_aoi_anomaly_raster_manifest(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    tile_records: list[dict],
    *,
    aoi_geometry: dict | None = None,
    aoi_bbox: list[float] | None = None,
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
        "aoi_geometry": aoi_geometry,
        "aoi_bbox": list(aoi_bbox) if aoi_bbox is not None else None,
        "full_aoi_bounds": list(full_aoi_bounds),
        "tile_count": len(sorted_tiles),
        "valid_tile_count": sum(1 for tile in sorted_tiles if tile["is_valid"]),
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
    aoi_geometry = full_aoi_anomaly_raster_manifest.get("aoi_geometry")
    for selected_tile in full_aoi_anomaly_raster_manifest["selected_tiles"]:
        clipped_tile_bounds, _ = _clipped_bounds_from_geometry(
            tuple(selected_tile["bounds"]),
            aoi_geometry,
        )
        if clipped_tile_bounds is None:
            continue
        min_x, min_y, max_x, max_y = clipped_tile_bounds
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


def build_default_anomaly_regions_with_diagnostics(
    full_aoi_anomaly_raster_manifest: dict,
) -> tuple[list[dict], dict[str, int | float | str | None]]:
    regions = []
    aoi_geometry = full_aoi_anomaly_raster_manifest.get("aoi_geometry")
    default_region_attempt_count = 0
    default_region_clipped_out_by_aoi_count = 0
    default_region_zero_area_after_margin_count = 0
    for selected_tile in full_aoi_anomaly_raster_manifest["selected_tiles"]:
        default_region_attempt_count += 1
        clipped_tile_bounds, _ = _clipped_bounds_from_geometry(
            tuple(selected_tile["bounds"]),
            aoi_geometry,
        )
        if clipped_tile_bounds is None:
            default_region_clipped_out_by_aoi_count += 1
            continue
        min_x, min_y, max_x, max_y = clipped_tile_bounds
        margin_x = (max_x - min_x) * 0.15
        margin_y = (max_y - min_y) * 0.15
        region_bounds = [
            round(min_x + margin_x, 6),
            round(min_y + margin_y, 6),
            round(max_x - margin_x, 6),
            round(max_y - margin_y, 6),
        ]
        if region_bounds[2] <= region_bounds[0] or region_bounds[3] <= region_bounds[1]:
            default_region_zero_area_after_margin_count += 1
        regions.append(
            {
                "region_id": f"region-{selected_tile['tile_id'][:12]}",
                "bounds": region_bounds,
            }
        )
    selected_tiles = list(full_aoi_anomaly_raster_manifest["selected_tiles"])
    selected_tile_scores = sorted(float(tile["tile_score"]) for tile in selected_tiles)
    selected_tile_score_mean = (
        round(sum(selected_tile_scores) / len(selected_tile_scores), 6)
        if selected_tile_scores
        else None
    )
    diagnostics: dict[str, int | float | str | None] = {
        "diagnostic_version": "v1",
        "anomaly_region_source": "default_selected_tile_regions",
        "selected_tile_count": len(selected_tiles),
        "selected_tile_score_min": selected_tile_scores[0] if selected_tile_scores else None,
        "selected_tile_score_max": selected_tile_scores[-1] if selected_tile_scores else None,
        "selected_tile_score_mean": selected_tile_score_mean,
        "selected_tile_bounds_count": sum(
            1 for tile in selected_tiles if tile.get("bounds") is not None
        ),
        "default_region_attempt_count": default_region_attempt_count,
        "default_region_created_count": len(regions),
        "default_region_clipped_out_by_aoi_count": default_region_clipped_out_by_aoi_count,
        "default_region_zero_area_after_margin_count": default_region_zero_area_after_margin_count,
        "anomaly_region_input_count": len(regions),
        "raw_polygon_count": len(regions),
        "raw_polygon_zero_reason": "",
        "aoi_tile_alignment_diagnostics": _tile_alignment_stats(
            full_aoi_anomaly_raster_manifest
        ),
    }
    return regions, diagnostics


def _tile_alignment_stats(
    full_aoi_anomaly_raster_manifest: dict,
) -> dict[str, int | float | str | bool | None]:
    aoi_geometry = full_aoi_anomaly_raster_manifest.get("aoi_geometry")
    selected_tiles = list(full_aoi_anomaly_raster_manifest["selected_tiles"])
    selected_tile_scores = sorted(float(tile["tile_score"]) for tile in selected_tiles)
    overlap_ratios: list[float] = []
    selected_tile_centroid_inside_aoi_count = 0
    selected_tile_intersects_aoi_count = 0
    selected_tile_clipped_out_by_aoi_count = 0

    for selected_tile in selected_tiles:
        tile_bounds = tuple(float(value) for value in selected_tile["bounds"])
        tile_area = _bounds_area(tile_bounds)
        tile_centroid = _centroid(tile_bounds)
        clipped_tile_bounds, _ = _clipped_bounds_from_geometry(tile_bounds, aoi_geometry)
        if _point_in_geometry(tile_centroid, aoi_geometry):
            selected_tile_centroid_inside_aoi_count += 1
        if clipped_tile_bounds is None:
            selected_tile_clipped_out_by_aoi_count += 1
            overlap_ratios.append(0.0)
            continue
        selected_tile_intersects_aoi_count += 1
        clipped_area = _bounds_area(clipped_tile_bounds)
        overlap_ratios.append(
            round(clipped_area / tile_area, 6) if tile_area > 0.0 else 0.0
        )

    if not selected_tiles:
        alignment_warning = "no_selected_tiles"
    elif selected_tile_intersects_aoi_count == 0:
        alignment_warning = "selected_tiles_do_not_intersect_aoi"
    elif selected_tile_intersects_aoi_count < len(selected_tiles):
        alignment_warning = "selected_tiles_partially_intersect_aoi"
    else:
        alignment_warning = "none"

    return {
        "diagnostic_version": "v1",
        "aoi_geometry_type": aoi_geometry.get("type") if isinstance(aoi_geometry, dict) else None,
        "tile_count": int(full_aoi_anomaly_raster_manifest.get("tile_count", 0)),
        "valid_tile_count": int(full_aoi_anomaly_raster_manifest.get("valid_tile_count", 0)),
        "selected_tile_count": len(selected_tiles),
        "selected_tile_with_bounds_count": sum(
            1 for tile in selected_tiles if tile.get("bounds") is not None
        ),
        "selected_tile_centroid_inside_aoi_count": selected_tile_centroid_inside_aoi_count,
        "selected_tile_intersects_aoi_count": selected_tile_intersects_aoi_count,
        "selected_tile_clipped_out_by_aoi_count": selected_tile_clipped_out_by_aoi_count,
        "selected_tile_overlap_ratio_min": min(overlap_ratios) if overlap_ratios else None,
        "selected_tile_overlap_ratio_max": max(overlap_ratios) if overlap_ratios else None,
        "selected_tile_overlap_ratio_mean": (
            round(sum(overlap_ratios) / len(overlap_ratios), 6)
            if overlap_ratios
            else None
        ),
        "selected_tile_score_min": selected_tile_scores[0] if selected_tile_scores else None,
        "selected_tile_score_max": selected_tile_scores[-1] if selected_tile_scores else None,
        "selected_tile_score_mean": (
            round(sum(selected_tile_scores) / len(selected_tile_scores), 6)
            if selected_tile_scores
            else None
        ),
        "derived_tile_bbox_present": bool(
            full_aoi_anomaly_raster_manifest.get("full_aoi_bounds")
        ),
        "aoi_bbox_present": full_aoi_anomaly_raster_manifest.get("aoi_bbox") is not None,
        "alignment_warning": alignment_warning,
    }


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


def _polygon_id(bounds: tuple[float, float, float, float], source_region_ids: list[str], clipped_geometry: dict | None) -> str:
    payload = {
        "bounds": [round(value, 6) for value in bounds],
        "clipped_geometry": clipped_geometry,
        "source_region_ids": sorted(source_region_ids),
    }
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _build_polygon_candidate(
    *,
    polygon_bounds: tuple[float, float, float, float],
    source_region_ids: list[str],
    selected_tiles: list[dict],
    aoi_geometry: dict | None = None,
    possible_duplicate: bool = False,
) -> dict | None:
    clipped_geometry, aoi_boundary_touching = _build_clipped_geometry(polygon_bounds, aoi_geometry)
    if clipped_geometry is None:
        return None

    clipped_bounds = _geometry_bounds(clipped_geometry)
    if not is_tile_edge_eligible(clipped_bounds, selected_tiles):
        return None

    polygon_centroid = _geometry_centroid(clipped_geometry)
    centroid_in_selected_tile = any(
        _contains_point(tuple(selected_tile["bounds"]), polygon_centroid)
        for selected_tile in selected_tiles
    )
    return {
        "polygon_id": _polygon_id(clipped_bounds, source_region_ids, clipped_geometry),
        "bounds": [round(value, 6) for value in clipped_bounds],
        "centroid": [round(value, 6) for value in polygon_centroid],
        "clipped_geometry": clipped_geometry,
        "selected_overlap_ratio": _selected_overlap_ratio(clipped_bounds, selected_tiles),
        "centroid_in_selected_tile": centroid_in_selected_tile,
        "parent_tile_id": assign_parent_tile(clipped_bounds, selected_tiles),
        "aoi_boundary_touching": aoi_boundary_touching,
        "possible_duplicate": possible_duplicate,
        "source_region_ids": sorted(source_region_ids),
    }


def deduplicate_polygon_candidates(
    polygon_candidates: list[dict],
    selected_tiles: list[dict],
    *,
    aoi_geometry: dict | None = None,
    return_diagnostics: bool = False,
) -> list[dict] | tuple[list[dict], dict[str, int]]:
    deduplicated: list[dict] = []
    duplicate_merged_count = 0
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
                    aoi_geometry=aoi_geometry,
                    possible_duplicate=False,
                )
                if merged_candidate is not None:
                    deduplicated[index] = merged_candidate
                    duplicate_merged_count += 1
                merged = True
                break
            if 0.10 <= iou < 0.30:
                existing["possible_duplicate"] = True
                current_candidate["possible_duplicate"] = True
        if not merged:
            deduplicated.append(current_candidate)

    deduplicated = sorted(deduplicated, key=lambda item: item["polygon_id"])
    diagnostics = {
        "duplicate_merged_count": duplicate_merged_count,
        "possible_duplicate_count": sum(
            1 for item in deduplicated if item["possible_duplicate"]
        ),
    }
    if return_diagnostics:
        return deduplicated, diagnostics
    return deduplicated


def polygonize_full_aoi(
    full_aoi_anomaly_raster_manifest: dict,
    anomaly_regions: list[dict] | None = None,
    *,
    return_diagnostics: bool = False,
) -> list[dict] | tuple[list[dict], dict[str, int]]:
    selected_tiles = list(full_aoi_anomaly_raster_manifest["selected_tiles"])
    aoi_geometry = full_aoi_anomaly_raster_manifest.get("aoi_geometry")
    selected_tile_scores = sorted(float(tile["tile_score"]) for tile in selected_tiles)
    raw_polygonization_diagnostics: dict[str, int | float | str | None] = {
        "diagnostic_version": "v1",
        "anomaly_region_source": "provided_anomaly_regions" if anomaly_regions is not None else "default_selected_tile_regions",
        "selected_tile_count": len(selected_tiles),
        "selected_tile_score_min": selected_tile_scores[0] if selected_tile_scores else None,
        "selected_tile_score_max": selected_tile_scores[-1] if selected_tile_scores else None,
        "selected_tile_score_mean": (
            round(sum(selected_tile_scores) / len(selected_tile_scores), 6)
            if selected_tile_scores
            else None
        ),
        "selected_tile_bounds_count": sum(
            1 for tile in selected_tiles if tile.get("bounds") is not None
        ),
        "default_region_attempt_count": 0,
        "default_region_created_count": 0,
        "default_region_clipped_out_by_aoi_count": 0,
        "default_region_zero_area_after_margin_count": 0,
        "anomaly_region_input_count": 0,
        "raw_polygon_count": 0,
        "raw_polygon_zero_reason": "",
        "aoi_tile_alignment_diagnostics": _tile_alignment_stats(
            full_aoi_anomaly_raster_manifest
        ),
    }
    if anomaly_regions is None:
        regions, raw_polygonization_diagnostics = build_default_anomaly_regions_with_diagnostics(
            full_aoi_anomaly_raster_manifest
        )
    else:
        regions = anomaly_regions
        raw_polygonization_diagnostics["anomaly_region_input_count"] = len(regions)
        raw_polygonization_diagnostics["raw_polygon_count"] = len(regions)

    polygon_candidates = []
    dropped_tile_edge_eligibility_count = 0
    for region in sorted(regions, key=lambda item: item["region_id"]):
        candidate = _build_polygon_candidate(
            polygon_bounds=tuple(region["bounds"]),
            source_region_ids=[region["region_id"]],
            selected_tiles=selected_tiles,
            aoi_geometry=aoi_geometry,
        )
        if candidate is not None:
            polygon_candidates.append(candidate)
        else:
            dropped_tile_edge_eligibility_count += 1

    deduplicated, dedup_diagnostics = deduplicate_polygon_candidates(
        polygon_candidates,
        selected_tiles,
        aoi_geometry=aoi_geometry,
        return_diagnostics=True,
    )
    diagnostics = {
        "raw_polygon_count": len(regions),
        "dropped_tile_edge_eligibility_count": dropped_tile_edge_eligibility_count,
        "raw_polygonization_diagnostics": raw_polygonization_diagnostics,
        **dedup_diagnostics,
    }
    raw_polygon_zero_reason = "no_anomaly_regions_generated"
    if int(raw_polygonization_diagnostics["raw_polygon_count"] or 0) > 0:
        raw_polygon_zero_reason = "raw_polygons_generated"
    elif int(raw_polygonization_diagnostics["selected_tile_count"] or 0) == 0:
        raw_polygon_zero_reason = "no_selected_tiles"
    elif (
        int(raw_polygonization_diagnostics["default_region_attempt_count"] or 0) > 0
        and int(raw_polygonization_diagnostics["default_region_created_count"] or 0) == 0
        and int(raw_polygonization_diagnostics["default_region_clipped_out_by_aoi_count"] or 0) > 0
    ):
        raw_polygon_zero_reason = "selected_tiles_clipped_out_by_aoi"
    elif (
        int(raw_polygonization_diagnostics["default_region_attempt_count"] or 0) > 0
        and int(raw_polygonization_diagnostics["default_region_created_count"] or 0) == 0
        and int(raw_polygonization_diagnostics["default_region_zero_area_after_margin_count"] or 0) > 0
    ):
        raw_polygon_zero_reason = "selected_tiles_zero_area_after_margin"
    raw_polygonization_diagnostics["raw_polygon_zero_reason"] = raw_polygon_zero_reason
    if return_diagnostics:
        return deduplicated, diagnostics
    return deduplicated


def build_polygonization_manifest(
    full_aoi_anomaly_raster_manifest: dict,
    full_aoi_anomaly_raster_cache_key: str,
    *,
    anomaly_regions: list[dict] | None = None,
) -> dict:
    polygons, polygonization_diagnostics = polygonize_full_aoi(
        full_aoi_anomaly_raster_manifest,
        anomaly_regions=anomaly_regions,
        return_diagnostics=True,
    )
    return {
        "manifest_version": "phase1-polygonization-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": full_aoi_anomaly_raster_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": full_aoi_anomaly_raster_manifest["source_endpoint_id"],
        "composite_metadata_cache_key": full_aoi_anomaly_raster_manifest["composite_metadata_cache_key"],
        "full_aoi_anomaly_raster_cache_key": full_aoi_anomaly_raster_cache_key,
        "aoi_geometry": full_aoi_anomaly_raster_manifest.get("aoi_geometry"),
        "aoi_bbox": full_aoi_anomaly_raster_manifest.get("aoi_bbox"),
        "full_aoi_bounds": list(full_aoi_anomaly_raster_manifest["full_aoi_bounds"]),
        "polygon_count": len(polygons),
        "polygonization_diagnostics": polygonization_diagnostics,
        "polygons": polygons,
    }


def _perimeter(bounds: tuple[float, float, float, float]) -> float:
    width = max(0.0, bounds[2] - bounds[0])
    height = max(0.0, bounds[3] - bounds[1])
    return (2.0 * width) + (2.0 * height)


def _passes_candidate_sanity_filter(candidate_record: dict) -> bool:
    """Return True if the candidate is non-degenerate and reviewable."""
    if candidate_record["pixel_count"] < MIN_REVIEW_CANDIDATE_PIXEL_COUNT:
        return False
    if candidate_record["area_m2"] <= MIN_REVIEW_CANDIDATE_AREA_M2:
        return False
    if candidate_record["perimeter_m"] <= MIN_REVIEW_CANDIDATE_PERIMETER_M:
        return False
    bounds = candidate_record["bounds"]
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        return False
    clipped_geometry = candidate_record.get("clipped_geometry")
    if clipped_geometry is not None:
        geom_area = _geometry_area(clipped_geometry)
        if geom_area <= 0.0:
            return False
        for rect in _geometry_rectangles(clipped_geometry):
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                return False
    return True


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
        "run_id": polygon_record.get("run_id"),
        "polygonization_manifest_cache_key": polygonization_manifest_cache_key,
        "parent_tile_id": polygon_record["parent_tile_id"],
        "bounds": [round(value, 6) for value in polygon_record["bounds"]],
        "clipped_geometry": polygon_record.get("clipped_geometry"),
        "source_region_ids": sorted(polygon_record["source_region_ids"]),
    }
    return sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def build_candidate_polygon_records(
    polygonization_manifest: dict,
    polygonization_manifest_cache_key: str,
    *,
    run_id: str | None = None,
    source_scene_ids: list[str] | None = None,
    tile_source_scene_ids_by_tile_id: dict[str, list[str]] | None = None,
    return_diagnostics: bool = False,
) -> list[dict] | tuple[list[dict], dict[str, int]]:
    full_aoi_bounds = tuple(polygonization_manifest["full_aoi_bounds"])
    candidate_source_scene_ids = list(sorted(source_scene_ids or []))
    candidate_records = []
    dropped_below_min_area_count = 0
    dropped_below_pixel_floor_count = 0
    for polygon in sorted(
        polygonization_manifest["polygons"],
        key=lambda item: (item["parent_tile_id"] or "", item["polygon_id"]),
    ):
        polygon_bounds = tuple(polygon["bounds"])
        clipped_geometry = polygon.get("clipped_geometry")
        area_m2 = _geometry_area(clipped_geometry) if clipped_geometry is not None else _bounds_area(polygon_bounds)
        perimeter_m = _geometry_perimeter(clipped_geometry) if clipped_geometry is not None else _perimeter(polygon_bounds)
        parent_tile_id = polygon["parent_tile_id"]
        parent_tile_source_scene_ids = candidate_source_scene_ids
        if tile_source_scene_ids_by_tile_id is not None and parent_tile_id is not None:
            parent_tile_source_scene_ids = list(
                sorted(tile_source_scene_ids_by_tile_id.get(parent_tile_id, []))
            )
        candidate_record = {
            "candidate_id": "",
            "run_id": run_id,
            "polygonization_manifest_cache_key": polygonization_manifest_cache_key,
            "source_scene_manifest_hash": polygonization_manifest["source_scene_manifest_hash"],
            "source_endpoint_id": polygonization_manifest["source_endpoint_id"],
            "parent_tile_id": parent_tile_id,
            "source_scene_ids": parent_tile_source_scene_ids,
            "bounds": [round(value, 6) for value in polygon_bounds],
            "centroid": [round(value, 6) for value in polygon["centroid"]],
            "clipped_geometry": clipped_geometry,
            "area_m2": round(area_m2, 6),
            "perimeter_m": round(perimeter_m, 6),
            "pixel_count": max(0, int(round(area_m2 / 100.0))),
            "boundary_touching": (
                _touches_bounds_edge(polygon_bounds, full_aoi_bounds)
                or polygon.get("aoi_boundary_touching", False)
            ),
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
        if _passes_candidate_sanity_filter(candidate_record):
            candidate_records.append(candidate_record)
            continue
        if candidate_record["area_m2"] <= MIN_REVIEW_CANDIDATE_AREA_M2:
            dropped_below_min_area_count += 1
        if candidate_record["pixel_count"] < MIN_REVIEW_CANDIDATE_PIXEL_COUNT:
            dropped_below_pixel_floor_count += 1
    diagnostics = {
        "dropped_below_min_area_count": dropped_below_min_area_count,
        "dropped_below_pixel_floor_count": dropped_below_pixel_floor_count,
    }
    if return_diagnostics:
        return candidate_records, diagnostics
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
                "run_id": candidate.get("run_id"),
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
