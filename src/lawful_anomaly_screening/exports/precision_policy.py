from __future__ import annotations

import json

from lawful_anomaly_screening.settings import load_settings

EXPORT_TIER_ALIASES = {
    "report/pdf": "report_pdf",
    "report-pdf": "report_pdf",
}


def load_precision_tiers() -> dict[str, dict]:
    path = load_settings().export_precision_path
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_export_tier(audience: str) -> str:
    normalized = audience.strip().lower().replace(" ", "_")
    return EXPORT_TIER_ALIASES.get(normalized, normalized)


def allow_exact_coordinates(audience: str) -> bool:
    tiers = load_precision_tiers()
    tier_name = normalize_export_tier(audience)
    return bool(tiers[tier_name]["allow_exact_coordinates"])


def redacted_for_public() -> bool:
    return not allow_exact_coordinates("public")
