from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from lawful_anomaly_screening.settings import load_settings


@dataclass(frozen=True)
class SourceEndpoint:
    endpoint_id: str
    provider: str
    role: str
    synchronous_only: bool


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
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    endpoint_ids = [data["primary"], *data["fallbacks"]]
    endpoints = {
        endpoint_id: SourceEndpoint(
            endpoint_id=endpoint_id,
            provider=data[endpoint_id]["provider"],
            role=data[endpoint_id]["role"],
            synchronous_only=bool(data[endpoint_id]["synchronous_only"]),
        )
        for endpoint_id in endpoint_ids
    }
    return EndpointRegistry(
        primary_endpoint_id=data["primary"],
        fallback_endpoint_ids=tuple(data["fallbacks"]),
        endpoints=endpoints,
    )


def discover_scenes(
    source_endpoint_id: str | None = None,
    *,
    registry: EndpointRegistry | None = None,
) -> list[dict]:
    active_registry = registry or load_endpoint_registry()
    endpoint_id = source_endpoint_id or active_registry.primary_endpoint_id
    if endpoint_id not in active_registry.endpoints:
        raise ValueError(f"unknown endpoint: {endpoint_id}")

    # Stubbed discovery stays deterministic so manifest hashing remains stable in tests.
    scenes = [
        {
            "scene_id": f"{endpoint_id}-scene-001",
            "acquired_at": "2024-01-01T00:00:00Z",
            "cloud_cover": 8.5,
        },
        {
            "scene_id": f"{endpoint_id}-scene-002",
            "acquired_at": "2024-01-03T00:00:00Z",
            "cloud_cover": 12.0,
        },
    ]
    return sorted(scenes, key=lambda scene: scene["scene_id"])


def fetch_scenes(source_endpoint_id: str | None = None) -> list[dict]:
    return discover_scenes(source_endpoint_id=source_endpoint_id)
