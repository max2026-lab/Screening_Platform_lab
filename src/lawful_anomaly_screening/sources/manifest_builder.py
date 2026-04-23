from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import discover_scenes, load_endpoint_registry

PREPROCESSING_CONFIG_PATH = Path("config/sources/preprocessing.json")


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


def load_preprocessing_config(path: Path | str = PREPROCESSING_CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_preprocessing_manifest(
    source_scene_manifest_hash: str,
    source_endpoint_id: str,
    *,
    season_window_name: str = "leaf_on",
    preprocessing_config: dict | None = None,
) -> dict:
    config = preprocessing_config or load_preprocessing_config()
    season_window = config["season_windows"][season_window_name]
    return {
        "manifest_version": "phase1-cache-preprocess-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": source_scene_manifest_hash,
        "source_endpoint_id": source_endpoint_id,
        "season_window_name": season_window_name,
        "season_window": season_window,
        "cloud_mask": config["cloud_mask"],
    }


def create_cache_key(asset_kind: str, payload: dict) -> str:
    digest_input = {
        "asset_kind": asset_kind,
        "payload": payload,
    }
    return sha256(_stable_manifest_json(digest_input).encode("utf-8")).hexdigest()


def cache_asset_reference(
    cache_key: str,
    asset_kind: str,
    root: Path | str = Path("data/cache"),
) -> str:
    return (Path(root) / asset_kind / f"{cache_key}.json").as_posix()
