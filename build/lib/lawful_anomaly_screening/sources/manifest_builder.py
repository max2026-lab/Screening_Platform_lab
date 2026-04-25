from __future__ import annotations

import math
from hashlib import sha256
import json
from pathlib import Path

from lawful_anomaly_screening.settings import load_settings
from lawful_anomaly_screening.sources.earth_search import discover_scenes, load_endpoint_registry

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
    aoi_hash: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    registry = load_endpoint_registry()
    endpoint = registry.endpoints[source_endpoint_id or registry.primary_endpoint_id]
    manifest_scenes = scenes if scenes is not None else discover_scenes(
        endpoint.endpoint_id,
        registry=registry,
        aoi_hash=aoi_hash,
        start_date=start_date,
        end_date=end_date,
    )
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
        "manifest_version": "phase4-aoi-manifest-v1",
        "execution_mode": "synchronous",
        "source_endpoint_id": endpoint.endpoint_id,
        "source_name": endpoint.provider,
        "aoi_hash": aoi_hash,
        "start_date": start_date,
        "end_date": end_date,
        "scene_count": len(normalized_scenes),
        "scenes": normalized_scenes,
    }


def create_source_scene_manifest_hash(manifest: dict) -> str:
    return sha256(_stable_manifest_json(manifest).encode("utf-8")).hexdigest()


def manifest_payload_reference(manifest_hash: str, root: Path | str = Path("data/manifests")) -> str:
    return (Path(root) / f"{manifest_hash}.json").as_posix()


def load_preprocessing_config(path: Path | str | None = None) -> dict:
    resolved_path = Path(path) if path is not None else load_settings().preprocessing_config_path
    return json.loads(resolved_path.read_text(encoding="utf-8"))


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
        "run_id": tile_payload.get("run_id"),
        "source_scene_manifest_hash": tile_payload["source_scene_manifest_hash"],
        "source_endpoint_id": tile_payload["source_endpoint_id"],
        "composite_metadata_cache_key": tile_payload["composite_metadata_cache_key"],
        "tile_size_m": tile_payload["tile_size_m"],
        "grid_bounds": tile_payload.get("grid_bounds"),
        "tile_bounds": tile_payload.get("bounds"),
        "x_index": tile_payload["x_index"],
        "y_index": tile_payload["y_index"],
    }
    return sha256(_stable_manifest_json(digest_input).encode("utf-8")).hexdigest()


def build_tile_feature_input(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    *,
    run_id: str | None = None,
    x_index: int,
    y_index: int,
    tile_size_m: int = 320,
    grid_bounds: list[float] | None = None,
    tile_bounds: list[float] | None = None,
) -> dict:
    tile_payload = {
        "manifest_version": "phase1-tile-feature-input-v1",
        "execution_mode": "synchronous",
        "run_id": run_id,
        "source_scene_manifest_hash": composite_metadata_manifest["source_scene_manifest_hash"],
        "source_endpoint_id": composite_metadata_manifest["source_endpoint_id"],
        "preprocessing_manifest_cache_key": composite_metadata_manifest["preprocessing_manifest_cache_key"],
        "composite_metadata_cache_key": composite_metadata_cache_key,
        "composite_season_window_name": composite_metadata_manifest["composite_season_window_name"],
        "tile_size_m": tile_size_m,
        "grid_bounds": grid_bounds,
        "bounds": tile_bounds,
        "x_index": x_index,
        "y_index": y_index,
        "is_valid": (x_index + y_index) % 5 != 0,
        "score_inputs": {
            "target_bands": {
                "B4": round(0.62 + (x_index * 0.04), 6),
                "B8": round(0.71 + (y_index * 0.03), 6),
                "B11": round(0.84 + ((x_index + y_index) * 0.025), 6),
                "B12": round(0.91 + ((x_index * 0.02) + (y_index * 0.015)), 6),
            },
            "baseline_median_bands": {
                "B4": 0.42,
                "B8": 0.5,
                "B11": 0.58,
                "B12": 0.63,
            },
            "baseline_std_bands": {
                "B4": 0.08,
                "B8": 0.1,
                "B11": 0.12,
                "B12": 0.14,
            },
            "valid_season_optical_values": [
                round(1.2 + (x_index * 0.35), 6),
                round(1.6 + (y_index * 0.25), 6),
                round(2.1 + ((x_index + y_index) * 0.2), 6),
                round(2.4 + (y_index * 0.15), 6),
            ],
            "masked_or_invalid_pixel_count": 6 + (((x_index + y_index) % 5) * 3),
            "total_pixel_count": 64,
            "water_edge_overlap_ratio": round(0.1 * ((x_index + y_index) % 4), 6),
            "cloud_seam_overlap_ratio": round(0.05 * ((x_index * 2 + y_index) % 5), 6),
            "compactness_ratio_value": round(0.9 - (0.08 * ((x_index + y_index) % 4)), 6),
            "elongation": round(1.0 + (0.45 * ((x_index * 3 + y_index) % 4)), 6),
        },
    }
    tile_payload["tile_id"] = create_tile_id(tile_payload)
    return tile_payload


def generate_fixed_tile_grid(
    composite_metadata_manifest: dict,
    composite_metadata_cache_key: str,
    *,
    run_id: str | None = None,
    tile_size_m: int = 320,
    width: int = 4,
    height: int = 5,
    grid_bounds: list[float] | None = None,
) -> list[dict]:
    resolved_grid_bounds = grid_bounds or [0.0, 0.0, float(width * tile_size_m), float(height * tile_size_m)]
    min_x, min_y, max_x, max_y = resolved_grid_bounds
    tile_span_x = (max_x - min_x) / max(1, width)
    tile_span_y = (max_y - min_y) / max(1, height)
    tiles = [
        build_tile_feature_input(
            composite_metadata_manifest,
            composite_metadata_cache_key,
            run_id=run_id,
            x_index=x_index,
            y_index=y_index,
            tile_size_m=tile_size_m,
            grid_bounds=resolved_grid_bounds,
            tile_bounds=[
                round(min_x + (x_index * tile_span_x), 6),
                round(min_y + (y_index * tile_span_y), 6),
                round(min_x + ((x_index + 1) * tile_span_x), 6),
                round(min_y + ((y_index + 1) * tile_span_y), 6),
            ],
        )
        for y_index in range(height)
        for x_index in range(width)
    ]
    return sorted(tiles, key=lambda tile: tile["tile_id"])


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def compute_optical_anomaly(
    target_bands: dict[str, float],
    baseline_median_bands: dict[str, float],
    baseline_std_bands: dict[str, float],
) -> float:
    band_names = sorted(
        set(target_bands) & set(baseline_median_bands) & set(baseline_std_bands)
    )
    if not band_names:
        return 0.0

    z_deviations = []
    for band_name in band_names:
        std_value = baseline_std_bands[band_name]
        if std_value <= 0:
            continue
        z_deviations.append(
            abs(target_bands[band_name] - baseline_median_bands[band_name]) / std_value
        )

    if not z_deviations:
        return 0.0

    mean_absolute_z_deviation = sum(z_deviations) / len(z_deviations)
    return round(_clamp(mean_absolute_z_deviation * 10.0, 0.0, 40.0), 6)


def compute_persistence(valid_season_optical_values: list[float]) -> float:
    if not valid_season_optical_values:
        return 0.0
    hit_count = sum(1 for value in valid_season_optical_values if value >= 2.0)
    hit_ratio = hit_count / len(valid_season_optical_values)
    return round(_clamp(25.0 * hit_ratio, 0.0, 25.0), 6)


def compute_cloud_penalty(
    masked_or_invalid_pixel_count: int,
    total_pixel_count: int,
) -> float:
    if total_pixel_count <= 0:
        return -30.0

    invalid_ratio = _clamp(masked_or_invalid_pixel_count / total_pixel_count, 0.0, 1.0)
    return round(_clamp(-30.0 * invalid_ratio, -30.0, 0.0), 6)


def compute_noise_penalty(
    water_edge_overlap_ratio: float,
    cloud_seam_overlap_ratio: float,
    compactness_ratio_value: float,
    elongation: float,
) -> float:
    normalized_water_edge = _clamp(water_edge_overlap_ratio, 0.0, 1.0)
    normalized_cloud_seam = _clamp(cloud_seam_overlap_ratio, 0.0, 1.0)
    linear_artifact_flag = (
        1.0
        if compactness_ratio_value < 0.10 and elongation > 6.0
        else 0.0
    )
    raw_penalty = (
        15.0 * normalized_water_edge
        + 10.0 * normalized_cloud_seam
        + 5.0 * linear_artifact_flag
    )
    return round(_clamp(-raw_penalty, -30.0, 0.0), 6)


def compute_tile_score(
    optical_anomaly: float,
    persistence: float,
    cloud_penalty: float,
    noise_penalty: float,
) -> float:
    return round(_clamp(optical_anomaly + persistence + cloud_penalty + noise_penalty, 0.0, 100.0), 6)


def score_retained_tile(tile_feature_input: dict) -> dict:
    score_inputs = tile_feature_input["score_inputs"]
    optical_anomaly = compute_optical_anomaly(
        score_inputs["target_bands"],
        score_inputs["baseline_median_bands"],
        score_inputs["baseline_std_bands"],
    )
    persistence = compute_persistence(score_inputs["valid_season_optical_values"])
    cloud_penalty = compute_cloud_penalty(
        score_inputs["masked_or_invalid_pixel_count"],
        score_inputs["total_pixel_count"],
    )
    noise_penalty = compute_noise_penalty(
        score_inputs["water_edge_overlap_ratio"],
        score_inputs["cloud_seam_overlap_ratio"],
        score_inputs["compactness_ratio_value"],
        score_inputs["elongation"],
    )
    tile_score = compute_tile_score(
        optical_anomaly,
        persistence,
        cloud_penalty,
        noise_penalty,
    )
    return {
        "tile_id": tile_feature_input["tile_id"],
        "source_scene_manifest_hash": tile_feature_input["source_scene_manifest_hash"],
        "source_endpoint_id": tile_feature_input["source_endpoint_id"],
        "composite_metadata_cache_key": tile_feature_input["composite_metadata_cache_key"],
        "tile_feature_input_cache_key": tile_feature_input["tile_feature_input_cache_key"],
        "is_valid": tile_feature_input["is_valid"],
        "optical_anomaly": optical_anomaly,
        "persistence": persistence,
        "cloud_penalty": cloud_penalty,
        "noise_penalty": noise_penalty,
        "tile_score": tile_score,
        "selected_for_polygonization": False,
    }


def flag_top_valid_tiles(tile_records: list[dict]) -> list[dict]:
    valid_tiles = [tile for tile in tile_records if tile["is_valid"]]
    selected_count = 0 if not valid_tiles else max(1, math.ceil(len(valid_tiles) * 0.15))
    ranked_valid = sorted(
        valid_tiles,
        key=lambda tile: (-tile["tile_score"], tile["tile_id"]),
    )
    selected_ids = {tile["tile_id"] for tile in ranked_valid[:selected_count]}

    flagged_tiles = []
    for tile in tile_records:
        updated = dict(tile)
        updated["selected_for_polygonization"] = tile["tile_id"] in selected_ids
        flagged_tiles.append(updated)
    return flagged_tiles
