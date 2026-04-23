from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("LAWFUL_ANOMALY_DB_PATH", "data/sqlite/lawful_anomaly_screening.sqlite3"))
    baseline_path: Path = Path(os.getenv("LAWFUL_ANOMALY_BASELINE_PATH", "config/baselines/baseline_v1_5_default.json"))
    logging_config_path: Path = Path(os.getenv("LAWFUL_ANOMALY_LOGGING_CONFIG", "config/logging/logging.yaml"))
    export_precision_path: Path = Path(os.getenv("LAWFUL_ANOMALY_EXPORT_PRECISION_PATH", "config/exports/precision_tiers.json"))


def load_settings() -> Settings:
    return Settings()
