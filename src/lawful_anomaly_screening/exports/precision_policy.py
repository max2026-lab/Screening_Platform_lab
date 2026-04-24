from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from lawful_anomaly_screening.exceptions import ExportPolicyError
from lawful_anomaly_screening.settings import load_settings

EXPORT_TIER_ALIASES = {
    "report/pdf": "report_pdf",
    "report-pdf": "report_pdf",
}

REVIEWER_ONLY_AUDIENCES = {"reviewer", "internal"}


@dataclass(frozen=True)
class ExportPolicy:
    audience: str
    precision_tier: str
    exact_coordinates_included: bool
    coordinate_resolution_m: int | None
    artifact_name_resolution_m: int | None
    allow_exact_artifact_coordinates: bool


def load_precision_tiers() -> dict[str, dict]:
    path = load_settings().export_precision_path
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_export_tier(audience: str) -> str:
    normalized = audience.strip().lower().replace(" ", "_")
    return EXPORT_TIER_ALIASES.get(normalized, normalized)


def _resolution_from_config(config: dict, precision_tier: str, key: str) -> int | None:
    if f"{key}_by_precision" in config:
        value = config[f"{key}_by_precision"][precision_tier]
    else:
        value = config.get(key)
    if value in (None, 0):
        return None
    return int(value)


def resolve_export_policy(audience: str, requested_precision: str | None = None) -> ExportPolicy:
    tiers = load_precision_tiers()
    normalized_audience = normalize_export_tier(audience)
    if normalized_audience not in tiers:
        raise ExportPolicyError(f"unsupported export audience: {audience}")

    config = tiers[normalized_audience]
    configured_precision = config["precision"]
    if configured_precision == "configurable":
        precision_tier = requested_precision or config.get("default_precision", "restricted")
        allowed_values = set(config.get("allowed_precision_values", []))
        if precision_tier not in allowed_values:
            raise ExportPolicyError(
                f"unsupported precision {precision_tier} for audience {normalized_audience}"
            )
    else:
        precision_tier = configured_precision
        if requested_precision is not None and requested_precision != precision_tier:
            raise ExportPolicyError(
                f"unsupported precision {requested_precision} for audience {normalized_audience}"
            )

    exact_coordinates_included = precision_tier == "exact" and bool(
        config["allow_exact_coordinates"]
    )
    if precision_tier == "exact" and not exact_coordinates_included:
        raise ExportPolicyError(f"exact coordinates are not allowed for audience {normalized_audience}")

    return ExportPolicy(
        audience=normalized_audience,
        precision_tier=precision_tier,
        exact_coordinates_included=exact_coordinates_included,
        coordinate_resolution_m=_resolution_from_config(
            config,
            precision_tier,
            "coordinate_resolution_m",
        ),
        artifact_name_resolution_m=_resolution_from_config(
            config,
            precision_tier,
            "artifact_name_resolution_m",
        ),
        allow_exact_artifact_coordinates=normalized_audience in REVIEWER_ONLY_AUDIENCES
        and exact_coordinates_included,
    )


def allow_exact_coordinates(audience: str, requested_precision: str | None = None) -> bool:
    return resolve_export_policy(audience, requested_precision).exact_coordinates_included


def redacted_for_public() -> bool:
    return not allow_exact_coordinates("public")


def _snap_value(value: float, resolution_m: int | None) -> float:
    if resolution_m is None:
        return float(value)
    return float(round(value / resolution_m) * resolution_m)


def apply_precision_to_centroid(
    centroid: list[float],
    audience: str,
    requested_precision: str | None = None,
) -> list[float]:
    policy = resolve_export_policy(audience, requested_precision)
    return [_snap_value(centroid[0], policy.coordinate_resolution_m), _snap_value(centroid[1], policy.coordinate_resolution_m)]


def apply_precision_to_bounds(
    bounds: list[float],
    audience: str,
    requested_precision: str | None = None,
) -> list[float]:
    policy = resolve_export_policy(audience, requested_precision)
    return [_snap_value(value, policy.coordinate_resolution_m) for value in bounds]


def sanitize_candidate_for_export(
    candidate: dict,
    audience: str,
    requested_precision: str | None = None,
) -> dict:
    sanitized = dict(candidate)
    if "centroid" in sanitized:
        sanitized["centroid"] = apply_precision_to_centroid(
            list(sanitized["centroid"]),
            audience,
            requested_precision,
        )
    if "bounds" in sanitized:
        sanitized["bounds"] = apply_precision_to_bounds(
            list(sanitized["bounds"]),
            audience,
            requested_precision,
        )
    return sanitized


def sanitize_candidates_for_export(
    candidates: list[dict],
    audience: str,
    requested_precision: str | None = None,
) -> list[dict]:
    return [
        sanitize_candidate_for_export(candidate, audience, requested_precision)
        for candidate in sorted(candidates, key=lambda item: item["candidate_id"])
    ]


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "-", value.strip().lower()).strip("-")


def build_location_token(
    centroid: list[float],
    audience: str,
    requested_precision: str | None = None,
) -> str:
    policy = resolve_export_policy(audience, requested_precision)
    resolution_m = None
    if not policy.allow_exact_artifact_coordinates:
        resolution_m = policy.artifact_name_resolution_m
    snapped_x = int(round(_snap_value(centroid[0], resolution_m)))
    snapped_y = int(round(_snap_value(centroid[1], resolution_m)))
    return f"e{snapped_x}_n{snapped_y}"


def build_artifact_name(
    *,
    run_id: str,
    audience: str,
    artifact_kind: str,
    centroid: list[float] | None = None,
    requested_precision: str | None = None,
    extension: str,
) -> str:
    normalized_audience = normalize_export_tier(audience)
    policy = resolve_export_policy(normalized_audience, requested_precision)
    parts = [_slugify(run_id), _slugify(normalized_audience), _slugify(artifact_kind), policy.precision_tier]
    if centroid is not None:
        parts.append(build_location_token(centroid, normalized_audience, requested_precision))
    return f"{'-'.join(parts)}.{extension}"


def build_bundle_name(
    *,
    run_id: str,
    audience: str,
    artifact_kind: str,
    centroid: list[float] | None = None,
    requested_precision: str | None = None,
) -> str:
    return build_artifact_name(
        run_id=run_id,
        audience=audience,
        artifact_kind=artifact_kind,
        centroid=centroid,
        requested_precision=requested_precision,
        extension="zip",
    )


def export_subdirectory(audience: str) -> Path:
    normalized_audience = normalize_export_tier(audience)
    if normalized_audience == "report_pdf":
        return Path("exports/reports")
    return Path("exports") / normalized_audience
