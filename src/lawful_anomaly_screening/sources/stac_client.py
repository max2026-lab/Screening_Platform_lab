from __future__ import annotations

import json
from urllib import request
from urllib.error import URLError, HTTPError

from lawful_anomaly_screening.exceptions import SourceError


def _build_stac_search_url(
    base_url: str,
    search_path: str,
) -> str:
    base = base_url.rstrip("/")
    path = search_path.lstrip("/")
    return f"{base}/{path}"


def _normalize_stac_item(item: dict) -> dict:
    """Normalize a single STAC item into the internal discovered-scene format."""
    properties = item.get("properties", {})
    cloud_cover = properties.get("eo:cloud_cover")
    if cloud_cover is None:
        cloud_cover = properties.get("cloud_cover")
    try:
        cloud_cover = float(cloud_cover)
    except (TypeError, ValueError):
        cloud_cover = None

    datetime_str = properties.get("datetime")
    if not datetime_str:
        datetime_str = properties.get("start_datetime")

    return {
        "scene_id": item.get("id"),
        "acquired_at": datetime_str,
        "cloud_cover": cloud_cover,
        "collection": item.get("collection"),
        "provider_item_id": item.get("id"),
    }


def query_stac_search(
    *,
    base_url: str,
    search_path: str = "search",
    collections: list[str] | None = None,
    bbox: list[float] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_items: int = 10,
    timeout_seconds: int = 30,
) -> list[dict]:
    """Query a STAC /search endpoint and return normalized scene records."""
    url = _build_stac_search_url(base_url, search_path)

    payload: dict = {
        "limit": max_items,
    }
    if collections:
        payload["collections"] = collections
    if bbox:
        payload["bbox"] = bbox
    if start_date or end_date:
        payload["datetime"] = f"{start_date or '..'}/{end_date or '..'})"

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/geo+json",
    }

    req = request.Request(url, data=data, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SourceError(f"STAC search HTTP error {exc.code}: {exc.reason}")
    except URLError as exc:
        raise SourceError(f"STAC search URL error: {exc.reason}")

    try:
        geojson = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceError(f"STAC search returned invalid JSON: {exc}")

    features = geojson.get("features", [])
    if not features:
        raise SourceError("STAC search returned no usable scenes")

    normalized = []
    for item in features:
        try:
            normalized.append(_normalize_stac_item(item))
        except Exception:
            continue

    if not normalized:
        raise SourceError("STAC search returned no usable scenes after normalization")

    # Sort deterministically by scene_id for stable hashing
    normalized.sort(key=lambda scene: scene["scene_id"] or "")
    return normalized
