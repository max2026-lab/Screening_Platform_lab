from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any


def validate_aoi_file(path: Path | str) -> dict[str, Any]:
    resolved_path = Path(path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"AOI file not found: {resolved_path}")

    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in AOI file: {exc}")

    geom = _extract_geometry(data)
    if geom["type"] not in ["Polygon", "MultiPolygon"]:
        raise ValueError(f"AOI geometry must be Polygon or MultiPolygon, got {geom['type']}")

    bbox = _calculate_bbox(geom)
    if bbox == [0.0, 0.0, 0.0, 0.0]:
        raise ValueError("AOI geometry is empty")

    canonical_geometry = canonicalize_aoi_geometry(geom)
    aoi_hash = sha256(_canonical_geometry_json(canonical_geometry).encode("utf-8")).hexdigest()

    return {
        "aoi_path": resolved_path.as_posix(),
        "aoi_geometry": canonical_geometry,
        "aoi_geometry_type": canonical_geometry["type"],
        "aoi_bbox": bbox,
        "aoi_hash": aoi_hash,
    }


def _extract_geometry(data: dict[str, Any]) -> dict[str, Any]:
    data_type = data.get("type")
    if data_type == "FeatureCollection":
        features = data.get("features", [])
        if not features:
            raise ValueError("Empty FeatureCollection in AOI file")
        if len(features) > 1:
            raise ValueError("FeatureCollection must contain exactly one feature")
        return features[0].get("geometry", {})
    if data_type == "Feature":
        return data.get("geometry", {})
    if data_type in ["Polygon", "MultiPolygon"]:
        return data
    raise ValueError(f"AOI geometry must be Polygon or MultiPolygon, got {data_type}")


def _calculate_bbox(geom: dict[str, Any]) -> list[float]:
    coords = []
    if geom["type"] == "Polygon":
        for ring in geom["coordinates"]:
            coords.extend(ring)
    elif geom["type"] == "MultiPolygon":
        for polygon in geom["coordinates"]:
            for ring in polygon:
                coords.extend(ring)
    
    if not coords:
        return [0.0, 0.0, 0.0, 0.0]

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [float(min(lons)), float(min(lats)), float(max(lons)), float(max(lats))]


def extract_bbox_from_geojson(data: dict[str, Any]) -> list[float]:
    """Extract a [min_lon, min_lat, max_lon, max_lat] bbox from GeoJSON data.

    Supports Polygon, MultiPolygon, Feature, and FeatureCollection.
    Assumes WGS84 lon/lat. Raises ValueError for unsupported or empty geometry.
    """
    geom = _extract_geometry(data)
    if geom["type"] not in ["Polygon", "MultiPolygon"]:
        raise ValueError(f"AOI geometry must be Polygon or MultiPolygon, got {geom['type']}")
    bbox = _calculate_bbox(geom)
    if bbox == [0.0, 0.0, 0.0, 0.0]:
        raise ValueError("AOI geometry is empty")
    return bbox


def validate_aoi(_: object) -> bool:
    # Keep the existing stub if needed, but we probably want to use validate_aoi_file
    return True


def canonicalize_aoi_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    return json.loads(_canonical_geometry_json(geometry))


def derive_execution_geometry_summary(
    aoi_geometry: dict[str, Any] | None,
    aoi_bbox: list[float] | None,
    *,
    base_tile_size_m: int = 320,
) -> dict[str, Any]:
    if not aoi_bbox:
        return {
            "aoi_bbox": None,
            "derived_tile_bbox": [0.0, 0.0, 1280.0, 1600.0],
            "grid_width": 4,
            "grid_height": 5,
            "tile_size_m": base_tile_size_m,
            "geometry_complexity": 0,
        }

    min_lon, min_lat, max_lon, max_lat = aoi_bbox
    span_lon = max(max_lon - min_lon, 0.0001)
    span_lat = max(max_lat - min_lat, 0.0001)
    canonical_geometry = canonicalize_aoi_geometry(aoi_geometry) if aoi_geometry else None
    geometry_complexity = _count_geometry_vertices(canonical_geometry)
    geometry_digest = (
        sha256(_canonical_geometry_json(canonical_geometry).encode("utf-8")).hexdigest()
        if canonical_geometry
        else "0" * 64
    )
    hash_width_bias = int(geometry_digest[:2], 16) % 2
    hash_height_bias = int(geometry_digest[2:4], 16) % 2
    width = max(2, min(8, int(round(span_lon)) + 2 + hash_width_bias))
    height = max(
        2,
        min(8, int(round(span_lat)) + 2 + (1 if geometry_complexity > 5 else 0) + hash_height_bias),
    )
    expansion_x = 1.0 + ((int(geometry_digest[4:6], 16) % 3) / 14.0)
    expansion_y = 1.0 + ((int(geometry_digest[6:8], 16) % 3) / 14.0)

    derived_tile_bbox = [
        round(min_lon, 6),
        round(min_lat, 6),
        round(min_lon + (width * span_lon * expansion_x / max(1, width - 1)), 6),
        round(min_lat + (height * span_lat * expansion_y / max(1, height - 1)), 6),
    ]

    return {
        "aoi_bbox": [round(value, 6) for value in aoi_bbox],
        "aoi_geometry_type": canonical_geometry["type"] if canonical_geometry else None,
        "derived_tile_bbox": derived_tile_bbox,
        "grid_width": width,
        "grid_height": height,
        "tile_size_m": base_tile_size_m,
        "geometry_complexity": geometry_complexity,
    }


def _count_geometry_vertices(aoi_geometry: dict[str, Any] | None) -> int:
    if not aoi_geometry:
        return 0
    geom_type = aoi_geometry.get("type")
    coordinates = aoi_geometry.get("coordinates", [])
    if geom_type == "Polygon":
        return sum(len(ring) for ring in coordinates)
    if geom_type == "MultiPolygon":
        return sum(len(ring) for polygon in coordinates for ring in polygon)
    return 0


def _canonical_geometry_json(geometry: dict[str, Any] | None) -> str:
    return json.dumps(geometry, sort_keys=True, separators=(",", ":"))
