from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent


def _resolve_runtime_path(env_var: str, default_relative_path: str) -> Path:
    if env_path := os.getenv(env_var):
        return Path(env_path)
    return PACKAGE_ROOT / default_relative_path


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("LAWFUL_ANOMALY_DB_PATH", "data/sqlite/lawful_anomaly_screening.sqlite3")
        )
    )
    baseline_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_BASELINE_PATH",
            "config/baselines/baseline_v1_5_default.json",
        )
    )
    logging_config_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_LOGGING_CONFIG",
            "config/logging/logging.yaml",
        )
    )
    export_precision_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_EXPORT_PRECISION_PATH",
            "config/exports/precision_tiers.json",
        )
    )
    endpoints_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_ENDPOINTS_PATH",
            "config/sources/endpoints.json",
        )
    )
    geofence_policy_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_GEOFENCE_POLICY_PATH",
            "config/legal/geofence_policy.json",
        )
    )
    preprocessing_config_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH",
            "config/sources/preprocessing.json",
        )
    )


def load_settings() -> Settings:
    return Settings()
