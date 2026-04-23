from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import discover_scenes, load_endpoint_registry


def _stable_manifest_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_manifest(
    source_endpoint_id: str | None = None,
    *,
    scenes: list[dict] | None = None,
) -> dict:
    registry = load_endpoint_registry()
    endpoint = registry.endpoints[source_endpoint_id or registry.primary_endpoint_id]
    manifest_scenes = scenes if scenes is not None else discover_scenes(endpoint.endpoint_id, registry=registry)
    normalized_scenes = sorted(
        [
            {
                "scene_id": scene["scene_id"],
                "acquired_at": scene["acquired_at"],
                "cloud_cover": scene["cloud_cover"],
            }
            for scene in manifest_scenes
        ],
        key=lambda scene: scene["scene_id"],
    )
    return {
        "manifest_version": "phase1-scene-manifest-v1",
        "execution_mode": "synchronous",
        "source_endpoint_id": endpoint.endpoint_id,
        "source_name": endpoint.provider,
        "scene_count": len(normalized_scenes),
        "scenes": normalized_scenes,
    }


def create_source_scene_manifest_hash(manifest: dict) -> str:
    return sha256(_stable_manifest_json(manifest).encode("utf-8")).hexdigest()


def manifest_payload_reference(manifest_hash: str, root: Path | str = Path("data/manifests")) -> str:
    return (Path(root) / f"{manifest_hash}.json").as_posix()
