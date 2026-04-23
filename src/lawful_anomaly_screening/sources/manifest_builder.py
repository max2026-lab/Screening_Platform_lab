from __future__ import annotations

import math
from hashlib import sha256
import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import discover_scenes, load_endpoint_registry

PREPROCESSING_CONFIG_PATH = Path("config/sources/preprocessing.json")
RETAINED_TILE_SCORE_FIELDS = (
    "optical_anomaly",
    "persistence",
    "cloud_penalty",
    "noise_penalty",
)


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


def is_valid_composite_season(
    preprocessing_manifest: dict,
    composite_season_window_name: str,
    *,
    preprocessing_config: dict | None = None,
) -> bool:
    config = preprocessing_config or load_preprocessing_config()
    if composite_season_window_name not in config["season_windows"]:
        return False
    return composite_season_window_name == preprocessing_manifest["season_window_name"]


def build_composite_metadata_manifest(
    preprocessing_manifest: dict,
    preprocessing_manifest_cache_key: str,
    *,
    composite_season_window_name: str,
    preprocessing_config: dict | None = None,
) -> dict:
    config = preprocessing_config or load_preprocessing_config()
    if not is_valid_composite_season(
        preprocessing_manifest,
        composite_season_window_name,
        preprocessing_config=config,
    ):
        raise ValueError(f"invalid composite season: {composite_season_window_name}")

    return {
        "manifest_version": "phase1-composite-metadata-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": preprocessing_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": preprocessing_manifest["source_endpoint_id"],
        "preprocessing_manifest_cache_key": preprocessing_manifest_cache_key,
        "preprocessing_season_window_name": preprocessing_manifest["season_window_name"],
        "composite_season_window_name": composite_season_window_name,
        "season_window": config["season_windows"][composite_season_window_name],
        "cloud_mask": preprocessing_manifest["cloud_mask"],
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


def create_tile_id(tile_payload: dict) -> str:
    digest_input = {
        "source_scene_manifest_hash": tile_payload["source_scene_manifest_hash"],
        "source_endpoint_id": tile_payload["source_endpoint_id"],
        "composite_metadata_cache_key": tile_payload["composite_metadata_cache_key"],
        "tile_size_m": tile_payload["tile_size_m"],
        "x_index": tile_payload["x_index"],
        "y_index": tile_payload["y_index"],
    }
    return sha256(_stable_manifest_json(digest_input).encode("utf-8")).hexdigest()


def build_tile_feature_input(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    *,
    x_index: int,
    y_index: int,
    tile_size_m: int = 320,
) -> dict:
    tile_payload = {
        "manifest_version": "phase1-tile-feature-input-v1",
        "execution_mode": "synchronous",
        "source_scene_manifest_hash": composite_metadata_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": composite_metadata_manifest["source_endpoint_id"],
        "preprocessing_manifest_cache_key": composite_metadata_manifest["preprocessing_manifest_cache_key"],
        "composite_metadata_cache_key": composite_metadata_cache_key,
        "composite_season_window_name": composite_metadata_manifest["composite_season_window_name"],
        "tile_size_m": tile_size_m,
        "x_index": x_index,
        "y_index": y_index,
        "is_valid": (x_index + y_index) % 5 != 0,
    }
    tile_payload["tile_id"] = create_tile_id(tile_payload)
    return tile_payload


def generate_fixed_tile_grid(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    *,
    tile_size_m: int = 320,
    width: int = 4,
    height: int = 5,
) -> list[dict]:
    tiles = [
        build_tile_feature_input(
            composite_metadata_manifest,
            composite_metadata_cache_key,
            x_index=x_index,
            y_index=y_index,
            tile_size_m=tile_size_m,
        )
        for y_index in range(height)
        for x_index in range(width)
    ]
    return sorted(tiles, key=lambda tile: tile["tile_id"])


def score_retained_tile(tile_feature_input: dict) -> dict:
    x_index = tile_feature_input["x_index"]
    y_index = tile_feature_input["y_index"]
    optical_anomaly = round(0.45 + (x_index * 0.04) + (y_index * 0.02), 6)
    persistence = round(0.35 + (y_index * 0.03), 6)
    cloud_penalty = round(0.01 * ((x_index + y_index) % 4), 6)
    noise_penalty = round(0.005 * ((x_index * 2 + y_index) % 5), 6)
    retained_score = round(
        optical_anomaly + persistence - cloud_penalty - noise_penalty,
        6,
    )
    return {
        "tile_id": tile_feature_input["tile_id"],
        "source_scene_manifest_hash": tile_feature_input["source_scene_manifest_hash"],
        "source_endpoint_id": tile_feature_input["source_endpoint_id"],
        "composite_metadata_cache_key": tile_feature_input["composite_metadata_cache_key"],
        "tile_feature_input_cache_key": tile_feature_input["tile_feature_input_cache_key"],
        "tile_size_m": tile_feature_input["tile_size_m"],
        "x_index": tile_feature_input["x_index"],
        "y_index": tile_feature_input["y_index"],
        "is_valid": tile_feature_input["is_valid"],
        "optical_anomaly": optical_anomaly,
        "persistence": persistence,
        "cloud_penalty": cloud_penalty,
        "noise_penalty": noise_penalty,
        "retained_score": retained_score,
        "top_valid_selection_flag": False,
    }


def flag_top_valid_tiles(tile_records: list[dict]) -> list[dict]:
    valid_tiles = [tile for tile in tile_records if tile["is_valid"]]
    selected_count = 0 if not valid_tiles else max(1, math.ceil(len(valid_tiles) * 0.15))
    ranked_valid = sorted(
        valid_tiles,
        key=lambda tile: (-tile["retained_score"], tile["tile_id"]),
    )
    selected_ids = {tile["tile_id"] for tile in ranked_valid[:selected_count]}

    flagged_tiles = []
    for tile in tile_records:
        updated = dict(tile)
        updated["top_valid_selection_flag"] = tile["tile_id"] in selected_ids
        flagged_tiles.append(updated)
    return flagged_tiles
