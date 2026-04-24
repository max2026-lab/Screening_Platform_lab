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

    aoi_hash = sha256(json.dumps(geom, sort_keys=True).encode("utf-8")).hexdigest()

    return {
        "aoi_path": resolved_path.as_posix(),
        "aoi_geometry_type": geom["type"],
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


def validate_aoi(_: object) -> bool:
    # Keep the existing stub if needed, but we probably want to use validate_aoi_file
    return True
