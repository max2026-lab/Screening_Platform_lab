from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from lawful_anomaly_screening.settings import load_settings
from lawful_anomaly_screening.exceptions import SourceError


def _has_active_stac_config(endpoint: SourceEndpoint) -> bool:
    extra = endpoint.extra
    return bool(
        extra.get("active") is True
        and extra.get("base_url")
        and extra.get("metadata_only") is True
    )


def _bbox_from_aoi_hash(aoi_hash: str | None) -> list[float] | None:
    """Return a minimal bbox placeholder when aoi_hash is present."""
    if not aoi_hash:
        return None
    # deterministic pseudo-bbox from hash for smoke stability
    digest = sha256(aoi_hash.encode("utf-8")).hexdigest()
    lon = -120.0 + (int(digest[:4], 16) % 40)
    lat = 35.0 + (int(digest[4:8], 16) % 10)
    size = 0.05 + (int(digest[8:12], 16) % 50) / 1000.0
    return [round(lon, 6), round(lat, 6), round(lon + size, 6), round(lat + size, 6)]


@dataclass(frozen=True)
class SourceEndpoint:
    endpoint_id: str
    provider: str
    role: str
    synchronous_only: bool
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EndpointRegistry:
    primary_endpoint_id: str
    fallback_endpoint_ids: tuple[str, ...]
    endpoints: dict[str, SourceEndpoint]

    @property
    def primary_endpoint(self) -> SourceEndpoint:
        return self.endpoints[self.primary_endpoint_id]

    @property
    def fallback_endpoints(self) -> list[SourceEndpoint]:
        return [self.endpoints[endpoint_id] for endpoint_id in self.fallback_endpoint_ids]


def load_endpoint_registry(path: Path | str | None = None) -> EndpointRegistry:
    resolved_path = Path(path) if path is not None else load_settings().endpoints_path
    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SourceError(f"failed to load endpoint config: {exc}")

    if "primary" not in data or "fallbacks" not in data:
        raise SourceError("invalid endpoint config: missing 'primary' or 'fallbacks' key")

    endpoint_ids = [data["primary"], *data["fallbacks"]]
    endpoints = {}
    for endpoint_id in endpoint_ids:
        if endpoint_id not in data:
            raise SourceError(f"invalid endpoint config: definition for '{endpoint_id}' missing")

        config = data[endpoint_id]
        try:
            extra = {
                k: v for k, v in config.items()
                if k not in ("provider", "role", "synchronous_only")
            }
            endpoints[endpoint_id] = SourceEndpoint(
                endpoint_id=endpoint_id,
                provider=config["provider"],
                role=config["role"],
                synchronous_only=bool(config["synchronous_only"]),
                extra=extra,
            )
        except KeyError as exc:
            raise SourceError(f"invalid endpoint config for '{endpoint_id}': missing {exc}")

    return EndpointRegistry(
        primary_endpoint_id=data["primary"],
        fallback_endpoint_ids=tuple(data["fallbacks"]),
        endpoints=endpoints,
    )


def discover_scenes(
    source_endpoint_id: str | None = None,
    *,
    registry: EndpointRegistry | None = None,
    aoi_hash: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    active_registry = registry or load_endpoint_registry()
    endpoint_id = source_endpoint_id or active_registry.primary_endpoint_id
    if endpoint_id not in active_registry.endpoints:
        raise SourceError(f"unknown source endpoint: {endpoint_id}")

    endpoint = active_registry.endpoints[endpoint_id]

    # Real STAC path: only when explicitly active and metadata-only
    if _has_active_stac_config(endpoint):
        from .stac_client import query_stac_search
        extra = endpoint.extra
        return query_stac_search(
            base_url=extra["base_url"],
            search_path=extra.get("search_path", "search"),
            collections=extra.get("collections"),
            bbox=_bbox_from_aoi_hash(aoi_hash),
            start_date=start_date,
            end_date=end_date,
            max_items=extra.get("max_items", 10),
            timeout_seconds=extra.get("timeout_seconds", 30),
        )

    # Simulation hook for empty results
    if aoi_hash == "all_fail_discovery_trigger":
        return []
    if aoi_hash == "empty_discovery_trigger" and endpoint_id == "earth_search":
        return []
    if endpoint.provider == "simulator-empty":
        return []

    discovery_seed = sha256(
        json.dumps(
            {
                "source_endpoint_id": endpoint_id,
                "aoi_hash": aoi_hash,
                "start_date": start_date,
                "end_date": end_date,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ).hexdigest()
    if start_date and end_date:
        try:
            window_start = datetime.strptime(start_date, "%Y-%m-%d").date()
            window_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SourceError(f"invalid date format: {exc}")
    else:
        window_start = date(2024, 1, 1)
        window_end = date(2024, 1, 31)

    window_span_days = max(0, (window_end - window_start).days)
    scenes = []
    for index in range(3):
        token = discovery_seed[index * 16:(index + 1) * 16]

        # Simulation hook for malformed records
        if endpoint.provider == "simulator-malformed" or (aoi_hash == "malformed_discovery_trigger" and index == 1 and endpoint_id == "earth_search"):
            scenes.append({"scene_id": f"{endpoint_id}-malformed-{token}"}) # missing fields
            continue

        acquired_offset = 0 if window_span_days == 0 else int(token[:2], 16) % (window_span_days + 1)
        acquired_on = window_start + timedelta(days=acquired_offset)
        cloud_cover = round((int(token[2:6], 16) % 300) / 10.0, 1)
        scenes.append(
            {
                "scene_id": f"{endpoint_id}-scene-{token}",
                "acquired_at": f"{acquired_on.isoformat()}T00:00:00Z",
                "cloud_cover": cloud_cover,
            }
        )
    return sorted(scenes, key=lambda scene: scene["scene_id"])


def fetch_scenes(source_endpoint_id: str | None = None) -> list[dict]:
    return discover_scenes(source_endpoint_id=source_endpoint_id)
