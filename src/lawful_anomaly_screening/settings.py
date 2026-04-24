from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_runtime_path(env_var: str, default_relative_path: str) -> Path:
    configured_path = Path(os.getenv(env_var, default_relative_path))
    if configured_path.is_absolute():
        return configured_path
    return REPO_ROOT / configured_path


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
    preprocessing_config_path: Path = field(
        default_factory=lambda: _resolve_runtime_path(
            "LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH",
            "config/sources/preprocessing.json",
        )
    )


def load_settings() -> Settings:
    return Settings()
